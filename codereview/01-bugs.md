# 01 — Concrete Bugs

Format: **Severity** · location · problem · fix.

## 1. `os` not imported in the bridge — High (verified)
[bridge.py:124](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L124) evaluates `self.mqtt_config.client_name or os.environ.get("HOSTNAME") or ...`.
The module imports `json, logging, Path, threading, time` but not `os`.
When `client_name` is empty or `None`, `start()` raises `NameError` while holding `self._lock`, after `_running = True` was set. A retry then returns early because `_running` is already `True`, so the bridge is dead until restart.
`run.sh` always fills in `client_name`, which hides this in the add-on. It will hit anyone running the CLI with a bare config.
**Fix:** add `import os`. Also set `_running = True` only after a successful start, or reset it in an `except`.

## 2. MQTT startup failure aborts the whole client — High (verified by reading)
[mqtt.py:177-184](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mqtt.py#L177-L184) calls the blocking `connect()` after `loop_start()` with no `try`.
If the internal broker or tunnel is not ready, `ConnectionRefusedError` propagates out of `PwrcellClient._start_live_mode`. Modbus polling, discovery and the UI never start.
`self.__mqttc` is already assigned, so a second `start()` returns early.
`bridge.py` handles this correctly with a `try` around `connect()`.
**Fix:** use `connect_async()` plus `reconnect_delay_set()`, or wrap `connect()` and let paho's loop retry.

## 3. Zero values are skipped and stale values persist — Medium/High (verified)
[state.py ~1550](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1546-L1560) uses `if ch.voltage_v:`. The same pattern appears for other channel fields: `if ch.exported_energy_ws is not None and ch.exported_energy_ws > 0`, `if snapshot.inverter_state:` and `if snapshot.inverter_id:`.
During a grid outage the NET voltage is legitimately `0.0`. It is never written, so HA keeps showing about 240 V.
The `energy > 0` guards are intentional against protobuf default zeros, but they also hide real resets.
**Fix:** proto3 scalars cannot distinguish "unset" from `0`. Declare the fields `optional` in the .proto (`HasField`), or treat a channel's absence as "no data" and its presence as authoritative.

## 4. `devices.yaml` is persisted to an ephemeral path in the add-on — High for add-on users (verified)
`AppConfig.write` special-cases `/data`, but `DeviceConfig.write`/`read` use `_getConfigPath("devices.yaml")`.
In the add-on that resolves to `/data/devices.yaml` only if it already exists. Otherwise it falls through to `/app/config/devices.yaml` inside the container image.
Result: the scan is repeated, and the 1..100 scan can take a long time (see 02 §5), after every add-on update or rebuild.
Also, once a `devices.yaml` exists it is never revalidated. A new PV Link, a changed slave ID or a replaced device is ignored forever. See 03 §6.
**Fix:** one `data_dir()` helper used by every writer: devices, ha_config, published topics, mappings, SunSpec cache.

## 5. `DeviceConfig.read` return type and error handling — Low (verified)
[config.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/config.py): `read()` is annotated `-> DeviceConfig` but returns `None`. It only catches `FileNotFoundError`, so a malformed YAML crashes startup.
`AppConfig.read` does the opposite and swallows every exception into `AppConfig()` defaults.
With defaults, `pwrcell is None`, so the next failure is `AttributeError: 'NoneType' has no attribute 'ssh_tunnel'`, far from the real cause. The default `testing=True` is also surprising.
**Fix:** fail loudly on a malformed file and use defaults only when the file is absent. Return `Optional[DeviceConfig]`.

## 6. Version strings disagree — Low (verified)
`__init__.py` has `3.0.11`, `config.yaml` has `3.0.10`, and `ha.py` `ORIGIN_INFO["sw_version"]` has `3.0.10`.
**Fix:** read the version once from `__version__`.

## 7. Missing `List` import — Low (verified)
[client.py:19](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/client.py#L19) imports `Generator, Optional` and uses `List` in annotations. It works only because of `from __future__ import annotations`; type checkers will flag it.

## 8. `unhashable` risk in sentinel checks — Low (suspected)
[state.py:1868, 1885](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1868) do `raw_val not in SUNSPEC_SENTINELS` on whatever the caller passed. For a `list` or `dict`, set membership raises `TypeError`.
Today `raw_val` is an int/float/str, but the fixtures/mock path passes `scaled_value` objects. Guard with `isinstance(raw_val, (int, float))`.

## 9. `_save_scanned_devices` classifies by substring — Medium (verified)
[client.py:419](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/client.py#L412-L431) uses `"Inverter" in md`, `"Battery" in md`, `"Beacon" in md`, then `"PV" in md`. Anything else becomes `icm`, including unknown or new devices.
Any model name containing "PV" (for example a PV-related inverter variant) is misclassified, and the first matching branch wins.
It also writes `devices.yaml` even if `discovered` is empty.
`_load_from_device_config` later invents `model_name = dev_type.title()`.
**Fix:** classify by the SunSpec model IDs the device exposes (for example 64251/64252/64200/102), and refuse to persist an empty scan.

## 10. Write "verification" does not verify — Medium (verified)
[modbus.py:413-430](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/modbus.py#L405-L436): the docstring says "verify by re-reading", but it only returns `point.cvalue` after the re-read. It never compares against the requested value.
Callers (`controls.py`) then store the requested value (`display_val`) in the state store, not the read-back value.
If the device clamps or rejects the value, the UI and HA show the wrong state until the next poll.
**Fix:** compare, log a warning on mismatch, and publish the read-back value.

## 11. Writable scaled registers truncate decimals and mis-scale on write — High (verified)
[catalog.py:434-456](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L434-L456) (`SunspecPointDef.validate_and_convert`) does not accept or use `sf_value` at all. For every integer register type (`uint16`, `int16`, `uint32`, `int32`), it casts `int(float(input_val))` and checks raw unscaled register limits (`0..65535` or `-32768..32767`).
Then [controls.py:239](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/controls.py#L239) passes that `raw_val` to `modbus_client.write_point_value(..., value=raw_val)`, where [modbus.py:426](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/modbus.py#L426) assigns `point.cvalue = value` (which `pysunspec2` divides by $10^{\text{sf}}$ when computing raw register `point.value`).
- If a user writes `50.5` to a scaled writable register (e.g. `WMaxLim_Pct` with `SF=-1`), `validate_and_convert` truncates `50.5` to `int(50)`.
- Worse, [catalog.py:831-839](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L831-L839) (`derive_ha_metadata`) hardcodes arbitrary `min_value` (`1.0` or `0.0`), `max_value` (`3600.0`, `100.0`, or `10000.0`), and `step=1.0` based only on whether `units == "s"` or `"%"`, ignoring the register's actual type bounds and scale factor.
**Fix:** pass `sf_value` into `validate_and_convert` (or validate in scaled engineering units and let `pysunspec2`'s `point.cvalue` apply the scale factor), and derive HA `min`/`max`/`step` from `StateField.get_bounds()`.

## 12. `format_state_value` published values — Low (verified)
[bridge.py:43-73](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L43-L73):
- `"nan"` is published for NaN/inf. HA numeric sensors log a `ValueError` for that payload.
- `""` is published when a value is a sentinel. This is the same problem and is only reached via values that bypass `validate_field_value`.
- A string containing the letter `e` (`"Active"`, `"Offline"`) goes through `float(value)` inside a `try/except ValueError`. Such strings only avoid breaking because they fail to parse. A state like `"1e5"` becomes `"100000"`.
**Fix:** return `None` and skip the publish (or publish `"None"`, which HA treats as unknown) instead of `""` or `"nan"`. Do not reinterpret strings.

## 13. `ssh_pkey` / key file written then chmod — Low (verified)
[setup_key.py:55-59](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/setup_key.py#L55-L59) writes the private key with the default umask and then calls `os.chmod(0o600)`. There is a brief window where the file is readable. Use `os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`.

## 14. `QueueEmpty` loop and trigger de-dup — Low (verified)
`poller._worker_loop` drains `_pending_triggers` into a `set`, so repeated triggers collapse. That is fine.
Trigger tiers that are not valid (`"foo"`) are accepted by `trigger_sync` and the UI endpoint, and only log a warning later in `poll_tier`. Validate at the entry point.

## 15. `CANONICAL_SYNONYMS` swaps Grid Imported and Exported energy — High (verified)
In [optimizer.py:138-155](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/optimizer.py#L138-L155):
- `"grid_imported_energy"` defines `"names": {"grid_imported_energy_wh", "totwhexp"}` (`TotWhExp` is Total Watt-Hours **Exported**).
- `"grid_exported_energy"` defines `"names": {"whout", "grid_exported_energy_wh", "totwhimp"}` (`TotWhImp` is Total Watt-Hours **Imported**).
Grouping `totwhexp` under `grid_imported_energy` and `totwhimp` under `grid_exported_energy` swaps imported and exported SunSpec energy registers in unified concept groups.
**Fix:** move `"totwhimp"` to `"grid_imported_energy"` and `"totwhexp"` to `"grid_exported_energy"`.

## 16. Protobuf vs. SunSpec `SAFETY_SHUTDOWN` enum value mismatch — High (verified)
In `energy_record_set_pb2.SystemMode`, `UNKNOWN_SYSTEM_MODE = 0`, `GRID_TIE = 1`, `SELF_SUPPLY = 2`, `CLEAN_BACKUP = 3`, `PRIORITY_BACKUP = 4`, `REMOTE_ARBITRAGE = 5`, `SELL = 6`, and **`SAFETY_SHUTDOWN = 16`**.
In SunSpec Model 64200 (`smdx_64200.xml`) and [controls.py:21-33](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/controls.py#L21-L33) (`OPERATING_MODES`), **`SAFETY_SHUTDOWN = 0`** (there is no `UNKNOWN` at 0 in Model 64200).
Several bugs stem from conflating or mis-defining these two enums:
1. [correlator.py:574-577](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/correlator.py#L574-L577) translates a raw integer Modbus `SysMd` (`mb_val`) using `from .mqtt import SYSTEM_MODE_NAMES`. When Modbus `SysMd == 0` (`SAFETY_SHUTDOWN`), `SYSTEM_MODE_NAMES.get(0)` translates it to `"UNKNOWN"`, masking a safety shutdown!
2. [mqtt.py:93-102](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mqtt.py#L93-L102) has a fallback `SYSTEM_MODE_NAMES` dictionary with completely wrong integer values (`1: "CLEAN_BACKUP", 2: "GRID_TIE", 3: "SELF_SUPPLY", 7: "SAFETY_SHUTDOWN"`), and [fixtures.py:263-265](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/fixtures.py#L263-L265) falls back to `3` for `SELF_SUPPLY` (which is `CLEAN_BACKUP` in the real proto).
3. [ui/server.py:101](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/server.py#L101) builds `inv_modes = {v: k for k, v in OPERATING_MODES.items()}`. Because `OPERATING_MODES` has duplicate integer values for aliases (`1: GRID_TIE` and `1: GRID_CONNECT`, `5: REMOTE_ARBITRAGE` and `5: ARBITRAGE`, `6: SELL` and `6: FULL_EXPORT`), the comprehension overwrites the first keys with the aliases.
**Fix:** keep `PROTO_SYSTEM_MODES` and `SUNSPEC_SYS_MD` explicitly separate, remove the broken fallback dict in `mqtt.py`, and use SunSpec `SysMd` symbols when decoding Modbus `SysMd`.

## 17. Module-level mapping caches in `state.py` and `correlator.py` never update on `reload()` — Medium (verified)
[state.py:145-146](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L145-L146) binds `MODBUS_TO_MQTT_MAPPING = get_active_modbus_to_mqtt_mapping()` and `RAW_TO_COMPOUND_MAPPING = get_active_raw_to_compound_mapping()` **once at import time**. Similarly, [correlator.py:92](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/correlator.py#L92) binds `KNOWN_TELEMETRY_MAPPINGS = _load_correlator_mappings()` once at import time.
When the user saves new mappings in the UI (`POST /api/mappings`, [ui/server.py:342](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/server.py#L342)), `reg.reload()` updates `MappingRegistry._instance`, **but `state.py` and `correlator.py` keep using the stale module-level dicts** until the process is restarted.
Additionally, `save_mappings()` ([mapping.py:354-365](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mapping.py#L354-L365)) writes directly to `pwrcell/data/telemetry_mappings.yaml` inside the package directory, which is ephemeral in the Docker container image (`/app/pwrcell/data/`).
**Fix:** query `MappingRegistry.get_instance()` dynamically instead of caching dicts at module import time, and store user-modified mappings in `/data/`.

## 18. Unreachable `NaN == NaN` check in `StateStore.set_field` and misleading test — Low (verified)
[state.py:1123-1128](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1123-L1128) checks `if isinstance(existing.value, float) and isinstance(value, float): if math.isnan(existing.value) and math.isnan(value): is_val_equal = True`.
However, earlier in `set_field` ([state.py:1067](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1067)), `value = validate_field_value(value, ...)` has already run, and `validate_field_value` ([state.py:52-53](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L52-L53)) converts `float("nan")` to `None`!
Thus `value` can never be `NaN` at line 1123—the `NaN` equality branch is dead code, while `existing.raw_value` retains `float("nan")` because `if raw_value is None and value is not None:` ran *before* `validate_field_value`. The unit test `test_nan_equality_does_not_loop_notifications` ([tests/test_state_and_controls.py:272-298](file:///Users/edalquist/projects/pwrcell_sunspec/tests/test_state_and_controls.py#L272-L298)) passes only because `None == None`.
**Fix:** remove the dead `math.isnan` branch in `set_field` (since `StateStore` normalizes invalid/NaN values to `None` at ingress), and also normalize `raw_value` when `raw_value` is `NaN`.
