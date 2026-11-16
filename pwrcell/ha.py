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
import re
from typing import Any, Dict, Iterable, List, Optional, Set
import yaml

from . import __version__
from .catalog import (
    get_suggested_precision,
    group_wildcard_matches_field_key,
    is_diagnostic_point,
    is_group_wildcard_key,
    normalize_ha_unit,
    wildcardize_group_field_key,
)
from .config import data_dir, is_addon_data_env
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

def _load_ha_security_config() -> tuple[Set[str], Set[str]]:
    """Load controllable allowlist and excluded options from HA config or default seed."""
    default_writable = {
        "system_mode", "SysMd", "SoCRsvMin", "SoCRsvMax",
        "SoCMax", "SoCMin", "WChaRteMax", "WDisChaRteMax",
        "AChaMax", "ADisChaMax",
    }
    default_excluded = {"SAFETY_SHUTDOWN"}
    try:
        import yaml
        for p in (get_default_ha_config_path(), get_default_seed_config_path()):
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if isinstance(data, dict):
                    ctrl = data.get("controllable_fields")
                    excl = data.get("excluded_select_options")
                    w_set = set(ctrl) if isinstance(ctrl, list) else default_writable
                    e_set = set(excl) if isinstance(excl, list) else default_excluded
                    return w_set, e_set
    except Exception:
        pass
    return default_writable, default_excluded


HA_WRITABLE_ALLOWLIST, HA_EXCLUDED_SELECT_OPTIONS = _load_ha_security_config()


def is_ha_writable_allowed(field: Any) -> bool:
    """Return True if the field is both writable and in the Home Assistant writable allow-list."""
    from .safety import is_mutation_blocked
    if is_mutation_blocked(field):
        return False
    if not getattr(field, "is_writable", False):
        return False
    if field.is_compound:
        mapping_id = getattr(field, "mapping_id", None) or getattr(field, "name", "")
        return mapping_id in HA_WRITABLE_ALLOWLIST
    pt_name = getattr(field, "name", "") or str(getattr(field, "key", "")).split(".")[-1]
    f_key = getattr(field, "key", "")
    active_fk = getattr(field, "active_source_key", None)
    if (
        pt_name in HA_WRITABLE_ALLOWLIST
        or f_key in HA_WRITABLE_ALLOWLIST
        or (active_fk and active_fk in HA_WRITABLE_ALLOWLIST)
    ):
        return True
    try:
        from .bounds import get_custom_bounds
        if get_custom_bounds(f_key, getattr(field, "device_sn", None), pt_name) or (
            active_fk and get_custom_bounds(active_fk, getattr(field, "device_sn", None), pt_name)
        ):
            return True
    except Exception:
        pass
    return False


def _filter_ha_options(options: Optional[List[str]]) -> Optional[List[str]]:
    if not options:
        return options
    return [opt for opt in options if opt not in HA_EXCLUDED_SELECT_OPTIONS]


def get_default_seed_config_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_HA_DEFAULT_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_HA_DEFAULT_CONFIG_FILE
    return repo_root / DEFAULT_HA_DEFAULT_CONFIG_FILE


def get_default_ha_config_path() -> Path:
    if is_addon_data_env():
        return data_dir() / DEFAULT_HA_CONFIG_FILE
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config" / DEFAULT_HA_CONFIG_FILE).exists():
        return repo_root / "config" / DEFAULT_HA_CONFIG_FILE
    if (repo_root / DEFAULT_HA_CONFIG_FILE).exists():
        return repo_root / DEFAULT_HA_CONFIG_FILE
    if (repo_root / "config").exists():
        return repo_root / "config" / DEFAULT_HA_CONFIG_FILE
    return data_dir() / DEFAULT_HA_CONFIG_FILE


def get_matching_selected_entries(
    field_key: str,
    device_sn: Optional[str],
    selected_keys: Iterable[str],
    mqtt_key: Optional[str] = None,
    candidate_keys: Optional[Iterable[str]] = None,
) -> Set[str]:
    """Return the subset of entries in `selected_keys` that select `field_key` on `device_sn`.

    Supports device-scoped ('<sn>:<key>'), legacy global keys, and sub-group '*' wildcards.
    """
    if not selected_keys:
        return set()
    s_set = selected_keys if isinstance(selected_keys, set) else set(selected_keys)

    check_keys = [field_key]
    if ".compound." in field_key:
        check_keys.append(field_key.replace(".compound.", ".concept."))
    elif ".concept." in field_key:
        check_keys.append(field_key.replace(".concept.", ".compound."))
    if mqtt_key:
        check_keys.append(mqtt_key)
    if candidate_keys:
        check_keys.extend(k for k in candidate_keys if k)

    wildcard_check_keys: List[str] = []
    for k in check_keys:
        wk = wildcardize_group_field_key(k)
        if wk and wk not in wildcard_check_keys:
            wildcard_check_keys.append(wk)

    matched: Set[str] = set()
    sn_upper = device_sn.strip().upper() if device_sn else ""
    prefix = f"{sn_upper}:" if sn_upper else ""

    for k in check_keys:
        if prefix and f"{prefix}{k}" in s_set:
            matched.add(f"{prefix}{k}")
        if k in s_set:
            matched.add(k)

    for wk in wildcard_check_keys:
        if prefix and f"{prefix}{wk}" in s_set:
            matched.add(f"{prefix}{wk}")
        if wk in s_set:
            matched.add(wk)

    # Support partial nested wildcards (e.g. 'Crv.1.Pt.*.V') present in selected_keys
    if any(".*." in sk for sk in s_set):
        for sk in s_set:
            if ".*." not in sk:
                continue
            for k in check_keys:
                concrete_q = f"{prefix}{k}" if prefix else k
                if group_wildcard_matches_field_key(sk, concrete_q):
                    matched.add(sk)
                    break

    return matched


def is_field_selected(
    field_key: str,
    device_sn: Optional[str],
    selected_keys: List[str] | Set[str],
    mqtt_key: Optional[str] = None,
    candidate_keys: Optional[Iterable[str]] = None,
) -> bool:
    """Check if a field is selected, supporting device-scoped, legacy global, and sub-group '*' wildcard keys."""
    if not selected_keys:
        return False
    s_set = selected_keys if isinstance(selected_keys, set) else set(selected_keys)

    check_keys = [field_key]
    if ".compound." in field_key:
        check_keys.append(field_key.replace(".compound.", ".concept."))
    elif ".concept." in field_key:
        check_keys.append(field_key.replace(".concept.", ".compound."))
    if mqtt_key:
        check_keys.append(mqtt_key)
    if candidate_keys:
        check_keys.extend(k for k in candidate_keys if k)

    sn_upper = device_sn.strip().upper() if device_sn else ""
    prefix = f"{sn_upper}:" if sn_upper else ""

    for k in check_keys:
        if prefix and f"{prefix}{k}" in s_set:
            return True
        if k in s_set:
            return True
        wk = wildcardize_group_field_key(k)
        if wk:
            if prefix and f"{prefix}{wk}" in s_set:
                return True
            if wk in s_set:
                return True

    if any(".*." in sk for sk in s_set):
        for sk in s_set:
            if ".*." not in sk:
                continue
            for k in check_keys:
                concrete_q = f"{prefix}{k}" if prefix else k
                if group_wildcard_matches_field_key(sk, concrete_q):
                    return True
    return False


_HA_CONFIG_CACHE: Dict[str, Dict[str, Any]] = {}


def clear_ha_config_cache() -> None:
    """Clear in-memory cache of HA config files."""
    _HA_CONFIG_CACHE.clear()


def _read_ha_config_doc(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"selected_fields": [], "category_overrides": {}}
    p_str = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
        cached = _HA_CONFIG_CACHE.get(p_str)
        if cached and cached.get("mtime") == mtime:
            return {
                "selected_fields": list(cached["selected_fields"]),
                "category_overrides": dict(cached["category_overrides"]),
            }
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw_fields = data.get("selected_fields")
        fields = (
            [str(x).strip() for x in raw_fields if x is not None and str(x).strip()]
            if raw_fields
            else []
        )
        raw_ov = data.get("category_overrides") or data.get("entity_categories") or {}
        overrides = (
            {str(k).strip(): str(v).strip().lower() for k, v in raw_ov.items() if k and v}
            if isinstance(raw_ov, dict)
            else {}
        )
        _HA_CONFIG_CACHE[p_str] = {
            "mtime": mtime,
            "selected_fields": list(fields),
            "category_overrides": dict(overrides),
        }
        return {"selected_fields": fields, "category_overrides": overrides}
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return {"selected_fields": [], "category_overrides": {}}


def load_ha_config(
    config_path: Optional[Path | str] = None,
    allow_default_seed: bool = True,
) -> List[str]:
    """Load list of selected field keys from ha_config.yaml.

    If the file does not exist or contains no selected fields, and allow_default_seed is True,
    falls back to ha_default_config.yaml as an initial seed.
    """
    path = Path(config_path) if config_path else get_default_ha_config_path()
    doc = _read_ha_config_doc(path)
    fields = list(doc.get("selected_fields") or [])

    if fields:
        logger.debug("Loaded %d selected HA field keys from %s", len(fields), path)
    elif allow_default_seed:
        seed_path = get_default_seed_config_path()
        if seed_path.exists():
            seed_doc = _read_ha_config_doc(seed_path)
            fields = list(seed_doc.get("selected_fields") or [])
            logger.debug(
                "HA config %s missing/empty; seeded %d default keys from %s",
                path,
                len(fields),
                seed_path,
            )
    else:
        logger.debug("HA config %s has 0 selected fields (allow_default_seed=False)", path)

    return fields


_LEGACY_CONCEPT_REMAP: Dict[str, str] = {
    "inverter.concept.ac_frequency": "inverter.inverter.Hz",
    "inverter.concept.grid_exported_energy_wh": "inverter.compound.grid_exported_energy",
    "inverter.concept.grid_imported_energy_wh": "inverter.compound.grid_imported_energy",
    "inverter.concept.inverter_output_power": "inverter.compound.inverter_output_power",
    "inverter.concept.inverter_output_power_w": "inverter.compound.inverter_output_power",
    "inverter.concept.inverter_state": "inverter.compound.inverter_state",
    "inverter.live.inverter_state_name": "inverter.compound.inverter_state",
    "inverter.concept.a": "inverter.inverter.A",
    "inverter.concept.aphb": "inverter.inverter.AphB",
    "battery.concept.battery_voltage": "battery.compound.battery_voltage",
    "battery.concept.battery_soh": "battery.compound.battery_soh",
    "battery.live.state_of_health": "battery.compound.battery_soh",
    "pv_link.concept.iin": "pv_link.string_combiner.DCA",
}


def _is_raw_field_excluded_from_compound(
    field_key: str,
    concept_id: str,
    device_sn: Optional[str] = None,
    reg: Optional[Any] = None,
    custom_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True if a raw field has been ungrouped or excluded from a compound group."""
    from .mapping import MappingRegistry
    from .grouping import is_field_excluded_from_mapping, load_custom_groupings

    reg = reg or MappingRegistry.get_instance()
    if reg.is_field_ungrouped(field_key):
        return True
    custom_data = custom_data if custom_data is not None else load_custom_groupings()
    if device_sn:
        if is_field_excluded_from_mapping(device_sn, field_key, concept_id, custom_data):
            return True
    else:
        overrides = custom_data.get("field_overrides", {}) or {}
        clean_fk = field_key.strip().lower()
        clean_cid = (concept_id or "").strip().lower()
        for ov_k, ov_tgt in overrides.items():
            ov_field = ov_k.split(":", 1)[1] if ":" in ov_k else ov_k
            if ov_field.strip().lower() == clean_fk:
                if ov_tgt is None or str(ov_tgt).strip().lower() in ("", "null", "none", "standalone", "ungrouped"):
                    return True
                if clean_cid and str(ov_tgt).strip().lower() != clean_cid:
                    return True
    return False


def _resolve_standalone_or_orphan_slug(
    dev_type: str,
    slug: str,
    state_store: Optional[StateStore] = None,
    sn_hint: Optional[str] = None,
) -> Optional[str]:
    """Resolve a standalone slug (e.g. 'socmin_802' or 'load_power_w') back to its canonical StateField.key."""
    clean_slug = (slug or "").strip()
    if clean_slug.endswith("_None"):
        clean_slug = clean_slug[:-5]
    if not clean_slug or clean_slug.lower() == "none":
        return None

    pt_lower = clean_slug.lower()
    mid_int: Optional[int] = None
    if "_" in clean_slug:
        prefix_part, suffix_part = clean_slug.rsplit("_", 1)
        if suffix_part.isdigit() and prefix_part:
            pt_lower = prefix_part.lower()
            mid_int = int(suffix_part)

    # 1. Inspect live fields on matching devices in state_store
    if state_store and hasattr(state_store, "devices"):
        candidate_devs = []
        if sn_hint:
            clean_sn = sn_hint.strip().upper()
            for d in state_store.devices.values():
                if d.serial_number.strip().upper() == clean_sn:
                    candidate_devs.append(d)
        if not candidate_devs:
            candidate_devs = [d for d in state_store.devices.values() if d.device_type == dev_type]

        for dev in candidate_devs:
            full_lower = clean_slug.lower()
            for f in dev.fields.values():
                f_sub = f.key.split(".", 1)[-1].replace(".", "_").lower() if "." in f.key else f.key.lower()
                if f_sub == full_lower:
                    return f.key
                f_gp = getattr(f, "group_path", None)
                if f_gp:
                    gp_slug = re.sub(r"[^a-z0-9]+", "_", f_gp.lower()).strip("_")
                    pt_slug = re.sub(r"[^a-z0-9]+", "_", (f.name or "").lower()).strip("_")
                    grp_ck = f"m{f.model_id}_{gp_slug}_{pt_slug}" if f.model_id is not None else f"{gp_slug}_{pt_slug}"
                    if full_lower == grp_ck:
                        return f.key
            if mid_int is not None:
                for f in dev.fields.values():
                    if f.model_id == mid_int and not getattr(f, "group_path", None) and (f.name or "").lower() == pt_lower:
                        return f.key
            # Match un-indexed / MQTT fields or full point name without model suffix
            for f in dev.fields.values():
                if f.model_id is None and (f.name or "").lower() == full_lower:
                    return f.key
            name_matches = [
                f.key for f in dev.fields.values()
                if not getattr(f, "group_path", None) and (f.name or "").lower() == full_lower
            ]
            if len(name_matches) == 1:
                return name_matches[0]

    # 2. Static fallback via SunSpec catalog when mid_int is present
    if mid_int is not None:
        from .catalog import get_catalog
        cat_model = get_catalog().get_model(mid_int)
        if cat_model:
            for pt in cat_model.points.values():
                if (pt.name or "").lower() == pt_lower:
                    return f"{dev_type}.{cat_model.name}.{pt.name}"

    # 3. Static fallback via MQTT live spec index
    from .state import _MQTT_LIVE_SPECS
    spec_key = (dev_type.lower(), clean_slug.lower())
    if spec_key in _MQTT_LIVE_SPECS:
        return f"{dev_type}.live.{clean_slug}"
    for (s_dev, s_name) in _MQTT_LIVE_SPECS:
        if s_dev == dev_type.lower() and s_name.lower() == clean_slug.lower():
            return f"{dev_type}.live.{s_name}"

    return None


def _remap_concept_key(
    field_part: str,
    state_store: Optional[StateStore] = None,
    sn_hint: Optional[str] = None,
) -> Optional[str]:
    from .mapping import MappingRegistry
    from .grouping import load_custom_groupings

    reg = MappingRegistry.get_instance()
    custom_data = load_custom_groupings()
    custom_concepts = custom_data.get("custom_concepts") or {}

    orig_part = field_part
    if field_part.endswith("_None"):
        field_part = field_part[:-5]

    if field_part in _LEGACY_CONCEPT_REMAP:
        mapped = _LEGACY_CONCEPT_REMAP[field_part]
        if ".live." in field_part and ".compound." in mapped:
            target_cid = mapped.split(".")[-1]
            if _is_raw_field_excluded_from_compound(field_part, target_cid, sn_hint, reg=reg, custom_data=custom_data):
                logger.debug(
                    "Preserving ungrouped raw key '%s' on %s (skipping legacy remap to '%s')",
                    field_part,
                    sn_hint or "*",
                    mapped,
                )
                return field_part
        logger.debug("Remapped legacy HA key '%s' -> '%s' (sn=%s)", orig_part, mapped, sn_hint or "*")
        return mapped

    if ".concept." in field_part:
        dev_type, _, cid = field_part.partition(".concept.")
        if reg.get_by_id(cid) or cid in custom_concepts:
            mapped = f"{dev_type}.compound.{cid}"
            logger.debug("Migrated legacy concept key '%s' -> '%s' (sn=%s)", orig_part, mapped, sn_hint or "*")
            return mapped
        resolved = _resolve_standalone_or_orphan_slug(dev_type, cid, state_store, sn_hint)
        if resolved:
            logger.debug("Resolved legacy concept key '%s' -> '%s' (sn=%s)", orig_part, resolved, sn_hint or "*")
            return resolved
        logger.warning("Dropping obsolete legacy concept key '%s' (sn=%s)", orig_part, sn_hint or "*")
        return None

    if ".standalone." in field_part:
        dev_type, _, slug = field_part.partition(".standalone.")
        resolved = _resolve_standalone_or_orphan_slug(dev_type, slug, state_store, sn_hint)
        if resolved:
            logger.debug("Repaired standalone HA key '%s' -> '%s' (sn=%s)", orig_part, resolved, sn_hint or "*")
            return resolved
        logger.warning("Dropping unresolvable standalone HA key '%s' (sn=%s)", orig_part, sn_hint or "*")
        return None

    if ".compound." in field_part:
        dev_type, _, cid = field_part.partition(".compound.")
        if reg.get_by_id(cid) or cid in custom_concepts:
            return field_part
        resolved = _resolve_standalone_or_orphan_slug(dev_type, cid, state_store, sn_hint)
        if resolved:
            logger.debug("Repaired invalid compound HA key '%s' -> '%s' (sn=%s)", orig_part, resolved, sn_hint or "*")
            return resolved
        logger.warning("Dropping invalid/unknown compound HA key '%s' (sn=%s)", orig_part, sn_hint or "*")
        return None

    return field_part


def qualify_legacy_ha_config(selected_field_keys: Optional[List[str]], state_store: StateStore) -> List[str]:
    """Ensure all field keys are scoped by device serial number (<SERIAL>:<FIELD_KEY>)."""
    if not selected_field_keys:
        return []
    qualified: Set[str] = set()
    for k in selected_field_keys:
        if k is None:
            continue
        k_str = str(k).strip()
        if not k_str:
            continue
        if ":" in k_str:
            sn_part, field_part = k_str.split(":", 1)
            sn_part = sn_part.strip().upper()
            field_part = field_part.strip()
            # Remap or drop legacy concept/standalone artifacts
            remapped = _remap_concept_key(field_part, state_store=state_store, sn_hint=sn_part)
            if not remapped:
                continue
            qualified.add(f"{sn_part}:{remapped}")
        else:
            # Legacy unqualified key, e.g. 'inverter.live.grid_power_w' or 'pv_link.string_combiner.DCW'
            remapped = _remap_concept_key(k_str, state_store=state_store)
            if not remapped:
                continue
            k_str = remapped
            dot_idx = k_str.find(".")
            dev_type = k_str[:dot_idx] if dot_idx != -1 else ""
            devices = [d for d in state_store.devices.values() if d.device_type == dev_type]
            if devices:
                for dev in devices:
                    qualified.add(f"{dev.serial_number.strip().upper()}:{k_str}")
            else:
                # If device not found yet in state_store, keep key as fallback
                logger.debug("No device of type '%s' registered yet; keeping unqualified key '%s'", dev_type, k_str)
                qualified.add(k_str)

    # Collapse redundant raw member keys whenever their active parent compound key is also selected
    from .mapping import MappingRegistry
    from .grouping import load_custom_groupings

    reg = MappingRegistry.get_instance()
    custom_data = load_custom_groupings()
    field_overrides = custom_data.get("field_overrides", {}) or {}
    to_remove: Set[str] = set()

    for qk in list(qualified):
        if ":" in qk:
            sn_part, f_part = qk.split(":", 1)
            sn_prefix = f"{sn_part}:"
        else:
            sn_part, f_part = "", qk
            sn_prefix = ""
        if ".compound." not in f_part:
            continue
        cid = f_part.split(".")[-1]
        members: Set[str] = set()
        m_def = reg.get_by_id(cid)
        if m_def:
            for mf in (list(m_def.mqtt_fields) + list(m_def.modbus_fields)):
                if not _is_raw_field_excluded_from_compound(mf, cid, sn_part or None, reg=reg, custom_data=custom_data):
                    members.add(mf)
        for ov_k, ov_tgt in field_overrides.items():
            if ov_tgt != cid:
                continue
            if ":" in ov_k:
                ov_sn, ov_fk = ov_k.split(":", 1)
                if sn_part and ov_sn.strip().upper() != sn_part:
                    continue
                members.add(ov_fk.strip())
            else:
                members.add(ov_k.strip())

        for mf in members:
            cand_raw = f"{sn_prefix}{mf}"
            if cand_raw in qualified and cand_raw not in to_remove:
                to_remove.add(cand_raw)
                logger.debug("Collapsed redundant raw member '%s' into active compound '%s'", cand_raw, qk)

    if to_remove:
        qualified -= to_remove

    # Deduplicate redundant concrete subgroup keys when an active wildcard rule covers them
    wildcard_rules = [qk for qk in qualified if is_group_wildcard_key(qk)]
    if wildcard_rules:
        redundant_concrete: Set[str] = set()
        for wk in wildcard_rules:
            wk_sn = wk.split(":", 1)[0].strip().upper() if ":" in wk else None
            for qk in qualified:
                if qk == wk or is_group_wildcard_key(qk):
                    continue
                qk_sn = qk.split(":", 1)[0].strip().upper() if ":" in qk else None
                if wk_sn != qk_sn:
                    continue
                if group_wildcard_matches_field_key(wk, qk):
                    redundant_concrete.add(qk)
                    logger.debug("Collapsed redundant concrete group key '%s' into active wildcard '%s'", qk, wk)
        if redundant_concrete:
            qualified -= redundant_concrete

    return sorted(list(qualified))


def reset_ha_config_to_defaults(
    state_store: StateStore,
    config_path: Optional[Path | str] = None,
) -> List[str]:
    """Reset ha_config.yaml to seed ha_default_config.yaml qualified for live devices."""
    seed_path = get_default_seed_config_path()
    raw_seed = load_ha_config(seed_path, allow_default_seed=False)
    if not raw_seed:
        raw_seed = get_recommended_field_keys(state_store)
    qualified = qualify_legacy_ha_config(raw_seed, state_store)
    save_ha_config(qualified, category_overrides={}, config_path=config_path)
    return qualified


def load_ha_category_overrides(config_path: Optional[Path | str] = None) -> Dict[str, str]:
    """Load dictionary of entity category overrides from ha_config.yaml.

    Returns mapping of '<SERIAL>:<FIELD_KEY>' (or '<FIELD_KEY>') -> 'primary' | 'diagnostic' | 'config'.
    """
    path = Path(config_path) if config_path else get_default_ha_config_path()
    doc = _read_ha_config_doc(path)
    return dict(doc.get("category_overrides") or {})


def save_ha_config(
    selected_field_keys: Optional[List[str]],
    category_overrides: Optional[Dict[str, str]] = None,
    config_path: Optional[Path | str] = None,
):
    """Save list of selected field keys and category overrides to ha_config.yaml."""
    path = Path(config_path) if config_path else get_default_ha_config_path()
    clean_keys = sorted(list({str(k).strip() for k in (selected_field_keys or []) if k is not None and str(k).strip()}))

    clean_overrides: Dict[str, str] = {}
    if category_overrides is not None:
        clean_overrides = {str(k).strip(): str(v).strip().lower() for k, v in category_overrides.items() if k and v}
    else:
        clean_overrides = load_ha_category_overrides(path)

    doc: Dict[str, Any] = {"selected_fields": clean_keys}
    if clean_overrides:
        doc["category_overrides"] = dict(sorted(clean_overrides.items()))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(
                doc,
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        tmp_path.replace(path)
        _HA_CONFIG_CACHE.pop(str(path.resolve()), None)
        logger.info("Saved %d entities and %d category overrides to %s", len(clean_keys), len(clean_overrides), path)
    except Exception as e:
        logger.error("Failed to save %s: %s", path, e)
        raise e


def save_ha_category_override(
    device_sn: Optional[str],
    field_key: str,
    category: Optional[str],
    config_path: Optional[Path | str] = None,
    field_keys: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Save or remove entity category override(s) in ha_config.yaml."""
    overrides = load_ha_category_overrides(config_path)
    sn_clean = (device_sn or "").strip().upper()

    target_keys = list(field_keys) if field_keys else []
    if field_key and field_key not in target_keys:
        target_keys.insert(0, field_key)

    cat_norm = (category or "").strip().lower()
    is_reset = not cat_norm or cat_norm in ("default", "none", "auto", "reset")

    for fk in target_keys:
        fk_clean = str(fk).strip()
        if not fk_clean:
            continue
        if is_group_wildcard_key(fk_clean):
            fk_sn = fk_clean.split(":", 1)[0].strip().upper() if ":" in fk_clean else sn_clean
            fk_field = fk_clean.split(":", 1)[1].strip() if ":" in fk_clean else fk_clean
            fk_parts = fk_field.split(".")
            grp_seg_re = "_".join(r"\d+" if s == "*" else re.escape(s.lower()) for s in fk_parts[2:-1])
            pt_re = re.escape(re.sub(r"[^a-z0-9]+", "_", fk_parts[-1].lower()).strip("_"))
            concept_inst_re = re.compile(
                rf"^{re.escape(fk_parts[0].lower())}\.(?:concept|standalone)\.(?:m\d+_)?{grp_seg_re}_{pt_re}$"
            )
            stale_concrete: List[str] = []
            for ov_k in overrides:
                ov_sn = ov_k.split(":", 1)[0].strip().upper() if ":" in ov_k else ""
                ov_field = ov_k.split(":", 1)[1].strip() if ":" in ov_k else ov_k.strip()
                if fk_sn and ov_sn and ov_sn != fk_sn:
                    continue
                if not fk_sn and ov_sn:
                    continue
                if ov_field == fk_field:
                    continue
                if group_wildcard_matches_field_key(fk_field, ov_field) or concept_inst_re.match(ov_field.lower()):
                    stale_concrete.append(ov_k)
            for sk in stale_concrete:
                overrides.pop(sk, None)

        qualified_key = fk_clean if ":" in fk_clean else (f"{sn_clean}:{fk_clean}" if sn_clean else fk_clean)
        if is_reset:
            overrides.pop(qualified_key, None)
            if ":" in qualified_key:
                overrides.pop(fk_clean, None)
        else:
            overrides[qualified_key] = cat_norm

    selected = load_ha_config(config_path, allow_default_seed=True)
    save_ha_config(selected, category_overrides=overrides, config_path=config_path)
    return overrides


def get_effective_ha_category(
    field: Any,
    device: Any,
    category_overrides: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Determine the effective Home Assistant entity_category ('diagnostic', 'config', or None for primary).

    Respects user overrides from category_overrides first. Otherwise evaluates
    is_diagnostic_point heuristics, pv_link overrides, and explicit field hints.
    """
    dev_sn = getattr(device, "serial_number", str(device) if isinstance(device, str) else "").strip().upper()
    dev_type = getattr(device, "device_type", None)

    # 1. Check user overrides
    if category_overrides:
        f_key = getattr(field, "key", getattr(field, "field_key", None)) or getattr(field, "id", "")
        f_id = getattr(field, "id", None)
        concept_key = getattr(field, "concept_key", None) or getattr(field, "compound_key", None)
        pt_name = getattr(field, "name", "")
        model_id = getattr(field, "model_id", None)
        mqtt_k = getattr(field, "mqtt_key", None) or getattr(field, "mqtt_equivalent", None)
        active_src = getattr(field, "active_source_key", None)

        raw_candidates: List[str] = []
        if f_key:
            raw_candidates.append(f_key)
        if f_id:
            raw_candidates.append(f_id)
        if concept_key:
            raw_candidates.append(concept_key)
            if dev_type:
                raw_candidates.append(f"{dev_type}.concept.{concept_key}")
                raw_candidates.append(f"{dev_type}.compound.{concept_key}")
        if active_src:
            raw_candidates.append(active_src)
        if pt_name:
            raw_candidates.append(pt_name)
            if dev_type:
                if model_id:
                    raw_candidates.append(f"{dev_type}.standalone.{pt_name.lower()}_{model_id}")
                else:
                    raw_candidates.append(f"{dev_type}.standalone.{pt_name.lower()}")
        if mqtt_k:
            raw_candidates.append(mqtt_k)

        # Sources if present (for ConceptView / CompoundFieldView)
        for s in getattr(field, "sources", []):
            sk = getattr(s, "field_key", None) or getattr(s, "key", None)
            if sk:
                raw_candidates.append(sk)

        # Check mapping registry for concept id
        try:
            from .mapping import MappingRegistry
            reg = MappingRegistry.get_instance()
            mapped = (
                reg.find_mapping_for_modbus(f_key)
                or (reg.find_concept(dev_type, pt_name, model_id) if dev_type and pt_name else None)
            )
            if mapped and mapped.id:
                raw_candidates.append(mapped.id)
                if dev_type:
                    raw_candidates.append(f"{dev_type}.concept.{mapped.id}")
                    raw_candidates.append(f"{dev_type}.compound.{mapped.id}")
        except Exception:
            pass

        unique_raw = list(dict.fromkeys(c for c in raw_candidates if c))
        wildcard_raw = list(dict.fromkeys(
            wk for c in unique_raw if (wk := wildcardize_group_field_key(c)) and wk not in unique_raw
        ))

        candidates: List[str] = []
        if dev_sn:
            for c in unique_raw:
                candidates.append(f"{dev_sn}:{c}")
        candidates.extend(unique_raw)
        # Explicit instance overrides take precedence over group '*' wildcard overrides
        if dev_sn:
            for wk in wildcard_raw:
                candidates.append(f"{dev_sn}:{wk}")
        candidates.extend(wildcard_raw)

        for c in candidates:
            if c in category_overrides:
                val = str(category_overrides[c]).strip().lower()
                if val in ("primary", "sensor", "none", "null", ""):
                    return None
                if val in ("diagnostic", "config"):
                    return val

        if any(".*." in ok for ok in category_overrides):
            for ok, raw_val in category_overrides.items():
                if ".*." not in ok:
                    continue
                if ":" in ok:
                    ok_sn, ok_field = ok.split(":", 1)
                    if dev_sn and ok_sn.strip().upper() != dev_sn:
                        continue
                else:
                    ok_field = ok
                if any(group_wildcard_matches_field_key(ok_field, c) for c in unique_raw):
                    val = str(raw_val).strip().lower()
                    if val in ("primary", "sensor", "none", "null", ""):
                        return None
                    if val in ("diagnostic", "config"):
                        return val

    # 2. Default logic
    is_writable = is_ha_writable_allowed(field)
    if is_writable:
        hint = getattr(field, "ha_hint", None)
        if hint and getattr(hint, "entity_category", None):
            return hint.entity_category
        return getattr(field, "entity_category", None)

    if getattr(field, "group_path", None):
        hint = getattr(field, "ha_hint", None)
        if hint and getattr(hint, "entity_category", None) == "config":
            return "config"
        return "diagnostic"

    f_key = getattr(field, "key", getattr(field, "field_key", None)) or getattr(field, "id", "")
    sub_key = str(f_key).split(".", 1)[-1].replace(".", "_").lower() if f_key else ""
    pt_name_lower = str(getattr(field, "name", "")).lower()

    if dev_type == "pv_link" and (
        pt_name_lower in ("p", "e", "dcw", "dcwh", "dca")
        or sub_key in ("rebus_status_p", "rebus_status_e", "string_combiner_dca", "string_combiner_dcw", "string_combiner_dcwh")
    ):
        return None

    if is_diagnostic_point(getattr(field, "name", ""), getattr(field, "model_id", None), device_type=dev_type) or is_diagnostic_point(sub_key, device_type=dev_type):
        return "diagnostic"

    hint = getattr(field, "ha_hint", None)
    if hint and getattr(hint, "entity_category", None):
        return hint.entity_category

    return getattr(field, "entity_category", None)


def unqualify_ha_config(selected_field_keys: Optional[List[str]]) -> List[str]:
    """Strip device serial number prefixes from field keys and return deduplicated generic field IDs."""
    if not selected_field_keys:
        return []
    generic_keys: Set[str] = set()
    for k in selected_field_keys:
        if k is None:
            continue
        k_str = str(k).strip()
        if not k_str:
            continue
        if ":" in k_str:
            _, field_part = k_str.split(":", 1)
            generic_keys.add(field_part.strip())
        else:
            generic_keys.add(k_str)
    return sorted(list(generic_keys))


_UNAMBIGUOUS_MODEL_DEV_TYPE: Dict[int, str] = {
    101: "inverter",
    102: "inverter",
    103: "inverter",
    701: "inverter",
    64202: "inverter",
    64204: "inverter",
    64208: "inverter",
    802: "battery",
    804: "battery",
    64209: "battery",
    64252: "battery",
    401: "pv_link",
    402: "pv_link",
    403: "pv_link",
    404: "pv_link",
    64251: "pv_link",
    64200: "rebus_beacon",
}


def _repair_legacy_export_key(key: str) -> Optional[str]:
    """Resolve '.standalone.' or unambiguous bare '<pt>_<model>' slugs during default export."""
    clean = (key or "").strip()
    if ".standalone." in clean and "." in clean:
        dev_p = clean.split(".", 1)[0]
        slug = clean.split(".")[-1]
        return _resolve_standalone_or_orphan_slug(dev_p, slug)
    if "." not in clean:
        if "_" not in clean:
            return None
        _, suffix = clean.rsplit("_", 1)
        if not suffix.isdigit():
            return None
        dev_t = _UNAMBIGUOUS_MODEL_DEV_TYPE.get(int(suffix))
        if not dev_t:
            return None
        return _resolve_standalone_or_orphan_slug(dev_t, clean)
    return clean


def generate_ha_default_config(
    source_path: Optional[Path | str] = None,
    target_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Generate generic ha_default_config dictionary and YAML string from current ha_config.yaml."""
    from .mapping import MappingRegistry

    src = Path(source_path) if source_path else get_default_ha_config_path()
    dst = Path(target_path) if target_path else get_default_seed_config_path()

    if not src.exists():
        raise FileNotFoundError(f"Source configuration file not found: {src}")

    raw_keys = load_ha_config(config_path=src, allow_default_seed=False)
    unqualified_keys = unqualify_ha_config(raw_keys)

    reg = MappingRegistry.get_instance()
    raw_to_comp = reg.get_raw_to_compound_map()
    canonical_keys: Set[str] = set()

    for gk in unqualified_keys:
        repaired = _repair_legacy_export_key(gk)
        if not repaired:
            continue
        gk = repaired

        if (".compound." in gk or ".concept." in gk) and "." in gk:
            dev_p = gk.split(".", 1)[0]
            cid = gk.split(".")[-1]
            m = reg.get_by_id(cid)
            if m and (not m.device_type or m.device_type == dev_p):
                canonical_keys.add(f"{dev_p}.compound.{m.id}")
            continue

        if not is_group_wildcard_key(gk) and gk in raw_to_comp and not reg.is_field_ungrouped(gk):
            canonical_keys.add(raw_to_comp[gk])
        else:
            canonical_keys.add(gk)

    active_wildcards = [k for k in canonical_keys if is_group_wildcard_key(k)]
    generic_keys = sorted(
        k for k in canonical_keys
        if is_group_wildcard_key(k)
        or not any(group_wildcard_matches_field_key(w, k) for w in active_wildcards)
    )

    existing_data: Dict[str, Any] = {}
    if dst.exists():
        try:
            with open(dst, "r", encoding="utf-8") as f_cur:
                existing_data = yaml.safe_load(f_cur) or {}
        except Exception:
            existing_data = {}

    out_dict = dict(existing_data)
    out_dict["selected_fields"] = generic_keys

    # Also generalize and deduplicate category overrides if present
    raw_overrides = load_ha_category_overrides(config_path=src)
    if raw_overrides:
        generic_overrides: Dict[str, str] = {}
        for ov_k, ov_v in raw_overrides.items():
            clean_k = ov_k.split(":", 1)[1].strip() if ":" in ov_k else ov_k.strip()
            clean_v = ov_v.strip().lower()
            repaired = _repair_legacy_export_key(clean_k)
            if not repaired:
                continue
            generic_overrides[repaired] = clean_v

        ov_wildcards = {k for k in generic_overrides if is_group_wildcard_key(k)}
        filtered_overrides = {
            k: v for k, v in generic_overrides.items()
            if k in ov_wildcards
            or not any(
                group_wildcard_matches_field_key(w, k) and generic_overrides.get(w) == v
                for w in ov_wildcards
            )
        }
        if filtered_overrides:
            out_dict["category_overrides"] = dict(sorted(filtered_overrides.items()))

    yaml_header = (
        "# PWRcell Default Home Assistant Entity Configuration\n"
        "# Generated from existing ha_config.yaml (hardware serial numbers stripped)\n\n"
    )
    yaml_str = yaml_header + yaml.dump(out_dict, default_flow_style=False, sort_keys=False)
    return {
        "data": out_dict,
        "yaml": yaml_str,
        "selected_fields": generic_keys,
        "source_path": str(src),
        "target_path": str(dst),
    }


def export_default_config(
    source_path: Optional[Path | str] = None,
    target_path: Optional[Path | str] = None,
) -> List[str]:
    """Convert a device-specific ha_config.yaml into a generic ha_default_config.yaml.

    Strips hardware serial numbers and deduplicates field IDs so the result
    can serve as a universal default seed across any installation.
    """
    res = generate_ha_default_config(source_path=source_path, target_path=target_path)
    dst = Path(res["target_path"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.with_suffix(".tmp")
    with open(tmp_dst, "w", encoding="utf-8") as f:
        f.write(res["yaml"])
    tmp_dst.replace(dst)

    generic_keys = res["selected_fields"]
    logger.info("Exported %d generic default field IDs from %s to %s", len(generic_keys), res["source_path"], dst)
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

    from .catalog import get_device_type_label
    dev_label = get_device_type_label(device.device_type) if device.device_type else device.model_name
    if device.device_type == "rebus_beacon":
        dev_info["name"] = f"PWRcell {dev_label}"
    else:
        dev_info["name"] = f"PWRcell {dev_label} ({short_sn})"

    # Device hierarchy: connect subordinate devices via gateway
    if gateway_device and gateway_device.serial_number != device.serial_number:
        dev_info["via_device"] = f"pwrcell_{gateway_device.serial_number.strip().lower()}"

    return dev_info


def generate_gateway_discovery_payload(
    gateway: UnifiedDevice,
    base_topic: str = "pwrcell",
    ha_prefix: str = "homeassistant",
) -> Dict[str, Any]:
    """Generate Home Assistant MQTT Discovery configuration for the top-level parent gateway device node."""
    gw_sn_lower = gateway.serial_number.strip().lower()
    gw_dev_info = get_device_info(gateway, gateway_device=None)
    gw_node_id = f"pwrcell_{gw_sn_lower}"
    gw_obj_id = "status"
    gw_config_topic = f"{ha_prefix}/binary_sensor/{gw_node_id}/{gw_obj_id}/config"
    gw_state_topic = f"{base_topic}/{gw_sn_lower}/status"
    gw_payload = {
        "has_entity_name": True,
        "name": "Status",
        "unique_id": f"pwrcell_{gw_sn_lower}_{gw_obj_id}",
        "object_id": f"{gateway.device_type}_{gw_sn_lower}_{gw_obj_id}",
        "state_topic": gw_state_topic,
        "payload_on": "online",
        "payload_off": "offline",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
        "device": gw_dev_info,
        "origin": ORIGIN_INFO,
        "availability": [
            {
                "topic": f"{base_topic}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ],
    }
    return {
        "config_topic": gw_config_topic,
        "state_topic": gw_state_topic,
        "attributes_topic": None,
        "command_topic": None,
        "old_sensor_topic": None,
        "legacy_config_topics": [],
        "suggested_display_precision": None,
        "availability_topic": f"{base_topic}/status",
        "device_availability_topic": gw_state_topic,
        "platform": "binary_sensor",
        "payload": gw_payload,
    }


def generate_discovery_payload(
    field: Any,
    device: UnifiedDevice,
    gateway_device: Optional[UnifiedDevice] = None,
    base_topic: str = "pwrcell",
    ha_prefix: str = "homeassistant",
    category_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Generate modern Home Assistant MQTT Discovery configuration dictionary and topics."""
    is_compound = field.is_compound
    is_concept = bool(is_compound or hasattr(field, "concept_key"))
    is_writable = is_ha_writable_allowed(field)

    if is_concept:
        platform = field.ha_platform if (is_writable or field.ha_platform == "sensor") else "sensor"
        if is_writable and platform == "sensor":
            if getattr(field, "ha_options", None) or getattr(field, "ha_device_class", None) == "enum":
                platform = "select"
            else:
                platform = "number"
    else:
        hint = field.ha_hint
        if is_writable:
            if hint and hint.platform in ("select", "number", "switch"):
                platform = hint.platform
            elif getattr(field, "is_enum", False) or getattr(field, "symbols", None):
                platform = "select"
            else:
                platform = "number"
        elif hint and hint.platform:
            platform = hint.platform
        else:
            platform = "sensor"

    clean_sn = device.serial_number.strip().lower()

    if is_concept:
        concept_id = getattr(field, "concept_key", None) or getattr(field, "mapping_id", None) or getattr(field, "name", "")
        sub_key = str(concept_id).lower().replace(".", "_")
    else:
        # Build unique object_id from sub-key path (e.g. 'live_solar_power_w' or 'compound_grid_power')
        sub_key = field.key.split(".", 1)[-1].replace(".", "_").lower()
        # Prevent raw fields whose trailing path matches a compound concept ID
        # (e.g., Model 802 battery.battery.SoC -> battery_soc) from colliding on
        # config_topic / state_topic / unique_id with the compound entity.
        from .mapping import MappingRegistry
        from .grouping import load_custom_groupings

        reg = MappingRegistry.get_instance()
        m_col = reg.get_by_id(sub_key) or next(
            (m for m in reg.get_all() if m.id.lower() == sub_key),
            None,
        )
        custom_concepts = load_custom_groupings().get("custom_concepts") or {}
        c_col = custom_concepts.get(sub_key) or next(
            (v for k, v in custom_concepts.items() if str(k).lower() == sub_key),
            None,
        )
        collides_compound = bool(
            (m_col and (not m_col.device_type or m_col.device_type == device.device_type))
            or (isinstance(c_col, dict) and (not c_col.get("device_type") or c_col.get("device_type") == device.device_type))
        )
        if collides_compound:
            orig_sub_key = sub_key
            model_id = getattr(field, "model_id", None)
            if model_id is not None:
                pt_tail = (
                    field.key.split(".", 2)[-1].replace(".", "_").lower()
                    if field.key.count(".") >= 2
                    else orig_sub_key
                )
                sub_key = f"m{model_id}_{pt_tail}"
            else:
                sub_key = f"raw_{orig_sub_key}"
            logger.debug(
                "Disambiguated raw field '%s' discovery sub_key '%s' -> '%s' to avoid compound collision",
                field.key,
                orig_sub_key,
                sub_key,
            )
    
    node_id = f"pwrcell_{clean_sn}"
    object_id = sub_key
    unique_id = f"pwrcell_{clean_sn}_{sub_key}"

    config_topic = f"{ha_prefix}/{platform}/{node_id}/{object_id}/config"
    state_topic = f"{base_topic}/{clean_sn}/{object_id}/state"
    command_topic = f"{base_topic}/{clean_sn}/{object_id}/set"
    availability_topic = f"{base_topic}/status"
    device_availability_topic = f"{base_topic}/{clean_sn}/status"

    old_sensor_topic = f"{ha_prefix}/sensor/{node_id}/{object_id}/config" if platform in ("select", "number", "switch") else None

    raw_label = getattr(field, "label", None) or getattr(field, "name", "")
    name_clean = str(raw_label).strip()

    sub_key_lower = sub_key.lower()
    pt_name_lower = str(getattr(field, "name", "")).lower()

    has_group = bool(getattr(field, "group_path", None))
    legacy_config_topics = []
    candidates = {sub_key}
    if pt_name_lower and not has_group:
        candidates.add(pt_name_lower)
    for c in candidates:
        for pfx in ("compound_", "concept_"):
            legacy_config_topics.append(f"{ha_prefix}/{platform}/{node_id}/{pfx}{c}/config")
            legacy_config_topics.append(f"{ha_prefix}/sensor/{node_id}/{pfx}{c}/config")
    # Exclude current config_topic and deduplicate
    legacy_config_topics = [t for t in dict.fromkeys(legacy_config_topics) if t != config_topic]

    # Friendly entity naming instead of raw SunSpec unit names (top-level entities only)
    if not has_group:
        if name_clean in ("Watts", "W") or sub_key_lower in ("inverter_w", "w"):
            name_clean = "Active Power"
        elif name_clean in ("Amps", "A") or sub_key_lower in ("inverter_a", "string_combiner_dca"):
            if device.device_type == "pv_link" or "string" in sub_key_lower or "dca" in sub_key_lower:
                name_clean = "String Current"
            else:
                name_clean = "AC Output Current"
        elif name_clean in ("Amps PhaseA", "AphA") or sub_key_lower in ("inverter_apha", "apha"):
            name_clean = "Phase A Current"
        elif name_clean in ("Amps PhaseB", "AphB") or sub_key_lower in ("inverter_aphb", "aphb"):
            name_clean = "Phase B Current"
        elif name_clean in ("Amps PhaseC", "AphC") or sub_key_lower in ("inverter_aphc", "aphc"):
            name_clean = "Phase C Current"
        elif name_clean.startswith("Phase Voltage AN") or sub_key_lower in ("inverter_phvpha", "phvpha"):
            name_clean = "Phase A Voltage"
        elif name_clean.startswith("Phase Voltage BN") or sub_key_lower in ("inverter_phvphb", "phvphb"):
            name_clean = "Phase B Voltage"
        elif name_clean.startswith("Phase Voltage CN") or sub_key_lower in ("inverter_phvphc", "phvphc"):
            name_clean = "Phase C Voltage"
        elif name_clean == "REbus Voltage " or sub_key_lower.endswith("rebus_status_v"):
            name_clean = "REbus Voltage"
        elif sub_key_lower in ("battery_soc", "state_of_charge") and name_clean.lower() in ("battery soc", "soc"):
            name_clean = "State of Charge"

    device_info = get_device_info(device, gateway_device=gateway_device)

    # Modern HA naming: has_entity_name=True ensures entity name is clean and prefixed by device name in HA UI
    payload: Dict[str, Any] = {
        "has_entity_name": True,
        "name": name_clean,
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

    if is_concept:
        if platform == "select":
            payload["command_topic"] = command_topic
            if getattr(field, "ha_options", None):
                payload["options"] = _filter_ha_options(field.ha_options)
            if getattr(field, "entity_category", None):
                payload["entity_category"] = field.entity_category
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            u_raw = field.ha_unit or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
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
            u_raw = field.ha_unit or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
            if (platform == "select" or getattr(field, "ha_device_class", None) == "enum") and getattr(field, "ha_options", None):
                payload["options"] = field.ha_options
    elif field.ha_hint:
        hint = field.ha_hint
        if platform == "select":
            payload["command_topic"] = command_topic
            if hint.options:
                payload["options"] = _filter_ha_options(hint.options)
            elif getattr(field, "symbols", None):
                payload["options"] = _filter_ha_options([
                    s.name if hasattr(s, "name") else s["name"]
                    for s in sorted(field.symbols, key=lambda x: getattr(x, "value", x.get("value") if isinstance(x, dict) else 0))
                ])
            if hint.entity_category:
                payload["entity_category"] = hint.entity_category
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            u_raw = hint.unit_of_measurement or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
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
            u_raw = hint.unit_of_measurement or field.units
            if u_raw:
                payload["unit_of_measurement"] = normalize_ha_unit(u_raw)
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
                payload["options"] = _filter_ha_options([
                    s.name if hasattr(s, "name") else s["name"]
                    for s in sorted(field.symbols, key=lambda x: getattr(x, "value", x.get("value") if isinstance(x, dict) else 0))
                ])
        elif platform == "number":
            payload["command_topic"] = command_topic
            payload["mode"] = "auto"
            if field.units:
                payload["unit_of_measurement"] = normalize_ha_unit(field.units)
            sf_val = device.get_scale_factor_value(field) if hasattr(device, "get_scale_factor_value") else None
            bounds = field.get_bounds(sf_value=sf_val) if hasattr(field, "get_bounds") else {}
            if bounds.get("min_value") is not None:
                payload["min"] = bounds["min_value"]
            if bounds.get("max_value") is not None:
                payload["max"] = bounds["max_value"]
            if isinstance(bounds.get("step"), (int, float)):
                payload["step"] = bounds["step"]
    elif field.units:
        payload["unit_of_measurement"] = normalize_ha_unit(field.units)

    # 1. Temperature device_class and unit enforcement
    if (
        sub_key_lower.endswith(("_tmpcab", "_tmpsnk", "_tmptrns", "_tmpot", "_modtmpavg", "_modtmpmax", "_modtmpmin", "_celltmpavg", "_celltmpmax", "_celltmpmin"))
        or sub_key_lower in ("inverter_tmpcab", "inverter_tmpsnk", "inverter_tmptrns", "inverter_tmpot", "rebus_status_t")
        or pt_name_lower in ("t", "tmpcab", "tmpsnk", "tmptrns", "tmpot", "modtmpavg", "modtmpmax", "modtmpmin")
        or payload.get("device_class") == "temperature"
        or payload.get("unit_of_measurement") in ("°C", "C", "Deg C")
    ):
        payload["device_class"] = "temperature"
        payload["unit_of_measurement"] = "°C"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    # 2. Electrical sensor device_class enforcement
    if sub_key_lower in ("inverter_va", "va") or pt_name_lower == "va":
        payload["device_class"] = "apparent_power"
        payload["unit_of_measurement"] = "VA"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    if sub_key_lower in ("inverter_var", "var") or pt_name_lower in ("var", "var_sf"):
        payload["device_class"] = "reactive_power"
        payload["unit_of_measurement"] = "var"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    if sub_key_lower in ("inverter_pf", "pf") or pt_name_lower == "pf":
        payload["device_class"] = "power_factor"
        payload["unit_of_measurement"] = "%"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    # 3. Battery SoC device_class and unit enforcement
    if sub_key_lower in ("battery_soc", "state_of_charge") or pt_name_lower in ("battery_soc", "soc", "state_of_charge"):
        payload["device_class"] = "battery"
        payload["unit_of_measurement"] = "%"
        if platform == "sensor":
            payload["state_class"] = "measurement"

    # 4. Number configuration entity bounds and device classes
    if platform == "number":
        norm_u = normalize_ha_unit(payload.get("unit_of_measurement"))
        if norm_u:
            payload["unit_of_measurement"] = norm_u
        if norm_u == "A" and not payload.get("device_class"):
            payload["device_class"] = "current"
        if norm_u == "%" or any(k in sub_key_lower for k in ("socmax", "socrsvmax", "socrsvmin", "socmin", "minrsvpct")):
            payload["mode"] = "slider"
            payload["step"] = 1
            if payload.get("max") is not None and payload["max"] > 100:
                payload["max"] = 100
            if payload.get("min") is not None and payload["min"] < 0:
                payload["min"] = 0

    # 5. Diagnostic entity categorization (honoring category_overrides and default heuristics)
    eff_cat = get_effective_ha_category(field, device, category_overrides=category_overrides)
    if eff_cat:
        payload["entity_category"] = eff_cat
    else:
        payload.pop("entity_category", None)

    # 6. HA schema validation: enum device_class requires options
    if payload.get("device_class") == "enum" and not payload.get("options"):
        payload.pop("device_class", None)

    precision = None
    if platform == "sensor":
        if is_concept:
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
        "legacy_config_topics": legacy_config_topics,
        "suggested_display_precision": precision,
        "availability_topic": availability_topic,
        "device_availability_topic": device_availability_topic,
        "platform": platform,
        "payload": payload,
    }


def ensure_selected_field_definitions(
    state_store: StateStore,
    dev: UnifiedDevice,
    selected_keys: Iterable[str],
    reg: Any = None,
    custom_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Pre-populate StateField metadata definitions for any selected keys not yet polled on `dev`."""
    from .mapping import MappingRegistry
    from .grouping import is_field_excluded_from_mapping, load_custom_groupings

    reg = reg or MappingRegistry.get_instance()
    custom_data = custom_data if custom_data is not None else load_custom_groupings()
    sn_clean = dev.serial_number.strip().upper()
    field_overrides = custom_data.get("field_overrides", {}) or {}

    for sel_key in selected_keys:
        if not sel_key or not isinstance(sel_key, str):
            continue
        if ":" in sel_key:
            target_sn, f_path = sel_key.split(":", 1)
            if target_sn.strip().upper() != sn_clean:
                continue
        else:
            f_path = sel_key
            if not f_path.startswith(f"{dev.device_type}."):
                continue

        if f_path.startswith(f"{dev.device_type}.compound.") or f_path.startswith(f"{dev.device_type}.concept."):
            cid = f_path.split(".")[-1]
            m = reg.get_by_id(cid)
            mqtt_candidates: List[str] = []
            mb_canonical: List[str] = []
            mb_alias: List[str] = []
            if m and m.device_type == dev.device_type:
                for cand in m.mqtt_fields:
                    if reg.is_field_ungrouped(cand) or is_field_excluded_from_mapping(sn_clean, cand, cid, custom_data):
                        continue
                    mqtt_candidates.append(cand)
                for cand in m.modbus_fields:
                    if reg.is_field_ungrouped(cand) or is_field_excluded_from_mapping(sn_clean, cand, cid, custom_data):
                        continue
                    parts = cand.split(".")
                    if len(parts) >= 2 and re.match(r"^model_\d+$", parts[1]):
                        mb_alias.append(cand)
                    else:
                        mb_canonical.append(cand)

            override_members: List[str] = []
            for ov_k, ov_tgt in field_overrides.items():
                if ov_tgt != cid:
                    continue
                if ":" in ov_k:
                    ov_sn, ov_fk = ov_k.split(":", 1)
                    if ov_sn.strip().upper() != sn_clean:
                        continue
                else:
                    ov_fk = ov_k
                ov_fk = ov_fk.strip()
                if ov_fk.startswith(f"{dev.device_type}.") and ov_fk not in override_members:
                    override_members.append(ov_fk)

            all_non_excluded = mqtt_candidates + mb_canonical + mb_alias + override_members
            if not any(cand in dev.fields for cand in all_non_excluded) and all_non_excluded:
                primary_cand = (mqtt_candidates or mb_canonical or mb_alias or override_members)[0]
                state_store.ensure_field_definition(dev.serial_number, primary_cand)
        elif is_group_wildcard_key(f_path):
            # Expand against any concrete subgroup instances already discovered on dev (never create a literal '*' field)
            p_parts = f_path.split(".")
            model_sub = p_parts[1]
            pt_leaf = p_parts[-1]
            existing_group_paths = {
                f.group_path
                for f in dev.fields.values()
                if f.group_path
                and f.key
                and "." in f.key
                and f.key.split(".")[1] == model_sub
                and group_wildcard_matches_field_key(f_path, f"{dev.device_type}.{model_sub}.{f.group_path}.{pt_leaf}")
            }
            for gp in sorted(existing_group_paths):
                concrete_path = f"{dev.device_type}.{model_sub}.{gp}.{pt_leaf}"
                if concrete_path not in dev.fields:
                    state_store.ensure_field_definition(dev.serial_number, concrete_path)
        elif f_path not in dev.fields:
            state_store.ensure_field_definition(dev.serial_number, f_path)


def collect_compound_member_keys(
    sn_clean: str,
    c_view: Any,
    reg: Any = None,
    custom_data: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """Collect qualified '<SN>:<field_key>' member keys actively governed by a compound view."""
    from .mapping import MappingRegistry
    from .grouping import is_field_excluded_from_mapping, load_custom_groupings

    reg = reg or MappingRegistry.get_instance()
    custom_data = custom_data if custom_data is not None else load_custom_groupings()
    cid = getattr(c_view, "concept_key", "") or ""
    members: Set[str] = set()

    if getattr(c_view, "mqtt_key", None):
        members.add(f"{sn_clean}:{c_view.mqtt_key}")
    for s in getattr(c_view, "sources", []):
        if getattr(s, "field_key", None):
            members.add(f"{sn_clean}:{s.field_key}")
    for cand in getattr(c_view, "modbus_candidates", []):
        if not reg.is_field_ungrouped(cand) and not is_field_excluded_from_mapping(sn_clean, cand, cid, custom_data):
            members.add(f"{sn_clean}:{cand}")

    m_def = reg.get_by_id(cid)
    if m_def:
        for mf in (list(m_def.mqtt_fields) + list(m_def.modbus_fields)):
            if not reg.is_field_ungrouped(mf) and not is_field_excluded_from_mapping(sn_clean, mf, cid, custom_data):
                members.add(f"{sn_clean}:{mf}")

    for ov_k, ov_tgt in (custom_data.get("field_overrides", {}) or {}).items():
        if ov_tgt != cid:
            continue
        if ":" in ov_k:
            ov_sn, ov_fk = ov_k.split(":", 1)
            if ov_sn.strip().upper() != sn_clean:
                continue
        else:
            ov_fk = ov_k
        members.add(f"{sn_clean}:{ov_fk.strip()}")

    return members


def is_raw_field_suppressed(
    sn_clean: str,
    field_key: str,
    field_compound_key: Optional[str],
    active_compounds: Set[str],
    active_members: Set[str],
    reg: Any = None,
    custom_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True if a raw field is covered by an active parent compound entity."""
    from .mapping import MappingRegistry
    from .grouping import is_field_excluded_from_mapping, load_custom_groupings

    if f"{sn_clean}:{field_key}" in active_members:
        return True

    reg = reg or MappingRegistry.get_instance()
    custom_data = custom_data if custom_data is not None else load_custom_groupings()

    for comp_cand in (field_compound_key, reg.get_raw_to_compound_map().get(field_key)):
        if not comp_cand:
            continue
        if f"{sn_clean}:{comp_cand}" not in active_compounds:
            continue
        cid = comp_cand.split(".")[-1]
        if not reg.is_field_ungrouped(field_key) and not is_field_excluded_from_mapping(sn_clean, field_key, cid, custom_data):
            return True

    return False
