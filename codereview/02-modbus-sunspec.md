# 02 — Modbus / SunSpec correctness and edge cases

## 1. Sentinel handling is type-blind — High (verified)
`SUNSPEC_SENTINELS` ([state.py:19-30](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L19-L30)) is a single flat set of int16, uint16, int32 and uint32 invalid markers. It is applied to:
- raw register values (`update_from_modbus_points`, Case 1)
- scaled values (`validate_field_value`, `safe_point_cvalue`, `format_state_value`, using `int(value)`)
- scale-factor candidates.

The SunSpec "not implemented" value depends on the point type:

| Type | Sentinel |
|---|---|
| `int16` | `0x8000` |
| `uint16` | `0xFFFF` |
| `int32` | `0x80000000` |
| `uint32`, `acc32` | `0xFFFFFFFF` |

Consequences:
- A `uint32`/`acc32` energy counter, or an `int32` power value, that legitimately equals 32767, 32768, 65534 or 65535 is dropped to `None`. Cumulative Wh counters pass through these values as they grow.
- `int(scaled_value)` is compared against the same set, so a scaled value of `32767.4 W` or `65535.0` is also rejected. This is a coincidence-based filter on post-scaling data, which is meaningless.
- `0x7FFF`/`0x7FFE` are not SunSpec sentinels for int16. Rejecting them is vendor folklore.
- Rejecting a *raw* `65535` in a `bitfield16` or `enum16` is wrong. `0xFFFF` is "unimplemented" for those, but all-bits-set is not distinguishable, so check the declared type.
- Meanwhile, [catalog.py:226-234](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L226-L234) defines a separate `sentinels` table (`"acc16": 0x0000, "acc32": 0x00000000, "bitfield16": 0xFFFF, ...`) that disagrees with `SUNSPEC_SENTINELS` in `state.py` (which uses `0xFFFF`/`0xFFFFFFFF` and never checks `0` for accumulators—note also that `0` can be a legitimate brand-new accumulator reading).

**Fix:** decide sentinels from `pt_def.type` (or `point.ptype` from pysunspec2) in one place, at the raw level only. pysunspec2's `point.cvalue` already returns `None` for its own sentinel; trust it instead of re-deriving. Remove the post-scaling `int(val) in SENTINELS` checks.

## 2. Monotonic counter guard can latch permanently — High (verified)
[state.py:1105-1120](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1105-L1120) rejects any new total-increasing value that is more than 10% below the stored one (or `<= 0`) once the existing value exceeds 100.
Failure modes:
- **Latch:** one bad reading that is too high (a glitch, an MQTT value in the wrong unit, a corrupted block) becomes the stored baseline. Every correct later reading is more than 10% below it and is suppressed forever, until restart.
- **Legitimate reset:** a replaced battery, a device reset or a firmware counter rollover is suppressed forever.
- **No signal:** the suppression is only a `logger.warning` on every poll (log spam), and the caller still gets `existing`, so the listener is not notified.
- The heuristic `units in ("Wh","kWh") and not name.endswith("_w")` also catches non-lifetime counters. The code special-cases `pv_link` but may miss other daily/session counters.
- The 10% tolerance also means a small real decrease (anything under 10%) is accepted as a drop.
- `existing.value > 100.0` means the guard is disabled for the first 100 Wh.

**Fix (simplest):** do not clamp in the store. Home Assistant's `total_increasing` state class already handles resets, and treats a decrease as a meter reset. If you want a guard, require N consecutive consistent lower readings before accepting, and log once.

## 3. Scale-factor logic is implemented three times — Medium (verified)
pysunspec2 computes `cvalue` (done in `poller.safe_point_cvalue`). `update_from_modbus_points` then re-implements scaling in Cases 3 and 4. `catalog`/`StateField.get_bounds` do it again with `sf_value`.
Differences between these implementations are a hidden-bug source:
- `scale_factors.get(a) or scale_factors.get(b) or ...` works only because all three keys hold the same value. It looks wrong, and it would break with a case-colliding SF name.
- `round(raw * 10**sf, abs(sf) if sf < 0 else 0)`: for `sf > 0` it rounds to 0 digits and returns a float with `.0`. For `sf < 0` it rounds to `|sf|` digits, which is correct but hides float repr noise.
- The scale factor range check `-10 <= sf <= 10` is applied in several places, with different fallbacks (`None` vs "use raw").
- SF points are looked up by name within the block only. SunSpec allows an SF to live in a different model, or in a repeating group, and the lookup silently returns `None`.

**Fix:** use pysunspec2 `cvalue` as the only scaled value (when available) and fall back to raw only for the mock path. Delete Cases 3 and 4.

## 4. `safe_point_cvalue` swallows everything — Low
[poller.py:32-60](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/poller.py#L32-L60): `except (OverflowError, ValueError, Exception)` is just `except Exception`. A real bug (for example a renamed attribute) is returned as `None`, which is indistinguishable from "sentinel". Log at debug level at least. The `sf_required`/`sf_value`/`sf` attribute probing is also guessing at pysunspec2 internals. Pin one pysunspec2 version and use its API directly.

## 5. Scan timing and failure behaviour — Medium (verified)
- `SerializedModbusClient(timeout=60.0)` is the socket timeout, and `scan_device` uses `retries=3` with 0.25 s then 0.5 s backoff. A scan of 100 non-existent slave IDs can run for hours if the gateway drops requests instead of returning an exception.
- `execute_sync(timeout=30.0)` is shorter than the socket timeout (60 s) and retries. The caller gives up, but the job keeps running on the worker thread and still holds the queue. Later jobs, and the poller, wait behind the orphaned job.
- Retries apply to every exception type. Deterministic errors (Modbus exception 2 "illegal data address", bad model definition, `ValueError` in point decoding) are retried three times and also reset the socket (`_handle_socket_error`). Retry only transport errors (`socket.timeout`, `ConnectionError`, `ModbusClientError('Connection...')`).
- `scan_range` default `1..100`: use `1..N` configurable, or break on N consecutive empty IDs. PWRcell devices occupy a small known range.

## 6. `scan_range` duplicate-serial logic — Medium (verified)
`stop_on_duplicate_serial` breaks the whole scan on the first duplicate serial, assuming the gateway wraps unknown IDs back onto an existing device.
A real second device with a blank or copied serial, or a transient read of the wrong device, stops discovery with no warning and with later devices missed. The duplicate is also not added to `discovered`. The log line is at `INFO`. Make it a `WARNING` with the list of IDs found so far.
Also: `sn not in ("", "0")` means devices with empty serials are keyed only by slave ID, and `StateStore.register_device` is keyed by serial. Two blank-serial devices collide.

## 7. Only model index 0 is ever read — Medium (verified)
`read_model_block(device, model_id, index=0)` and `poll_device_model` read only the first instance of each model. Repeating instances, such as multiple strings (model 404) or multiple batteries behind one slave, are ignored. State keys are `device_type.<model_name>.<point>`, which would collide anyway if more than one instance were read.

## 8. Model-ID aliasing in the device map — Medium (verified)
[poller.py:71-115](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/poller.py#L71-L115) maps `REbus_exp` and `inverter_status` both to 64208, and `model_64252` and `DCB105_warranty` to 64252. Elsewhere 64208 is also treated as a `SysMd` holder (`controls.py` fallback).
Name-to-ID resolution through three sources (state fields, hard-coded map, catalog), plus `resolve_minimal_models_for_paths` in `optimizer.py`, can yield different answers for the same path.
`resolve_paths_to_models` also does a prefix match `f.key.startswith(p)` with `p` being a raw user string, which can match unrelated keys (`"battery.battery"` matches `"battery.battery_status..."`).

## 9. Hard-coded SunSpec model numbers inside logic — Low
`64200`/`64208` in `controls.set_system_mode`, `64252`, `404`, `802` in poller defaults. If Generac renumbers a model (a firmware update ships new models via `sunspec-models`), these silently break. Resolve by model *name* via the catalog, and keep the numbers in one constants module.

## 10. Socket drain logic — Low (verified)
`_drain_stale_socket_bytes` sets the socket non-blocking and reads until `BlockingIOError`. If `recv()` returns `b""` (peer closed), it just breaks and leaves a dead socket that `is_connected()` still reports as connected. The next request fails and `_handle_socket_error` recovers it, but it costs one failed (and retried) transaction. Treat `b""` as a reason to disconnect and reconnect immediately. The drain also discards bytes that might belong to an in-flight response after a timeout; that is the intent, but the Modbus TCP transaction ID is the real fix.

## 11. Model definitions fetched with `AutoAddPolicy` — Medium (security)
[models.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/models.py) uses `AutoAddPolicy` (accepts any host key) and `scp.get(..., recursive=True)`. The result is loaded as model definitions (XML/JSON) for the library. A MITM on the LAN can feed arbitrary definitions to the parser, and the same applies to `SSHTunnelForwarder` host-key handling. At minimum, pin the beacon's host key (`known_hosts` in `/data`) after first use (TOFU). Also fix:
- Failures are logged only as `INFO` ("Using cached sunspec models").
- `version.chk` is not cleaned up.
- `scp.get('/opt/pika/...', sunspec_cache_dir, recursive=True)` downloads over existing files without atomicity. An interrupted copy leaves a half-updated model directory.

## 12. Catalog JSON parser flattens repeating sub-groups and shifts offsets — Medium (verified)
In `_parse_model_json` ([catalog.py:725-788](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L725-L788)):
- `running_offset` starts at `0` and includes the `ID` and `L` header points (2 registers), whereas `smdx_*.xml` (`_parse_smdx_xml`, [catalog.py:648-680](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L648-L680)) reads explicit `offset` attributes that are relative to the start of the fixed block (excluding the 2-register `ID`/`L` header). Thus `pt_def.offset` differs by 2 depending on whether a model came from JSON or XML!
- Lines 785–788 flatten repeating `groups` into the single `model_def.points` dict:
  ```python
  cur_offset = _parse_points_list(group.get("points", []), 0)
  for sub_grp in group.get("groups", []):
      cur_offset = _parse_points_list(sub_grp.get("points", []), cur_offset)
  ```
  If a repeating sub-group defines points with the same name as the fixed block or another sub-group (for example `ID`, `Tmp`, `V`, `A`), `model_def.points[pt_name]` silently overwrites the fixed block's point definition with the sub-group's point and accumulates `cur_offset` assuming each sub-group repeats once.
