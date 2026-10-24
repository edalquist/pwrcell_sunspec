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

logger = logging.getLogger(__name__)

DEFAULT_GROUPING_CONFIG_FILE = "custom_groupings.yaml"


def get_default_grouping_config_path() -> Path:
    """Locate the custom groupings YAML file."""
    if Path("/data").is_dir() and Path("/data/options.json").exists():
        return Path("/data") / DEFAULT_GROUPING_CONFIG_FILE
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_GROUPING_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_GROUPING_CONFIG_FILE
    if (repo_root / DEFAULT_GROUPING_CONFIG_FILE).exists():
        return repo_root / DEFAULT_GROUPING_CONFIG_FILE
    if (repo_root / "config").is_dir():
        return repo_root / "config" / DEFAULT_GROUPING_CONFIG_FILE
    return repo_root / DEFAULT_GROUPING_CONFIG_FILE


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
