"""Unified Device State Store for Generac PWRcell.

Maintains a single coherent in-memory state tree merging real-time push telemetry
from internal MQTT with SunSpec Modbus registers, providing field-level metadata,
Home Assistant hints, and change subscription hooks.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .catalog import (
    HomeAssistantHint,
    ModelCatalog,
    SUNSPEC_SENTINELS_BY_TYPE,
    SunspecPointDef,
    get_catalog,
    get_suggested_precision,
    is_scale_factor_point,
    is_sunspec_sentinel,
)
from .mapping import MappingRegistry, apply_transform
from .mqtt import LiveTelemetrySnapshot

logger = logging.getLogger(__name__)


# Plausibility bounds by measurement kind: (label, min, max, symmetric_abs_only)
_BOUNDS_BY_KIND = {
    "voltage": ("voltage", -10.0, 2000.0),      # PV/battery systems operate up to 1500V DC
    "frequency": ("frequency", 0.0, 100.0),     # 60Hz nominal, allowing generator ramps
    "percent": ("percentage", 0.0, 110.0),      # SoC/SoH with small float headroom
    "temperature": ("temperature", -60.0, 250.0),
    "power": ("power", -1000000.0, 1000000.0),  # up to 1 MW
    "power_kw": ("power", -1000.0, 1000.0),
    "current": ("current", -1000.0, 1000.0),    # whole-home CT services up to 1,000A
}
_KIND_BY_UNIT = {
    "V": "voltage", "HZ": "frequency", "%": "percent",
    "°C": "temperature", "C": "temperature", "DEG C": "temperature", "DEGC": "temperature",
    "W": "power", "KW": "power_kw", "A": "current",
}
_KIND_BY_DEVICE_CLASS = {
    "voltage": "voltage", "frequency": "frequency", "battery": "percent",
    "temperature": "temperature", "power": "power", "current": "current",
}


def validate_field_value(
    value: Any,
    units: Optional[str] = None,
    device_class: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[Any]:
    """Validate a parsed/scaled field value against physical plausibility bounds.

    Bounds are selected from the explicit units (authoritative) or device_class metadata, never from
    point-name substrings. Returns None if the value is invalid or physically implausible.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value) or math.isinf(value):
            return None

        # Check astronomical scale/overflow
        if abs(value) > 1e12:
            return None

        kind = _KIND_BY_UNIT.get((units or "").strip().upper())
        if kind is None:
            kind = _KIND_BY_DEVICE_CLASS.get((device_class or "").strip().lower())
        if kind is not None:
            label, lo, hi = _BOUNDS_BY_KIND[kind]
            if value < lo or value > hi:
                logger.warning("Rejected out-of-bounds %s reading %s for %s (%s)", label, value, name, units)
                return None

    return value


class FieldSource(str, Enum):
    MQTT_PUSH = "MQTT_PUSH"
    MODBUS_POLL = "MODBUS_POLL"
    MODBUS_CONFIG = "MODBUS_CONFIG"
    COMPUTED = "COMPUTED"


def get_active_modbus_to_mqtt_mapping() -> Dict[str, str]:
    """Dynamically return modbus to mqtt mapping from MappingRegistry."""
    return MappingRegistry.get_instance().get_modbus_to_mqtt_map()


def get_active_raw_to_compound_mapping() -> Dict[str, str]:
    """Dynamically return raw field key to compound field key mapping from MappingRegistry."""
    return MappingRegistry.get_instance().get_raw_to_compound_map()


# ── Declarative MQTT push telemetry → StateStore field tables ────────────────
def _hint(device_class=None, state_class=None, unit=None, platform="sensor", category=None):
    return HomeAssistantHint(
        platform=platform, device_class=device_class, state_class=state_class,
        unit_of_measurement=unit, entity_category=category,
    )


_H_W = _hint("power", "measurement", "W")
_H_V = _hint("voltage", "measurement", "V")
_H_WH = _hint("energy", "total_increasing", "Wh")
_H_PCT = _hint("battery", "measurement", "%")
_H_DIAG = _hint(category="diagnostic")
_H_ENUM_DIAG = _hint("enum", category="diagnostic")

_TELEMETRY_CONDITIONS = {
    "always": lambda v: True,
    "notnone": lambda v: v is not None,
    "gt0": lambda v: v is not None and v > 0,
    "truthy": lambda v: bool(v),
}


def _r1(v):
    return round(v, 1)


def _ws_to_wh(v):
    return round(v / 3600.0, 1)


def _same(v):
    return v


# Name-valued attrs whose raw_value is the numeric code
_SNAPSHOT_RAW_ATTR = {"system_mode_name": "system_mode", "inverter_state_name": "inverter_state"}

# (devkey, name, label, description, snapshot attr, units, hint, condition, value converter)
_SNAPSHOT_FIELD_SPECS = [
    ("inv", "grid_power_w", "Grid Net Power", "Real-time power imported from (+) or exported to (-) utility grid", "grid_power_w", "W", _H_W, "always", _r1),
    ("inv", "solar_power_w", "Solar Production Power", "Total real-time solar generation across all PV strings", "solar_power_w", "W", _H_W, "always", _r1),
    ("inv", "load_power_w", "Home Consumption Power", "Real-time total electrical power consumed by home loads", "load_power_w", "W", _H_W, "always", _r1),
    ("inv", "system_mode", "Live System Mode", "Current system operating mode pushed from inverter", "system_mode_name", None, _hint("enum"), "always", _same),
    ("inv", "inverter_state", "Inverter State", "PWRcell inverter operational status code", "inverter_state", None, _H_DIAG, "notnone", _same),
    ("inv", "inverter_state_name", "Inverter State Name", "PWRcell inverter operational status description", "inverter_state_name", None, _H_ENUM_DIAG, "notnone", _same),
    ("inv", "inverter_id", "Inverter Serial Number", "Inverter unique identifier from MQTT push", "inverter_id", None, _H_DIAG, "truthy", _same),
    ("inv", "system_family", "System Architecture Family", "PWRcell system family architecture generation", "system_family", None, _H_DIAG, "truthy", _same),
    ("beacon", "gateway_id", "Gateway Serial Number", "REbus Beacon gateway identifier from MQTT telemetry", "gateway_id", None, _H_DIAG, "truthy", _same),
    ("beacon", "gateway_type", "Gateway Type", "REbus Beacon hardware gateway type", "gateway_type", None, _H_DIAG, "truthy", _same),
    ("bat", "battery_power_w", "Battery Power", "Real-time battery discharge (+) or charge (-) power", "battery_power_w", "W", _H_W, "always", _r1),
    ("bat", "state_of_charge", "State of Charge", "Battery state of charge percentage", "battery_soc", "%", _H_PCT, "notnone", _r1),
    ("bat", "state_of_health", "State of Health", "Battery state of health percentage", "battery_soh", "%", _H_PCT, "notnone", _r1),
]

# (channel type names, channel type id, [(devkey, name, label, description, channel attr, units, hint, condition, converter)])
# The first spec's devkey is the device the channel requires; first matching channel kind wins.
_CHANNEL_FIELD_SPECS = [
    (("NET", "NET_GRID"), 1, [
        ("inv", "grid_voltage_v", "Grid AC Voltage", "Real-time AC grid voltage", "voltage_v", "V", _H_V, "notnone", _r1),
        ("inv", "grid_imported_energy_wh", "Grid Imported Energy", "Cumulative grid imported energy", "imported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
        ("inv", "grid_exported_energy_wh", "Grid Exported Energy", "Cumulative grid exported energy", "exported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
    ]),
    (("GENERATION", "GENERATION_SOLAR"), 2, [
        ("inv", "solar_generation_energy_wh", "Solar Lifetime Generated Energy", "Cumulative solar PV generated energy", "exported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
    ]),
    (("CONSUMPTION", "CONSUMPTION_LOAD"), 3, [
        ("inv", "load_imported_energy_wh", "Home Consumption Energy", "Cumulative home consumption energy", "imported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
    ]),
    (("STORAGE", "STORAGE_BATTERY"), 4, [
        ("bat", "battery_voltage_v", "Battery DC Voltage", "Real-time battery pack DC voltage", "voltage_v", "V", _H_V, "notnone", _r1),
        ("bat", "battery_imported_energy_wh", "Battery Charged Energy", "Cumulative energy charged into battery", "imported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
        ("bat", "battery_exported_energy_wh", "Battery Discharged Energy", "Cumulative energy discharged from battery", "exported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
        ("bat", "max_charge_power_w", "Max Battery Charge Power", "Maximum rated battery charging power capability", "real_power_sink_max_w", "W", _H_W, "notnone", _r1),
        ("bat", "max_discharge_power_w", "Max Battery Discharge Power", "Maximum rated battery discharge power capability", "real_power_source_max_w", "W", _H_W, "notnone", _r1),
    ]),
    (("INVERTER_OUTPUT",), 5, [
        ("inv", "inverter_output_power_w", "Inverter AC Output Power", "Real-time inverter AC output real power", "real_power_w", "W", _H_W, "always", _r1),
        ("inv", "inverter_output_exported_energy_wh", "Inverter Output Exported Energy", "Cumulative inverter AC output energy", "exported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
        ("inv", "inverter_max_power_w", "System Max Power Capability", "Instantaneous maximum power capability of inverter and battery", "real_power_source_max_w", "W", _H_W, "truthy", _r1),
        ("bat", "max_discharge_power_w", "Max Battery Discharge Power", "Maximum rated discharge power capability", "real_power_source_max_w", "W", _H_W, "truthy", _r1),
    ]),
    (("STORAGE_AC",), 7, [
        ("bat", "storage_ac_discharged_energy_wh", "Battery AC Discharged Energy", "Cumulative AC energy discharged from battery", "exported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
        ("bat", "storage_ac_charged_energy_wh", "Battery AC Charged Energy", "Cumulative AC energy charged into battery", "imported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
    ]),
    (("GENERATION_AC",), 6, [
        ("inv", "solar_generation_ac_energy_wh", "Solar AC Generated Energy", "Cumulative AC energy generated from solar PV", "exported_energy_ws", "Wh", _H_WH, "gt0", _ws_to_wh),
    ]),
]



@dataclass
class CompoundFieldView:
    """A unified composite view over distinct MQTT push and Modbus poll telemetry fields.
    
    Preserves the two separate values and their timestamps while surfacing the latest value
    to external clients and the Web UI.
    """
    key: str  # e.g. 'inverter.compound.grid_power'
    mapping_id: str  # e.g. 'grid_power'
    device_sn: str
    device_type: str
    name: str  # e.g. 'grid_power'
    label: str  # e.g. 'Grid Net Power'
    description: str
    units: Optional[str] = None
    access: str = "R"
    is_writable: bool = False

    # The 3 observable values for UI and clients:
    latest_value: Any = None
    latest_source: str = "NONE"  # 'MQTT_PUSH' or 'MODBUS_POLL'
    latest_updated: float = 0.0

    mqtt_value: Any = None
    mqtt_raw_value: Any = None
    mqtt_key: Optional[str] = None
    mqtt_updated: Optional[float] = None

    modbus_value: Any = None  # Transformed value (e.g. negated CT power)
    modbus_raw_value: Any = None  # Untransformed Modbus point
    modbus_key: Optional[str] = None
    modbus_updated: Optional[float] = None

    delta: Optional[float] = None
    match_pct: Optional[float] = None
    modbus_candidates: List[str] = field(default_factory=list)

    ha_platform: str = "sensor"
    ha_device_class: Optional[str] = None
    ha_state_class: Optional[str] = None
    ha_unit: Optional[str] = None
    ha_options: Optional[List[str]] = None
    ha_suggested_display_precision: Optional[int] = None
    is_compound: bool = True
    model_id: Optional[int] = None
    model_name: str = "compound"
    model_label: str = "Merged Telemetry"

    def get_bounds(self) -> Dict[str, Any]:
        if self.ha_options:
            return {
                "category": "enum",
                "point_type": "enum16",
                "raw_min": 0,
                "raw_max": len(self.ha_options) - 1,
                "min_value": 0,
                "max_value": len(self.ha_options) - 1,
                "step": 1,
                "units": self.units,
                "valid_values": list(range(len(self.ha_options))),
                "valid_names": list(self.ha_options),
                "symbols": [{"value": i, "name": opt, "label": opt} for i, opt in enumerate(self.ha_options)],
                "sentinel": None,
                "description": f"{len(self.ha_options)} options: " + ", ".join(self.ha_options),
            }
        return {
            "category": "other",
            "point_type": None,
            "units": self.units,
            "sf": None,
            "sf_value": None,
            "sentinel": None,
            "description": f"Compound field {self.label}",
        }

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "mapping_id": self.mapping_id,
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "units": self.units,
            "access": self.access,
            "is_writable": self.is_writable,
            "bounds": self.get_bounds(),
            # The 3 values:
            "latest_value": self.latest_value,
            "latest_source": self.latest_source,
            "latest_updated": self.latest_updated,
            "value": self.latest_value,
            "source": self.latest_source,
            "mqtt_value": self.mqtt_value,
            "mqtt_raw_value": self.mqtt_raw_value,
            "mqtt_key": self.mqtt_key,
            "mqtt_updated": self.mqtt_updated,
            "modbus_value": self.modbus_value,
            "modbus_raw_value": self.modbus_raw_value,
            "modbus_key": self.modbus_key,
            "modbus_updated": self.modbus_updated,
            "modbus_candidates": self.modbus_candidates,
            "delta": round(self.delta, 2) if self.delta is not None else None,
            "match_pct": round(self.match_pct, 1) if self.match_pct is not None else None,
            "ha_platform": self.ha_platform,
            "ha_device_class": self.ha_device_class,
            "ha_state_class": self.ha_state_class,
            "ha_unit": self.ha_unit or self.units,
            "ha_options": self.ha_options,
            "is_compound": True,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "model_label": self.model_label,
            "last_updated": self.latest_updated,
        }



@dataclass
class StateField:
    """A single observable metric or configuration point on a device."""
    key: str  # e.g., 'inverter.live.solar_power_w' or 'inverter.inverter_status.SysMd'
    device_sn: str
    device_type: str  # 'inverter', 'battery', 'pv_link', 'rebus_beacon', 'icm'
    name: str  # e.g., 'solar_power_w' or 'SysMd'
    label: str  # Human readable label
    description: str
    value: Any  # Scaled/processed current value
    raw_value: Any
    units: Optional[str] = None
    point_type: Optional[str] = None  # e.g., 'enum16', 'uint16', 'int16', etc.
    is_enum: bool = False
    is_bitfield: bool = False
    bitmask_flags: Optional[List[str]] = None
    source: FieldSource = FieldSource.MODBUS_POLL
    access: str = "R"  # "R" or "RW"
    symbols: Optional[List[Any]] = None  # Enum/bitfield symbol defs or names
    is_scale_factor: bool = False
    scale_factor_point: Optional[str] = None
    offset: Optional[int] = None
    size: int = 1
    mqtt_equivalent: Optional[str] = None
    compound_key: Optional[str] = None
    is_compound_raw: bool = False
    ha_hint: Optional[HomeAssistantHint] = None
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    model_label: Optional[str] = None
    last_updated: float = field(default_factory=time.time)

    @property
    def is_compound(self) -> bool:
        """Raw fields are never compound views (CompoundFieldView.is_compound is True)."""
        return False

    @property
    def is_writable(self) -> bool:
        return self.access == "RW"

    @property
    def active_flags(self) -> List[str]:
        """List of active flag names if this field is a bitfield."""
        if self.bitmask_flags is not None:
            return self.bitmask_flags
        if self.is_bitfield and isinstance(self.value, list):
            return self.value
        return []

    def is_flag_set(self, flag_name: str) -> bool:
        """Check whether a specific flag is active in this bitfield."""
        if not self.is_bitfield:
            return False
        clean = flag_name.strip().upper()
        for f in self.active_flags:
            if f.upper() == clean:
                return True
        if isinstance(self.raw_value, int) and self.symbols:
            for s in self.symbols:
                s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
                s_val = s.get("value") if isinstance(s, dict) else getattr(s, "value", None)
                if s_name and s_name.upper() == clean and s_val is not None:
                    return bool(self.raw_value & (1 << int(s_val)))
        return False

    @property
    def flags_dict(self) -> Optional[Dict[str, bool]]:
        """Dictionary of {flag_name: bool} showing status of all known symbols for this bitfield."""
        if not self.is_bitfield or not self.symbols:
            return None
        active_set = {f.upper() for f in self.active_flags}
        res: Dict[str, bool] = {}
        for s in self.symbols:
            s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
            s_val = s.get("value") if isinstance(s, dict) else getattr(s, "value", None)
            if s_name:
                is_active = (s_name.upper() in active_set)
                if not is_active and isinstance(self.raw_value, int) and s_val is not None:
                    is_active = bool(self.raw_value & (1 << int(s_val)))
                res[s_name] = is_active
        return res

    def get_bounds(self, sf_value: Optional[int] = None) -> Dict[str, Any]:
        """Calculate SunSpec bounds restrictions for this field."""
        raw_bounds = {
            "uint16": (0, 65535),
            "int16": (-32768, 32767),
            "uint32": (0, 4294967295),
            "int32": (-2147483648, 2147483647),
            "uint64": (0, 18446744073709551615),
            "int64": (-9223372036854775808, 9223372036854775807),
            "acc16": (0, 65535),
            "acc32": (0, 4294967295),
            "acc64": (0, 18446744073709551615),
            "count": (0, 65535),
            "sunssf": (-10, 10),
        }

        sentinels = {
            "uint16": 0xFFFF,
            "int16": -0x8000,
            "uint32": 0xFFFFFFFF,
            "int32": -0x80000000,
            "sunssf": -0x8000,
            "acc16": 0xFFFF,
            "acc32": 0xFFFFFFFF,
        }

        p_type = self.point_type or "uint16"

        # 1. Enums
        if self.is_enum or (self.symbols and not self.is_bitfield):
            symbols_list = []
            valid_vals = []
            valid_names = []
            if self.symbols:
                for s in self.symbols:
                    s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", str(s))
                    s_val = s.get("value") if isinstance(s, dict) else getattr(s, "value", None)
                    s_lbl = s.get("label") if isinstance(s, dict) else getattr(s, "label", s_name)
                    if s_val is not None:
                        valid_vals.append(s_val)
                    if s_name:
                        valid_names.append(s_name)
                    symbols_list.append({"name": s_name, "value": s_val, "label": s_lbl})
            min_v = min(valid_vals) if valid_vals else 0
            max_v = max(valid_vals) if valid_vals else 65535
            desc = (
                f"{len(valid_names)} options: " + ", ".join(f"{s['name']}" + (f" ({s['value']})" if s['value'] is not None else "") for s in symbols_list)
                if symbols_list else f"Enum values: {min_v} to {max_v}"
            )
            return {
                "category": "enum",
                "point_type": p_type,
                "raw_min": min_v,
                "raw_max": max_v,
                "min_value": min_v,
                "max_value": max_v,
                "step": 1,
                "units": self.units,
                "symbols": symbols_list,
                "valid_values": valid_vals,
                "valid_names": valid_names,
                "sentinel": None,
                "description": desc,
            }

        # 2. Bitfields
        if self.is_bitfield:
            max_bits = self.size * 16
            max_mask = (1 << max_bits) - 1
            symbols_list = []
            if self.symbols:
                for s in self.symbols:
                    s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", str(s))
                    s_val = s.get("value") if isinstance(s, dict) else getattr(s, "value", 0)
                    s_lbl = s.get("label") if isinstance(s, dict) else getattr(s, "label", s_name)
                    symbols_list.append({"name": s_name, "value": s_val, "label": s_lbl})
            hex_mask = f"0x{max_mask:04X}" if max_bits == 16 else f"0x{max_mask:08X}"
            desc = f"Bitmask 0x0000 to {hex_mask} ({max_bits} bits, {len(symbols_list)} flags)"
            return {
                "category": "bitfield",
                "point_type": p_type,
                "raw_min": 0,
                "raw_max": max_mask,
                "min_value": 0,
                "max_value": max_mask,
                "step": 1,
                "max_bits": max_bits,
                "mask_hex": hex_mask,
                "units": self.units,
                "symbols": symbols_list,
                "sentinel": None,
                "description": desc,
            }

        # 3. Numeric types
        if p_type in raw_bounds:
            raw_min, raw_max = raw_bounds[p_type]
            scaled_min = None
            scaled_max = None
            step = 1
            if sf_value is not None and -10 <= sf_value <= 10:
                multiplier = 10.0 ** sf_value
                step = multiplier
                scaled_min = round(raw_min * multiplier, 6)
                scaled_max = round(raw_max * multiplier, 6)
                if step >= 1:
                    step = int(step)
                    scaled_min = int(scaled_min)
                    scaled_max = int(scaled_max)
                unit_str = f" {self.units}" if self.units else ""
                desc = f"{scaled_min} to {scaled_max}{unit_str} (raw: {raw_min:,} to {raw_max:,}, step: {step})"
            else:
                unit_str = f" {self.units}" if self.units else ""
                desc = f"{raw_min:,} to {raw_max:,}{unit_str}"

            return {
                "category": "numeric",
                "point_type": p_type,
                "raw_min": raw_min,
                "raw_max": raw_max,
                "scaled_min": scaled_min,
                "scaled_max": scaled_max,
                "min_value": scaled_min if scaled_min is not None else raw_min,
                "max_value": scaled_max if scaled_max is not None else raw_max,
                "step": step,
                "units": self.units,
                "sf": self.scale_factor_point,
                "sf_value": sf_value,
                "sentinel": sentinels.get(p_type),
                "description": desc,
            }

        # 4. Floats
        if p_type in ("float32", "float64"):
            return {
                "category": "float",
                "point_type": p_type,
                "raw_min": None,
                "raw_max": None,
                "min_value": None,
                "max_value": None,
                "step": "any",
                "units": self.units,
                "sf": None,
                "sf_value": None,
                "sentinel": None,
                "description": f"IEEE 754 {p_type} floating point" + (f" ({self.units})" if self.units else ""),
            }

        # 5. Strings
        if p_type == "string":
            max_len = self.size * 2
            return {
                "category": "string",
                "point_type": p_type,
                "max_length": max_len,
                "size_words": self.size,
                "units": None,
                "sf": None,
                "sf_value": None,
                "sentinel": None,
                "description": f"Max {max_len} characters ({self.size} registers)",
            }

        return {
            "category": "other",
            "point_type": p_type,
            "size_words": self.size,
            "units": self.units,
            "sf": self.scale_factor_point,
            "sf_value": None,
            "sentinel": None,
            "description": f"Type: {p_type}",
        }

    def to_dict(self, sf_value: Optional[int] = None) -> dict:
        serialized_symbols = None
        if self.symbols:
            serialized_symbols = []
            for s in self.symbols:
                if isinstance(s, dict):
                    serialized_symbols.append(s)
                elif hasattr(s, "to_dict"):
                    serialized_symbols.append(s.to_dict())
                elif hasattr(s, "name") and hasattr(s, "value"):
                    serialized_symbols.append({
                        "name": s.name,
                        "value": s.value,
                        "label": getattr(s, "label", None),
                        "desc": getattr(s, "desc", None),
                    })
                elif isinstance(s, str):
                    serialized_symbols.append({"name": s, "value": None, "label": s})

        raw_hex_str = None
        raw_bin_str = None
        if isinstance(self.raw_value, int) and -0x80000000 <= self.raw_value <= 0xFFFFFFFF:
            if self.size == 1:
                raw_hex_str = f"0x{self.raw_value & 0xFFFF:04X}"
                b = f"{self.raw_value & 0xFFFF:016b}"
                raw_bin_str = f"{b[0:4]} {b[4:8]} {b[8:12]} {b[12:16]}"
            elif self.size == 2:
                raw_hex_str = f"0x{self.raw_value & 0xFFFFFFFF:08X}"
                b = f"{self.raw_value & 0xFFFFFFFF:032b}"
                raw_bin_str = f"{b[0:4]} {b[4:8]} {b[8:12]} {b[12:16]} {b[16:20]} {b[20:24]} {b[24:28]} {b[28:32]}"
            else:
                raw_hex_str = f"0x{self.raw_value:X}"

        return {
            "key": self.key,
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "value": self.value,
            "raw_value": self.raw_value,
            "raw_hex": raw_hex_str,
            "raw_bin": raw_bin_str,
            "units": self.units,
            "point_type": self.point_type,
            "is_enum": self.is_enum,
            "is_bitfield": self.is_bitfield,
            "bitmask_flags": self.bitmask_flags or (self.active_flags if self.is_bitfield else None),
            "flags_dict": self.flags_dict if self.is_bitfield else None,
            "source": self.source.value,
            "access": self.access,
            "is_writable": self.is_writable,
            "bounds": self.get_bounds(sf_value=sf_value),
            "is_scale_factor": self.is_scale_factor,
            "scale_factor_point": self.scale_factor_point,
            "sf": self.scale_factor_point,
            "offset": self.offset,
            "size": self.size,
            "mqtt_equivalent": self.mqtt_equivalent,
            "compound_key": self.compound_key,
            "is_compound_raw": self.is_compound_raw,
            "symbols": serialized_symbols,
            "ha_platform": self.ha_hint.platform if self.ha_hint else "sensor",
            "ha_device_class": self.ha_hint.device_class if self.ha_hint else None,
            "ha_state_class": self.ha_hint.state_class if self.ha_hint else None,
            "ha_unit": self.ha_hint.unit_of_measurement if self.ha_hint else self.units,
            "ha_category": self.ha_hint.entity_category if self.ha_hint else None,
            "ha_options": self.ha_hint.options if self.ha_hint else None,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "model_label": self.model_label,
            "last_updated": self.last_updated,
            "data_age": round(max(0.0, time.time() - self.last_updated), 1) if self.last_updated > 0 else None,
        }


@dataclass
class UnifiedDevice:
    """Unified representation of a PWRcell device."""
    serial_number: str
    slave_id: Optional[int]
    device_type: str  # 'inverter', 'battery', 'pv_link', 'rebus_beacon', 'icm'
    model_name: str
    manufacturer: str
    version: str
    supported_models: List[int] = field(default_factory=list)
    fields: Dict[str, StateField] = field(default_factory=dict)
    online: bool = True
    last_seen: float = field(default_factory=time.time)

    def get_scale_factor_value(self, field: StateField) -> Optional[int]:
        if not field.scale_factor_point:
            return None
        fields_snapshot = dict(self.fields)
        parts = field.key.split(".")
        if len(parts) >= 2:
            group = parts[1]
            sf_key = f"{self.device_type}.{group}.{field.scale_factor_point}"
            if sf_key in fields_snapshot:
                val = fields_snapshot[sf_key].value
                if isinstance(val, (int, float)):
                    return int(val)
        for f in fields_snapshot.values():
            if f.name == field.scale_factor_point and isinstance(f.value, (int, float)):
                return int(f.value)
        return None

    def serialize_fields(self) -> Dict[str, dict]:
        fields_items = list(self.fields.items())
        return {
            f_key: f.to_dict(sf_value=self.get_scale_factor_value(f))
            for f_key, f in fields_items
        }

    def get_models_summary(self, catalog: Optional[ModelCatalog] = None) -> List[Dict[str, Any]]:
        cat = catalog or get_catalog()
        fields_values = list(self.fields.values())
        all_model_ids = set(self.supported_models)
        for f in fields_values:
            if f.model_id is not None:
                all_model_ids.add(f.model_id)

        result = []
        for mid in sorted(all_model_ids):
            m_def = cat.get_model(mid)
            pts_count = sum(1 for f in fields_values if f.model_id == mid)
            result.append({
                "model_id": mid,
                "name": m_def.name if m_def else f"model_{mid}",
                "label": m_def.label if m_def else f"Model {mid}",
                "desc": m_def.desc if m_def else "",
                "field_count": pts_count,
                "total_points": len(m_def.points) if m_def else 0,
            })
        return result

    def to_dict(self, catalog: Optional[ModelCatalog] = None) -> dict:
        models_summary = self.get_models_summary(catalog)
        return {
            "serial_number": self.serial_number,
            "slave_id": self.slave_id,
            "device_type": self.device_type,
            "model_name": self.model_name,
            "manufacturer": self.manufacturer,
            "version": self.version,
            "online": self.online,
            "last_seen": self.last_seen,
            "field_count": len(self.fields),
            "supported_models": self.supported_models,
            "models": models_summary,
            "model_count": len(models_summary),
        }


class StateStore:
    """Central state store managing all devices and field streams."""

    def __init__(self, catalog: Optional[ModelCatalog] = None):
        self.catalog = catalog or get_catalog()
        self.devices: Dict[str, UnifiedDevice] = {}  # serial_number -> UnifiedDevice
        self.devices_by_slave_id: Dict[int, UnifiedDevice] = {}
        self._listeners: List[Callable[[StateField], None]] = []
        self._compound_listeners: List[Callable[[CompoundFieldView], None]] = []
        self._monotonic_drop_counts: Dict[tuple[str, str], tuple[int, float]] = {}
        self._lock = threading.RLock()

    def register_device(
        self,
        serial_number: str,
        slave_id: Optional[int],
        device_type: str,
        model_name: str,
        manufacturer: str = "Generac",
        version: str = "",
        supported_models: Optional[List[int]] = None,
    ) -> UnifiedDevice:
        """Register or retrieve a unified device."""
        with self._lock:
            clean_sn = (serial_number or "").strip()
            if not clean_sn or clean_sn in ("0", "None"):
                clean_sn = f"SLAVE_{slave_id}" if slave_id is not None else f"UNKNOWN_{len(self.devices) + 1}"
            serial_number = clean_sn

            if serial_number in self.devices:
                dev = self.devices[serial_number]
                if slave_id is not None:
                    dev.slave_id = slave_id
                    self.devices_by_slave_id[slave_id] = dev
                if supported_models:
                    dev.supported_models = sorted(list(set(dev.supported_models + supported_models)))
                return dev

            dev = UnifiedDevice(
                serial_number=serial_number,
                slave_id=slave_id,
                device_type=device_type,
                model_name=model_name,
                manufacturer=manufacturer,
                version=version,
                supported_models=sorted(list(set(supported_models or []))),
            )
            self.devices[serial_number] = dev
            if slave_id is not None:
                self.devices_by_slave_id[slave_id] = dev
            return dev

    def set_supported_models(self, serial_number: str, model_ids: List[int]):
        """Update or add supported SunSpec models for a registered device."""
        with self._lock:
            dev = self.devices.get(serial_number)
            if dev:
                dev.supported_models = sorted(list(set(dev.supported_models + model_ids)))

    def update_device_metadata(
        self,
        serial_number: str,
        model_name: Optional[str] = None,
        version: Optional[str] = None,
    ):
        """Update device model_name and/or version under the state lock."""
        with self._lock:
            dev = self.devices.get(serial_number)
            if dev:
                if model_name:
                    dev.model_name = model_name
                if version:
                    dev.version = version

    def get_devices_snapshot(self) -> List[UnifiedDevice]:
        """Return a shallow list copy of registered devices under the state lock."""
        with self._lock:
            return list(self.devices.values())

    def get_device(self, serial_number: str) -> Optional[UnifiedDevice]:
        """Look up a registered device by serial number (exact or case-insensitive) under the state lock."""
        if not serial_number:
            return None
        with self._lock:
            dev = self.devices.get(serial_number)
            if dev is not None:
                return dev
            clean_sn = serial_number.strip().upper()
            for d in self.devices.values():
                if d.serial_number.strip().upper() == clean_sn:
                    return d
            return None

    def get_devices_by_type(self, device_type: str) -> List[UnifiedDevice]:
        with self._lock:
            return [d for d in self.devices.values() if d.device_type == device_type]

    def get_inverter(self) -> Optional[UnifiedDevice]:
        invs = self.get_devices_by_type("inverter")
        return invs[0] if invs else None

    def get_battery(self) -> Optional[UnifiedDevice]:
        bats = self.get_devices_by_type("battery")
        return bats[0] if bats else None

    def get_beacon(self) -> Optional[UnifiedDevice]:
        beacons = self.get_devices_by_type("rebus_beacon")
        return beacons[0] if beacons else None

    def find_fields(self, key: str) -> List[StateField]:
        """Find all StateField instances across all devices matching exact key or point suffix."""
        with self._lock:
            matched: List[StateField] = []
            devices_list = list(self.devices.values())
            for dev in devices_list:
                if key in dev.fields:
                    matched.append(dev.fields[key])

            if matched:
                return matched

            # Suffix match e.g. inverter.inverter_status.CTPow matching inverter.model_64208.CTPow
            parts = key.split(".")
            if len(parts) >= 3:
                target_dev_type = parts[0]
                target_point = parts[-1]
                for dev in devices_list:
                    if dev.device_type == target_dev_type:
                        for f_key, f_obj in list(dev.fields.items()):
                            if f_key.endswith(f".{target_point}") and f_obj.source != FieldSource.MQTT_PUSH:
                                matched.append(f_obj)
                                break
            return matched

    def _find_field(self, key: str) -> Optional[StateField]:
        """Find a StateField by exact key or by device_type + point_name suffix."""
        fields = self.find_fields(key)
        return fields[0] if fields else None

    def get_compound_view(self, mapping_id: str) -> Optional[CompoundFieldView]:
        """Compute compound view for a specific mapping id.
        
        Surfaces all 3 values (latest, mqtt, modbus) while preserving underlying state.
        """
        reg = MappingRegistry.get_instance()
        m = reg.get_by_id(mapping_id)
        if not m:
            return None

        # Determine target device
        target_dev = None
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
            else:
                target_dev = self.get_inverter() or self.get_beacon()
        if not target_dev:
            return None

        # 1. Lookup MQTT Field
        mqtt_field = self._find_field(m.mqtt_field)
        mqtt_val = mqtt_field.value if mqtt_field else None
        mqtt_raw = mqtt_field.raw_value if mqtt_field else None
        mqtt_upd = mqtt_field.last_updated if mqtt_field else None
        mqtt_k = mqtt_field.key if mqtt_field else m.mqtt_field

        # 2. Lookup Modbus Field (primary candidate then alternatives)
        candidates = [m.modbus_field] + [c for c in m.modbus_candidates if c != m.modbus_field]
        mb_fields: List[StateField] = []
        chosen_cand_key = m.modbus_field
        for cand_key in candidates:
            fields = self.find_fields(cand_key)
            if fields and any(f.value is not None for f in fields):
                mb_fields = fields
                chosen_cand_key = cand_key
                break
        if not mb_fields:
            mb_fields = self.find_fields(m.modbus_field)

        should_sum = (
            m.transform in ("sum", "sum_all", "sum_devices")
            or m.id == "solar_power"
            or (chosen_cand_key.startswith("pv_link.") and m.mqtt_field == "inverter.live.solar_power_w")
        )

        mb_field = mb_fields[0] if mb_fields else None
        if should_sum and mb_fields:
            num_vals = [f.value for f in mb_fields if isinstance(f.value, (int, float))]
            mb_raw = sum(num_vals) if num_vals else (0.0 if mb_fields else None)
            mb_upd = max((f.last_updated for f in mb_fields), default=None)
            mb_k = chosen_cand_key
            if m.transform and m.transform not in ("sum", "sum_all", "sum_devices"):
                mb_val = apply_transform(mb_raw, m.transform)
            else:
                mb_val = mb_raw
        else:
            mb_raw = mb_field.value if mb_field else None
            mb_upd = mb_field.last_updated if mb_field else None
            mb_k = mb_field.key if mb_field else chosen_cand_key
            mb_val = apply_transform(mb_raw, m.transform)

        # 3. Determine Latest Value
        if mqtt_upd is not None and mb_upd is not None:
            if mb_upd > mqtt_upd:
                latest_val = mb_val
                latest_src = FieldSource.MODBUS_POLL.value
                latest_upd = mb_upd
            else:
                latest_val = mqtt_val
                latest_src = FieldSource.MQTT_PUSH.value
                latest_upd = mqtt_upd
        elif mqtt_upd is not None:
            latest_val = mqtt_val
            latest_src = FieldSource.MQTT_PUSH.value
            latest_upd = mqtt_upd
        elif mb_upd is not None:
            latest_val = mb_val
            latest_src = FieldSource.MODBUS_POLL.value
            latest_upd = mb_upd
        else:
            latest_val = None
            latest_src = "NONE"
            latest_upd = 0.0

        # Compute delta and match percentage
        delta = None
        match_pct = None
        if isinstance(mqtt_val, (int, float)) and isinstance(mb_val, (int, float)):
            delta = abs(mqtt_val - mb_val)
            denom = max(abs(mqtt_val), abs(mb_val), 1.0)
            match_pct = max(0.0, 100.0 - (delta / denom * 100.0))

        key = f"{target_dev.device_type}.compound.{m.id}"
        is_writable = False
        if m.id == "system_mode":
            is_writable = True
        elif mb_field and mb_field.is_writable:
            is_writable = True
        else:
            for cand_key in candidates:
                pt_def = self.catalog.get_point_for_field(cand_key) if self.catalog else None
                if pt_def and pt_def.is_writable:
                    is_writable = True
                    break

        options = None
        if m.id == "system_mode":
            from .controls import OPERATING_MODES
            options = sorted(list(set(OPERATING_MODES.keys())))
        elif mb_field and mb_field.ha_hint and mb_field.ha_hint.options:
            options = mb_field.ha_hint.options
        elif is_writable:
            for cand_key in candidates:
                pt_def = self.catalog.get_point_for_field(cand_key) if self.catalog else None
                if pt_def and pt_def.symbols:
                    options = [s.name for s in sorted(pt_def.symbols, key=lambda x: x.value)]
                    break

        ha_platform = m.ha_platform
        ha_device_class = m.ha_device_class
        ha_state_class = m.ha_state_class
        if is_writable:
            if options or m.ha_device_class == "enum" or m.id == "system_mode":
                ha_platform = "select"
                ha_device_class = None
                ha_state_class = None
            elif m.unit and m.unit != "":
                ha_platform = "number"
                ha_state_class = None

        precision = None
        if ha_platform == "sensor":
            u = (m.unit or (mb_field.units if mb_field else (mqtt_field.units if mqtt_field else "")) or "").strip()
            precision = get_suggested_precision(u, device_class=ha_device_class, point_name=m.id)

        return CompoundFieldView(
            key=key,
            mapping_id=m.id,
            device_sn=target_dev.serial_number,
            device_type=target_dev.device_type,
            name=m.id,
            label=m.label,
            description=m.description,
            units=m.unit or (mb_field.units if mb_field else (mqtt_field.units if mqtt_field else None)),
            access="RW" if is_writable else "R",
            is_writable=is_writable,
            latest_value=latest_val,
            latest_source=latest_src,
            latest_updated=latest_upd,
            mqtt_value=mqtt_val,
            mqtt_raw_value=mqtt_raw,
            mqtt_key=mqtt_k,
            mqtt_updated=mqtt_upd,
            modbus_value=mb_val,
            modbus_raw_value=mb_raw,
            modbus_key=mb_k,
            modbus_updated=mb_upd,
            modbus_candidates=candidates,
            delta=delta,
            match_pct=match_pct,
            ha_platform=ha_platform,
            ha_device_class=ha_device_class,
            ha_state_class=ha_state_class,
            ha_unit=m.unit,
            ha_options=options,
            ha_suggested_display_precision=precision,
        )

    def get_compound_views(self, device_sn: Optional[str] = None) -> List[CompoundFieldView]:
        """Compute all compound views, optionally filtered by device_sn."""
        reg = MappingRegistry.get_instance()
        views = []
        for m in reg.get_all():
            view = self.get_compound_view(m.id)
            if view:
                if device_sn is None or view.device_sn == device_sn:
                    views.append(view)
        return views

    def get_unified_fields(
        self,
        device_sn: str,
        preferred_sources: Optional[Dict[str, str]] = None,
        ha_selected_keys: Optional[Set[str]] = None,
    ) -> List[Any]:
        """Compute unified semantic field groups for a device, grouping duplicate metrics across models."""
        from .optimizer import group_device_fields
        with self._lock:
            dev = self.devices.get(device_sn)
            if not dev:
                clean_sn = device_sn.strip().upper()
                for d in self.devices.values():
                    if d.serial_number.strip().upper() == clean_sn:
                        dev = d
                        break
            if not dev:
                return []
            return group_device_fields(
                dev,
                mapping_registry=MappingRegistry.get_instance(),
                ha_selected_keys=ha_selected_keys,
                preferred_sources=preferred_sources,
            )

    def subscribe_compound(self, listener: Callable[[CompoundFieldView], None]):
        """Register a callback for compound view updates."""
        with self._lock:
            self._compound_listeners.append(listener)

    def unsubscribe_compound(self, listener: Callable[[CompoundFieldView], None]):
        """Unregister a callback for compound view updates."""
        with self._lock:
            if listener in self._compound_listeners:
                self._compound_listeners.remove(listener)

    def notify_field_change(self, field_obj: StateField):
        """Notify registered listeners of a field change."""
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(field_obj)
            except Exception as e:
                logger.warning("Error in state change listener: %s", e)

    def notify_compound_change(self, c_view: Any):
        """Notify registered compound listeners of a compound view change."""
        with self._lock:
            compound_listeners = list(self._compound_listeners)
        for listener in compound_listeners:
            try:
                listener(c_view)
            except Exception as e:
                logger.warning("Error in compound change listener: %s", e)

    def _resolve_model_metadata(self, sub_group, model_id, model_name, model_label):
        """Resolve SunSpec model metadata from the sub-group name when not explicitly provided."""
        if model_id is not None or not sub_group:
            return model_id, model_name, model_label
        if sub_group == "live":
            return model_id, "live", "Push Telemetry"
        if sub_group == "compound":
            return model_id, "compound", "Merged Telemetry"
        cat_model = self.catalog.get_model_by_name(sub_group)
        if not cat_model and sub_group.startswith("model_"):
            try:
                cat_model = self.catalog.get_model(int(sub_group[6:]))
            except ValueError:
                pass
        if cat_model:
            return cat_model.model_id, cat_model.name, cat_model.label
        return model_id, model_name, model_label

    def _should_suppress_counter_drop(self, dev, key, name, existing, value, units, ha_hint) -> bool:
        """Monotonicity protection for lifetime total_increasing energy counters.

        PV Link counters (e.g. REbus_status.E, string_combiner.DCWh) are volatile daily/session
        counters that reset when de-energized, so they are exempt. Returns True if the update
        should be dropped as an anomalous reading.
        """
        device_sn = dev.serial_number
        is_total_inc = (
            dev.device_type != "pv_link"
            and ((ha_hint and ha_hint.state_class == "total_increasing") or (units in ("Wh", "kWh") and not name.endswith("_w")))
        )
        if not (is_total_inc and isinstance(existing.value, (int, float)) and existing.value > 100.0):
            return False
        drop_key = (device_sn, key)
        if not (isinstance(value, (int, float)) and value < existing.value):
            self._monotonic_drop_counts.pop(drop_key, None)
            return False
        if not (value <= 0 or (existing.value - value) > (0.1 * existing.value)):
            return False

        dev_info = f" on {dev.serial_number}" + (f" (slave {dev.slave_id})" if dev.slave_id is not None else "")
        prev_count, prev_cand = self._monotonic_drop_counts.get(drop_key, (0, 0.0))
        if value > 0 and prev_count > 0 and value >= prev_cand * 0.9:
            new_count = prev_count + 1
        elif value > 0:
            new_count = 1
        else:
            new_count = 0

        if new_count >= 3:
            logger.warning(
                "Accepted reset/lower baseline in cumulative energy counter %s%s after %d consecutive readings (%s -> %s)",
                key, dev_info, new_count, existing.value, value,
            )
            self._monotonic_drop_counts.pop(drop_key, None)
            return False
        if prev_count == 0:
            logger.warning(
                "Suppressed anomalous drop in cumulative energy counter %s%s (%s -> %s)",
                key, dev_info, existing.value, value,
            )
        self._monotonic_drop_counts[drop_key] = (max(1, new_count), float(value))
        return True

    @staticmethod
    def _build_field(dev, key, existing, *, name, label, description, value, raw_value, units, source,
                     access, symbols, point_type, is_enum, is_bitfield, bitmask_flags, is_scale_factor,
                     scale_factor_point, offset, size, ha_hint, model_id, model_name, model_label,
                     mqtt_eq, c_key) -> StateField:
        """Create a new StateField, or merge incoming metadata over an existing one."""
        def pick(new, old_attr):
            if new is not None or existing is None:
                return new
            return getattr(existing, old_attr)

        if existing is None:
            merged_label = label
            merged_access = access
            merged_size = size
            merged_bitfield = bool(is_bitfield)
            merged_flags = bitmask_flags or (value if (is_bitfield and isinstance(value, list)) else None)
        else:
            merged_label = label if (label and label != existing.name) else existing.label
            merged_access = access if (access != "R" or existing.access == "R") else existing.access
            merged_size = size if (size != 1 or existing.size == 1) else existing.size
            merged_bitfield = bool(pick(is_bitfield, "is_bitfield"))
            if bitmask_flags is not None:
                merged_flags = bitmask_flags
            elif merged_bitfield and isinstance(value, list):
                merged_flags = value
            else:
                merged_flags = existing.bitmask_flags

        merged_pt_type = pick(point_type, "point_type")
        return StateField(
            key=key,
            device_sn=dev.serial_number,
            device_type=dev.device_type,
            name=name,
            label=merged_label,
            description=description if (description or existing is None) else existing.description,
            value=value,
            raw_value=raw_value,
            units=pick(units, "units"),
            point_type=merged_pt_type,
            is_enum=bool(pick(is_enum, "is_enum")),
            is_bitfield=merged_bitfield,
            bitmask_flags=merged_flags,
            source=pick(source, "source"),
            access=merged_access,
            symbols=pick(symbols, "symbols"),
            is_scale_factor=is_scale_factor_point(
                name=name,
                point_type=merged_pt_type,
                label=merged_label,
                explicit=bool(is_scale_factor or (existing and existing.is_scale_factor)),
            ),
            scale_factor_point=pick(scale_factor_point, "scale_factor_point"),
            offset=pick(offset, "offset"),
            size=merged_size,
            mqtt_equivalent=mqtt_eq,
            compound_key=c_key,
            is_compound_raw=bool(c_key),
            ha_hint=pick(ha_hint, "ha_hint"),
            model_id=pick(model_id, "model_id"),
            model_name=pick(model_name, "model_name"),
            model_label=pick(model_label, "model_label"),
            last_updated=time.time(),
        )

    def set_field(
        self,
        device_sn: str,
        name: str,
        label: str = "",
        description: str = "",
        value: Any = None,
        raw_value: Any = None,
        units: Optional[str] = None,
        source: FieldSource = FieldSource.MODBUS_POLL,
        access: str = "R",
        symbols: Optional[List[Any]] = None,
        point_type: Optional[str] = None,
        is_enum: Optional[bool] = None,
        is_bitfield: Optional[bool] = None,
        bitmask_flags: Optional[List[str]] = None,
        is_scale_factor: bool = False,
        scale_factor_point: Optional[str] = None,
        offset: Optional[int] = None,
        size: int = 1,
        ha_hint: Optional[HomeAssistantHint] = None,
        sub_group: Optional[str] = None,
        model_id: Optional[int] = None,
        model_name: Optional[str] = None,
        model_label: Optional[str] = None,
    ) -> StateField:
        """Set a field value, notify listeners and compound subscribers if changed."""
        with self._lock:
            dev = self.devices.get(device_sn)
            if not dev:
                raise ValueError(f"Device with serial number {device_sn} not registered")

            if not label:
                label = name

            # Validate value against physical plausibility and sentinels
            if value is not None:
                value = validate_field_value(
                    value,
                    units=units,
                    device_class=ha_hint.device_class if ha_hint else None,
                    name=name,
                )
            if isinstance(raw_value, float) and (math.isnan(raw_value) or math.isinf(raw_value)):
                raw_value = None
            if raw_value is None and value is not None:
                raw_value = value

            model_id, model_name, model_label = self._resolve_model_metadata(
                sub_group, model_id, model_name, model_label
            )

            if model_id is not None and model_id not in dev.supported_models:
                dev.supported_models = sorted(list(set(dev.supported_models + [model_id])))

            group_prefix = f"{sub_group}." if sub_group else ""
            key = f"{dev.device_type}.{group_prefix}{name}"
            mb_to_mqtt = get_active_modbus_to_mqtt_mapping()
            raw_to_comp = get_active_raw_to_compound_mapping()
            mqtt_eq = mb_to_mqtt.get(key)
            c_key = raw_to_comp.get(key) or (raw_to_comp.get(mqtt_eq) if mqtt_eq else None)

            existing = dev.fields.get(key)
            if existing is not None and self._should_suppress_counter_drop(dev, key, name, existing, value, units, ha_hint):
                return existing

            changed = existing is None or existing.value != value
            field_obj = self._build_field(
                dev, key, existing,
                name=name, label=label, description=description, value=value, raw_value=raw_value,
                units=units, source=source, access=access, symbols=symbols, point_type=point_type,
                is_enum=is_enum, is_bitfield=is_bitfield, bitmask_flags=bitmask_flags,
                is_scale_factor=is_scale_factor, scale_factor_point=scale_factor_point,
                offset=offset, size=size, ha_hint=ha_hint,
                model_id=model_id, model_name=model_name, model_label=model_label,
                mqtt_eq=mqtt_eq, c_key=c_key,
            )
            dev.fields[key] = field_obj

            dev.last_seen = time.time()
            listeners = list(self._listeners) if changed else []
            compound_listeners = list(self._compound_listeners) if changed else []

        # Check if this field affects any compound view
        affected_view = None
        if changed and compound_listeners:
            reg = MappingRegistry.get_instance()
            mapping = reg.get_by_mqtt(key) or reg.find_mapping_for_modbus(key)
            if mapping:
                affected_view = self.get_compound_view(mapping.id)

        # Notify outside lock
        for listener in listeners:
            try:
                listener(field_obj)
            except Exception as e:
                logger.warning("Error in state change listener: %s", e)

        if affected_view and compound_listeners:
            for c_listener in compound_listeners:
                try:
                    c_listener(affected_view)
                except Exception as e:
                    logger.warning("Error in compound change listener: %s", e)

        return field_obj

    def ensure_field_definition(self, device_sn: str, field_key: str) -> Optional[StateField]:
        """Ensure a StateField metadata definition exists for a device (resolving from catalog if not yet polled)."""
        dev = self.devices.get(device_sn)
        if not dev:
            return None

        if field_key in dev.fields:
            return dev.fields[field_key]

        parts = field_key.split(".")
        if len(parts) < 2:
            return None

        dev_type = parts[0]
        if dev_type != dev.device_type:
            return None

        sub_group = parts[1] if len(parts) >= 3 else ""
        name = parts[-1]

        # Compound fields are handled separately by get_compound_views()
        if sub_group == "compound":
            return None

        label = name
        description = ""
        units = None
        access = "R"
        point_type = "uint16"
        is_enum = False
        is_bitfield = False
        symbols = None
        ha_hint = None
        model_id = None
        model_name = sub_group
        model_label = sub_group

        source = FieldSource.MODBUS_POLL
        scale_factor_point = None
        offset = None
        size = 1
        is_scale_factor = False
        if sub_group == "live":
            label = name.replace("_", " ").title()
            model_name = "live"
            model_label = "Push Telemetry"
            source = FieldSource.MQTT_PUSH
            if name.endswith("_wh"):
                units = "Wh"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="energy", state_class="total_increasing", unit_of_measurement="Wh")
            elif name.endswith("_w"):
                units = "W"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="power", state_class="measurement", unit_of_measurement="W")
            elif name.endswith("_v"):
                units = "V"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="voltage", state_class="measurement", unit_of_measurement="V")
            elif name.endswith("_a"):
                units = "A"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="current", state_class="measurement", unit_of_measurement="A")
            elif name.endswith("_hz"):
                units = "Hz"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="frequency", state_class="measurement", unit_of_measurement="Hz")
            elif name.endswith("_deg_c") or name.endswith("_c"):
                units = "°C"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="temperature", state_class="measurement", unit_of_measurement="°C")
            elif name in ("state_of_charge", "state_of_health"):
                units = "%"
                ha_hint = HomeAssistantHint(platform="sensor", device_class="battery", state_class="measurement", unit_of_measurement="%")
            elif name == "system_mode":
                ha_hint = HomeAssistantHint(platform="sensor", device_class="enum")
        elif self.catalog:
            cat_model = self.catalog.get_model_by_name(sub_group)
            if not cat_model and sub_group.startswith("model_"):
                try:
                    cat_model = self.catalog.get_model(int(sub_group[6:]))
                except ValueError:
                    pass
            if cat_model:
                model_id = cat_model.model_id
                model_name = cat_model.name
                model_label = cat_model.label
                cat_point = cat_model.points.get(name)
                if cat_point:
                    label = cat_point.label or name
                    description = cat_point.desc or ""
                    units = cat_point.units
                    access = cat_point.access or "R"
                    point_type = cat_point.type or "uint16"
                    is_enum = cat_point.is_enum
                    is_bitfield = cat_point.is_bitfield
                    symbols = cat_point.symbols
                    is_scale_factor = cat_point.is_scale_factor
                    scale_factor_point = cat_point.sf
                    offset = cat_point.offset
                    size = cat_point.size
                    ha_hint = self.catalog.derive_ha_metadata(cat_point, model_id)

        return self.set_field(
            device_sn=device_sn,
            name=name,
            label=label,
            description=description,
            value=None,
            raw_value=None,
            units=units,
            access=access,
            point_type=point_type,
            is_enum=is_enum,
            is_bitfield=is_bitfield,
            symbols=symbols,
            is_scale_factor=is_scale_factor,
            scale_factor_point=scale_factor_point,
            offset=offset,
            size=size,
            ha_hint=ha_hint,
            sub_group=sub_group,
            model_id=model_id,
            model_name=model_name,
            model_label=model_label,
            source=source,
        )

    def update_from_telemetry_snapshot(self, snapshot: LiveTelemetrySnapshot):
        """Ingest a push telemetry snapshot from internal MQTT using declarative field tables."""
        devs = {"inv": self.get_inverter(), "bat": self.get_battery(), "beacon": self.get_beacon()}

        def emit(devkey, name, label, desc, value, raw, units, hint):
            dev = devs[devkey]
            self.set_field(
                device_sn=dev.serial_number,
                name=name,
                label=label,
                description=desc,
                value=value,
                raw_value=raw,
                units=units,
                source=FieldSource.MQTT_PUSH,
                ha_hint=hint,
                sub_group="live",
            )

        for devkey, name, label, desc, attr, units, hint, cond, conv in _SNAPSHOT_FIELD_SPECS:
            if not devs[devkey]:
                continue
            raw = getattr(snapshot, attr)
            if not _TELEMETRY_CONDITIONS[cond](raw):
                continue
            raw_attr = _SNAPSHOT_RAW_ATTR.get(attr, attr)
            emit(devkey, name, label, desc, conv(raw), getattr(snapshot, raw_attr), units, hint)

        # Ingest channel-level energy and voltage telemetries
        for ch in snapshot.channels.values():
            for names, ch_type, specs in _CHANNEL_FIELD_SPECS:
                primary_dev = specs[0][0]
                if not (ch.channel_type_name in names or ch.channel_type == ch_type) or not devs[primary_dev]:
                    continue
                for devkey, name, label, desc, attr, units, hint, cond, conv in specs:
                    if not devs[devkey]:
                        continue
                    raw = getattr(ch, attr)
                    if not _TELEMETRY_CONDITIONS[cond](raw):
                        continue
                    emit(devkey, name, label, desc, conv(raw), raw, units, hint)
                break

    def update_from_modbus_points(
        self,
        serial_number: str,
        model_id: int,
        raw_values: Dict[str, Any],
        computed_values: Optional[Dict[str, Any]] = None,
        instance_index: int = 0,
    ):
        """Update fields from a polled SunSpec Modbus model block.

        Accurately resolves SunSpec scale factors once, avoiding duplicate multiplier issues.
        """
        model_def = self.catalog.get_model(model_id)
        base_model_name = model_def.name if model_def else f"model_{model_id}"
        base_model_label = model_def.label if (model_def and model_def.label) else base_model_name
        model_name = f"{base_model_name}_{instance_index}" if instance_index > 0 else base_model_name
        model_label = f"{base_model_label} (#{instance_index})" if instance_index > 0 else base_model_label

        # Collect all valid scale factor point values in this block.
        # SunSpec scale factors MUST be in range [-10, 10] and must not be sentinels.
        scale_factors: Dict[str, int] = {}
        for pt_name, val in raw_values.items():
            pt_d = model_def.points.get(pt_name) if model_def else None
            is_sf_point = is_scale_factor_point(
                name=pt_name,
                point_type=pt_d.type if pt_d else None,
                label=pt_d.label if pt_d else None,
                explicit=bool(pt_d and pt_d.is_scale_factor),
            )
            if is_sf_point and isinstance(val, (int, float)):
                if not is_sunspec_sentinel(val, "sunssf") and -10 <= val <= 10:
                    int_val = int(val)
                    scale_factors[pt_name] = int_val
                    scale_factors[pt_name.lower()] = int_val
                    scale_factors[pt_name.upper()] = int_val

        for pt_name, raw_val in raw_values.items():
            pt_def = model_def.points.get(pt_name) if model_def else None
            if pt_name in ("ID", "L", "Pad") or pt_name.startswith("Pad") or (pt_def and pt_def.type == "pad"):
                continue
            label = pt_def.label if pt_def else pt_name
            desc = pt_def.desc if pt_def else ""
            units = pt_def.units if pt_def else None
            access = pt_def.access if pt_def else "R"
            pt_type = pt_def.type if pt_def else None

            # Determine final scaled value:
            # Case 1: Sentinel value or None represents an unimplemented register (checked at raw level by point type)
            if raw_val is None or is_sunspec_sentinel(raw_val, pt_type):
                raw_val = None
                scaled_val = None
            # Case 2: Pre-computed value provided (e.g. from safe_point_cvalue or MockPointValue.scaled_value)
            elif computed_values is not None and pt_name in computed_values:
                cand = computed_values[pt_name]
                if cand is not None and isinstance(cand, (int, float)):
                    if math.isnan(cand) or math.isinf(cand) or abs(cand) > 1e12:
                        scaled_val = None
                        raw_val = None
                    else:
                        scaled_val = cand
                else:
                    scaled_val = cand
                    if cand is None:
                        raw_val = None
            else:
                scaled_val = raw_val

            # If enum, lookup against enum symbols:
            # scaled_val becomes the enum symbol name, while raw_val remains the integer register value
            is_sentinel = raw_val is None or is_sunspec_sentinel(raw_val, pt_type)
            if pt_def and pt_def.is_enum and not is_sentinel:
                sym = None
                if isinstance(raw_val, int):
                    sym = pt_def.symbols_by_value.get(raw_val)
                elif isinstance(raw_val, str) and (raw_val.isdigit() or (raw_val.startswith("-") and raw_val[1:].isdigit())):
                    sym = pt_def.symbols_by_value.get(int(raw_val))
                elif isinstance(raw_val, str) and raw_val in pt_def.symbols_by_name:
                    sym = pt_def.symbols_by_name[raw_val]
                elif isinstance(scaled_val, int):
                    sym = pt_def.symbols_by_value.get(scaled_val)

                if sym is not None:
                    scaled_val = sym.name

            # If bitfield, decode integer bitmask into list of active symbol names:
            # scaled_val becomes the list of active flag names, while raw_val remains the integer register value
            bitmask_flags = None
            if pt_def and pt_def.is_bitfield and not is_sentinel:
                bit_val = raw_val if isinstance(raw_val, int) else (int(raw_val) if isinstance(raw_val, str) and (raw_val.isdigit() or (raw_val.startswith("-") and raw_val[1:].isdigit())) else None)
                if bit_val is not None:
                    bitmask_flags = pt_def.decode_bitfield(bit_val)
                    scaled_val = bitmask_flags
                elif isinstance(scaled_val, list):
                    bitmask_flags = scaled_val

            # Derive HA hints
            pt_sf = None
            if pt_def and pt_def.sf:
                sf_name = pt_def.sf
                pt_sf = scale_factors.get(sf_name) if sf_name in scale_factors else (
                    scale_factors.get(sf_name.lower()) if sf_name.lower() in scale_factors else scale_factors.get(sf_name.upper())
                )
            ha_hint = self.catalog.derive_ha_metadata(pt_def, model_id=model_id, sf_value=pt_sf) if pt_def else None

            # Symbol definitions if enum or bitfield
            symbols_defs = [s.to_dict() for s in pt_def.symbols] if (pt_def and (pt_def.is_enum or pt_def.is_bitfield or pt_def.symbols)) else None

            # Detect scale factor point
            is_sf = is_scale_factor_point(
                name=pt_name,
                point_type=pt_def.type if pt_def else None,
                label=label,
                explicit=bool(pt_def and pt_def.is_scale_factor),
            )

            self.set_field(
                device_sn=serial_number,
                name=pt_name,
                label=label,
                description=desc,
                value=scaled_val,
                raw_value=raw_val,
                units=units,
                source=FieldSource.MODBUS_POLL,
                access=access,
                symbols=symbols_defs,
                point_type=pt_def.type if pt_def else None,
                is_enum=pt_def.is_enum if pt_def else False,
                is_bitfield=pt_def.is_bitfield if pt_def else False,
                bitmask_flags=bitmask_flags,
                is_scale_factor=is_sf,
                scale_factor_point=pt_def.sf if pt_def else None,
                offset=pt_def.offset if pt_def else None,
                size=pt_def.size if pt_def else 1,
                ha_hint=ha_hint,
                sub_group=model_name,
                model_id=model_id,
                model_name=model_name,
                model_label=model_label,
            )

    def subscribe(self, listener: Callable[[StateField], None]):
        """Register a callback for field value changes."""
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[StateField], None]):
        """Unregister a callback for field value changes."""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def get_field_modbus_details(self, device_sn: str, field_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve comprehensive Modbus register details, scale factor definitions, and associated registers."""
        with self._lock:
            dev = self.devices.get(device_sn)
            if not dev:
                clean_sn = device_sn.strip().upper()
                for d in self.devices.values():
                    if d.serial_number.strip().upper() == clean_sn:
                        dev = d
                        break
            if not dev:
                return None

            # Check if requested key is a compound view
            c_view = None
            for cv in self.get_compound_views(dev.serial_number):
                if cv.key == field_key or cv.mapping_id == field_key:
                    c_view = cv
                    break

            underlying_mb_field = None
            if c_view:
                if c_view.modbus_key and c_view.modbus_key in dev.fields:
                    underlying_mb_field = dev.fields[c_view.modbus_key]
                else:
                    for cand in c_view.modbus_candidates:
                        if cand in dev.fields:
                            underlying_mb_field = dev.fields[cand]
                            break
                    if not underlying_mb_field and c_view.modbus_key:
                        underlying_mb_field = self.ensure_field_definition(dev.serial_number, c_view.modbus_key)

            target_field = underlying_mb_field if c_view else dev.fields.get(field_key)
            if not target_field and not c_view:
                # Check if requested key is a unified concept
                for ug in self.get_unified_fields(dev.serial_number):
                    if ug.id == field_key or ug.concept_key == field_key:
                        active_src = next((s for s in ug.sources if s.field_key == ug.active_source_key), None)
                        if not active_src:
                            active_src = next((s for s in ug.sources if s.model_id is not None), None)
                        if active_src:
                            target_field = dev.fields.get(active_src.field_key) or self.ensure_field_definition(dev.serial_number, active_src.field_key)
                            if target_field:
                                break
            if not target_field:
                target_field = self.ensure_field_definition(dev.serial_number, field_key)

            if not target_field and not c_view:
                return None

            # Point and model definition from catalog
            pt_def = None
            model_def = None
            if target_field:
                if target_field.model_id:
                    model_def = self.catalog.get_model(target_field.model_id)
                    if model_def:
                        pt_def = model_def.points.get(target_field.name)
                if not pt_def:
                    pt_def = self.catalog.get_point_for_field(target_field.key)
                    if pt_def and not model_def:
                        for m in self.catalog.models.values():
                            if target_field.name in m.points:
                                model_def = m
                                break

            # If target_field lacks offset or size, sync from pt_def
            if target_field and pt_def:
                if target_field.offset is None and pt_def.offset is not None:
                    target_field.offset = pt_def.offset
                if target_field.scale_factor_point is None and pt_def.sf:
                    target_field.scale_factor_point = pt_def.sf
                if target_field.size == 1 and pt_def.size != 1:
                    target_field.size = pt_def.size

            # Scale factor info
            sf_info = None
            sf_name = pt_def.sf if pt_def else (target_field.scale_factor_point if target_field else None)
            if sf_name and model_def:
                sf_pt_def = model_def.points.get(sf_name)
                sf_key = f"{dev.device_type}.{model_def.name}.{sf_name}"
                sf_field = dev.fields.get(sf_key)
                if not sf_field:
                    for f in dev.fields.values():
                        if f.model_id == model_def.model_id and f.name == sf_name:
                            sf_field = f
                            break
                if not sf_field:
                    sf_field = self.ensure_field_definition(dev.serial_number, sf_key)

                sf_val = sf_field.value if sf_field else None
                sf_raw = sf_field.raw_value if sf_field else None
                multiplier = None
                formula = None
                if sf_val is not None and isinstance(sf_val, (int, float)) and -10 <= sf_val <= 10:
                    multiplier = 10 ** int(sf_val)
                    if target_field and target_field.raw_value is not None:
                        formula = f"{target_field.raw_value} × 10^({int(sf_val)}) = {target_field.value} {target_field.units or ''}".strip()
                    else:
                        formula = f"Value = Raw × 10^({int(sf_val)})"

                sf_info = {
                    "name": sf_name,
                    "key": sf_field.key if sf_field else sf_key,
                    "label": sf_pt_def.label if sf_pt_def else (sf_field.label if sf_field else sf_name),
                    "description": sf_pt_def.desc if sf_pt_def else (sf_field.description if sf_field else ""),
                    "type": "sunssf",
                    "offset": sf_pt_def.offset if sf_pt_def else (sf_field.offset if sf_field else None),
                    "size": sf_pt_def.size if sf_pt_def else 1,
                    "value": sf_val,
                    "raw_value": sf_raw,
                    "raw_hex": f"0x{sf_raw & 0xFFFF:04X}" if isinstance(sf_raw, int) else None,
                    "multiplier": multiplier,
                    "formula": formula,
                }

            # Scaled points (if this field is a scale factor, or for the associated scale factor)
            scaled_points = []
            is_sf = target_field.is_scale_factor if target_field else False
            query_sf_name = target_field.name if is_sf else sf_name
            if query_sf_name and model_def:
                for p_name, p_d in model_def.points.items():
                    if p_d.sf == query_sf_name:
                        p_key = f"{dev.device_type}.{model_def.name}.{p_name}"
                        pf = dev.fields.get(p_key)
                        raw_v = pf.raw_value if pf else None
                        raw_h = None
                        if isinstance(raw_v, int):
                            raw_h = f"0x{raw_v & 0xFFFF:04X}" if p_d.size == 1 else f"0x{raw_v & 0xFFFFFFFF:08X}"
                        scaled_points.append({
                            "name": p_name,
                            "key": pf.key if pf else p_key,
                            "label": p_d.label or (pf.label if pf else p_name),
                            "description": p_d.desc or (pf.description if pf else ""),
                            "offset": p_d.offset,
                            "size": p_d.size,
                            "type": p_d.type,
                            "raw_value": raw_v,
                            "raw_hex": raw_h,
                            "value": pf.value if pf else None,
                            "units": p_d.units or (pf.units if pf else None),
                            "is_writable": p_d.is_writable,
                        })

            # Associated registers
            associated_registers = []
            if model_def and target_field:
                assoc_defs = model_def.get_associated_points(target_field.name)
                for item in assoc_defs:
                    p_d = item["point_def"]
                    p_key = f"{dev.device_type}.{model_def.name}.{p_d.name}"
                    pf = dev.fields.get(p_key)
                    raw_v = pf.raw_value if pf else None
                    raw_h = None
                    if isinstance(raw_v, int):
                        raw_h = f"0x{raw_v & 0xFFFF:04X}" if p_d.size == 1 else f"0x{raw_v & 0xFFFFFFFF:08X}"
                    associated_registers.append({
                        "name": p_d.name,
                        "key": pf.key if pf else p_key,
                        "label": p_d.label or (pf.label if pf else p_d.name),
                        "description": p_d.desc or (pf.description if pf else ""),
                        "relationship": item["relationship"],
                        "offset": p_d.offset,
                        "size": p_d.size,
                        "type": p_d.type,
                        "raw_value": raw_v,
                        "raw_hex": raw_h,
                        "value": pf.value if pf else None,
                        "units": p_d.units or (pf.units if pf else None),
                        "is_writable": p_d.is_writable,
                    })

            # Bitfield breakdown
            bitfield_flags = None
            if target_field and target_field.is_bitfield and pt_def and pt_def.symbols:
                raw_int = target_field.raw_value if isinstance(target_field.raw_value, int) else None
                bitfield_flags = []
                for s in sorted(pt_def.symbols, key=lambda x: x.value):
                    is_set = bool(raw_int & (1 << s.value)) if raw_int is not None else False
                    bitfield_flags.append({
                        "bit": s.value,
                        "mask": f"0x{(1 << s.value):04X}",
                        "name": s.name,
                        "label": s.label or s.name,
                        "desc": s.desc or "",
                        "is_set": is_set,
                    })

            # Enum symbols
            enum_symbols = None
            if target_field and target_field.is_enum and pt_def and pt_def.symbols:
                enum_symbols = []
                for s in sorted(pt_def.symbols, key=lambda x: x.value):
                    is_active = (s.name == target_field.value or s.value == target_field.raw_value)
                    enum_symbols.append({
                        "name": s.name,
                        "value": s.value,
                        "label": s.label or s.name,
                        "desc": s.desc or "",
                        "is_active": is_active,
                    })

            # Compound Link
            compound_link = None
            if c_view:
                compound_link = {
                    "is_compound": True,
                    "key": c_view.key,
                    "mapping_id": c_view.mapping_id,
                    "label": c_view.label,
                    "latest_value": c_view.latest_value,
                    "latest_source": c_view.latest_source,
                    "mqtt_value": c_view.mqtt_value,
                    "mqtt_key": c_view.mqtt_key,
                    "modbus_value": c_view.modbus_value,
                    "modbus_key": c_view.modbus_key,
                    "delta": c_view.delta,
                    "match_pct": c_view.match_pct,
                }
            elif target_field and target_field.compound_key:
                matched_cv = self.get_compound_view(target_field.compound_key.split(".")[-1])
                if matched_cv:
                    compound_link = {
                        "is_compound": False,
                        "key": matched_cv.key,
                        "mapping_id": matched_cv.mapping_id,
                        "label": matched_cv.label,
                        "latest_value": matched_cv.latest_value,
                        "latest_source": matched_cv.latest_source,
                        "mqtt_value": matched_cv.mqtt_value,
                        "mqtt_key": matched_cv.mqtt_key,
                        "modbus_value": matched_cv.modbus_value,
                        "modbus_key": matched_cv.modbus_key,
                        "delta": matched_cv.delta,
                        "match_pct": matched_cv.match_pct,
                    }

            sf_val_num = sf_info["value"] if (sf_info and isinstance(sf_info.get("value"), (int, float))) else None
            bounds_info = pt_def.get_bounds(sf_val_num) if pt_def else (target_field.get_bounds(sf_val_num) if target_field else (c_view.get_bounds() if c_view else None))

            return {
                "device": {
                    "serial_number": dev.serial_number,
                    "slave_id": dev.slave_id,
                    "model_name": dev.model_name,
                    "manufacturer": dev.manufacturer,
                    "version": dev.version,
                    "device_type": dev.device_type,
                },
                "field": target_field.to_dict(sf_value=sf_val_num) if target_field else c_view.to_dict(),
                "model": {
                    "model_id": model_def.model_id if model_def else (target_field.model_id if target_field else None),
                    "name": model_def.name if model_def else (target_field.model_name if target_field else None),
                    "label": model_def.label if model_def else (target_field.model_label if target_field else None),
                    "desc": model_def.desc if model_def else "",
                    "total_points": len(model_def.points) if model_def else 0,
                } if (model_def or (target_field and target_field.model_id)) else None,
                "point_def": pt_def.to_dict(sf_value=sf_val_num) if pt_def else None,
                "bounds": bounds_info,
                "scale_factor": sf_info,
                "scaled_points": scaled_points,
                "associated_registers": associated_registers,
                "bitfield_flags": bitfield_flags,
                "enum_symbols": enum_symbols,
                "compound_link": compound_link,
            }

    def to_dict(self) -> dict:
        """Full serializable dictionary of all devices and fields."""
        with self._lock:
            return {
                sn: {
                    **dev.to_dict(self.catalog),
                    "fields": dev.serialize_fields(),
                }
                for sn, dev in self.devices.items()
            }
