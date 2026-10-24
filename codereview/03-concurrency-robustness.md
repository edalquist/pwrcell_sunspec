# 03 — Concurrency, lifecycle and robustness

## 1. Shared state accessed without the lock — Medium (verified)
`StateStore._lock` guards `register_device` and `set_field`, but many readers bypass it:
- `client._poll_device_models_live` iterates `self.state.devices.values()` directly (wrapped in `list(...)`, which is itself not atomic against a dict resize in another thread).
- `controls.set_system_mode` iterates `state_store.devices.values()` and mutates `StateField.value/raw_value/last_updated` directly, without `set_field` and without a lock.
- `controls.write_field` mutates `target_field.value`, `raw_value` and `bitmask_flags` in place.
- `ui/server.py` serialises devices and fields from Flask request threads while the poller and MQTT threads write.
- `poller.last_poll`, `poll_counts` and `fast_models` are read by the UI and mutated by the poller and `sync_ha_selected_fields` with no lock.
- `bridge._on_field_update` reads `selected_field_keys`, `_published_discovery_topics` and `_selected_set` without `self._lock`, while `publish_discovery`/`reload_config_and_republish` replace them.

Python dict/list mutation during iteration raises `RuntimeError`. It is rare, so it will show up as an occasional unexplained UI 500 or a swallowed listener error.
**Fix:** route every state mutation through one `StateStore` method that takes the lock, and provide `snapshot()`/`to_dict()` that copies under the lock. Treat `StateField` as immutable (replace instead of mutate).

## 2. Lock held across blocking operations — Medium (verified)
- `PwrcellClient.stop()` holds `self._lock` while joining threads (1–2 s each) and closing Modbus.
- `SerializedModbusWorker.stop()` holds its lock while draining the queue and joining the worker thread.
- `HomeAssistantBridge.publish_discovery` holds `_lock` while it publishes hundreds of messages and calls `StateStore` methods. Lock order is bridge then state. `StateStore.set_field` calls listeners outside its own lock, which is correct. Keep it that way, and document the order.
- `PwrCellTunnel.ensure_active` can run `time.sleep(0.5)` plus three connection attempts with `sleep(1.0*attempt)`, about 8 seconds or more. Modbus jobs and the watchdog both call it and block on `_reconnect_lock`. Because `_ensure_device_connected` calls it on the Modbus worker thread, **all polling stalls** during a tunnel rebuild. That is expected, but every queued job's `execute_sync` has a 30 s timeout, and the retry-with-backoff in `_execute_job` multiplies this.

## 3. Stale data is indistinguishable from fresh data — High (verified)
- HA availability is the single topic `pwrcell/status` ("online"/LWT "offline"). If Modbus polling fails, the SSH tunnel is down, or the internal MQTT drops, the bridge process is still "online" and **all entities keep their last value as available**. HA energy dashboards and automations will act on stale grid, battery SoC and power values.
- `StateField.last_updated` exists but is never used to expire values.
- `poll_tier` sets `last_poll[tier]` and increments the tier counter even if **every** model read failed, so health reporting says "polled".
- MQTT snapshots that lack a channel leave the previous channel value in place, and `LiveTelemetrySnapshot` defaults (`grid_power_w = 0.0`) turn "no NET channel in this message" into a published `0 W`.

**Fix:** per-entity availability, either an availability template based on a per-source heartbeat topic, or (simplest) publish `unavailable` (empty/`None` payload) when a field exceeds N times its poll interval. Add a `data_age` metric. Track poll success separately from poll attempted.

## 4. Startup/shutdown ordering — Medium (verified)
- `PwrcellClient._start_live_mode` starts the poller, then spawns the initial deep-poll thread. Both use the Modbus worker and both may call `scan_device` for the same slave, so the model scan runs twice.
- The poller thread also re-runs `load_or_discover_devices()` and `_poll_device_models_live()` synchronously from its own loop every 30 s when no devices exist. If discovery takes minutes, the fast/config tiers are not serviced.
- `PwrcellClient.stop()` never stops the bridge (`getattr(self, "bridge", None)` is used elsewhere, and `bridge` is not declared in `__init__`).
- `stop()` returns while threads may still be running (join timeouts of 1–2 s with no check).
- `SerializedModbusWorker.submit()` auto-starts the worker if it is not running. After `close()` any late call, such as an HA command thread, silently resurrects the worker thread against a closed client.
- `cli.cmd_service` runs Flask's development server (`app.run`). It is not production-grade: it has no graceful SIGTERM handling, and in Docker `exec python3 ...` gets SIGTERM and exits without the `finally:` blocks (bridge offline message, tunnel stop). Handle `SIGTERM` explicitly, or at least translate it to `KeyboardInterrupt`.
- Start the SSH tunnel and model-sync in one place. Today `load_models_dir` opens a separate SSH connection, in addition to the `sshtunnel` one.

## 5. Reconnect behaviour — Medium (verified by reading)
- **Internal MQTT** ([mqtt.py:240-278](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mqtt.py#L240-L278)): on disconnect with a tunnel manager, a thread calls `ensure_active()` and then `disconnect()` plus `connect_async()`. If the tunnel was already healthy (`ensure_active()` returns `True` both before and after), nothing is changed and paho's own auto-reconnect is the only recovery, so there are two competing recovery mechanisms. If the tunnel is rebuilt on a new port, `self.__mqttc.disconnect()` followed by `connect_async` depends on paho's internal state machine. Test this path explicitly.
- `subscribe("#")` subscribes to every topic on the Beacon's broker and processes every message on the paho thread. A noisy broker burns CPU. Subscribe only to `/energy_recordset_live`.
- `on_connect` re-subscribes. OK.
- **Tunnel watchdog** polls every 2 s and, together with Modbus-triggered `ensure_active()`, can rebuild the tunnel while another component holds a socket to the old local port. `modbus` handles it via `_get_shared_client`, but only on the next call.
- When `ensure_active()` falls back to ephemeral ports, `TunnelConfig` objects that were handed out earlier are stale. The code works around it with `tunnel.modbus_port` lookups in `modbus.py` and `mqtt.port`. A single `tunnel.get_config()` accessor used everywhere, instead of per-object lookups, would be simpler.

## 6. Discovery cache never refreshes — Medium (verified)
`load_or_discover_devices` trusts an existing `devices.yaml` forever. If a slave ID changes (re-commissioning), a device is replaced or a PV Link is added:
- the old serial stays registered with the old slave ID and polls the wrong or no device,
- the new device is never seen.

Add a cheap periodic verification, such as reading model 1 (common) for each cached slave ID and comparing serials. Offer a "rescan" action in the UI.

## 7. Thread creation per command — Low
[bridge.py:482-487](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L482-L487) spawns an unbounded daemon thread for every HA command message. A burst (an automation looping, or retained replays, see 04 §3) creates N threads that each block on the Modbus queue for up to 30 s. Use one small `ThreadPoolExecutor(max_workers=1)` so commands are also ordered.

## 8. Exceptions swallowed in the wrong places — Low
About 70 `except Exception` blocks. The ones in `StateStore.notify_*` log listener errors at `debug` level, so a broken bridge listener means HA silently stops updating with nothing in the default log.
Likewise `ModbusClient.close()`, `_handle_socket_error` and the tunnel code swallow at debug level. Use `logger.exception`/`warning` for the first occurrence and rate-limit repeats.
