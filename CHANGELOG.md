# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0] - 2026-11-15

### Added
- **Generic SunSpec Sub-Group Support (Per-Module Battery Telemetry & Nested Groups)**:
  - Recursively parses SunSpec sub-group metamodel definitions (`SunspecGroupDef`, `SunspecPointDef` group metadata, `ModelCatalog`, `SunspecModelDef.get_group_point()`) across all models without colliding with fixed-block register names (`pwrcell/catalog.py`).
  - Surfacing of per-battery-module telemetry from Model `804` (`lithium_ion_string_module`) and Model `64252` (`DCB105_module` warranty/module health metrics), Model `64200` (`devices` REbus directory slots including `ID`), and nested SunSpec sub-groups (`704`, `705` `Crv.Pt`, etc.).
  - Explicit group metadata (`group_name`, `group_index`, `group_path`, `group_label`) on `StateField`, `ConceptSource`, `ConceptView`, Modbus register details, and REST APIs (`pwrcell/state.py`, `pwrcell/concept.py`).
  - Polls SunSpec `battery.lithium_ion_string` (`804`) in `DEFAULT_SLOW_PATHS` and recursively extracts live `pysunspec2` sub-groups (`extract_model_groups` in `pwrcell/poller.py`) and recorded fixtures (`MockFixtureLoader` in `pwrcell/fixtures.py`, `pwrcell/client.py`).
  - Added add-on/config option `include_bulk_table_groups` (default `false`, opt-in in `config.yaml`, `pwrcell/config.py`, `pwrcell/setup_key.py`) so large curve/schedule lookup tables (`126`, `129`–`144`, `705`–`712`, `64229`–`64257`) can be enabled on demand while raw flash buffers (Model `64258` `flash_reader.sector`) are always excluded.
  - Added `group_path` traversal to `SerializedModbusClient.write_point_value()` (`pwrcell/modbus.py`) and `ControlDispatcher.write_field()` (`pwrcell/controls.py`) so writable sub-group points can be updated safely while preserving group metadata.
  - Added Web Explorer UI sub-group instance dividers (`.subgroup-divider-row`), `.badge-subgroup` pills, natural numeric name sorting (`Module 1`, `Module 2`, ..., `Module 10`), and sub-group details in the register modal (`pwrcell/ui/static/app.js`, `pwrcell/ui/static/style.css`).
- **Collapsible Sub-Group Rollup Rows in Web Explorer (`pwrcell/ui/static/index.html`, `pwrcell/ui/static/app.js`, `pwrcell/ui/static/style.css`)**:
  - Added **Roll up sub-groups** toolbar toggle (`#rollupSubgroups`, enabled by default whenever the active device exposes repeating sub-group instances) to collapse repeated SunSpec sub-group points (such as Model `804` `ModSoC` or Model `64252` `DCB105_module` metrics across all battery modules) into compact summary rows.
  - Summary rows display instance counts (e.g. `6× Modules`), a 3-state Home Assistant selection checkbox (`checked` / `indeterminate` / `unchecked`), HA exported badge (`6/6 ★`, `2/6`, `0/6`), cross-instance value range / enum summary with live SSE refresh & flash (`handleLiveFieldUpdate`), and inline group category toggling (`toggleRollupCategoryAction`).
  - Expanding a rollup opens an embedded per-instance drawer with per-instance HA checkboxes, live values, independent category toggles, `Set`/`Details`/`Copy` actions, and an inline rule-mode pill (`★ Saved as Wildcard (*)` ↔ `Saved as N Explicit Keys`).
  - Targeted searches (e.g. `"Module 3"`) automatically unroll matching concrete instances, and Optimization Plan Breakdown click-to-jump automatically expands the parent rollup and highlights the target child row.
- **Wildcard & Explicit Sub-Group Home Assistant Selection Rules (`pwrcell/catalog.py`, `pwrcell/ha.py`, `pwrcell/bridge.py`, `pwrcell/ui/routes/ha.py`, `pwrcell/optimizer.py`)**:
  - Added catalog helpers (`wildcard_group_path`, `wildcardize_group_field_key`, `is_group_wildcard_key`, `group_wildcard_matches_field_key`) supporting single-level and nested SunSpec repeating paths (e.g. `battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC`, `inverter.DERVoltVar.Crv.*.Pt.*.V`).
  - Defaults to saving a canonical `*.<Point>` wildcard rule in `ha_config.yaml` when all instances in a sub-group are selected, while supporting explicit per-instance keys, automatically splitting a wildcard into remaining explicit keys when a single instance is unchecked, and auto-collapsing back to a wildcard when all explicit instances are selected.
  - Supports wildcard and per-instance Home Assistant `category_overrides` (with exact instance overrides taking precedence over wildcards), cold-start safety (`StateStore.ensure_field_definition()` never creates literal `*` `StateField` entries and preview logs `group_wildcard_awaiting_poll` until polled), HA config deduplication (`qualify_legacy_ha_config`), and accurate minimal-model solving for wildcard subgroup paths in `resolve_minimal_models_for_paths()`.
- Added unit, API, optimizer, cold-start, and Node VM frontend test suites in `tests/test_sunspec_groups.py`.

### Changed
- **Semantic Grouping & Home Assistant MQTT Discovery for Sub-Groups**:
  - Updated `group_device_fields()` (`pwrcell/optimizer.py`) to isolate sub-group points into instance-scoped concepts (`<device_type>.concept.m<model_id>_<group_path>_<point>`) so values never merge across modules/instances or into bank-level metrics.
  - Updated `pwrcell/ha.py` so sub-group entities attach to their parent `UnifiedDevice`, default to `entity_category: "diagnostic"`, preserve instance-prefixed entity labels and saved config slugs (`_resolve_standalone_or_orphan_slug`), and avoid colliding with top-level legacy discovery topics.

### Fixed
- Cleared invalid unit/scale-factor metadata on SunSpec Model `804` `ModCellVMinCell` and defaulted `%` units on Model `64252` `DCB105_module` `SOC`/`SOH` points in `pwrcell/catalog.py`.

## [3.1.16] - 2026-11-15

### Fixed
- **Battery SoC/SoH Retained Discovery Topic Collision & Model Alias Grouping (Issue #17)**:
  - Disambiguated raw Modbus discovery `object_id`/`sub_key` (`generate_discovery_payload` in `pwrcell/ha.py`) when a raw point's trailing path collides with a compound concept ID on the same device type (e.g., Model 802 `battery.battery.SoC` -> `m802_soc` and `battery.battery.SoH` -> `m802_soh`), preventing suppressed Model 802 member clears from wiping retained `battery_soc/config` and `battery_soh/config` discovery payloads on the MQTT broker.
  - Hardened `HomeAssistantBridge.publish_discovery()` and `_on_compound_update()` (`pwrcell/bridge.py`) to defer all suppressed-member and legacy retained `""` clears until after active discovery and state topics are registered, never clearing any topic claimed by an active entity.
  - Updated `ensure_selected_field_definitions()` (`pwrcell/ha.py`) to pre-populate only a single primary non-excluded candidate on cold start when a selected compound has zero polled members yet, avoiding unnecessary synthetic placeholder raw fields.
  - Expanded `model_<id>` aliases to canonical SunSpec catalog model names at `MappingRegistry.reload()` (`pwrcell/mapping.py`), added explicit canonical SunSpec model keys (including `inverter.REbus_status.St`, `inverter.inverter.St`, `inverter.DERMeasureAC.InvSt`, and `invst` synonym in `inverter_state`) to `pwrcell/data/groupings.yaml`, and preserved `unit` when serializing `battery_soc` in `save_mappings()`.

### Added
- **Collision-Avoidance & Alias-Expansion Diagnostics and Regression Tests**:
  - Added `DEBUG` logging in `pwrcell/ha.py`, `pwrcell/bridge.py`, and `pwrcell/mapping.py`, plus 4 regression tests in `tests/test_issue_17_ha_config.py`.

## [3.1.15] - 2026-11-15

### Fixed
- **Home Assistant Selection, Config Migration & MQTT Discovery Preview Sync (Issue #17)**:
  - Fixed Web UI selection helpers (`getCompoundKeyForItem`, `isFieldSelected`, `toggleHaSelection`, `btnDeselectAll`, `btnApplySameType`, and `compoundKeyByRaw` lookup) in `pwrcell/ui/static/app.js` so standalone Unified View rows preserve their real raw keys instead of fabricating invalid `.compound.` keys, and compound selections/deselections cleanly manage member keys via `member_keys` exported by `ConceptView.to_dict()` (`pwrcell/concept.py`).
  - Updated `btnPreviewHA` in `pwrcell/ui/static/app.js` and `/api/ha/preview` in `pwrcell/ui/routes/ha.py` to support live `POST` previews of unsaved UI selections and category overrides alongside `GET` previews, while pre-populating unpolled MQTT/Modbus definitions from `mqtt_telemetry.yaml` (`StateStore.ensure_field_definition` in `pwrcell/state.py`).
  - Fixed `StateStore.get_compound_view()` in `pwrcell/state.py` so Modbus-only `inverter_state` views preserve `ha_device_class="enum"`.
  - Updated `pwrcell/ha.py` (`qualify_legacy_ha_config`, `_remap_concept_key`, and shared `ensure_selected_field_definitions`, `collect_compound_member_keys`, `is_raw_field_suppressed` helpers) and `pwrcell/bridge.py` to repair orphaned `.standalone.`/invalid `.compound.` keys, respect per-device ungrouped exclusions when remapping or suppressing raw member entities, and keep `ha_config.yaml` vs preview/bridge discovery aligned.
  - Updated `pwrcell/optimizer.py` (`group_device_fields`, `resolve_minimal_models_for_paths`) and `pwrcell/ui/routes/devices.py` to honor both `.compound.` and `.concept.` selections when resolving optimal Modbus polling models.
  - Updated `pwrcell/mapping.py` (`load_mappings`, `save_mappings`, `TelemetryMappingDef.member_transforms`), added `battery.lithium_ion_string.SoC` to `battery_soc` in `pwrcell/data/groupings.yaml`, and removed stale/redundant entries from `config/ha_default_config.yaml`.

### Added
- **Expanded `DEBUG`-Level Diagnostic Logging & Regression Tests**:
  - Added detailed `DEBUG` logging across `pwrcell/ha.py`, `pwrcell/state.py`, `pwrcell/ui/routes/ha.py` (save diffs and unmatched preview keys), `pwrcell/bridge.py` (reload diffs and skipped/unmatched keys), `pwrcell/mapping.py`, and `pwrcell/ui/static/app.js` (`console.debug` selection trace) to aid diagnostics.
  - Added regression tests in `tests/test_issue_17_ha_config.py` (including Node-executed verification of `app.js` helpers and `assertLogs` debug-logging assertions) and updated default config assertions in `tests/test_ui.py`.

## [3.1.14] - 2026-11-14

### Fixed
- **Custom Concepts `TelemetryMappingDef` Initialization Error (Issue #16)**:
  - Removed the invalid `name` keyword argument when constructing `TelemetryMappingDef` for custom concepts in `StateStore.get_compound_view` (`pwrcell/state.py`), which caused `TypeError: TelemetryMappingDef.__init__() got an unexpected keyword argument 'name'` and prevented UI field loading and MQTT discovery/updates whenever `custom_concepts` were present.
  - Also added fallback support for `unit` alongside `units` in custom concept metadata.
  - Added regression test `test_get_compound_view_with_custom_concept` in `tests/test_compound_and_mapping.py`.

## [3.1.13] - 2026-11-13

### Fixed
- **MQTT Retained State Continuity on Home Assistant Reconnects**:
  - Updated `HomeAssistantBridge._on_field_update` in `pwrcell/bridge.py` to publish live raw field state updates with `retain=True` (matching `publish_discovery` and `_on_compound_update`).
  - Prevents Mosquitto from holding stale retained `state_topic` payloads between discovery runs, eliminating false `total_increasing` counter reset spikes in Home Assistant Energy statistics when Home Assistant restarts or reloads MQTT.
  - Added unit test `test_on_field_update_retains_state_to_prevent_stale_broker_values` in `tests/test_bridge.py`.

## [3.1.12] - 2026-11-12

### Fixed
- **PV Link Energy Counter Continuity & Negative Solar Statistics**:
  - Replaced high-water mark clamping with **Cumulative Baseline Offset Tracking** in `StateStore._process_counter_monotonicity`. When a PV Link suffers overnight uncommitted RAM loss at brownout (e.g. dropping 5–250 Wh from dusk to dawn flash recovery), the lost delta is automatically converted into a persistent cumulative offset after 2-poll debounce.
  - **Zero Masking of Morning Solar Generation**: Unlike high-water mark freezing, every watt-hour produced at sunrise is immediately added to the offset baseline and published to Home Assistant, completely eliminating morning generation masking.
  - **No Negative Energy Deltas in Home Assistant**: Prevents Home Assistant long-term statistics compiler from recording negative hourly solar production bars on the Energy Dashboard.
  - Added debounced zero-reset handling (requiring 3 consecutive readings of $\le 1\text{ Wh}$) so clean daily session resets on PV Links or meter rollovers are passed through cleanly without transient glitch vulnerability.
  - Persisted cumulative offsets to `.monotonic_offsets.json` in `data_dir()` so continuity survives add-on restarts.
  - Always suppress corrupt/invalid negative energy readings on cumulative counters.
  - Added comprehensive unit tests in `tests/test_state_and_controls.py` verifying brownout drop offset calculation, unmasked morning generation reporting, and restart persistence.

## [3.1.11] - 2026-11-12

### Changed
- **Management UI Documentation Streamlining**:
  - Removed obsolete ASCII art diagram mockups replaced by screenshots in `docs/management_ui.md`.
  - Streamlined documentation for clarity and conciseness, replacing dense prose with structured tables and crisp operational references.

## [3.1.10] - 2026-11-12

### Added
- **Web Explorer UI Screenshots in Documentation**:
  - Captured actual screenshots from the live Web Explorer in mock simulation mode (`python main.py explore --mock`).
  - Added visual references in `docs/images/` and embedded into `docs/management_ui.md`:
    - `ui_overview_unified.png`: Primary overview dashboard showing live header chips, device tree, minimal polling plan, and unified grid.
    - `ui_rescan_discovery.png`: Device discovery modal showing slave ID range and cache purge option.
    - `ui_all_registers_raw.png`: Raw register map view showing all SunSpec models, scale factors, and wire points.
    - `ui_modbus_details.png`: Modbus Register Definition inspector modal detailing register offsets, types, and scale factor exponents.
    - `ui_telemetry_comparison.png`: Telemetry comparison modal displaying agreement status, discrepancy tabs, and Sync Sample controls.
    - `ui_safety_policy.png`: Blocked Modbus mutation fields modal illustrating safety-protected registers.
    - `ui_mqtt_preview.png`: Home Assistant MQTT discovery JSON preview modal.

## [3.1.9] - 2026-11-12

### Added
- **Management UI (Web Explorer) Technical Documentation**:
  - Added comprehensive [Web Explorer Technical Guide](docs/management_ui.md) in `docs/management_ui.md` targeting technical users, developers, and energy systems engineers.
  - Documented complete architecture (dual-stream MQTT/Modbus ingestion, SSE streaming, weighted set-cover minimal polling optimizer).
  - Detailed guides for all UI components: Header telemetry & system mode control, hardware discovery tree, Unified Semantic vs. Raw register views, minimal model solver with manual source pinning, Modbus register inspector, writable setpoints/bounds validation, telemetry discrepancy analysis & polarity resolution, safety policy enforcement for hazardous registers, and Home Assistant MQTT Discovery management.
  - Added cross-links from `README.md` and `DOCS.md`.

## [3.1.8] - 2026-11-12

### Fixed
- **Grouped Entity HA Discovery Synchronization & Default Config**:
  - In `config/ha_default_config.yaml`: Updated default entity seed configuration to specify canonical compound entity keys (`pv_link.compound.accumulated_energy`, `pv_link.compound.rebus_power`, `pv_link.compound.device_temperature`, `inverter.compound.rebus_voltage`, `battery.compound.max_cell_voltage`, `battery.compound.min_cell_voltage`, `battery.compound.battery_power`, `battery.compound.battery_soc`, `battery.compound.battery_ac_charged_energy`, `battery.compound.battery_ac_discharged_energy`, `inverter.compound.inverter_output_energy`, `inverter.compound.solar_power`, `inverter.compound.system_mode`).
  - In `pwrcell/bridge.py` and `pwrcell/ui/routes/ha.py`: Ensured `/api/ha/preview` and `publish_discovery()` suppress all raw members whose compound view is active, including checking `MappingRegistry.get_raw_to_compound_map()` and mapping candidates to prevent raw register leakage.
- **Inverter Grid Imported Energy Grouping**:
  - In `pwrcell/data/groupings.yaml`: Added `inverter.REbus_exp.Whin`, `inverter.model_64204.Whin`, and `inverter.model_64204.WhIn` (SunSpec Model 64204 REbus Export/Import model registers) to `grid_imported_energy`, grouping them cleanly and eliminating raw entity leakage (`rebus_exp_whin`).
- **Elimination of `_None` Suffixes on Standalone Push Telemetry**:
  - In `pwrcell/optimizer.py` & `pwrcell/ha.py`: Fixed standalone concept key generation for unmapped push telemetry fields where `model_id` is None, generating clean identifiers (e.g. `load_power_w`, `load_imported_energy_wh`, `solar_generation_energy_wh`, `inverter_max_power_w`) without appending malformed `_None` suffixes.

## [3.1.7] - 2026-11-11

### Fixed
- **Inverter Operational State Reporting & Enum Options**: Fixed issue where `Inverter Operational State` was not showing or updating in Home Assistant.
  - In `pwrcell/data/groupings.yaml`: Reordered Modbus candidates for `inverter_state` to prioritize `inverter.model_64207.St` (which contains full Generac SunSpec REbus state symbols) ahead of vendor-specific raw integer points (`StVnd`). Removed obsolete `inverter.concept.inverter_state` from `ungrouped_fields`.
  - In `pwrcell/state.py`: Guaranteed that `inverter_state` compound views always resolve `ha_device_class = "enum"` with complete REbus status symbols (`GRID_CONNECTED`, `STANDBY`, etc.), and automatically convert raw integer codes (`2080`) or numeric strings to their canonical enum symbol name across Modbus, MQTT, and latest values so Home Assistant never receives invalid raw integer states for enum sensors.
  - In `pwrcell/bridge.py`: Set `retain=True` for compound state updates in `_on_compound_update()`, preventing Home Assistant restarts or reconnects from falling back to stale or uninitialized state.
- **System Operating Mode Option Deduplication & Normalization**:
  - In `pwrcell/controls.py`: Added `get_canonical_system_operating_modes()` to provide deduplicated system modes without synonym collisions. Canonicalized written mode names in `set_system_mode()` so that aliases (e.g. `GRID_CONNECT`, `FULL_EXPORT`, `ARBITRAGE`) map to canonical SunSpec names (`GRID_TIE`, `SELL`, `REMOTE_ARBITRAGE`).
  - In `pwrcell/state.py`: Populated `system_mode` compound view options with canonical modes and normalized alias values in `get_compound_view()`, eliminating duplicate synonyms in the Home Assistant select dropdown.
- **Web Explorer Write Modal Enum Dropdown**:
  - In `pwrcell/ui/static/app.js`: Updated `openWriteModal()` and `lookupEnumSymbol()` to detect enum fields via `field.bounds.symbols` and `field.ha_options` in addition to direct `field.symbols`, enabling dropdown selection for merged/compound enum fields like `System Operating Mode` instead of rendering a plain text input.

## [3.1.6] - 2026-11-11

### Fixed
- **Group Selection Generating Multiple HA Entities**: Fixed issue where selecting a single group row in the Web UI (e.g. "Inverter Operational State") resulted in multiple entities in Home Assistant (`sensor.pwrcell_inverter_14e9_inverter_operational_state` and `sensor.pwrcell_inverter_14e9_inverter_state_name`).
  - In `pwrcell/ui/static/app.js`: Updated `toggleHaSelection` and peer device application to only select the compound key (`<SN>:<dev>.compound.<concept>`) for grouped items, never the raw member source keys (`f.active_source_key` or `f.key`), and to clear any individual member selections upon group selection.
  - In `pwrcell/ha.py`: Updated `_LEGACY_CONCEPT_REMAP` to map `inverter.concept.inverter_state` and legacy `inverter.live.inverter_state_name` to `inverter.compound.inverter_state`, and `battery.concept.battery_soh` to `battery.compound.battery_soh`.
  - In `pwrcell/bridge.py`: Expanded member suppression in `publish_discovery()` and `_is_field_suppressed_by_compound()` to include all mapping candidate members (`m.mqtt_fields` and `m.modbus_fields`), ensuring secondary MQTT and Modbus points (like `inverter.live.inverter_state_name`) are properly suppressed and removed from Home Assistant.
  - In `pwrcell/data/groupings.yaml` & `pwrcell/state.py`: Prioritized `inverter.live.inverter_state_name` over numeric `inverter.live.inverter_state` in `inverter_state` mapping, and mapped MQTT `ha_hint.options` and `ha_hint.device_class` onto the compound view, so the unified compound sensor publishes the friendly enum string (e.g. `GRID_CONNECTED`) with declared options in Home Assistant.

## [3.1.5] - 2026-11-10

### Fixed
- **Combined Sensor Jitter & Out-of-Order Delivery**: Fixed combined sensors (MQTT + Modbus) updating from both sources simultaneously. When MQTT is selected for a grouped concept, Modbus updates for that concept are ignored—preventing newer Modbus poll timestamps from overwriting MQTT push telemetry in `StateStore.get_compound_view()`, and suppressing Modbus-triggered compound change dispatches in `set_field()` and `HomeAssistantBridge._on_compound_update()`.
- **System Mode Control Synchronization**: Ensured `set_system_mode()` updates both the Modbus register and the live push telemetry state (`inverter.live.system_mode`) so compound views reflect control mutations immediately without waiting for the next telemetry cycle.
- **Preferred Source Custom Groupings Support**: Added `preferred_sources` configuration support in `pwrcell/grouping.py` for persistent user pinning of sources via `custom_groupings.yaml`.

## [3.1.4] - 2026-11-10

### Fixed
- **Multi-Device Control Dispatch Scoping**: Updated `ControlDispatcher.write_field()` to accept `device_sn` (and parse `<SN>:<field>` prefixes), scoping writes correctly on multi-device systems (e.g. secondary PV Links and multi-battery setups) instead of always defaulting to `devs[0]`.
- **Compound and Concept Control Writes**: Normalized `.concept.` keys to `.compound.` in `ControlDispatcher.write_field()`, scoped compound views to `device_sn`, and prioritized writable Modbus candidates.
- **Home Assistant Command Dispatch Device Context**: Passed device serial numbers through `HomeAssistantBridge._on_message` and `_execute_command_async` into control writes.
- **Safety Blocked Mutation Compound View Audit**: Updated `get_blocked_mutation_fields()` to inspect compound views via `StateStore.get_compound_views()` instead of the nonexistent `.compound_views` attribute.
- **HA Config File I/O Caching**: Added `st_mtime`-based caching with automatic cache invalidation on save for `load_ha_config()` and `load_ha_category_overrides()` in `pwrcell/ha.py`.
- **Category Override Isolation & Deduplication**: Removed unscoped `pt_name_model_id` match candidate in `get_effective_ha_category()` and removed unscoped bare keys from `config/ha_default_config.yaml` to prevent cross-device category bleeding.
- **Internal MQTT Tunnel Port Update**: Hardened `MqttClient` reconnect handling on SSH tunnel reconnect to update `client._port`.
- **Web UI Home Assistant Entity Preview**: Updated unified row preview in Web Explorer JavaScript to generate accurate `haEntityId` using device serial number and platform.
- **Correlator Shim Cleanup**: Re-exported `ComparisonResultRow` properly from `pwrcell/correlator.py` and removed unused shadowed import from `pwrcell/tools/correlator.py`.

## [3.1.3] - 2026-11-10

### Fixed
- **Multi-Device Compound Views**: Resolved single-device lookup collision (`devs[0]`) in `StateStore.get_compound_view()` by adding `device_sn` scoping, enabling compound sensors on secondary PV Links and multi-battery installations.
- **Null Modbus Clobbering Valid Telemetry**: Ensured that polling an unimplemented or sentinel register (returning `None`) does not overwrite valid push telemetry in `get_compound_view()`.
- **Compound View Selection & Remapping**: Updated `qualify_legacy_ha_config()` to remap recognized `<dev>.concept.<id>` keys to `<dev>.compound.<id>` instead of discarding them, and aligned `is_field_selected()` to match `.concept.` and `.compound.` aliases.
- **HA Discovery Race Condition & Duplicate Sensors**: Pre-populated field definitions before compound discovery step in `HomeAssistantBridge.publish_discovery()`, and unpublished raw member sensor discovery topics when compound views are published dynamically.
- **Preview Discovery Filtering**: Updated `/api/ha/preview` to filter out raw member fields suppressed by active compound views.
- **Ungrouping Suppression & Compound Link Refresh**: Added `refresh_compound_links()` to `StateStore` and filtered excluded fields from `modbus_candidates` so ungrouped fields are not hidden from Home Assistant.
- **Dead Code Cleanup in Compound View**: Fixed unreachable dead code assigning `c_view.ha_category` and passed serial number instead of device object.
- **Web UI Compound Key Selection**: Fixed `isFieldSelected()`, `toggleHaSelection()`, and `btnDeselectAll` in Web Explorer JavaScript to properly track, toggle, and clear `.compound.` entity keys.
- **Missing Solar Generation Power Concept**: Restored `solar_power` concept in `groupings.yaml` and removed `battery.live.state_of_health` from `ungrouped_fields`.
- **Default Config Deduplication**: Removed redundant duplicate sibling member keys from `config/ha_default_config.yaml` and `config/ha_config.yaml`.

## [3.1.2] - 2026-11-10

### Added
- Force full device re-scan option and cache clearing in Web Explorer UI:
  - Added Re-scan button and modal to UI with configurable Start and End slave IDs.
  - Added "Force full re-scan (delete existing device cache)" option.
  - Added "Scan for Devices" call-to-action button when the device sidebar is empty.
  - Added `DeviceConfig.delete()` method to safely remove cached `devices.yaml`.
  - Added `SerializedModbusClient.clear_devices()` to clear cached SunSpec client instances.
  - Added `clear_cache` parameter support in `client.rescan_devices()` and `POST /api/devices/rescan`.

## [3.1.1] - 2026-11-07

### Added
- Added "My Home Assistant" one-click add-on repository install badge to `DOCS.md` and `README.md`.

### Fixed
- Fixed Modbus device discovery scan aborting on duplicate unit serial numbers (#14). Defaulted `stop_on_duplicate_serial` to `False` and added duplicate threshold termination to avoid missing devices at higher slave IDs.

## [3.1.0] - 2026-10-27

### Added
- Full functional release of Generac PWRcell SunSpec Gateway and Home Assistant Add-on.
- Integrated Web Explorer accessible via Home Assistant Ingress.
- Native Home Assistant MQTT Auto-Discovery with entity categories (diagnostic, configuration).
- Operating mode control (`SELF_SUPPLY`, `CLEAN_BACKUP`, `PRIORITY_BACKUP`, etc.) with validation.
- Automatic SSH tunneling to Generac Beacon.
- Modbus register and push telemetry inspection and comparison.

## [3.0.18] - 2026-10-27

### Fixed
- Fixed Home Assistant diagnostic category matching and multi-device synchronization.

## [3.0.17] - 2026-10-27

### Security
- Protected inverter zero export settings (`ZExp` and `ZExpLim`) from mutation.

## [3.0.16] - 2026-10-27

### Added
- Safety blocked mutation fields configuration (`config/blocked_fields.yaml`).
- Groupings and Home Assistant default config exports.

## [3.0.15] - 2026-10-27

### Added
- Home Assistant entity category controls and UI table badges.
