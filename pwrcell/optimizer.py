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

from .catalog import infer_ha_classes, is_scale_factor_point

logger = logging.getLogger(__name__)


def clean_unit(unit: Optional[str]) -> str:
    """Normalize unit string for fuzzy matching across models."""
    if not unit:
        return ""
    u = str(unit).replace("°", "").replace("Deg", "").replace("deg", "").replace("_", " ").strip()
    mapping = {
        "c": "C",
        "celsius": "C",
        "f": "F",
        "fahrenheit": "F",
        "w": "W",
        "watt": "W",
        "watts": "W",
        "kw": "kW",
        "kilowatt": "kW",
        "kilowatts": "kW",
        "wh": "Wh",
        "watt-hour": "Wh",
        "watt-hours": "Wh",
        "watt hour": "Wh",
        "watt hours": "Wh",
        "kwh": "kWh",
        "v": "V",
        "volt": "V",
        "volts": "V",
        "a": "A",
        "amp": "A",
        "amps": "A",
        "ampere": "A",
        "amperes": "A",
        "hz": "Hz",
        "hertz": "Hz",
        "pct": "%",
        "percent": "%",
        "%": "%",
        "%whrtg": "%",
        "sec": "s",
        "second": "s",
        "seconds": "s",
        "s": "s",
        "va": "VA",
        "var": "VAr",
        "vars": "VAr",
    }
    return mapping.get(u.lower(), u)


class _CanonicalSynonymsProxy(dict):
    """Dynamic proxy for CANONICAL_SYNONYMS that resolves dynamically from MappingRegistry."""
    def _data(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        from .mapping import MappingRegistry
        return MappingRegistry.get_instance().get_canonical_synonyms_dict()

    class _DevProxy(dict):
        def __init__(self, data: dict, all_data: dict):
            super().__init__(data)
            self._all_data = all_data

        def __getitem__(self, k):
            if k in self:
                return super().__getitem__(k)
            for d in self._all_data.values():
                if k in d:
                    return d[k]
            raise KeyError(k)

        def get(self, k, default=None):
            if k in self:
                return super().get(k)
            for d in self._all_data.values():
                if k in d:
                    return d[k]
            return default

    def get(self, k, default=None):
        data = self._data()
        if k in data:
            return self._DevProxy(data[k], data)
        return default

    def __getitem__(self, k):
        data = self._data()
        return self._DevProxy(data.get(k, {}), data)

    def __contains__(self, k):
        return k in self._data()

    def items(self):
        return self._data().items()

    def keys(self):
        return self._data().keys()

    def values(self):
        return self._data().values()

    def __len__(self):
        return len(self._data())


CANONICAL_SYNONYMS = _CanonicalSynonymsProxy()


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


# Default tie-breaking weights favoring native REbus vendor models (>= 64000) over standard models (< 1000)
_DEFAULT_FAVORED_MODELS: Dict[int, float] = {
    64208: 0.8,
    64252: 0.8,
    64207: 0.8,
    404: 0.85,
    102: 0.9,
    802: 0.9,
}


def get_default_favored_models() -> Dict[int, float]:
    """Default tie-breaking model weights favoring native REbus vendor models."""
    return dict(_DEFAULT_FAVORED_MODELS)


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
    default_favored = get_default_favored_models()

    def get_weight(m: int) -> float:
        return weights.get(m, default_favored.get(m, 1.0))

    assignments: Dict[str, Union[int, str]] = {}
    modbus_items: Dict[str, Set[int]] = {}

    # 1. Process items pinned to MQTT or satisfied by MQTT without user Modbus pinning
    for item_key, candidates in items.items():
        user_pin = pinned.get(item_key)
        if user_pin == "MQTT":
            assignments[item_key] = "MQTT"
            continue
        if user_pin is None and allow_mqtt and "MQTT" in candidates:
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
                "mqtt_covered_count": sum(1 for v in assignments.values() if v == "MQTT"),
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


from .concept import (
    ConceptSource,
    ConceptSource as UnifiedSource,
    ConceptView,
    ConceptView as UnifiedFieldGroup,
)


def find_canonical_concept(dev_type: str, point_name: str, units: Optional[str]) -> Optional[str]:
    """Match point_name and unit against canonical concept definitions."""
    from .mapping import MappingRegistry
    m = MappingRegistry.get_instance().find_concept(dev_type, point_name, units)
    if m:
        return m.id
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
    if len(parts) >= 3:
        target_dev_type = parts[0].lower()
        if getattr(f, "device_type", None) and target_dev_type != f.device_type.lower():
            return False
    return True


def group_device_fields(
    dev: Any,
    mapping_registry: Optional[Any] = None,
    ha_selected_keys: Optional[Set[str]] = None,
    preferred_sources: Optional[Dict[str, str]] = None,
    custom_groupings: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, str]] = None,
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
    field_transforms = custom_groupings.get("field_transforms", {}) or {}
    custom_concepts = custom_groupings.get("custom_concepts", {}) or {}

    dev_type = getattr(dev, "device_type", "inverter")
    dev_sn = getattr(dev, "serial_number", "")
    all_fields = dict(getattr(dev, "fields", {}))

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

    def _field_priority(item):
        k, _ = item
        qk = f"{dev_sn}:{k}" if dev_sn else k
        if qk in overrides or k in overrides:
            return 0
        return 1

    sorted_fields = sorted(all_fields.items(), key=_field_priority)
    for f_key, f in sorted_fields:
        # Check user custom grouping overrides first
        qual_key = f"{dev_sn}:{f_key}" if dev_sn else f_key
        has_override = qual_key in overrides or f_key in overrides
        target_concept = overrides.get(qual_key, overrides.get(f_key)) if has_override else None

        if not has_override and overrides:
            fk_parts = f_key.split(".")
            fk_dev = fk_parts[0] if fk_parts else ""
            fk_point = fk_parts[-1] if fk_parts else ""
            for k, v in overrides.items():
                k_sn = k.split(":", 1)[0] if ":" in k else ""
                k_part = k.split(":", 1)[1] if ":" in k else k
                if k_sn and dev_sn and k_sn.strip().upper() != dev_sn.strip().upper():
                    continue
                kp_parts = k_part.split(".")
                kp_dev = kp_parts[0] if kp_parts else ""
                kp_point = kp_parts[-1] if kp_parts else ""
                if (
                    fk_dev
                    and kp_dev
                    and fk_dev.lower() == kp_dev.lower()
                    and fk_point
                    and kp_point
                    and fk_point.lower() == kp_point.lower()
                ):
                    has_override = True
                    target_concept = v
                    break

        if has_override:
            if target_concept is None or str(target_concept).strip().lower() in ("", "null", "none", "standalone", "ungrouped"):
                c_id = f"{dev_type}.standalone.{f.name.lower()}_{getattr(f, 'model_id', 'raw')}"
                if c_id not in concept_metadata:
                    u_d_class = f.ha_hint.device_class if f.ha_hint else None
                    u_s_class = f.ha_hint.state_class if f.ha_hint else None
                    if not u_d_class and not u_s_class:
                        u_d_class, u_s_class = infer_ha_classes(units=f.units, name=f.name)
                    concept_metadata[c_id] = {
                        "id": c_id,
                        "concept_key": f"{f.name.lower()}_{getattr(f, 'model_id', 'raw')}",
                        "name": f.name,
                        "label": f.label or f.name,
                        "description": f.description,
                        "units": f.units,
                        "ha_platform": f.ha_hint.platform if f.ha_hint else ("sensor" if not f.is_writable else "number"),
                        "ha_device_class": u_d_class,
                        "ha_state_class": u_s_class,
                        "is_custom_override": True,
                    }
                concept_buckets.setdefault(c_id, []).append((f_key, f, None))
                assigned_field_keys.add(f_key)
                continue
            else:
                target_key = str(target_concept).strip()
                if target_key.startswith(f"{dev_type}.concept."):
                    target_key = target_key[len(f"{dev_type}.concept."):]
                elif target_key.startswith(f"{dev_type}."):
                    target_key = target_key[len(f"{dev_type}."):]
                c_id = f"{dev_type}.concept.{target_key}"
                c_meta = custom_concepts.get(target_key, {})
                c_units = c_meta.get("units", f.units)
                c_d_class = c_meta.get("ha_device_class")
                c_s_class = c_meta.get("ha_state_class")
                if not c_d_class and not c_s_class:
                    c_d_class, c_s_class = infer_ha_classes(units=c_units, name=target_key)
                if c_id not in concept_metadata:
                    matching_f = next((df for df in dev.fields.values() if df.name.lower() == target_key.lower()), None)
                    resolved_label = c_meta.get("label") or (matching_f.label if matching_f else target_key.replace("_", " ").title())
                    concept_metadata[c_id] = {
                        "id": c_id,
                        "concept_key": target_key,
                        "name": target_key,
                        "label": resolved_label,
                        "description": c_meta.get("description", f.description),
                        "units": c_units,
                        "ha_platform": c_meta.get("ha_platform", f.ha_hint.platform if f.ha_hint else "sensor"),
                        "ha_device_class": c_d_class,
                        "ha_state_class": c_s_class,
                        "is_custom_override": True,
                    }
                is_mqtt = getattr(f.source, "value", str(f.source)) == "MQTT_PUSH" or "live." in f_key
                c_trans = c_meta.get("transform")
                
                # Check explicit field transform first
                if qual_key in field_transforms or f_key in field_transforms:
                    raw_tf = field_transforms.get(qual_key, field_transforms.get(f_key))
                    f_trans = None if raw_tf in (None, "none", "") else raw_tf
                elif c_trans and c_trans != "none":
                    # Concept negation applies to Modbus/candidate fields, never to MQTT reference stream
                    if is_mqtt and c_trans == "negate":
                        f_trans = None
                    else:
                        f_trans = c_trans
                else:
                    f_trans = None

                concept_buckets.setdefault(c_id, []).append((f_key, f, f_trans))
                assigned_field_keys.add(f_key)
                continue

        # Check if explicitly ungrouped in telemetry_mappings.yaml
        is_reg_ungrouped = bool(getattr(reg, "is_field_ungrouped", lambda *a, **kw: False)(f_key, f, dev_type))
        if is_reg_ungrouped:
            c_id = f"{dev_type}.standalone.{f.name.lower()}_{getattr(f, 'model_id', 'raw')}"
            if c_id not in concept_metadata:
                u_d_class = f.ha_hint.device_class if f.ha_hint else None
                u_s_class = f.ha_hint.state_class if f.ha_hint else None
                if not u_d_class and not u_s_class:
                    u_d_class, u_s_class = infer_ha_classes(units=f.units, name=f.name)
                concept_metadata[c_id] = {
                    "id": c_id,
                    "concept_key": f"{f.name.lower()}_{getattr(f, 'model_id', 'raw')}",
                    "name": f.name,
                    "label": f"{f.label or f.name} (Ungrouped)",
                    "description": f.description,
                    "units": f.units,
                    "ha_platform": f.ha_hint.platform if f.ha_hint else ("sensor" if not f.is_writable else "number"),
                    "ha_device_class": u_d_class,
                    "ha_state_class": u_s_class,
                    "is_custom_override": False,
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
                if any(f_key == mf or f.name == mf.split(".")[-1] for mf in m.mqtt_fields):
                    is_match = True
                elif any(f_key == mbf or _field_matches_modbus_target(f, mbf) for mbf in m.modbus_fields):
                    is_match = True
                    transform = m.transform

                if is_match:
                    if qual_key in field_transforms or f_key in field_transforms:
                        transform = field_transforms.get(qual_key, field_transforms.get(f_key))
                    c_id = f"{dev_type}.concept.{m.id}"
                    if c_id not in concept_metadata:
                        concept_metadata[c_id] = {
                            "id": c_id,
                            "concept_key": m.id,
                            "name": m.id,
                            "label": m.label,
                            "description": m.description,
                            "units": m.unit or f.units,
                            "ha_platform": m.ha_platform,
                            "ha_device_class": m.ha_device_class,
                            "ha_state_class": m.ha_state_class,
                            "is_custom_override": False,
                        }
                    concept_buckets.setdefault(c_id, []).append((f_key, f, transform))
                    assigned_field_keys.add(f_key)
                    assigned = True
                    break

        if assigned:
            continue

        # Check if an unmapped field belongs to an existing custom concept bucket on this device
        cand_keys = [
            f"{f.name.lower()}_{getattr(f, 'model_id', 'raw')}",
            f.name.lower(),
            f.name,
        ]
        matching_c_id = next(
            (f"{dev_type}.concept.{ck}" for ck in cand_keys if f"{dev_type}.concept.{ck}" in concept_buckets),
            None
        )
        if matching_c_id:
            concept_buckets[matching_c_id].append((f_key, f, None))
            assigned_field_keys.add(f_key)
            continue

        active_target_concepts = {
            str(v).strip()
            for k, v in overrides.items()
            if (not dev_sn or k.startswith(f"{dev_sn}:")) and v and str(v).strip().lower() not in ("", "null", "none", "standalone", "ungrouped")
        }
        matching_target_key = next((ck for ck in cand_keys if ck in active_target_concepts), None)
        if matching_target_key:
            c_id = f"{dev_type}.concept.{matching_target_key}"
            c_meta = custom_concepts.get(matching_target_key, {})
            if c_id not in concept_metadata:
                resolved_label = c_meta.get("label") or f.label or matching_target_key.replace("_", " ").title()
                c_units = c_meta.get("units", f.units)
                c_d_class = c_meta.get("ha_device_class")
                c_s_class = c_meta.get("ha_state_class")
                if not c_d_class and not c_s_class:
                    c_d_class, c_s_class = infer_ha_classes(units=c_units, name=matching_target_key)
                concept_metadata[c_id] = {
                    "id": c_id,
                    "concept_key": matching_target_key,
                    "name": matching_target_key,
                    "label": resolved_label,
                    "description": c_meta.get("description", f.description),
                    "units": c_units,
                    "ha_platform": c_meta.get("ha_platform", f.ha_hint.platform if f.ha_hint else "sensor"),
                    "ha_device_class": c_d_class,
                    "ha_state_class": c_s_class,
                    "is_custom_override": True,
                }
            concept_buckets.setdefault(c_id, []).append((f_key, f, None))
            assigned_field_keys.add(f_key)
            continue

        # If auto-grouping heuristics are disabled, every unmapped field is strictly standalone
        if not getattr(reg, "auto_group_heuristics", True):
            c_id = f"{dev_type}.standalone.{f.name.lower()}_{getattr(f, 'model_id', 'raw')}"
            if c_id not in concept_metadata:
                u_d_class = f.ha_hint.device_class if f.ha_hint else None
                u_s_class = f.ha_hint.state_class if f.ha_hint else None
                if not u_d_class and not u_s_class:
                    u_d_class, u_s_class = infer_ha_classes(units=f.units, name=f.name)
                concept_metadata[c_id] = {
                    "id": c_id,
                    "concept_key": f"{f.name.lower()}_{getattr(f, 'model_id', 'raw')}",
                    "name": f.name,
                    "label": f.label or f.name,
                    "description": f.description,
                    "units": f.units,
                    "ha_platform": f.ha_hint.platform if f.ha_hint else ("sensor" if not f.is_writable else "number"),
                    "ha_device_class": u_d_class,
                    "ha_state_class": u_s_class,
                    "is_custom_override": False,
                }
            concept_buckets.setdefault(c_id, []).append((f_key, f, None))
            assigned_field_keys.add(f_key)
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
            or not getattr(reg, "auto_group_heuristics", True)
            or norm_name in {
                "modena", "actcrv", "ncrv", "wintms", "rmptms", "rvrttms", "crvnum",
                "readonly", "subgroup", "npts",
            }
        )
        m_id = getattr(f, "model_id", None)
        if is_model_specific and m_id:
            auto_c_id = f"{dev_type}.m{m_id}.concept.{norm_name}"
            c_key = f"{norm_name}_m{m_id}"
            c_label = f"{f.label} (M{m_id})" if f.label else f.name
        else:
            auto_c_id = f"{dev_type}.concept.{norm_name}"
            c_key = norm_name
            c_label = f.label

        if auto_c_id not in concept_metadata:
            f_d_class = f.ha_hint.device_class if f.ha_hint else None
            f_s_class = f.ha_hint.state_class if f.ha_hint else None
            if not f_d_class and not f_s_class:
                f_d_class, f_s_class = infer_ha_classes(units=f.units, name=f.name)
            concept_metadata[auto_c_id] = {
                "id": auto_c_id,
                "concept_key": c_key,
                "name": f.name,
                "label": c_label,
                "description": f.description,
                "units": f.units,
                "ha_platform": f.ha_hint.platform if f.ha_hint else ("sensor" if not f.is_writable else "number"),
                "ha_device_class": f_d_class,
                "ha_state_class": f_s_class,
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
                    device_sn=dev_sn,
                    last_updated=getattr(f, "last_updated", None) or getattr(f, "timestamp", None),
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

        grp_src_ts = [s.last_updated for s in sources if s.last_updated]
        latest_grp_ts = max(grp_src_ts) if grp_src_ts else 0.0

        grp_units = meta.get("units") or next((s.units for s in sources if s.units), None)

        from .bounds import get_custom_bounds
        c_grp_bounds = get_custom_bounds(c_id, device_sn=dev_sn)
        if c_grp_bounds:
            if not grp_bounds:
                grp_bounds = {
                    "category": "numeric",
                    "point_type": "float32",
                    "units": grp_units,
                    "step": 1,
                }
            else:
                grp_bounds = dict(grp_bounds)
            if c_grp_bounds.get("min_value") is not None:
                grp_bounds["min_value"] = c_grp_bounds["min_value"]
                grp_bounds["scaled_min"] = c_grp_bounds["min_value"]
            if c_grp_bounds.get("max_value") is not None:
                grp_bounds["max_value"] = c_grp_bounds["max_value"]
                grp_bounds["scaled_max"] = c_grp_bounds["max_value"]
            if c_grp_bounds.get("step") is not None:
                grp_bounds["step"] = c_grp_bounds["step"]
            grp_bounds["is_custom"] = True

        group = UnifiedFieldGroup(
            id=c_id,
            concept_key=meta.get("concept_key", c_id.split(".")[-1]),
            device_sn=dev_sn,
            device_type=dev_type,
            name=meta.get("name", c_id.split(".")[-1]),
            label=meta.get("label", c_id.split(".")[-1]),
            description=meta.get("description", ""),
            units=grp_units,
            sources=sources,
            preferred_source_key=pref_key,
            is_writable=is_grp_writable,
            ha_platform=meta.get("ha_platform", "sensor"),
            ha_device_class=meta.get("ha_device_class") or infer_ha_classes(units=grp_units, name=meta.get("name", c_id.split(".")[-1]), platform=meta.get("ha_platform", "sensor"))[0],
            ha_state_class=meta.get("ha_state_class") or infer_ha_classes(units=grp_units, name=meta.get("name", c_id.split(".")[-1]), platform=meta.get("ha_platform", "sensor"))[1],
            is_selected=grp_selected,
            bounds=grp_bounds,
            point_type=next((s.point_type for s in sources if s.point_type), None),
            is_bitfield=any(s.is_bitfield for s in sources),
            is_enum=any(s.is_enum for s in sources),
            symbols=next((s.symbols for s in sources if s.symbols), None),
            bitmask_flags=next((s.bitmask_flags for s in sources if s.bitmask_flags), None),
            latest_updated=latest_grp_ts,
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
        from .ha import get_effective_ha_category
        group.ha_category = get_effective_ha_category(group, dev, category_overrides=category_overrides)
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
        polled_models = set(opt_res.minimal_models)
        assignments = opt_res.assignments

    # 4. Assign active sources and optimal flags
    for g in groups:
        for s in g.sources:
            s.is_optimal = False
            s.is_pinned = False
            s.is_primary = False

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
            active_src.is_primary = True
            g.active_source_key = active_src.field_key
            g.primary_source_key = active_src.field_key
            g.latest_value = active_src.value
            g.raw_value = active_src.raw_value
            g.latest_source = active_src.source_id
            if active_src.last_updated:
                g.latest_updated = active_src.last_updated
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

        # Also identify the optimal SunSpec candidate among Modbus sources for comparison/fallback
        mb_sources = [s for s in g.sources if s.source_type != "MQTT"]
        if mb_sources and not any(s.is_optimal for s in mb_sources):
            favored = get_default_favored_models()
            best_mb = min(
                mb_sources,
                key=lambda s: (0 if s.model_id in polled_models else 1, favored.get(s.model_id or 0, 1.0))
            )
            best_mb.is_optimal = True

        # Compute delta and match percentage across sources
        num_vals = [s.value for s in g.sources if isinstance(s.value, (int, float))]
        if len(num_vals) >= 2:
            g.delta = abs(num_vals[0] - num_vals[1])
            denom = max(abs(num_vals[0]), abs(num_vals[1]), 1.0)
            g.match_pct = max(0.0, 100.0 - (g.delta / denom * 100.0))
            if g.delta == 0:
                g.status = "EXACT"
            elif g.match_pct >= 95.0:
                g.status = "CLOSE"
            else:
                g.status = "DIVERGENT"
                g.is_discrepant = True
                g.discrepancy_reason = f"Divergence detected across sources: {num_vals[0]} vs {num_vals[1]}"
        elif len(g.sources) > 1:
            g.status = "PARTIALLY_POLLED"
        else:
            g.status = "SINGLE_SOURCE"

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
                    for cand_key in m_def.modbus_fields:
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
