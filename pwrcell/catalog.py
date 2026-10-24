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

            return {
                "category": "numeric",
                "point_type": self.type,
                "raw_min": raw_min,
                "raw_max": raw_max,
                "scaled_min": scaled_min,
                "scaled_max": scaled_max,
                "min_value": scaled_min if scaled_min is not None else raw_min,
                "max_value": scaled_max if scaled_max is not None else raw_max,
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

            sym = self.symbols_by_value.get(int_val)
            if sym is not None:
                return sym.value, sym.name

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

        COMMON_ABBREVIATIONS: Dict[str, str] = {
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
            "A": "Total DC Current",
            "V": "Total DC Voltage",
            "W": "Total DC Power",
        }

        def _parse_points_list(points_list: list, start_offset: int) -> int:
            running_offset = start_offset
            for p_raw in points_list:
                pt_name = p_raw.get("name")
                if not pt_name:
                    continue

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
                pt_size = p_raw.get("size", 1)

                # Infer human-friendly label if missing or equal to identifier
                label = raw_label
                if not label or label == pt_name or label.startswith("Model "):
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

                pt_def = SunspecPointDef(
                    name=pt_name,
                    label=label,
                    desc=desc,
                    type=pt_type,
                    size=pt_size,
                    offset=running_offset,
                    units=p_raw.get("units"),
                    sf=p_raw.get("sf"),
                    access=p_raw.get("access", "R"),
                    mandatory=p_raw.get("mandatory") == "M",
                    static=p_raw.get("static") == "S",
                    symbols=symbols,
                    symbols_by_value=symbols_val,
                    symbols_by_name=symbols_name,
                )
                model_def.points[pt_name] = pt_def
                running_offset += pt_size
            return running_offset

        cur_offset = _parse_points_list(group.get("points", []), 0)
        for sub_grp in group.get("groups", []):
            cur_offset = _parse_points_list(sub_grp.get("points", []), cur_offset)

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
        if raw_units in ("%WHRtg", "%WH", "%Pct"):
            canonical_units = "%"
        elif raw_units == "Secs":
            canonical_units = "s"

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
            return HomeAssistantHint(
                platform="number",
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
                entity_category="diagnostic" if "status" in point.name.lower() or "err" in point.name.lower() else None,
                options=[s.name for s in sorted(point.symbols, key=lambda x: x.value)],
            )

        # 4. Bitfield diagnostic sensors
        if point.is_bitfield:
            return HomeAssistantHint(
                platform="sensor",
                entity_category="diagnostic",
            )

        # 5. Numeric measurement sensors
        device_class = None
        state_class = None
        icon = None

        if canonical_units in ("W", "kW"):
            device_class = "power"
            state_class = "measurement"
        elif canonical_units in ("Wh", "kWh"):
            device_class = "energy"
            state_class = "total_increasing"
        elif canonical_units in ("V",):
            device_class = "voltage"
            state_class = "measurement"
        elif canonical_units in ("A",):
            device_class = "current"
            state_class = "measurement"
        elif canonical_units in ("Hz",):
            device_class = "frequency"
            state_class = "measurement"
        elif canonical_units == "%":
            device_class = "battery" if "soc" in point.name.lower() or "soh" in point.name.lower() or "whrtg" in raw_units.lower() else None
            state_class = "measurement"
        elif canonical_units in ("C", "°C"):
            device_class = "temperature"
            state_class = "measurement"
        elif point.is_accumulator:
            state_class = "total_increasing"
        elif point.is_numeric and not point.is_scale_factor:
            state_class = "measurement"

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
