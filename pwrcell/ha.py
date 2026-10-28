"""Home Assistant MQTT Discovery and Configuration Generator for Generac PWRcell.

Adheres strictly to Home Assistant's latest MQTT discovery guidance:
- Universally unique hardware identifiers (serial numbers, zero index dependencies).
- `has_entity_name: True` for clean entity naming hierarchy.
- Global device registry linkage (`via_device` hierarchy to gateway).
- Explicit `serial_number`, `model`, `manufacturer`, and `sw_version`.
- System availability topic (`availability` with LWT).
- Modern integration provenance (`origin` dictionary).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from . import __version__
from .catalog import get_suggested_precision, normalize_ha_unit, is_diagnostic_point
from .config import data_dir, is_addon_data_env
from .state import FieldSource, StateField, StateStore, UnifiedDevice

logger = logging.getLogger(__name__)

DEFAULT_HA_CONFIG_FILE = "ha_config.yaml"
DEFAULT_HA_DEFAULT_CONFIG_FILE = "ha_default_config.yaml"

# Home Assistant Integration Provenance metadata (HA 2024+)
ORIGIN_INFO: Dict[str, str] = {
    "name": "PWRcell SunSpec",
    "sw_version": __version__,
    "support_url": "https://github.com/edalquist/pwrcell_sunspec",
}

def _load_ha_security_config() -> tuple[Set[str], Set[str]]:
    """Load controllable allowlist and excluded options from HA config or default seed."""
    default_writable = {
        "system_mode", "SysMd", "SoCRsvMin", "SoCRsvMax",
        "SoCMax", "SoCMin", "WChaRteMax", "WDisChaRteMax",
        "AChaMax", "ADisChaMax",
    }
    default_excluded = {"SAFETY_SHUTDOWN"}
    try:
        import yaml
        for p in (get_default_ha_config_path(), get_default_seed_config_path()):
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if isinstance(data, dict):
                    ctrl = data.get("controllable_fields")
                    excl = data.get("excluded_select_options")
                    w_set = set(ctrl) if isinstance(ctrl, list) else default_writable
                    e_set = set(excl) if isinstance(excl, list) else default_excluded
                    return w_set, e_set
    except Exception:
        pass
    return default_writable, default_excluded


HA_WRITABLE_ALLOWLIST, HA_EXCLUDED_SELECT_OPTIONS = _load_ha_security_config()


def is_ha_writable_allowed(field: Any) -> bool:
    """Return True if the field is both writable and in the Home Assistant writable allow-list."""
    from .safety import is_mutation_blocked
    if is_mutation_blocked(field):
        return False
    if not getattr(field, "is_writable", False):
        return False
    if field.is_compound:
        mapping_id = getattr(field, "mapping_id", None) or getattr(field, "name", "")
        return mapping_id in HA_WRITABLE_ALLOWLIST
    pt_name = getattr(field, "name", "") or str(getattr(field, "key", "")).split(".")[-1]
    f_key = getattr(field, "key", "")
    if pt_name in HA_WRITABLE_ALLOWLIST or f_key in HA_WRITABLE_ALLOWLIST:
        return True
    try:
        from .bounds import get_custom_bounds
        if get_custom_bounds(f_key, getattr(field, "device_sn", None), pt_name):
            return True
    except Exception:
        pass
    return False


def _filter_ha_options(options: Optional[List[str]]) -> Optional[List[str]]:
    if not options:
        return options
    return [opt for opt in options if opt not in HA_EXCLUDED_SELECT_OPTIONS]


def get_default_seed_config_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_HA_DEFAULT_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_HA_DEFAULT_CONFIG_FILE
    return repo_root / DEFAULT_HA_DEFAULT_CONFIG_FILE


def get_default_ha_config_path() -> Path:
    if is_addon_data_env():
        return data_dir() / DEFAULT_HA_CONFIG_FILE
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_HA_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_HA_CONFIG_FILE
    if (repo_root / DEFAULT_HA_CONFIG_FILE).exists():
        return repo_root / DEFAULT_HA_CONFIG_FILE
    if (repo_root / "config").exists():
        return repo_root / "config" / DEFAULT_HA_CONFIG_FILE
    return data_dir() / DEFAULT_HA_CONFIG_FILE


def is_field_selected(
    field_key: str,
    device_sn: Optional[str],
    selected_keys: List[str] | Set[str],
    mqtt_key: Optional[str] = None,
) -> bool:
    """Check if a field is selected, supporting both device-scoped ('<sn>:<key>') and legacy global keys."""
    if not selected_keys:
        return False
    s_set = selected_keys if isinstance(selected_keys, set) else set(selected_keys)
    # Selected keys are normalized at load time (qualify_legacy_ha_config): '<SERIAL_UPPER>:<field_key>'.
    if device_sn:
        prefix = f"{device_sn.strip().upper()}:"
        if f"{prefix}{field_key}" in s_set:
            return True
        if mqtt_key and f"{prefix}{mqtt_key}" in s_set:
            return True

    # Legacy global keys (no serial prefix) are only present until a device of that type registers.
    if field_key in s_set:
        return True
    if mqtt_key and mqtt_key in s_set:
        return True
    return False


def load_ha_config(
    config_path: Optional[Path | str] = None,
    allow_default_seed: bool = True,
) -> List[str]:
    """Load list of selected field keys from ha_config.yaml.

    If the file does not exist or contains no selected fields, and allow_default_seed is True,
    falls back to ha_default_config.yaml as an initial seed.
    """
    path = Path(config_path) if config_path else get_default_ha_config_path()
    fields: List[str] = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                raw_fields = data.get("selected_fields")
                if raw_fields:
                    fields = [str(x).strip() for x in raw_fields if x is not None and str(x).strip()]
        except Exception as e:
            logger.error("Failed to load %s: %s", path, e)

    if not fields and allow_default_seed:
        seed_path = get_default_seed_config_path()
        if seed_path.exists():
            try:
                with open(seed_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    raw_fields = data.get("selected_fields")
                    if raw_fields:
                        fields = [str(x).strip() for x in raw_fields if x is not None and str(x).strip()]
            except Exception as e:
                logger.error("Failed to load default seed %s: %s", seed_path, e)

    return fields


_LEGACY_CONCEPT_REMAP: Dict[str, str] = {
    "inverter.concept.ac_frequency": "inverter.inverter.Hz",
    "inverter.concept.grid_exported_energy_wh": "inverter.compound.grid_exported_energy",
    "inverter.concept.grid_imported_energy_wh": "inverter.compound.grid_imported_energy",
    "inverter.concept.inverter_output_power": "inverter.compound.inverter_output_power",
    "inverter.concept.inverter_output_power_w": "inverter.compound.inverter_output_power",
    "inverter.concept.inverter_state": "inverter.live.inverter_state_name",
    "inverter.concept.a": "inverter.inverter.A",
    "inverter.concept.aphb": "inverter.inverter.AphB",
    "battery.concept.battery_voltage": "battery.compound.battery_voltage",
    "battery.concept.battery_soh": "battery.live.state_of_health",
    "pv_link.concept.iin": "pv_link.string_combiner.DCA",
}


def qualify_legacy_ha_config(selected_field_keys: Optional[List[str]], state_store: StateStore) -> List[str]:
    """Ensure all field keys are scoped by device serial number (<SERIAL>:<FIELD_KEY>)."""
    if not selected_field_keys:
        return []
    qualified: Set[str] = set()
    for k in selected_field_keys:
        if k is None:
            continue
        k_str = str(k).strip()
        if not k_str:
            continue
        if ":" in k_str:
            sn_part, field_part = k_str.split(":", 1)
            sn_part = sn_part.strip().upper()
            field_part = field_part.strip()
            # Remap or drop legacy concept/standalone artifacts
            if field_part in _LEGACY_CONCEPT_REMAP:
                field_part = _LEGACY_CONCEPT_REMAP[field_part]
            elif ".concept." in field_part or field_part.endswith("_None"):
                continue
            qualified.add(f"{sn_part}:{field_part}")
        else:
            # Legacy unqualified key, e.g. 'inverter.live.grid_power_w' or 'pv_link.string_combiner.DCW'
            if k_str in _LEGACY_CONCEPT_REMAP:
                k_str = _LEGACY_CONCEPT_REMAP[k_str]
            elif ".concept." in k_str or k_str.endswith("_None"):
                continue
            dot_idx = k_str.find(".")
            dev_type = k_str[:dot_idx] if dot_idx != -1 else ""
            devices = [d for d in state_store.devices.values() if d.device_type == dev_type]
            if devices:
                for dev in devices:
                    qualified.add(f"{dev.serial_number.strip().upper()}:{k_str}")
            else:
                # If device not found yet in state_store, keep key as fallback
                qualified.add(k_str)
    return sorted(list(qualified))


def reset_ha_config_to_defaults(
    state_store: StateStore,
    config_path: Optional[Path | str] = None,
) -> List[str]:
    """Reset ha_config.yaml to seed ha_default_config.yaml qualified for live devices."""
    seed_path = get_default_seed_config_path()
    raw_seed = load_ha_config(seed_path, allow_default_seed=False)
    if not raw_seed:
        raw_seed = get_recommended_field_keys(state_store)
    qualified = qualify_legacy_ha_config(raw_seed, state_store)
    save_ha_config(qualified, category_overrides={}, config_path=config_path)
    return qualified


def load_ha_category_overrides(config_path: Optional[Path | str] = None) -> Dict[str, str]:
    """Load dictionary of entity category overrides from ha_config.yaml.

    Returns mapping of '<SERIAL>:<FIELD_KEY>' (or '<FIELD_KEY>') -> 'primary' | 'diagnostic' | 'config'.
    """
    path = Path(config_path) if config_path else get_default_ha_config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                raw_overrides = data.get("category_overrides") or data.get("entity_categories")
                if isinstance(raw_overrides, dict):
                    return {str(k).strip(): str(v).strip().lower() for k, v in raw_overrides.items() if k and v}
        except Exception as e:
            logger.error("Failed to load category overrides from %s: %s", path, e)
    return {}


def save_ha_config(
    selected_field_keys: Optional[List[str]],
    category_overrides: Optional[Dict[str, str]] = None,
    config_path: Optional[Path | str] = None,
):
    """Save list of selected field keys and category overrides to ha_config.yaml."""
    path = Path(config_path) if config_path else get_default_ha_config_path()
    clean_keys = sorted(list({str(k).strip() for k in (selected_field_keys or []) if k is not None and str(k).strip()}))

    clean_overrides: Dict[str, str] = {}
    if category_overrides is not None:
        clean_overrides = {str(k).strip(): str(v).strip().lower() for k, v in category_overrides.items() if k and v}
    else:
        clean_overrides = load_ha_category_overrides(path)

    doc: Dict[str, Any] = {"selected_fields": clean_keys}
    if clean_overrides:
        doc["category_overrides"] = dict(sorted(clean_overrides.items()))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(
                doc,
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        tmp_path.replace(path)
        logger.info("Saved %d entities and %d category overrides to %s", len(clean_keys), len(clean_overrides), path)
    except Exception as e:
        logger.error("Failed to save %s: %s", path, e)
        raise e


def save_ha_category_override(
    device_sn: Optional[str],
    field_key: str,
    category: Optional[str],
    config_path: Optional[Path | str] = None,
) -> Dict[str, str]:
    """Save or remove a single entity category override in ha_config.yaml."""
    overrides = load_ha_category_overrides(config_path)
    sn_clean = (device_sn or "").strip().upper()
    qualified_key = f"{sn_clean}:{field_key.strip()}" if sn_clean else field_key.strip()

    cat_norm = (category or "").strip().lower()
    if not cat_norm or cat_norm in ("default", "none", "auto", "reset"):
        overrides.pop(qualified_key, None)
        if ":" in qualified_key:
            overrides.pop(field_key.strip(), None)
    else:
        overrides[qualified_key] = cat_norm

    selected = load_ha_config(config_path, allow_default_seed=True)
    save_ha_config(selected, category_overrides=overrides, config_path=config_path)
    return overrides


def get_effective_ha_category(
    field: Any,
    device: Any,
    category_overrides: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Determine the effective Home Assistant entity_category ('diagnostic', 'config', or None for primary).

    Respects user overrides from category_overrides first. Otherwise evaluates
    is_diagnostic_point heuristics, pv_link overrides, and explicit field hints.
    """
    dev_sn = getattr(device, "serial_number", str(device) if isinstance(device, str) else "").strip().upper()
    dev_type = getattr(device, "device_type", None)

    # 1. Check user overrides
    if category_overrides:
        f_key = getattr(field, "key", getattr(field, "field_key", None)) or getattr(field, "id", "")
        concept_key = getattr(field, "concept_key", None)
        pt_name = getattr(field, "name", "")
        mqtt_k = getattr(field, "mqtt_key", None)

        candidates = []
        if dev_sn:
            if f_key:
                candidates.append(f"{dev_sn}:{f_key}")
            if concept_key:
                candidates.append(f"{dev_sn}:{concept_key}")
            if pt_name:
                candidates.append(f"{dev_sn}:{pt_name}")
            if mqtt_k:
                candidates.append(f"{dev_sn}:{mqtt_k}")
        if f_key:
            candidates.append(f_key)
        if concept_key:
            candidates.append(concept_key)
        if pt_name:
            candidates.append(pt_name)
        if mqtt_k:
            candidates.append(mqtt_k)

        for c in candidates:
            if c in category_overrides:
                val = str(category_overrides[c]).strip().lower()
                if val in ("primary", "sensor", "none", "null", ""):
                    return None
                if val in ("diagnostic", "config"):
                    return val

    # 2. Default logic
    is_writable = is_ha_writable_allowed(field)
    if is_writable:
        hint = getattr(field, "ha_hint", None)
        if hint and getattr(hint, "entity_category", None):
            return hint.entity_category
        return getattr(field, "entity_category", None)

    f_key = getattr(field, "key", getattr(field, "field_key", None)) or getattr(field, "id", "")
    sub_key = str(f_key).split(".", 1)[-1].replace(".", "_").lower() if f_key else ""
    pt_name_lower = str(getattr(field, "name", "")).lower()

    if dev_type == "pv_link" and (
        pt_name_lower in ("p", "e", "dcw", "dcwh", "dca")
        or sub_key in ("rebus_status_p", "rebus_status_e", "string_combiner_dca", "string_combiner_dcw", "string_combiner_dcwh")
    ):
        return None

    if is_diagnostic_point(getattr(field, "name", ""), getattr(field, "model_id", None), device_type=dev_type) or is_diagnostic_point(sub_key, device_type=dev_type):
        return "diagnostic"

    hint = getattr(field, "ha_hint", None)
    if hint and getattr(hint, "entity_category", None):
        return hint.entity_category

    return getattr(field, "entity_category", None)


def unqualify_ha_config(selected_field_keys: Optional[List[str]]) -> List[str]:
    """Strip device serial number prefixes from field keys and return deduplicated generic field IDs."""
    if not selected_field_keys:
        return []
    generic_keys: Set[str] = set()
    for k in selected_field_keys:
        if k is None:
            continue
        k_str = str(k).strip()
        if not k_str:
            continue
        if ":" in k_str:
            _, field_part = k_str.split(":", 1)
            generic_keys.add(field_part.strip())
        else:
            generic_keys.add(k_str)
    return sorted(list(generic_keys))


def generate_ha_default_config(
    source_path: Optional[Path | str] = None,
    target_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Generate generic ha_default_config dictionary and YAML string from current ha_config.yaml."""
    src = Path(source_path) if source_path else get_default_ha_config_path()
    dst = Path(target_path) if target_path else get_default_seed_config_path()

    if not src.exists():
        raise FileNotFoundError(f"Source configuration file not found: {src}")

    raw_keys = load_ha_config(config_path=src, allow_default_seed=False)
    generic_keys = unqualify_ha_config(raw_keys)

    existing_data: Dict[str, Any] = {}
    if dst.exists():
        try:
            with open(dst, "r", encoding="utf-8") as f_cur:
                existing_data = yaml.safe_load(f_cur) or {}
        except Exception:
            existing_data = {}

    out_dict = dict(existing_data)
    out_dict["selected_fields"] = generic_keys

    # Also generalize category overrides if present
    raw_overrides = load_ha_category_overrides(config_path=src)
    if raw_overrides:
        generic_overrides: Dict[str, str] = {}
        for ov_k, ov_v in raw_overrides.items():
            clean_k = ov_k.split(":", 1)[1].strip() if ":" in ov_k else ov_k.strip()
            generic_overrides[clean_k] = ov_v.strip().lower()
        if generic_overrides:
            out_dict["category_overrides"] = dict(sorted(generic_overrides.items()))

    yaml_header = (
        "# PWRcell Default Home Assistant Entity Configuration\n"
        "# Generated from existing ha_config.yaml (hardware serial numbers stripped)\n\n"
    )
    yaml_str = yaml_header + yaml.dump(out_dict, default_flow_style=False, sort_keys=False)
    return {
        "data": out_dict,
        "yaml": yaml_str,
        "selected_fields": generic_keys,
        "source_path": str(src),
        "target_path": str(dst),
    }


def export_default_config(
    source_path: Optional[Path | str] = None,
    target_path: Optional[Path | str] = None,
) -> List[str]:
    """Convert a device-specific ha_config.yaml into a generic ha_default_config.yaml.

    Strips hardware serial numbers and deduplicates field IDs so the result
    can serve as a universal default seed across any installation.
    """
    res = generate_ha_default_config(source_path=source_path, target_path=target_path)
    dst = Path(res["target_path"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.with_suffix(".tmp")
    with open(tmp_dst, "w", encoding="utf-8") as f:
        f.write(res["yaml"])
    tmp_dst.replace(dst)

    generic_keys = res["selected_fields"]
    logger.info("Exported %d generic default field IDs from %s to %s", len(generic_keys), res["source_path"], dst)
    return generic_keys


def get_recommended_field_keys(
    state_store: StateStore,
    device_sn: Optional[str] = None,
) -> List[str]:
    """Return keys for the standard recommended set of fields for Home Assistant."""
    clean_target_sn = device_sn.strip().upper() if device_sn else None

    # First attempt to load recommended seed keys from ha_default_config.yaml
    seed_path = get_default_seed_config_path()
    if seed_path.exists():
        raw_seed = load_ha_config(seed_path, allow_default_seed=False)
        if raw_seed:
            qualified = qualify_legacy_ha_config(raw_seed, state_store)
            if clean_target_sn:
                prefix = f"{clean_target_sn}:"
                qualified = [k for k in qualified if k.startswith(prefix)]
            return sorted(list(set(qualified)))

    recommended: List[str] = []
    if clean_target_sn:
        devices = [d for d in state_store.devices.values() if d.serial_number.strip().upper() == clean_target_sn]
    else:
        devices = list(state_store.devices.values())

    for dev in devices:
        sn = dev.serial_number.strip().upper()

        # Inverter metrics
        if dev.device_type == "inverter":
            for k in ("grid_power_w", "solar_power_w", "load_power_w", "system_mode"):
                full_key = f"inverter.live.{k}"
                if full_key in dev.fields:
                    recommended.append(f"{sn}:{full_key}")

        # Battery metrics
        elif dev.device_type == "battery":
            for k in ("state_of_charge", "state_of_health", "battery_power_w"):
                full_key = f"battery.live.{k}"
                if full_key in dev.fields:
                    recommended.append(f"{sn}:{full_key}")

        # Beacon controls
        elif dev.device_type == "rebus_beacon":
            for f_key, f in dev.fields.items():
                if f.name == "SysMd" and f.is_writable:
                    recommended.append(f"{sn}:{f_key}")

        # PV Links: power and energy per string
        elif dev.device_type == "pv_link":
            for f_key, f in dev.fields.items():
                if f.name in ("P", "E", "DCW", "DCWh") and not f.name.endswith("_sf"):
                    recommended.append(f"{sn}:{f_key}")

    return sorted(list(set(recommended)))


def get_device_info(
    device: UnifiedDevice,
    gateway_device: Optional[UnifiedDevice] = None,
) -> Dict[str, Any]:
    """Generate Home Assistant device dictionary with universally unique hardware identifiers."""
    clean_sn = device.serial_number.strip().upper()
    short_sn = clean_sn[-4:] if len(clean_sn) >= 4 else clean_sn

    dev_info: Dict[str, Any] = {
        "identifiers": [f"pwrcell_{clean_sn.lower()}"],
        "serial_number": clean_sn,
        "manufacturer": device.manufacturer or "Generac",
        "model": device.model_name,
        "sw_version": device.version or "1.0",
    }

    from .catalog import get_device_type_label
    dev_label = get_device_type_label(device.device_type) if device.device_type else device.model_name
    if device.device_type == "rebus_beacon":
        dev_info["name"] = f"PWRcell {dev_label}"
    else:
        dev_info["name"] = f"PWRcell {dev_label} ({short_sn})"

    # Device hierarchy: connect subordinate devices via gateway
    if gateway_device and gateway_device.serial_number != device.serial_number:
        dev_info["via_device"] = f"pwrcell_{gateway_device.serial_number.strip().lower()}"

    return dev_info


def generate_gateway_discovery_payload(
    gateway: UnifiedDevice,
    base_topic: str = "pwrcell",
    ha_prefix: str = "homeassistant",
) -> Dict[str, Any]:
    """Generate Home Assistant MQTT Discovery configuration for the top-level parent gateway device node."""
    gw_sn_lower = gateway.serial_number.strip().lower()
    gw_dev_info = get_device_info(gateway, gateway_device=None)
    gw_node_id = f"pwrcell_{gw_sn_lower}"
    gw_obj_id = "status"
    gw_config_topic = f"{ha_prefix}/binary_sensor/{gw_node_id}/{gw_obj_id}/config"
    gw_state_topic = f"{base_topic}/{gw_sn_lower}/status"
    gw_payload = {
        "has_entity_name": True,
        "name": "Status",
        "unique_id": f"pwrcell_{gw_sn_lower}_{gw_obj_id}",
        "object_id": f"{gateway.device_type}_{gw_sn_lower}_{gw_obj_id}",
        "state_topic": gw_state_topic,
        "payload_on": "online",
        "payload_off": "offline",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
        "device": gw_dev_info,
        "origin": ORIGIN_INFO,
        "availability": [
            {
                "topic": f"{base_topic}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ],
    }
    return {
        "config_topic": gw_config_topic,
        "state_topic": gw_state_topic,
        "attributes_topic": None,
        "command_topic": None,
        "old_sensor_topic": None,
        "legacy_config_topics": [],
        "suggested_display_precision": None,
        "availability_topic": f"{base_topic}/status",
        "device_availability_topic": gw_state_topic,
        "platform": "binary_sensor",
        "payload": gw_payload,
    }


def generate_discovery_payload(
    field: Any,
    device: UnifiedDevice,
    gateway_device: Optional[UnifiedDevice] = None,
    base_topic: str = "pwrcell",
    ha_prefix: str = "homeassistant",
    category_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Generate modern Home Assistant MQTT Discovery configuration dictionary and topics."""
    is_compound = field.is_compound
    is_writable = is_ha_writable_allowed(field)

    if is_compound:
        platform = field.ha_platform if (is_writable or field.ha_platform == "sensor") else "sensor"
        if is_writable and platform == "sensor":
            if getattr(field, "ha_options", None) or getattr(field, "ha_device_class", None) == "enum":
                platform = "select"
            else:
                platform = "number"
    else:
        hint = field.ha_hint
        if is_writable:
            if hint and hint.platform in ("select", "number", "switch"):
                platform = hint.platform
            elif getattr(field, "is_enum", False) or getattr(field, "symbols", None):
                platform = "select"
            else:
                platform = "number"
        elif hint and hint.platform:
            platform = hint.platform
        else:
            platform = "sensor"

    clean_sn = device.serial_number.strip().lower()

    if is_compound:
        concept_id = getattr(field, "concept_key", None) or getattr(field, "mapping_id", None) or getattr(field, "name", "")
        sub_key = str(concept_id).lower().replace(".", "_")
    else:
        # Build unique object_id from sub-key path (e.g. 'live_solar_power_w' or 'compound_grid_power')
        sub_key = field.key.split(".", 1)[-1].replace(".", "_").lower()
    
    node_id = f"pwrcell_{clean_sn}"
    object_id = sub_key
    unique_id = f"pwrcell_{clean_sn}_{sub_key}"

    config_topic = f"{ha_prefix}/{platform}/{node_id}/{object_id}/config"
    state_topic = f"{base_topic}/{clean_sn}/{object_id}/state"
    command_topic = f"{base_topic}/{clean_sn}/{object_id}/set"
    availability_topic = f"{base_topic}/status"
    device_availability_topic = f"{base_topic}/{clean_sn}/status"

    old_sensor_topic = f"{ha_prefix}/sensor/{node_id}/{object_id}/config" if platform in ("select", "number", "switch") else None

    raw_label = getattr(field, "label", None) or getattr(field, "name", "")
    name_clean = str(raw_label).strip()

    sub_key_lower = sub_key.lower()
    pt_name_lower = str(getattr(field, "name", "")).lower()

    legacy_config_topics = []
    candidates = {sub_key}
    if pt_name_lower:
        candidates.add(pt_name_lower)
    for c in candidates:
        for pfx in ("compound_", "concept_"):
            legacy_config_topics.append(f"{ha_prefix}/{platform}/{node_id}/{pfx}{c}/config")
            legacy_config_topics.append(f"{ha_prefix}/sensor/{node_id}/{pfx}{c}/config")
    # Exclude current config_topic and deduplicate
    legacy_config_topics = [t for t in dict.fromkeys(legacy_config_topics) if t != config_topic]

    # Friendly entity naming instead of raw SunSpec unit names
    if name_clean in ("Watts", "W") or sub_key_lower in ("inverter_w", "w"):
        name_clean = "Active Power"
    elif name_clean in ("Amps", "A") or sub_key_lower in ("inverter_a", "string_combiner_dca"):
        if device.device_type == "pv_link" or "string" in sub_key_lower or "dca" in sub_key_lower:
            name_clean = "String Current"
        else:
            name_clean = "AC Output Current"
    elif name_clean in ("Amps PhaseA", "AphA") or sub_key_lower in ("inverter_apha", "apha"):
        name_clean = "Phase A Current"
    elif name_clean in ("Amps PhaseB", "AphB") or sub_key_lower in ("inverter_aphb", "aphb"):
        name_clean = "Phase B Current"
    elif name_clean in ("Amps PhaseC", "AphC") or sub_key_lower in ("inverter_aphc", "aphc"):
        name_clean = "Phase C Current"
    elif name_clean.startswith("Phase Voltage AN") or sub_key_lower in ("inverter_phvpha", "phvpha"):
        name_clean = "Phase A Voltage"
    elif name_clean.startswith("Phase Voltage BN") or sub_key_lower in ("inverter_phvphb", "phvphb"):
        name_clean = "Phase B Voltage"
    elif name_clean.startswith("Phase Voltage CN") or sub_key_lower in ("inverter_phvphc", "phvphc"):
        name_clean = "Phase C Voltage"
    elif name_clean == "REbus Voltage " or sub_key_lower.endswith("rebus_status_v"):
        name_clean = "REbus Voltage"
    elif sub_key_lower in ("battery_soc", "state_of_charge") and name_clean.lower() in ("battery soc", "soc"):
        name_clean = "State of Charge"

    device_info = get_device_info(device, gateway_device=gateway_device)

    # Modern HA naming: has_entity_name=True ensures entity name is clean and prefixed by device name in HA UI
    payload: Dict[str, Any] = {
        "has_entity_name": True,
        "name": name_clean,
        "unique_id": unique_id,
        "object_id": f"{device.device_type}_{clean_sn}_{object_id}",
        "state_topic": state_topic,
        "availability_mode": "all",
        "availability": [
            {
                "topic": availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
            },
            {
                "topic": device_availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
            },
        ],
        "device": device_info,
        "origin": ORIGIN_INFO,
    }

    if is_compound:
        if platform == "select":
            payload["command_topic"] = command_topic
            if getattr(field, "ha_options", None):
                payload["options"] = _filter_ha_options(field.ha_options)
            if getattr(field, "entity_category", None):
                payload["entity_category"] = field.entity_category
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            u_raw = field.ha_unit or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
            if field.ha_device_class:
                payload["device_class"] = field.ha_device_class
            bounds = field.get_bounds() if hasattr(field, "get_bounds") else {}
            if bounds.get("min_value") is not None:
                payload["min"] = bounds["min_value"]
            if bounds.get("max_value") is not None:
                payload["max"] = bounds["max_value"]
            if isinstance(bounds.get("step"), (int, float)):
                payload["step"] = bounds["step"]
        else:
            if field.ha_device_class:
                payload["device_class"] = field.ha_device_class
            if field.ha_state_class:
                payload["state_class"] = field.ha_state_class
            u_raw = field.ha_unit or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
            if (platform == "select" or getattr(field, "ha_device_class", None) == "enum") and getattr(field, "ha_options", None):
                payload["options"] = field.ha_options
    elif field.ha_hint:
        hint = field.ha_hint
        if platform == "select":
            payload["command_topic"] = command_topic
            if hint.options:
                payload["options"] = _filter_ha_options(hint.options)
            elif getattr(field, "symbols", None):
                payload["options"] = _filter_ha_options([
                    s.name if hasattr(s, "name") else s["name"]
                    for s in sorted(field.symbols, key=lambda x: getattr(x, "value", x.get("value") if isinstance(x, dict) else 0))
                ])
            if hint.entity_category:
                payload["entity_category"] = hint.entity_category
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            u_raw = hint.unit_of_measurement or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
            if hint.device_class:
                payload["device_class"] = hint.device_class
            sf_val = device.get_scale_factor_value(field) if hasattr(device, "get_scale_factor_value") else None
            bounds = field.get_bounds(sf_value=sf_val) if hasattr(field, "get_bounds") else {}
            min_v = bounds.get("min_value") if bounds.get("min_value") is not None else hint.min_value
            max_v = bounds.get("max_value") if bounds.get("max_value") is not None else hint.max_value
            step_v = bounds.get("step") if isinstance(bounds.get("step"), (int, float)) else hint.step
            if min_v is not None:
                payload["min"] = min_v
            if max_v is not None:
                payload["max"] = max_v
            if step_v is not None:
                payload["step"] = step_v
            if hint.entity_category:
                payload["entity_category"] = hint.entity_category
        else:
            if hint.device_class:
                payload["device_class"] = hint.device_class
            if hint.state_class:
                payload["state_class"] = hint.state_class
            u_raw = hint.unit_of_measurement or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
            if hint.entity_category:
                payload["entity_category"] = hint.entity_category
            if hint.icon:
                payload["icon"] = hint.icon
            if hint.device_class == "enum" and hint.options:
                payload["options"] = hint.options
    elif is_writable:
        if platform == "select":
            payload["command_topic"] = command_topic
            if getattr(field, "symbols", None):
                payload["options"] = _filter_ha_options([
                    s.name if hasattr(s, "name") else s["name"]
                    for s in sorted(field.symbols, key=lambda x: getattr(x, "value", x.get("value") if isinstance(x, dict) else 0))
                ])
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            if field.units:
                payload["unit_of_measurement"] = normalize_ha_unit(field.units)
            sf_val = device.get_scale_factor_value(field) if hasattr(device, "get_scale_factor_value") else None
            bounds = field.get_bounds(sf_value=sf_val) if hasattr(field, "get_bounds") else {}
            if bounds.get("min_value") is not None:
                payload["min"] = bounds["min_value"]
            if bounds.get("max_value") is not None:
                payload["max"] = bounds["max_value"]
            if isinstance(bounds.get("step"), (int, float)):
                payload["step"] = bounds["step"]
    elif field.units:
        payload["unit_of_measurement"] = normalize_ha_unit(field.units)

    # 1. Temperature device_class and unit enforcement
    if (
        sub_key_lower.endswith(("_tmpcab", "_tmpsnk", "_tmptrns", "_tmpot", "_modtmpavg", "_modtmpmax", "_modtmpmin", "_celltmpavg", "_celltmpmax", "_celltmpmin"))
        or sub_key_lower in ("inverter_tmpcab", "inverter_tmpsnk", "inverter_tmptrns", "inverter_tmpot", "rebus_status_t")
        or pt_name_lower in ("t", "tmpcab", "tmpsnk", "tmptrns", "tmpot", "modtmpavg", "modtmpmax", "modtmpmin")
        or payload.get("device_class") == "temperature"
        or payload.get("unit_of_measurement") in ("°C", "C", "Deg C")
    ):
        payload["device_class"] = "temperature"
        payload["unit_of_measurement"] = "°C"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    # 2. Electrical sensor device_class enforcement
    if sub_key_lower in ("inverter_va", "va") or pt_name_lower == "va":
        payload["device_class"] = "apparent_power"
        payload["unit_of_measurement"] = "VA"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    if sub_key_lower in ("inverter_var", "var") or pt_name_lower in ("var", "var_sf"):
        payload["device_class"] = "reactive_power"
        payload["unit_of_measurement"] = "var"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    if sub_key_lower in ("inverter_pf", "pf") or pt_name_lower == "pf":
        payload["device_class"] = "power_factor"
        payload["unit_of_measurement"] = "%"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    # 3. Battery SoC device_class and unit enforcement
    if sub_key_lower in ("battery_soc", "state_of_charge") or pt_name_lower in ("battery_soc", "soc", "state_of_charge"):
        payload["device_class"] = "battery"
        payload["unit_of_measurement"] = "%"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    # 4. Number configuration entity bounds and device classes
    if platform == "number":
        norm_u = normalize_ha_unit(payload.get("unit_of_measurement"))
        if norm_u:
            payload["unit_of_measurement"] = norm_u
        if norm_u == "A" and not payload.get("device_class"):
            payload["device_class"] = "current"
        if norm_u == "%" or any(k in sub_key_lower for k in ("socmax", "socrsvmax", "socrsvmin", "socmin", "minrsvpct")):
            payload["mode"] = "slider"
            payload["step"] = 1
            if payload.get("max") is not None and payload["max"] > 100:
                payload["max"] = 100
            if payload.get("min") is not None and payload["min"] < 0:
                payload["min"] = 0

    # 5. Diagnostic entity categorization (honoring category_overrides and default heuristics)
    eff_cat = get_effective_ha_category(field, device, category_overrides=category_overrides)
    if eff_cat:
        payload["entity_category"] = eff_cat
    else:
        payload.pop("entity_category", None)

    # 6. HA schema validation: enum device_class requires options
    if payload.get("device_class") == "enum" and not payload.get("options"):
        payload.pop("device_class", None)

    precision = None
    if platform == "sensor":
        if is_compound:
            precision = getattr(field, "ha_suggested_display_precision", None)
            if precision is None:
                precision = get_suggested_precision(field.ha_unit or field.units, field.ha_device_class)
        elif field.ha_hint:
            precision = getattr(field.ha_hint, "suggested_display_precision", None)
            if precision is None:
                precision = get_suggested_precision(field.ha_hint.unit_of_measurement or field.units, field.ha_hint.device_class)
        elif field.units:
            precision = get_suggested_precision(field.units)

        if precision is not None:
            payload["suggested_display_precision"] = precision

    attributes_topic = None
    if getattr(field, "is_bitfield", False) or (getattr(field, "point_type", "") or "").startswith("bitfield"):
        attributes_topic = f"{base_topic}/{clean_sn}/{object_id}/attributes"
        payload["json_attributes_topic"] = attributes_topic
        if is_writable:
            payload["command_topic"] = command_topic

    return {
        "config_topic": config_topic,
        "state_topic": state_topic,
        "attributes_topic": attributes_topic,
        "command_topic": command_topic if is_writable else None,
        "old_sensor_topic": old_sensor_topic,
        "legacy_config_topics": legacy_config_topics,
        "suggested_display_precision": precision,
        "availability_topic": availability_topic,
        "device_availability_topic": device_availability_topic,
        "platform": platform,
        "payload": payload,
    }
