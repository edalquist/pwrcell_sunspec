"""Custom bounds configuration, normalization, and validation for mutable fields."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml

from .config import _getConfigPath, is_addon_data_env, data_dir

logger = logging.getLogger(__name__)

_CUSTOM_BOUNDS_CACHE: Dict[str, Any] = {
    "mtime": {},
    "data": None,
}


def clear_custom_bounds_cache() -> None:
    """Clear in-memory custom bounds cache."""
    _CUSTOM_BOUNDS_CACHE["mtime"] = {}
    _CUSTOM_BOUNDS_CACHE["data"] = None


def normalize_bounds(raw_cfg: Any) -> Optional[Dict[str, Any]]:
    """Normalize user-specified bounds into {'min_value': float, 'max_value': float, 'step': float}.

    Supports:
      - dict: {'min': 0, 'max': 35, 'step': 0.1} or {'min_value': 0, 'max_value': 35}
      - list/tuple: [0, 35] or [0, 35, 0.1]
      - scalar: 35 (interpreted as max_value=35)
    """
    if raw_cfg is None:
        return None

    min_v: Optional[float] = None
    max_v: Optional[float] = None
    step_v: Optional[float] = None

    if isinstance(raw_cfg, (list, tuple)):
        if len(raw_cfg) > 0 and raw_cfg[0] is not None:
            try:
                min_v = float(raw_cfg[0])
            except (ValueError, TypeError):
                pass
        if len(raw_cfg) > 1 and raw_cfg[1] is not None:
            try:
                max_v = float(raw_cfg[1])
            except (ValueError, TypeError):
                pass
        if len(raw_cfg) > 2 and raw_cfg[2] is not None:
            try:
                step_v = float(raw_cfg[2])
            except (ValueError, TypeError):
                pass
    elif isinstance(raw_cfg, dict):
        raw_min = raw_cfg.get("min", raw_cfg.get("min_value"))
        raw_max = raw_cfg.get("max", raw_cfg.get("max_value"))
        raw_step = raw_cfg.get("step")

        if raw_min is not None:
            try:
                min_v = float(raw_min)
            except (ValueError, TypeError):
                pass
        if raw_max is not None:
            try:
                max_v = float(raw_max)
            except (ValueError, TypeError):
                pass
        if raw_step is not None:
            try:
                step_v = float(raw_step)
            except (ValueError, TypeError):
                pass
    elif isinstance(raw_cfg, (int, float)):
        max_v = float(raw_cfg)
    else:
        return None

    if min_v is None and max_v is None and step_v is None:
        return None

    return {
        "min_value": min_v,
        "max_value": max_v,
        "step": step_v,
    }


def _get_potential_config_paths() -> List[Path]:
    """Return ordered list of files that can supply custom bounds."""
    from .grouping import get_default_grouping_config_path
    from .ha import get_default_ha_config_path, get_default_seed_config_path

    paths: List[Path] = []

    # 1. custom_groupings.yaml
    try:
        p_grp = get_default_grouping_config_path()
        if p_grp and p_grp.exists() and p_grp not in paths:
            paths.append(p_grp)
    except Exception:
        pass

    # 2. ha_config.yaml & ha_default_config.yaml
    try:
        p_ha = get_default_ha_config_path()
        if p_ha and p_ha.exists() and p_ha not in paths:
            paths.append(p_ha)
    except Exception:
        pass

    try:
        p_seed = get_default_seed_config_path()
        if p_seed and p_seed.exists() and p_seed not in paths:
            paths.append(p_seed)
    except Exception:
        pass

    # 3. pwrcell.yaml / config.yaml
    try:
        p_cfg = Path(_getConfigPath("pwrcell.yaml"))
        if p_cfg.exists() and p_cfg not in paths:
            paths.append(p_cfg)
    except Exception:
        pass

    return paths


def load_custom_bounds(config_path: Optional[Path | str] = None) -> Dict[str, Dict[str, Any]]:
    """Load and normalize custom field bounds across configuration files.

    Returns a dict mapping field identifier to normalized bounds:
      {'battery.battery.AChaMax': {'min_value': 0.0, 'max_value': 35.0, 'step': None}, ...}
    """
    if config_path:
        p = Path(config_path)
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}
                if isinstance(raw_data, dict):
                    bounds_map = raw_data.get("custom_bounds") or raw_data.get("field_bounds") or {}
                    out: Dict[str, Dict[str, Any]] = {}
                    for k, v in bounds_map.items():
                        norm = normalize_bounds(v)
                        if norm:
                            out[str(k).strip()] = norm
                    return out
        except Exception as e:
            logger.error("Failed loading custom bounds from %s: %s", p, e)
            return {}

    # Check cached mtimes
    paths = _get_potential_config_paths()
    current_mtimes = {str(p): p.stat().st_mtime for p in paths if p.exists()}
    if (
        _CUSTOM_BOUNDS_CACHE["data"] is not None
        and _CUSTOM_BOUNDS_CACHE["mtime"] == current_mtimes
    ):
        return dict(_CUSTOM_BOUNDS_CACHE["data"])

    merged: Dict[str, Dict[str, Any]] = {}
    # Iterate in reverse order so higher-priority files overwrite lower-priority
    for p in reversed(paths):
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
                if isinstance(doc, dict):
                    bounds_map = doc.get("custom_bounds") or doc.get("field_bounds") or {}
                    if isinstance(bounds_map, dict):
                        for k, v in bounds_map.items():
                            norm = normalize_bounds(v)
                            if norm:
                                merged[str(k).strip()] = norm
        except Exception as e:
            logger.warning("Error reading custom bounds from %s: %s", p, e)

    _CUSTOM_BOUNDS_CACHE["mtime"] = current_mtimes
    _CUSTOM_BOUNDS_CACHE["data"] = merged
    return dict(merged)


def get_custom_bounds(
    field_key: str,
    device_sn: Optional[str] = None,
    point_name: Optional[str] = None,
    custom_bounds_dict: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Look up custom bounds for a field by candidate identifiers.

    Matches in priority order:
      1. <SERIAL>:<field_key>
      2. <SERIAL>:<point_name>
      3. <field_key>
      4. <device_type>.<point_name>
      5. <point_name>
    """
    bounds_map = custom_bounds_dict if custom_bounds_dict is not None else load_custom_bounds()
    if not bounds_map:
        return None

    clean_sn = device_sn.strip().upper() if device_sn else ""
    f_key = (field_key or "").strip()
    pt_name = (point_name or "").strip()

    candidates: List[str] = []

    # 1. Device-specific matches
    if clean_sn:
        if f_key:
            candidates.append(f"{clean_sn}:{f_key}")
        if pt_name:
            candidates.append(f"{clean_sn}:{pt_name}")

    # 2. Exact field key
    if f_key:
        candidates.append(f_key)
        if ":" in f_key:
            sn_part, rest = f_key.split(":", 1)
            candidates.append(rest.strip())

    # 3. Model-agnostic key: device_type.point_name
    if f_key and "." in f_key:
        parts = f_key.split(".")
        dev_type = parts[0]
        actual_pt = parts[-1]
        candidates.append(f"{dev_type}.{actual_pt}")
        candidates.append(actual_pt)

    # 4. Standalone point name
    if pt_name:
        candidates.append(pt_name)

    # Direct match check
    for cand in candidates:
        if cand in bounds_map:
            return dict(bounds_map[cand])

    # Case-insensitive fallback match
    lower_map = {k.lower(): v for k, v in bounds_map.items()}
    for cand in candidates:
        if cand.lower() in lower_map:
            return dict(lower_map[cand.lower()])

    # Model-agnostic check: e.g. 'battery.battery.AChaMax' in bounds_map matches 'battery.model_802.AChaMax'
    if pt_name and f_key and "." in f_key:
        dev_type = f_key.split(".")[0].lower()
        target_pt = pt_name.lower()
        for k, v in bounds_map.items():
            clean_k = (k.split(":", 1)[-1] if ":" in k else k).lower()
            parts = clean_k.split(".")
            if len(parts) >= 3 and parts[0] == dev_type and parts[-1] == target_pt:
                return dict(v)

    return None


def save_custom_bound(
    field_key: str,
    bounds: Optional[Union[Dict[str, Any], List[Any], Tuple[Any, ...]]],
    device_sn: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> None:
    """Save or remove custom bounds for a field in custom_groupings.yaml."""
    from .grouping import get_default_grouping_config_path

    target_path = Path(config_path) if config_path else get_default_grouping_config_path()
    raw_data: Dict[str, Any] = {}
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}
                if not isinstance(raw_data, dict):
                    raw_data = {}
        except Exception as e:
            logger.error("Failed reading %s: %s", target_path, e)

    custom_bounds = dict(raw_data.get("custom_bounds", {}) or {})
    fk = field_key.strip()
    if ":" in fk:
        prefix, rest = fk.split(":", 1)
        if not device_sn and len(prefix) >= 8:
            device_sn = prefix
        fk = rest

    clean_k = f"{device_sn.strip().upper()}:{fk}" if device_sn else fk

    if bounds is None:
        custom_bounds.pop(clean_k, None)
        custom_bounds.pop(fk, None)
        if device_sn:
            custom_bounds.pop(f"{device_sn.strip().upper()}:{fk}", None)
    else:
        norm = normalize_bounds(bounds)
        if norm:
            custom_bounds[clean_k] = norm
        else:
            custom_bounds.pop(clean_k, None)
            custom_bounds.pop(fk, None)

    raw_data["custom_bounds"] = custom_bounds
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(raw_data, f, default_flow_style=False, sort_keys=False)
    tmp_path.replace(target_path)

    clear_custom_bounds_cache()
    logger.info("Saved custom bounds for %s to %s", clean_k, target_path)
