"""Set-Cover Optimization & Unified Field Grouping for Generac PWRcell (v3).

Groups redundant metrics across multiple SunSpec models and internal MQTT push
into single unified rows. Computes the exact minimal set of SunSpec models
needed to satisfy a collection of requested/selected fields (Set Cover Problem),
minimizing Modbus RS-485 bus traffic, cycle times, and redundant registers.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .catalog import is_scale_factor_point

logger = logging.getLogger(__name__)


def clean_unit(unit: Optional[str]) -> str:
    """Normalize unit string for fuzzy matching across models."""
    if not unit:
        return ""
    u = unit.strip().replace("°", "").replace("Deg", "").replace("deg", "")
    mapping = {
        "c": "C",
        "f": "F",
        "w": "W",
        "wh": "Wh",
        "kwh": "kWh",
        "v": "V",
        "a": "A",
        "hz": "Hz",
        "pct": "%",
        "percent": "%",
        "%": "%",
        "%whrtg": "%",
        "sec": "s",
        "s": "s",
        "va": "VA",
        "var": "VAr",
    }
    return mapping.get(u.lower(), u)


# Canonical synonym dictionary: maps (device_type, canonical_name) -> set of point names
CANONICAL_SYNONYMS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "inverter": {
        "ac_frequency": {
            "names": {"hz", "ac_frequency_hz", "ac_freq"},
            "units": "Hz",
            "label": "AC Frequency",
            "ha_platform": "sensor",
            "ha_device_class": "frequency",
            "ha_state_class": "measurement",
            "desc": "AC line grid frequency",
        },
        "inverter_output_power": {
            "names": {"w", "inverter_power_w", "inverter_output_power_w", "inverter_output_power", "inverter_power", "real_power"},
            "units": "W",
            "label": "Inverter Output Power",
            "ha_platform": "sensor",
            "ha_device_class": "power",
            "ha_state_class": "measurement",
            "desc": "Real AC power output from inverter",
        },
        "inverter_output_energy": {
            "names": {"wh", "e", "inverter_output_exported_energy_wh", "inverter_output_energy_wh"},
            "units": "Wh",
            "label": "Inverter Output Energy",
            "ha_platform": "sensor",
            "ha_device_class": "energy",
            "ha_state_class": "total_increasing",
            "desc": "Cumulative electrical energy produced/exported by the inverter",
        },
        "grid_power": {
            "names": {"ctpow", "grid_power_w"},
            "units": "W",
            "label": "Grid Net Power",
            "ha_platform": "sensor",
            "ha_device_class": "power",
            "ha_state_class": "measurement",
            "desc": "Net power imported (+) or exported (-) to the utility grid",
        },
        "phase_a_voltage": {
            "names": {"phvpha", "ac_voltage_v"},
            "units": "V",
            "label": "Phase A Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "AC voltage on Phase A",
        },
        "phase_b_voltage": {
            "names": {"phvphb"},
            "units": "V",
            "label": "Phase B Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "AC voltage on Phase B",
        },
        "phase_c_voltage": {
            "names": {"phvphc"},
            "units": "V",
            "label": "Phase C Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "AC voltage on Phase C",
        },
        "phase_a_current": {
            "names": {"apha"},
            "units": "A",
            "label": "Phase A Current",
            "ha_platform": "sensor",
            "ha_device_class": "current",
            "ha_state_class": "measurement",
            "desc": "AC current on Phase A",
        },
        "phase_b_current": {
            "names": {"aphb"},
            "units": "A",
            "label": "Phase B Current",
            "ha_platform": "sensor",
            "ha_device_class": "current",
            "ha_state_class": "measurement",
            "desc": "AC current on Phase B",
        },
        "phase_c_current": {
            "names": {"aphc"},
            "units": "A",
            "label": "Phase C Current",
            "ha_platform": "sensor",
            "ha_device_class": "current",
            "ha_state_class": "measurement",
            "desc": "AC current on Phase C",
        },
        "grid_imported_energy": {
            "names": {"grid_imported_energy_wh", "totwhimp"},
            "units": "Wh",
            "label": "Grid Imported Energy",
            "ha_platform": "sensor",
            "ha_device_class": "energy",
            "ha_state_class": "total_increasing",
            "desc": "Cumulative energy imported from grid",
        },
        "grid_exported_energy": {
            "names": {"whout", "grid_exported_energy_wh", "totwhexp"},
            "units": "Wh",
            "label": "Grid Exported Energy",
            "ha_platform": "sensor",
            "ha_device_class": "energy",
            "ha_state_class": "total_increasing",
            "desc": "Cumulative energy exported to grid",
        },
        "system_mode": {
            "names": {"sysmd", "system_mode"},
            "units": "",
            "label": "System Operating Mode",
            "ha_platform": "select",
            "desc": "Operating mode of PWRcell inverter and REbus system",
        },
        "temp_cabinet": {
            "names": {"tmpcab", "temperature_cabinet_c"},
            "units": "C",
            "label": "Cabinet Temperature",
            "ha_platform": "sensor",
            "ha_device_class": "temperature",
            "ha_state_class": "measurement",
            "desc": "Internal cabinet temperature",
        },
        "temp_heatsink": {
            "names": {"tmpsnk", "temperature_heatsink_c"},
            "units": "C",
            "label": "Heatsink Temperature",
            "ha_platform": "sensor",
            "ha_device_class": "temperature",
            "ha_state_class": "measurement",
            "desc": "Inverter power stage heatsink temperature",
        },
        "temp_ambient": {
            "names": {"tmpamb"},
            "units": "C",
            "label": "Ambient Temperature",
            "ha_platform": "sensor",
            "ha_device_class": "temperature",
            "ha_state_class": "measurement",
            "desc": "Ambient surrounding temperature",
        },
        "vref": {
            "names": {"vref"},
            "units": "V",
            "label": "Voltage Reference",
            "ha_platform": "number",
            "ha_device_class": "voltage",
            "desc": "Bus voltage reference setting",
        },
        "wmax": {
            "names": {"wmax"},
            "units": "W",
            "label": "Max Power Setting",
            "ha_platform": "number",
            "ha_device_class": "power",
            "desc": "Configured maximum active power limit",
        },
    },
    "battery": {
        "state_of_charge": {
            "names": {"soc", "state_of_charge"},
            "units": "%",
            "label": "Battery State of Charge",
            "ha_platform": "sensor",
            "ha_device_class": "battery",
            "ha_state_class": "measurement",
            "desc": "Current battery charge level percentage",
        },
        "state_of_health": {
            "names": {"soh", "state_of_health"},
            "units": "%",
            "label": "Battery State of Health",
            "ha_platform": "sensor",
            "ha_device_class": "battery",
            "ha_state_class": "measurement",
            "desc": "Battery health percentage relative to nameplate",
        },
        "battery_power": {
            "names": {"w", "battery_power_w"},
            "units": "W",
            "label": "Battery Power",
            "ha_platform": "sensor",
            "ha_device_class": "power",
            "ha_state_class": "measurement",
            "desc": "Real power discharged (+) or charged (-) by battery",
        },
        "battery_voltage": {
            "names": {"battery_voltage_v"},
            "units": "V",
            "label": "Battery Terminal Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "DC voltage measured at battery terminals",
        },
        "rebus_voltage": {
            "names": {"rebus_v"},
            "units": "V",
            "label": "REbus DC Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "REbus 380V DC distribution line voltage measured at battery",
        },
        "battery_current": {
            "names": {"a", "battery_current_a"},
            "units": "A",
            "label": "Battery Current",
            "ha_platform": "sensor",
            "ha_device_class": "current",
            "ha_state_class": "measurement",
            "desc": "DC current flowing into or out of battery",
        },
        "battery_imported_energy": {
            "names": {"whin", "battery_imported_energy_wh"},
            "units": "Wh",
            "label": "Battery Stored Energy",
            "ha_platform": "sensor",
            "ha_device_class": "energy",
            "ha_state_class": "total_increasing",
            "desc": "Cumulative electrical energy charged into battery storage",
        },
        "battery_exported_energy": {
            "names": {"whout", "battery_exported_energy_wh"},
            "units": "Wh",
            "label": "Battery Discharged Energy",
            "ha_platform": "sensor",
            "ha_device_class": "energy",
            "ha_state_class": "total_increasing",
            "desc": "Cumulative electrical energy discharged from battery storage",
        },
        "operating_state": {
            "names": {"state", "battery_state"},
            "units": "",
            "label": "Battery Operating State",
            "ha_platform": "sensor",
            "desc": "Operating status / state enumeration",
        },
        "rebus_node_state": {
            "names": {"st", "rebus_state"},
            "units": "",
            "label": "REbus Node State",
            "ha_platform": "sensor",
            "desc": "REbus communication node operating status",
        },
        "temp_battery": {
            "names": {"tmp", "temperature_c"},
            "units": "C",
            "label": "Battery Temperature",
            "ha_platform": "sensor",
            "ha_device_class": "temperature",
            "ha_state_class": "measurement",
            "desc": "Battery module internal temperature",
        },
    },
    "pv_link": {
        "dc_power": {
            "names": {"dcw", "p", "solar_power_w"},
            "units": "W",
            "label": "DC String Power",
            "ha_platform": "sensor",
            "ha_device_class": "power",
            "ha_state_class": "measurement",
            "desc": "Photovoltaic DC power generated on this string link",
        },
        "dc_voltage": {
            "names": {"dcv"},
            "units": "V",
            "label": "DC Output Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "PV Link DC output voltage",
        },
        "string_input_voltage": {
            "names": {"vin", "indcv"},
            "units": "V",
            "label": "PV String Input Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "Solar PV string input voltage",
        },
        "rebus_voltage": {
            "names": {"v", "rebus_v"},
            "units": "V",
            "label": "REbus DC Voltage",
            "ha_platform": "sensor",
            "ha_device_class": "voltage",
            "ha_state_class": "measurement",
            "desc": "REbus 380V DC distribution line voltage measured at PV Link",
        },
        "dc_current": {
            "names": {"dca", "i"},
            "units": "A",
            "label": "DC Output Current",
            "ha_platform": "sensor",
            "ha_device_class": "current",
            "ha_state_class": "measurement",
            "desc": "PV Link DC output current",
        },
        "string_input_current": {
            "names": {"iin", "indca"},
            "units": "A",
            "label": "PV String Input Current",
            "ha_platform": "sensor",
            "ha_device_class": "current",
            "ha_state_class": "measurement",
            "desc": "Solar PV string input current",
        },
        "energy": {
            "names": {"dcwh", "e"},
            "units": "Wh",
            "label": "Lifetime DC Energy",
            "ha_platform": "sensor",
            "ha_device_class": "energy",
            "ha_state_class": "total_increasing",
            "desc": "Cumulative solar energy generated",
        },
        "operating_state": {
            "names": {"st", "state"},
            "units": "",
            "label": "PV Link State",
            "ha_platform": "sensor",
            "desc": "PV Link module operating state",
        },
        "temp_pvlink": {
            "names": {"tmp", "temperature_c"},
            "units": "C",
            "label": "PV Link Temperature",
            "ha_platform": "sensor",
            "ha_device_class": "temperature",
            "ha_state_class": "measurement",
            "desc": "PV Link heatsink temperature",
        },
    },
    "rebus_beacon": {
        "system_mode": {
            "names": {"sysmd", "system_mode"},
            "units": "",
            "label": "System Operating Mode",
            "ha_platform": "select",
            "desc": "PWRcell system operating mode",
        },
    },
}


@dataclass
class OptimizationResult:
    """Result of Set Cover Optimization."""
    minimal_models: List[int]
    assignments: Dict[str, Union[int, str]]  # item_id -> chosen model_id or 'MQTT'
    stats: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "minimal_models": self.minimal_models,
            "assignments": self.assignments,
            "stats": self.stats,
        }


def solve_minimal_model_set(
    items: Dict[str, Set[Union[int, str]]],
    pinned_sources: Optional[Dict[str, Union[int, str]]] = None,
    model_preferences: Optional[Dict[int, float]] = None,
    allow_mqtt: bool = True,
) -> OptimizationResult:
    """Find the exact minimal set of SunSpec models to poll for a collection of items.

    Uses exact Set Cover branch-and-bound search. Since candidate model count
    per PWRcell device is small (<= 15 models), this always finds the global
    minimum in < 1ms.

    Args:
        items: Dict of item_key -> Set of candidate sources (e.g. {102, 64208, 'MQTT'})
        pinned_sources: User-pinned preference per item_key (forced into solution)
        model_preferences: Optional lower-is-better weights per model ID (tie-breaker)
        allow_mqtt: Whether MQTT source satisfies the item without Modbus polling

    Returns:
        OptimizationResult with minimal_models, assignments, and performance stats.
    """
    if not items:
        return OptimizationResult(minimal_models=[], assignments={}, stats={"total_items": 0, "models_needed": 0})

    pinned = pinned_sources or {}
    weights = model_preferences or {}

    # Default weights prioritize rich models like Generac status models
    default_favored = {64208: 0.8, 64252: 0.8, 404: 0.8, 64207: 0.85, 102: 0.9, 802: 0.9}

    def get_weight(m: int) -> float:
        return weights.get(m, default_favored.get(m, 1.0))

    assignments: Dict[str, Union[int, str]] = {}
    modbus_items: Dict[str, Set[int]] = {}

    # 1. Process items pinned to MQTT or satisfied by MQTT without user Modbus pinning
    for item_key, candidates in items.items():
        user_pin = pinned.get(item_key)
        if user_pin == "MQTT" or (user_pin is None and allow_mqtt and "MQTT" in candidates and len(candidates) == 1):
            assignments[item_key] = "MQTT"
            continue

        if user_pin == "MQTT":
            assignments[item_key] = "MQTT"
            continue

        # Extract numeric Modbus model candidates
        int_cands = {c for c in candidates if isinstance(c, int)}
        if not int_cands:
            if "MQTT" in candidates:
                assignments[item_key] = "MQTT"
            continue

        modbus_items[item_key] = int_cands

    # 2. Extract fixed/pinned models & mandatory models (essential sets)
    chosen_models: Set[int] = set()
    for item_key, cand_set in modbus_items.items():
        user_pin = pinned.get(item_key)
        if user_pin is not None and isinstance(user_pin, int) and user_pin in cand_set:
            chosen_models.add(user_pin)
            assignments[item_key] = user_pin

    # Mandatory models: any model that is the sole Modbus candidate for an item has no choice
    for item_key, cand_set in modbus_items.items():
        if len(cand_set) == 1:
            m = next(iter(cand_set))
            chosen_models.add(m)
            assignments[item_key] = m

    # 3. Determine remaining uncovered items
    uncovered = {k: cands for k, cands in modbus_items.items() if k not in assignments}
    uncovered_after_pinned = {k: cands for k, cands in uncovered.items() if not (cands & chosen_models)}

    # For items that are already covered by chosen_models, assign them now
    for k, cands in list(uncovered.items()):
        intersect = cands & chosen_models
        if intersect:
            # Pick best model among intersect
            best_m = min(intersect, key=lambda m: (get_weight(m), m))
            assignments[k] = best_m

    # If all items are satisfied by pinned models, we are done!
    if not uncovered_after_pinned:
        all_candidate_models = {c for cands in modbus_items.values() for c in cands}
        models_list = sorted(list(chosen_models))
        return OptimizationResult(
            minimal_models=models_list,
            assignments=assignments,
            stats={
                "total_items": len(items),
                "models_needed": len(models_list),
                "candidate_models_count": len(all_candidate_models),
                "models_avoided": max(0, len(all_candidate_models) - len(models_list)),
            },
        )

    # 4. Exact Set Cover combination search on remaining uncovered items
    cand_pool = sorted(list({c for cands in uncovered_after_pinned.values() for c in cands}))
    required_keys = list(uncovered_after_pinned.keys())

    best_comb: Optional[Tuple[int, ...]] = None
    best_cost = float("inf")

    # Search combinations of increasing size k = 1, 2, ..., len(cand_pool)
    for k in range(1, len(cand_pool) + 1):
        found_for_k = False
        for comb in itertools.combinations(cand_pool, k):
            comb_set = set(comb)
            # Check if comb_set covers all required keys
            if all(uncovered_after_pinned[key] & comb_set for key in required_keys):
                cost = sum(get_weight(m) for m in comb)
                if cost < best_cost:
                    best_cost = cost
                    best_comb = comb
                    found_for_k = True

        if found_for_k:
            # Since we iterate k in increasing order, the first k with a valid cover is strictly minimal
            break

    if best_comb:
        chosen_models.update(best_comb)

    # 5. Finalize assignments for all items
    for item_key, cands in modbus_items.items():
        if item_key not in assignments:
            intersect = cands & chosen_models
            if intersect:
                assignments[item_key] = min(intersect, key=lambda m: (get_weight(m), m))
            elif cands:
                # Fallback if no model was chosen (should not happen)
                assignments[item_key] = min(cands, key=lambda m: (get_weight(m), m))

    all_candidate_models = {c for cands in modbus_items.values() for c in cands}
    models_list = sorted(list(chosen_models))
    models_avoided = max(0, len(all_candidate_models) - len(models_list))

    return OptimizationResult(
        minimal_models=models_list,
        assignments=assignments,
        stats={
            "total_items": len(items),
            "models_needed": len(models_list),
            "candidate_models_count": len(all_candidate_models),
            "models_avoided": models_avoided,
            "mqtt_covered_count": sum(1 for v in assignments.values() if v == "MQTT"),
        },
    )


@dataclass
class UnifiedSource:
    """A candidate data source for a unified field."""
    source_type: str  # 'MQTT' or 'SUNSPEC'
    source_id: str    # e.g. 'MQTT', 'M102', 'M64208'
    field_key: str    # e.g. 'inverter.inverter.Hz'
    name: str         # short point name 'Hz'
    label: str        # e.g. 'AC Frequency (Model 102)'
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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.field_key
        return d


@dataclass
class UnifiedFieldGroup:
    """A unified semantic group representing a metric across 0..1 MQTT + 0..N SunSpec sources."""
    id: str  # Unique group ID e.g. 'inverter.unified.ac_frequency'
    concept_key: str  # Concept key e.g. 'ac_frequency'
    device_sn: str
    device_type: str
    name: str
    label: str
    description: str
    units: Optional[str] = None
    sources: List[UnifiedSource] = field(default_factory=list)
    active_source_key: Optional[str] = None
    preferred_source_key: Optional[str] = None
    latest_value: Any = None
    latest_source: str = "NONE"
    latest_updated: float = 0.0
    is_writable: bool = False
    ha_platform: str = "sensor"
    ha_device_class: Optional[str] = None
    ha_state_class: Optional[str] = None
    is_selected: bool = False
    bounds: Optional[Dict[str, Any]] = None
    point_type: Optional[str] = None
    is_bitfield: bool = False
    is_enum: bool = False
    symbols: Optional[List[Any]] = None
    bitmask_flags: Optional[List[str]] = None
    raw_value: Any = None
    is_scale_factor: bool = False
    is_custom_override: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.active_source_key or self.id,
            "field_key": self.active_source_key,
            "concept_key": self.concept_key,
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "units": self.units,
            "sources": [s.to_dict() for s in self.sources],
            "active_source_key": self.active_source_key,
            "preferred_source_key": self.preferred_source_key,
            "latest_value": self.latest_value,
            "raw_value": self.raw_value,
            "latest_source": self.latest_source,
            "latest_updated": self.latest_updated,
            "is_writable": self.is_writable,
            "ha_platform": self.ha_platform,
            "ha_device_class": self.ha_device_class,
            "ha_state_class": self.ha_state_class,
            "is_selected": self.is_selected,
            "bounds": self.bounds,
            "point_type": self.point_type,
            "is_bitfield": self.is_bitfield,
            "is_enum": self.is_enum,
            "symbols": self.symbols,
            "bitmask_flags": self.bitmask_flags,
            "is_scale_factor": self.is_scale_factor,
            "is_custom_override": self.is_custom_override,
            "source_count": len(self.sources),
            "sunspec_model_count": len({s.model_id for s in self.sources if s.model_id is not None}),
        }


def find_canonical_concept(dev_type: str, point_name: str, units: Optional[str]) -> Optional[str]:
    """Match point_name and unit against canonical concept definitions."""
    d_type = dev_type.lower()
    p_name = point_name.lower().strip()
    c_unit = clean_unit(units)

    concepts = CANONICAL_SYNONYMS.get(d_type, {})
    # 1. Exact name + matching unit
    for c_key, c_def in concepts.items():
        if p_name in c_def["names"]:
            exp_unit = clean_unit(c_def.get("units"))
            if not exp_unit or not c_unit or exp_unit == c_unit:
                return c_key

    # 2. Name match (allows detecting unit mismatches across models)
    for c_key, c_def in concepts.items():
        if p_name in c_def["names"]:
            return c_key

    return None


def _field_matches_modbus_target(f: Any, target_str: str) -> bool:
    """Check if a StateField matches a configured Modbus target string like 'battery.model_802.V'."""
    if not target_str:
        return False
    parts = target_str.split(".")
    target_point = parts[-1]
    if f.name.lower() != target_point.lower():
        return False
    if len(parts) >= 2:
        model_part = parts[-2].lower()
        if model_part.startswith("model_"):
            try:
                target_m_id = int(model_part.replace("model_", ""))
                if f.model_id is not None and f.model_id != target_m_id:
                    return False
            except ValueError:
                pass
        else:
            if f.model_name and model_part not in (f.model_name.lower(), f"model_{f.model_id}"):
                return False
    return True


def group_device_fields(
    dev: Any,
    mapping_registry: Optional[Any] = None,
    ha_selected_keys: Optional[Set[str]] = None,
    preferred_sources: Optional[Dict[str, str]] = None,
    custom_groupings: Optional[Dict[str, Any]] = None,
) -> List[UnifiedFieldGroup]:
    """Group all fields of a device into unified semantic rows with minimal model solving.

    Args:
        dev: DeviceState or UnifiedDevice instance
        mapping_registry: MappingRegistry instance
        ha_selected_keys: Set of keys currently selected in HA export
        preferred_sources: Dict of group_id -> preferred field_key (pinned by user)
        custom_groupings: Dict of custom user grouping overrides

    Returns:
        List of UnifiedFieldGroup objects sorted cleanly.
    """
    from .mapping import MappingRegistry
    reg = mapping_registry or MappingRegistry.get_instance()
    selected_keys = ha_selected_keys or set()
    user_pins = preferred_sources or {}

    if custom_groupings is None:
        try:
            from .grouping import load_custom_groupings
            custom_groupings = load_custom_groupings()
        except Exception:
            custom_groupings = {}

    overrides = custom_groupings.get("field_overrides", {}) or {}
    custom_concepts = custom_groupings.get("custom_concepts", {}) or {}

    dev_type = getattr(dev, "device_type", "inverter")
    dev_sn = getattr(dev, "serial_number", "")
    all_fields = getattr(dev, "fields", {})

    # 1. Bucket fields by concept ID
    # Bucket format: concept_id -> list of (field_key, field_obj, transform)
    concept_buckets: Dict[str, List[Tuple[str, Any, Optional[str]]]] = {}
    concept_metadata: Dict[str, Dict[str, Any]] = {}

    # Map configured mappings for this device type
    for m in reg.get_all():
        if m.device_type == dev_type:
            c_id = f"{dev_type}.concept.{m.id}"
            concept_metadata[c_id] = {
                "id": c_id,
                "concept_key": m.id,
                "name": m.id,
                "label": m.label,
                "description": m.description,
                "units": m.unit,
                "ha_platform": m.ha_platform,
                "ha_device_class": m.ha_device_class,
                "ha_state_class": m.ha_state_class,
            }

    # Map each field into a concept
    assigned_field_keys: Set[str] = set()

    for f_key, f in all_fields.items():
        # Check user custom grouping overrides first
        qual_key = f"{dev_sn}:{f_key}" if dev_sn else f_key
        has_override = qual_key in overrides or f_key in overrides

        if has_override:
            target_concept = overrides.get(qual_key, overrides.get(f_key))
            if target_concept is None or str(target_concept).strip().lower() in ("", "null", "none", "standalone", "ungrouped"):
                c_id = f"{dev_type}.standalone.{f.name.lower()}_{getattr(f, 'model_id', 'raw')}"
                if c_id not in concept_metadata:
                    concept_metadata[c_id] = {
                        "id": c_id,
                        "concept_key": f"{f.name.lower()}_{getattr(f, 'model_id', 'raw')}",
                        "name": f.name,
                        "label": f"{f.label} (Ungrouped)",
                        "description": f.description,
                        "units": f.units,
                        "ha_platform": f.ha_hint.platform if f.ha_hint else ("sensor" if not f.is_writable else "number"),
                        "ha_device_class": f.ha_hint.device_class if f.ha_hint else None,
                        "ha_state_class": f.ha_hint.state_class if f.ha_hint else None,
                        "is_custom_override": True,
                    }
                concept_buckets.setdefault(c_id, []).append((f_key, f, None))
                assigned_field_keys.add(f_key)
                continue
            else:
                target_key = str(target_concept).strip()
                c_id = f"{dev_type}.concept.{target_key}"
                c_meta = custom_concepts.get(target_key, {})
                if c_id not in concept_metadata:
                    concept_metadata[c_id] = {
                        "id": c_id,
                        "concept_key": target_key,
                        "name": target_key,
                        "label": c_meta.get("label") or target_key.replace("_", " ").title(),
                        "description": c_meta.get("description", f.description),
                        "units": c_meta.get("units", f.units),
                        "ha_platform": c_meta.get("ha_platform", f.ha_hint.platform if f.ha_hint else "sensor"),
                        "ha_device_class": c_meta.get("ha_device_class"),
                        "ha_state_class": c_meta.get("ha_state_class"),
                        "is_custom_override": True,
                    }
                concept_buckets.setdefault(c_id, []).append((f_key, f, None))
                assigned_field_keys.add(f_key)
                continue

        # Check if mapped to a TelemetryMappingDef
        assigned = False
        for m in reg.get_all():
            if m.device_type == dev_type:
                is_match = False
                transform = None
                if f_key == m.mqtt_field or f.name == m.mqtt_field.split(".")[-1]:
                    is_match = True
                elif f_key == m.modbus_field or _field_matches_modbus_target(f, m.modbus_field):
                    is_match = True
                    transform = m.transform
                elif any(f_key == alt or _field_matches_modbus_target(f, alt) for alt in m.modbus_candidates):
                    is_match = True
                    transform = m.transform

                if is_match:
                    c_id = f"{dev_type}.concept.{m.id}"
                    concept_buckets.setdefault(c_id, []).append((f_key, f, transform))
                    assigned_field_keys.add(f_key)
                    assigned = True
                    break

        if assigned:
            continue

        # Check canonical synonyms
        matched_concept = find_canonical_concept(dev_type, f.name, f.units)
        if matched_concept:
            c_id = f"{dev_type}.concept.{matched_concept}"
            syn_info = CANONICAL_SYNONYMS[dev_type][matched_concept]
            if c_id not in concept_metadata:
                concept_metadata[c_id] = {
                    "id": c_id,
                    "concept_key": matched_concept,
                    "name": matched_concept,
                    "label": syn_info["label"],
                    "description": syn_info.get("desc", f.description),
                    "units": syn_info.get("units", f.units),
                    "ha_platform": syn_info.get("ha_platform", f.ha_hint.platform if f.ha_hint else "sensor"),
                    "ha_device_class": syn_info.get("ha_device_class"),
                    "ha_state_class": syn_info.get("ha_state_class"),
                }
            concept_buckets.setdefault(c_id, []).append((f_key, f, None))
            assigned_field_keys.add(f_key)
            continue

        # Fallback 1: Group by name + clean unit if duplicates exist across models
        norm_name = f.name.lower()
        c_unit = clean_unit(f.units)
        pt_type = getattr(f, "point_type", None)
        is_sf = is_scale_factor_point(
            name=f.name,
            point_type=pt_type,
            label=getattr(f, "label", None),
            explicit=bool(getattr(f, "is_scale_factor", False)),
        )
        is_model_specific = (
            is_sf
            or norm_name in {
                "modena", "actcrv", "ncrv", "wintms", "rmptms", "rvrttms", "crvnum",
                "readonly", "subgroup", "npts",
            }
        )
        m_id = getattr(f, "model_id", None)
        if is_model_specific and m_id:
            auto_c_id = f"{dev_type}.m{m_id}.concept.{norm_name}_{c_unit}" if c_unit else f"{dev_type}.m{m_id}.concept.{norm_name}"
            c_key = f"{norm_name}_m{m_id}"
            c_label = f"{f.label} (M{m_id})" if f.label else f.name
        else:
            auto_c_id = f"{dev_type}.concept.{norm_name}_{c_unit}" if c_unit else f"{dev_type}.concept.{norm_name}"
            c_key = norm_name
            c_label = f.label

        if auto_c_id not in concept_metadata:
            concept_metadata[auto_c_id] = {
                "id": auto_c_id,
                "concept_key": c_key,
                "name": f.name,
                "label": c_label,
                "description": f.description,
                "units": f.units,
                "ha_platform": f.ha_hint.platform if f.ha_hint else ("sensor" if not f.is_writable else "number"),
                "ha_device_class": f.ha_hint.device_class if f.ha_hint else None,
                "ha_state_class": f.ha_hint.state_class if f.ha_hint else None,
            }
        concept_buckets.setdefault(auto_c_id, []).append((f_key, f, None))
        assigned_field_keys.add(f_key)

    # 2. Build UnifiedFieldGroup objects & prepare Set Cover Problem inputs
    groups: List[UnifiedFieldGroup] = []
    solver_items: Dict[str, Set[Union[int, str]]] = {}
    pinned_model_inputs: Dict[str, Union[int, str]] = {}

    for c_id, f_list in concept_buckets.items():
        meta = concept_metadata.get(c_id, {})
        sources: List[UnifiedSource] = []
        is_grp_writable = False
        grp_bounds = None
        grp_selected = False

        for f_key, f, transform in f_list:
            is_mqtt = getattr(f.source, "value", str(f.source)) == "MQTT_PUSH" or "live." in f_key
            m_id = getattr(f, "model_id", None)
            m_name = getattr(f, "model_name", None)
            src_type = "MQTT" if is_mqtt else "SUNSPEC"
            src_id = "MQTT" if is_mqtt else (f"M{m_id}" if m_id else "SunSpec")

            sf_val = dev.get_scale_factor_value(f) if hasattr(dev, "get_scale_factor_value") else None
            bounds = f.get_bounds(sf_value=sf_val) if hasattr(f, "get_bounds") else None

            if f.is_writable:
                is_grp_writable = True
            if bounds and not grp_bounds:
                grp_bounds = bounds

            # Check if this field or qualified field is selected in HA config
            qual_key = f"{dev_sn}:{f_key}" if dev_sn else f_key
            if f_key in selected_keys or qual_key in selected_keys:
                grp_selected = True

            pin_match = (user_pins.get(c_id) == f_key)

            is_bf = getattr(f, "is_bitfield", False) or (getattr(f, "point_type", "") or "").startswith("bitfield")
            is_en = getattr(f, "is_enum", False)
            syms = getattr(f, "symbols", None)
            bm_flags = getattr(f, "bitmask_flags", None) or (f.value if (is_bf and isinstance(f.value, list)) else None)
            pt_type = getattr(f, "point_type", None)
            is_sf = is_scale_factor_point(
                name=f.name,
                point_type=pt_type,
                label=getattr(f, "label", None),
                explicit=bool(getattr(f, "is_scale_factor", False)),
            )

            effective_val = f.value
            if transform and effective_val is not None:
                from .mapping import apply_transform
                try:
                    effective_val = apply_transform(effective_val, transform)
                except Exception:
                    pass

            sources.append(
                UnifiedSource(
                    source_type=src_type,
                    source_id=src_id,
                    field_key=f_key,
                    name=f.name,
                    label=f"{f.label} ({src_id})",
                    model_id=m_id,
                    model_name=m_name,
                    value=effective_val,
                    raw_value=f.raw_value,
                    units=f.units or meta.get("units"),
                    is_writable=f.is_writable,
                    offset=getattr(f, "offset", None),
                    scale_factor=getattr(f, "scale_factor_point", None),
                    bounds=bounds,
                    is_pinned=pin_match,
                    transform=transform,
                    point_type=pt_type,
                    is_bitfield=is_bf,
                    is_enum=is_en,
                    symbols=syms,
                    bitmask_flags=bm_flags,
                    is_scale_factor=is_sf,
                    is_custom_override=(qual_key in overrides or f_key in overrides),
                )
            )

        # Check if group id itself was selected
        qual_grp = f"{dev_sn}:{c_id}" if dev_sn else c_id
        if c_id in selected_keys or qual_grp in selected_keys:
            grp_selected = True

        # Build candidate sources for the solver
        # Each source is either model_id (int) or 'MQTT'
        cand_sources: Set[Union[int, str]] = set()
        for s in sources:
            if s.source_type == "MQTT":
                cand_sources.add("MQTT")
            elif s.model_id is not None:
                cand_sources.add(s.model_id)

        solver_items[c_id] = cand_sources

        # Handle user pinned preference
        pref_key = user_pins.get(c_id)
        if pref_key:
            for s in sources:
                if s.field_key == pref_key:
                    pinned_model_inputs[c_id] = "MQTT" if s.source_type == "MQTT" else (s.model_id or pref_key)
                    break

        group = UnifiedFieldGroup(
            id=c_id,
            concept_key=meta.get("concept_key", c_id.split(".")[-1]),
            device_sn=dev_sn,
            device_type=dev_type,
            name=meta.get("name", c_id.split(".")[-1]),
            label=meta.get("label", c_id.split(".")[-1]),
            description=meta.get("description", ""),
            units=meta.get("units"),
            sources=sources,
            preferred_source_key=pref_key,
            is_writable=is_grp_writable,
            ha_platform=meta.get("ha_platform", "sensor"),
            ha_device_class=meta.get("ha_device_class"),
            ha_state_class=meta.get("ha_state_class"),
            is_selected=grp_selected,
            bounds=grp_bounds,
            point_type=next((s.point_type for s in sources if s.point_type), None),
            is_bitfield=any(s.is_bitfield for s in sources),
            is_enum=any(s.is_enum for s in sources),
            symbols=next((s.symbols for s in sources if s.symbols), None),
            bitmask_flags=next((s.bitmask_flags for s in sources if s.bitmask_flags), None),
            is_scale_factor=(
                is_scale_factor_point(
                    name=meta.get("name"),
                    label=meta.get("label"),
                    explicit=any(s.is_scale_factor for s in sources),
                )
                or is_scale_factor_point(name=meta.get("concept_key"))
            ),
            is_custom_override=any(s.is_custom_override for s in sources) or meta.get("is_custom_override", False),
        )
        groups.append(group)

    # 3. Solve Set Cover across all groups (or selected groups)
    selected_solver_items = {
        g.id: solver_items[g.id]
        for g in groups
        if g.is_selected
    }

    if selected_solver_items:
        opt_res = solve_minimal_model_set(
            items=selected_solver_items,
            pinned_sources=pinned_model_inputs,
            allow_mqtt=True,
        )
        polled_models = set(opt_res.minimal_models)
        assignments = dict(opt_res.assignments)

        # For unselected items, if they can be covered by one of the polled models, assign that model!
        for g in groups:
            if g.id not in assignments and not g.preferred_source_key:
                cand_in_polled = [
                    s for s in g.sources
                    if (s.source_type == "MQTT" and "MQTT" in polled_models) or (s.model_id in polled_models)
                ]
                if cand_in_polled:
                    assignments[g.id] = "MQTT" if cand_in_polled[0].source_type == "MQTT" else cand_in_polled[0].model_id
    else:
        opt_res = solve_minimal_model_set(
            items=solver_items,
            pinned_sources=pinned_model_inputs,
            allow_mqtt=True,
        )
        assignments = opt_res.assignments

    # 4. Assign active sources and optimal flags
    for g in groups:
        for s in g.sources:
            s.is_optimal = False
            s.is_pinned = False

        chosen = assignments.get(g.id)
        active_src: Optional[UnifiedSource] = None

        # If user explicitly pinned a preferred field_key, respect it
        if g.preferred_source_key:
            for s in g.sources:
                if s.field_key == g.preferred_source_key:
                    active_src = s
                    s.is_pinned = True
                    break

        # Otherwise pick the source matching chosen model / MQTT
        if not active_src and chosen is not None:
            for s in g.sources:
                if (chosen == "MQTT" and s.source_type == "MQTT") or (s.model_id == chosen):
                    active_src = s
                    break

        # Fallback to first source if none matched
        if not active_src and g.sources:
            active_src = g.sources[0]

        if active_src:
            active_src.is_optimal = True
            g.active_source_key = active_src.field_key
            g.latest_value = active_src.value
            g.raw_value = active_src.raw_value
            g.latest_source = active_src.source_id
            if active_src.point_type:
                g.point_type = active_src.point_type
            if active_src.is_bitfield:
                g.is_bitfield = True
            if active_src.is_enum:
                g.is_enum = True
            if active_src.symbols:
                g.symbols = active_src.symbols
            if active_src.bitmask_flags:
                g.bitmask_flags = active_src.bitmask_flags
            if active_src.is_scale_factor:
                g.is_scale_factor = True

    # Sort groups cleanly: common/important ones first, then alphabetical
    sort_priority = {
        "grid_power": 1,
        "inverter_output_power": 2,
        "solar_power": 3,
        "battery_power": 4,
        "state_of_charge": 5,
        "state_of_health": 6,
        "system_mode": 7,
        "ac_frequency": 8,
        "phase_a_voltage": 9,
        "phase_b_voltage": 10,
        "phase_c_voltage": 11,
        "phase_a_current": 12,
        "phase_b_current": 13,
        "phase_c_current": 14,
    }
    groups.sort(key=lambda g: (sort_priority.get(g.concept_key, 99), g.label.lower()))
    return groups


def resolve_minimal_models_for_paths(
    paths: List[str],
    state_store: Optional[Any] = None,
    catalog: Optional[Any] = None,
    pinned_sources: Optional[Dict[str, str]] = None,
) -> Dict[str, List[int]]:
    """Resolve paths to the exact minimal set of SunSpec models per device type.

    Evaluates candidate models for each path and runs Set Cover Optimization.
    """
    from .mapping import MappingRegistry
    reg = MappingRegistry.get_instance()

    # Bucket paths by device type
    dev_paths: Dict[str, List[str]] = {}
    for p in paths:
        if not p or not isinstance(p, str):
            continue
        clean_p = p.strip()
        if ":" in clean_p:
            _, clean_p = clean_p.split(":", 1)
            clean_p = clean_p.strip()
        parts = clean_p.split(".")
        d_type = parts[0].strip().lower()
        dev_paths.setdefault(d_type, []).append(clean_p)

    result: Dict[str, List[int]] = {}

    for d_type, p_list in dev_paths.items():
        solver_items: Dict[str, Set[Union[int, str]]] = {}
        fixed_models: Set[int] = set()

        for p in p_list:
            parts = p.split(".")
            if len(parts) == 1 or parts[1] == "*":
                # Wildcard: all models for device type
                if state_store and hasattr(state_store, "devices"):
                    for dev in state_store.devices.values():
                        if dev.device_type == d_type:
                            fixed_models.update(dev.supported_models)
                continue

            sub = parts[1]

            # Direct numeric model (e.g. 'inverter.102' or 'inverter.model_102')
            if sub.isdigit():
                fixed_models.add(int(sub))
                continue
            if sub.startswith("model_") and sub[6:].isdigit():
                fixed_models.add(int(sub[6:]))
                continue

            # Compound or unified concept path
            if sub in ("compound", "concept", "unified") and len(parts) >= 3:
                c_id = parts[2]
                cand_set: Set[Union[int, str]] = set()

                m_def = reg.get_by_id(c_id)
                if m_def:
                    for cand_key in [m_def.modbus_field] + list(m_def.modbus_candidates):
                        if cand_key:
                            c_parts = cand_key.split(".")
                            if len(c_parts) >= 2:
                                grp = c_parts[1]
                                if grp.isdigit():
                                    cand_set.add(int(grp))
                                elif grp.startswith("model_") and grp[6:].isdigit():
                                    cand_set.add(int(grp[6:]))
                                elif state_store and hasattr(state_store, "devices"):
                                    for dev in state_store.devices.values():
                                        if dev.device_type == d_type and cand_key in dev.fields:
                                            mid = dev.fields[cand_key].model_id
                                            if mid:
                                                cand_set.add(mid)

                # Also check canonical concept synonyms
                matched_concept = find_canonical_concept(d_type, c_id, None) or (c_id if c_id in CANONICAL_SYNONYMS.get(d_type, {}) else None)
                if matched_concept:
                    syn_names = CANONICAL_SYNONYMS[d_type][matched_concept]["names"]
                    if state_store and hasattr(state_store, "devices"):
                        for dev in state_store.devices.values():
                            if dev.device_type == d_type:
                                for f in dev.fields.values():
                                    if f.name.lower() in syn_names and f.model_id:
                                        cand_set.add(f.model_id)

                if cand_set:
                    solver_items[p] = cand_set
                continue

            # Specific point (e.g. 'inverter.inverter.Hz' or 'inverter.live.grid_power_w')
            found_field_models: Set[int] = set()
            pt_name = parts[-1].lower()

            if state_store and hasattr(state_store, "devices"):
                for dev in state_store.devices.values():
                    if dev.device_type == d_type:
                        # Check canonical synonyms for pt_name
                        matched_c = find_canonical_concept(d_type, pt_name, None)
                        syn_names = CANONICAL_SYNONYMS[d_type][matched_c]["names"] if matched_c else {pt_name}

                        for f_key, f in dev.fields.items():
                            if (f.name.lower() in syn_names or f.key == p) and f.model_id:
                                found_field_models.add(f.model_id)

            if found_field_models:
                solver_items[p] = found_field_models
            else:
                from .poller import resolve_subgroup_to_model_id
                mid = resolve_subgroup_to_model_id(
                    d_type,
                    sub,
                    catalog=catalog,
                    state_store=state_store,
                    exact_path=p,
                )
                if mid is not None:
                    fixed_models.add(mid)

        # Run Set Cover solver for this device type
        opt = solve_minimal_model_set(solver_items, allow_mqtt=False)
        resolved = sorted(list(set(opt.minimal_models) | fixed_models))
        if resolved:
            result[d_type] = resolved

    return result
