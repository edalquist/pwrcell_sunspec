# Code Review Summary — pwrcell_sunspec

Scope: `pwrcell/` (≈14k LOC), `main.py`, `rootfs/run.sh`, `config.yaml`, `Dockerfile`, and `tests/`. Focus: complexity and hidden-bug / edge-case risk.
Method: full static read-through of all modules in `pwrcell/` (`modbus.py`, `client.py`, `poller.py`, `mqtt.py`, `bridge.py`, `ha.py`, `controls.py`, `tunnel.py`, `config.py`, `models.py`, `cli.py`, `state.py`, `ui/server.py`, `optimizer.py`, `correlator.py`, `catalog.py`, `grouping.py`, `mapping.py`, `recommender.py`, `fixtures.py`, `clean_discovery.py`) plus `run.sh` and the test suite (`tests/`).
All 119 unit tests were executed via `.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v` (119 passed in 33.85s).

> The existing `memory/code_review.md` is an earlier review. This one is independent and may overlap with it.

## Files
| File | Contents |
|---|---|
| [01-bugs.md](01-bugs.md) | Concrete defects. Most are small fixes. |
| [02-modbus-sunspec.md](02-modbus-sunspec.md) | Modbus and SunSpec correctness and edge cases. |
| [03-concurrency-robustness.md](03-concurrency-robustness.md) | Threading, startup/shutdown, reconnects, stale data. |
| [04-homeassistant-security.md](04-homeassistant-security.md) | HA discovery/MQTT behaviour and security of the write paths. |
| [05-complexity.md](05-complexity.md) | Complexity hotspots, overlapping abstractions, and test suite findings. |

## Top 12 priorities
1. **Unauthenticated Modbus write API.** `POST /api/fields/write` on `0.0.0.0:5555` can set `SysMd`, including `SAFETY_SHUTDOWN`. See 04 §1.
2. **`NameError` in the bridge (missed by tests).** `bridge.py:124` uses `os` without importing it, so the bridge crashes whenever `mqtt.client_name` is empty (`test_bridge.py` never calls `bridge.start()`). See 01 §1.
3. **Swapped Grid Imported vs. Exported energy synonyms.** `optimizer.py:138-155` groups `totwhexp` (Total Wh *Exported*) into `grid_imported_energy` and `totwhimp` (Total Wh *Imported*) into `grid_exported_energy`. See 01 §15.
4. **Protobuf vs. SunSpec `SAFETY_SHUTDOWN` enum mismatch (`16` vs `0`).** In Protobuf `0` is `UNKNOWN_SYSTEM_MODE` and `16` is `SAFETY_SHUTDOWN`, whereas in SunSpec Model 64200 `0` is `SAFETY_SHUTDOWN`. `correlator.py:576` maps raw Modbus `0` through MQTT `SYSTEM_MODE_NAMES` to `"UNKNOWN"`, and fallback mode tables in `mqtt.py`/`fixtures.py` have wrong integer values. See 01 §16.
5. **Broken writes and HA metadata for scaled registers.** `SunspecPointDef.validate_and_convert` (`catalog.py:434-456`) ignores `sf_value`, truncating float inputs with `int(float(input_val))` while `modbus.py:426` assigns the unscaled value to `point.cvalue` (which `pysunspec2` divides by $10^{\text{sf}}$). See 01 §11.
6. **Retained command messages are replayed as writes.** The bridge never ignores `msg.retain`. See 04 §3.
7. **Grid voltage `0` is never published.** `if ch.voltage_v:` skips zero, so an outage keeps showing the last good voltage. See 01 §3.
8. **Sentinel filtering ignores point type.** `SUNSPEC_SENTINELS` applies one global set to every point, so legitimate `uint32`/`acc32`/`int32` values such as 32767, 65535 and 65534 are discarded. See 02 §1.
9. **The monotonic-counter guard can latch forever.** One bad high reading suppresses all later correct readings. See 02 §2.
10. **Stale data looks fresh, and runtime mapping reloads don't update `state.py`.** HA availability tracks only the bridge process, and `MODBUS_TO_MQTT_MAPPING` / `RAW_TO_COMPOUND_MAPPING` in `state.py` are cached at import time and never refreshed on `MappingRegistry.reload()`. See 03 §3 and 01 §17.
11. **`devices.yaml` and `telemetry_mappings.yaml` are written outside `/data` in the add-on**, so they are lost on container rebuild. See 01 §4 and 01 §17.
12. **Three overlapping "unified field" systems (`CompoundFieldView`, `UnifiedFieldGroup`, `ComparisonResultRow`)** across `state.py`, `optimizer.py`, `grouping.py`, `correlator.py`, and `recommender.py` (~4.5k LOC total). See 05 §7.

## Overall impression
The architecture is sound. It has a single serialized Modbus worker, a tiered poller, a state store and an HA bridge. Most of the risk comes from three things:
- Defensive code layered on defensive code (`getattr`/`hasattr`/broad `except Exception`, about 156 `getattr`/`hasattr` calls).
- The same logic written several times (scale-factor handling, sentinel handling, mode name maps, serial-prefix matching).
- Business rules hidden in string matching. Examples are unit, name and substring heuristics in `validate_field_value`, and the device-type guess from the model name in `_save_scanned_devices`.

Collapsing these into single sources of truth would remove most of the hidden-bug surface.
