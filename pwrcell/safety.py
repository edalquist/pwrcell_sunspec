"""Safety Enforcement & Blocked Mutation Fields for PWRcell SunSpec.

Enforces system-level mutation locks on sensitive Modbus registers (e.g. grid trip
thresholds, factory calibration, inverter safety disconnect limits, internal battery cutoffs).

SECURITY & SAFETY ARCHITECTURE:
- Default blocked patterns live in `config/blocked_fields.yaml` (or `/data/blocked_fields.yaml`
  in HA Add-on if customized directly).
- Out-of-band positive (`blocked_fields`) and negative (`unblocked_fields`) overrides can be
  configured in the Home Assistant Add-on Configuration UI (synced to `/data/pwrcell.yaml`) or
  in standalone `config/pwrcell.yaml` / `config/blocked_fields.yaml`.
- Intentionally NO REST API endpoint or Web Explorer UI action exists to modify or unblock fields.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from .config import _getConfigPath

logger = logging.getLogger(__name__)

DEFAULT_BLOCKED_FIELDS_FILE = "blocked_fields.yaml"
DEFAULT_OVERRIDES_CONFIG_FILE = "pwrcell.yaml"

# Resolved path -> ((st_mtime_ns, st_size), blocked_patterns, unblocked_patterns)
_YAML_SAFETY_CACHE: Dict[Path, Tuple[Tuple[int, int], List[str], List[str]]] = {}


def get_blocked_fields_path() -> Path:
    """Return the filesystem path to blocked_fields.yaml."""
    return Path(_getConfigPath(DEFAULT_BLOCKED_FIELDS_FILE))


def get_safety_overrides_path() -> Optional[Path]:
    """Return the filesystem path to pwrcell.yaml if it exists for safety overrides."""
    p = Path(_getConfigPath(DEFAULT_OVERRIDES_CONFIG_FILE))
    return p if p.exists() else None


def clear_blocked_fields_cache() -> None:
    """Clear in-memory cache of blocked and unblocked safety patterns."""
    _YAML_SAFETY_CACHE.clear()


def _normalize_pattern_list(raw_list: Any) -> List[str]:
    """Strip comments/whitespace and deduplicate pattern strings preserving order."""
    patterns: List[str] = []
    seen: Set[str] = set()
    if not isinstance(raw_list, list):
        return patterns
    for item in raw_list:
        if item and isinstance(item, str):
            clean = item.strip()
            if clean and not clean.startswith("#") and clean not in seen:
                seen.add(clean)
                patterns.append(clean)
    return patterns


def _read_yaml_safety_lists(path: Path) -> Tuple[List[str], List[str]]:
    """Read (blocked_fields, unblocked_fields) from a YAML file with stat-based caching."""
    if not path.exists():
        return [], []

    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    try:
        st = path.stat()
        stat_token = (st.st_mtime_ns, st.st_size)
    except OSError:
        stat_token = (0, 0)

    cached = _YAML_SAFETY_CACHE.get(resolved)
    if cached is not None and cached[0] == stat_token:
        return list(cached[1]), list(cached[2])

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if isinstance(data, dict):
            raw_blocked = data.get("blocked_fields") or data.get("blocked_mutation_fields") or []
            raw_unblocked = data.get("unblocked_fields") or data.get("unblocked_mutation_fields") or []
        elif isinstance(data, list):
            raw_blocked = data
            raw_unblocked = []
        else:
            raw_blocked = []
            raw_unblocked = []

        blocked = _normalize_pattern_list(raw_blocked)
        unblocked = _normalize_pattern_list(raw_unblocked)
    except Exception as e:
        logger.error("Failed to load safety rules from %s: %s", path, e)
        if cached is not None:
            return list(cached[1]), list(cached[2])
        return [], []

    _YAML_SAFETY_CACHE[resolved] = (stat_token, blocked, unblocked)
    return list(blocked), list(unblocked)


def _merge_unique(first: List[str], second: List[str]) -> List[str]:
    out = list(first)
    seen = set(first)
    for item in second:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def load_safety_rules(
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> Dict[str, List[str]]:
    """Load layered safety rules from blocked_fields.yaml and optional pwrcell.yaml overrides."""
    base_path = Path(config_path) if config_path else get_blocked_fields_path()
    base_blocked, base_unblocked = _read_yaml_safety_lists(base_path)

    extra_blocked: List[str] = []
    extra_unblocked: List[str] = []

    ov_path: Optional[Path] = None
    if overrides_path is not None:
        ov_path = Path(overrides_path)
    elif config_path is None:
        ov_path = get_safety_overrides_path()

    if ov_path is not None and ov_path.exists():
        try:
            same_file = ov_path.resolve() == base_path.resolve()
        except OSError:
            same_file = ov_path == base_path
        if not same_file:
            extra_blocked, extra_unblocked = _read_yaml_safety_lists(ov_path)

    return {
        "base_blocked": base_blocked,
        "extra_blocked": extra_blocked,
        "blocked": _merge_unique(base_blocked, extra_blocked),
        "base_unblocked": base_unblocked,
        "extra_unblocked": extra_unblocked,
        "unblocked": _merge_unique(base_unblocked, extra_unblocked),
    }


def load_blocked_fields(
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> List[str]:
    """Load combined blocked mutation patterns (defaults + positive overrides)."""
    return load_safety_rules(config_path=config_path, overrides_path=overrides_path)["blocked"]


def load_unblocked_fields(
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> List[str]:
    """Load combined unblocked mutation patterns (negative overrides)."""
    return load_safety_rules(config_path=config_path, overrides_path=overrides_path)["unblocked"]


def _extract_plain_and_scoped_candidates(
    field_or_key: Any,
    device_sn: Optional[str] = None,
) -> Tuple[Set[str], Set[str]]:
    """Extract plain (unscoped) and serial-scoped ('<SN>:<cand>') candidate strings."""
    plain: Set[str] = set()
    scoped: Set[str] = set()

    def _add_dotted_variants(raw_str: str) -> None:
        clean = raw_str.strip()
        if not clean:
            return
        plain.add(clean)
        if "." in clean:
            parts = clean.split(".")
            plain.add(parts[-1])
            if len(parts) >= 2:
                plain.add(f"{parts[-2]}.{parts[-1]}")
            if len(parts) >= 3:
                plain.add(f"{parts[0]}.{parts[1]}.{parts[-1]}")

    if isinstance(field_or_key, str):
        raw_key = field_or_key.strip()
        sn_upper = device_sn.strip().upper() if device_sn else ""
        if ":" in raw_key:
            prefix_sn, stripped = raw_key.split(":", 1)
            if not sn_upper and prefix_sn.strip():
                sn_upper = prefix_sn.strip().upper()
            _add_dotted_variants(stripped)
        else:
            _add_dotted_variants(raw_key)
        if sn_upper:
            for p in plain:
                scoped.add(f"{sn_upper}:{p}")
        return plain, scoped

    # Object handling (StateField, UnifiedFieldGroup, CompoundFieldView, etc.)
    f = field_or_key
    sn_val = device_sn or getattr(f, "device_sn", None) or ""
    sn_upper = str(sn_val).strip().upper()

    for attr in ("key", "field_key", "id", "mapping_id", "name", "concept_key"):
        val = getattr(f, attr, None)
        if val and isinstance(val, str):
            clean = val.strip()
            if ":" in clean:
                p_sn, clean_stripped = clean.split(":", 1)
                if not sn_upper and p_sn.strip():
                    sn_upper = p_sn.strip().upper()
                _add_dotted_variants(clean_stripped)
            else:
                _add_dotted_variants(clean)

    dev_type = getattr(f, "device_type", None) or ""
    model_name = getattr(f, "model_name", None) or ""
    model_id = getattr(f, "model_id", None)
    pt_name = getattr(f, "name", None) or ""

    if pt_name:
        plain.add(pt_name)
        if model_name:
            plain.add(f"{model_name}.{pt_name}")
            if dev_type:
                plain.add(f"{dev_type}.{model_name}.{pt_name}")
        if model_id is not None:
            plain.add(f"model_{model_id}.{pt_name}")
            if dev_type:
                plain.add(f"{dev_type}.model_{model_id}.{pt_name}")
        if dev_type:
            plain.add(f"{dev_type}.{pt_name}")

    # Inspect sources if UnifiedFieldGroup
    if hasattr(f, "sources") and isinstance(f.sources, list):
        for s in f.sources:
            s_key = getattr(s, "field_key", None)
            s_name = getattr(s, "name", None)
            if s_key:
                _add_dotted_variants(str(s_key))
            if s_name:
                plain.add(str(s_name).strip())

    # Inspect modbus candidates if CompoundFieldView
    if hasattr(f, "modbus_key") and f.modbus_key:
        _add_dotted_variants(str(f.modbus_key))
    if hasattr(f, "modbus_candidates") and isinstance(f.modbus_candidates, list):
        for mc in f.modbus_candidates:
            if mc:
                _add_dotted_variants(str(mc))

    if sn_upper:
        for p in plain:
            scoped.add(f"{sn_upper}:{p}")

    return plain, scoped


def _extract_field_candidates(field_or_key: Any, device_sn: Optional[str] = None) -> Set[str]:
    """Extract all string representation candidates for a field for pattern matching."""
    plain, scoped = _extract_plain_and_scoped_candidates(field_or_key, device_sn=device_sn)
    return plain | scoped


def _match_pattern(
    plain_lower: List[str],
    scoped_lower: List[str],
    patterns: List[str],
) -> Optional[str]:
    """Return the first pattern matching plain (or serial-scoped) candidates, else None."""
    for pat in patterns:
        pat_lower = pat.lower()
        if ":" in pat_lower:
            for cand in scoped_lower:
                if cand == pat_lower or fnmatch.fnmatchcase(cand, pat_lower):
                    return pat
        else:
            point_pat = pat_lower[2:] if pat_lower.startswith("*.") else None
            for cand in plain_lower:
                if cand == pat_lower or fnmatch.fnmatchcase(cand, pat_lower) or (point_pat and cand == point_pat):
                    return pat
    return None


def get_matched_unblocked_pattern(
    field_or_key: Any,
    device_sn: Optional[str] = None,
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> Optional[str]:
    """Return the negative override pattern matching field_or_key, or None."""
    rules = load_safety_rules(config_path=config_path, overrides_path=overrides_path)
    if not rules["unblocked"]:
        return None
    plain, scoped = _extract_plain_and_scoped_candidates(field_or_key, device_sn=device_sn)
    return _match_pattern(
        [c.lower() for c in plain],
        [c.lower() for c in scoped],
        rules["unblocked"],
    )


def get_matched_blocked_pattern(
    field_or_key: Any,
    device_sn: Optional[str] = None,
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> Optional[str]:
    """Return the effective blocked pattern matching field_or_key, or None if allowed/unblocked."""
    rules = load_safety_rules(config_path=config_path, overrides_path=overrides_path)
    if not rules["blocked"]:
        return None

    plain, scoped = _extract_plain_and_scoped_candidates(field_or_key, device_sn=device_sn)
    plain_lower = [c.lower() for c in plain]
    scoped_lower = [c.lower() for c in scoped]

    matched_block = _match_pattern(plain_lower, scoped_lower, rules["blocked"])
    if not matched_block:
        return None

    if rules["unblocked"] and _match_pattern(plain_lower, scoped_lower, rules["unblocked"]):
        return None

    return matched_block


def is_mutation_blocked(
    field_or_key: Any,
    device_sn: Optional[str] = None,
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> bool:
    """Return True if mutation of field_or_key is blocked by safety configuration."""
    return (
        get_matched_blocked_pattern(
            field_or_key,
            device_sn=device_sn,
            config_path=config_path,
            overrides_path=overrides_path,
        )
        is not None
    )


def get_blocked_mutation_fields(
    state_store: Optional[Any] = None,
    config_path: Optional[Path | str] = None,
    overrides_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Audit all RW fields blocked for safety as well as any overridden/unblocked items."""
    path = Path(config_path) if config_path else get_blocked_fields_path()
    ov_path = Path(overrides_path) if overrides_path else (get_safety_overrides_path() if config_path is None else None)
    rules = load_safety_rules(config_path=path, overrides_path=ov_path)

    patterns = rules["blocked"]
    base_pattern_set = set(rules["base_blocked"])
    unblocked_patterns = rules["unblocked"]

    blocked_items: List[Dict[str, Any]] = []
    unblocked_items: List[Dict[str, Any]] = []

    def _classify_target(target_obj: Any, item_meta: Dict[str, Any], dev_sn: str) -> None:
        if not patterns:
            return
        plain, scoped = _extract_plain_and_scoped_candidates(target_obj, device_sn=dev_sn)
        plain_lower = [c.lower() for c in plain]
        scoped_lower = [c.lower() for c in scoped]
        matched_block = _match_pattern(plain_lower, scoped_lower, patterns)
        if not matched_block:
            return
        matched_unblock = _match_pattern(plain_lower, scoped_lower, unblocked_patterns) if unblocked_patterns else None
        if matched_unblock:
            unblocked_items.append({
                **item_meta,
                "matched_block_pattern": matched_block,
                "matched_unblock_pattern": matched_unblock,
            })
        else:
            blocked_items.append({
                **item_meta,
                "matched_pattern": matched_block,
                "source": "default" if matched_block in base_pattern_set else "override",
            })

    if state_store and hasattr(state_store, "devices"):
        for dev in state_store.devices.values():
            dev_sn = getattr(dev, "serial_number", "")
            dev_type = getattr(dev, "device_type", "")
            for f_key, f in list(dev.fields.items()):
                if f.access == "RW" or getattr(f, "is_writable", False):
                    _classify_target(
                        f,
                        {
                            "key": f_key,
                            "name": f.name,
                            "label": f.label or f.name,
                            "device_sn": dev_sn,
                            "device_type": dev_type,
                            "model_id": f.model_id,
                            "model_name": f.model_name,
                            "access": f.access,
                        },
                        dev_sn,
                    )

        # Also inspect compound views
        if hasattr(state_store, "get_compound_views"):
            for c_view in state_store.get_compound_views():
                has_writable_src = any(getattr(s, "is_writable", False) for s in getattr(c_view, "sources", []) or [])
                if getattr(c_view, "is_writable", False) or getattr(c_view, "access", "R") == "RW" or has_writable_src:
                    dev_sn = getattr(c_view, "device_sn", None) or "COMPOUND"
                    c_id = getattr(c_view, "concept_key", None) or getattr(c_view, "mapping_id", "")
                    _classify_target(
                        c_view,
                        {
                            "key": getattr(c_view, "key", f"compound.{c_id}"),
                            "name": c_id,
                            "label": getattr(c_view, "label", c_id) or c_id,
                            "device_sn": dev_sn,
                            "device_type": getattr(c_view, "device_type", "compound") or "compound",
                            "model_id": None,
                            "model_name": "compound",
                            "access": "RW",
                        },
                        dev_sn,
                    )

    return {
        "status": "ok",
        "config_path": str(path),
        "overrides_path": str(ov_path) if ov_path else None,
        "patterns_count": len(patterns),
        "patterns": patterns,
        "base_patterns": rules["base_blocked"],
        "extra_blocked_patterns": rules["extra_blocked"],
        "unblocked_patterns": unblocked_patterns,
        "blocked_count": len(blocked_items),
        "blocked_fields": blocked_items,
        "unblocked_count": len(unblocked_items),
        "unblocked_fields": unblocked_items,
        "unblock_instruction": (
            "In Home Assistant, configure 'blocked_fields' (positive block overrides) and "
            "'unblocked_fields' (negative unblock overrides) in the Add-on Configuration tab and restart. "
            "For standalone installs, manually edit config/blocked_fields.yaml (or set blocked_fields / "
            "unblocked_fields in config/pwrcell.yaml). No Web Explorer or REST API unblock option is permitted."
        ),
    }
