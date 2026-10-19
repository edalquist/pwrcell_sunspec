# PWRCell v3 Design Document

## 1. Executive Summary & Goals

The goal of **PWRCell v3** is to provide a robust, production-grade Python client library and an interactive companion web UI for the Generac PWRcell solar and storage system. 

### Core Goals:
1. **Eliminate Concurrency Deadlocks**: Provide a strictly serialized, resilient Modbus communication engine with connection reuse, exponential backoff, and block reads.
2. **Unified Hybrid Data Engine**: Seamlessly marry high-frequency push telemetry from the internal MQTT broker (`/energy_recordset_live` protobuf) with deep register inspection and writable configuration from SunSpec Modbus.
3. **Rich Field Metamodel & HA Semantic Catalog**: Automatically extract human-readable labels, descriptions, units, types, and access controls from SunSpec model definitions and provide sensible Home Assistant entity suggestions (`sensor`, `binary_sensor`, `select`, `number`).
4. **Interactive Companion Web UI Explorer**: Deliver a lightweight, browser-based explorer to inspect discovered devices, monitor real-time values as they stream, preview Home Assistant MQTT Discovery payloads, and select exactly which entities to expose.
5. **Offline Simulator & Fixture Engine**: Enable comprehensive testing and UI preview without requiring a live connection to an inverter, leveraging `model_dump/` and recorded protobuf fixtures.

---

## 2. System Architecture

```
                                  Generac PWRcell Unit
                      ┌───────────────────────────────────────────┐
                      │  Port 502 (Modbus)   Port 1883 (MQTT)    │
                      └─────────────┬──────────────────────┬──────┘
                                    │                      │
                               SSH Tunnel (pwrcell.tunnel)
                                    │                      │
                      ┌─────────────▼──────────────────────▼──────┐
                      │                PWRCell v3 Core            │
                      │                                           │
                      │  ┌──────────────────┐ ┌────────────────┐  │
                      │  │ Serialized Modbus│ │ Internal MQTT  │  │
                      │  │ Engine (Queue)   │ │ Push Receiver  │  │
                      │  └────────┬─────────┘ └───────┬────────┘  │
                      │           │                   │           │
                      │  ┌────────▼───────────────────▼────────┐  │
                      │  │        Unified State Store          │  │
                      │  │  Inverter, Battery, PVLinks, Beacon │  │
                      │  └──────────────────┬──────────────────┘  │
                      │                     │                     │
                      │  ┌──────────────────▼──────────────────┐  │
                      │  │      Field Metamodel & HA Hints     │  │
                      │  └──────────────────┬──────────────────┘  │
                      └─────────────────────┼─────────────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
       ┌───────────────────────────┐                 ┌───────────────────────────┐
       │   Companion Web Explorer  │                 │   Home Assistant Agent    │
       │ - FastAPI/Flask Web UI    │                 │ - MQTT Discovery Pub      │
       │ - Real-Time Feed (SSE)    │                 │ - Selective HA Exporter   │
       │ - Entity Selector & Config│                 │ - Bidirectional Commands  │
       └───────────────────────────┘                 └───────────────────────────┘
```

---

## 3. Core Subsystems

### 3.1 Serialized Modbus Engine (`pwrcell.core.modbus`)
* **Problem Solved**: Modbus TCP requests to the PWRcell over RS485/REbus gateways must never overlap.
* **Architecture**:
  * A single, dedicated I/O worker thread and a thread-safe request queue (or async queue).
  * All Modbus operations (`read_model`, `read_point`, `write_point`, `scan_device`) are enqueued as request jobs returning futures.
  * **Block Reads**: Instead of reading points individually, `read_model()` fetches whole SunSpec model blocks, caching register values in memory.
  * **Resilient Connection Lifecycle**:
    * Maintains a persistent single connection.
    * Transparent exponential backoff on transient errors (e.g., Modbus error 11 or socket timeouts).
    * Guaranteed timeout budgets (max 5s per request, max 3 retries).

### 3.2 Internal Push MQTT Telemetry Engine (`pwrcell.core.mqtt`)
* **Problem Solved**: High-frequency metrics (instantaneous power, battery SoC, energy accumulators) need real-time updates without polling Modbus.
* **Architecture**:
  * Paho MQTT client connected to the forwarded port 1883 over the SSH tunnel.
  * Automatic subscription to `#` with specialized handling for `/energy_recordset_live`.
  * Protobuf decoder extracting `EnergyRecordSet`:
    * System Mode & Inverter State.
    * Channel samples: NET, GENERATION, CONSUMPTION, STORAGE, INVERTER_OUTPUT.
    * Battery SoC, SoH, and voltage.
    * Energy accumulators (imported / exported watt-seconds converted to kWh).
  * Direct ingestion into the Unified State Store with update notifications dispatched to listeners.

### 3.3 Unified Device State Store (`pwrcell.state`)
* **Device Abstractions**:
  * `Device`: Base class holding metadata (`serial_number`, `model_name`, `manufacturer`, `firmware_version`, `slave_id`).
  * `InverterDevice`: System operating mode, CT power, grid/load power, AC frequency, voltage, inverter status bitfields.
  * `BatteryDevice`: SoC, SoH, power, current, voltage, temperature, energy in/out, max charge/discharge rates.
  * `PVLinkDevice`: String power, string voltage, string current, accumulated watt-hours, status.
  * `RebusBeaconDevice`: System operating mode command, REbus status.
  * `ICMDevice`: Internal controller telemetry.
* **Field Representation (`StateField`)**:
  * `key`: Fully-qualified identifier (e.g., `inverter.inverter_status.CTPow`, `battery.live.soc`).
  * `label`: Human-readable label (e.g., "Current Transformer Power", "State of Charge").
  * `description`: Comprehensive explanation.
  * `value`: Current parsed value.
  * `raw_value`: Raw register value before scaling or enum translation.
  * `units`: Canonical unit string (`W`, `Wh`, `V`, `A`, `%`, `°C`).
  * `source`: `SourceType.MQTT_PUSH`, `SourceType.MODBUS_POLL`, `SourceType.MODBUS_CONFIG`, or `SourceType.COMPUTED`.
  * `access`: `Access.READ_ONLY` or `Access.READ_WRITE`.
  * `symbols`: Enum options map `{name: value}` for select controls.
  * `ha_hint`: Recommended Home Assistant entity metadata (`platform`, `device_class`, `state_class`).
  * `last_updated`: Timestamp of last value change.

### 3.4 Metamodel & SunSpec Model Catalog (`pwrcell.catalog`)
* Reads model JSON definitions from `sunspec-models/json/` (or SCP cache).
* Indexes all models by ID (e.g., 1, 64207, 64208, 64209, 802).
* Dynamically extracts:
  * Point descriptions, labels, units, types (`enum16`, `bitfield16`, `acc32`, etc.).
  * Scale factor bindings (e.g., `V` bound to `VT_sf`).
  * Firmware-specific quirks (e.g., PV Link scale factor adjustments).
* Provides an automatic Home Assistant recommendation rule engine:
  * Power (`W`, `kW`) &rarr; `sensor`, `device_class: power`, `state_class: measurement`
  * Energy (`Wh`, `kWh`) &rarr; `sensor`, `device_class: energy`, `state_class: total_increasing`
  * Percentage (`%`, `%WHRtg`) &rarr; `sensor`, `device_class: battery`, `unit: %`
  * Voltage (`V`) &rarr; `sensor`, `device_class: voltage`
  * Read-Write Enum &rarr; `select`
  * Read-Write Numeric &rarr; `number`

### 3.5 Writable Controls & Command Dispatcher (`pwrcell.controls`)
* Thread-safe dispatch of control commands to the serialized Modbus worker:
  * `set_system_mode(mode: SystemMode)`: Updates `rebus_beacon` and `inverter` operating mode registers.
  * `set_min_reserve(percent: int)`: Configures minimum battery reserve for backup.
  * `write_register(device_id, model_id, point_name, value)`: Generic register modification.
* Immediately invalidates and re-reads the modified model block to verify that the value was applied and update the State Store.

---

## 4. Companion Web Explorer UI (`pwrcell.ui`)

### 4.1 Architecture
* Built-in lightweight web server using Flask (or FastAPI).
* Packaged as an executable module: `python -m pwrcell.ui` or CLI command `pwrcell explore`.
* Single-page reactive application using modern HTML5, CSS, and clean vanilla JavaScript (zero heavy build steps, zero npm dependency chain).

### 4.2 Key Features & Pages
1. **Device Tree View**:
   * Sidebar listing all discovered devices with badges for online status, serial number, and firmware version.
   * Device summary card showing manufacturer, model, slave ID, and communication health.
2. **Interactive Field Explorer**:
   * Searchable and filterable table of all fields on the selected device.
   * Columns: Expose (Checkbox), Label, Key, Source (`MQTT` badge vs `Modbus` badge), Type (`Sensor` / `Select` / `Number`), Current Value (live update!), Units, Description tooltip.
   * Inline controls: For writable fields (like `SysMd`), allow the user to test changing values directly from the UI.
3. **Real-Time Live Streaming (SSE / Server-Sent Events)**:
   * Endpoint `/api/stream`: Streams JSON events whenever fields update.
   * Highlights changing values with a subtle flash effect in the browser.
4. **Home Assistant Entity Configuration & Export**:
   * Toggle checkboxes to select which fields to expose to Home Assistant.
   * "Select Recommended Defaults" button to auto-select standard power, energy, battery SoC, and mode controls.
   * Live preview drawer showing the exact Home Assistant MQTT Discovery JSON payloads.
   * "Save Configuration" button to write selections to `ha_config.yaml`.
5. **Simulator / Mock Mode Toggle**:
   * If live hardware is unavailable, run with `--mock` to load data from `model_dump/` and replay simulated MQTT telemetry.

---

## 5. Home Assistant Integration (`pwrcell.homeassistant`)

* Reads user selections from `ha_config.yaml` (configured via the Web UI).
* Connects to external Home Assistant MQTT broker.
* Publishes Home Assistant MQTT Discovery payloads to `<discovery_prefix>/<component>/<node_id>/<object_id>/config`.
* Subscribes to command topics for writable entities (`select` and `number`) and delegates commands to the PWRcell Control Dispatcher.
* Publishes state updates efficiently whenever fields in the State Store change.
