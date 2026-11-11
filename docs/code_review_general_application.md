# Code Review: General Application Architecture, Concurrency, Controls & UI

This document complements [`docs/code_review_grouping_and_mqtt.md`](file:///Users/edalquist/projects/pwrcell_sunspec/docs/code_review_grouping_and_mqtt.md) by reviewing the rest of the `pwrcell_sunspec` codebase (`pwrcell/state.py`, `pwrcell/poller.py`, `pwrcell/controls.py`, `pwrcell/modbus.py`, `pwrcell/mqtt.py`, `pwrcell/tunnel.py`, `pwrcell/safety.py`, `pwrcell/tools/*`, `pwrcell/ui/*`) with concrete code-level fix suggestions and a prioritized master checklist.

---

## 1. Architecture & Code Organization Findings

### A1: Incomplete Unification & Shadowed Dataclasses (`pwrcell/concept.py`, `pwrcell/tools/correlator.py`)
- **Severity**: Medium
- **Locations**:
  - `pwrcell/concept.py:345-359`
  - `pwrcell/tools/correlator.py:21` and `pwrcell/tools/correlator.py:116-147`
- **Details**:
  - `docs/design_grouping_unification.md` proposed unifying `CompoundFieldView` (`state.py`), `UnifiedFieldGroup` (`optimizer.py`), and `ComparisonResultRow` (`tools/correlator.py`) into `ConceptView` (`concept.py`) backed by a single `ConceptRegistry`.
  - In `pwrcell/tools/correlator.py:21`, `ComparisonResultRow` is imported from `..concept`, and then **re-defined from scratch as a separate `@dataclass class ComparisonResultRow` at line 116**, shadowing the import from `concept.py`!
  - Meanwhile, `ConceptView` in `pwrcell/concept.py:72-180` carries ~45 fields merged from all three legacy classes (`modbus_candidates`, `sources`, `optimal_source_id`, `delta`, `is_discrepant`, etc.), while `state.py`, `optimizer.py`, and `tools/correlator.py` still run three separate grouping and comparison algorithms that can disagree on active values, transforms, and source membership.

#### Suggested Fix for A1
Remove the duplicate `@dataclass class ComparisonResultRow` definition in `pwrcell/tools/correlator.py:116-147` (or keep only the `ComparisonResultRow` alias from `pwrcell/concept.py:21`) after ensuring `ConceptView.to_dict()` includes any correlator-specific serialized keys (`is_explicitly_grouped`, `status`, `summary`, `modbus_sources`, `mqtt_sources`).

---

### A2: Broken `get_blocked_mutation_fields()` Compound View Audit (`pwrcell/safety.py`)
- **Severity**: Medium
- **Location**: `pwrcell/safety.py:238-253` (`get_blocked_mutation_fields`)
- **Details**:
  At `pwrcell/safety.py:239`, `get_blocked_mutation_fields()` attempts to inspect compound views via:
  ```python
  for c_id, c_view in list(getattr(state_store, "compound_views", {}).items()):
  ```
  `StateStore` does **not** have a `compound_views` dict attribute—it has a `get_compound_views(device_sn=None) -> List[ConceptView]` method (`pwrcell/state.py:1069`). Because `getattr(state_store, "compound_views", {})` always returns `{}`, compound views are never audited in `get_blocked_mutation_fields()` / `pwrcell list-blocked`.

#### Suggested Fix for A2
Replace lines 238–253 of `pwrcell/safety.py` with:
```python
        # Also inspect compound views
        if hasattr(state_store, "get_compound_views"):
            for c_view in state_store.get_compound_views():
                if c_view.is_writable or getattr(c_view, "access", "R") == "RW":
                    matched = get_matched_blocked_pattern(c_view, device_sn=c_view.device_sn, config_path=path)
                    if matched:
                        blocked_items.append({
                            "key": c_view.key,
                            "name": c_view.concept_key,
                            "label": c_view.label or c_view.concept_key,
                            "device_sn": c_view.device_sn or "COMPOUND",
                            "device_type": c_view.device_type or "compound",
                            "model_id": None,
                            "model_name": "compound",
                            "access": "RW",
                            "matched_pattern": matched,
                        })
```

---

## 2. Concurrency, Locking & Performance Findings

### C1: Uncached `load_ha_config()` & `load_ha_category_overrides()` Disk Reads on Hot Paths (`pwrcell/ha.py`, `pwrcell/poller.py`)
- **Severity**: High
- **Locations**:
  - `pwrcell/ha.py:140-174` (`load_ha_config`)
  - `pwrcell/ha.py:243-260` (`load_ha_category_overrides`)
  - `pwrcell/poller.py:201-215` (`BackgroundPoller._get_active_models_for_device`)
- **Details**:
  Unlike `pwrcell/grouping.py` (`_CUSTOM_GROUPINGS_CACHE`) and `pwrcell/safety.py` (`_BLOCKED_FIELDS_CACHE`), `load_ha_config()` and `load_ha_category_overrides()` in `pwrcell/ha.py` have **no `st_mtime` cache**. Every call opens `ha_config.yaml` from disk and runs `yaml.safe_load()`. Because `BackgroundPoller._get_active_models_for_device()` calls `load_ha_config()` on every device poll cycle and UI/API endpoints call `load_ha_config()` and `load_ha_category_overrides()` repeatedly, `ha_config.yaml` is parsed from disk continuously.

#### Suggested Fix for C1
Add `st_mtime`-based caching in `pwrcell/ha.py` (invalidated automatically when `save_ha_config()` writes to disk or when the file's `st_mtime` changes):
```python
_HA_CONFIG_CACHE: Dict[str, Any] = {
    "path": None,
    "mtime": 0.0,
    "selected_fields": None,
    "category_overrides": None,
}


def _read_ha_config_doc(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
        if _HA_CONFIG_CACHE["path"] == str(path) and _HA_CONFIG_CACHE["mtime"] == mtime:
            return {
                "selected_fields": list(_HA_CONFIG_CACHE["selected_fields"] or []),
                "category_overrides": dict(_HA_CONFIG_CACHE["category_overrides"] or {}),
            }
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw_fields = data.get("selected_fields") or []
        fields = [str(x).strip() for x in raw_fields if x is not None and str(x).strip()]
        raw_ov = data.get("category_overrides") or data.get("entity_categories") or {}
        overrides = (
            {str(k).strip(): str(v).strip().lower() for k, v in raw_ov.items() if k and v}
            if isinstance(raw_ov, dict)
            else {}
        )
        _HA_CONFIG_CACHE["path"] = str(path)
        _HA_CONFIG_CACHE["mtime"] = mtime
        _HA_CONFIG_CACHE["selected_fields"] = fields
        _HA_CONFIG_CACHE["category_overrides"] = overrides
        return {"selected_fields": list(fields), "category_overrides": dict(overrides)}
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return {}
```

---

### C2: `PwrCellMqttListener` Does Not Rebind to New Ephemeral Tunnel Port When SSH Tunnel Reconnects (`pwrcell/mqtt.py`, `pwrcell/tunnel.py`, `pwrcell/client.py`)
- **Severity**: High
- **Locations**:
  - `pwrcell/mqtt.py:356-420` (`PwrCellMqttListener`)
  - `pwrcell/tunnel.py:166-179, 224-230` (`PwrCellTunnel.ensure_active`)
  - `pwrcell/modbus.py:274-291` (`SerializedModbusClient._get_shared_client`)
- **Details**:
  - When the SSH tunnel drops and reconnects in `PwrCellTunnel.ensure_active()` (`pwrcell/tunnel.py:166-179`), if the previous local ephemeral port is in `TIME_WAIT` or cannot be rebound, `_create_and_start_server()` falls back to **new ephemeral ports** (`self.modbus_port`, `self.mqtt_port`).
  - `SerializedModbusClient._get_shared_client()` (`pwrcell/modbus.py:276-291`) explicitly checks `self.tunnel` for port changes and updates `self.port`.
  - However, `PwrCellMqttListener` (`pwrcell/mqtt.py:356-420`) is initialized with a static `host` and `port` in `pwrcell/client.py:187-194` and uses `paho-mqtt`'s internal `loop_start()` reconnect loop, which keeps retrying the **old, dead `mqtt_port`** forever if the SSH tunnel rebound to a new ephemeral `mqtt_port`!

#### Suggested Fix for C2
Pass `tunnel: Optional[Any] = None` to `PwrCellMqttListener.__init__` in `pwrcell/mqtt.py` (and from `pwrcell/client.py`), and update `_on_disconnect` in `PwrCellMqttListener` to refresh the port from `self.tunnel` before Paho reconnects:
```python
    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.debug("Disconnected from internal PWRcell MQTT broker (reason=%s)", reason_code)
        if self.tunnel and self._running:
            try:
                self.tunnel.ensure_active()
                cfg = self.tunnel.get_config() if hasattr(self.tunnel, "get_config") else self.tunnel
                new_port = getattr(cfg, "mqtt_port", None)
                if new_port and new_port != self.port:
                    logger.info("Internal MQTT tunnel port updated: %s -> %s", self.port, new_port)
                    self.port = new_port
                    client._port = new_port
            except Exception as e:
                logger.debug("Error checking tunnel on MQTT disconnect: %s", e)
```

---

## 3. Controls, Write Path & Web UI Findings

### W1: `ControlDispatcher.write_field()` Ignores `device_sn`, Writing to the Wrong Device on Multi-Device Systems, and Rejects `.concept.` Keys (`pwrcell/controls.py`, `pwrcell/bridge.py`, `pwrcell/ui/routes/control.py`)
- **Severity**: High
- **Locations**:
  - `pwrcell/controls.py:285-364` (`ControlDispatcher.write_field`)
  - `pwrcell/bridge.py:645-655` (`HomeAssistantBridge._on_message`, `_execute_command_async`)
  - `pwrcell/ui/routes/control.py:46-61` (`write_field`)
- **Details**:
  1. `ControlDispatcher.write_field(self, field_key: str, new_value: Any)` (`pwrcell/controls.py:285`) does not accept `device_sn` (nor does it parse `<SN>:<field_key>`).
  2. At `pwrcell/controls.py:356-360`:
     ```python
     for dev in self.state_store.get_devices_snapshot():
         if field_key in dev.fields:
             target_field = dev.fields[field_key]
             target_dev = dev
             break
     ```
     If a system has multiple devices of the same type (e.g., 5 PV Links or 2 Batteries), writing to a field on Device #2 (either via Home Assistant MQTT command topic in `bridge.py:645` or via `/api/fields/write` in `ui/routes/control.py:56`) **always writes to Device #1 (`devs[0]`)**!
  3. Similarly, for compound/concept writes (`pwrcell/controls.py:317-354`):
     - It only checks `if ".compound." in field_key:`, not `".concept." in field_key`.
     - It calls `self.state_store.get_compound_view(mapping_id)` without `device_sn`.
     - At `pwrcell/controls.py:341`, it picks `target_mb_key = c_view.modbus_key` without verifying whether `c_view.modbus_key` is actually the writable (`RW`) register when a mapping has both read-only and read-write candidates.

#### Suggested Fix for W1
1. **In `pwrcell/controls.py` (`write_field`, lines 285–364)**: Accept `device_sn: Optional[str] = None` (and strip any `<SN>:` prefix from `field_key`), handle both `.compound.` and `.concept.` keys, prefer writable Modbus candidates, and scope device lookup to `device_sn` when provided:
```python
    def write_field(self, field_key: str, new_value: Any, device_sn: Optional[str] = None) -> Any:
        """Write any writable field by key, optionally scoped to device_sn."""
        from .safety import is_mutation_blocked

        if ":" in field_key and not device_sn:
            sn_part, field_key = field_key.split(":", 1)
            device_sn = sn_part.strip().upper()

        if is_mutation_blocked(field_key, device_sn=device_sn):
            raise PermissionError(
                f"Field '{field_key}' is blocked from mutation by safety configuration. "
                "To unblock, manually edit config/blocked_fields.yaml."
            )

        # Normalize .concept. to .compound. for unified concept writes
        if ".concept." in field_key:
            field_key = field_key.replace(".concept.", ".compound.")

        if ".compound." in field_key:
            mapping_id = field_key.split(".compound.", 1)[-1]
            c_view = self.state_store.get_compound_view(mapping_id, device_sn=device_sn)
            if not c_view:
                raise KeyError(f"Compound field '{field_key}' not found in state store")
            if not c_view.is_writable:
                raise PermissionError(f"Compound field '{field_key}' is read-only")
            ...
            target_mb_key = None
            for cand in ([c_view.modbus_key] if c_view.modbus_key else []) + list(c_view.modbus_candidates):
                pt = self.catalog.get_point_for_field(cand) if self.catalog else None
                if pt and pt.is_writable:
                    target_mb_key = cand
                    break
            if not target_mb_key:
                target_mb_key = c_view.modbus_key
            if not target_mb_key:
                raise PermissionError(f"Compound field '{field_key}' has no writable modbus target point")
            res = self.write_field(target_mb_key, new_value, device_sn=c_view.device_sn)
            updated_c = self.state_store.get_compound_view(mapping_id, device_sn=c_view.device_sn)
            if updated_c:
                self.state_store.notify_compound_change(updated_c)
            return res

        if device_sn:
            dev = self.state_store.get_device(device_sn)
            if dev and field_key in dev.fields:
                target_dev = dev
                target_field = dev.fields[field_key]
        if not target_field:
            for dev in self.state_store.get_devices_snapshot():
                if field_key in dev.fields:
                    target_field = dev.fields[field_key]
                    target_dev = dev
                    break
```
2. **In `pwrcell/bridge.py` (`_on_message` & `_execute_command_async`, lines 645–655)**: Pass `target_field.device_sn` to `write_field`:
```python
        self._cmd_executor.submit(
            self._execute_command_async,
            target_field.key,
            payload_str,
            getattr(target_field, "device_sn", None),
        )

    def _execute_command_async(self, field_key: str, payload_str: str, device_sn: Optional[str] = None):
        try:
            confirmed_val = self.client.controls.write_field(field_key, payload_str, device_sn=device_sn)
            logger.info("Executed command for %s (device=%s): confirmed=%s", field_key, device_sn, confirmed_val)
        except Exception as e:
            logger.error("Failed executing command for %s (device=%s): %s", field_key, device_sn, e)
```
3. **In `pwrcell/ui/routes/control.py` (`write_field`, lines 47–60)**: Pass `device_sn = body.get("device_sn")` to `client.controls.write_field(field_key, value, device_sn=device_sn)`.

---

### W2: Category Override Key Proliferation & Unscoped Cross-Device Collisions (`pwrcell/ha.py`, `pwrcell/ui/static/app.js`, `config/ha_default_config.yaml`)
- **Severity**: Medium
- **Locations**:
  - `pwrcell/ha.py:333-413` (`get_effective_ha_category`)
  - `pwrcell/ha.py:487-495` (`generate_ha_default_config`)
  - `pwrcell/ui/static/app.js:704-748` (`hasCategoryOverride`, `isFieldDiagnostic`, `toggleFieldCategoryAction`)
  - `config/ha_default_config.yaml:97-138`
- **Details**:
  - Look at `config/ha_default_config.yaml:97-138`: toggling category on a few fields wrote **41 keys** into `category_overrides`, including bare model-point suffixes (`i_64207`, `v_64207`, `st_64207`), standalone concept IDs (`battery.standalone.i_64207`, `inverter.standalone.i_64207`), and raw keys (`battery.REbus_status.I`, `inverter.REbus_status.I`).
  - Because `get_effective_ha_category()` (`pwrcell/ha.py:372`) checks bare `f"{pt_name.lower()}_{model_id}"` (`i_64207`, `v_64207`) and `generate_ha_default_config()` strips serial numbers from all keys in `category_overrides`, overriding the category of `REbus_status.I` on the **Battery** also overrides `REbus_status.I` on the **Inverter** and **all 5 PV Links**!

#### Suggested Fix for W2
1. In `pwrcell/ha.py` (`get_effective_ha_category`, line 372), remove the unscoped `raw_candidates.append(f"{pt_name.lower()}_{model_id}")` candidate (always require the `dev_type` prefix, e.g., `f"{dev_type}.standalone.{pt_name.lower()}_{model_id}"`).
2. In `config/ha_default_config.yaml:97-138`, remove the bare keys lacking a `<device_type>.` prefix (`i_64207`, `modtmpavg_804`, `modtmpmax_804`, `modtmpmin_804`, `px1_64204`, `px2_64204`, `st_64207`, `tmpot_102`, `tmpsnk_102`, `tmptrns_102`, `v_64207`, `whin_64204`).

---

### W3: UI Preview Tag Shows Wrong Home Assistant Entity ID Format (`pwrcell/ui/static/app.js`)
- **Severity**: Low
- **Location**: `pwrcell/ui/static/app.js:2117-2118` (`renderUnifiedRow`)
- **Details**:
  When expanding a unified group row in the Web UI, the header displays:
  ```javascript
  const cleanDeviceType = f.device_type || 'inverter';
  const haEntityId = `sensor.pwrcell_${cleanDeviceType}_${f.concept_key}`;
  ```
  However, `generate_discovery_payload()` (`pwrcell/ha.py:698-715`) actually generates `object_id = f"pwrcell_{clean_sn}_{sub_key}"` using the device's **serial number** and actual `ha_platform` (`sensor`, `number`, `select`, `binary_sensor`).

#### Suggested Fix for W3
Replace lines 2117–2118 of `pwrcell/ui/static/app.js` with:
```javascript
      const cleanSn = (f.device_sn || f.device_type || 'inverter').toLowerCase();
      const platform = f.ha_platform || 'sensor';
      const haEntityId = `${platform}.pwrcell_${cleanSn}_${(f.concept_key || '').toLowerCase()}`;
```

---

## 4. Master Prioritized Action Plan for Addressing All Findings

Another agent tasked with fixing these issues can follow this checklist in order:

### Phase 1: Core Grouping & Compound View Fixes (`pwrcell/grouping.py`, `pwrcell/state.py`, `pwrcell/ui/routes/grouping.py`)
- [ ] **1.1 (Bug H1)**: Add `device_sn: Optional[str] = None` to `StateStore.get_compound_view(mapping_id, device_sn=None)` and update `StateStore.get_compound_views(device_sn=None)` in [`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L827-L1078) so every device (including all 5 PV Links and multiple batteries) gets its own device-scoped compound views without cross-device `find_fields()` leakage. Pass `device_sn` when computing `affected_view` in `StateStore.set_field()` (`state.py:1416`).
- [ ] **1.2 (Bug H2)**: In `StateStore.get_compound_view()` ([`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L881)), filter `candidates` by `not is_field_excluded_from_mapping(target_sn, cand_key, m.id, custom_data)` so ungrouped fields are removed from `c_view.modbus_candidates`. Add `StateStore.refresh_compound_links(device_sn=None)` and call it (plus `client.bridge.publish_discovery()`) from all grouping mutation routes in [`pwrcell/ui/routes/grouping.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/routes/grouping.py#L212-L403).
- [ ] **1.3 (Bug H3)**: In `StateStore.get_compound_view()` and `get_compound_views()` ([`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L857-L1078)), include fields assigned to a concept via `custom_groupings.yaml` `field_overrides`, apply per-field transforms from `field_transforms`, and generate compound views for `custom_concepts`.
- [ ] **1.4 (Bug H5 & Bug H7)**: In `StateStore.get_compound_view()` ([`pwrcell/state.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/state.py#L927-L949)), require `mqtt_val is not None` / `mb_val is not None` when selecting `latest_val`, and fix the unreachable `c_view.ha_category = get_effective_ha_category(c_view, target_dev.serial_number)` code (`state.py:1040-1067`).

### Phase 2: Home Assistant Selection & MQTT Discovery Fixes (`pwrcell/ha.py`, `pwrcell/bridge.py`, `pwrcell/ui/routes/ha.py`)
- [ ] **2.1 (Bug D2)**: In `qualify_legacy_ha_config()` ([`pwrcell/ha.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ha.py#L191-L227)), remap `<dev_type>.concept.<id>` for any known mapping or custom concept to `<dev_type>.compound.<id>` instead of dropping it.
- [ ] **2.2 (Bug D2)**: Update `is_field_selected()` in [`pwrcell/ha.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ha.py#L114-L138) to accept `candidate_keys` so compound views match if `<dev_type>.compound.<id>`, `<dev_type>.concept.<id>`, `c_view.mqtt_key`, or any non-excluded member key in `c_view.modbus_candidates` is in `selected_set`.
- [ ] **2.3 (Bug D1)**: In `HomeAssistantBridge.publish_discovery()` ([`pwrcell/bridge.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L315-L375)), move `ensure_field_definition()` **before** Step 1 (`get_compound_views`), and ensure `c_view.mqtt_key` is populated from `m.mqtt_field` even before the first MQTT snapshot arrives.
- [ ] **2.4 (Bug D1 & Bug D4)**: In `HomeAssistantBridge._on_compound_update()` ([`pwrcell/bridge.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L564-L618)) and `_is_field_suppressed_by_compound()` ([`pwrcell/bridge.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/bridge.py#L489-L510)), check `c_view.modbus_candidates` and record all member keys in `self._active_member_keys` when a compound view becomes active.
- [ ] **2.5 (Bug D5)**: Update `preview_ha_discovery()` in [`pwrcell/ui/routes/ha.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/routes/ha.py#L363-L395) to skip raw fields suppressed by active compound views.
- [ ] **2.6 (Bug D3)**: Remove `battery.live.state_of_health` from `ungrouped_fields` in [`pwrcell/data/groupings.yaml`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/data/groupings.yaml#L424-L426) and deduplicate sibling member keys in `get_recommended_field_keys()` ([`pwrcell/ha.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ha.py#L505-L565)), [`config/ha_default_config.yaml`](file:///Users/edalquist/projects/pwrcell_sunspec/config/ha_default_config.yaml), and [`config/ha_config.yaml`](file:///Users/edalquist/projects/pwrcell_sunspec/config/ha_config.yaml).

### Phase 3: Optimizer, Controls, Transport & Frontend Fixes (`pwrcell/optimizer.py`, `pwrcell/controls.py`, `pwrcell/mqtt.py`, `pwrcell/safety.py`, `pwrcell/ui/static/app.js`)
- [ ] **3.1 (Bug H4)**: In `solve_minimal_polling_plan()` ([`pwrcell/optimizer.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/optimizer.py#L581-L598)), do not allow unpolled `VirtualField` MQTT sources (`value is None` when the device has no live MQTT telemetry) to suppress Modbus polling.
- [ ] **3.2 (Bug H6 & W3)**: Update `isFieldSelected()`, `toggleHaSelection()`, `btnDeselectAll`, and the `haEntityId` preview tag in [`pwrcell/ui/static/app.js`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/ui/static/app.js#L750-L805).
- [ ] **3.3 (W1)**: Update `ControlDispatcher.write_field()` in [`pwrcell/controls.py`](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/controls.py#L285-L364) (and callers in `bridge.py` and `ui/routes/control.py`) to accept `device_sn`, handle `.concept.` keys, and prefer writable Modbus candidates.
- [ ] **3.4 (A1, A2, C1, C2, W2)**: Remove shadowed `ComparisonResultRow` in `pwrcell/tools/correlator.py`, fix `get_blocked_mutation_fields()` in `pwrcell/safety.py`, add `st_mtime` caching to `load_ha_config()` in `pwrcell/ha.py`, rebind `PwrCellMqttListener` port on tunnel reconnect in `pwrcell/mqtt.py`, and remove unscoped `pt_name_model_id` category overrides in `pwrcell/ha.py`.
