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
try:
    import yaml
except ImportError:
    yaml = None

from .state import FieldSource, StateField, StateStore, UnifiedDevice

logger = logging.getLogger(__name__)

DEFAULT_HA_CONFIG_FILE = "ha_config.yaml"

# Home Assistant Integration Provenance metadata (HA 2024+)
ORIGIN_INFO: Dict[str, str] = {
    "name": "PWRcell SunSpec",
    "sw_version": "3.0.0",
    "support_url": "https://github.com/edalquist/pwrcell_sunspec",
}


def get_default_ha_config_path() -> Path:
    # If running inside Home Assistant Add-on container with persistent /data
    if Path("/data").is_dir() and Path("/data/options.json").exists():
        return Path("/data/ha_config.yaml")
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / DEFAULT_HA_CONFIG_FILE


def load_ha_config(config_path: Optional[Path | str] = None) -> List[str]:
    """Load list of selected field keys from ha_config.yaml."""
    path = Path(config_path) if config_path else get_default_ha_config_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("selected_fields", [])
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return []


def save_ha_config(selected_field_keys: List[str], config_path: Optional[Path | str] = None):
    """Save list of selected field keys to ha_config.yaml."""
    path = Path(config_path) if config_path else get_default_ha_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"selected_fields": sorted(list(set(selected_field_keys)))},
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        logger.info("Saved %d entities to %s", len(selected_field_keys), path)
    except Exception as e:
        logger.error("Failed to save %s: %s", path, e)
        raise e


def get_recommended_field_keys(state_store: StateStore) -> List[str]:
    """Return keys for the standard recommended set of fields for Home Assistant."""
    recommended: List[str] = []

    # Live Inverter & Power metrics
    inv = state_store.get_inverter()
    if inv:
        for k in ("grid_power_w", "solar_power_w", "load_power_w", "system_mode"):
            full_key = f"inverter.live.{k}"
            if full_key in inv.fields:
                recommended.append(full_key)

    # Live Battery metrics
    bat = state_store.get_battery()
    if bat:
        for k in ("state_of_charge", "state_of_health", "battery_power_w"):
            full_key = f"battery.live.{k}"
            if full_key in bat.fields:
                recommended.append(full_key)

    # Writable System Mode on Beacon or Inverter
    beacon = state_store.get_beacon()
    if beacon:
        for f_key, f in beacon.fields.items():
            if f.name == "SysMd" and f.is_writable:
                recommended.append(f_key)

    # PV Links: power and energy
    for dev in state_store.get_devices_by_type("pv_link"):
        for f_key, f in dev.fields.items():
            if f.name in ("P", "E", "DCW", "DCWh") and not f.name.endswith("_sf"):
                recommended.append(f_key)

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
    platform = field.ha_platform if is_compound else (field.ha_hint.platform if field.ha_hint else "sensor")
    clean_sn = device.serial_number.strip().lower()
    short_sn = clean_sn[-4:] if len(clean_sn) >= 4 else clean_sn

    # Build unique object_id from sub-key path (e.g. 'live_solar_power_w' or 'compound_grid_power')
    sub_key = field.key.split(".", 1)[-1].replace(".", "_").lower()
    
    node_id = f"pwrcell_{clean_sn}"
    object_id = sub_key
    unique_id = f"pwrcell_{clean_sn}_{sub_key}"

    config_topic = f"{ha_prefix}/{platform}/{node_id}/{object_id}/config"
    state_topic = f"{base_topic}/{clean_sn}/{object_id}/state"
    command_topic = f"{base_topic}/{clean_sn}/{object_id}/set"
    availability_topic = f"{base_topic}/status"

    device_info = get_device_info(device, gateway_device=gateway_device)

    # Modern HA naming: has_entity_name=True ensures entity name is clean and prefixed by device name in HA UI
    payload: Dict[str, Any] = {
        "has_entity_name": True,
        "name": field.label,
        "unique_id": unique_id,
        "object_id": f"{device.device_type}_{short_sn}_{object_id}",
        "state_topic": state_topic,
        "availability": [
            {
                "topic": availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ],
        "device": device_info,
        "origin": ORIGIN_INFO,
    }

    if is_compound:
        if field.ha_device_class:
            payload["device_class"] = field.ha_device_class
        if field.ha_state_class:
            payload["state_class"] = field.ha_state_class
        if field.ha_unit or field.units:
            payload["unit_of_measurement"] = field.ha_unit or field.units
        if platform in ("select", "number") and field.is_writable:
            payload["command_topic"] = command_topic
    elif field.ha_hint:
        hint = field.ha_hint
        if hint.device_class:
            payload["device_class"] = hint.device_class
        if hint.state_class:
            payload["state_class"] = hint.state_class
        if hint.unit_of_measurement:
            payload["unit_of_measurement"] = hint.unit_of_measurement
        if hint.entity_category:
            payload["entity_category"] = hint.entity_category
        if hint.icon:
            payload["icon"] = hint.icon
        if platform == "select" and hint.options:
            payload["options"] = hint.options
            payload["command_topic"] = command_topic
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            if hint.min_value is not None:
                payload["min"] = hint.min_value
            if hint.max_value is not None:
                payload["max"] = hint.max_value
            if hint.step is not None:
                payload["step"] = hint.step
    elif field.units:
        payload["unit_of_measurement"] = field.units

    attributes_topic = None
    if getattr(field, "is_bitfield", False) or (getattr(field, "point_type", "") or "").startswith("bitfield"):
        attributes_topic = f"{base_topic}/{clean_sn}/{object_id}/attributes"
        payload["json_attributes_topic"] = attributes_topic
        if field.is_writable:
            payload["command_topic"] = command_topic

    return {
        "config_topic": config_topic,
        "state_topic": state_topic,
        "attributes_topic": attributes_topic,
        "command_topic": command_topic if field.is_writable else None,
        "availability_topic": availability_topic,
        "platform": platform,
        "payload": payload,
    }
