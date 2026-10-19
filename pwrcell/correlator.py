"""Telemetry Correlation and Modbus-to-MQTT Mapping Engine for Generac PWRcell (v3).

Provides:
1. Static mappings between internal MQTT push protobuf messages and SunSpec Modbus registers.
2. Runtime comparison engine computing live value deltas, percent matches, and status.
3. Heuristic matching scanner to discover new register relationships.
4. CLI monitor rendering synchronized side-by-side telemetry tables.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .mapping import MappingRegistry, ModbusCandidateDef, TelemetryMappingDef as ConfigMappingDef, apply_transform
from .state import FieldSource, StateField, StateStore

logger = logging.getLogger(__name__)


@dataclass
class ModbusCandidate:
    """A candidate Modbus register mapping."""
    field_key: str  # e.g. 'inverter.model_64208.CTPow'
    label: str
    confidence: str  # 'HIGH', 'PROBABLE', 'CANDIDATE'
    transform: Optional[Any] = None  # Callable or transform name string ('negate', etc.)
    transform_desc: Optional[str] = None
    notes: str = ""


@dataclass
class TelemetryMappingDef:
    """Definition of an MQTT push telemetry point and its corresponding Modbus candidate(s)."""
    mapping_id: str
    label: str
    mqtt_key: str  # State store key e.g. 'inverter.live.grid_power_w'
    mqtt_desc: str
    unit: str
    primary_candidate: ModbusCandidate
    alternative_candidates: List[ModbusCandidate] = field(default_factory=list)


def _load_correlator_mappings() -> List[TelemetryMappingDef]:
    """Build correlator TelemetryMappingDef list dynamically from MappingRegistry."""
    res = []
    reg = MappingRegistry.get_instance()
    for m in reg.get_all():
        cand_defs = m.get_candidate_defs()
        prim_def = cand_defs[0]
        prim_cand = ModbusCandidate(
            field_key=prim_def.field_key,
            label=prim_def.label,
            confidence=prim_def.confidence,
            transform=prim_def.transform,
            transform_desc=prim_def.transform_desc,
            notes=prim_def.notes,
        )
        alt_cands = [
            ModbusCandidate(
                field_key=alt.field_key,
                label=alt.label,
                confidence=alt.confidence,
                transform=alt.transform,
                transform_desc=alt.transform_desc,
                notes=alt.notes,
            )
            for alt in cand_defs[1:]
        ]
        res.append(
            TelemetryMappingDef(
                mapping_id=m.id,
                label=m.label,
                mqtt_key=m.mqtt_field,
                mqtt_desc=m.description,
                unit=m.unit,
                primary_candidate=prim_cand,
                alternative_candidates=alt_cands,
            )
        )
    return res


# Dynamic Mappings between MQTT push telemetry and SunSpec Modbus registers
KNOWN_TELEMETRY_MAPPINGS: List[TelemetryMappingDef] = _load_correlator_mappings()



@dataclass
class ComparisonResultRow:
    """Evaluated side-by-side comparison between MQTT and a candidate Modbus register."""
    mapping_id: str
    label: str
    unit: str
    mqtt_key: str
    mqtt_value: Any
    modbus_key: str
    modbus_label: str
    modbus_value: Any
    confidence: str
    status: str  # 'EXACT', 'CLOSE', 'DIVERGENT', 'MQTT_MISSING', 'MODBUS_MISSING'
    match_pct: Optional[float]
    delta: Optional[float]
    notes: str

    def to_dict(self) -> dict:
        return {
            "mapping_id": self.mapping_id,
            "label": self.label,
            "unit": self.unit,
            "mqtt_key": self.mqtt_key,
            "mqtt_value": self.mqtt_value,
            "modbus_key": self.modbus_key,
            "modbus_label": self.modbus_label,
            "modbus_value": self.modbus_value,
            "confidence": self.confidence,
            "status": self.status,
            "match_pct": round(self.match_pct, 1) if self.match_pct is not None else None,
            "delta": round(self.delta, 2) if self.delta is not None else None,
            "notes": self.notes,
        }


def evaluate_comparisons(
    state_store: StateStore,
    mappings: Optional[List[TelemetryMappingDef]] = None,
) -> List[ComparisonResultRow]:
    """Evaluate all known telemetry mappings against current live state in StateStore."""
    results: List[ComparisonResultRow] = []
    active_mappings = mappings if mappings is not None else _load_correlator_mappings()

    for mapping in active_mappings:
        # 1. Fetch MQTT Field
        mqtt_field = _find_field(state_store, mapping.mqtt_key)
        mqtt_val = mqtt_field.value if mqtt_field else None

        # 2. Evaluate Primary Candidate
        cand = mapping.primary_candidate
        mb_fields = _find_fields(state_store, cand.field_key)

        row = _build_comparison_row(
            mapping=mapping,
            candidate=cand,
            mqtt_val=mqtt_val,
            mb_fields=mb_fields,
        )
        results.append(row)

        # Also evaluate alternatives if primary is missing or divergent
        for alt in mapping.alternative_candidates:
            alt_mb_fields = _find_fields(state_store, alt.field_key)
            if alt_mb_fields and (not mb_fields or row.status in ("DIVERGENT", "MODBUS_MISSING")):
                alt_row = _build_comparison_row(
                    mapping=mapping,
                    candidate=alt,
                    mqtt_val=mqtt_val,
                    mb_fields=alt_mb_fields,
                )
                results.append(alt_row)

    return results


def _build_comparison_row(
    mapping: TelemetryMappingDef,
    candidate: ModbusCandidate,
    mqtt_val: Any,
    mb_field: Optional[StateField] = None,
    mb_fields: Optional[List[StateField]] = None,
) -> ComparisonResultRow:
    """Build a comparison row and compute delta and match percentage."""
    if mb_fields is None:
        mb_fields = [mb_field] if mb_field is not None else []
    elif mb_field is None and mb_fields:
        mb_field = mb_fields[0]

    should_sum = (
        candidate.transform in ("sum", "sum_all", "sum_devices")
        or mapping.mapping_id == "solar_power"
        or (candidate.field_key.startswith("pv_link.") and mapping.mqtt_key == "inverter.live.solar_power_w")
    )

    notes = candidate.notes
    modbus_label = candidate.label

    # Check if modbus field(s) exist and have values
    if should_sum:
        num_vals = [f.value for f in mb_fields if isinstance(f.value, (int, float))]
        has_mb_val = bool(num_vals)
    else:
        has_mb_val = (mb_field is not None and mb_field.value is not None)

    if mqtt_val is None:
        mb_val_display = None
        if has_mb_val:
            if should_sum:
                num_vals = [f.value for f in mb_fields if isinstance(f.value, (int, float))]
                mb_val_display = sum(num_vals)
            else:
                mb_val_display = mb_field.value
        return ComparisonResultRow(
            mapping_id=mapping.mapping_id,
            label=mapping.label,
            unit=mapping.unit,
            mqtt_key=mapping.mqtt_key,
            mqtt_value=None,
            modbus_key=candidate.field_key,
            modbus_label=modbus_label,
            modbus_value=mb_val_display,
            confidence=candidate.confidence,
            status="MQTT_MISSING",
            match_pct=None,
            delta=None,
            notes=notes,
        )

    if not has_mb_val:
        return ComparisonResultRow(
            mapping_id=mapping.mapping_id,
            label=mapping.label,
            unit=mapping.unit,
            mqtt_key=mapping.mqtt_key,
            mqtt_value=mqtt_val,
            modbus_key=candidate.field_key,
            modbus_label=modbus_label,
            modbus_value=None,
            confidence=candidate.confidence,
            status="MODBUS_MISSING",
            match_pct=None,
            delta=None,
            notes=notes,
        )

    if should_sum:
        num_vals = [f.value for f in mb_fields if isinstance(f.value, (int, float))]
        raw_mb_val = sum(num_vals)
        if len(mb_fields) > 1:
            dev_summary = ", ".join(f"{f.device_sn[-4:] if len(f.device_sn) >= 4 else f.device_sn}:{f.value}" for f in mb_fields if f.value is not None)
            notes = f"Sum across {len(mb_fields)} devices ({dev_summary})"
            modbus_label = f"{candidate.label} (∑ {len(mb_fields)})"
        if candidate.transform and candidate.transform not in ("sum", "sum_all", "sum_devices"):
            if callable(candidate.transform):
                mb_val = candidate.transform(raw_mb_val)
            else:
                mb_val = apply_transform(raw_mb_val, candidate.transform)
        else:
            mb_val = raw_mb_val
    else:
        raw_mb_val = mb_field.value
        if candidate.transform:
            if callable(candidate.transform):
                mb_val = candidate.transform(raw_mb_val)
            else:
                mb_val = apply_transform(raw_mb_val, candidate.transform)
        else:
            mb_val = raw_mb_val

    # For system_mode, normalize integer enum values to string names
    if mapping.mapping_id == "system_mode":
        if isinstance(mb_val, int):
            from .mqtt import SYSTEM_MODE_NAMES
            mb_val = SYSTEM_MODE_NAMES.get(mb_val, f"MODE_{mb_val}")

    # Comparison logic
    delta: Optional[float] = None
    match_pct: Optional[float] = None
    status = "DIVERGENT"

    if isinstance(mqtt_val, (int, float)) and isinstance(mb_val, (int, float)):
        delta = float(mb_val) - float(mqtt_val)
        abs_delta = abs(delta)
        denom = max(abs(float(mqtt_val)), abs(float(mb_val)), 1.0)
        pct_diff = (abs_delta / denom) * 100.0
        match_pct = max(0.0, min(100.0, 100.0 - pct_diff))

        if abs_delta < 0.05 or match_pct >= 99.5:
            status = "EXACT"
            if abs_delta < 0.05:
                match_pct = 100.0
        elif match_pct >= 95.0 or abs_delta < 2.0:
            status = "CLOSE"
        else:
            status = "DIVERGENT"
    else:
        # String / Enum comparison
        str_mqtt = str(mqtt_val).strip().upper()
        str_mb = str(mb_val).strip().upper()
        if str_mqtt == str_mb:
            status = "EXACT"
            match_pct = 100.0
            delta = 0.0
        else:
            status = "DIVERGENT"
            match_pct = 0.0

    return ComparisonResultRow(
        mapping_id=mapping.mapping_id,
        label=mapping.label,
        unit=mapping.unit,
        mqtt_key=mapping.mqtt_key,
        mqtt_value=mqtt_val,
        modbus_key=candidate.field_key,
        modbus_label=modbus_label,
        modbus_value=mb_val,
        confidence=candidate.confidence,
        status=status,
        match_pct=match_pct,
        delta=delta,
        notes=notes,
    )


def find_heuristic_matches(
    state_store: StateStore,
    target_value: float,
    tolerance_pct: float = 5.0,
    unit: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scan all Modbus registers in state_store for values closely matching target_value."""
    matches = []
    denom = max(abs(target_value), 1.0)

    # 1. Individual field matches
    for dev in state_store.devices.values():
        for f_key, field_obj in dev.fields.items():
            if field_obj.source == FieldSource.MQTT_PUSH:
                continue
            val = field_obj.value
            if not isinstance(val, (int, float)):
                continue

            delta = abs(val - target_value)
            pct = (delta / denom) * 100.0

            if pct <= tolerance_pct:
                matches.append({
                    "device": dev.model_name,
                    "field_key": f_key,
                    "label": field_obj.label,
                    "value": val,
                    "unit": field_obj.units,
                    "delta": round(delta, 2),
                    "match_pct": round(100.0 - pct, 1),
                })

    # 2. Aggregated sums across devices of same type (e.g. sum of all PV Links)
    by_key_vals: Dict[str, List[float]] = {}
    key_meta: Dict[str, tuple] = {}
    for dev in state_store.devices.values():
        for f_key, field_obj in dev.fields.items():
            if field_obj.source == FieldSource.MQTT_PUSH:
                continue
            val = field_obj.value
            if isinstance(val, (int, float)):
                by_key_vals.setdefault(f_key, []).append(float(val))
                key_meta[f_key] = (dev.device_type, field_obj.label, field_obj.units)

    for f_key, vals in by_key_vals.items():
        if len(vals) > 1:
            total = sum(vals)
            delta = abs(total - target_value)
            pct = (delta / denom) * 100.0
            if pct <= tolerance_pct:
                dev_type, label, u = key_meta[f_key]
                matches.append({
                    "device": f"All {dev_type}s (sum of {len(vals)})",
                    "field_key": f_key,
                    "label": f"{label} (Sum of {len(vals)} devices)",
                    "value": round(total, 1),
                    "unit": u,
                    "delta": round(delta, 2),
                    "match_pct": round(100.0 - pct, 1),
                })

    matches.sort(key=lambda m: m["delta"])
    return matches


def _find_fields(state_store: StateStore, key: str) -> List[StateField]:
    """Find all StateField instances across all devices matching key or suffix."""
    if hasattr(state_store, "find_fields"):
        return state_store.find_fields(key)

    matched: List[StateField] = []
    for dev in state_store.devices.values():
        if key in dev.fields:
            matched.append(dev.fields[key])

    if matched:
        return matched

    parts = key.split(".")
    if len(parts) >= 3:
        target_dev_type = parts[0]
        target_point = parts[-1]
        for dev in state_store.devices.values():
            if dev.device_type == target_dev_type:
                for f_key, f_obj in dev.fields.items():
                    if f_key.endswith(f".{target_point}") and f_obj.source != FieldSource.MQTT_PUSH:
                        matched.append(f_obj)
                        break
    return matched


def _find_field(state_store: StateStore, key: str) -> Optional[StateField]:
    """Find a StateField by its canonical key with fallback to model name/ID normalization."""
    fields = _find_fields(state_store, key)
    return fields[0] if fields else None


# ─────────────────────────────────────────────────────────────────────────────
# Terminal CLI Monitor
# ─────────────────────────────────────────────────────────────────────────────

def log_unrecognized_proto_fields(unrecognized: List[Dict[str, Any]]):
    """Log any unrecognized or unknown protobuf fields to python logger."""
    if not unrecognized:
        return
    logger.warning("=== Unrecognized & Unknown MQTT Protobuf Telemetry Detected (%d items) ===", len(unrecognized))
    for item in unrecognized:
        cat = item.get("category", "UNKNOWN")
        loc = item.get("location", "")
        f_name = item.get("field_name") or f"Field #{item.get('field_number')}"
        val = item.get("value", "")
        desc = item.get("description", "")
        logger.warning("  • [%s] %s -> %s: %s (%s)", cat, loc, f_name, val, desc)


def format_comparison_table(
    results: List[ComparisonResultRow],
    unrecognized_fields: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format comparison rows into a clean ANSI terminal table, including unrecognized proto data."""
    # ANSI color codes
    C_RESET = "\033[0m"
    C_BOLD = "\033[1m"
    C_GREEN = "\033[32m"
    C_YELLOW = "\033[33m"
    C_RED = "\033[31m"
    C_GRAY = "\033[90m"
    C_CYAN = "\033[36m"

    lines = []
    header = f"{C_BOLD}{'Metric / Concept':<26} {'MQTT Push':<16} {'Modbus Candidate Register':<34} {'Modbus Val':<14} {'Match':<8} {'Status'}{C_RESET}"
    sep = "─" * 110

    lines.append(header)
    lines.append(sep)

    for r in results:
        # Format MQTT value
        if r.mqtt_value is None:
            mqtt_str = f"{C_GRAY}--{C_RESET}"
        elif isinstance(r.mqtt_value, float):
            mqtt_str = f"{r.mqtt_value:.1f} {r.unit}"
        else:
            mqtt_str = f"{r.mqtt_value} {r.unit}".strip()

        # Format Modbus value
        if r.modbus_value is None:
            mb_str = f"{C_GRAY}--{C_RESET}"
        elif isinstance(r.modbus_value, float):
            mb_str = f"{r.modbus_value:.1f} {r.unit}"
        else:
            mb_str = f"{r.modbus_value} {r.unit}".strip()

        # Format Status & Match
        if r.status == "EXACT":
            st_color = C_GREEN
            st_text = "EXACT MATCH ✓"
            match_str = f"{r.match_pct:.0f}%" if r.match_pct is not None else "100%"
        elif r.status == "CLOSE":
            st_color = C_YELLOW
            st_text = "CLOSE (~)"
            match_str = f"{r.match_pct:.0f}%" if r.match_pct is not None else "--"
        elif r.status == "DIVERGENT":
            st_color = C_RED
            st_text = "DIVERGENT ✗"
            match_str = f"{r.match_pct:.0f}%" if r.match_pct is not None else "0%"
        elif r.status == "MODBUS_MISSING":
            st_color = C_GRAY
            st_text = "MODBUS NOT POLLED"
            match_str = "--"
        else:
            st_color = C_GRAY
            st_text = "MQTT WAITING"
            match_str = "--"

        modbus_display_key = r.modbus_key
        if len(modbus_display_key) > 33:
            modbus_display_key = "..." + modbus_display_key[-30:]

        line = (
            f"{r.label:<26} "
            f"{mqtt_str:<25} "
            f"{modbus_display_key:<34} "
            f"{mb_str:<23} "
            f"{match_str:<8} "
            f"{st_color}{st_text}{C_RESET}"
        )
        lines.append(line)

    if unrecognized_fields is not None:
        lines.append("")
        if unrecognized_fields:
            unrec_header = f"{C_BOLD}{C_YELLOW}── Unrecognized / Unmapped MQTT Protobuf Fields ({len(unrecognized_fields)} items) ──{C_RESET}"
            lines.append(unrec_header)
            for item in unrecognized_fields:
                cat = item.get("category", "UNKNOWN")
                loc = item.get("location", "")
                f_name = item.get("field_name") or f"Field #{item.get('field_number')}"
                val = item.get("value", "")
                desc = item.get("description", "")
                lines.append(f"  {C_YELLOW}•{C_RESET} [{cat}] {C_BOLD}{loc}{C_RESET} -> {f_name}: {C_CYAN}{val}{C_RESET}")
                if desc:
                    lines.append(f"    {C_GRAY}{desc}{C_RESET}")
        else:
            lines.append(f"{C_GREEN}✓ No unrecognized or unknown protobuf fields detected on MQTT bus.{C_RESET}")

    return "\n".join(lines)
