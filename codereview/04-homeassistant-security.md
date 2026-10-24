# 04 — Home Assistant integration and security

## 1. Unauthenticated write access to the inverter — High (verified)
- `run_explorer` binds `0.0.0.0:5555`. `config.yaml` publishes `5555/tcp` on the host and also enables Ingress.
- `POST /api/fields/write` ([server.py:530](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/server.py#L530-L544)) calls `controls.write_field`, which writes Modbus registers. No authentication, no CSRF protection, and no origin check.
- `POST /api/poller/trigger`, `/api/mappings`, `/api/ha/config`, `/api/grouping/*` and `/api/ha/export_defaults` (which writes a file) are equally open. `/api/ha/config` rewrites which entities are published.
- The writable `SysMd` enum includes `SAFETY_SHUTDOWN` (`0`). Any host on the LAN, or any web page open in a browser on the LAN (a cross-site POST with `Content-Type: text/plain` that Flask's `get_json()` may still reject, but JSON-less simple requests are still possible with `force=True` elsewhere), can shut the system down.
- The write endpoint returns `str(e)` to the client and `app.run(debug=...)` is exposed through the `--debug` flag. Flask debug mode means the Werkzeug debugger, i.e. remote code execution if enabled on `0.0.0.0`.

**Fix (simplest, most effective):** with Ingress enabled, drop the direct `ports:` mapping by default and bind to `127.0.0.1` or the Ingress interface. Reject requests that do not come from the Supervisor ingress (`172.30.32.2`). Put the write endpoints behind an explicit option such as `allow_writes: false`. Remove `SAFETY_SHUTDOWN` from the writable options exposed over the API and HA discovery. Require `debug` to force `127.0.0.1`.

## 2. Writable exposure is generic — Medium (verified)
`ha.generate_discovery_payload` turns any field with `access == "rw"` into a `number`/`select` entity, with no `min`/`max` unless the hint has one. HA then lets a user write arbitrary values to arbitrary registers through the UI, including safety or grid-code parameters (volt-var, volt-watt, reconnect timers; models 126/132/64203 are in the poller map).
**Fix:** an explicit allow-list of controllable points (system mode, battery reserve and similar), not "everything the SunSpec model says is rw". Validate against the catalog's min/max (`validate_and_convert` should enforce them).

## 3. Retained command messages replay writes — High (verified)
[bridge.py:468-487](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L468-L487): `_on_message` ignores `msg.retain`. If any publisher sends a command with `retain=True` (a user mistake, a misconfigured automation, or an HA `mqtt.publish` with retain), the broker redelivers it on every (re)subscribe. `publish_discovery()` runs on every reconnect and re-subscribes each command topic. The inverter mode or setting is overwritten on every reconnect, indefinitely.
**Fix:** `if msg.retain: return` (log a warning). Ideally also ignore payloads while the first discovery after connect is still being processed.

## 4. Bridge availability, state freshness and republish — Medium (verified)
- See 03 §3: availability is only the process-level `pwrcell/status`.
- `_on_field_update` publishes state with `retain=False`, but discovery-time state is published with `retain=True`. After an HA restart (the birth message is not handled), non-retained slow-tier values are unknown until their next change. HA birth (`homeassistant/status` = `online`) should trigger `publish_discovery()` and a full state republish.
- `old_sensor_topic` is published empty **on every discovery** for every select/number entity, as unconditional cleanup. It is churn and is unnecessary once the old topics were removed.
- If an entity's platform changes between runs (sensor to select, because a hint was added), the old config topic differs from the new one. It is cleaned only for the sensor to select/number/switch cases. Other platform changes leave an orphan entity. The persisted topic file handles most of this.
- `_on_field_update` calls `is_field_selected(field.key, ..., self.selected_field_keys)`, passing the **list**. `is_field_selected` rebuilds `set(selected_keys)` on **every field update** (hundreds per poll). The cached `self._selected_set` exists but is not used. It also rebuilds `generate_discovery_payload` for every update just to get topics. Cache `payload_info` per field key.
- Compound-view behaviour: when a compound view is active, raw fields are suppressed and their retained topics are cleared on each `publish_discovery`. The selected-set check order determines which one wins. This is intricate; see 05.
- `object_id` in the discovery payload is deprecated in recent Home Assistant releases (replaced by `default_entity_id`) and slated for removal. Check the HA version you target.
- `ORIGIN_INFO` version string is hard-coded and stale (01 §6).

## 5. Add-on config generation is injectable — Medium (verified)
[rootfs/run.sh](file:///Users/edalquist/projects/pwrcell_sunspec/rootfs/run.sh) builds `/data/pwrcell.yaml` with an unquoted heredoc using `$BEACON_PASS`, `$MQTT_PASS`, `$SSH_PASSPHRASE` and others inside double quotes.
- A password containing `"`, `\`, `#` or a newline produces invalid or altered YAML. A newline lets an option value inject additional YAML keys.
- Because `AppConfig.read` swallows parse errors into defaults (01 §5), a broken file silently becomes "no configuration".
- Secrets end up in a plain file under `/data`; set `chmod 600`.

**Fix:** generate the file in Python from `options.json` (you already ship `setup_key.py`) with `yaml.safe_dump`, or let `AppConfig` read `options.json` directly and delete the shell translation layer.

## 6. SSH trust — Medium (verified)
`AutoAddPolicy` in `models.py` (and `sshtunnel` without host-key pinning) trusts the first and every host key. See 02 §11.
`ssh_password` and `key_passphrase` are accepted. Passwords for a root login on the beacon are a risk; prefer key-only.

## 7. Entity naming / unique IDs — Low (verified)
`unique_id = pwrcell_{sn}_{sub_key}` depends on `field.key` (`device_type.sub_group.name`). `sub_group` is the SunSpec model *name* from the catalog. If the catalog's model names change after a `sunspec-models` sync from the beacon (the code downloads new definitions at each start), **every entity gets a new `unique_id`**, and old ones become orphans/unavailable. Consider keying on model **ID** and point name.
`short_sn` is the last 4 characters of the serial in `object_id`. Two devices whose serials end the same way collide.

## 8. `yaml` optional import — Low (verified)
`ha.py` sets `yaml = None` on `ImportError`, but PyYAML is in `requirements.txt`. Remove the fallback: `save_ha_config` would raise `AttributeError` in that case, and the other paths catch it with a broad `except`, hiding it.
`save_ha_config` and `export_default_config` write in place and are not atomic. A crash mid-write corrupts the file, and the loader then returns `[]` on error. That causes the bridge to fall back to "recommended" entities and unpublish the user's selection (`removed_topics`). Write to a temp file and `replace` (as `_save_persisted_published_topics` already does).
