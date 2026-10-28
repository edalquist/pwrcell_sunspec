"""SunSpec Model Catalog and Metamodel Engine for Generac PWRcell.

This module parses SunSpec model definitions (including Generac custom 64xxx and 8xx models)
from JSON definitions or the bundled zip file, providing metadata (labels, descriptions,
units, types, enum symbols, and Home Assistant mapping hints) for any register.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile

logger = logging.getLogger(__name__)

# Named SunSpec & Generac vendor model ID constants
MODEL_COMMON = 1
MODEL_IP_SETTINGS = 16
MODEL_INVERTER_SPLIT_PHASE = 102
MODEL_NAMEPLATE = 120
MODEL_CONTROLS = 123
MODEL_VOLT_VAR = 126
MODEL_VOLT_WATT = 132
MODEL_SCHEDULE = 133
MODEL_STRING_COMBINER = 404
MODEL_BATTERY_BASE = 802
MODEL_LITHIUM_ION_STRING = 804
MODEL_REBUS_DIR = 64200
MODEL_REBUS_ARB = 64202
MODEL_RECONNECT = 64203
MODEL_EI_CONFIG = 64206
MODEL_REBUS_STATUS = 64207
MODEL_INVERTER_STATUS = 64208
MODEL_BATTERY_STATUS = 64209
MODEL_PVLINK_STATUS = 64251
MODEL_BATTERY_WARRANTY = 64252
MODEL_FLASH_READER = 64258
MODEL_TZ_CONFIG = 64260
MODEL_PVRSS_CONFIG = 64263
MODEL_PVRSS_TELEMETRY = 64264


# Canonical SunSpec unimplemented / null sentinel register values keyed by point type
SUNSPEC_SENTINELS_BY_TYPE: Dict[str, set[int]] = {
    "int16": {-0x8000, 0x8000},
    "sunssf": {-0x8000, 0x8000},
    "uint16": {0xFFFF},
    "acc16": {0xFFFF},
    "count": {0xFFFF},
    "enum16": {0xFFFF},
    "bitfield16": {0xFFFF},
    "int32": {-0x80000000, 0x80000000},
    "uint32": {0xFFFFFFFF},
    "acc32": {0xFFFFFFFF},
    "enum32": {0xFFFFFFFF},
    "bitfield32": {0xFFFFFFFF},
    "int64": {-0x8000000000000000, 0x8000000000000000},
    "uint64": {0xFFFFFFFFFFFFFFFF},
    "acc64": {0xFFFFFFFFFFFFFFFF},
}


def is_sunspec_sentinel(raw_value: Any, point_type: Optional[str] = None) -> bool:
    """Return True if raw_value is the SunSpec unimplemented sentinel for point_type."""
    if raw_value is None or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return False
    if isinstance(raw_value, float) and (
        not raw_value.is_integer() or raw_value != raw_value or abs(raw_value) == float("inf")
    ):
        return False
    int_val = int(raw_value)
    if point_type:
        pt = point_type.strip().lower()
        if pt in SUNSPEC_SENTINELS_BY_TYPE:
            return int_val in SUNSPEC_SENTINELS_BY_TYPE[pt]
    return int_val in {-0x8000, 0x8000, 0xFFFF, -0x80000000, 0x80000000, 0xFFFFFFFF}



def is_scale_factor_point(
    name: Optional[str] = None,
    point_type: Optional[str] = None,
    label: Optional[str] = None,
    explicit: bool = False,
) -> bool:
    """Return True if the point metadata indicates a SunSpec scale factor register."""
    if explicit or point_type == "sunssf":
        return True
    if name and (
        name.endswith(("_sf", "_SF"))
        or name.startswith(("sf_", "SF_", "sunssf_"))
    ):
        return True
    if label and "scale factor" in label.lower():
        return True
    return False


def get_suggested_precision(
    unit: Optional[str],
    device_class: Optional[str] = None,
    point_name: Optional[str] = None,
) -> Optional[int]:
    """Derive Home Assistant suggested display precision for numeric sensors."""
    u = (unit or "").strip()
    if u in ("W", "VA", "VAr", "VAR", "Wh", "Ws", "VAh", "varh"):
        return 0
    if u in ("kWh", "Hz", "kVAh", "kvarh"):
        return 2
    if u in ("V", "A", "%", "C", "°C", "kW"):
        return 1
    if device_class == "power":
        return 0
    if device_class == "energy":
        return 2 if "k" in u.lower() else 0
    if device_class in ("voltage", "current", "battery", "temperature"):
        return 1
    if device_class == "frequency":
        return 2
    return None


def normalize_ha_unit(unit: Optional[str]) -> Optional[str]:
    """Normalize SunSpec raw units into canonical Home Assistant units of measurement."""
    if not unit:
        return unit
    u = unit.strip()
    if u in ("%WHRtg", "%WH", "%Pct", "%SoC", "Pct"):
        return "%"
    if u in ("C", "Deg C", "degC", "deg C", "°C"):
        return "°C"
    if u == "Secs":
        return "s"
    return u


def is_diagnostic_point(name: Optional[str], model_id: Optional[int] = None, device_type: Optional[str] = None) -> bool:
    """Check if a point represents an internal engineering or diagnostic metric."""
    if not name:
        return False
    n_lower = name.lower()

    # On PV Links, string power (P), energy (E), and current (DCA) are primary operational metrics
    if device_type == "pv_link" and n_lower in ("p", "e", "dcw", "dcwh", "dca", "string_combiner_dca", "rebus_status_p", "rebus_status_e"):
        return False

    if any(k in n_lower for k in (
        "tmpcab", "tmpsnk", "tmptrns", "tmpot", "modtmp", "celltmp",
        "auxtmp", "thsin", "maxcellt", "mincellt", "dcv", "hz",
        "cellvmax", "cellvmin", "err", "fault", "warn", "status",
        "rebus_status", "rebus_exp", "px1", "px2", "whin", "derate"
    )):
        return True
    if model_id in (64207, 64208, 64209, 64252):
        if n_lower in ("t", "v", "i", "st"):
            return True
        if n_lower in ("p", "e") and device_type != "pv_link":
            return True
    if n_lower in ("t", "st", "i", "v"):
        return True
    if n_lower == "dca" and device_type != "pv_link":
        return True
    return False


def infer_ha_classes(
    units: Optional[str] = None,
    name: Optional[str] = None,
    platform: Optional[str] = "sensor",
) -> tuple[Optional[str], Optional[str]]:
    """Infer Home Assistant (device_class, state_class) from physical units and point name.

    Returns (None, None) for non-sensor platforms (e.g. select, binary_sensor) or text/status fields.
    """
    if platform and platform not in ("sensor", "number"):
        return None, None

    u = normalize_ha_unit(units) or ""
    u_lower = u.lower()
    n_lower = (name or "").lower()

    if u in ("Wh", "kWh") or u_lower in ("wh", "kwh") or n_lower.endswith("_wh") or "energy" in n_lower or n_lower.endswith("_e"):
        return "energy", "total_increasing"
    if u in ("VA", "kVA") or u_lower in ("va", "kva") or n_lower in ("va", "kva") or "apparent" in n_lower:
        return "apparent_power", "measurement"
    if u in ("var", "VAr", "VAR", "kvar", "kVAr", "kVAR") or u_lower in ("var", "kvar") or n_lower in ("var", "kvar") or "reactive" in n_lower:
        return "reactive_power", "measurement"
    if n_lower in ("pf", "pfa", "pfb", "pfc") or "power_factor" in n_lower or (u_lower in ("%", "pct") and n_lower.endswith("pf")):
        return "power_factor", "measurement"
    if u in ("W", "kW") or u_lower in ("w", "kw") or n_lower.endswith("_w") or "power" in n_lower or n_lower.endswith("_power") or n_lower.endswith("_p"):
        return "power", "measurement"
    if u in ("V", "mV", "kV") or u_lower in ("v", "mv", "kv") or n_lower.endswith("_v") or "voltage" in n_lower or n_lower.endswith("_dcv"):
        return "voltage", "measurement"
    if u in ("A", "mA") or u_lower in ("a", "ma") or n_lower.endswith("_a") or "current" in n_lower or n_lower.endswith("_dca") or "achamax" in n_lower or "adischamax" in n_lower:
        return "current", ("measurement" if platform != "number" else None)
    if u in ("Hz", "kHz") or u_lower in ("hz", "khz") or n_lower.endswith("_hz") or "frequency" in n_lower:
        return "frequency", "measurement"
    if (
        u in ("C", "°C", "F", "°F", "Deg C", "deg C", "degC")
        or u_lower in ("c", "°c", "f", "°f", "deg_c", "deg c", "degc")
        or n_lower.endswith(("_deg_c", "_c", "_temp", "_tmpsnk", "_tmpcab"))
        or n_lower in ("t", "tmp", "temp", "tmpcab", "tmpsnk", "tmptrns", "tmpot", "modtmpavg", "modtmpmax", "modtmpmin", "celltmpavg", "celltmpmax", "celltmpmin", "thsin", "maxcellt", "mincellt")
    ):
        return "temperature", "measurement"
    if not (is_scale_factor_point(name) or n_lower.endswith("_sf") or n_lower.startswith("sf_")):
        if u == "%" or u_lower in ("%", "pct", "percent") or any(k in n_lower for k in ("soc", "soh", "battery_soc", "state_of_charge")):
            dev_class = "battery" if any(k in n_lower for k in ("soc", "soh", "charge", "health", "battery")) else None
            return dev_class, ("measurement" if platform != "number" else None)
    if u in ("s", "sec", "seconds", "min", "minutes", "h", "hours"):
        return "duration", "measurement"

    return None, None




@dataclass(frozen=True)
class SunspecSymbol:
    """Represents a single symbol/option in an enum or bitfield."""
    name: str
    value: int
    label: Optional[str] = None
    desc: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "label": self.label,
            "desc": self.desc,
        }


@dataclass
class HomeAssistantHint:
    """Recommended Home Assistant entity configuration derived from SunSpec metadata."""
    platform: str  # 'sensor', 'binary_sensor', 'select', 'number', 'switch'
    device_class: Optional[str] = None  # 'power', 'energy', 'voltage', 'current', 'battery', etc.
    state_class: Optional[str] = None  # 'measurement', 'total_increasing', 'total', None
    unit_of_measurement: Optional[str] = None
    entity_category: Optional[str] = None  # 'config', 'diagnostic', None
    icon: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    options: Optional[List[str]] = None
    suggested_display_precision: Optional[int] = None


@dataclass
class SunspecPointDef:
    """Metamodel definition of a single register point in a SunSpec model."""
    name: str
    label: str
    desc: str
    type: str  # 'uint16', 'int16', 'enum16', 'bitfield16', 'sunssf', 'acc32', etc.
    size: int = 1
    offset: int = 0  # Register offset within model
    units: Optional[str] = None
    sf: Optional[str] = None  # Name of scale-factor point in same model
    access: str = "R"  # "R" or "RW"
    mandatory: bool = False
    static: bool = False
    symbols: List[SunspecSymbol] = field(default_factory=list)
    symbols_by_value: Dict[int, SunspecSymbol] = field(default_factory=dict)
    symbols_by_name: Dict[str, SunspecSymbol] = field(default_factory=dict)

    @property
    def is_scale_factor(self) -> bool:
        return is_scale_factor_point(
            name=self.name,
            point_type=self.type,
            label=self.label,
        )

    @property
    def is_pad(self) -> bool:
        return self.type == "pad" or self.name.startswith("Pad")

    @property
    def is_writable(self) -> bool:
        return self.access == "RW"

    @property
    def is_enum(self) -> bool:
        return self.type in ("enum16", "enum32")

    @property
    def is_bitfield(self) -> bool:
        return self.type in ("bitfield16", "bitfield32")

    @property
    def has_substate_encoding(self) -> bool:
        """Return True if this enum point uses 4-bit substate encoding (lower nibble)."""
        if not self.is_enum or not self.symbols:
            return False
        non_zero = [s.value for s in self.symbols if s.value != 0]
        return bool(non_zero and all(v % 16 == 0 for v in non_zero))

    def lookup_symbol(self, val: Any) -> Optional[SunspecSymbol]:
        """Lookup SunspecSymbol for enum point, supporting 4-bit sub-state masking if applicable."""
        if not self.is_enum or val is None:
            return None

        # Check string name lookup first
        if isinstance(val, str):
            if val in self.symbols_by_name:
                return self.symbols_by_name[val]
            val_upper = val.strip().upper()
            if val_upper in self.symbols_by_name:
                return self.symbols_by_name[val_upper]
            if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
                val = int(val)
            else:
                return None

        if not isinstance(val, int):
            return None

        # 1. Exact match
        sym = self.symbols_by_value.get(val)
        if sym is not None:
            return sym

        # 2. Check for 4-bit sub-state masking (lower nibble)
        if self.has_substate_encoding:
            base_val = val & ~0x000F
            sym = self.symbols_by_value.get(base_val)
            if sym is not None:
                return sym

        return None

    def get_substate(self, val: Any) -> Optional[int]:
        """Extract integer sub-state (lower 4 bits) if this point has sub-state encoding."""
        if not self.has_substate_encoding or val is None:
            return None
        if isinstance(val, str) and (val.isdigit() or (val.startswith("-") and val[1:].isdigit())):
            val = int(val)
        if isinstance(val, int):
            return val & 0x000F
        return None

    @property
    def symbols_by_bit(self) -> Dict[int, SunspecSymbol]:
        """For bitfield points, mapping of bit index to SunspecSymbol."""
        return self.symbols_by_value

    def decode_bitfield(self, raw_val: Any) -> List[str]:
        """Decode an integer bitmask into a list of active symbol names."""
        if not isinstance(raw_val, int):
            if isinstance(raw_val, str) and (raw_val.isdigit() or (raw_val.startswith("-") and raw_val[1:].isdigit())):
                raw_val = int(raw_val)
            else:
                return []
        active: List[str] = []
        for sym in sorted(self.symbols, key=lambda s: s.value):
            if (raw_val & (1 << sym.value)) != 0:
                active.append(sym.name)
        return active

    def decode_bitfield_symbols(self, raw_val: Any) -> List[SunspecSymbol]:
        """Decode an integer bitmask into a list of active SunspecSymbol objects."""
        if not isinstance(raw_val, int):
            if isinstance(raw_val, str) and (raw_val.isdigit() or (raw_val.startswith("-") and raw_val[1:].isdigit())):
                raw_val = int(raw_val)
            else:
                return []
        active: List[SunspecSymbol] = []
        for sym in sorted(self.symbols, key=lambda s: s.value):
            if (raw_val & (1 << sym.value)) != 0:
                active.append(sym)
        return active

    def decode_bitfield_dict(self, raw_val: Any) -> Dict[str, bool]:
        """Decode an integer bitmask into a dictionary of {symbol_name: is_set}."""
        if not isinstance(raw_val, int):
            if isinstance(raw_val, str) and (raw_val.isdigit() or (raw_val.startswith("-") and raw_val[1:].isdigit())):
                raw_val = int(raw_val)
            else:
                raw_val = 0
        return {
            sym.name: bool(raw_val & (1 << sym.value))
            for sym in sorted(self.symbols, key=lambda s: s.value)
        }

    def encode_bitfield(self, input_val: Any) -> int:
        """Encode bitfield input (int, symbol name string, list/set of symbol names/bit ints) into an integer bitmask."""
        if isinstance(input_val, int):
            return input_val
        if isinstance(input_val, str):
            input_val = input_val.strip()
            if input_val.isdigit() or (input_val.startswith("-") and input_val[1:].isdigit()):
                return int(input_val)
            import re
            parts = [p.strip() for p in re.split(r'[,|; \t\n]+', input_val) if p.strip()]
            input_val = parts

        if isinstance(input_val, (list, tuple, set)):
            mask = 0
            for item in input_val:
                if isinstance(item, int):
                    mask |= (1 << item)
                elif isinstance(item, str):
                    clean = item.strip()
                    if clean.isdigit():
                        mask |= (1 << int(clean))
                        continue
                    sym = self.symbols_by_name.get(clean.upper()) or self.symbols_by_name.get(clean)
                    if not sym:
                        valid_names = [s.name for s in self.symbols]
                        raise ValueError(f"Unknown flag '{clean}' for bitfield '{self.name}'. Valid flags: {valid_names}")
                    mask |= (1 << sym.value)
                elif hasattr(item, "value"):
                    mask |= (1 << int(item.value))
                else:
                    raise ValueError(f"Invalid flag item '{item}' for bitfield '{self.name}'")
            return mask

        raise ValueError(f"Cannot encode '{input_val}' to bitfield for point '{self.name}'")

    @property
    def is_accumulator(self) -> bool:
        return self.type in ("acc16", "acc32", "acc64")

    @property
    def is_numeric(self) -> bool:
        return self.type in (
            "int16", "int32", "int64",
            "uint16", "uint32", "uint64",
            "float32", "float64",
            "acc16", "acc32", "acc64",
        )

    def to_dict(self, sf_value: Optional[int] = None) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "desc": self.desc,
            "type": self.type,
            "size": self.size,
            "offset": self.offset,
            "units": self.units,
            "sf": self.sf,
            "access": self.access,
            "mandatory": self.mandatory,
            "static": self.static,
            "is_writable": self.is_writable,
            "is_enum": self.is_enum,
            "has_substate_encoding": self.has_substate_encoding,
            "is_bitfield": self.is_bitfield,
            "is_numeric": self.is_numeric,
            "is_scale_factor": self.is_scale_factor,
            "symbols": [s.to_dict() for s in self.symbols],
            "bounds": self.get_bounds(sf_value=sf_value),
        }

    def get_bounds(self, sf_value: Optional[int] = None) -> Dict[str, Any]:
        """Compute the SunSpec bounds restrictions for this point."""
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

        # 1. Enums
        if self.is_enum:
            symbols_list = [s.to_dict() for s in self.symbols]
            valid_vals = [s.value for s in self.symbols] if self.symbols else []
            valid_names = [s.name for s in self.symbols] if self.symbols else []
            min_v = min(valid_vals) if valid_vals else 0
            max_v = max(valid_vals) if valid_vals else (65535 if self.type == "enum16" else 4294967295)
            desc = (
                f"{len(self.symbols)} options: " + ", ".join(f"{s.name} ({s.value})" for s in self.symbols)
                if self.symbols else f"Enum values: {min_v} to {max_v}"
            )
            return {
                "category": "enum",
                "point_type": self.type,
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
            symbols_list = [s.to_dict() for s in self.symbols]
            hex_mask = f"0x{max_mask:04X}" if max_bits == 16 else f"0x{max_mask:08X}"
            desc = f"Bitmask 0x0000 to {hex_mask} ({max_bits} bits, {len(self.symbols)} flags)"
            return {
                "category": "bitfield",
                "point_type": self.type,
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
        if self.type in raw_bounds:
            raw_min, raw_max = raw_bounds[self.type]
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

            calc_min = scaled_min if scaled_min is not None else raw_min
            calc_max = scaled_max if scaled_max is not None else raw_max

            norm_u = normalize_ha_unit(self.units)
            pt_lower = self.name.lower()
            if norm_u == "%" or any(k in pt_lower for k in ("socmax", "socrsvmax", "socrsvmin", "socmin", "minrsvpct")):
                if calc_max is not None and calc_max > 100:
                    calc_max = 100 if isinstance(step, int) else 100.0
                if calc_min is not None and calc_min < 0:
                    calc_min = 0 if isinstance(step, int) else 0.0

            return {
                "category": "numeric",
                "point_type": self.type,
                "raw_min": raw_min,
                "raw_max": raw_max,
                "scaled_min": scaled_min,
                "scaled_max": scaled_max,
                "min_value": calc_min,
                "max_value": calc_max,
                "step": step,
                "units": self.units,
                "sf": self.sf,
                "sf_value": sf_value,
                "sentinel": sentinels.get(self.type),
                "description": desc,
            }

        # 4. Floats
        if self.type in ("float32", "float64"):
            return {
                "category": "float",
                "point_type": self.type,
                "raw_min": None,
                "raw_max": None,
                "min_value": None,
                "max_value": None,
                "step": "any",
                "units": self.units,
                "sf": None,
                "sf_value": None,
                "sentinel": None,
                "description": f"IEEE 754 {self.type} floating point" + (f" ({self.units})" if self.units else ""),
            }

        # 5. Strings
        if self.type == "string":
            max_len = self.size * 2
            return {
                "category": "string",
                "point_type": self.type,
                "max_length": max_len,
                "size_words": self.size,
                "units": None,
                "sf": None,
                "sf_value": None,
                "sentinel": None,
                "description": f"Max {max_len} characters ({self.size} registers)",
            }

        # 6. Fallback
        return {
            "category": "other",
            "point_type": self.type,
            "size_words": self.size,
            "units": self.units,
            "sf": self.sf,
            "sf_value": None,
            "sentinel": None,
            "description": f"Type: {self.type}",
        }

    def validate_and_convert(
        self,
        input_val: Any,
        ignore_access: bool = False,
        sf_value: Optional[int] = None,
    ) -> tuple[Any, Any]:
        """Validate input value against point descriptor and return (raw_register_val, state_display_val).
        
        Raises PermissionError if point is not writable and ignore_access is False.
        Raises ValueError if input value does not conform to the field descriptor.
        """
        if not self.is_writable and not ignore_access:
            raise PermissionError(f"Field '{self.name}' is read-only (access: {self.access})")

        if input_val is None:
            raise ValueError(f"Value for '{self.name}' cannot be None")

        # 1. Enum types (enum16, enum32)
        if self.is_enum:
            if not self.symbols:
                try:
                    int_val = int(input_val)
                    return int_val, int_val
                except (ValueError, TypeError):
                    raise ValueError(f"Invalid integer value '{input_val}' for enum '{self.name}'")

            # Check if input matches symbol name (case-insensitive)
            if isinstance(input_val, str) and not (input_val.isdigit() or (input_val.startswith("-") and input_val[1:].isdigit())):
                val_upper = input_val.strip().upper()
                sym = self.symbols_by_name.get(val_upper)
                if not sym:
                    for s in self.symbols:
                        if s.name.upper() == val_upper or (s.label and s.label.upper() == val_upper):
                            sym = s
                            break
                if sym:
                    return sym.value, sym.name
                valid_opts = [s.name for s in self.symbols]
                raise ValueError(
                    f"Invalid enum symbol '{input_val}' for '{self.name}'. Valid options: {valid_opts}"
                )

            # Check if input is integer / numeric
            try:
                int_val = int(input_val)
            except (ValueError, TypeError):
                valid_opts = [f"{s.name} ({s.value})" for s in self.symbols]
                raise ValueError(
                    f"Invalid value '{input_val}' for '{self.name}'. Expected enum symbol or integer in: {valid_opts}"
                )

            sym = self.lookup_symbol(int_val)
            if sym is not None:
                return int_val, sym.name

            valid_opts = [f"{s.name} ({s.value})" for s in self.symbols]
            raise ValueError(
                f"Invalid enum value {int_val} for '{self.name}'. Valid values: {valid_opts}"
            )

        # 2. Bitfield types (bitfield16, bitfield32)
        if self.is_bitfield:
            mask = self.encode_bitfield(input_val)
            max_mask = (1 << (self.size * 16)) - 1
            if not (0 <= mask <= max_mask):
                raise ValueError(
                    f"Bitmask {mask} out of range for point '{self.name}' ({self.type}). Must be 0..{max_mask}"
                )
            decoded_flags = self.decode_bitfield(mask)
            return (mask, decoded_flags)

        # 3. Integer numeric types (uint16, int16, uint32, int32, etc.)
        if self.type in ("uint16", "int16", "uint32", "int32", "uint64", "int64", "acc16", "acc32", "acc64"):
            try:
                num_val = float(input_val)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid numeric value '{input_val}' for point '{self.name}' ({self.type})")

            if sf_value is not None and -10 <= sf_value <= 10:
                int_val = int(round(num_val / (10.0 ** sf_value)))
                display_val = round(int_val * (10.0 ** sf_value), abs(sf_value)) if sf_value < 0 else int(round(int_val * (10.0 ** sf_value)))
            else:
                int_val = int(num_val)
                display_val = int_val

            bounds = {
                "uint16": (0, 65535),
                "int16": (-32768, 32767),
                "uint32": (0, 4294967295),
                "int32": (-2147483648, 2147483647),
                "acc16": (0, 65535),
                "acc32": (0, 4294967295),
            }
            if self.type in bounds:
                min_b, max_b = bounds[self.type]
                if not (min_b <= int_val <= max_b):
                    raise ValueError(
                        f"Value {input_val} (raw {int_val}) out of range for point '{self.name}' ({self.type}). Raw must be between {min_b} and {max_b}"
                    )
            return int_val, display_val

        # 3. Float numeric types (float32, float64)
        if self.type in ("float32", "float64"):
            try:
                flt_val = float(input_val)
                return flt_val, flt_val
            except (ValueError, TypeError):
                raise ValueError(f"Invalid float value '{input_val}' for point '{self.name}' ({self.type})")

        # 4. String types
        if self.type == "string":
            str_val = str(input_val)
            max_len = self.size * 2
            if len(str_val) > max_len:
                str_val = str_val[:max_len]
            return str_val, str_val

        return input_val, input_val

    def resolve_enum_value(self, input_val: Any) -> tuple[int, str]:
        """Validate and resolve an enum input (name string or integer) into (int_value, symbol_name)."""
        raw, val = self.validate_and_convert(input_val, ignore_access=True)
        return int(raw), str(val)


@dataclass
class SunspecModelDef:
    """Metamodel definition of a SunSpec model group."""
    model_id: int
    name: str
    label: str
    desc: str
    points: Dict[str, SunspecPointDef] = field(default_factory=dict)

    def get_associated_points(self, point_name: str) -> List[Dict[str, Any]]:
        """Identify associated registers (scale factors, shared SF siblings, phase siblings, counters)."""
        target = self.points.get(point_name)
        if not target:
            return []

        results: List[Dict[str, Any]] = []
        seen = {point_name}

        # 1. Scale factor register (if target is scaled by another point)
        if target.sf and target.sf in self.points and target.sf not in seen:
            sf_pt = self.points[target.sf]
            results.append({
                "name": sf_pt.name,
                "label": sf_pt.label,
                "relationship": "Scale Factor",
                "point_def": sf_pt,
            })
            seen.add(target.sf)

        # 2. If target IS a scale factor, include all points it scales
        if target.is_scale_factor:
            for p_name, p_def in self.points.items():
                if p_def.sf == target.name and p_name not in seen:
                    results.append({
                        "name": p_def.name,
                        "label": p_def.label,
                        "relationship": "Scaled by this register",
                        "point_def": p_def,
                    })
                    seen.add(p_name)

        # 3. Sibling registers that share the exact same scale factor
        if target.sf:
            for p_name, p_def in self.points.items():
                if p_def.sf == target.sf and p_name not in seen:
                    results.append({
                        "name": p_def.name,
                        "label": p_def.label,
                        "relationship": f"Shared Scale Factor ({target.sf})",
                        "point_def": p_def,
                    })
                    seen.add(p_name)

        # 4. Phase / vector siblings (e.g. AphA -> AphB, AphC; PhVphA -> PhVphB, PhVphC)
        phase_stems = ["Aph", "PPVph", "PhV", "Px", "PFph", "VArph", "VAph", "Wph"]
        for stem in phase_stems:
            if stem in point_name:
                for p_name, p_def in self.points.items():
                    if p_name != point_name and stem in p_name and p_name not in seen:
                        results.append({
                            "name": p_def.name,
                            "label": p_def.label,
                            "relationship": "Phase Sibling",
                            "point_def": p_def,
                        })
                        seen.add(p_name)

        # 5. Paired energy counters (WhIn <-> WhOut)
        if "WhIn" in point_name:
            out_name = point_name.replace("WhIn", "WhOut")
            if out_name in self.points and out_name not in seen:
                p_def = self.points[out_name]
                results.append({
                    "name": p_def.name,
                    "label": p_def.label,
                    "relationship": "Paired Energy Counter",
                    "point_def": p_def,
                })
                seen.add(out_name)
        elif "WhOut" in point_name:
            in_name = point_name.replace("WhOut", "WhIn")
            if in_name in self.points and in_name not in seen:
                p_def = self.points[in_name]
                results.append({
                    "name": p_def.name,
                    "label": p_def.label,
                    "relationship": "Paired Energy Counter",
                    "point_def": p_def,
                })
                seen.add(in_name)

        return results


DEVICE_TYPE_RULES: Dict[str, Dict[str, Any]] = {
    "rebus_beacon": {
        "label": "REbus Beacon",
        "model_ids": [64200],
        "keywords": ["beacon", "rebus dir"],
    },
    "inverter": {
        "label": "Inverter",
        "model_ids": [101, 102, 103, 64208, 64202, 64203],
        "keywords": ["inverter"],
    },
    "battery": {
        "label": "Battery",
        "model_ids": [802, 804, 64209, 64252],
        "keywords": ["battery"],
    },
    "pv_link": {
        "label": "PV Link",
        "model_ids": [401, 404, 64251, 64258, 64263, 64264],
        "keywords": ["pv link", "pv"],
    },
    "icm": {
        "label": "Inverter Control Module",
        "model_ids": [],
        "keywords": ["icm"],
    },
}


def classify_device_type(supported_models: Optional[List[int]] = None, model_name: str = "") -> str:
    """Classify a discovered PWRcell device by its SunSpec model IDs and model name."""
    models_set = set(supported_models or [])
    # 1. Match by model IDs
    for dev_type, info in DEVICE_TYPE_RULES.items():
        req_ids = set(info["model_ids"])
        if req_ids and (models_set & req_ids):
            return dev_type
    # 2. Match by model name keywords
    md_lower = (model_name or "").lower()
    for dev_type, info in DEVICE_TYPE_RULES.items():
        if any(kw in md_lower for kw in info["keywords"]):
            return dev_type
    return "unknown"


def get_device_type_label(device_type: str) -> str:
    """Get user-friendly display label for a device type."""
    return DEVICE_TYPE_RULES.get(device_type, {}).get("label", device_type.replace("_", " ").title())


_DEFAULT_POINT_ABBREVIATIONS: Dict[str, str] = {
    "CTPow": "Current Transformer Power",
    "SysMd": "System Operating Mode",
    "Px1": "Phase A (P1) Real Power",
    "Px2": "Phase B (P2) Real Power",
    "Px3": "Phase C (P3) Real Power",
    "WhIn": "Total Energy In",
    "WhOut": "Total Energy Out",
    "AHRtg": "Amp-Hour Capacity Rating",
    "WHRtg": "Watt-Hour Capacity Rating",
    "WChaRteMax": "Max Battery Charge Rate",
    "WDisChaRteMax": "Max Battery Discharge Rate",
    "ReConn_Tms": "Reconnect Time",
    "ReConnMinV": "Reconnect Min Voltage",
    "ReConnMaxV": "Reconnect Max Voltage",
    "ReConnMinHz": "Reconnect Min Frequency",
    "ReConnMaxHz": "Reconnect Max Frequency",
    "VWLatchTms": "Volt Latch Time",
    "FWLatchTms": "Frequency Latch Time",
    "Hz": "Line Frequency",
    "VA": "AC Apparent Power",
    "VAr": "AC Reactive Power",
    "VAR": "AC Reactive Power",
    "PF": "AC Power Factor",
    "DCA": "DC Current",
    "DCV": "DC Voltage",
    "DCW": "DC Power",
    "DCWh": "DC Accumulated Energy",
    "DCAMax": "Max DC Current Rating",
    "Tmp": "Temperature",
    "Evt": "Operating Events",
    "St": "Operating State",
    "Conn": "Connection Status",
    "A": "AC Output Current",
    "AphA": "Phase A Current",
    "AphB": "Phase B Current",
    "AphC": "Phase C Current",
    "PhVphA": "Phase A Voltage",
    "PhVphB": "Phase B Voltage",
    "PhVphC": "Phase C Voltage",
    "V": "AC Voltage",
    "W": "Active Power",
}


def get_point_abbreviations() -> Dict[str, str]:
    return _DEFAULT_POINT_ABBREVIATIONS


class ModelCatalog:
    """Catalog of all known SunSpec models loaded from local JSON or zip archives."""

    def __init__(self, models_dir: Optional[Path | str] = None, zip_path: Optional[Path | str] = None):
        self._models_by_id: Dict[int, SunspecModelDef] = {}
        self._models_by_name: Dict[str, SunspecModelDef] = {}
        self._load_catalog(models_dir, zip_path)

    @property
    def models(self) -> Dict[int, SunspecModelDef]:
        return self._models_by_id

    def get_model(self, model_id: int) -> Optional[SunspecModelDef]:
        return self._models_by_id.get(model_id)

    def get_model_by_name(self, name: str) -> Optional[SunspecModelDef]:
        return self._models_by_name.get(name)

    def get_point(self, model_id: int, point_name: str) -> Optional[SunspecPointDef]:
        model = self.get_model(model_id)
        if model:
            return model.points.get(point_name)
        return None

    def get_point_for_field(self, field_key: str) -> Optional[SunspecPointDef]:
        """Look up point definition by field key (e.g. 'rebus_beacon.REbus_dir.SysMd' or 'inverter.model_64208.SysMd')."""
        parts = field_key.split(".")
        if len(parts) >= 3:
            group_name = parts[1]
            point_name = parts[2]
            model = self.get_model_by_name(group_name)
            if not model and group_name.startswith("model_"):
                try:
                    model = self.get_model(int(group_name[6:]))
                except ValueError:
                    pass
            if model:
                pt = model.points.get(point_name)
                if pt:
                    return pt
        elif len(parts) == 2:
            point_name = parts[1]
        else:
            point_name = field_key

        # Fallback: search across all models
        for m in self._models_by_id.values():
            if point_name in m.points:
                return m.points[point_name]
        return None

    def _load_catalog(self, models_dir: Optional[Path | str], zip_path: Optional[Path | str]):
        # Priority 1: Specified models_dir
        # Priority 2: sunspec-models/json in repo
        # Priority 3: sunspec-models.zip
        repo_root = Path(__file__).resolve().parent.parent

        target_dir = Path(models_dir) if models_dir else (repo_root / "sunspec-models" / "json")
        if target_dir.exists() and target_dir.is_dir():
            self._load_from_dir(target_dir)
            if self._models_by_id:
                logger.info("Loaded %d models from %s", len(self._models_by_id), target_dir)
                return

        target_zip = Path(zip_path) if zip_path else (repo_root / "sunspec-models.zip")
        if target_zip.exists() and target_zip.is_file():
            self._load_from_zip(target_zip)
            logger.info("Loaded %d models from %s", len(self._models_by_id), target_zip)

    def _load_from_dir(self, directory: Path):
        for json_file in sorted(directory.glob("model_*.json"), key=lambda p: int(p.stem.split('_')[1]) if p.stem.split('_')[1].isdigit() else 0):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self._parse_model_json(raw)
            except Exception as e:
                logger.debug("Failed to parse %s: %s", json_file.name, e)

    def _load_from_zip(self, zip_path: Path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            items = [i for i in zf.namelist() if i.startswith("sunspec-models/json/model_") and i.endswith(".json")]
            for item in sorted(items):
                try:
                    with zf.open(item) as f:
                        raw = json.load(f)
                        self._parse_model_json(raw)
                except Exception as e:
                    logger.debug("Failed to parse zip item %s: %s", item, e)

    def _parse_model_json(self, raw: dict):
        model_id = raw.get("id")
        group = raw.get("group", {})
        if model_id is None:
            # Check ID point inside group
            for pt in group.get("points", []):
                if pt.get("name") == "ID" and "value" in pt:
                    model_id = pt["value"]
                    break

        if model_id is None:
            return

        model_name = group.get("name", f"model_{model_id}")
        model_label = group.get("label", model_name)
        model_desc = group.get("desc", "")

        model_def = SunspecModelDef(
            model_id=int(model_id),
            name=model_name,
            label=model_label,
            desc=model_desc,
        )

        COMMON_ABBREVIATIONS = get_point_abbreviations()

        def _parse_points_list(points_list: list, start_offset: int, group_prefix: str = "") -> int:
            running_offset = start_offset
            for p_raw in points_list:
                pt_name = p_raw.get("name")
                if not pt_name:
                    continue

                pt_size = p_raw.get("size", 1)
                # Skip counting the 2-register SunSpec model header (ID and L) in fixed-block offsets
                is_header_pt = not group_prefix and pt_name in ("ID", "L")
                pt_offset = 0 if is_header_pt else running_offset

                symbols: List[SunspecSymbol] = []
                symbols_val: Dict[int, SunspecSymbol] = {}
                symbols_name: Dict[str, SunspecSymbol] = {}

                for s_raw in p_raw.get("symbols", []):
                    sym = SunspecSymbol(
                        name=s_raw.get("name", ""),
                        value=int(s_raw.get("value", 0)),
                        label=s_raw.get("label"),
                        desc=s_raw.get("desc"),
                    )
                    symbols.append(sym)
                    symbols_val[sym.value] = sym
                    symbols_name[sym.name] = sym

                raw_label = p_raw.get("label")
                desc = p_raw.get("desc", "").strip()
                pt_type = p_raw.get("type", "uint16")

                # Infer human-friendly label if missing, raw unit, or unhelpful
                RAW_UNIT_LABELS = {
                    "Watts": "Active Power",
                    "Amps": "String Current" if (group_prefix == "string_combiner" or pt_name.startswith("DC")) else "AC Output Current",
                    "Volts": "AC Voltage",
                    "Amps PhaseA": "Phase A Current",
                    "Amps PhaseB": "Phase B Current",
                    "Amps PhaseC": "Phase C Current",
                    "Phase Voltage AN": "Phase A Voltage",
                    "Phase Voltage BN": "Phase B Voltage",
                    "Phase Voltage CN": "Phase C Voltage",
                    "REbus Voltage": "REbus Voltage",
                }
                label = (raw_label or "").strip()
                if label in RAW_UNIT_LABELS:
                    label = RAW_UNIT_LABELS[label]
                elif not label or label == pt_name or label.startswith("Model "):
                    if pt_name in COMMON_ABBREVIATIONS:
                        label = COMMON_ABBREVIATIONS[pt_name]
                    elif desc and len(desc) < 45 and not desc.lower().startswith(("an ", "the ", "this ", "miscellaneous ")):
                        clean_d = desc.rstrip(".")
                        if clean_d.lower().startswith("scale factor for "):
                            label = f"Scale Factor: {clean_d[17:].title()}"
                        elif clean_d.lower().endswith(" scale factor"):
                            label = f"Scale Factor: {clean_d[:-13].title()}"
                        else:
                            label = clean_d.title()
                    else:
                        label = pt_name
                label = label.strip()

                pt_def = SunspecPointDef(
                    name=pt_name,
                    label=label,
                    desc=desc,
                    type=pt_type,
                    size=pt_size,
                    offset=pt_offset,
                    units=p_raw.get("units"),
                    sf=p_raw.get("sf"),
                    access=p_raw.get("access", "R"),
                    mandatory=p_raw.get("mandatory") == "M",
                    static=p_raw.get("static") == "S",
                    symbols=symbols,
                    symbols_by_value=symbols_val,
                    symbols_by_name=symbols_name,
                )
                if group_prefix:
                    model_def.points[f"{group_prefix}.{pt_name}"] = pt_def
                    if pt_name not in model_def.points:
                        model_def.points[pt_name] = pt_def
                else:
                    model_def.points[pt_name] = pt_def

                if not is_header_pt:
                    running_offset += pt_size
            return running_offset

        cur_offset = _parse_points_list(group.get("points", []), 0)
        for sub_grp in group.get("groups", []):
            sub_name = sub_grp.get("name", "subgroup")
            cur_offset = _parse_points_list(sub_grp.get("points", []), cur_offset, group_prefix=sub_name)

        # Second pass: link scale factor points to the exact points they scale
        for pt_name, pt_def in model_def.points.items():
            if pt_def.is_scale_factor:
                scaled_targets = [
                    p.label for p in model_def.points.values()
                    if p.sf == pt_name and p.label and not p.label.startswith("Scale Factor")
                ]
                if scaled_targets:
                    pt_def.label = f"Scale Factor: {scaled_targets[0]} ({pt_name})"
                elif pt_def.label == pt_name:
                    clean_sf = pt_name[:-3] if pt_name.endswith(("_SF", "_sf")) else pt_name
                    pt_def.label = f"Scale Factor: {clean_sf}"

        self._models_by_id[int(model_id)] = model_def
        # Prefer vendor models (64000+) if names collide with draft/standard models
        existing = self._models_by_name.get(model_name)
        if existing is None or int(model_id) >= 64000:
            self._models_by_name[model_name] = model_def
        self._models_by_name[f"model_{model_id}"] = model_def
        self._models_by_name[str(model_id)] = model_def

    def derive_ha_metadata(
        self,
        point: SunspecPointDef,
        model_id: Optional[int] = None,
        sf_value: Optional[int] = None,
    ) -> HomeAssistantHint:
        """Derive Home Assistant entity platform, device_class, state_class, and units."""
        raw_units = point.units or ""
        canonical_units = raw_units

        # Clean unit notations
        canonical_units = normalize_ha_unit(point.units)

        # 1. Writable select entities (RW enum)
        if point.is_writable and point.is_enum:
            options = [s.name for s in sorted(point.symbols, key=lambda x: x.value)]
            return HomeAssistantHint(
                platform="select",
                entity_category="config",
                options=options,
            )

        # 2. Writable numeric entities (RW number)
        if point.is_writable and point.is_numeric and not point.is_scale_factor:
            bounds = point.get_bounds(sf_value=sf_value)
            dev_class, _ = infer_ha_classes(units=canonical_units, name=point.name, platform="number")
            return HomeAssistantHint(
                platform="number",
                device_class=dev_class,
                unit_of_measurement=canonical_units if canonical_units else None,
                entity_category="config",
                min_value=bounds.get("min_value"),
                max_value=bounds.get("max_value"),
                step=bounds.get("step") if isinstance(bounds.get("step"), (int, float)) else 1.0,
            )

        # 3. Read-only Enum sensors
        if point.is_enum:
            return HomeAssistantHint(
                platform="sensor",
                device_class="enum",
                entity_category="diagnostic" if is_diagnostic_point(point.name, model_id) else None,
                options=[s.name for s in sorted(point.symbols, key=lambda x: x.value)],
            )

        # 4. Bitfield diagnostic sensors
        if point.is_bitfield:
            return HomeAssistantHint(
                platform="sensor",
                entity_category="diagnostic",
            )

        # 5. Numeric measurement sensors
        device_class, state_class = infer_ha_classes(units=canonical_units, name=point.name, platform="sensor")
        if not state_class and point.is_accumulator:
            state_class = "total_increasing"
        elif not state_class and point.is_numeric and not point.is_scale_factor:
            state_class = "measurement"
        icon = None

        # Determine suggested display precision
        precision = get_suggested_precision(
            canonical_units,
            device_class=device_class,
            point_name=point.name,
        )

        return HomeAssistantHint(
            platform="sensor",
            device_class=device_class,
            state_class=state_class,
            unit_of_measurement=canonical_units if canonical_units else None,
            entity_category="diagnostic" if is_diagnostic_point(point.name, model_id) else None,
            icon=icon,
            suggested_display_precision=precision,
        )


# Global singleton instance for easy import
_GLOBAL_CATALOG: Optional[ModelCatalog] = None

def get_catalog() -> ModelCatalog:
    global _GLOBAL_CATALOG
    if _GLOBAL_CATALOG is None:
        _GLOBAL_CATALOG = ModelCatalog()
    return _GLOBAL_CATALOG
