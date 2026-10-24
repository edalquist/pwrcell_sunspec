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
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .mapping import MappingRegistry, ModbusCandidateDef, TelemetryMappingDef as ConfigMappingDef, apply_transform
from .optimizer import group_device_fields, clean_unit
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
    """Evaluated side-by-side comparison between MQTT and Modbus registers, or across all grouped registers."""
    mapping_id: str
    label: str
    unit: str
    mqtt_key: str
    mqtt_value: Any
    modbus_key: str
    modbus_label: str
    modbus_value: Any
    confidence: str
    status: str  # 'EXACT', 'CLOSE', 'DIVERGENT', 'UNIT_MISMATCH', 'POLARITY_MISMATCH', 'SCALE_MISMATCH', 'MQTT_MISSING', 'MODBUS_MISSING', 'SINGLE_SOURCE', 'PARTIALLY_POLLED', 'NO_DATA'
    match_pct: Optional[float]
    delta: Optional[float]
    notes: str
    # Multi-register grouped concept fields:
    id: str = ""
    concept_key: str = ""
    device_sn: str = ""
    device_type: str = ""
    device_name: str = ""
    status_label: str = ""
    is_discrepant: bool = False
    is_custom_override: bool = False
    is_scale_factor: bool = False
    discrepancy_reason: str = ""
    source_count: int = 0
    polled_count: int = 0
    sources: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id or self.mapping_id,
            "mapping_id": self.mapping_id,
            "concept_key": self.concept_key or self.mapping_id,
            "label": self.label,
            "unit": self.unit,
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "device_name": self.device_name,
            "mqtt_key": self.mqtt_key,
            "mqtt_value": self.mqtt_value,
            "modbus_key": self.modbus_key,
            "modbus_label": self.modbus_label,
            "modbus_value": self.modbus_value,
            "confidence": self.confidence,
            "status": self.status,
            "status_label": self.status_label or self.status,
            "is_discrepant": self.is_discrepant,
            "is_custom_override": self.is_custom_override,
            "is_scale_factor": self.is_scale_factor,
            "match_pct": round(self.match_pct, 1) if self.match_pct is not None else None,
            "delta": round(self.delta, 2) if self.delta is not None else None,
            "notes": self.notes,
            "discrepancy_reason": self.discrepancy_reason or self.notes,
            "source_count": self.source_count or len(self.sources),
            "polled_count": self.polled_count,
            "sources": self.sources,
        }


def evaluate_comparisons(
    state_store: StateStore,
    mappings: Optional[List[TelemetryMappingDef]] = None,
) -> List[ComparisonResultRow]:
    """Evaluate all grouped registers across all devices and telemetry mappings against current live state."""
    results: List[ComparisonResultRow] = []

    # 1. Global / Cross-Device Telemetry Mappings (MQTT Push vs Modbus Registers)
    active_mappings = mappings if mappings is not None else _load_correlator_mappings()
    telemetry_ids = {m.mapping_id for m in active_mappings}

    for mapping in active_mappings:
        mqtt_field = _find_field(state_store, mapping.mqtt_key)
        mqtt_val = mqtt_field.value if mqtt_field else None
        cand = mapping.primary_candidate
        mb_fields = _find_fields(state_store, cand.field_key)

        row = _build_comparison_row(
            mapping=mapping,
            candidate=cand,
            mqtt_val=mqtt_val,
            mb_fields=mb_fields,
            state_store=state_store,
        )
        results.append(row)

        for alt in mapping.alternative_candidates:
            alt_mb_fields = _find_fields(state_store, alt.field_key)
            if alt_mb_fields and (not mb_fields or row.status in ("DIVERGENT", "MODBUS_MISSING")):
                alt_row = _build_comparison_row(
                    mapping=mapping,
                    candidate=alt,
                    mqtt_val=mqtt_val,
                    mb_fields=alt_mb_fields,
                    state_store=state_store,
                )
                results.append(alt_row)

    # 2. Evaluate all Unified Field Groups across all registered devices
    if state_store.devices:
        for dev in state_store.devices.values():
            groups = group_device_fields(dev)
            for g in groups:
                # Exclude raw scale factor registers from telemetry comparison & merging UI
                if getattr(g, "is_scale_factor", False):
                    continue

                # If this concept is already a top-level telemetry mapping, give the device-level
                # row a qualified mapping_id so it doesn't overwrite the global mapping in legacy maps
                is_telemetry = g.concept_key in telemetry_ids
                mapping_id = f"{dev.serial_number}_{g.concept_key}" if is_telemetry else g.concept_key

                row = _build_group_comparison_row(dev, g, mapping_id=mapping_id)
                results.append(row)

    # Sort results with discrepancies first, then multi-source, then matching
    status_priority = {
        "DIVERGENT": 1,
        "UNIT_MISMATCH": 1,
        "POLARITY_MISMATCH": 1,
        "SCALE_MISMATCH": 1,
        "CLOSE": 2,
        "EXACT": 3,
        "PARTIALLY_POLLED": 4,
        "SINGLE_SOURCE": 5,
        "NO_DATA": 6,
    }
    results.sort(key=lambda r: (
        status_priority.get(r.status, 99),
        0 if r.is_discrepant else 1,
        -(r.delta if r.delta is not None else -1),
        (r.match_pct if r.match_pct is not None else 999),
        r.device_type,
        r.label.lower(),
    ))

    return results


def _build_group_comparison_row(dev, g, mapping_id: Optional[str] = None) -> ComparisonResultRow:
    """Build a rich ComparisonResultRow evaluating all grouped sources in a UnifiedFieldGroup."""
    sources_dicts: List[Dict[str, Any]] = []
    polled_sources: List[Dict[str, Any]] = []

    for s in g.sources:
        s_dict = {
            "source_type": s.source_type,
            "source_id": s.source_id,
            "field_key": s.field_key,
            "name": s.name,
            "label": s.label,
            "model_id": s.model_id,
            "model_name": s.model_name,
            "value": s.value,
            "raw_value": s.raw_value,
            "units": s.units,
            "transform": s.transform,
            "is_optimal": s.is_optimal,
            "is_pinned": s.is_pinned,
            "is_custom_override": getattr(s, "is_custom_override", False),
            "is_divergent": False,
        }
        sources_dicts.append(s_dict)
        if s.value is not None:
            polled_sources.append(s_dict)

    # Unit mismatch check across non-empty clean units
    clean_units_map: Dict[str, str] = {}
    for s in polled_sources:
        u = s.get("units")
        if u and str(u).strip():
            cu = clean_unit(u)
            if cu and cu not in clean_units_map:
                clean_units_map[cu] = str(u).strip()

    unit_mismatch = len(clean_units_map) > 1

    # Check numeric agreement
    all_numeric = bool(polled_sources) and all(
        isinstance(s["value"], (int, float)) and not isinstance(s["value"], bool)
        for s in polled_sources
    )

    delta: Optional[float] = None
    match_pct: Optional[float] = None
    is_discrepant = False

    if len(polled_sources) >= 2:
        if unit_mismatch:
            status = "UNIT_MISMATCH"
            status_label = "Unit Mismatch ⚠️"
            is_discrepant = True
            match_pct = 0.0
            discrepancy_reason = f"Conflicting units across sources: {', '.join(sorted(clean_units_map.values()))}"
        elif all_numeric:
            vals = [float(s["value"]) for s in polled_sources]
            min_val = min(vals)
            max_val = max(vals)
            delta = max_val - min_val
            denom = max(max(abs(v) for v in vals), 1.0)
            pct_diff = (delta / denom) * 100.0
            match_pct = max(0.0, min(100.0, 100.0 - pct_diff))
            mean_val = sum(vals) / len(vals)

            # Check if this is near-zero noise (e.g. idle power standby: -1W to +1W)
            is_near_zero = (denom <= 5.0 and delta <= 5.0)

            # Check close tolerance (within 5%, or low-power sensor noise <= 5W with <= 15% diff, or near zero)
            is_close = is_near_zero or (pct_diff <= 5.0) or (delta <= 5.0 and pct_diff <= 15.0)

            # Mark outlier/divergent sources
            if delta > 0.5 and pct_diff > 5.0 and not is_close:
                for s in polled_sources:
                    if abs(float(s["value"]) - mean_val) > max(0.05 * denom, 0.5):
                        s["is_divergent"] = True

            if min_val < -0.5 and max_val > 0.5 and not is_near_zero:
                status = "POLARITY_MISMATCH"
                status_label = "Polarity Divergence ✗"
                is_discrepant = True
                discrepancy_reason = f"Opposite polarity: min={min_val:.1f}, max={max_val:.1f} (possible missing/inverted transform)"
            elif not is_near_zero and abs(min_val) > 0.01 and 9.0 <= abs(max_val / min_val) <= 1100.0 and delta > 1.0:
                ratio = abs(max_val / min_val)
                status = "SCALE_MISMATCH"
                status_label = "Scale Mismatch ⚠️"
                is_discrepant = True
                discrepancy_reason = f"Values differ by scale factor of ~{round(ratio):.0f}x ({min_val:.1f} vs {max_val:.1f})"
            elif delta <= 0.05:
                status = "EXACT"
                status_label = "Exact Match ✓"
                is_discrepant = False
                match_pct = 100.0
                delta = 0.0
                discrepancy_reason = "All sources agree exactly"
            elif is_close or pct_diff <= 5.0:
                status = "CLOSE"
                status_label = "Close (~)"
                is_discrepant = False
                discrepancy_reason = f"Values agree within {pct_diff:.1f}% (Δ {delta:.2f})"
            else:
                status = "DIVERGENT"
                status_label = "Divergent ✗"
                is_discrepant = True
                discrepancy_reason = f"Values differ by {delta:.2f} {g.units or ''} ({pct_diff:.1f}% difference)"
        else:
            str_vals = [str(s["value"]).strip().upper() for s in polled_sources]
            raw_vals = [s.get("raw_value") for s in polled_sources if s.get("raw_value") is not None]
            has_raw = len(raw_vals) == len(polled_sources)

            def _hashable_val(v: Any) -> Any:
                if isinstance(v, list):
                    return tuple(_hashable_val(x) for x in v)
                if isinstance(v, dict):
                    return tuple(sorted((k, _hashable_val(val)) for k, val in v.items()))
                return v

            all_raw_same = has_raw and len(set(_hashable_val(r) for r in raw_vals)) == 1

            if len(set(str_vals)) == 1 or all_raw_same:
                status = "EXACT"
                status_label = "Exact Match ✓"
                is_discrepant = False
                match_pct = 100.0
                delta = 0.0
                discrepancy_reason = (
                    "All state / enum values agree"
                    if len(set(str_vals)) == 1
                    else f"All raw enum values agree ({raw_vals[0]}) across naming variations"
                )
            else:
                status = "DIVERGENT"
                status_label = "Divergent ✗"
                is_discrepant = True
                match_pct = 0.0
                delta = None
                discrepancy_reason = f"Conflicting states: {', '.join(sorted(set(str_vals)))}"
                c = Counter(str_vals)
                common_val, _ = c.most_common(1)[0]
                for s in polled_sources:
                    if str(s["value"]).strip().upper() != common_val:
                        s["is_divergent"] = True
    elif len(polled_sources) == 1:
        if len(sources_dicts) == 1:
            status = "SINGLE_SOURCE"
            status_label = "Single Source"
            is_discrepant = False
            match_pct = 100.0
            delta = 0.0
            discrepancy_reason = "Only one source available in this group"
        else:
            status = "PARTIALLY_POLLED"
            status_label = "Partially Polled"
            is_discrepant = False
            match_pct = None
            delta = None
            discrepancy_reason = f"1 of {len(sources_dicts)} sources has data; others unpolled"
    else:
        status = "NO_DATA"
        status_label = "No Data"
        is_discrepant = False
        match_pct = None
        delta = None
        discrepancy_reason = "No polled values for any source"

    mqtt_src = next((s for s in sources_dicts if s["source_type"] == "MQTT"), None)
    mb_src = next((s for s in sources_dicts if s["source_type"] == "SUNSPEC"), None)

    dev_label = f"{dev.model_name or dev.device_type} ({dev.serial_number[-4:] if len(dev.serial_number) >= 4 else dev.serial_number})"

    return ComparisonResultRow(
        id=f"{dev.serial_number}:{g.concept_key}",
        mapping_id=mapping_id or g.concept_key,
        concept_key=g.concept_key,
        label=g.label,
        unit=g.units or "",
        device_sn=dev.serial_number,
        device_type=dev.device_type,
        device_name=dev_label,
        mqtt_key=mqtt_src["field_key"] if mqtt_src else "",
        mqtt_value=mqtt_src["value"] if mqtt_src else None,
        modbus_key=mb_src["field_key"] if mb_src else "",
        modbus_label=mb_src["label"] if mb_src else "",
        modbus_value=mb_src["value"] if mb_src else None,
        confidence="HIGH" if status in ("EXACT", "CLOSE") else "CANDIDATE",
        status=status,
        status_label=status_label,
        is_discrepant=is_discrepant,
        is_custom_override=getattr(g, "is_custom_override", False),
        is_scale_factor=getattr(g, "is_scale_factor", False),
        match_pct=match_pct,
        delta=delta,
        notes=discrepancy_reason,
        discrepancy_reason=discrepancy_reason,
        source_count=len(sources_dicts),
        polled_count=len(polled_sources),
        sources=sources_dicts,
    )


def _build_comparison_row(
    mapping: TelemetryMappingDef,
    candidate: ModbusCandidate,
    mqtt_val: Any,
    mb_field: Optional[StateField] = None,
    mb_fields: Optional[List[StateField]] = None,
    state_store: Optional[StateStore] = None,
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

    dev_type = mapping.mqtt_key.split(".")[0] if "." in mapping.mqtt_key else "system"

    if mqtt_val is None:
        mb_val_display = None
        if has_mb_val:
            if should_sum:
                num_vals = [f.value for f in mb_fields if isinstance(f.value, (int, float))]
                mb_val_display = sum(num_vals)
            else:
                mb_val_display = mb_field.value
        return ComparisonResultRow(
            id=f"telemetry:{mapping.mapping_id}",
            mapping_id=mapping.mapping_id,
            concept_key=mapping.mapping_id,
            label=mapping.label,
            unit=mapping.unit,
            device_sn="",
            device_type=dev_type,
            device_name=f"{dev_type.capitalize()} Telemetry",
            mqtt_key=mapping.mqtt_key,
            mqtt_value=None,
            modbus_key=candidate.field_key,
            modbus_label=modbus_label,
            modbus_value=mb_val_display,
            confidence=candidate.confidence,
            status="MQTT_MISSING",
            status_label="MQTT Waiting",
            is_discrepant=False,
            match_pct=None,
            delta=None,
            notes=notes,
            discrepancy_reason="Waiting for MQTT push telemetry",
            source_count=1 if has_mb_val else 0,
            polled_count=1 if has_mb_val else 0,
            sources=[],
        )

    if not has_mb_val:
        return ComparisonResultRow(
            id=f"telemetry:{mapping.mapping_id}",
            mapping_id=mapping.mapping_id,
            concept_key=mapping.mapping_id,
            label=mapping.label,
            unit=mapping.unit,
            device_sn="",
            device_type=dev_type,
            device_name=f"{dev_type.capitalize()} Telemetry",
            mqtt_key=mapping.mqtt_key,
            mqtt_value=mqtt_val,
            modbus_key=candidate.field_key,
            modbus_label=modbus_label,
            modbus_value=None,
            confidence=candidate.confidence,
            status="MODBUS_MISSING",
            status_label="Modbus Not Polled",
            is_discrepant=False,
            match_pct=None,
            delta=None,
            notes=notes,
            discrepancy_reason="Modbus register not polled yet",
            source_count=1,
            polled_count=1,
            sources=[
                {
                    "source_type": "MQTT",
                    "source_id": "MQTT",
                    "field_key": mapping.mqtt_key,
                    "name": mapping.mqtt_key.split(".")[-1],
                    "label": f"{mapping.label} (Push)",
                    "model_id": None,
                    "model_name": None,
                    "value": mqtt_val,
                    "raw_value": mqtt_val,
                    "units": mapping.unit,
                    "transform": None,
                    "is_optimal": True,
                    "is_pinned": False,
                    "is_divergent": False,
                }
            ],
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

    # For system_mode, normalize integer enum values to string names using the SunSpec SysMd table
    if mapping.mapping_id == "system_mode":
        if isinstance(mb_val, int):
            from .controls import SUNSPEC_SYS_MD_NAMES
            mb_val = SUNSPEC_SYS_MD_NAMES.get(mb_val, f"MODE_{mb_val}")

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

    is_discrepant = status == "DIVERGENT"
    discrepancy_reason = notes or ("All sources agree exactly" if status == "EXACT" else f"Values differ by {delta} {mapping.unit}")

    # Construct rich sources list
    sources = [
        {
            "source_type": "MQTT",
            "source_id": "MQTT",
            "field_key": mapping.mqtt_key,
            "name": mapping.mqtt_key.split(".")[-1],
            "label": f"{mapping.label} (Push)",
            "model_id": None,
            "model_name": None,
            "value": mqtt_val,
            "raw_value": mqtt_val,
            "units": mapping.unit,
            "transform": None,
            "is_optimal": True,
            "is_pinned": False,
            "is_divergent": is_discrepant,
        },
        {
            "source_type": "SUNSPEC",
            "source_id": candidate.field_key.split(".")[-2].replace("model_", "M") if "." in candidate.field_key else "SUNSPEC",
            "field_key": candidate.field_key,
            "name": candidate.field_key.split(".")[-1],
            "label": modbus_label,
            "model_id": None,
            "model_name": None,
            "value": mb_val,
            "raw_value": raw_mb_val,
            "units": mapping.unit,
            "transform": str(candidate.transform) if candidate.transform else None,
            "is_optimal": False,
            "is_pinned": False,
            "is_divergent": is_discrepant,
        }
    ]

    return ComparisonResultRow(
        id=f"telemetry:{mapping.mapping_id}",
        mapping_id=mapping.mapping_id,
        concept_key=mapping.mapping_id,
        label=mapping.label,
        unit=mapping.unit,
        device_sn="",
        device_type=dev_type,
        device_name=f"{dev_type.capitalize()} Telemetry",
        mqtt_key=mapping.mqtt_key,
        mqtt_value=mqtt_val,
        modbus_key=candidate.field_key,
        modbus_label=modbus_label,
        modbus_value=mb_val,
        confidence=candidate.confidence,
        status=status,
        status_label="Exact Match ✓" if status == "EXACT" else ("Close (~)" if status == "CLOSE" else "Divergent ✗"),
        is_discrepant=is_discrepant,
        match_pct=match_pct,
        delta=delta,
        notes=notes,
        discrepancy_reason=discrepancy_reason,
        source_count=len(sources),
        polled_count=len(sources),
        sources=sources,
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

    # Calculate summary metrics
    discrepant_count = sum(1 for r in results if r.is_discrepant or r.status in ("DIVERGENT", "UNIT_MISMATCH", "POLARITY_MISMATCH", "SCALE_MISMATCH"))
    exact_count = sum(1 for r in results if r.status == "EXACT")
    multi_count = sum(1 for r in results if r.source_count > 1 or len(r.sources) > 1)

    lines.append(f"{C_BOLD}=== PWRcell Grouped Registers & Telemetry Comparison ==={C_RESET}")
    lines.append(f"Total: {len(results)} groups | Multi-source: {multi_count} | {C_RED if discrepant_count > 0 else C_GREEN}Discrepancies: {discrepant_count}{C_RESET} | Exact: {exact_count}")
    lines.append("─" * 110)

    for r in results:
        # Status styling
        if r.status == "EXACT":
            st_color = C_GREEN
            st_text = "EXACT MATCH ✓"
            match_str = f"{r.match_pct:.0f}%" if r.match_pct is not None else "100%"
        elif r.status == "CLOSE":
            st_color = C_YELLOW
            st_text = "CLOSE (~)"
            match_str = f"{r.match_pct:.0f}%" if r.match_pct is not None else "--"
        elif r.status in ("DIVERGENT", "UNIT_MISMATCH", "POLARITY_MISMATCH", "SCALE_MISMATCH"):
            st_color = C_RED
            st_text = f"{r.status} ✗"
            match_str = f"{r.match_pct:.0f}%" if r.match_pct is not None else "0%"
        elif r.status == "MODBUS_MISSING":
            st_color = C_GRAY
            st_text = "MODBUS NOT POLLED"
            match_str = "--"
        elif r.status == "SINGLE_SOURCE":
            st_color = C_GRAY
            st_text = "SINGLE SOURCE"
            match_str = "--"
        elif r.status == "PARTIALLY_POLLED":
            st_color = C_CYAN
            st_text = "PARTIALLY POLLED"
            match_str = "--"
        else:
            st_color = C_GRAY
            st_text = "WAITING / NO DATA"
            match_str = "--"

        # If rich multi-source sources exist
        if r.sources and len(r.sources) > 1:
            dev_prefix = f"[{r.device_name}] " if r.device_name else ""
            lines.append(
                f"{st_color}{st_text:<18}{C_RESET} {C_BOLD}{dev_prefix}{r.label}{C_RESET} "
                f"({r.concept_key}) [{r.unit or ''}]"
            )
            for s in r.sources:
                s_id = s.get("source_id", "SRC")
                s_key = s.get("field_key", "")
                val = s.get("value")
                val_str = f"{val} {s.get('units') or ''}".strip() if val is not None else f"{C_GRAY}--{C_RESET}"
                raw_str = f" (raw: {s.get('raw_value')})" if s.get("raw_value") is not None and s.get("raw_value") != val else ""
                tf_str = f" [⚙ {s.get('transform')}]" if s.get("transform") else ""
                opt_str = f" {C_CYAN}★ Optimal{C_RESET}" if s.get("is_optimal") else ""
                outlier_str = f" {C_RED}[OUTLIER]{C_RESET}" if s.get("is_divergent") else ""

                lines.append(f"   • {C_CYAN}[{s_id:<6}]{C_RESET} {s_key:<42} : {val_str}{raw_str}{tf_str}{opt_str}{outlier_str}")

            if r.is_discrepant and r.discrepancy_reason:
                lines.append(f"   {C_RED}⚠️  Discrepancy: {r.discrepancy_reason}{C_RESET}")
            lines.append(" " * 4)
        else:
            # Format single line
            mqtt_str = f"{r.mqtt_value} {r.unit}".strip() if r.mqtt_value is not None else f"{C_GRAY}--{C_RESET}"
            mb_str = f"{r.modbus_value} {r.unit}".strip() if r.modbus_value is not None else f"{C_GRAY}--{C_RESET}"
            mb_key = r.modbus_key if len(r.modbus_key) <= 33 else "..." + r.modbus_key[-30:]
            line = (
                f"{r.label:<26} "
                f"{mqtt_str:<18} "
                f"{mb_key:<34} "
                f"{mb_str:<16} "
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
