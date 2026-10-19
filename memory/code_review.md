# Comprehensive Code Review: PWRcell SunSpec (v3)

**Date**: October 2026  
**Scope**: Full codebase review of `pwrcell/`, `main.py`, configuration loaders, and companion services.  
**Focus**: 
1. **Correctness** (SunSpec protocol compliance, math/scaling, HA MQTT discovery contract, data integrity)
2. **Long-Term Execution Stability** (24/7 daemon durability, deadlocks, connection recovery, memory/resource leaks, thread safety)
3. **Readability & Maintainability** (Code structure, typing, error handling, logging, duplication)

---

## 1. Executive Summary

The PWRcell v3 architecture represents a substantial architectural leap forward over v2. The transition to a unified State Store, serialized Modbus worker queue, internal push MQTT telemetry decoding, and dynamic Home Assistant discovery provides a modern, maintainable foundation.

However, a rigorous inspection of the codebase reveals several **critical correctness bugs** (such as SunSpec sentinel corruption, duplicate serial scan aborts, and Home Assistant MQTT discovery schema violations) and **severe execution stability risks** (such as memory leaks in Server-Sent Events, dictionary iteration race conditions across threads, lock contention during tunnel reconnects, and blocking Modbus writes within Paho MQTT network callbacks).

If left unaddressed, these issues will cause crashes, silent data corruption, or system lockups when deployed as a continuous background daemon or Home Assistant add-on.

---

## 2. Correctness Issues (Primary Concern)

### 2.1 SunSpec Unimplemented Sentinel Value Corruption
* **File**: [`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1168-L1186)
* **Severity**: **Critical**
* **Root Cause**:
  In the SunSpec standard, unimplemented or invalid registers return sentinel values:
  - `int16`: `0x8000` (`-32768`)
  - `uint16`: `0xFFFF` (`65535`)
  - `int32`: `0x80000000` (`-2147483648`)
  - `uint32`: `0xFFFFFFFF` (`4294967295`)
  - `sunssf` (scale factor): `0x8000` (`-32768`)

  When pysunspec2 encounters these sentinels during a block read, it evaluates `p.cvalue = None`.
  However, `update_from_modbus_points()` in `state.py` has a fallback:
  ```python
  if computed_values and pt_name in computed_values and computed_values[pt_name] is not None:
      scaled_val = computed_values[pt_name]
  elif isinstance(raw_val, (int, float)) and pt_def and pt_def.sf:
      sf = ...
      scaled_val = round(raw_val * (10 ** sf), ...)
  ```
  If `computed_values[pt_name]` is `None` (because pysunspec2 correctly identified the sentinel), the code falls into `elif` and multiplies the raw sentinel (e.g. `-32768` or `65535`) by the scale factor!
* **Impact**:
  Unimplemented registers are published to Home Assistant and Web UI as valid values (e.g. `-3276.8 W` or `6553.5 V`) rather than `None` or `unavailable`.
* **Remediation**:
  Check for standard SunSpec sentinels or verify `if computed_values and pt_name in computed_values:`—if pysunspec2 evaluated `cvalue` as `None`, do not apply a raw scale factor fallback; keep `scaled_val = None`.

---

### 2.2 Premature Device Scan Abort on Duplicate/Missing Serial Number
* **File**: [`pwrcell/modbus.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/modbus.py#L326-L340)
* **Severity**: **High**
* **Root Cause**:
  In `scan_range()`:
  ```python
  sn = str(dev.common[0].SN.value).strip() if hasattr(dev, "common") else ""
  if sn:
      ids = found_serials.setdefault(sn, [])
      ids.append(slave_id)
      if len(ids) > 1 and stop_on_duplicate_serial:
          logger.info("Found duplicate serial %s at ID %d, stopping scan", sn, slave_id)
          break
  ```
  If `dev.common[0].SN.value` is `None` (due to an uncommissioned device or transient register read failure), `str(None).strip()` returns `"None"`.
  Because `"None"` is truthy, it is added to `found_serials["None"]`. When a second device without a serial number is read, `len(ids) > 1` triggers, and the scan **aborts prematurely**, missing any subsequent valid devices (e.g., PV Links or Batteries at higher slave IDs).
* **Remediation**:
  Validate `sn` explicitly:
  ```python
  raw_sn = dev.common[0].SN.value if hasattr(dev, "common") else None
  sn = str(raw_sn).strip() if raw_sn is not None else ""
  if sn and sn != "None":
      ...
  ```

---

### 2.3 Home Assistant MQTT Discovery Payload Schema Violations
* **File**: [`pwrcell/ha.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ha.py#L193-L217)
* **Severity**: **High**
* **Root Cause**:
  1. **Missing `options` on `sensor` with `device_class: enum`**:
     In Home Assistant 2023.1+, sensors configured with `device_class: enum` **require** the `options` key in their MQTT discovery payload. In `ha.py`:
     ```python
     if platform == "select" and hint.options:
         payload["options"] = hint.options
         payload["command_topic"] = command_topic
     ```
     `payload["options"]` is only populated when `platform == "select"`. For read-only enum sensors (e.g. Inverter State, System Status), `platform == "sensor"` and `device_class == "enum"`, but `options` is omitted. Home Assistant logs an invalid schema warning and ignores the entity.
  2. **Missing `options` on `CompoundFieldView` for `select`**:
     For compound fields (like `system_mode`), lines 193–201 do not copy `ha_options` into `payload["options"]`, causing Home Assistant to reject the `select` entity discovery payload.
* **Remediation**:
  Update `generate_discovery_payload()` to always include `options` if provided whenever `platform == "select"` OR `device_class == "enum"`, both for raw `StateField` and `CompoundFieldView`.

---

### 2.4 Literal String `"None"` Published to Home Assistant State Topics
* **File**: [`pwrcell/bridge.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L230)
* **Severity**: **Medium**
* **Root Cause**:
  In `_publish_field_state()`:
  ```python
  self._mqttc.publish(state_topic, str(field.value), retain=retain)
  ```
  If `field.value` is `None` (e.g., a sensor that has not yet reported or is currently offline), `str(None)` publishes the literal ASCII text `"None"`.
  When Home Assistant receives `"None"` on a numeric sensor (`device_class: power`, `energy`, `voltage`, etc.), HA logs repeated tracebacks:
  `ValueError: could not convert string to float: 'None'`.
* **Remediation**:
  If `field.value is None`, either publish an empty string `""` (which Home Assistant interprets as state cleared/unknown) or skip publishing state until a valid value is recorded.

---

### 2.5 Battery 0% SoC Masked as `None` in MQTT Telemetry Decoding
* **File**: [`pwrcell/mqtt.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mqtt.py#L317)
* **Severity**: **Medium**
* **Root Cause**:
  In `_parse_snapshot()`:
  ```python
  soc_val = float(ch.soc) if (ch.deviceType == energy_record_set_pb2.BATTERY or ch.soc != 0) else None
  ```
  If a battery is fully depleted to `0.0%`, and the protobuf `deviceType` field is `0` (or if it is an AC-coupled storage channel where `deviceType != BATTERY`), `(ch.deviceType == BATTERY or ch.soc != 0)` evaluates to `False`. The valid `0.0` SoC reading is replaced with `None`.
* **Remediation**:
  Check channel type directly:
  ```python
  is_storage = (ch.channelType in (energy_record_set_pb2.STORAGE, energy_record_set_pb2.STORAGE_AC) or ch.deviceType == energy_record_set_pb2.BATTERY)
  soc_val = float(ch.soc) if is_storage else (float(ch.soc) if ch.soc != 0 else None)
  ```

---

### 2.6 Floating Point `NaN` Causing Infinite Event Storms
* **File**: [`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L637)
* **Severity**: **Medium**
* **Root Cause**:
  In `set_field()`:
  ```python
  changed = (existing.value != value)
  ```
  In Python, `float('nan') != float('nan')` is always `True`. If a corrupted Modbus register or sensor returns `NaN`, every polling cycle evaluates `changed = True`, triggering listeners, SSE queue broadcasts, and MQTT discovery/state republishing on every single tick.
* **Remediation**:
  Normalize `math.isnan()`:
  ```python
  if isinstance(existing.value, float) and isinstance(value, float) and math.isnan(existing.value) and math.isnan(value):
      changed = False
  else:
      changed = (existing.value != value)
  ```

---

### 2.7 Fragile Path Resolution via `sys.path[0]`
* **File**: [`pwrcell/config.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/config.py#L29), [`pwrcell/models.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/models.py#L20)
* **Severity**: **Medium**
* **Root Cause**:
  ```python
  base = Path(sys.path[0])
  ```
  When the application is run via systemd, an entrypoint script, or `python -m pwrcell.cli`, `sys.path[0]` can be an empty string `""`, `/usr/local/bin`, or the directory of an arbitrary runner script rather than the project root.
* **Remediation**:
  Use `Path(__file__).resolve().parent.parent` (or an explicit configuration directory argument / environment variable `PWRCELL_ROOT`).

---

### 2.8 Missing Parent Directory Creation in SCP Model Sync
* **File**: [`pwrcell/models.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/models.py#L32-L46)
* **Severity**: **Low**
* **Root Cause**:
  `remote_version_file = sunspec_models_dir / 'version.chk'`
  `scp.get('/opt/pika/sunspec-models/version', remote_version_file)`
  If `sunspec_models_dir` does not exist on a fresh installation, `scp.get()` fails because the parent directory does not exist.
* **Remediation**:
  Call `sunspec_models_dir.mkdir(parents=True, exist_ok=True)` prior to invoking `scp.get()`.

---

## 3. Long-Term Execution Stability & 24/7 Durability (Primary Concern)

### 3.1 Memory Leak in SSE Stream Queues on Client Disconnect
* **File**: [`pwrcell/ui/server.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/server.py#L285-L304)
* **Severity**: **Critical**
* **Root Cause**:
  In `sse_stream()`:
  ```python
  client_queue: queue.Queue = queue.Queue(maxsize=100)
  with sse_lock:
      sse_queues.append(client_queue)

  def event_generator():
      try:
          ...
      except GeneratorExit:
          with sse_lock:
              if client_queue in sse_queues:
                  sse_queues.remove(client_queue)
  ```
  When a browser tab closes or a network disconnect occurs, WSGI servers (Werkzeug, Gunicorn, uWSGI) often raise `BrokenPipeError`, `ConnectionResetError`, or terminate the generator without raising `GeneratorExit`.
  Because cleanup is inside `except GeneratorExit:`, any abnormal socket drop bypasses queue removal!
  The disconnected client's queue remains in `sse_queues` permanently. As state updates occur, `on_field_change()` continues putting events into the orphaned queue, filling up memory over days and weeks.
* **Remediation**:
  Use a `finally:` block:
  ```python
  def event_generator():
      try:
          yield f"data: {json.dumps({'type': 'connected'})}\n\n"
          while True:
              try:
                  event_data = client_queue.get(timeout=15.0)
                  yield f"data: {json.dumps(event_data)}\n\n"
              except queue.Empty:
                  yield ": keepalive\n\n"
      finally:
          with sse_lock:
              if client_queue in sse_queues:
                  sse_queues.remove(client_queue)
  ```

---

### 3.2 Race Condition: `RuntimeError: dictionary changed size during iteration`
* **File**: [`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L384-L402), [`pwrcell/poller.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/poller.py#L151)
* **Severity**: **Critical**
* **Root Cause**:
  In `StateStore.find_fields()`:
  ```python
  matched: List[StateField] = []
  for dev in self.devices.values():
      if key in dev.fields:
          matched.append(dev.fields[key])
  ...
  for f_key, f_obj in dev.fields.items():
      ...
  ```
  `find_fields()` does **not** acquire `self._lock`!
  Simultaneously, the MQTT push receiver thread and the Modbus polling thread call `set_field()`, which mutates `dev.fields` (`dev.fields[key] = field_obj`).
  When `find_fields()` is invoked (from the Web UI thread during `/api/compare`, `/api/devices`, or `/api/stream`), concurrent mutation of `dev.fields` triggers:
  `RuntimeError: dictionary changed size during iteration`.
  This crashes Web UI requests and comparison monitors.
* **Remediation**:
  Enclose `find_fields` in `with self._lock:` or create a snapshot copy `list(dev.fields.values())` inside `self._lock`.

---

### 3.3 Blocking Modbus Operations Inside Paho MQTT Network Loop
* **File**: [`pwrcell/bridge.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L271-L289)
* **Severity**: **High**
* **Root Cause**:
  When Home Assistant issues a command (e.g. changing system operating mode), Paho MQTT invokes `_on_message()` on its internal networking thread:
  ```python
  def _on_message(self, client, userdata, msg):
      ...
      confirmed_val = self.client.controls.write_field(target_field.key, payload_str)
  ```
  `write_field()` submits a synchronous Modbus job (`execute_sync()`) which communicates across the SSH tunnel and RS-485 bus, retrying up to 3 times with exponential backoff (timeout up to 30 seconds).
  While this occurs, **Paho MQTT's networking thread is completely frozen**. It cannot send `PINGREQ` heartbeats or process incoming packets. If the Modbus write takes more than 1.5x the keepalive interval (or if the bus is busy), the external MQTT broker drops the client for a missed heartbeat, triggering reconnection storms.
* **Remediation**:
  Offload command execution to a background worker thread or thread pool:
  ```python
  def _on_message(self, client, userdata, msg):
      topic = msg.topic
      payload = msg.payload.decode("utf-8").strip()
      threading.Thread(
          target=self._handle_command_async,
          args=(topic, payload),
          daemon=True,
      ).start()
  ```

---

### 3.4 Lock Contention & Unresponsive Shutdown in SSH Tunnel Watchdog
* **File**: [`pwrcell/tunnel.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/tunnel.py#L117-L145)
* **Severity**: **High**
* **Root Cause**:
  `ensure_active()` acquires `self._lock` and calls `_reconnect_locked()`.
  Inside `_reconnect_locked()`:
  - Sleeps 0.5s.
  - Loops 3 times, attempting `_start_server_locked()` and sleeping `1.0 * attempt` seconds.
  - Paramiko's SSH connection timeout default can take 10–30 seconds per attempt.
  All of this occurs while **holding `self._lock`**.
  If network transport drops:
  - Any thread calling `tunnel.is_active` or `tunnel.stop()` blocks for up to 30–90 seconds.
  - Signal handlers (SIGINT/SIGTERM) cannot stop the process cleanly, causing supervisor timeouts and `kill -9` termination.
* **Remediation**:
  Do not hold `self._lock` across socket connection establishment and sleep delays. Use a dedicated reconnection lock or state flag (`self._reconnecting`).

---

### 3.5 Tunnel Port Invalidation on Reconnect
* **File**: [`pwrcell/tunnel.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/tunnel.py#L80-L107), [`pwrcell/client.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/client.py#L374-L380)
* **Severity**: **High**
* **Root Cause**:
  If the SSH tunnel drops and reconnects, `_start_server_locked()` attempts to bind to `self.modbus_port` and `self.mqtt_port`.
  However, if the operating system has placed those local ports in `TIME_WAIT` (or if port allocation failed), `SSHTunnelForwarder` selects new ephemeral ports.
  `self.modbus_port` and `self.mqtt_port` in `PwrCellTunnel` change, but:
  - `SerializedModbusClient` holds `self.port` passed at initialization.
  - `MqttClient` holds `self.__tunnel_port` passed at initialization.
  Neither client is updated with the new ports! They will continuously attempt to connect to the dead, closed local port forever.
* **Remediation**:
  Have `SerializedModbusClient` and `MqttClient` dynamically query `self.tunnel.modbus_port` / `self.tunnel.mqtt_port` rather than storing immutable integers, or trigger a full client transport rebind on tunnel reconnection.

---

### 3.6 Worker Thread Shutdown Queue Stranding
* **File**: [`pwrcell/modbus.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/modbus.py#L79-L87), [`pwrcell/modbus.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/modbus.py#L123-L131)
* **Severity**: **Medium**
* **Root Cause**:
  In `SerializedModbusWorker.stop()`:
  ```python
  self._running = False
  self._queue.put(None)
  ```
  In `_worker_loop()`:
  ```python
  while self._running:
      try:
          job = self._queue.get(timeout=1.0)
      except queue.Empty:
          continue
      if job is None:
          break
  ```
  If `self._running` is set to `False` while jobs are in the queue, the `while self._running:` loop condition terminates immediately on the next timeout tick without draining remaining jobs. Any caller blocked on `future.result()` will hang until their timeout expires instead of receiving a clean `CancelledError` or `RuntimeError("Worker shutting down")`.
* **Remediation**:
  Use `while True:` and rely strictly on the `None` sentinel to break the loop, or cancel all remaining pending futures in the queue on shutdown.

---

### 3.7 Permanent Deadlock on Initial Device Discovery Failure
* **File**: [`pwrcell/client.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/client.py#L293-L303), [`pwrcell/poller.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/poller.py#L151)
* **Severity**: **Medium**
* **Root Cause**:
  When `client.start()` runs in live mode:
  If `devices.yaml` does not exist, it runs `scan_range(1, 100)`.
  If the inverter is rebooting or the Modbus link is temporarily down during startup, `scan_range()` discovers 0 devices.
  `devices.yaml` is saved as empty.
  The client proceeds to launch `TieredModbusPoller`.
  In `TieredModbusPoller.poll_tier()`:
  `devices = list(self.client.state.devices.values())`
  Because `devices` is empty, the poller loops continuously doing nothing. **It never attempts to rediscover devices.** The service remains permanently dead until manually restarted.
* **Remediation**:
  In `TieredModbusPoller`, if `len(self.client.state.devices) == 0`, schedule periodic discovery retry attempts (e.g. every 60 seconds) until devices are discovered.

---

### 3.8 Unbounded Memory Growth in Unrecognized MQTT Topics
* **File**: [`pwrcell/mqtt.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mqtt.py#L276-L278)
* **Severity**: **Low**
* **Root Cause**:
  The internal MQTT client subscribes to `#`.
  For every topic not matching `/energy_recordset_live`:
  ```python
  with self.__lock:
      self.__unrecognized_topics[msg.topic] = len(msg.payload)
  ```
  If firmware logs or debugging topics contain timestamps, sequence IDs, or high-cardinality keys, `__unrecognized_topics` grows without bound.
* **Remediation**:
  Cap `__unrecognized_topics` to a maximum size (e.g. 500 keys) using `collections.OrderedDict` or an eviction policy.

---

### 3.9 Thread Storms on MQTT Disconnection
* **File**: [`pwrcell/mqtt.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mqtt.py#L236-L240)
* **Severity**: **Low**
* **Root Cause**:
  `__mqtt_disconnect` spawns an unbounded thread on *every* disconnect:
  ```python
  threading.Thread(target=self.__tunnel_manager.ensure_active, daemon=True).start()
  ```
  If the broker is restarting or the tunnel is down, Paho MQTT reconnects and disconnects rapidly. Each event spawns a new thread that stacks up attempting to acquire `tunnel._lock`.
* **Remediation**:
  Use a single debounced event or check if a reconnect task is already active before spawning a new thread.

---

### 3.10 Missing Listener Unsubscription in State Store
* **File**: [`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L554-L558), [`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1246-L1250)
* **Severity**: **Low**
* **Root Cause**:
  `StateStore` provides `subscribe()` and `subscribe_compound()`, but no `unsubscribe()` or `unsubscribe_compound()`. If components or test cases register listeners and are later recreated, the old callbacks remain in memory and continue executing on every state change.
* **Remediation**:
  Add `unsubscribe(listener)` and `unsubscribe_compound(listener)`.

---

## 4. Readability, Architecture & Code Organization

### 4.1 Redundant Code Across Subsystems
- **Field Lookup Duplication**:
  `_find_field()` and `_find_fields()` logic is duplicated in both `pwrcell/state.py` (lines 381–408) and `pwrcell/correlator.py` (lines 384–402). Suffix-matching and device-matching logic should be unified directly on `StateStore`.
- **System Mode Mappings**:
  `OPERATING_MODES` is declared in `controls.py`, `SYSTEM_MODE_NAMES` is declared in `mqtt.py`, and SunSpec model 64200 symbols are parsed in `catalog.py`. These mappings should be centralized in an authoritative enum or mapping module.

### 4.2 Logging Standards & Error Masking
- In `pwrcell/poller.py` line 194:
  `logger.debug("Failed reading model %s on slave %d (%s): %s", model_id, slave_id, serial_number, e)`
  Persistent Modbus read failures on critical models (such as Inverter or Battery) are logged only at `DEBUG` level. In production, users running at `INFO` will have no visibility into why battery SoC or power values are not updating.
  Failed reads should log at `WARNING` when error thresholds are exceeded.
- In `pwrcell/modbus.py` line 256:
  Empty `except Exception: pass` when disconnecting sockets can obscure underlying OS resource leaks.

### 4.3 Dataclass Design & Typing Inconsistencies
- In `pwrcell/mqtt.py` line 74:
  `channels: Dict[int, ChannelTelemetry] = None`
  Dataclasses should use `field(default_factory=dict)` or `Optional[Dict[...]] = None` to avoid typing and runtime bugs.
- `c_view: Any` in `state.py` line 570 should be typed as `CompoundFieldView`.

---

## 5. Prioritized Remediation Roadmap

| Priority | Issue | Component | Recommended Action |
| :--- | :--- | :--- | :--- |
| **P0** | SunSpec Sentinel Value Corruption | `state.py` | Prevent scale factor fallback when SunSpec `cvalue` is `None`. |
| **P0** | SSE Stream Memory Leak | `ui/server.py` | Ensure SSE queue removal runs in `finally:` block. |
| **P0** | Dict Iteration Race Condition | `state.py` | Synchronize `find_fields()` with `self._lock`. |
| **P1** | Duplicate Serial Scan Abort | `modbus.py` | Ignore `None` serials when checking for duplicate devices. |
| **P1** | HA MQTT Discovery Enum/Select `options` | `ha.py` | Always include `options` for `platform: select` and `device_class: enum`. |
| **P1** | Literal `"None"` State Topic Payload | `bridge.py` | Publish empty payload `""` or skip publishing when value is `None`. |
| **P1** | Blocking Modbus in Paho MQTT Loop | `bridge.py` | Offload command execution in `_on_message` to a worker thread. |
| **P1** | Tunnel Watchdog Lock Contention | `tunnel.py` | Release `_lock` during sleep and SSH connection attempts. |
| **P1** | Port Invalidation on Tunnel Reconnect | `tunnel.py`, `client.py` | Dynamically resolve ports from tunnel manager. |
| **P2** | Initial Discovery Failure Recovery | `client.py`, `poller.py` | Add periodic device rediscovery when 0 devices are known. |
| **P2** | 0% SoC Masked as `None` | `mqtt.py` | Check `channelType` for storage channels rather than non-zero value. |
| **P2** | `sys.path[0]` Fragility | `config.py`, `models.py` | Use `__file__` based project root resolution. |
| **P2** | StateStore Unsubscribe Methods | `state.py` | Add `unsubscribe()` and `unsubscribe_compound()`. |
