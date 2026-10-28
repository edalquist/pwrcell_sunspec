"""Safety Enforcement & Blocked Mutation Fields for PWRcell SunSpec.

Enforces system-level mutation locks on sensitive Modbus registers (e.g. grid trip
thresholds, factory calibration, inverter safety disconnect limits, internal battery cutoffs).

SECURITY & SAFETY ARCHITECTURE:
- Any field listed in `config/blocked_fields.yaml` (or `/data/blocked_fields.yaml` in HA Add-on)
  is strictly blocked from mutation via controls.py, Web UI, and MQTT bridge.
- The ONLY way to unblock a field is for a human operator to MANUALLY edit the configuration
  file on the host filesystem.
- Intentionally NO REST API endpoint or UI action exists to modify or unblock these fields.
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

_BLOCKED_FIELDS_CACHE: Optional[List[str]] = None
_BLOCKED_FIELDS_MTIME: Optional[float] = None
_BLOCKED_FIELDS_LOADED_PATH: Optional[Path] = None


def get_blocked_fields_path() -> Path:
    """Return the filesystem path to blocked_fields.yaml."""
    return Path(_getConfigPath(DEFAULT_BLOCKED_FIELDS_FILE))


def clear_blocked_fields_cache() -> None:
    """Clear in-memory cache of blocked fields."""
    global _BLOCKED_FIELDS_CACHE, _BLOCKED_FIELDS_MTIME, _BLOCKED_FIELDS_LOADED_PATH
    _BLOCKED_FIELDS_CACHE = None
    _BLOCKED_FIELDS_MTIME = None
    _BLOCKED_FIELDS_LOADED_PATH = None


def load_blocked_fields(config_path: Optional[Path | str] = None) -> List[str]:
    """Load blocked mutation patterns from blocked_fields.yaml.

    Automatically refreshes if the underlying file modification timestamp changes,
    allowing operator edits on disk to take immediate effect without application restart.
    """
    global _BLOCKED_FIELDS_CACHE, _BLOCKED_FIELDS_MTIME, _BLOCKED_FIELDS_LOADED_PATH

    path = Path(config_path) if config_path else get_blocked_fields_path()

    if not path.exists():
        return []

    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        current_mtime = 0.0

    if (
        _BLOCKED_FIELDS_CACHE is not None
        and _BLOCKED_FIELDS_LOADED_PATH == path
        and _BLOCKED_FIELDS_MTIME == current_mtime
    ):
        return list(_BLOCKED_FIELDS_CACHE)

    patterns: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        raw_list: Any = []
        if isinstance(data, dict):
            raw_list = data.get("blocked_fields") or data.get("blocked_mutation_fields") or []
        elif isinstance(data, list):
            raw_list = data

        if isinstance(raw_list, list):
            for item in raw_list:
                if item and isinstance(item, str):
                    clean = item.strip()
                    if clean and not clean.startswith("#"):
                        patterns.append(clean)
    except Exception as e:
        logger.error("Failed to load blocked fields from %s: %s", path, e)
        if _BLOCKED_FIELDS_CACHE is not None:
            return list(_BLOCKED_FIELDS_CACHE)
        return []

    _BLOCKED_FIELDS_CACHE = list(patterns)
    _BLOCKED_FIELDS_MTIME = current_mtime
    _BLOCKED_FIELDS_LOADED_PATH = path
    return list(patterns)


def _extract_field_candidates(field_or_key: Any, device_sn: Optional[str] = None) -> Set[str]:
    """Extract all string representation candidates for a field for pattern matching."""
    candidates: Set[str] = set()

    if isinstance(field_or_key, str):
        raw_key = field_or_key.strip()
        candidates.add(raw_key)
        # Strip serial number prefix if present (e.g. 0001000714E9:inverter.inverter.AMax)
        if ":" in raw_key:
            prefix_sn, stripped = raw_key.split(":", 1)
            candidates.add(stripped)
            raw_key = stripped
        # Point name is usually the last segment
        if "." in raw_key:
            parts = raw_key.split(".")
            candidates.add(parts[-1])
            if len(parts) >= 2:
                candidates.add(f"{parts[-2]}.{parts[-1]}")
            if len(parts) >= 3:
                candidates.add(f"{parts[0]}.{parts[1]}.{parts[-1]}")
        return candidates

    # Object handling (StateField, UnifiedFieldGroup, CompoundFieldView, etc.)
    f = field_or_key

    # Check key / field_key / id / mapping_id / name
    for attr in ("key", "field_key", "id", "mapping_id", "name", "concept_key"):
        val = getattr(f, attr, None)
        if val and isinstance(val, str):
            clean = val.strip()
            candidates.add(clean)
            if ":" in clean:
                clean_stripped = clean.split(":", 1)[1]
                candidates.add(clean_stripped)
            if "." in clean:
                candidates.add(clean.split(".")[-1])

    dev_type = getattr(f, "device_type", None) or ""
    model_name = getattr(f, "model_name", None) or ""
    model_id = getattr(f, "model_id", None)
    pt_name = getattr(f, "name", None) or ""

    if pt_name:
        candidates.add(pt_name)
        if model_name:
            candidates.add(f"{model_name}.{pt_name}")
            if dev_type:
                candidates.add(f"{dev_type}.{model_name}.{pt_name}")
        if model_id is not None:
            candidates.add(f"model_{model_id}.{pt_name}")
            if dev_type:
                candidates.add(f"{dev_type}.model_{model_id}.{pt_name}")
        if dev_type:
            candidates.add(f"{dev_type}.{pt_name}")

    # Inspect sources if UnifiedFieldGroup
    if hasattr(f, "sources") and isinstance(f.sources, list):
        for s in f.sources:
            s_key = getattr(s, "field_key", None)
            s_name = getattr(s, "name", None)
            if s_key:
                candidates.add(s_key)
            if s_name:
                candidates.add(s_name)

    # Inspect modbus candidates if CompoundFieldView
    if hasattr(f, "modbus_key") and f.modbus_key:
        candidates.add(f.modbus_key)
    if hasattr(f, "modbus_candidates") and isinstance(f.modbus_candidates, list):
        for mc in f.modbus_candidates:
            if mc:
                candidates.add(mc)

    return candidates


def get_matched_blocked_pattern(
    field_or_key: Any,
    device_sn: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> Optional[str]:
    """Return the blocked pattern that matches field_or_key, or None if not blocked."""
    patterns = load_blocked_fields(config_path)
    if not patterns:
        return None

    candidates = _extract_field_candidates(field_or_key, device_sn=device_sn)
    lower_candidates = [c.lower() for c in candidates]

    for pat in patterns:
        pat_lower = pat.lower()
        point_pat = pat_lower[2:] if pat_lower.startswith("*.") else None
        for cand in lower_candidates:
            if cand == pat_lower or fnmatch.fnmatchcase(cand, pat_lower) or (point_pat and cand == point_pat):
                return pat
    return None


def is_mutation_blocked(
    field_or_key: Any,
    device_sn: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> bool:
    """Return True if mutation of field_or_key is blocked by safety configuration."""
    return get_matched_blocked_pattern(field_or_key, device_sn=device_sn, config_path=config_path) is not None


def get_blocked_mutation_fields(
    state_store: Optional[Any] = None,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Audit and list all fields where Modbus allows writes, but mutation is blocked for safety."""
    path = Path(config_path) if config_path else get_blocked_fields_path()
    patterns = load_blocked_fields(path)

    blocked_items: List[Dict[str, Any]] = []

    if state_store and hasattr(state_store, "devices"):
        for dev in state_store.devices.values():
            dev_sn = getattr(dev, "serial_number", "")
            dev_type = getattr(dev, "device_type", "")
            for f_key, f in list(dev.fields.items()):
                if f.access == "RW" or getattr(f, "is_writable", False):
                    matched = get_matched_blocked_pattern(f, device_sn=dev_sn, config_path=path)
                    if matched:
                        blocked_items.append({
                            "key": f_key,
                            "name": f.name,
                            "label": f.label or f.name,
                            "device_sn": dev_sn,
                            "device_type": dev_type,
                            "model_id": f.model_id,
                            "model_name": f.model_name,
                            "access": f.access,
                            "matched_pattern": matched,
                        })

        # Also inspect compound views
        for c_id, c_view in list(getattr(state_store, "compound_views", {}).items()):
            if c_view.is_writable or c_view.access == "RW":
                matched = get_matched_blocked_pattern(c_view, config_path=path)
                if matched:
                    blocked_items.append({
                        "key": f"compound.{c_id}",
                        "name": c_id,
                        "label": c_view.label or c_id,
                        "device_sn": "COMPOUND",
                        "device_type": "compound",
                        "model_id": None,
                        "model_name": "compound",
                        "access": "RW",
                        "matched_pattern": matched,
                    })

    return {
        "status": "ok",
        "config_path": str(path),
        "patterns_count": len(patterns),
        "patterns": patterns,
        "blocked_count": len(blocked_items),
        "blocked_fields": blocked_items,
        "unblock_instruction": (
            "To unblock mutation of any field, manually edit config/blocked_fields.yaml "
            "on the host filesystem and remove or comment out the blocked entry. "
            "No API or Web UI unblock option is permitted."
        ),
    }
