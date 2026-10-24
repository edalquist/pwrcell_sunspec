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

from .config import data_dir, is_addon_data_env

logger = logging.getLogger(__name__)

DEFAULT_GROUPING_CONFIG_FILE = "custom_groupings.yaml"


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
    """Load custom grouping overrides from YAML."""
    path = Path(config_path) if config_path else get_default_grouping_config_path()
    if not path.exists():
        return {"field_overrides": {}, "custom_concepts": {}, "dismissed_suggestions": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                return {"field_overrides": {}, "custom_concepts": {}, "dismissed_suggestions": []}
            return {
                "field_overrides": data.get("field_overrides", {}) or {},
                "custom_concepts": data.get("custom_concepts", {}) or {},
                "dismissed_suggestions": list(data.get("dismissed_suggestions", []) or []),
            }
    except Exception as e:
        logger.error("Failed to load custom groupings from %s: %s", path, e)
        return {"field_overrides": {}, "custom_concepts": {}, "dismissed_suggestions": []}


def save_custom_groupings(data: Dict[str, Any], config_path: Optional[Path | str] = None) -> None:
    """Save custom grouping overrides to YAML."""
    path = Path(config_path) if config_path else get_default_grouping_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "field_overrides": data.get("field_overrides", {}) or {},
            "custom_concepts": data.get("custom_concepts", {}) or {},
            "dismissed_suggestions": sorted(list(set(data.get("dismissed_suggestions", []) or []))),
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write("# PWRcell SunSpec - Custom Field Grouping Overrides\n")
            f.write("# Allows manually grouping or ungrouping Modbus registers & MQTT push fields.\n\n")
            yaml.safe_dump(content, f, default_flow_style=False, sort_keys=True)
    except Exception as e:
        logger.error("Failed to save custom groupings to %s: %s", path, e)


def set_field_grouping_override(
    device_sn: str,
    field_key: str,
    target_concept: Optional[str],
    custom_label: Optional[str] = None,
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

    data["field_overrides"][qual_key] = clean_target

    if clean_target and custom_label:
        data.setdefault("custom_concepts", {})[clean_target] = {
            "label": custom_label.strip(),
        }

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

    save_custom_groupings(data, config_path)
    return data


def dismiss_suggestion(
    suggestion_id: str,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Record a suggestion ID as dismissed by user so it won't appear again."""
    data = load_custom_groupings(config_path)
    s_id = suggestion_id.strip()
    dismissed = set(data.get("dismissed_suggestions", []))
    dismissed.add(s_id)
    data["dismissed_suggestions"] = list(dismissed)
    save_custom_groupings(data, config_path)
    return data


def approve_suggestion(
    device_sn: str,
    field_keys: List[str],
    target_concept: str,
    custom_label: Optional[str] = None,
    suggestion_id: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Approve a suggested grouping by setting overrides for all source field keys."""
    data = load_custom_groupings(config_path)
    clean_sn = device_sn.strip().upper()
    clean_target = target_concept.strip()

    for f_key in field_keys:
        qual_key = f"{clean_sn}:{f_key.strip()}"
        data["field_overrides"][qual_key] = clean_target

    if custom_label:
        data.setdefault("custom_concepts", {})[clean_target] = {
            "label": custom_label.strip(),
        }

    if suggestion_id:
        dismissed = set(data.get("dismissed_suggestions", []))
        dismissed.add(suggestion_id.strip())
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

    result_dict = {
        "field_overrides": generalized_overrides,
        "custom_concepts": custom_concepts,
    }

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
) -> Dict[str, Any]:
    """Export active field groupings as built-in telemetry_mappings.yaml format.

    Generates official mapping schema entries (id, device_type, mqtt_field, modbus_candidates)
    suitable for updating pwrcell/data/telemetry_mappings.yaml or submitting a pull request.
    """
    from .optimizer import group_device_fields
    raw_data = load_custom_groupings(config_path)
    custom_concepts = set(raw_data.get("custom_concepts", {}).keys())
    overrides = set(raw_data.get("field_overrides", {}).keys())

    mappings_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}

    if hasattr(state_store, "devices") and state_store.devices:
        for dev in state_store.devices.values():
            dev_type = getattr(dev, "device_type", "inverter")
            dev_sn = getattr(dev, "serial_number", "")
            groups = group_device_fields(dev, custom_groupings=raw_data)

            for g in groups:
                if getattr(g, "is_scale_factor", False):
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

                primary_mb = candidates[0] if candidates else ""
                mqtt_field = mqtt_sources[0].field_key if mqtt_sources else f"{dev_type}.live.{g.concept_key}"

                if map_key in mappings_by_key:
                    # Merge candidates if already present from another unit
                    existing = mappings_by_key[map_key]
                    for c in candidates:
                        if c not in existing["modbus_candidates"]:
                            existing["modbus_candidates"].append(c)
                else:
                    mappings_by_key[map_key] = {
                        "id": g.concept_key,
                        "label": g.label or g.concept_key.replace("_", " ").title(),
                        "device_type": dev_type,
                        "unit": g.units or "",
                        "mqtt_field": mqtt_field,
                        "modbus_field": primary_mb,
                        "modbus_candidates": candidates,
                        "transform": "none",
                        "transform_desc": "",
                        "description": g.description or f"Aggregated {g.label} telemetry",
                        "ha_platform": getattr(g, "ha_platform", "sensor"),
                        "ha_device_class": getattr(g, "ha_device_class", None),
                        "ha_state_class": getattr(g, "ha_state_class", None),
                    }

    mappings_list = list(mappings_by_key.values())
    output_dict = {
        "version": "1.0",
        "mappings": mappings_list,
    }

    yaml_header = (
        "# PWRcell SunSpec - Custom Telemetry Mappings Export\n"
        "# Formatted for pwrcell/data/telemetry_mappings.yaml to contribute to integration defaults.\n\n"
    )
    yaml_str = yaml_header + yaml.safe_dump(output_dict, default_flow_style=False, sort_keys=False)
    return {
        "mappings": mappings_list,
        "yaml": yaml_str,
    }

