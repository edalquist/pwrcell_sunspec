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
from .catalog import get_suggested_precision
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


def get_default_seed_config_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_HA_DEFAULT_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_HA_DEFAULT_CONFIG_FILE
    return repo_root / DEFAULT_HA_DEFAULT_CONFIG_FILE


def get_default_ha_config_path() -> Path:
    # If running inside Home Assistant Add-on container with persistent /data
    if Path("/data").is_dir() and Path("/data/options.json").exists():
        return Path("/data/ha_config.yaml")
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_HA_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_HA_CONFIG_FILE
    if (repo_root / DEFAULT_HA_CONFIG_FILE).exists():
        return repo_root / DEFAULT_HA_CONFIG_FILE
    if (repo_root / "config").is_dir():
        return repo_root / "config" / DEFAULT_HA_CONFIG_FILE
    return repo_root / DEFAULT_HA_CONFIG_FILE


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
    if device_sn:
        clean_sn = device_sn.strip().upper()
        if f"{clean_sn}:{field_key}" in s_set:
            return True
        if mqtt_key and f"{clean_sn}:{mqtt_key}" in s_set:
            return True
        clean_sn_lower = device_sn.strip().lower()
        if f"{clean_sn_lower}:{field_key}" in s_set:
            return True
        if mqtt_key and f"{clean_sn_lower}:{mqtt_key}" in s_set:
            return True

    # Fall back to legacy global key (without device serial prefix)
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

    If the file does not exist and allow_default_seed is True, falls back to
    ha_default_config.yaml as an initial seed.
    """
    path = Path(config_path) if config_path else get_default_ha_config_path()
    if not path.exists():
        if allow_default_seed and not config_path:
            seed_path = get_default_seed_config_path()
            if seed_path.exists():
                try:
                    with open(seed_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                        return data.get("selected_fields", [])
                except Exception as e:
                    logger.error("Failed to load default seed %s: %s", seed_path, e)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("selected_fields", [])
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return []


def qualify_legacy_ha_config(selected_field_keys: List[str], state_store: StateStore) -> List[str]:
    """Ensure all field keys are scoped by device serial number (<SERIAL>:<FIELD_KEY>)."""
    qualified: Set[str] = set()
    for k in selected_field_keys:
        k_str = str(k).strip()
        if not k_str:
            continue
        if ":" in k_str:
            sn_part, field_part = k_str.split(":", 1)
            qualified.add(f"{sn_part.strip().upper()}:{field_part.strip()}")
        else:
            # Legacy unqualified key, e.g. 'inverter.live.grid_power_w' or 'pv_link.string_combiner.DCW'
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


def save_ha_config(selected_field_keys: List[str], config_path: Optional[Path | str] = None):
    """Save list of selected field keys to ha_config.yaml."""
    path = Path(config_path) if config_path else get_default_ha_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"selected_fields": sorted(list(set(selected_field_keys)))},
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        tmp_path.replace(path)
        logger.info("Saved %d entities to %s", len(selected_field_keys), path)
    except Exception as e:
        logger.error("Failed to save %s: %s", path, e)
        raise e


def unqualify_ha_config(selected_field_keys: List[str]) -> List[str]:
    """Strip device serial number prefixes from field keys and return deduplicated generic field IDs."""
    generic_keys: Set[str] = set()
    for k in selected_field_keys:
        k_str = str(k).strip()
        if not k_str:
            continue
        if ":" in k_str:
            _, field_part = k_str.split(":", 1)
            generic_keys.add(field_part.strip())
        else:
            generic_keys.add(k_str)
    return sorted(list(generic_keys))


def export_default_config(
    source_path: Optional[Path | str] = None,
    target_path: Optional[Path | str] = None,
) -> List[str]:
    """Convert a device-specific ha_config.yaml into a generic ha_default_config.yaml.

    Strips hardware serial numbers and deduplicates field IDs so the result
    can serve as a universal default seed across any installation.
    """
    src = Path(source_path) if source_path else get_default_ha_config_path()
    dst = Path(target_path) if target_path else get_default_seed_config_path()

    if not src.exists():
        raise FileNotFoundError(f"Source configuration file not found: {src}")

    raw_keys = load_ha_config(config_path=src, allow_default_seed=False)
    generic_keys = unqualify_ha_config(raw_keys)

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.with_suffix(".tmp")
    with open(tmp_dst, "w", encoding="utf-8") as f:
        f.write("# PWRcell Default Home Assistant Entity Configuration\n")
        f.write("# Generated from existing ha_config.yaml (hardware serial numbers stripped)\n\n")
        yaml.dump({"selected_fields": generic_keys}, f, default_flow_style=False, sort_keys=False)
    tmp_dst.replace(dst)

    logger.info("Exported %d generic default field IDs from %s to %s", len(generic_keys), src, dst)
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

    # Universally unique device naming
    if device.device_type == "pv_link":
        dev_info["name"] = f"PWRcell PV Link ({short_sn})"
    elif device.device_type == "battery":
        dev_info["name"] = f"PWRcell Battery ({short_sn})"
    elif device.device_type == "inverter":
        dev_info["name"] = f"PWRcell Inverter ({short_sn})"
    elif device.device_type == "rebus_beacon":
        dev_info["name"] = "PWRcell REbus Beacon"
    elif device.device_type == "icm":
        dev_info["name"] = "PWRcell Inverter Control Module"
    else:
        dev_info["name"] = f"PWRcell {device.model_name} ({short_sn})"

    # Device hierarchy: connect subordinate devices via gateway
    if gateway_device and gateway_device.serial_number != device.serial_number:
        dev_info["via_device"] = f"pwrcell_{gateway_device.serial_number.strip().lower()}"

    return dev_info


def generate_discovery_payload(
    field: Any,
    device: UnifiedDevice,
    gateway_device: Optional[UnifiedDevice] = None,
    base_topic: str = "pwrcell",
    ha_prefix: str = "homeassistant",
) -> Dict[str, Any]:
    """Generate modern Home Assistant MQTT Discovery configuration dictionary and topics."""
    is_compound = getattr(field, "is_compound", False)
    is_writable = getattr(field, "is_writable", False)

    if is_compound:
        platform = field.ha_platform
        if is_writable and platform == "sensor":
            if getattr(field, "ha_options", None) or getattr(field, "ha_device_class", None) == "enum":
                platform = "select"
            else:
                platform = "number"
    else:
        hint = field.ha_hint
        if hint and hint.platform:
            platform = hint.platform
        elif is_writable:
            if getattr(field, "is_enum", False) or getattr(field, "symbols", None):
                platform = "select"
            else:
                platform = "number"
        else:
            platform = "sensor"

    clean_sn = device.serial_number.strip().lower()

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

    device_info = get_device_info(device, gateway_device=gateway_device)

    # Modern HA naming: has_entity_name=True ensures entity name is clean and prefixed by device name in HA UI
    payload: Dict[str, Any] = {
        "has_entity_name": True,
        "name": field.label,
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
                payload["options"] = field.ha_options
            if getattr(field, "entity_category", None):
                payload["entity_category"] = field.entity_category
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            if field.ha_unit or field.units:
                payload["unit_of_measurement"] = field.ha_unit or field.units
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
            if field.ha_unit or field.units:
                payload["unit_of_measurement"] = field.ha_unit or field.units
            if (platform == "select" or getattr(field, "ha_device_class", None) == "enum") and getattr(field, "ha_options", None):
                payload["options"] = field.ha_options
    elif field.ha_hint:
        hint = field.ha_hint
        if platform == "select":
            payload["command_topic"] = command_topic
            if hint.options:
                payload["options"] = hint.options
            elif getattr(field, "symbols", None):
                payload["options"] = [
                    s.name if hasattr(s, "name") else s["name"]
                    for s in sorted(field.symbols, key=lambda x: getattr(x, "value", x.get("value") if isinstance(x, dict) else 0))
                ]
            if hint.entity_category:
                payload["entity_category"] = hint.entity_category
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            if hint.unit_of_measurement or field.units:
                payload["unit_of_measurement"] = hint.unit_of_measurement or field.units
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
            if hint.unit_of_measurement or field.units:
                payload["unit_of_measurement"] = hint.unit_of_measurement or field.units
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
                payload["options"] = [
                    s.name if hasattr(s, "name") else s["name"]
                    for s in sorted(field.symbols, key=lambda x: getattr(x, "value", x.get("value") if isinstance(x, dict) else 0))
                ]
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            if field.units:
                payload["unit_of_measurement"] = field.units
    elif field.units:
        payload["unit_of_measurement"] = field.units

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
        "suggested_display_precision": precision,
        "availability_topic": availability_topic,
        "device_availability_topic": device_availability_topic,
        "platform": platform,
        "payload": payload,
    }
