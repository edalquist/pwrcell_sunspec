"""Unified Concept Model for Generac PWRcell (v3).

Replaces the separate CompoundFieldView, UnifiedFieldGroup, and ComparisonResultRow
abstractions with a single canonical ConceptView. Represents a logical metric across
contributing MQTT push telemetry and SunSpec Modbus registers.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConceptSource:
    """A contributing telemetry source (MQTT push or Modbus register)."""
    source_type: str        # 'MQTT' or 'SUNSPEC'
    source_id: str          # 'MQTT', 'M102', 'M64208', etc.
    field_key: str          # e.g. 'inverter.model_64208.CTPow' or 'inverter.live.grid_power_w'
    name: str               # e.g. 'CTPow'
    label: str              # e.g. 'Grid Net Power (M64208)'
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    value: Any = None
    raw_value: Any = None
    units: Optional[str] = None
    is_writable: bool = False
    offset: Optional[int] = None
    scale_factor: Optional[str] = None
    bounds: Optional[Dict[str, Any]] = None
    is_optimal: bool = False
    is_pinned: bool = False
    transform: Optional[str] = None
    point_type: Optional[str] = None
    is_bitfield: bool = False
    is_enum: bool = False
    symbols: Optional[List[Any]] = None
    bitmask_flags: Optional[List[str]] = None
    is_scale_factor: bool = False
    is_custom_override: bool = False
    is_divergent: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.field_key
        return d


@dataclass
class ConceptView:
    """Single unified representation of a logical metric across 1..N sources.
    
    Unifies CompoundFieldView, UnifiedFieldGroup, and ComparisonResultRow into
    a single canonical data structure consumed by Home Assistant, the Web UI,
    and diagnostic tools.
    """
    id: str                 # Canonical ID: '<device_type>.concept.<concept_key>'
    concept_key: str        # e.g. 'grid_power', 'battery_soc'
    device_sn: str
    device_type: str
    name: str
    label: str
    description: str
    units: Optional[str] = None

    # Telemetry sources:
    sources: List[ConceptSource] = field(default_factory=list)
    active_source_key: Optional[str] = None
    preferred_source_key: Optional[str] = None
    latest_value: Any = None
    raw_value: Any = None
    latest_source: str = "NONE"
    latest_updated: float = 0.0

    # Comparison / Discrepancy analysis:
    delta: Optional[float] = None
    match_pct: Optional[float] = None
    status: str = "SINGLE_SOURCE"   # 'EXACT', 'CLOSE', 'DIVERGENT', 'SINGLE_SOURCE', 'NO_DATA'
    status_label: str = ""
    is_discrepant: bool = False
    discrepancy_reason: str = ""
    confidence: str = "HIGH"
    notes: str = ""

    # Home Assistant & Control metadata:
    ha_platform: str = "sensor"     # 'sensor', 'select', 'number', 'binary_sensor'
    ha_device_class: Optional[str] = None
    ha_state_class: Optional[str] = None
    ha_unit: Optional[str] = None
    ha_options: Optional[List[str]] = None
    ha_suggested_display_precision: Optional[int] = None
    is_writable: bool = False
    is_selected: bool = False
    bounds: Optional[Dict[str, Any]] = None
    point_type: Optional[str] = None
    is_bitfield: bool = False
    is_enum: bool = False
    symbols: Optional[List[Any]] = None
    bitmask_flags: Optional[List[str]] = None
    is_scale_factor: bool = False
    is_custom_override: bool = False
    modbus_candidates: List[str] = field(default_factory=list)

    # Identity and compatibility properties:
    is_compound: bool = True
    model_id: Optional[int] = None
    model_name: str = "concept"
    model_label: str = "Unified Concept"

    @property
    def access(self) -> str:
        """Access permission ('RW' if writable else 'R')."""
        return "RW" if self.is_writable else "R"

    @property
    def value(self) -> Any:
        return self.latest_value

    @property
    def source(self) -> str:
        return self.latest_source

    @property
    def key(self) -> str:
        """Primary identifier, aliased to id for compatibility."""
        return self.id

    @property
    def mapping_id(self) -> str:
        """Legacy mapping ID compatibility."""
        return self.concept_key

    @property
    def mqtt_source(self) -> Optional[ConceptSource]:
        """Contributing MQTT push telemetry source if present."""
        return next((s for s in self.sources if s.source_type == "MQTT"), None)

    @property
    def modbus_source(self) -> Optional[ConceptSource]:
        """Active or primary contributing Modbus source if present."""
        optimal = next((s for s in self.sources if s.source_type != "MQTT" and s.is_optimal), None)
        if optimal:
            return optimal
        return next((s for s in self.sources if s.source_type != "MQTT"), None)

    @property
    def mqtt_value(self) -> Any:
        src = self.mqtt_source
        return src.value if src else None

    @mqtt_value.setter
    def mqtt_value(self, val: Any):
        src = self.mqtt_source
        if src:
            src.value = val
        self.latest_value = val

    @property
    def mqtt_raw_value(self) -> Any:
        src = self.mqtt_source
        return src.raw_value if src else None

    @mqtt_raw_value.setter
    def mqtt_raw_value(self, val: Any):
        src = self.mqtt_source
        if src:
            src.raw_value = val
        self.raw_value = val

    @property
    def mqtt_key(self) -> Optional[str]:
        src = self.mqtt_source
        return src.field_key if src else None

    @property
    def modbus_value(self) -> Any:
        src = self.modbus_source
        return src.value if src else None

    @modbus_value.setter
    def modbus_value(self, val: Any):
        src = self.modbus_source
        if src:
            src.value = val
        self.latest_value = val

    @property
    def modbus_raw_value(self) -> Any:
        src = self.modbus_source
        return src.raw_value if src else None

    @modbus_raw_value.setter
    def modbus_raw_value(self, val: Any):
        src = self.modbus_source
        if src:
            src.raw_value = val
        self.raw_value = val

    @property
    def modbus_key(self) -> Optional[str]:
        src = self.modbus_source
        return src.field_key if src else None

    @property
    def modbus_label(self) -> str:
        src = self.modbus_source
        return src.label if src else ""

    def get_bounds(self) -> Optional[Dict[str, Any]]:
        """Compute bounds dictionary for UI controls or HA validation."""
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
            }
        if self.bounds:
            return self.bounds
        for s in self.sources:
            if s.bounds:
                return s.bounds
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for REST API responses."""
        return {
            "id": self.id,
            "key": self.active_source_key or self.id,
            "field_key": self.active_source_key,
            "concept_key": self.concept_key,
            "mapping_id": self.concept_key,
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "device_name": getattr(self, "device_name", ""),
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "units": self.units,
            "unit": self.units or "",
            "access": self.access,
            "value": self.latest_value,
            "source": self.latest_source,
            "sources": [s.to_dict() for s in self.sources],
            "active_source_key": self.active_source_key,
            "preferred_source_key": self.preferred_source_key,
            "latest_value": self.latest_value,
            "raw_value": self.raw_value,
            "latest_source": self.latest_source,
            "latest_updated": self.latest_updated,
            "mqtt_key": self.mqtt_key,
            "mqtt_value": self.mqtt_value,
            "modbus_key": self.modbus_key,
            "modbus_label": self.modbus_label,
            "modbus_value": self.modbus_value,
            "modbus_candidates": self.modbus_candidates or [s.field_key for s in self.sources if s.source_type != "MQTT"],
            "delta": round(self.delta, 2) if self.delta is not None else None,
            "match_pct": round(self.match_pct, 1) if self.match_pct is not None else None,
            "status": self.status,
            "status_label": self.status_label or self.status,
            "is_discrepant": self.is_discrepant,
            "discrepancy_reason": self.discrepancy_reason or self.notes,
            "confidence": self.confidence,
            "notes": self.notes,
            "is_writable": self.is_writable,
            "ha_platform": self.ha_platform,
            "ha_device_class": self.ha_device_class,
            "ha_state_class": self.ha_state_class,
            "is_selected": self.is_selected,
            "bounds": self.get_bounds(),
            "point_type": self.point_type,
            "is_bitfield": self.is_bitfield,
            "is_enum": self.is_enum,
            "symbols": self.symbols,
            "bitmask_flags": self.bitmask_flags,
            "is_scale_factor": self.is_scale_factor,
            "is_custom_override": self.is_custom_override,
            "is_compound": self.is_compound,
            "source_count": len(self.sources),
            "sunspec_model_count": len({s.model_id for s in self.sources if s.model_id is not None}),
        }


# Aliases for unified consumption across existing modules
UnifiedSource = ConceptSource
UnifiedFieldGroup = ConceptView
CompoundFieldView = ConceptView
ComparisonResultRow = ConceptView
