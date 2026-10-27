"""Configurable Telemetry and Modbus Mapping Registry for Generac PWRcell (v3).

Manages user-configurable links between internal MQTT push protobuf metrics
and SunSpec Modbus registers, persisted to telemetry_mappings.yaml.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
try:
    import yaml
except ImportError:
    yaml = None

from .catalog import infer_ha_classes
from .config import data_dir, is_addon_data_env

logger = logging.getLogger(__name__)

DEFAULT_GROUPINGS_FILE = "groupings.yaml"
LEGACY_MAPPINGS_FILE = "telemetry_mappings.yaml"
DEFAULT_MAPPINGS_FILE = DEFAULT_GROUPINGS_FILE


def apply_transform(val: Any, transform: Optional[str]) -> Any:
    """Apply a configured transform function to a raw register value."""
    if val is None or not transform or transform in ("none", "identity", ""):
        return val

    if transform in ("sum", "sum_all", "sum_devices"):
        if isinstance(val, (list, tuple, set)):
            nums = [v for v in val if isinstance(v, (int, float))]
            return sum(nums) if nums else 0
        return val

    if transform in ("negate", "-x", "invert"):
        if isinstance(val, (int, float)):
            return -val
        return val

    if transform == "wh_to_kwh":
        if isinstance(val, (int, float)):
            return round(val / 1000.0, 3)
        return val

    if transform == "kwh_to_wh":
        if isinstance(val, (int, float)):
            return round(val * 1000.0, 1)
        return val

    # Custom expression evaluation fallback safely for simple math
    if "-x" in transform:
        try:
            return -float(val)
        except Exception:
            return val

    return val


@dataclass
class GroupMemberDef:
    """A member telemetry source in a minimal field group."""
    path: str
    transform: Optional[str] = None

    def to_dict(self) -> Union[str, Dict[str, Any]]:
        if self.transform and self.transform != "none":
            return {"path": self.path, "transform": self.transform}
        return self.path

    @classmethod
    def from_item(cls, item: Union[str, Dict[str, Any]]) -> GroupMemberDef:
        if isinstance(item, str):
            return cls(path=item.strip())
        if isinstance(item, dict):
            return cls(path=str(item.get("path", "")).strip(), transform=item.get("transform"))
        return cls(path=str(item).strip())


@dataclass
class FieldGroupDef:
    """Minimal representation of a unified field group (v2.0)."""
    id: str
    name: str
    fields: List[GroupMemberDef] = field(default_factory=list)
    device_type: Optional[str] = None
    synonyms: List[str] = field(default_factory=list)

    def to_mapping_def(self) -> TelemetryMappingDef:
        mqtt_fields: List[str] = []
        modbus_fields: List[str] = []
        grp_transform = "none"
        d_type = self.device_type
        for m in self.fields:
            p = m.path.strip()
            if not p:
                continue
            if not d_type and ("live." in p or p.startswith(("inverter.live", "battery.live", "rebus_beacon.live"))):
                d_type = p.split(".")[0]
            if d_type and "." in p:
                prefix = p.split(".")[0].lower()
                if prefix in ("inverter", "battery", "pv_link", "rebus_beacon") and prefix != d_type.lower():
                    logger.warning("Rejecting cross-device field '%s' from group '%s' (device_type=%s)", p, self.id, d_type)
                    continue
            if "live." in p or p.startswith(("inverter.live", "battery.live", "rebus_beacon.live")):
                mqtt_fields.append(p)
            else:
                modbus_fields.append(p)
                if m.transform and m.transform != "none":
                    grp_transform = m.transform

        if not d_type:
            for m in self.fields:
                p = m.path.strip()
                if p and "." in p:
                    d_type = p.split(".")[0]
                    break
        if not d_type:
            d_type = "inverter"

        d_class, s_class = infer_ha_classes(units=None, name=self.id)
        return TelemetryMappingDef(
            id=self.id,
            label=self.name,
            device_type=d_type,
            mqtt_fields=mqtt_fields,
            modbus_fields=modbus_fields,
            synonyms=list(self.synonyms),
            transform=grp_transform,
            ha_device_class=d_class,
            ha_state_class=s_class,
        )


@dataclass
class ModbusCandidateDef:
    """A candidate Modbus register mapping."""
    field_key: str
    label: str
    confidence: str = "HIGH"  # 'HIGH', 'PROBABLE', 'CANDIDATE'
    transform: Optional[str] = None
    transform_desc: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(init=False)
class TelemetryMappingDef:
    """User-configurable mapping between MQTT push telemetry and SunSpec Modbus."""
    id: str
    label: str
    device_type: str = "inverter"  # 'inverter', 'battery', 'rebus_beacon', 'pv_link'
    mqtt_fields: List[str] = field(default_factory=list)
    modbus_fields: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    transform: str = "none"  # 'negate', 'none', 'wh_to_kwh'
    transform_desc: str = ""
    unit: str = ""
    description: str = ""
    ha_platform: str = "sensor"  # 'sensor', 'select', 'number'
    ha_device_class: Optional[str] = None
    ha_state_class: Optional[str] = None

    def __init__(
        self,
        id: str,
        label: str,
        device_type: str = "inverter",
        mqtt_fields: Optional[List[str]] = None,
        modbus_fields: Optional[List[str]] = None,
        mqtt_field: Optional[str] = None,
        modbus_field: Optional[str] = None,
        modbus_candidates: Optional[List[str]] = None,
        synonyms: Optional[List[str]] = None,
        transform: str = "none",
        transform_desc: str = "",
        unit: str = "",
        description: str = "",
        ha_platform: str = "sensor",
        ha_device_class: Optional[str] = None,
        ha_state_class: Optional[str] = None,
    ):
        self.id = id
        self.label = label
        self.device_type = device_type

        # Resolve mqtt_fields list
        if mqtt_fields is not None:
            self.mqtt_fields = [str(x).strip() for x in mqtt_fields if str(x).strip()]
        elif mqtt_field:
            self.mqtt_fields = [str(mqtt_field).strip()]
        else:
            self.mqtt_fields = []

        # Resolve modbus_fields list
        if modbus_fields is not None:
            self.modbus_fields = [str(x).strip() for x in modbus_fields if str(x).strip()]
        else:
            m_list: List[str] = []
            if modbus_field and str(modbus_field).strip():
                m_list.append(str(modbus_field).strip())
            for c in (modbus_candidates or []):
                c_str = str(c).strip()
                if c_str and c_str not in m_list:
                    m_list.append(c_str)
            self.modbus_fields = m_list

        self.synonyms = list(synonyms or [])
        self.transform = transform or "none"
        self.transform_desc = transform_desc or ""
        self.unit = unit or ""
        self.description = description or ""
        self.ha_platform = ha_platform or "sensor"
        self.ha_device_class = ha_device_class
        self.ha_state_class = ha_state_class

    @property
    def mqtt_field(self) -> str:
        """Backward-compatible primary MQTT field accessor."""
        return self.mqtt_fields[0] if self.mqtt_fields else ""

    @property
    def primary_mqtt_field(self) -> str:
        """Primary MQTT field key."""
        return self.mqtt_fields[0] if self.mqtt_fields else ""

    @property
    def modbus_field(self) -> str:
        """Backward-compatible primary Modbus candidate accessor."""
        return self.modbus_fields[0] if self.modbus_fields else ""

    @property
    def primary_modbus_field(self) -> str:
        """Primary Modbus candidate field key."""
        return self.modbus_fields[0] if self.modbus_fields else ""

    @property
    def modbus_candidates(self) -> List[str]:
        """Backward-compatible list of all Modbus candidates."""
        return list(self.modbus_fields)

    def get_candidate_defs(self) -> List[ModbusCandidateDef]:
        """Return candidate definitions list with primary candidate first."""
        if not self.modbus_fields:
            return [
                ModbusCandidateDef(
                    field_key="",
                    label=f"{self.label} (Primary)",
                    confidence="NONE",
                    transform=None,
                    notes=self.description,
                )
            ]
        candidates = []
        for i, mb_key in enumerate(self.modbus_fields):
            is_primary = (i == 0)
            c_transform = self.transform if (is_primary or self.transform in ("sum", "sum_all", "sum_devices")) else None
            candidates.append(
                ModbusCandidateDef(
                    field_key=mb_key,
                    label=f"{self.label} ({'Primary' if is_primary else 'Alternative: ' + mb_key.split('.')[-1]})",
                    confidence="HIGH" if is_primary else "PROBABLE",
                    transform=c_transform if c_transform != "none" else None,
                    transform_desc=self.transform_desc or (f"Transform: {c_transform}" if c_transform and c_transform != "none" else None),
                    notes=self.description if is_primary else "Configured alternative candidate",
                )
            )
        return candidates

    def to_yaml_dict(self) -> dict:
        """Compact dictionary format for clean YAML serialization with zero boilerplate."""
        d: Dict[str, Any] = {
            "id": self.id,
            "label": self.label,
        }
        if self.device_type and self.device_type != "inverter":
            d["device_type"] = self.device_type
        if self.unit:
            d["unit"] = self.unit
        if self.mqtt_fields:
            d["mqtt_fields"] = list(self.mqtt_fields)
        if self.modbus_fields:
            d["modbus_fields"] = list(self.modbus_fields)
        if self.transform and self.transform != "none":
            d["transform"] = self.transform
        if self.transform_desc:
            d["transform_desc"] = self.transform_desc
        if self.ha_platform and self.ha_platform != "sensor":
            d["ha_platform"] = self.ha_platform
        if self.ha_device_class is not None:
            d["ha_device_class"] = self.ha_device_class
        if self.ha_state_class is not None:
            d["ha_state_class"] = self.ha_state_class
        if self.description:
            d["description"] = self.description
        if self.synonyms:
            d["synonyms"] = list(self.synonyms)
        return d

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "device_type": self.device_type,
            "unit": self.unit,
            "mqtt_fields": list(self.mqtt_fields),
            "modbus_fields": list(self.modbus_fields),
            "transform": self.transform,
            "transform_desc": self.transform_desc,
            "description": self.description,
            "ha_platform": self.ha_platform,
            "ha_device_class": self.ha_device_class,
            "ha_state_class": self.ha_state_class,
            "synonyms": list(self.synonyms),
            # Legacy fields for backward compatibility
            "mqtt_field": self.mqtt_field,
            "modbus_field": self.modbus_field,
            "modbus_candidates": self.modbus_candidates,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TelemetryMappingDef:
        d_class = data.get("ha_device_class")
        s_class = data.get("ha_state_class")
        if not d_class and not s_class:
            d_class, s_class = infer_ha_classes(
                units=data.get("unit"),
                name=data.get("id"),
                platform=data.get("ha_platform", "sensor"),
            )

        return cls(
            id=data["id"],
            label=data.get("label", data["id"]),
            device_type=data.get("device_type", "inverter"),
            mqtt_fields=data.get("mqtt_fields"),
            modbus_fields=data.get("modbus_fields"),
            mqtt_field=data.get("mqtt_field"),
            modbus_field=data.get("modbus_field"),
            modbus_candidates=data.get("modbus_candidates"),
            synonyms=data.get("synonyms", []),
            transform=data.get("transform", "none"),
            transform_desc=data.get("transform_desc", ""),
            unit=data.get("unit", ""),
            description=data.get("description", ""),
            ha_platform=data.get("ha_platform", "sensor"),
            ha_device_class=d_class,
            ha_state_class=s_class,
        )


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


def _field_matches_modbus_target(f: Any, target_str: str) -> bool:
    """Check if a StateField matches a configured Modbus target string like 'battery.model_802.V'."""
    if not target_str:
        return False
    parts = str(target_str).split(".")
    target_point = parts[-1]
    f_name = getattr(f, "name", "")
    if f_name.lower() != target_point.lower():
        return False
    if len(parts) >= 2:
        model_part = parts[-2].lower()
        f_model_id = getattr(f, "model_id", None)
        f_model_name = getattr(f, "model_name", None)
        if model_part.startswith("model_"):
            try:
                target_m_id = int(model_part.replace("model_", ""))
                if f_model_id is not None and f_model_id != target_m_id:
                    return False
            except ValueError:
                pass
        else:
            if f_model_name and model_part not in (f_model_name.lower(), f"model_{f_model_id}"):
                return False
    return True


def get_default_mappings() -> List[TelemetryMappingDef]:
    """Default configurable mappings loaded directly from package data groupings.yaml or telemetry_mappings.yaml."""
    pkg_dir = Path(__file__).resolve().parent
    for fname in (DEFAULT_GROUPINGS_FILE, LEGACY_MAPPINGS_FILE):
        pkg_data_path = pkg_dir / "data" / fname
        if pkg_data_path.exists():
            try:
                with open(pkg_data_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    if "groups" in data:
                        mappings = []
                        for g_dict in data.get("groups", []):
                            g_id = g_dict.get("id")
                            g_name = g_dict.get("name", g_id)
                            fields = [GroupMemberDef.from_item(item) for item in g_dict.get("fields", [])]
                            g_def = FieldGroupDef(id=g_id, name=g_name, fields=fields, device_type=g_dict.get("device_type"))
                            mappings.append(g_def.to_mapping_def())
                        return mappings
                    items = data.get("mappings", [])
                    if items:
                        return [TelemetryMappingDef.from_dict(d) for d in items]
            except Exception as e:
                logger.error("Failed to load package %s from %s: %s", fname, pkg_data_path, e)
    return []


def _resolve_mappings_path(config_path: Optional[Path | str] = None) -> Path:
    if config_path:
        return Path(config_path)
    if is_addon_data_env():
        g_path = data_dir() / DEFAULT_GROUPINGS_FILE
        if g_path.exists():
            return g_path
        leg_path = data_dir() / LEGACY_MAPPINGS_FILE
        if leg_path.exists():
            return leg_path
        return g_path
    pkg_dir = Path(__file__).resolve().parent
    repo_root = pkg_dir.parent

    # Look for groupings.yaml in config, root, data_dir
    for base in (repo_root / "config", repo_root, data_dir()):
        p = base / DEFAULT_GROUPINGS_FILE
        if p.exists():
            return p
    # Look for legacy telemetry_mappings.yaml
    for base in (repo_root / "config", repo_root, data_dir()):
        p = base / LEGACY_MAPPINGS_FILE
        if p.exists():
            return p

    data_path = pkg_dir / "data" / DEFAULT_GROUPINGS_FILE
    if data_path.exists():
        return data_path
    return data_path


def load_mappings_config(config_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Load raw telemetry mappings configuration dictionary from yaml."""
    path = _resolve_mappings_path(config_path)
    if not path.exists():
        return {"version": "2.0", "auto_group_heuristics": False, "ungrouped_fields": [], "groups": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to load mappings config from %s: %s", path, e)
        return {"version": "2.0", "auto_group_heuristics": False, "ungrouped_fields": [], "groups": []}


def load_mappings(config_path: Optional[Path | str] = None) -> List[TelemetryMappingDef]:
    """Load telemetry mappings from yaml file, falling back to defaults and saving file if missing."""
    path = _resolve_mappings_path(config_path)

    if not path.exists():
        logger.info("Mappings configuration %s not found. Creating default configuration file.", path)
        defaults = get_default_mappings()
        save_mappings(defaults, path)
        return defaults

    raw = load_mappings_config(config_path)
    if "groups" in raw:
        mappings = []
        for g_dict in raw.get("groups", []):
            g_id = g_dict.get("id")
            g_name = g_dict.get("name", g_id)
            fields = [GroupMemberDef.from_item(item) for item in g_dict.get("fields", [])]
            syns = list(g_dict.get("synonyms", []) or [])
            g_def = FieldGroupDef(id=g_id, name=g_name, fields=fields, device_type=g_dict.get("device_type"), synonyms=syns)
            mappings.append(g_def.to_mapping_def())
        logger.info("Loaded %d field groups from %s", len(mappings), path)
        return mappings

    items = raw.get("mappings", [])
    if not items:
        logger.warning("No mappings defined in %s. Using built-in defaults.", path)
        return get_default_mappings()
    mappings = [TelemetryMappingDef.from_dict(d) for d in items]
    logger.info("Loaded %d telemetry mappings from %s", len(mappings), path)
    return mappings


def save_mappings(
    mappings: List[TelemetryMappingDef],
    config_path: Optional[Path | str] = None,
    ungrouped_fields: Optional[Union[List[str], Set[str]]] = None,
    auto_group_heuristics: bool = False,
):
    """Save field groups list, ungrouped fields, and heuristic settings to YAML (v2.0 minimal format)."""
    path = _resolve_mappings_path(config_path)
    # If path currently points to legacy file name, prefer saving as groupings.yaml
    if path.name == LEGACY_MAPPINGS_FILE and not config_path:
        path = path.parent / DEFAULT_GROUPINGS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        u_list = sorted(list({str(x).strip() for x in (ungrouped_fields or []) if str(x).strip()}))
        groups_list = []
        for m in mappings:
            f_list = []
            for mf in m.mqtt_fields:
                f_list.append(mf)
            for mbf in m.modbus_fields:
                if m.transform and m.transform != "none":
                    f_list.append({"path": mbf, "transform": m.transform})
                else:
                    f_list.append(mbf)
            g_entry = {
                "id": m.id,
                "name": m.label,
                "fields": f_list,
            }
            if m.synonyms:
                g_entry["synonyms"] = list(m.synonyms)
            groups_list.append(g_entry)

        data: Dict[str, Any] = {
            "version": "2.0",
            "groups": groups_list,
        }
        if u_list:
            data["ungrouped_fields"] = u_list

        with open(path, "w", encoding="utf-8") as f:
            f.write("# PWRcell SunSpec - Field Groupings & Telemetry Mappings (v2.0)\n")
            f.write("# Unified links across MQTT push streams and SunSpec Modbus registers.\n\n")
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info("Saved %d field groups to %s", len(mappings), path)
    except Exception as e:
        logger.error("Failed to save mappings to %s: %s", path, e)
        raise e


class MappingRegistry:
    """Thread-safe singleton/registry of active telemetry mappings."""

    _instance: Optional[MappingRegistry] = None

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self._mappings: List[TelemetryMappingDef] = []
        self._by_id: Dict[str, TelemetryMappingDef] = {}
        self._by_mqtt: Dict[str, TelemetryMappingDef] = {}
        self._modbus_to_mqtt: Dict[str, str] = {}
        self._raw_to_compound: Dict[str, str] = {}
        self.ungrouped_fields: Set[str] = set()
        self.auto_group_heuristics: bool = False
        self.reload()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> MappingRegistry:
        if cls._instance is None:
            cls._instance = MappingRegistry(config_path)
        elif config_path is not None and cls._instance.config_path != config_path:
            cls._instance.config_path = config_path
            cls._instance.reload()
        return cls._instance

    def reload(self):
        raw = load_mappings_config(self.config_path)
        self.auto_group_heuristics = bool(raw.get("auto_group_heuristics", False))
        raw_ungrouped = raw.get("ungrouped_fields", []) or []
        self.ungrouped_fields = {str(x).strip() for x in raw_ungrouped if str(x).strip()}

        self._mappings = load_mappings(self.config_path)

        self._by_id = {m.id: m for m in self._mappings}
        self._by_mqtt: Dict[str, TelemetryMappingDef] = {}
        for m in self._mappings:
            for mf in m.mqtt_fields:
                self._by_mqtt[mf] = m

        mb_to_mqtt: Dict[str, str] = {}
        raw_to_comp: Dict[str, str] = {}
        syn_index: Dict[Tuple[str, str], TelemetryMappingDef] = {}

        for m in self._mappings:
            c_key = f"{m.device_type}.compound.{m.id}"
            primary_mqtt = m.primary_mqtt_field
            for mf in m.mqtt_fields:
                raw_to_comp[mf] = c_key
            for mbf in m.modbus_fields:
                if primary_mqtt:
                    mb_to_mqtt[mbf] = primary_mqtt
                raw_to_comp[mbf] = c_key

            # Index synonyms for fast concept discovery
            d_type = m.device_type.lower()
            syn_index[(d_type, m.id.lower())] = m
            for s in m.synonyms:
                syn_index[(d_type, s.lower())] = m
            for mf in m.mqtt_fields:
                mqtt_name = mf.split(".")[-1].lower()
                syn_index[(d_type, mqtt_name)] = m
            for mbf in m.modbus_fields:
                mb_name = mbf.split(".")[-1].lower()
                syn_index[(d_type, mb_name)] = m

        self._modbus_to_mqtt = mb_to_mqtt
        self._raw_to_compound = raw_to_comp
        self._synonyms_index = syn_index

    def is_field_ungrouped(
        self,
        field_key: str,
        field_obj: Optional[Any] = None,
        dev_type: Optional[str] = None,
    ) -> bool:
        """Check if a field is explicitly configured as ungrouped/standalone in telemetry_mappings.yaml."""
        if not self.ungrouped_fields:
            return False
        norm_key = str(field_key).strip()
        if norm_key in self.ungrouped_fields:
            return True
        if dev_type and not norm_key.startswith(f"{dev_type}."):
            if f"{dev_type}.{norm_key}" in self.ungrouped_fields:
                return True
        for u in self.ungrouped_fields:
            u_str = str(u).strip()
            if u_str == norm_key:
                return True
            if dev_type and u_str == f"{dev_type}.{norm_key}":
                return True
            if field_obj is not None and _field_matches_modbus_target(field_obj, u_str):
                if not dev_type or u_str.startswith(f"{dev_type}."):
                    return True
        return False

    def get_modbus_to_mqtt_map(self) -> Dict[str, str]:
        return self._modbus_to_mqtt

    def get_raw_to_compound_map(self) -> Dict[str, str]:
        return self._raw_to_compound

    def get_all(self) -> List[TelemetryMappingDef]:
        return list(self._mappings)

    def get_by_id(self, mapping_id: str) -> Optional[TelemetryMappingDef]:
        return self._by_id.get(mapping_id)

    def get_by_mqtt(self, mqtt_key: str) -> Optional[TelemetryMappingDef]:
        return self._by_mqtt.get(mqtt_key)

    def find_concept(
        self,
        device_type: str,
        point_name: str,
        units: Optional[str] = None,
    ) -> Optional[TelemetryMappingDef]:
        """Find concept definition matching device type, point name/synonym, and unit."""
        d_type = device_type.lower()
        p_name = point_name.lower().strip()
        c_unit = clean_unit(units)

        # 1. Exact device_type + point_name/synonym match
        m = self._synonyms_index.get((d_type, p_name))
        if m:
            exp_unit = clean_unit(m.unit)
            if not exp_unit or not c_unit or exp_unit == c_unit:
                return m

        # 2. Check all device types if not found for specific device_type
        for (dt, sn), cand_m in self._synonyms_index.items():
            if sn == p_name:
                exp_unit = clean_unit(cand_m.unit)
                if not exp_unit or not c_unit or exp_unit == c_unit:
                    return cand_m

        return m

    def get_canonical_synonyms_dict(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Construct canonical synonyms dictionary dynamically from loaded mappings."""
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for m in self._mappings:
            target_types = {m.device_type.lower()}
            for mf in m.mqtt_fields:
                if "." in mf:
                    target_types.add(mf.split(".")[0].lower())
            for mbf in m.modbus_fields:
                if "." in mbf:
                    target_types.add(mbf.split(".")[0].lower())

            syn_names = set(s.lower() for s in m.synonyms)
            syn_names.add(m.id.lower())
            for mf in m.mqtt_fields:
                syn_names.add(mf.split(".")[-1].lower())
            for mbf in m.modbus_fields:
                syn_names.add(mbf.split(".")[-1].lower())

            info = {
                "names": syn_names,
                "units": m.unit,
                "label": m.label,
                "ha_platform": m.ha_platform,
                "ha_device_class": m.ha_device_class,
                "ha_state_class": m.ha_state_class,
                "desc": m.description,
            }
            for dt in target_types:
                result.setdefault(dt, {})[m.id] = info
        return result

    def find_mapping_for_modbus(self, modbus_key: str) -> Optional[TelemetryMappingDef]:
        """Find mapping that matches a modbus key (either exact or point-suffix match)."""
        for m in self._mappings:
            if modbus_key in m.modbus_fields:
                return m
            # Check suffix match (e.g. inverter.inverter_status.CTPow vs inverter.model_64208.CTPow)
            for mbf in m.modbus_fields:
                cand_point = mbf.split(".")[-1]
                if modbus_key.endswith(f".{cand_point}") and m.device_type in modbus_key:
                    return m
        return None


# Aliases for Concept Registry unification
ConceptRegistry = MappingRegistry
ConceptDef = TelemetryMappingDef
