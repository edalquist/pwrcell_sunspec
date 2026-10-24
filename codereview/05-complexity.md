# 05 — Complexity and simplification

Simpler is the goal, so this section lists where complexity is highest and what could be removed or merged.

## Hotspots

Measured with a rough branch count (`if`/`for`/`try`/boolean ops/comprehensions) per function:

| Function | Lines | Branches |
|---|---|---|
| `ui/server.py::create_app` | 747 | 201 |
| `state.py::get_field_modbus_details` | 266 | 136 |
| `optimizer.py::group_device_fields` | 437 | 129 |
| `ha.py::generate_discovery_payload` | 181 | 78 |
| `state.py::update_from_modbus_points` | 143 | 78 |
| `state.py::set_field` | 221 | 77 |
| `state.py::get_compound_view` | 189 | 76 |
| `state.py::update_from_telemetry_snapshot` | 416 | 59 |
| `correlator.py::_build_comparison_row` / `_build_group_comparison_row` | 239 / 198 | 43 / 57 |
| `recommender.py::find_suggested_groupings` | 197 | 50 |

File sizes: `state.py` 2220, `optimizer.py` 1274, `catalog.py` 922, `correlator.py` 904, `ui/server.py` 791.

## Recommendations (highest value first)

### 1. Declarative MQTT-to-field table instead of 400 lines of `set_field` calls
`update_from_telemetry_snapshot` ([state.py:1372-1788](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1372-L1788)) is 25+ near-identical `set_field(...)` blocks. Each repeats `HomeAssistantHint(...)`, `source=MQTT_PUSH`, `sub_group="live"`, and `round(x, 1)`.
Replace with a table of `(device_type, name, label, desc, getter, units, hint)` and a loop. That cuts roughly 400 lines to about 60 and makes the zero-vs-missing bugs (01 §3) fixable in one place. `client._mock_sim_loop` repeats the same pattern for the mock path; it should reuse the same table.

### 2. Split `set_field` (221 lines, 25 parameters)
- The create branch and the update branch duplicate the `is_scale_factor` expression (which already differs: the update branch also ORs `existing.is_scale_factor`, and the create branch lacks the `point_type == "sunssf"` clause in one form).
- Side effects are interleaved: validation, sentinel rejection, model metadata resolution, monotonic guard, field merge, listener fan-out, compound-view recomputation.
- Introduce a `FieldSpec` dataclass for static metadata (label, description, symbols, point type, SF info, model info) and keep `set_field(sn, key, value, raw, source)` as the hot path. Static metadata only changes when the catalog changes, so set it once at definition time and not on every poll.
- `update_from_modbus_points` rebuilds `symbols_defs`, `ha_hint` and other metadata for every point on every poll (a catalog lookup and a list of dicts each time). Cache per `(model_id, point)`.

### 3. One scaled-value pipeline
See 02 §3: delete the home-grown scale-factor cases and the type-blind sentinel checks. It removes about 60 lines and a whole class of "why does this show 6553.5 V" bugs.

### 4. `validate_field_value`: heuristic plausibility bounds by substring
[state.py:39-109](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L39-L109). Unit and name substring matching has false positives:
- `"phv" in name`, `name.endswith("_a")` (matches `"alarm_a"`) and `"tmp" in name or "temp" in name` (`"attempt"`, `"template"`).
- The `elif` chain stops at the first match, so a point in `%` whose name contains "temp" is judged as a percentage.
- `units == "A"` bounds at 1000 A, `V` at 2000 V and `W` at 1 MW are system-specific. DC-bus current limits on a different PWRcell configuration could be rejected silently (only a WARNING).
If you keep it, drive it from catalog metadata (`device_class` + explicit bounds) and not from name patterns. Otherwise remove it and rely on SunSpec sentinels.

### 5. Replace `hasattr`/`getattr` probing with real types
156 uses across `pwrcell/`. Examples: `getattr(field, "is_compound", False)`, `hasattr(field, "active_flags")`, `getattr(self.tunnel, "modbus_port", None)`, `hasattr(self.client, "poller")`.
`generate_discovery_payload` accepts `Any` for either `StateField` or `CompoundFieldView` and branches on attribute existence. Give both a small shared protocol (`key`, `label`, `units`, `ha_*`, `is_writable`) or convert compound views to a `StateField`-like dataclass at the edge. That will remove most of the 181-line function's branching.
Declare `self.bridge: Optional[HomeAssistantBridge] = None` in `PwrcellClient.__init__` and delete `getattr(self, "bridge", None)`.

### 6. Break up `create_app`
A 747-line closure with ~30 routes registered inside one function is hard to test and hard to review for security (04 §1).
Use Flask blueprints: `devices`, `fields`, `ha`, `grouping`, `poller`. Move business logic (such as `optimize_polling_for_device`, ~120 lines, and the HA-config merge logic in `handle_ha_config`) into plain functions that take `client`. Routes should only parse requests and serialise responses.

### 7. Collapse the three overlapping "unified field" systems (~4.5k LOC)
Reading `state.py`, `optimizer.py`, `grouping.py`, `correlator.py`, `recommender.py`, and `mapping.py` in full shows that the codebase has **three separate systems** that merge MQTT push telemetry and redundant SunSpec Modbus registers into a single concept:
1. **`MappingRegistry` + `CompoundFieldView`** ([mapping.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/mapping.py), [state.py:771-970](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L771-L970)) — produces `<device_type>.compound.<id>` entities driven by `telemetry_mappings.yaml`, recomputed on every `set_field` notification.
2. **`CANONICAL_SYNONYMS` + `group_device_fields` + `UnifiedFieldGroup`** ([optimizer.py:42-315, 792-1274](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/optimizer.py#L42-L315), [grouping.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/grouping.py)) — produces `<device_type>.concept.<id>` groups using hardcoded `CANONICAL_SYNONYMS` (which has the `totwhexp`/`totwhimp` swap bug in 01 §15), `custom_groupings.yaml`, and `MappingRegistry`.
3. **`evaluate_comparisons` + `ComparisonResultRow` + `SEMANTIC_SYNONYM_CLUSTERS`** ([correlator.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/correlator.py), [recommender.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/recommender.py)) — re-implements value comparison, scale/unit reconciliation, and synonym clustering a third time.

Questions worth answering before adding more features:
- Can `CompoundFieldView` and `UnifiedFieldGroup` be unified into a single data-driven concept table backed by `telemetry_mappings.yaml`?
- Is the weighted set-cover in `solve_minimal_model_set` ([optimizer.py:553-702](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/optimizer.py#L553-L702)) needed? The poller reads at most a dozen models per device; a simple `set` of required `(device_sn, model_id)` pairs from the selected fields is sufficient.
- Should offline discovery/correlation tooling (`correlator.py`, `recommender.py`, `clean_discovery.py`) move out of the runtime add-on path into `tools/`?

### 8. Several lookups by suffix/prefix string match
`find_fields` falls back to "any field in this device type whose key ends with `.<point>`", returning `MQTT_PUSH`-excluded first match. `resolve_paths_to_models` matches `f.key.startswith(p)` with raw user strings. `is_field_selected` tries upper/lower serial variants, each key with and without the `mqtt_key`. `write_field` treats any key ending in `.SysMd` or `.system_mode` specially.
Pick one canonical key form (`<serial>:<model_id>.<point>`, or similar), normalise on input (config load, API entry), and require exact matches afterwards. This removes the upper/lower/qualified/legacy variants (`qualify_legacy_ha_config`, `unqualify_ha_config`, and the two merge code paths in the UI).

### 9. Duplicated constant tables and copy-pasted helpers
- **System-mode names:** `controls.OPERATING_MODES` (SunSpec enum: `SAFETY_SHUTDOWN=0, GRID_CONNECT=1, SELF_SUPPLY=2, CLEAN_BACKUP=3...`) versus `mqtt.SYSTEM_MODE_NAMES` (Protobuf enum: `UNKNOWN=0, GRID_TIE=1, SELF_SUPPLY=2, CLEAN_BACKUP=3..., SAFETY_SHUTDOWN=16`) versus `mqtt.py:93-102` fallback (`CLEAN_BACKUP=1, GRID_TIE=2, SELF_SUPPLY=3, SAFETY_SHUTDOWN=7`). Keep them in one module with explicit `SUNSPEC_` and `PROTO_` prefixes, and delete the broken fallback dict.
- **Display precision (`get_suggested_precision`):** copy-pasted three times across [ha.py:295-315](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ha.py#L295-L315), [catalog.py:889-907](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L889-L907), and [state.py:910-924](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L910-L924).
- **Scale factor detection (`is_scale_factor`):** copy-pasted seven times across [catalog.py:820](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/catalog.py#L820), [state.py:1143, 1219, 1796](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L1143), [optimizer.py:390, 916](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/optimizer.py#L390), and [recommender.py:139](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/recommender.py#L139) with slightly different conditions (`endswith("_sf")` vs `== "sf"` vs `point_type == "sunssf"`).
- **Default tiers:** defined three times (`DEFAULT_*_PATHS`, `DEFAULT_*_MODELS` and `PWRCELL_DEVICE_MODEL_MAP`). Keep only the paths and resolve.

### 10. Misc small simplifications
- `client.PwrcellClient.__init__` has about 30 lines of manual unpacking of `polling_tiers` that accept either a list or a dict for each tier. Pick one schema and give `AppConfig` a typed `PollingTierConfig`.
- `poller.poll_tier("all"/"deep")` mixes tier polling with "poll everything", and `last_poll["all"]` is added dynamically.
- `models.py` shares its name with the SunSpec "models" concept and contains only an SCP downloader. Rename it (`model_sync.py`).
- `PwrcellClient._mock_sim_loop` writes a dozen fields by hand with a magic `1.5` s tick duplicated between `tick(elapsed_seconds=1.5)` and `time.sleep(1.5)`.
- The sentinel `if not self._running` / `Condition` dance in `TieredModbusPoller._worker_loop` re-reads `time.time()` three times per iteration. One `schedule = {tier: next_due}` dict and a single `_cond.wait(min(next_due) - now)` would replace about 70 lines, and remove the 1 s idle wake-up and the unconditional `time.sleep(2.0)` startup stagger that ignores stop requests.

## Test Suite Findings & Hygiene (`tests/`)
Running `.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v` executes **119 tests in 33.85s** (all passing). Inspecting the test suite revealed several important gaps and side effects:
1. **Why `test_bridge.py` missed the `NameError: name 'os' is not defined` crash in `bridge.start()`:**
   [tests/test_bridge.py:21-38](file:///Users/edalquist/projects/pwrcell_sunspec/tests/test_bridge.py#L21-L38) constructs `HomeAssistantBridge` and assigns `self.bridge._mqttc = MagicMock()` and `self.bridge._connected = True` directly in `setUp`, never calling `self.bridge.start()`. Add a unit test that mocks `mqtt.Client` and exercises `bridge.start()` with `client_name=""`.
2. **Tests mutate real workspace config files on disk:**
   - [tests/test_ui.py:24-31](file:///Users/edalquist/projects/pwrcell_sunspec/tests/test_ui.py#L24-L31) calls `load_ha_config()` in `setUpClass` and `save_ha_config(cls.orig_ha_config)` in `tearDownClass`. If `ha_config.yaml` did not exist beforehand, `load_ha_config()` loads the seed from `ha_default_config.yaml` and `tearDownClass` writes a new `ha_config.yaml` to the workspace (or leaves dirty state if a test interrupts).
   - Endpoints tested in `test_ui.py` (`POST /api/grouping/override`, `POST /api/grouping/reset`, `POST /api/mappings`) read and write the real `pwrcell/data/custom_groupings.yaml` and `pwrcell/data/telemetry_mappings.yaml` unless patched. Use `tempfile.TemporaryDirectory` or patch the config paths in `setUpClass`.
3. **Why 119 unit tests take 34 seconds:**
   - `PwrcellClient(is_mock=True).start()` spawns the `_mock_sim_loop` thread ([client.py:209](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/client.py#L209)), which calls `time.sleep(1.5)` instead of waiting on a stop `Event`. Every `client.stop()` in `test_bridge.py` (9 tests) and `test_ui.py` waits up to 1.5s for that sleep to finish, accounting for ~15s of wall time. Using `self._stop_event.wait(1.5)` in `_mock_sim_loop` will make `client.stop()` instant and cut test runtime in half.
   - [tests/test_tunnel.py](file:///Users/edalquist/projects/pwrcell_sunspec/tests/test_tunnel.py) sleeps for `0.5s + 1.0s` in reconnect tests and checks for a real `~/.ssh/id_rsa` on the host machine, logging `ERROR:pwrcell.tunnel:SSH identity file not found at: /Users/edalquist/.ssh/id_rsa`.
4. **Misleading `NaN` test (`test_nan_equality_does_not_loop_notifications`):**
   As noted in 01 §18, [tests/test_state_and_controls.py:272-298](file:///Users/edalquist/projects/pwrcell_sunspec/tests/test_state_and_controls.py#L272-L298) claims to test `NaN == NaN` in `set_field`, but actually tests `None == None` because `validate_field_value` strips `NaN` to `None` before the equality check.
