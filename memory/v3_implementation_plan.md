# PWRCell v3 Implementation Plan

## Phase 1: Metamodel Catalog & Mock Fixture Foundation
- [x] **1.1 SunSpec Model Catalog (`pwrcell.catalog`)**:
  - Implement JSON model reader loading models from `sunspec-models/json/`.
  - Extract point definitions: name, label, description, units, scale factor references (`sf`), access (`R`/`RW`), data types (`enum16`, `bitfield16`, `acc32`, `uint16`, `int16`, etc.).
  - Extract enum symbols with integer values, symbolic names, and human-friendly descriptions.
  - Implement Home Assistant metadata derivation rules (`platform`, `device_class`, `state_class`, `unit_of_measurement`).
- [x] **1.2 Mock & Fixture Engine (`pwrcell.fixtures`)**:
  - Implement fixture loader reading device JSON dumps from `model_dump/` (1.json = beacon, 2.json = icm, 3..7.json = pvlinks, 8.json = inverter, 9.json = battery).
  - Implement synthetic `EnergyRecordSet` protobuf generator replaying realistic power, battery SoC, energy accumulators, and mode changes.
  - Enable running the entire client library and Web UI offline in simulated mode.

---

## Phase 2: Core Engines (Serialized Modbus & Push MQTT)
- [x] **2.1 Serialized Modbus Worker (`pwrcell.core.modbus`)**:
  - Implement thread-safe job queue and dedicated single-worker communication thread.
  - Implement block model reads (`read_model()`) to fetch full register sets in a single Modbus transaction.
  - Implement retry with exponential backoff on transient Modbus exception 11 or socket timeouts.
  - Implement safe register writing (`write_point()`) with post-write verification.
  - Wrap slave device scanning (1..100) using the serialized worker.
- [x] **2.2 Internal Push MQTT Telemetry Engine (`pwrcell.core.mqtt`)**:
  - Refactor `pwrcell.mqtt.MqttClient` to safely handle tunnel lifecycle and reconnects.
  - Decode `/energy_recordset_live` protobuf messages into typed channel records and battery telemetry.
  - Expose clean subscription hooks (`on_telemetry_record`).

---

## Phase 3: Unified Device State Store & Controls
- [x] **3.1 Unified State Store (`pwrcell.state`)**:
  - Define `StateField` and device classes: `InverterDevice`, `BatteryDevice`, `PVLinkDevice`, `RebusBeaconDevice`, `ICMDevice`.
  - Merge MQTT push telemetry (high-frequency wattage, SoC, energy deltas) with Modbus-polled configuration and registers.
  - Implement listener pattern for field-level change notifications.
- [x] **3.2 Control Dispatcher (`pwrcell.controls`)**:
  - Implement high-level control APIs:
    - `set_system_mode(mode: str | int)`
    - `set_min_reserve(soc_percent: int)`
    - `write_point(device_id, point_id, value)`
  - Dispatch write operations safely via the serialized Modbus worker.

---

## Phase 4: Companion Web Explorer UI
- [x] **4.1 Web Server & API (`pwrcell.ui.server`)**:
  - Implement lightweight web server (Flask or FastAPI) packaged under `pwrcell.ui`.
  - Endpoints:
    - `GET /api/devices`: Discovered devices with connectivity and serial numbers.
    - `GET /api/devices/<id>/fields`: Full list of fields for a device with metadata, live values, and HA hints.
    - `POST /api/fields/<key>/write`: Test modifying a writable register from the UI.
    - `GET /api/stream`: Server-Sent Events (SSE) pushing field updates in real time.
    - `GET /api/ha/config`: Currently selected Home Assistant entities.
    - `POST /api/ha/config`: Save selected Home Assistant entities to `ha_config.yaml`.
    - `GET /api/ha/preview`: Preview generated MQTT Discovery JSON payloads.
- [x] **4.2 Responsive Frontend Application (`pwrcell.ui.static`)**:
  - Single-page application using modern HTML5, CSS, and vanilla JS.
  - **Sidebar**: Device list with live status badges.
  - **Main View**:
    - Header with connection status and mock mode toggle.
    - Search & category filter (Sensors, Selects, Numbers, MQTT Live vs Modbus).
    - Interactive table with live-updating value badges, units, descriptions, and HA export checkboxes.
  - **HA Export Panel**:
    - Live count of selected entities.
    - Discovery JSON preview modal.
    - "Save to ha_config.yaml" button.
  - **Control Modal**: Quick interface to test changing operating modes or reserve battery levels.

---

## Phase 5: Home Assistant Integration Engine
- [x] **5.1 Dynamic MQTT Discovery Generator (`pwrcell.ha.discovery`)**:
  - Read `ha_config.yaml` to discover which fields the user elected to expose.
  - Construct valid Home Assistant MQTT Discovery payloads for `sensor`, `binary_sensor`, `select`, and `number`.
- [x] **5.2 HA Bridge Daemon (`pwrcell.ha.bridge`)**:
  - Connect to user's external Home Assistant MQTT broker.
  - Publish retained discovery topics on startup.
  - Subscribe to command topics for writable controls (`SysMd`, `ReConn_Tms`, etc.).
  - Publish state updates when values in the State Store change.

---

## Phase 6: CLI, Packaging & Testing
- [x] **6.1 Unified CLI Entrypoint (`pwrcell.cli`)**:
  - `pwrcell explore [--mock] [--port 5555]`: Launch companion Web Explorer.
  - `pwrcell scan`: Scan and print/save device IDs.
  - `pwrcell run`: Run the production Home Assistant bridge daemon.
  - `pwrcell set-mode <MODE>`: Quick CLI tool to set system operating mode.
  - `pwrcell status`: View live status in terminal.
- [x] **6.2 Automated Test Suite (`tests/`)**:
  - Unit tests for Model Catalog parsing and HA hint rules.
  - Unit tests for Serialized Modbus worker queue and block reads.
  - Unit tests for Protobuf `EnergyRecordSet` decoding.
  - Integration tests for State Store and Web UI endpoints using the mock fixture engine.

---

## Phase 7: Telemetry Correlation & Validation Tooling
- [x] **7.1 Modbus-to-MQTT Mapping Engine (`pwrcell.correlator`)**:
  - Static mapping registry linking high-frequency MQTT push fields (Net Power, Battery Power, SoC, SoH, Solar Generation, Modes, Energies, Voltages) to candidate SunSpec Modbus registers.
  - Dynamic evaluation engine calculating real-time deltas, percent matches, and match statuses (`EXACT`, `CLOSE`, `DIVERGENT`, `MISSING`).
- [x] **7.2 Terminal & UI Comparison Tooling**:
  - `python main.py compare [--mock] [--interval 1.0] [--once]`: Live terminal dashboard formatting side-by-side telemetry tables with ANSI colors.
  - Web Explorer UI integration: Added "⚡ Compare Telemetry" modal and `badge-mqtt-linked` badges in the field explorer table.
  - REST endpoint `GET /api/compare` streaming live comparison rows.

