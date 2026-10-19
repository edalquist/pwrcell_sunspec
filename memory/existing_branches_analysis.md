# PWRCell Integration: Detailed Analysis of Existing Branches

## 1. System Overview & Generac PWRcell Architecture

The Generac PWRcell is a hybrid residential solar + storage system structured around a proprietary 380V DC bus known as the **REbus**. Multiple devices communicate across and coordinate on this bus:
- **PWRcell Inverter (e.g., X7602 / X11402)**: The central inverter managing grid connection, local AC loads, and DC-to-AC conversion. It exposes extensive status, metering (CTs), operating mode control, and grid reconnect parameters.
- **PWRcell Battery (B-Link / EX / DCB)**: High-voltage DC-coupled battery modules. Exposes state of charge (SoC), state of health (SoH), energy in/out counters, cell/stack temperatures, voltage, current, and charge/discharge limits.
- **PV Links (Substring Combiners / S2502)**: DC-DC optimizers combining solar strings into the REbus. Expose string voltage, current, power, accumulated energy, and string status.
- **REbus Beacon**: Gateway and coordinator communicating with the system. Controls high-level system operating mode (Clean Backup, Priority Backup, Self Supply, Grid Tie, Safety Shutdown) and network configuration.
- **ICM (Inverter Control Module)**: Internal supervisory controller.

Communication with the PWRcell occurs over two interfaces exposed on the internal controller (accessible via Ethernet or SSH tunnel):
1. **SunSpec Modbus TCP (Port 502)**: The industry-standard register-based protocol, augmented with Generac/Pika proprietary models (model IDs in 64xxx series and 8xx series).
2. **Internal MQTT Broker (Port 1883)**: An internal message broker used by the Generac firmware that publishes real-time telemetry encoded in Protocol Buffers (protobuf) messages on topics like `.../energy_recordset_live`.

---

## 2. Analysis of Branch: `main` (Original Implementation)

### 2.1 Code Structure
The `main` branch consists of:
- `pwrcell.py`: Core client class `GeneracPwrCell` wrapping `sunspec2.modbus.client`.
- `homeassistant.py`: Class `PwrCellHA` publishing Home Assistant MQTT Discovery configs and state updates to an external broker.
- `main.py`: Entry point running an infinite polling loop (`gpc.read()` followed by `pwrcell_ha.loop()`).
- `scan.py`: Standalone script to discover device slave IDs by scanning IDs 1..100.
- `watch.py`: CLI monitor for real-time terminal output.
- `config.example.yaml`: Static configuration containing SSH tunnel settings and fixed slave IDs.

### 2.2 Critical Flaws & Concurrency Deadlocks
1. **Thread Pool Contention over a Single Serial Gateway**:
   In `pwrcell.py`, a `ThreadPoolExecutor` is created:
   ```python
   self.__executor = concurrent.futures.ThreadPoolExecutor(
       thread_name_prefix='ModBusPool', max_workers=(len(self.__devices) * 2))
   ```
   During polling, `self.__read()` dispatches `self.__do_read_points()` across devices concurrently:
   ```python
   for device, points in points.items():
       futures_to_devices[self.__do_read_points(device, points)] = device
   for future in concurrent.futures.as_completed(futures_to_devices):
       ...
   ```
   **The root failure:** The Generac controller's Modbus TCP server (and the underlying serial RS485 bridge to REbus devices) is strictly single-threaded and cannot process simultaneous Modbus TCP transactions. When multiple worker threads hit port 502 simultaneously:
   - Packet collisions occur on the controller socket.
   - Sockets time out or receive `Modbus exception 11` (Gateway Target Device Failed to Respond).
   - Frames get corrupted or misaligned across threads.

2. **Cascading Reconnection Storms**:
   In `pwrcell.py`'s `__read_points`:
   ```python
   except Exception as e:
       logging.warning("Error reading %s on try %s: %s", device.name, t, e)
       self.__connect_device(device, tries=tries, reconnect=True)
   ```
   When one thread times out, it forcefully reconnects. Concurrently, other threads encounter timeouts and also attempt reconnects. The device gateway becomes saturated with reconnect handshakes, leading to an unrecoverable deadlock where `as_completed()` hangs forever.

3. **High-Latency Point-by-Point Reads**:
   Each watched field performs an individual `point.read()` transaction rather than batching registers into a single `model.read()`. With ~50 monitored fields across 8 devices, each polling cycle generates 50+ individual Modbus round-trips over the SSH tunnel, causing latency spikes and high timeout probability.

### 2.3 Home Assistant Mapping Challenges
- **Cryptic Register Identifiers**: Register names such as `CTPow`, `SysMd`, `Px1`, `Px2`, `AHRtg`, `WHRtg`, `DCW`, `DCWh`, and `St` were hardcoded into `homeassistant.py`.
- **Hardcoded Sensor Set**: Adding or removing an entity required writing Python code in `homeassistant.py`.
- **Scale Factor Fragility**: Different firmware versions (e.g. PV Link `634_13700` vs older) had bugged or missing scale factor points (`DCW_SF`), requiring manual hacks like `string_combiner.DCW.sf_value = -1`.
- **Lack of Observability**: Users could not see which fields had real data, which were static constants, and which actually changed during solar generation or battery discharge.

---

## 3. Analysis of Branch: `v2` (Modernization & Telemetry Discovery)

### 3.1 Modularization & Architectural Upgrades
Branch `v2` refactored the monolith into a clean Python package under `pwrcell/`:
- `pwrcell/client.py`: High-level entry point `create_client()` context manager bundling tunnel, SunSpec client, and MQTT client.
- `pwrcell/tunnel.py`: `sshtunnel` manager that forwards both port 502 (Modbus) and port 1883 (internal MQTT) to dynamic local ports.
- `pwrcell/models.py`: Automated model downloader using Paramiko/SCP to check `/opt/pika/sunspec-models/version` on the unit and cache JSON definitions locally.
- `pwrcell/config.py`: Structured dataclasses using `dataconf` (`AppConfig`, `DeviceConfig`, `SshTunnel`, `MqttConfig`).
- `pwrcell/sunspec.py`: Device auto-discovery scanning slave IDs 1..100, verifying serial numbers, and persisting discovery state to `devices.yaml`.
- `pwrcell/mqtt.py`: Internal MQTT client listening to `#` and decoding `/energy_recordset_live` protobuf messages.
- `pwrcell/protos/`: Extracted `.proto` definitions (`energy_record_set.proto`, `base.proto`, etc.) and generated Python protobuf bindings.
- `pwrcell/http_api.py` (uncommitted): Preliminary Flask API providing `/api/devices` and device JSON endpoints.

### 3.2 Key Discoveries in `v2`
1. **The Internal MQTT Telemetry Stream (`EnergyRecordSet`)**:
   The Generac unit natively pushes high-frequency, push-based energy records over internal MQTT.
   Every update contains:
   - Global timestamp and inverter state
   - `SystemMode` (GRID_TIE, SELF_SUPPLY, CLEAN_BACKUP, PRIORITY_BACKUP, etc.)
   - Per-channel metrics (`ChannelSample`):
     - `channelType`: NET, GENERATION, CONSUMPTION, STORAGE, INVERTER_OUTPUT
     - `realPower_W` / `realPower_Wf`: Instantaneous wattage
     - `importedEnergy_Ws` & `exportedEnergy_Ws`: High-resolution watt-second accumulators
     - `soc` (State of Charge %) & `soh` (State of Health %)
     - `voltage_V` & `reactivePower_VAR`
     - Device ID & device type
   **Significance**: This push stream eliminates the need to poll Modbus for live power, energy, and SoC, drastically reducing Modbus bus traffic!

2. **SunSpec Model Metadata in JSON (`sunspec-models/json/`)**:
   Every custom model (e.g. 64207, 64208, 64209, 802, etc.) includes full human-readable labels, descriptions, units, types, enum symbol maps, and access permissions (`R` vs `RW`).

### 3.3 What `v2` Leaves Unfinished
- **No Unified State Engine**: Modbus and MQTT data exist in completely isolated classes without cross-referencing or merging.
- **Modbus Concurrency Not Yet Solved**: `pwrcell/sunspec.py` still creates independent device objects and does not serialize Modbus transactions or provide a thread-safe read/write queue.
- **No Interactive Web UI**: `http_api.py` only returned raw dictionaries via Flask; there was no frontend explorer, real-time streaming, or Home Assistant entity selector.
- **Home Assistant Bridge Detached**: `homeassistant.py` was not updated to consume the new `v2` modular client or the push MQTT telemetry.

---

## 4. Comparison Matrix: `main` vs `v2` vs Planned `v3`

| Feature | `main` | `v2` | Planned `v3` |
| :--- | :--- | :--- | :--- |
| **Modbus Concurrency** | Concurrent threads (deadlocks & hangs) | Single-threaded scan, uncoordinated reads | Dedicated serialized queue / worker with mutex & backoff |
| **Modbus Read Strategy** | Point-by-point reads (`point.read()`) | Model scans during init, ad-hoc point reads | Block/model reads (`model.read()`) with register caching |
| **Internal MQTT Push** | None | Raw listener for `/energy_recordset_live` | Integrated push stream merged with device state store |
| **Model Synchronization**| Static zip file | SCP download from `/opt/pika` | Local cache + fallback to bundled definitions + SCP sync |
| **Device Discovery** | Static config or standalone scan | Auto-scan + `devices.yaml` caching | Auto-scan + persistent registry + serial verification |
| **Data Model** | Raw SunSpec points | Raw SunSpec dicts & raw protobufs | Unified Device Hierarchy (`Inverter`, `Battery`, `PVLink`) |
| **Field Metadata** | Hardcoded abbreviations | Unused JSON files | Dynamic metamodel (label, desc, units, R/RW, HA hints) |
| **Web Explorer UI** | None | Embryonic Flask API (`/api/devices`) | Modern interactive Web UI with live streaming & HA picker |
| **Home Assistant Integration**| Hardcoded monolithic publisher | Broken/unintegrated | Flexible, selective MQTT Discovery from user config |
| **Offline Testing** | None | Static JSON dumps in `model_dump/` | Mock simulator engine using `model_dump/` & proto fixtures |
