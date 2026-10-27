"""User Grouping Overrides & Custom Concept Management for Generac PWRcell.

Allows users to manually override automatic SunSpec/canonical field grouping:
- Ungroup: Split an incorrectly grouped field out into its own standalone concept.
- Regroup / Group With: Manually assign any field to an existing or custom concept.
- Reset: Revert a field's grouping back to automatic heuristics.
- Suggestions: Approve or dismiss automated grouping recommendations.
Persists configuration cleanly in custom_groupings.yaml.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from .catalog import infer_ha_classes
from .config import data_dir, is_addon_data_env

logger = logging.getLogger(__name__)

DEFAULT_GROUPING_CONFIG_FILE = "custom_groupings.yaml"

_CUSTOM_GROUPINGS_CACHE: Dict[str, Any] = {
    "path": None,
    "mtime": 0.0,
    "data": None,
}


def clear_custom_groupings_cache() -> None:
    """Clear in-memory cache of custom grouping overrides."""
    _CUSTOM_GROUPINGS_CACHE["path"] = None
    _CUSTOM_GROUPINGS_CACHE["mtime"] = 0.0
    _CUSTOM_GROUPINGS_CACHE["data"] = None


def get_default_grouping_config_path() -> Path:
    """Locate the custom groupings YAML file."""
    if is_addon_data_env():
        return data_dir() / DEFAULT_GROUPING_CONFIG_FILE
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_GROUPING_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_GROUPING_CONFIG_FILE
    if (repo_root / DEFAULT_GROUPING_CONFIG_FILE).exists():
        return repo_root / DEFAULT_GROUPING_CONFIG_FILE
    return data_dir() / DEFAULT_GROUPING_CONFIG_FILE


def load_custom_groupings(config_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Load custom grouping overrides from YAML with mtime caching."""
    path = Path(config_path) if config_path else get_default_grouping_config_path()
    if not path.exists():
        _CUSTOM_GROUPINGS_CACHE["path"] = str(path)
        _CUSTOM_GROUPINGS_CACHE["mtime"] = 0.0
        _CUSTOM_GROUPINGS_CACHE["data"] = None
        return {"field_overrides": {}, "field_transforms": {}, "custom_concepts": {}, "dismissed_suggestions": [], "custom_bounds": {}}
    
    try:
        mtime = path.stat().st_mtime
        if _CUSTOM_GROUPINGS_CACHE["path"] == str(path) and _CUSTOM_GROUPINGS_CACHE["mtime"] == mtime:
            cached = _CUSTOM_GROUPINGS_CACHE["data"]
            if cached is not None:
                return {
                    "field_overrides": dict(cached.get("field_overrides", {})),
                    "field_transforms": dict(cached.get("field_transforms", {}) or {}),
                    "custom_concepts": dict(cached.get("custom_concepts", {})),
                    "dismissed_suggestions": list(cached.get("dismissed_suggestions", [])),
                    "custom_bounds": dict(cached.get("custom_bounds", {}) or {}),
                }

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                res = {"field_overrides": {}, "field_transforms": {}, "custom_concepts": {}, "dismissed_suggestions": [], "custom_bounds": {}}
            else:
                res = {
                    "field_overrides": data.get("field_overrides", {}) or {},
                    "field_transforms": data.get("field_transforms", {}) or {},
                    "custom_concepts": data.get("custom_concepts", {}) or {},
                    "dismissed_suggestions": list(data.get("dismissed_suggestions", []) or []),
                    "custom_bounds": data.get("custom_bounds", {}) or {},
                }
            _CUSTOM_GROUPINGS_CACHE["path"] = str(path)
            _CUSTOM_GROUPINGS_CACHE["mtime"] = mtime
            _CUSTOM_GROUPINGS_CACHE["data"] = res
            return {
                "field_overrides": dict(res["field_overrides"]),
                "field_transforms": dict(res["field_transforms"]),
                "custom_concepts": dict(res["custom_concepts"]),
                "dismissed_suggestions": list(res["dismissed_suggestions"]),
                "custom_bounds": dict(res["custom_bounds"]),
            }
    except Exception as e:
        logger.error("Failed to load custom groupings from %s: %s", path, e)
        return {"field_overrides": {}, "field_transforms": {}, "custom_concepts": {}, "dismissed_suggestions": [], "custom_bounds": {}}


def save_custom_groupings(data: Dict[str, Any], config_path: Optional[Path | str] = None) -> None:
    """Save custom grouping overrides to YAML and refresh cache."""
    path = Path(config_path) if config_path else get_default_grouping_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "field_overrides": data.get("field_overrides", {}) or {},
            "field_transforms": data.get("field_transforms", {}) or {},
            "custom_concepts": data.get("custom_concepts", {}) or {},
            "dismissed_suggestions": sorted(list(set(data.get("dismissed_suggestions", []) or []))),
            "custom_bounds": data.get("custom_bounds", {}) or {},
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write("# PWRcell SunSpec - Custom Field Grouping Overrides\n")
            f.write("# Allows manually grouping or ungrouping Modbus registers & MQTT push fields.\n\n")
            yaml.safe_dump(content, f, default_flow_style=False, sort_keys=True)
        _CUSTOM_GROUPINGS_CACHE["path"] = str(path)
        _CUSTOM_GROUPINGS_CACHE["mtime"] = path.stat().st_mtime
        _CUSTOM_GROUPINGS_CACHE["data"] = content
        try:
            from .bounds import clear_custom_bounds_cache
            clear_custom_bounds_cache()
        except Exception:
            pass
    except Exception as e:
        logger.error("Failed to save custom groupings to %s: %s", path, e)


def is_field_excluded_from_mapping(
    device_sn: str,
    field_key: str,
    concept_id: str,
    custom_groupings: Optional[Dict[str, Any]] = None,
) -> bool:
    """Check if a field is excluded from a baseline concept/mapping due to user overrides.

    Returns True if the field has been explicitly ungrouped (target is None / null / standalone)
    or if it has been reassigned to a different concept.
    """
    if not field_key:
        return False
    from .mapping import MappingRegistry
    reg = MappingRegistry.get_instance()
    if reg.is_field_ungrouped(field_key):
        return True
    if custom_groupings is None:
        custom_groupings = load_custom_groupings()

    overrides = custom_groupings.get("field_overrides", {}) or {}
    if not overrides:
        return False

    clean_sn = (device_sn or "").strip().upper()
    clean_fk = field_key.strip()
    clean_cid = (concept_id or "").strip().lower()

    qual_key = f"{clean_sn}:{clean_fk}" if clean_sn else clean_fk

    if qual_key in overrides:
        target = overrides[qual_key]
    elif clean_fk in overrides:
        target = overrides[clean_fk]
    else:
        # Match model-neutral or device-prefixed fallback across model naming variations
        # (e.g. '000100082128:battery.REbus_status.V' matching 'battery.model_64252.V')
        fk_parts = clean_fk.split(".")
        fk_dev = fk_parts[0] if fk_parts else ""
        fk_point = fk_parts[-1] if fk_parts else ""

        target_found = False
        target = None
        for k, v in overrides.items():
            k_sn = k.split(":", 1)[0] if ":" in k else ""
            k_part = k.split(":", 1)[1] if ":" in k else k
            if k_sn and clean_sn and k_sn.strip().upper() != clean_sn:
                continue

            if k_part == clean_fk:
                target = v
                target_found = True
                break

            kp_parts = k_part.split(".")
            kp_dev = kp_parts[0] if kp_parts else ""
            kp_point = kp_parts[-1] if kp_parts else ""
            if (
                fk_dev
                and kp_dev
                and fk_dev.lower() == kp_dev.lower()
                and fk_point
                and kp_point
                and fk_point.lower() == kp_point.lower()
            ):
                target = v
                target_found = True
                break

        if not target_found:
            return False

    # 1. Explicitly ungrouped or standalone
    if target is None or str(target).strip().lower() in ("", "null", "none", "standalone", "ungrouped"):
        return True

    # 2. Reassigned to another concept
    clean_target = str(target).strip().lower()
    if clean_cid and clean_target != clean_cid:
        return True

    return False


def set_field_grouping_override(
    device_sn: str,
    field_key: str,
    target_concept: Optional[str],
    custom_label: Optional[str] = None,
    transform: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Assign a field to a concept (or null to ungroup/isolate)."""
    data = load_custom_groupings(config_path)
    clean_sn = device_sn.strip().upper()
    qual_key = f"{clean_sn}:{field_key.strip()}"
    
    clean_target = (
        target_concept.strip()
        if target_concept and target_concept.strip().lower() not in ("", "null", "none", "standalone", "ungrouped")
        else None
    )

    if clean_target:
        from .mapping import MappingRegistry
        reg = MappingRegistry.get_instance()
        m = reg.get_by_id(clean_target)
        if m and m.device_type and "." in field_key:
            f_prefix = field_key.split(".")[0].lower()
            if f_prefix in ("inverter", "battery", "pv_link", "rebus_beacon") and f_prefix != m.device_type.lower():
                raise ValueError(
                    f"Cannot group field '{field_key}' ({f_prefix}) into concept '{clean_target}' ({m.device_type}): "
                    f"grouping across devices is not permitted."
                )

    data["field_overrides"][qual_key] = clean_target

    if clean_target and transform and transform != "none":
        data.setdefault("field_transforms", {})[qual_key] = transform.strip()
    elif transform is None or transform == "none":
        data.get("field_transforms", {}).pop(qual_key, None)
        data.get("field_transforms", {}).pop(field_key.strip(), None)

    if clean_target and custom_label:
        c_entry = data.setdefault("custom_concepts", {}).setdefault(clean_target, {})
        c_entry["label"] = custom_label.strip()

    save_custom_groupings(data, config_path)
    return data


def reset_field_grouping_override(
    device_sn: str,
    field_key: str,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Remove custom grouping override for a field, reverting to automatic grouping."""
    data = load_custom_groupings(config_path)
    clean_sn = device_sn.strip().upper()
    qual_key = f"{clean_sn}:{field_key.strip()}"

    data["field_overrides"].pop(qual_key, None)
    data["field_overrides"].pop(field_key.strip(), None)
    data.get("field_transforms", {}).pop(qual_key, None)
    data.get("field_transforms", {}).pop(field_key.strip(), None)
    save_custom_groupings(data, config_path)
    return data


def ungroup_entire_concept(
    device_sn: str,
    concept_key: str,
    device_fields: Dict[str, Any],
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Ungroup all fields currently belonging to a concept for a device."""
    data = load_custom_groupings(config_path)
    clean_sn = device_sn.strip().upper()

    for f_key in device_fields.keys():
        qual_key = f"{clean_sn}:{f_key}"
        data["field_overrides"][qual_key] = None
        data.get("field_transforms", {}).pop(qual_key, None)
        data.get("field_transforms", {}).pop(f_key, None)

    save_custom_groupings(data, config_path)
    return data


def dismiss_suggestion(
    suggestion_id: str,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Record a suggestion ID as dismissed by user so it won't appear again."""
    return dismiss_suggestions([suggestion_id], config_path=config_path)


def dismiss_suggestions(
    suggestion_ids: List[str],
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Record multiple suggestion IDs as dismissed by user so they won't appear again."""
    data = load_custom_groupings(config_path)
    dismissed = set(data.get("dismissed_suggestions", []))
    for s_id in suggestion_ids:
        if s_id and s_id.strip():
            dismissed.add(s_id.strip())
    data["dismissed_suggestions"] = list(dismissed)
    save_custom_groupings(data, config_path)
    return data


def approve_suggestion(
    device_sn: str,
    field_keys: List[str],
    target_concept: str,
    custom_label: Optional[str] = None,
    suggestion_id: Optional[str] = None,
    transform: Optional[str] = None,
    negate_field_key: Optional[str] = None,
    positive_field_key: Optional[str] = None,
    negative_field_key: Optional[str] = None,
    polarity_convention: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Approve a suggested grouping by setting overrides for all source field keys."""
    return approve_suggestions(
        [
            {
                "device_sn": device_sn,
                "field_keys": field_keys,
                "target_concept": target_concept,
                "custom_label": custom_label,
                "suggestion_id": suggestion_id,
                "transform": transform,
                "negate_field_key": negate_field_key,
                "positive_field_key": positive_field_key,
                "negative_field_key": negative_field_key,
                "polarity_convention": polarity_convention,
            }
        ],
        config_path=config_path,
    )


def approve_suggestions(
    suggestions: List[Dict[str, Any]],
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Approve multiple suggested groupings in a single batch operation."""
    data = load_custom_groupings(config_path)
    dismissed = set(data.get("dismissed_suggestions", []))
    field_transforms = data.setdefault("field_transforms", {})

    for item in suggestions:
        device_sn = item.get("device_sn", "").strip().upper()
        field_keys = item.get("field_keys", [])
        target_concept = item.get("target_concept", "").strip()
        custom_label = item.get("label") or item.get("custom_label")
        suggestion_id = item.get("suggestion_id") or item.get("id")
        transform = item.get("transform")
        negate_field_key = item.get("negate_field_key")
        pos_key = item.get("positive_field_key")
        neg_key = item.get("negative_field_key")
        pol_conv = item.get("polarity_convention") or "positive"

        if not device_sn or not field_keys or not target_concept:
            continue

        for f_key in field_keys:
            qual_key = f"{device_sn}:{f_key.strip()}"
            data["field_overrides"][qual_key] = target_concept

        # Determine which specific field to negate if polarity inversion is requested
        if transform == "negate":
            if not negate_field_key:
                if pol_conv == "negative" and pos_key:
                    negate_field_key = pos_key
                elif neg_key:
                    negate_field_key = neg_key
                else:
                    # Prefer negating Modbus candidates over MQTT telemetry stream
                    mb_keys = [k for k in field_keys if "live." not in k and not k.startswith("live.")]
                    negate_field_key = mb_keys[0] if mb_keys else field_keys[0]

            if negate_field_key:
                qual_negate_key = f"{device_sn}:{negate_field_key.strip()}"
                field_transforms[qual_negate_key] = "negate"
                # Explicitly mark other fields in this group as 'none' so concept-level defaults don't inadvertently invert them
                for f_key in field_keys:
                    if f_key.strip() != negate_field_key.strip():
                        field_transforms[f"{device_sn}:{f_key.strip()}"] = "none"
        elif transform == "none":
            for f_key in field_keys:
                field_transforms[f"{device_sn}:{f_key.strip()}"] = "none"

        if custom_label or transform:
            c_entry = data.setdefault("custom_concepts", {}).setdefault(target_concept, {})
            if custom_label:
                c_entry["label"] = custom_label.strip()
            if transform:
                c_entry["transform"] = transform.strip()

        if suggestion_id:
            dismissed.add(str(suggestion_id).strip())

    data["dismissed_suggestions"] = list(dismissed)
    save_custom_groupings(data, config_path)
    return data


def export_generalized_groupings(config_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Export custom groupings stripped of device-specific serial numbers.

    Produces a clean, portable custom_groupings.yaml format where overrides are keyed
    directly by device field key (e.g. 'inverter.inverter.W': 'inverter_output_power').
    This can be placed in /data/custom_groupings.yaml or config/custom_groupings.yaml
    to apply universally across any PWRcell system on fresh install.
    """
    raw_data = load_custom_groupings(config_path)
    overrides = raw_data.get("field_overrides", {}) or {}
    field_transforms = raw_data.get("field_transforms", {}) or {}
    custom_concepts = raw_data.get("custom_concepts", {}) or {}

    generalized_overrides: Dict[str, Any] = {}
    for qual_key, target in overrides.items():
        if not qual_key:
            continue
        # Strip serial prefix if present (e.g. '0001000714E9:inverter.inverter.W' -> 'inverter.inverter.W')
        if ":" in qual_key:
            _, f_key = qual_key.split(":", 1)
        else:
            f_key = qual_key
        generalized_overrides[f_key.strip()] = target

    generalized_transforms: Dict[str, Any] = {}
    for qual_key, tf in field_transforms.items():
        if not qual_key:
            continue
        if ":" in qual_key:
            _, f_key = qual_key.split(":", 1)
        else:
            f_key = qual_key
        generalized_transforms[f_key.strip()] = tf

    result_dict: Dict[str, Any] = {
        "field_overrides": generalized_overrides,
        "custom_concepts": custom_concepts,
    }
    if generalized_transforms:
        result_dict["field_transforms"] = generalized_transforms

    yaml_header = (
        "# PWRcell SunSpec - Generalized Custom Field Groupings\n"
        "# Portable configuration without device serial numbers.\n"
        "# Place in /data/custom_groupings.yaml or config/custom_groupings.yaml to set defaults for new installs.\n\n"
    )
    yaml_str = yaml_header + yaml.safe_dump(result_dict, default_flow_style=False, sort_keys=True)
    return {
        "data": result_dict,
        "yaml": yaml_str,
    }


def export_as_telemetry_mappings(
    state_store: Any,
    config_path: Optional[Path | str] = None,
    only_custom: bool = True,
    only_explicit_groupings: bool = True,
) -> Dict[str, Any]:
    """Export active field groupings as built-in telemetry_mappings.yaml format.

    Generates official mapping schema entries (id, device_type, mqtt_fields, modbus_fields)
    for explicit multi-field groupings, omitting single un-grouped fields and redundant metadata.
    """
    from .mapping import MappingRegistry
    from .optimizer import group_device_fields
    reg = MappingRegistry.get_instance()
    raw_data = load_custom_groupings(config_path)
    custom_concepts = set(raw_data.get("custom_concepts", {}).keys())
    overrides = set(raw_data.get("field_overrides", {}).keys())

    mappings_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    exported_ungrouped: Set[str] = set(reg.ungrouped_fields)

    # Collect overrides where target is null/standalone
    for ov_k, ov_v in raw_data.get("field_overrides", {}).items():
        if ov_v is None or str(ov_v).strip().lower() in ("", "null", "none", "standalone", "ungrouped"):
            fk = ov_k.split(":", 1)[1] if ":" in ov_k else ov_k
            exported_ungrouped.add(fk)

    if hasattr(state_store, "devices") and state_store.devices:
        for dev in state_store.devices.values():
            dev_type = getattr(dev, "device_type", "inverter")
            dev_sn = getattr(dev, "serial_number", "")
            groups = group_device_fields(dev, custom_groupings=raw_data)

            for g in groups:
                if getattr(g, "is_scale_factor", False):
                    continue

                # Collect standalone/ungrouped fields if heuristics enabled
                if g.id.startswith(f"{dev_type}.standalone.") or "(Ungrouped)" in (g.label or ""):
                    for s in g.sources:
                        if s.model_id and s.name:
                            ref = f"{dev_type}.model_{s.model_id}.{s.name}"
                        else:
                            ref = s.field_key
                        if (
                            f"{dev_sn}:{s.field_key}" in overrides
                            or s.field_key in overrides
                            or s.field_key in exported_ungrouped
                            or ref in exported_ungrouped
                        ):
                            exported_ungrouped.add(ref)
                    continue

                # Filter if only exporting custom groups
                is_custom = (
                    getattr(g, "is_custom_override", False)
                    or g.concept_key in custom_concepts
                    or any(f"{dev_sn}:{s.field_key}" in overrides or s.field_key in overrides for s in g.sources)
                )

                if only_custom and not is_custom:
                    continue

                map_key = (dev_type, g.concept_key)

                # Extract MQTT and Modbus sources
                mqtt_sources = [s for s in g.sources if s.source_type == "MQTT"]
                mb_sources = [s for s in g.sources if s.source_type != "MQTT"]

                # Modbus candidates
                candidates: List[str] = []
                for s in mb_sources:
                    if s.model_id and s.name:
                        cand_ref = f"{dev_type}.model_{s.model_id}.{s.name}"
                    else:
                        cand_ref = s.field_key
                    if cand_ref not in candidates:
                        candidates.append(cand_ref)

                mqtt_keys = [s.field_key for s in mqtt_sources] if mqtt_sources else ([f"{dev_type}.live.{g.concept_key}"] if not candidates else [])

                # Skip single unmapped fields if only exporting explicit groupings
                if only_explicit_groupings and not is_custom and (len(mqtt_keys) + len(candidates)) <= 1:
                    continue

                if map_key in mappings_by_key:
                    # Merge candidates if already present from another unit
                    existing = mappings_by_key[map_key]
                    for c in candidates:
                        if c not in existing.setdefault("modbus_fields", []):
                            existing["modbus_fields"].append(c)
                    for mk in mqtt_keys:
                        if mk not in existing.setdefault("mqtt_fields", []):
                            existing["mqtt_fields"].append(mk)
                else:
                    dev_class = getattr(g, "ha_device_class", None)
                    st_class = getattr(g, "ha_state_class", None)
                    if not dev_class and not st_class:
                        dev_class, st_class = infer_ha_classes(
                            units=g.units,
                            name=g.concept_key,
                            platform=getattr(g, "ha_platform", "sensor"),
                        )

                    entry: Dict[str, Any] = {
                        "id": g.concept_key,
                        "name": g.label or g.concept_key.replace("_", " ").title(),
                        "fields": [],
                    }
                    orig_m = reg.get_by_id(g.concept_key)
                    c_meta = raw_data.get("custom_concepts", {}).get(g.concept_key, {})
                    g_trans = (
                        next((s.transform for s in mb_sources if getattr(s, "transform", None)), None)
                        or c_meta.get("transform")
                        or (orig_m.transform if orig_m and orig_m.transform != "none" else None)
                        or next((s.transform for s in g.sources if getattr(s, "transform", None)), None)
                    )
                    for mk in mqtt_keys:
                        entry["fields"].append(mk)
                    for c in candidates:
                        c_tf = next((s.transform for s in mb_sources if (s.field_key == c or getattr(s, "name", "") == c.split(".")[-1]) and getattr(s, "transform", None)), None) or g_trans
                        if c_tf and c_tf != "none":
                            entry["fields"].append({"path": c, "transform": c_tf})
                        else:
                            entry["fields"].append(c)

                    mappings_by_key[map_key] = entry

    # When exporting full mappings, ensure existing canonical mappings are preserved
    if not only_custom:
        for m in reg.get_all():
            map_key = (m.device_type, m.id)
            if map_key not in mappings_by_key:
                f_list = []
                for mf in m.mqtt_fields:
                    f_list.append(mf)
                for mbf in m.modbus_fields:
                    if m.transform and m.transform != "none":
                        f_list.append({"path": mbf, "transform": m.transform})
                    else:
                        f_list.append(mbf)
                mappings_by_key[map_key] = {
                    "id": m.id,
                    "name": m.label,
                    "fields": f_list,
                }

    mappings_list = [
        m for m in mappings_by_key.values()
        if not only_explicit_groupings
        or m.get("id") in custom_concepts
        or len(m.get("fields", [])) > 1
    ]

    output_dict: Dict[str, Any] = {
        "version": "2.0",
        "groups": mappings_list,
    }
    if exported_ungrouped:
        output_dict["ungrouped_fields"] = sorted(list(exported_ungrouped))

    yaml_header = (
        "# PWRcell SunSpec - Field Groupings & Telemetry Mappings (v2.0)\n"
        "# Unified links across MQTT push streams and SunSpec Modbus registers.\n\n"
    )
    yaml_str = yaml_header + yaml.safe_dump(output_dict, default_flow_style=False, sort_keys=False)
    return {
        "mappings": mappings_list,
        "groups": mappings_list,
        "ungrouped_fields": sorted(list(exported_ungrouped)),
        "yaml": yaml_str,
    }


def save_current_as_telemetry_mappings(
    state_store: Any,
    config_path: Optional[Path | str] = None,
    custom_groupings_path: Optional[Path | str] = None,
    only_custom: bool = False,
    clear_custom_overrides: bool = True,
) -> Dict[str, Any]:
    """Save active groupings & ungrouped fields directly to telemetry_mappings.yaml and reload."""
    from .mapping import MappingRegistry, _resolve_mappings_path
    reg = MappingRegistry.get_instance()
    res = export_as_telemetry_mappings(state_store, config_path=custom_groupings_path, only_custom=only_custom)
    path = _resolve_mappings_path(config_path)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(res["yaml"])

    reg.reload()

    if clear_custom_overrides:
        save_custom_groupings({
            "field_overrides": {},
            "field_transforms": {},
            "custom_concepts": {},
            "dismissed_suggestions": [],
        }, config_path=custom_groupings_path)
        clear_custom_groupings_cache()

    return {
        "status": "ok",
        "saved_path": str(path),
        "mappings_count": len(res.get("mappings", [])),
        "ungrouped_count": len(res.get("ungrouped_fields", [])),
        "ungrouped_fields": res.get("ungrouped_fields", []),
        "cleared_custom_overrides": clear_custom_overrides,
    }


export_custom_groupings_as_mappings = export_as_telemetry_mappings

