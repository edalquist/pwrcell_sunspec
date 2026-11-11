# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
