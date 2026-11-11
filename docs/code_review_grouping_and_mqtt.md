# Code Review: Grouping Logic & Home Assistant MQTT Publishing

## Executive Summary

An in-depth audit of the grouping pipeline (`pwrcell/grouping.py`, `pwrcell/mapping.py`, `pwrcell/optimizer.py`, `pwrcell/concept.py`, `pwrcell/state.py`, `pwrcell/ui/routes/grouping.py`, `pwrcell/ui/static/app.js`) and the Home Assistant MQTT Discovery / state publishing pipeline (`pwrcell/bridge.py`, `pwrcell/ha.py`, `pwrcell/ui/routes/ha.py`, `config/ha_config.yaml`, `config/ha_default_config.yaml`) confirmed **multiple interacting bugs that directly cause duplicate sensors and hidden (missing or non-updating) sensors in Home Assistant**.

At a high level, the root causes fall into four categories:

1. **Incomplete Unification Between the UI Grouping Engine and the MQTT Bridge Engine**:
   - Despite `docs/design_grouping_unification.md` and `pwrcell/concept.py` aliasing `UnifiedFieldGroup = ConceptView` and `CompoundFieldView = ConceptView`, two completely separate grouping engines still exist:
     - **Web UI / Optimizer Engine** (`pwrcell/optimizer.py:group_device_fields`): Produces `ConceptView` objects with IDs `<device_type>.concept.<id>` and `<device_type>.standalone.<id>`, honors `custom_groupings.yaml` (`field_overrides`, `field_transforms`, `custom_concepts`), and uses the minimal-model set-cover solver to pick `active_source_key`.
     - **StateStore / MQTT Bridge Engine** (`pwrcell/state.py:get_compound_view` & `get_compound_views`): Produces `ConceptView` objects with IDs `<device_type>.compound.<id>`, ignores `custom_groupings.yaml` (`custom_concepts`, `field_transforms`, and fields added via `field_overrides`), hardcodes single-device lookup (`devs[0]`), and only checks `c_view.key` and `c_view.mqtt_key` for selection.
2. **Selection Key Stripping & Mismatch Between UI, `ha_config.yaml`, and `HomeAssistantBridge`**:
   - Selecting a grouped row in the Web UI Unified View adds `<sn>:<active_source_key>` and `<sn>:<dev_type>.concept.<id>`.
   - Saving via `POST /api/ha/config` calls `qualify_legacy_ha_config()` (`pwrcell/ha.py:191-227`), which **silently deletes** any `.concept.` key not in the 11-item `_LEGACY_CONCEPT_REMAP` dict (and maps 5 of those 11 to raw keys instead of `.compound.`).
   - `HomeAssistantBridge.publish_discovery()` (`pwrcell/bridge.py:320`) then checks `is_field_selected(c_view.key, dev.serial_number, selected_set, c_view.mqtt_key)`—which **never checks `c_view.modbus_candidates` or `c_view.sources`**. Thus, any concept group without an active `mqtt_key` (all Modbus-only groups, or hybrid groups before MQTT arrives) is treated as unselected, bypassing compound discovery and member suppression.
3. **Startup Race Conditions Between `publish_discovery()` and First Telemetry Arrival**:
   - When `publish_discovery()` runs at startup before live `StateField`s exist in `dev.fields`, `get_compound_view()` returns `None` (or returns a view with `mqtt_key = None` if only Modbus has been polled). Step 2 of `publish_discovery()` then calls `ensure_field_definition()` and publishes **raw sensor discovery topics**. Moments later, when MQTT data arrives, `_on_compound_update()` dynamically publishes the **compound sensor discovery topic** without unpublishing the raw sensor discovery topics, creating permanent duplicate entities in Home Assistant.
4. **Multi-Device Binding Failure (`devs[0]`) and Unsynced Grouping Overrides**:
   - `StateStore.get_compound_view(mapping_id)` takes no `device_sn` parameter and always binds to `devs[0]` (`self.get_devices_by_type(m.device_type)[0]`). For systems with multiple PV Links (e.g., 5 PV Links in `config/devices.yaml`) or multiple batteries, secondary devices receive **zero compound views**.
   - Ungrouping a field in the Web UI leaves it in `c_view.modbus_candidates` (`pwrcell/state.py:881, 1056`) and leaves stale `field.compound_key` on existing `StateField`s, so `HomeAssistantBridge` continues suppressing the ungrouped sensor (hiding it from Home Assistant).

---

## Part 1: Bugs Resulting in Duplicate MQTT Sensors

### Bug D1: Startup / Reconnect Race Publishes Both Raw and Compound Sensors (`pwrcell/bridge.py`, `pwrcell/state.py`)
- **Severity**: Critical
- **Locations**:
  - `pwrcell/bridge.py:315-432` (`HomeAssistantBridge.publish_discovery`)
  - `pwrcell/bridge.py:564-618` (`HomeAssistantBridge._on_compound_update`)
  - `pwrcell/state.py:860-904, 1001-1037` (`StateStore.get_compound_view`)
  - `pwrcell/concept.py:192-194` (`ConceptView.mqtt_key`)
- **Root Cause & Reproduction Trace**:
  1. When `HomeAssistantBridge.start()` connects to the MQTT broker, `_on_connect()` immediately calls `self.publish_discovery()`.
  2. In Step 1 of `publish_discovery()` (`pwrcell/bridge.py:319`), `self.client.state.get_compound_views(dev.serial_number)` is called **before** `self.client.state.ensure_field_definition()` (which only runs in Step 2 at `pwrcell/bridge.py:374`).
  3. **Scenario A (Neither MQTT nor Modbus polled yet)**:
     - Inside `StateStore.get_compound_view()` (`pwrcell/state.py:861-903`), `self._find_field()` and `self.find_fields()` return `None`/`[]` because `dev.fields` is empty.
     - Line 902 (`if not mqtt_field and not mb_fields: return None`) causes `get_compound_views()` to return `[]`.
     - Consequently, `new_active_compounds` and `new_active_member_keys` are **empty**.
     - Step 2 (`pwrcell/bridge.py:363-432`) then iterates over `selected_keys` (which contains raw keys such as `0001000714E9:inverter.live.grid_power_w`, `0001000714E9:inverter.live.solar_power_w`, `000100082128:battery.live.battery_power_w`, `000100082128:battery.REbus_status.P`), calls `ensure_field_definition()` to materialize the raw `StateField`s in `dev.fields`, sees `is_suppressed = False` (because `new_active_compounds` is empty), and **publishes MQTT discovery payloads for the raw sensors** (e.g., `pwrcell_0001000714e9_live_grid_power_w`, `pwrcell_000100082128_live_battery_power_w`, `pwrcell_000100082128_rebus_status_p`).
  4. **Scenario B (Modbus polled first, MQTT snapshot not yet received)**:
     - `get_compound_view("grid_power")` finds `mqtt_field = None` and `mb_field = CTPow`.
     - At `pwrcell/state.py:1002`, `ConceptSource(source_type="MQTT", ...)` is only appended to `sources` `if mqtt_field:`.
     - Therefore `c_view.mqtt_source` is `None`, which makes the `c_view.mqtt_key` property (`pwrcell/concept.py:192`) return `None`! (Notice `mqtt_k` computed at `pwrcell/state.py:878` is never stored on `ConceptView` when `mqtt_field` is `None`!)
     - At `pwrcell/bridge.py:320`, `is_field_selected(c_view.key, dev.serial_number, selected_set, c_view.mqtt_key)` is called with `mqtt_key=None`. Because `ha_config.yaml` stores `0001000714E9:inverter.live.grid_power_w` (not `inverter.compound.grid_power`), `is_field_selected` returns `False`.
     - Step 2 then materializes `inverter.live.grid_power_w` via `ensure_field_definition()` and publishes the raw sensor `pwrcell_0001000714e9_live_grid_power_w`.
  5. **When the first MQTT message arrives**:
     - `StateStore.set_field()` updates `inverter.live.grid_power_w` and fires `_on_compound_update(c_view)` (`pwrcell/bridge.py:564-618`).
     - Now `c_view.mqtt_key` is `"inverter.live.grid_power_w"`, so `is_field_selected(c_view.key, c_view.device_sn, selected_snapshot, c_view.mqtt_key)` returns `True`.
     - `_on_compound_update` sees `config_topic not in self._published_discovery_topics` (`pwrcell/bridge.py:596`) and publishes discovery for the **compound sensor** (`pwrcell_0001000714e9_grid_power`) **without unpublishing the already-published raw sensor(s)**.
     - Worse, `_is_field_suppressed_by_compound()` now suppresses all future state updates to the raw sensor, leaving duplicate sensors in Home Assistant where one is permanently stale/`unknown`.

#### Suggested Fix for Bug D1
1. **In `pwrcell/bridge.py` (`publish_discovery`, lines 315–375)**: Move the `ensure_field_definition` pre-population loop **before** Step 1 (`get_compound_views`), and also pre-populate member fields for any selected `.compound.` or `.concept.` keys:
```python
        for dev in self.client.state.get_devices_snapshot():
            sn_clean = dev.serial_number.strip().upper()
            self._publish_device_availability(dev, force=True)

            # 0. Pre-populate metadata for any selected fields (and compound members) not yet polled
            reg = MappingRegistry.get_instance()
            for sel_key in selected_keys:
                if ":" in sel_key:
                    target_sn, f_path = sel_key.split(":", 1)
                    if target_sn.strip().upper() != sn_clean:
                        continue
                else:
                    f_path = sel_key
                    if not f_path.startswith(f"{dev.device_type}."):
                        continue

                if f_path.startswith(f"{dev.device_type}.compound.") or f_path.startswith(f"{dev.device_type}.concept."):
                    cid = f_path.split(".")[-1]
                    m = reg.get_by_id(cid)
                    if m and m.device_type == dev.device_type:
                        for cand in m.all_fields:
                            if cand not in dev.fields:
                                self.client.state.ensure_field_definition(dev.serial_number, cand)
                elif f_path not in dev.fields:
                    self.client.state.ensure_field_definition(dev.serial_number, f_path)

            # 1. Publish selected compound fields
            for c_view in self.client.state.get_compound_views(dev.serial_number):
```
2. **In `pwrcell/state.py` (`get_compound_view`, lines 1001–1018)**: Even if `mqtt_field` is `None` (not yet received), if `m.mqtt_field` is configured and not excluded by `is_field_excluded_from_mapping(target_sn, m.mqtt_field, m.id, custom_data)`, include a placeholder `ConceptSource(source_type="MQTT", source_id="MQTT", field_key=m.mqtt_field, ...)` (or set `mqtt_key` on `ConceptView`) so `c_view.mqtt_key` is always known at startup.
3. **In `pwrcell/bridge.py` (`_on_compound_update`, lines 572–612)**: When `_on_compound_update` activates a compound view, record all its member keys in `self._active_member_keys` and unpublish any raw member discovery topics that were previously published:
```python
        with self._lock:
            self._active_compound_keys.add(cache_key)
            if getattr(c_view, "mqtt_key", None):
                self._active_member_keys.add(f"{clean_sn}:{c_view.mqtt_key}")
            for cand in getattr(c_view, "modbus_candidates", []):
                self._active_member_keys.add(f"{clean_sn}:{cand}")
            for s in getattr(c_view, "sources", []):
                if getattr(s, "field_key", None):
                    self._active_member_keys.add(f"{clean_sn}:{s.field_key}")
            payload_info = self._payload_info_cache.get(cache_key)
```

---

### Bug D2: `is_field_selected()` Ignores Modbus Member Keys & `qualify_legacy_ha_config()` Strips `.concept.` Keys (`pwrcell/ha.py`, `pwrcell/bridge.py`, `pwrcell/ui/static/app.js`)
- **Severity**: Critical
- **Locations**:
  - `pwrcell/ha.py:114-138` (`is_field_selected`)
  - `pwrcell/ha.py:176-227` (`_LEGACY_CONCEPT_REMAP`, `qualify_legacy_ha_config`)
  - `pwrcell/bridge.py:320, 504, 570` (`publish_discovery`, `_is_field_suppressed_by_compound`, `_on_compound_update`)
  - `pwrcell/ui/static/app.js:768-805` (`toggleHaSelection`)
- **Root Cause & Reproduction Trace**:
  1. In `pwrcell/ui/static/app.js:768-785`, checking a grouped row in Unified View adds `scopedPrimaryKey` (`<sn>:<active_source_key>`, e.g., `000100034AC7:pv_link.REbus_status.I`) and `scopedId` (`000100034AC7:pv_link.concept.rebus_current`). It never adds `<sn>:<dev_type>.compound.<id>`.
  2. When saved via `POST /api/ha/config`, `qualify_legacy_ha_config()` (`pwrcell/ha.py:207-210`) checks:
     ```python
     if field_part in _LEGACY_CONCEPT_REMAP:
         field_part = _LEGACY_CONCEPT_REMAP[field_part]
     elif ".concept." in field_part or field_part.endswith("_None"):
         continue
     ```
     Because `_LEGACY_CONCEPT_REMAP` only contains 11 hardcoded entries, `000100034AC7:pv_link.concept.rebus_current` (along with 25+ other standard concepts in `groupings.yaml` and all custom concepts) is **silently stripped**.
  3. Only the raw Modbus key (or multiple raw Modbus keys if selected via defaults/recommended/raw view) remains in `ha_config.yaml`.
  4. In `HomeAssistantBridge.publish_discovery()` (`pwrcell/bridge.py:320`), Step 1 checks:
     ```python
     if is_field_selected(c_view.key, dev.serial_number, selected_set, c_view.mqtt_key):
     ```
     `is_field_selected()` (`pwrcell/ha.py:114-138`) **only** checks `c_view.key` (`<dev_type>.compound.<id>`) and `c_view.mqtt_key` (which is `None` for all Modbus-only groups such as `rebus_voltage`, `rebus_power`, `rebus_current`, `cabinet_temperature`, `phase_a_voltage`, `battery_temperature`, `battery_voltage`, `max_charge_power`, `max_discharge_power`).
  5. Because `is_field_selected()` returns `False`, the compound view is not published and its members are not added to `new_active_member_keys`.
  6. In Step 2 (`pwrcell/bridge.py:376-432`), every selected raw member field is published as an individual sensor. In the current `config/ha_config.yaml` and `config/ha_default_config.yaml`, this immediately produces duplicate sensors for:
     - **Every PV Link (`000100034AC7`, `000100034E68`, `000100034FAC`, `0001000361C7`, `0001000361F4`)**: Both `pv_link.REbus_status.I` ("DC Current") AND `pv_link.string_combiner.DCA` ("DC Current") are published as separate sensors on all 5 PV Links.
     - **Inverter (`0001000714E9`)**: Both `inverter.REbus_status.V` ("Bus Voltage") AND `inverter.inverter.DCV` ("DC Voltage") are published as separate sensors despite belonging to `rebus_voltage`.
     - **Battery (`000100082128`)**: Both `battery.REbus_status.T` AND `battery.lithium_ion_string.ModTmpAvg` are published as separate sensors despite belonging to `battery_temperature`.

#### Suggested Fix for Bug D2
1. **In `pwrcell/ha.py` (`is_field_selected`, lines 114–138)**: Accept `candidate_keys: Optional[Iterable[str]] = None` (or add `is_compound_selected(c_view, device_sn, selected_keys)`) so a compound view matches if its `.compound.` key, `.concept.` key, `mqtt_key`, or any active member key in `c_view.modbus_candidates` / `c_view.sources` is selected:
```python
def is_field_selected(
    field_key: str,
    device_sn: Optional[str],
    selected_keys: List[str] | Set[str],
    mqtt_key: Optional[str] = None,
    candidate_keys: Optional[List[str]] = None,
) -> bool:
    """Check if a field or compound view is selected."""
    if not selected_keys:
        return False
    s_set = selected_keys if isinstance(selected_keys, set) else set(selected_keys)

    check_keys = [field_key]
    if ".compound." in field_key:
        check_keys.append(field_key.replace(".compound.", ".concept."))
    if mqtt_key:
        check_keys.append(mqtt_key)
    if candidate_keys:
        check_keys.extend(k for k in candidate_keys if k)

    if device_sn:
        prefix = f"{device_sn.strip().upper()}:"
        for k in check_keys:
            if f"{prefix}{k}" in s_set:
                return True

    for k in check_keys:
        if k in s_set:
            return True
    return False
```
2. **In `pwrcell/bridge.py` (lines 320, 504, 570)** and **`pwrcell/ui/routes/ha.py` (line 369)**: Pass `candidate_keys=getattr(c_view, "modbus_candidates", None)` to `is_field_selected(...)`:
```python
if is_field_selected(
    c_view.key,
    dev.serial_number,
    selected_set,
    getattr(c_view, "mqtt_key", None),
    candidate_keys=getattr(c_view, "modbus_candidates", None),
):
```
3. **In `pwrcell/ha.py` (`qualify_legacy_ha_config`, lines 191–227)**: Instead of dropping `.concept.` keys, remap any `<dev_type>.concept.<cid>` that corresponds to a known mapping in `MappingRegistry` (or `custom_concepts` in `custom_groupings.yaml`) to `<dev_type>.compound.<cid>`:
```python
def _remap_concept_key(field_part: str) -> Optional[str]:
    if field_part in _LEGACY_CONCEPT_REMAP:
        return _LEGACY_CONCEPT_REMAP[field_part]
    if field_part.endswith("_None"):
        return None
    if ".concept." in field_part:
        dev_type, _, cid = field_part.partition(".concept.")
        reg = MappingRegistry.get_instance()
        if reg.get_by_id(cid):
            return f"{dev_type}.compound.{cid}"
        from .grouping import load_custom_groupings
        if cid in (load_custom_groupings().get("custom_concepts") or {}):
            return f"{dev_type}.compound.{cid}"
        return None
    return field_part
```

---

### Bug D3: `get_recommended_field_keys()` and `ha_default_config.yaml` Select Multiple Members of the Same Group (`pwrcell/ha.py`, `config/ha_default_config.yaml`, `config/ha_config.yaml`, `pwrcell/data/groupings.yaml`)
- **Severity**: High
- **Locations**:
  - `pwrcell/ha.py:505-565` (`get_recommended_field_keys`)
  - `pwrcell/data/groupings.yaml:424-426` (`ungrouped_fields`)
  - `config/ha_default_config.yaml:4-79`
  - `config/ha_config.yaml:1-98`
- **Root Cause**:
  `get_recommended_field_keys()` and `config/ha_default_config.yaml` include multiple raw and compound keys that belong to the same concept in `pwrcell/data/groupings.yaml`:
  - `rebus_voltage` (Inverter): `inverter.inverter.DCV` + `inverter.REbus_status.V`
  - `inverter_output_power` (Inverter): `inverter.compound.inverter_output_power` + `inverter.live.inverter_output_power_w` + `inverter.inverter.W`
  - `grid_exported_energy` (Inverter): `inverter.compound.grid_exported_energy` + `inverter.inverter_status.WhOut` + `inverter.live.inverter_output_exported_energy_wh`
  - `grid_imported_energy` (Inverter): `inverter.compound.grid_imported_energy` + `inverter.inverter_status.WhIn` + `inverter.REbus_exp.Whin`
  - `battery_power` (Battery): `battery.live.battery_power_w` + `battery.REbus_status.P`
  - `battery_temperature` (Battery): `battery.REbus_status.T` + `battery.lithium_ion_string.ModTmpAvg`
  - `battery_soh` (Battery): `battery.live.state_of_health` + `battery.battery.SoH` — because `battery.live.state_of_health` is in `ungrouped_fields` in `pwrcell/data/groupings.yaml:425`, **both** are published to Home Assistant as duplicate State of Health sensors!
  - `battery_exported_energy` / `battery_imported_energy` (Battery): `battery.compound.battery_exported_energy` + `battery.live.storage_ac_discharged_energy_wh` and `battery.compound.battery_imported_energy` + `battery.live.storage_ac_charged_energy_wh`
  - `rebus_current` (PV Link): `pv_link.REbus_status.I` + `pv_link.string_combiner.DCA`
  - `rebus_voltage` (PV Link): `pv_link.REbus_status.V` + `pv_link.string_combiner.DCV`
  - `system_mode` (Inverter & Beacon): `inverter.live.system_mode` + `rebus_beacon.REbus_dir.SysMd`

#### Suggested Fix for Bug D3
1. **In `pwrcell/data/groupings.yaml:424-426`**: Remove `battery.live.state_of_health` from `ungrouped_fields` so `battery_soh` (`pwrcell/data/groupings.yaml:307-319`) properly merges `battery.live.state_of_health` and `battery.battery.SoH`:
```yaml
ungrouped_fields:
- inverter.concept.inverter_state
```
2. **In `pwrcell/ha.py` (`get_recommended_field_keys`) and `config/ha_default_config.yaml`**: Remove redundant sibling member fields so each concept is represented once:
   - Remove `pv_link.string_combiner.DCA` and `pv_link.string_combiner.DCV` (covered by `pv_link.REbus_status.I` / `pv_link.compound.rebus_current` and `pv_link.REbus_status.V` / `pv_link.compound.rebus_voltage`).
   - Remove `inverter.REbus_status.V` (covered by `inverter.inverter.DCV` / `inverter.compound.rebus_voltage`).
   - Remove `battery.REbus_status.P` (covered by `battery.live.battery_power_w` / `battery.compound.battery_power`).
   - Remove `battery.REbus_status.T` (covered by `battery.lithium_ion_string.ModTmpAvg` / `battery.compound.battery_temperature`).
   - Remove `rebus_beacon.REbus_dir.SysMd` (covered by `inverter.live.system_mode` / `inverter.compound.system_mode`).

---

### Bug D4: Incomplete Member Suppression in `_is_field_suppressed_by_compound()` (`pwrcell/bridge.py`, `pwrcell/state.py`)
- **Severity**: High
- **Locations**:
  - `pwrcell/state.py:880-900, 1018-1036` (`StateStore.get_compound_view`)
  - `pwrcell/bridge.py:489-510` (`HomeAssistantBridge._is_field_suppressed_by_compound`)
- **Root Cause**:
  1. In `StateStore.get_compound_view()` (`pwrcell/state.py:911, 1018`), `c_view.sources` only includes **at most one** Modbus `StateField` (`mb_field = mb_fields[0]`), even when `m.modbus_fields` has multiple Modbus registers on the same device (e.g., `REbus_status.I` and `string_combiner.DCA`, or `REbus_status.T` and `lithium_ion_string.ModTmpAvg`).
  2. In `HomeAssistantBridge._is_field_suppressed_by_compound()` (`pwrcell/bridge.py:502`), the fallback check does:
     ```python
     is_member = any(getattr(s, "field_key", None) == field.key for s in getattr(c_view, "sources", []))
     ```
     It does **not** check `field.key in getattr(c_view, "modbus_candidates", [])` or `field.key == getattr(c_view, "mqtt_key", None)`.

#### Suggested Fix for Bug D4
Update `_is_field_suppressed_by_compound()` in `pwrcell/bridge.py:500-509`:
```python
        c_views = self.client.state.get_compound_views(field.device_sn)
        for c_view in c_views:
            is_member = (
                field.key == getattr(c_view, "mqtt_key", None)
                or field.key in getattr(c_view, "modbus_candidates", [])
                or any(getattr(s, "field_key", None) == field.key for s in getattr(c_view, "sources", []))
                or (field.compound_key and c_view.key == field.compound_key)
            )
            if is_member:
                if is_field_selected(
                    c_view.key,
                    field.device_sn,
                    selected_snapshot,
                    getattr(c_view, "mqtt_key", None),
                    candidate_keys=getattr(c_view, "modbus_candidates", None),
                ):
                    with self._lock:
                        self._active_compound_keys.add(f"{clean_sn}:{c_view.key}")
                        self._active_member_keys.add(f"{clean_sn}:{field.key}")
                    return True
        return False
```

---

### Bug D5: `/api/ha/preview` Does Not Filter Out Raw Fields Suppressed by Compound Views (`pwrcell/ui/routes/ha.py`)
- **Severity**: Medium
- **Location**: `pwrcell/ui/routes/ha.py:363-395` (`preview_ha_discovery`)
- **Root Cause**:
  Unlike `HomeAssistantBridge.publish_discovery()` (`pwrcell/bridge.py:321-395`), `preview_ha_discovery()` loops over `client.state.get_compound_views(dev.serial_number)` and then loops over `dev.fields.values()` **without tracking `active_member_keys` or `active_compounds`**. As a result, the "Preview HA MQTT Discovery" modal in the Web UI shows duplicate discovery payloads for both the compound view and its raw member(s).

#### Suggested Fix for Bug D5
Update `pwrcell/ui/routes/ha.py:363-395` to track and skip suppressed member fields just like `HomeAssistantBridge.publish_discovery()`:
```python
        for dev in client.state.devices.values():
            sn_clean = dev.serial_number.strip().upper()
            active_compounds = set()
            active_members = set()

            # 1. Compound fields
            for c_view in client.state.get_compound_views(dev.serial_number):
                if is_field_selected(
                    c_view.key,
                    dev.serial_number,
                    selected_set,
                    c_view.mqtt_key,
                    candidate_keys=getattr(c_view, "modbus_candidates", None),
                ):
                    active_compounds.add(f"{sn_clean}:{c_view.key}")
                    if c_view.mqtt_key:
                        active_members.add(f"{sn_clean}:{c_view.mqtt_key}")
                    for cand in getattr(c_view, "modbus_candidates", []):
                        active_members.add(f"{sn_clean}:{cand}")
                    for s in getattr(c_view, "sources", []):
                        if getattr(s, "field_key", None):
                            active_members.add(f"{sn_clean}:{s.field_key}")
                    payload_info = generate_discovery_payload(
                        c_view, dev, gateway_device=gateway, category_overrides=cat_overrides
                    )
                    entities.append(payload_info)

            # 2. Raw fields (skipping members suppressed by active compound views)
            for f_key, field in dev.fields.items():
                if (
                    f"{sn_clean}:{f_key}" in active_members
                    or (field.compound_key and f"{sn_clean}:{field.compound_key}" in active_compounds)
                ):
                    continue
                if is_field_selected(f_key, dev.serial_number, selected_set):
                    payload_info = generate_discovery_payload(
                        field, dev, gateway_device=gateway, category_overrides=cat_overrides
                    )
                    entities.append(payload_info)
```

---

## Part 2: Bugs Resulting in Hidden (Missing or Non-Updating) MQTT Sensors

### Bug H1: Multi-Device Compound View Collision (`devs[0]`) Hides Compound Sensors on Secondary PV Links & Batteries (`pwrcell/state.py`)
- **Severity**: Critical
- **Locations**:
  - `pwrcell/state.py:827-905` (`StateStore.get_compound_view`)
  - `pwrcell/state.py:1069-1078` (`StateStore.get_compound_views`)
  - `pwrcell/state.py:1410-1431` (`StateStore.set_field`)
- **Root Cause & Reproduction Trace**:
  1. `StateStore.get_compound_view(self, mapping_id: str)` does **not** accept a `device_sn` parameter.
  2. At `pwrcell/state.py:838-854`, it resolves `target_dev` as:
     ```python
     if m.mqtt_field.startswith("inverter."):
         target_dev = self.get_inverter()
     elif m.mqtt_field.startswith("battery."):
         target_dev = self.get_battery()
     elif m.mqtt_field.startswith("rebus_beacon."):
         target_dev = self.get_beacon()

     if not target_dev:
         devs = self.get_devices_by_type(m.device_type)
         if devs:
             target_dev = devs[0]
     ```
  3. Then `StateStore.get_compound_views(self, device_sn: Optional[str] = None)` (`pwrcell/state.py:1069-1078`) loops over `reg.get_all()`, calls `self.get_compound_view(m.id)`, and filters by `view.device_sn == device_sn`.
  4. In a system with multiple devices of the same type—such as the 5 `pv_link` devices in `config/devices.yaml` (`000100034AC7`, `000100034E68`, `000100034FAC`, `0001000361C7`, `0001000361F4`) or multiple batteries:
     - `get_compound_view(m.id)` **always** binds `target_dev` to `devs[0]` (`000100034AC7`).
     - For PV Links #2, #3, #4, and #5 (`000100034E68`, `000100034FAC`, `0001000361C7`, `0001000361F4`), `view.device_sn == device_sn` is always `False`, so `get_compound_views(device_sn)` returns `[]`!
     - Any compound sensor on PV Links #2–#5 (or a 2nd battery) is **100% hidden (never published to MQTT)**.
  5. Worse still:
     - Inside `get_compound_view()` (`pwrcell/state.py:885`), `fields = self.find_fields(cand_key)` searches across **all** devices of that type! For non-summing mappings (like `rebus_power`, `rebus_voltage`, `rebus_current` on `pv_link`), `mb_field = mb_fields[0]` grabs whichever PV Link happened to be first or had a value!
     - Inside `StateStore.set_field()` (`pwrcell/state.py:1416`), whenever PV Link #2, #3, #4, or #5 updates a field, `self.get_compound_view(mapping.id)` recomputes PV Link #1's compound view instead of the updating device's compound view!

#### Suggested Fix for Bug H1
1. **In `pwrcell/state.py` (`get_compound_view` & `get_compound_views`, lines 827–905 and 1069–1078)**: Add `device_sn: Optional[str] = None` to `get_compound_view()`, scope field lookups to `target_dev.fields` (except when `should_sum` is `True` across `pv_link` devices for `inverter.compound.solar_power`), and iterate per device in `get_compound_views()`:
```python
    def _find_device_field(self, dev: UnifiedDevice, key: str) -> Optional[StateField]:
        """Find a StateField on a specific device by exact key or point suffix."""
        if key in dev.fields:
            return dev.fields[key]
        parts = key.split(".")
        if len(parts) >= 3:
            target_dev_type = parts[0]
            target_point = parts[-1]
            if dev.device_type == target_dev_type:
                for f_key, f_obj in list(dev.fields.items()):
                    if f_key.endswith(f".{target_point}") and f_obj.source != FieldSource.MQTT_PUSH:
                        return f_obj
        return None

    def get_compound_view(self, mapping_id: str, device_sn: Optional[str] = None) -> Optional[CompoundFieldView]:
        """Compute compound view for a specific mapping id on a target device."""
        reg = MappingRegistry.get_instance()
        m = reg.get_by_id(mapping_id)
        if not m:
            return None

        target_dev = self.get_device(device_sn) if device_sn else None
        if target_dev and m.device_type and target_dev.device_type != m.device_type:
            return None

        if not target_dev:
            if m.mqtt_field.startswith("inverter."):
                target_dev = self.get_inverter()
            elif m.mqtt_field.startswith("battery."):
                target_dev = self.get_battery()
            elif m.mqtt_field.startswith("rebus_beacon."):
                target_dev = self.get_beacon()
            if not target_dev:
                devs = self.get_devices_by_type(m.device_type)
                target_dev = devs[0] if devs else (self.get_inverter() or self.get_beacon())
        if not target_dev:
            return None
```
And for looking up `mb_fields` inside `get_compound_view()` (lines 880–900):
```python
        should_sum = (
            m.transform in ("sum", "sum_all", "sum_devices")
            or m.id == "solar_power"
            or ( any(c.startswith("pv_link.") for c in m.modbus_fields) and m.mqtt_field == "inverter.live.solar_power_w" )
        )
        candidates = [
            cand_key for cand_key in m.modbus_fields
            if not is_field_excluded_from_mapping(target_sn, cand_key, m.id, custom_data)
        ]
        mb_fields: List[StateField] = []
        chosen_cand_key = candidates[0] if candidates else ""
        for cand_key in candidates:
            if should_sum:
                fields = self.find_fields(cand_key)
            else:
                f_single = self._find_device_field(target_dev, cand_key)
                fields = [f_single] if f_single else []
            valid_fields = [
                f for f in fields
                if not is_field_excluded_from_mapping(getattr(f, "device_sn", None) or target_sn, f.key, m.id, custom_data)
            ]
            if valid_fields and any(f.value is not None for f in valid_fields):
                mb_fields = valid_fields
                chosen_cand_key = cand_key
                break
        if not mb_fields and chosen_cand_key:
            if should_sum:
                fields = self.find_fields(chosen_cand_key)
            else:
                f_single = self._find_device_field(target_dev, chosen_cand_key)
                fields = [f_single] if f_single else []
            mb_fields = [
                f for f in fields
                if not is_field_excluded_from_mapping(getattr(f, "device_sn", None) or target_sn, f.key, m.id, custom_data)
            ]
```
And in `get_compound_views()` (`pwrcell/state.py:1069-1078`):
```python
    def get_compound_views(self, device_sn: Optional[str] = None) -> List[CompoundFieldView]:
        """Compute all compound views, optionally filtered by device_sn."""
        reg = MappingRegistry.get_instance()
        views: List[CompoundFieldView] = []
        target_devices = [self.get_device(device_sn)] if device_sn else self.get_devices_snapshot()
        for dev in target_devices:
            if not dev:
                continue
            for m in reg.get_all():
                if m.device_type == dev.device_type:
                    view = self.get_compound_view(m.id, device_sn=dev.serial_number)
                    if view:
                        views.append(view)
        return views
```
2. **In `pwrcell/state.py` (`set_field`, lines 1412–1417)**: Pass `device_sn` when resolving the affected compound view:
```python
        if changed and compound_listeners:
            reg = MappingRegistry.get_instance()
            mapping = reg.get_by_mqtt(key) or reg.find_mapping_for_modbus(key)
            if mapping:
                target_comp_sn = device_sn if mapping.device_type == dev.device_type else None
                affected_view = self.get_compound_view(mapping.id, device_sn=target_comp_sn)
```

---

### Bug H2: Ungrouped Fields Remain Suppressed (Hidden) in MQTT Because `modbus_candidates` Is Unfiltered & `StateField.compound_key` Is Not Refreshed (`pwrcell/state.py`, `pwrcell/ui/routes/grouping.py`, `pwrcell/bridge.py`)
- **Severity**: Critical
- **Locations**:
  - `pwrcell/state.py:881, 1056` (`StateStore.get_compound_view`)
  - `pwrcell/state.py:1377-1387` (`StateStore.set_field`)
  - `pwrcell/ui/routes/grouping.py:212-403` (grouping override/ungroup/reset routes)
  - `pwrcell/bridge.py:324-325, 377-380` (`HomeAssistantBridge.publish_discovery`)
- **Root Cause & Reproduction Trace**:
  1. When a user ungroups a field from a concept in the Web UI (`POST /api/grouping/override` with `target_concept: null` or `POST /api/grouping/ungroup_all`), `set_field_grouping_override()` writes `"000100082128:battery.REbus_status.P": None` into `custom_groupings.yaml`.
  2. However, in `StateStore.get_compound_view()` (`pwrcell/state.py:881, 1056`), `candidates = list(m.modbus_fields)` is **unfiltered** by `is_field_excluded_from_mapping()` and passed directly to `ConceptView(modbus_candidates=candidates)`!
  3. Furthermore, none of the grouping routes in `pwrcell/ui/routes/grouping.py` refresh `field.compound_key` or `field.mqtt_equivalent` on existing `StateField` objects in `client.state.devices[sn].fields`, so `field.compound_key` remains `"battery.compound.battery_power"` until the next poll!
  4. When `HomeAssistantBridge.publish_discovery()` runs (`pwrcell/bridge.py:324-325, 377-380`):
     ```python
     for cand in getattr(c_view, "modbus_candidates", []):
         new_active_member_keys.add(f"{sn_clean}:{cand}")
     ...
     is_suppressed = (
         f"{sn_clean}:{f_key}" in new_active_member_keys
         or (field.compound_key and f"{sn_clean}:{field.compound_key}" in new_active_compounds)
     )
     ```
     Both conditions evaluate to `True` for the ungrouped field!
  5. Result: `HomeAssistantBridge` **unpublishes and suppresses the ungrouped field** even though the user explicitly ungrouped it and selected it in the Web UI.

#### Suggested Fix for Bug H2
1. **In `pwrcell/state.py` (`get_compound_view`, line 881)**: Filter `candidates` using `is_field_excluded_from_mapping(target_sn, cand_key, m.id, custom_data)` so excluded/ungrouped fields are never included in `c_view.modbus_candidates`:
```python
        candidates = [
            cand_key for cand_key in m.modbus_fields
            if not is_field_excluded_from_mapping(target_sn, cand_key, m.id, custom_data)
        ]
```
2. **In `pwrcell/state.py` (add `refresh_compound_links` method to `StateStore`)**: Add a method to recompute `compound_key` and `mqtt_equivalent` on all existing `StateField`s whenever grouping overrides change:
```python
    def refresh_compound_links(self, device_sn: Optional[str] = None) -> None:
        """Re-evaluate compound_key and mqtt_equivalent on existing StateFields after grouping changes."""
        from .grouping import load_custom_groupings, is_field_excluded_from_mapping
        custom_data = load_custom_groupings()
        mb_to_mqtt = get_active_modbus_to_mqtt_mapping()
        raw_to_comp = get_active_raw_to_compound_mapping()
        overrides = custom_data.get("field_overrides", {}) or {}

        with self._lock:
            target_devs = [self.get_device(device_sn)] if device_sn else list(self.devices.values())
            for dev in target_devs:
                if not dev:
                    continue
                for f_key, f_obj in dev.fields.items():
                    mqtt_eq = mb_to_mqtt.get(f_key)
                    c_key = raw_to_comp.get(f_key) or (raw_to_comp.get(mqtt_eq) if mqtt_eq else None)
                    qual_key = f"{dev.serial_number.strip().upper()}:{f_key}"
                    override_target = overrides.get(qual_key, overrides.get(f_key))
                    if override_target and str(override_target).strip().lower() not in ("", "null", "none", "standalone", "ungrouped"):
                        c_key = f"{dev.device_type}.compound.{str(override_target).strip()}"
                    elif c_key:
                        cid = c_key.split(".")[-1]
                        if is_field_excluded_from_mapping(dev.serial_number, f_key, cid, custom_data):
                            c_key = None
                            mqtt_eq = None
                    f_obj.mqtt_equivalent = mqtt_eq
                    f_obj.compound_key = c_key
                    f_obj.is_compound_raw = bool(c_key)
```
3. **In `pwrcell/ui/routes/grouping.py`**: Call `client.state.refresh_compound_links(device_sn)` (and `if getattr(client, "bridge", None): client.bridge.publish_discovery()`) at the end of `/api/grouping/override`, `/api/grouping/reset`, `/api/grouping/invert`, `/api/grouping/ungroup_all`, `/api/grouping/suggestions/approve`, `/api/grouping/suggestions/batch-approve`, and `/api/grouping/reset_defaults`.

---

### Bug H3: Custom Concepts, Overridden Member Fields & Polarity Transforms in `custom_groupings.yaml` Are Ignored by `StateStore.get_compound_view()` (`pwrcell/state.py`, `pwrcell/grouping.py`)
- **Severity**: High
- **Locations**:
  - `pwrcell/state.py:827-926, 1069-1078` (`StateStore.get_compound_view`, `StateStore.get_compound_views`)
  - `pwrcell/grouping.py:212-256, 290-310, 353-416` (`set_field_grouping_override`, `approve_suggestions`)
- **Root Cause & Reproduction Trace**:
  1. When a user approves a correlation suggestion or groups fields into a new concept (or adds a new field to an existing concept) in the Web UI, `pwrcell/grouping.py` writes to `custom_groupings.yaml`:
     - `field_overrides`: `{"<SN>:<field_key>": "<target_concept>"}`
     - `field_transforms`: `{"<SN>:<field_key>": "negate"}`
     - `custom_concepts`: `{"<target_concept>": {"label": "...", "transform": "..."}}`
  2. While `optimizer.py:group_device_fields()` reads all three sections of `custom_groupings.yaml` for the Web UI, `StateStore.get_compound_view()` and `StateStore.get_compound_views()` (`pwrcell/state.py:827-1078`):
     - Only iterate over `MappingRegistry.get_instance().get_all()` (`groupings.yaml`), **completely ignoring `custom_concepts`**!
     - Only inspect `m.mqtt_fields` and `m.modbus_fields` from `MappingRegistry`, **never adding fields assigned to `m.id` via `custom_data["field_overrides"]`**!
     - Only apply `m.transform` (`pwrcell/state.py:918, 925`), **completely ignoring per-field polarity inversions in `custom_data["field_transforms"]`** (such as clicking `± Invert` in the Web UI or approving a negative-polarity suggestion)!

#### Suggested Fix for Bug H3
In `pwrcell/state.py` (`get_compound_view` and `get_compound_views`):
1. Merge any fields from `custom_data["field_overrides"]` whose target matches `m.id` (for `target_sn`) into `mqtt_candidates` (if `.live.`) or `candidates` (if Modbus).
2. When computing `mb_val` (`pwrcell/state.py:922-925`), check `custom_data["field_transforms"]` for `f"{target_sn}:{mb_k}"` or `mb_k` before falling back to `m.transform`:
```python
        field_transforms = custom_data.get("field_transforms", {}) or {}
        eff_transform = (
            field_transforms.get(f"{target_sn}:{mb_k}")
            or field_transforms.get(mb_k)
            or (custom_data.get("custom_concepts", {}).get(m.id, {}) or {}).get("transform")
            or m.transform
        )
        mb_val = apply_transform(mb_raw, eff_transform)
```
3. In `get_compound_views()`, also iterate over `custom_data.get("custom_concepts", {})` (or any target concept in `field_overrides` not already in `MappingRegistry`) so user-created concepts are published as compound entities to Home Assistant.

---

### Bug H4: Optimizer Unconditionally Injects `VirtualField` MQTT Sources, Preventing Modbus Fallback Polling When MQTT Is Absent (`pwrcell/optimizer.py`, `pwrcell/poller.py`)
- **Severity**: High
- **Locations**:
  - `pwrcell/optimizer.py:316-332` (`group_device_fields`)
  - `pwrcell/optimizer.py:581-598` (`solve_minimal_polling_plan`)
  - `pwrcell/poller.py:201-257` (`BackgroundPoller._get_active_models_for_device`)
- **Root Cause & Reproduction Trace**:
  1. In `group_device_fields(device)` (`pwrcell/optimizer.py:316-332`), Step 3 unconditionally injects a `VirtualField` with `source="MQTT_PUSH"`, `value=None`, and `last_updated=0.0` for every `m.mqtt_field` in `MappingRegistry.get_all()`, even if no MQTT push stream is active or that MQTT field has never been received on `device`.
  2. Next, `solve_minimal_polling_plan()` (`pwrcell/optimizer.py:581-598`) checks:
     ```python
     has_mqtt = any(s.source_type == "MQTT" for s in grp.sources)
     if has_mqtt:
         mqtt_covered.append(grp.id)
         assignments[grp.id] = "MQTT"
     ```
  3. Because the `VirtualField` has `source_type == "MQTT"`, `has_mqtt` is **always `True`** for every hybrid concept (`grid_power`, `home_load_power`, `solar_power`, `battery_power`, `battery_soc`, `system_mode`, etc.), even when `s.value is None`!
  4. As a result, `solve_minimal_polling_plan()` marks those concepts as covered by `"MQTT"` and **omits their Modbus models from `minimal_models`**.
  5. For models that have no other selected non-MQTT fields in `ha_config.yaml`—specifically **Inverter Model 64208 (`REbus_dir`, providing `CTPow` for `grid_power`)** and **Inverter Model 64206 (`REbus_Load`, providing `Pload` for `home_load_power`)**—`BackgroundPoller._get_active_models_for_device()` **never polls those Modbus models**. If the internal MQTT push stream is unavailable or delayed, those sensors remain `None` (hidden/unavailable) indefinitely.

#### Suggested Fix for Bug H4
In `pwrcell/optimizer.py` (`solve_minimal_polling_plan`, lines 581–598), only treat an unpinned MQTT source as covering the concept if the device actually has live MQTT telemetry (e.g., `s.value is not None` or at least one `MQTT_PUSH` field in `device.fields` has received a non-`None` value):
```python
        device_has_live_mqtt = any(
            getattr(f, "source", None) == FieldSource.MQTT_PUSH and f.value is not None
            for f in device.fields.values()
        )
        has_mqtt = any(
            s.source_type == "MQTT" and (s.value is not None or device_has_live_mqtt)
            for s in grp.sources
        )
        if has_mqtt:
            mqtt_covered.append(grp.id)
            assignments[grp.id] = "MQTT"
            continue
```

---

### Bug H5: Null `mb_val` Overwrites Valid `mqtt_val` When `mb_upd > mqtt_upd` in `StateStore.get_compound_view()` (`pwrcell/state.py`)
- **Severity**: High
- **Location**: `pwrcell/state.py:894-949` (`StateStore.get_compound_view`)
- **Root Cause**:
  1. When a SunSpec register returns an unimplemented sentinel (`0xFFFF = 65535`, `0x8000 = -32768`), `update_from_modbus_points()` (`pwrcell/state.py:1659-1661`) sets `scaled_val = None` and `raw_val = None`, and calls `self.set_field(...)`, which sets `field.last_updated = time.time()` (`pwrcell/state.py:1296`).
  2. In `StateStore.get_compound_view()` (`pwrcell/state.py:894-900`), if no Modbus candidate has a non-`None` value, the fallback puts the `StateField` (with `value=None` and a fresh `last_updated` timestamp) into `mb_fields`.
  3. Then at `pwrcell/state.py:922-936`:
     - `mb_raw = mb_field.value` (`None`) -> `mb_val = None`
     - `mb_upd = mb_field.last_updated` (fresh timestamp from Modbus poll!)
     - `if mqtt_upd is not None and mb_upd is not None: if mb_upd > mqtt_upd: latest_val = mb_val`!
  4. Because `mb_upd > mqtt_upd` does **not** check whether `mb_val is not None`, every Modbus poll of an unimplemented/sentinel register sets `latest_val = None`, overwriting the valid `mqtt_val`! And because `_on_compound_update()` (`pwrcell/bridge.py:566`) returns early `if c_view.latest_value is None:`, compound state updates stop being published to MQTT!

#### Suggested Fix for Bug H5
In `pwrcell/state.py:927-949`, require non-`None` values when picking `latest_val`:
```python
        # 3. Determine Latest Value (only considering sources with non-None values)
        has_mqtt_val = mqtt_val is not None and mqtt_upd is not None
        has_mb_val = mb_val is not None and mb_upd is not None

        if has_mqtt_val and has_mb_val:
            if mb_upd > mqtt_upd:
                latest_val = mb_val
                latest_src = FieldSource.MODBUS_POLL.value
                latest_upd = mb_upd
            else:
                latest_val = mqtt_val
                latest_src = FieldSource.MQTT_PUSH.value
                latest_upd = mqtt_upd
        elif has_mqtt_val:
            latest_val = mqtt_val
            latest_src = FieldSource.MQTT_PUSH.value
            latest_upd = mqtt_upd
        elif has_mb_val:
            latest_val = mb_val
            latest_src = FieldSource.MODBUS_POLL.value
            latest_upd = mb_upd
        else:
            latest_val = None
            latest_src = "NONE"
            latest_upd = max(mqtt_upd or 0.0, mb_upd or 0.0)
```

---

### Bug H6: `.compound.` Entities Cannot Be Seen as Checked or Unchecked in Web UI Unified View (`pwrcell/ui/static/app.js`)
- **Severity**: High
- **Locations**:
  - `pwrcell/ui/static/app.js:750-765` (`isFieldSelected`)
  - `pwrcell/ui/static/app.js:768-805` (`toggleHaSelection`)
  - `pwrcell/ui/static/app.js:4358-4377` (`btnDeselectAll`)
- **Root Cause**:
  1. In `config/ha_config.yaml`, 6 entities are stored as `.compound.` keys (e.g. `000100082128:battery.compound.battery_voltage`, where neither raw source `battery.battery.Vol` nor `battery.model_802.Vol` is in `ha_config.yaml`).
  2. In `pwrcell/ui/static/app.js:750-765`, `isFieldSelected(f)` for a Unified View group (`f.sources` is an Array) checks `f.id` (`battery.concept.battery_voltage`) and `s.field_key` (`battery.battery.Vol`, `battery.model_802.Vol`), but **never checks `${sn}:${f.device_type}.compound.${f.concept_key}`**!
  3. Consequently, `battery_voltage` appears **unchecked** in the Web UI Unified View even though `000100082128:battery.compound.battery_voltage` is in `ha_config.yaml` and published to MQTT.
  4. Furthermore, `toggleHaSelection(f, false)` (`pwrcell/ui/static/app.js:785-801`) and `btnDeselectAll` (`pwrcell/ui/static/app.js:4358-4377`) never delete `${sn}:${f.device_type}.compound.${f.concept_key}` (and `btnDeselectAll` never deletes `${sn}:${f.id}` either), making it impossible to deselect `.compound.` keys from Unified View!

#### Suggested Fix for Bug H6
Update `isFieldSelected`, `toggleHaSelection`, and `btnDeselectAll` in `pwrcell/ui/static/app.js`:
```javascript
function getCompoundKeyForItem(f) {
  if (f.device_type && f.concept_key) {
    return `${f.device_type}.compound.${f.concept_key}`;
  }
  if (f.id && f.id.includes('.concept.')) {
    return f.id.replace('.concept.', '.compound.');
  }
  return null;
}

function isFieldSelected(f) {
  const sn = getFieldDeviceSn(f);
  const compKey = getCompoundKeyForItem(f);
  if (f.sources && Array.isArray(f.sources)) {
    if (sn) {
      if (state.selectedHaKeys.has(`${sn}:${f.id}`)) return true;
      if (compKey && state.selectedHaKeys.has(`${sn}:${compKey}`)) return true;
      return f.sources.some(s => state.selectedHaKeys.has(`${sn}:${s.field_key}`));
    }
    if (state.selectedHaKeys.has(f.id)) return true;
    if (compKey && state.selectedHaKeys.has(compKey)) return true;
    return f.sources.some(s => state.selectedHaKeys.has(s.field_key));
  }
  if (sn) {
    return state.selectedHaKeys.has(`${sn}:${f.key}`) ||
           (Boolean(f.mqtt_key) && state.selectedHaKeys.has(`${sn}:${f.mqtt_key}`));
  }
  return state.selectedHaKeys.has(f.key) || (Boolean(f.mqtt_key) && state.selectedHaKeys.has(f.mqtt_key));
}
```
And in `toggleHaSelection(f, checked)` (`pwrcell/ui/static/app.js:785-801`), also delete `compKey` and `${sn}:${compKey}` when `checked` is `false`:
```javascript
    const compKey = getCompoundKeyForItem(f);
    if (compKey) {
      state.selectedHaKeys.delete(compKey);
      if (sn) state.selectedHaKeys.delete(`${sn}:${compKey}`);
    }
```
And in `btnDeselectAll` (`pwrcell/ui/static/app.js:4359-4377`), remove all keys for `sn`:
```javascript
    if (sn) {
      for (const k of Array.from(state.selectedHaKeys)) {
        if (k.startsWith(`${sn}:`)) {
          state.selectedHaKeys.delete(k);
        }
      }
    }
```

---

### Bug H7: Unreachable Dead Code Leaves `c_view.ha_category = None` on All Compound Views (`pwrcell/state.py`)
- **Severity**: Medium
- **Location**: `pwrcell/state.py:1040-1067` (`StateStore.get_compound_view`)
- **Root Cause**:
  Lines 1040–1064 end with `return ConceptView(...)`, making lines 1065–1067 completely unreachable:
  ```python
          return ConceptView(
              ...
          )
          from .ha import get_effective_ha_category
          c_view.ha_category = get_effective_ha_category(c_view, target_dev)
          return c_view
  ```
  Because of this early return (and note that `get_effective_ha_category` expects `device_sn: Optional[str]` as its second argument, not `target_dev`), `c_view.ha_category` is always `None` on every compound view returned by `StateStore.get_compound_view()`.

#### Suggested Fix for Bug H7
Replace lines 1040–1067 of `pwrcell/state.py` with:
```python
        c_view = ConceptView(
            id=key,
            concept_key=m.id,
            device_sn=target_dev.serial_number,
            device_type=target_dev.device_type,
            name=m.id,
            label=m.label,
            description=m.description,
            units=m.unit or (mb_field.units if mb_field else (mqtt_field.units if mqtt_field else None)),
            sources=sources,
            active_source_key=active_k,
            latest_value=latest_val,
            latest_source=latest_src,
            latest_updated=latest_upd,
            delta=delta,
            match_pct=match_pct,
            modbus_candidates=candidates,
            is_writable=is_writable,
            ha_platform=ha_platform,
            ha_device_class=ha_device_class,
            ha_state_class=ha_state_class,
            ha_unit=m.unit,
            ha_options=options,
            ha_suggested_display_precision=precision,
        )
        from .ha import get_effective_ha_category
        c_view.ha_category = get_effective_ha_category(c_view, target_dev.serial_number)
        return c_view
```
