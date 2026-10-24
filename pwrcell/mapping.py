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

from .config import data_dir, is_addon_data_env

logger = logging.getLogger(__name__)

DEFAULT_MAPPINGS_FILE = "telemetry_mappings.yaml"


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


@dataclass
class TelemetryMappingDef:
    """User-configurable mapping between MQTT push telemetry and SunSpec Modbus."""
    id: str
    label: str
    device_type: str  # 'inverter', 'battery', 'rebus_beacon', 'pv_link'
    mqtt_field: str  # State store key e.g. 'inverter.live.grid_power_w'
    modbus_field: str  # Primary candidate register e.g. 'inverter.model_64208.CTPow'
    modbus_candidates: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    transform: str = "none"  # 'negate', 'none', 'wh_to_kwh'
    transform_desc: str = ""
    unit: str = ""
    description: str = ""
    ha_platform: str = "sensor"  # 'sensor', 'select', 'number'
    ha_device_class: Optional[str] = None
    ha_state_class: Optional[str] = None

    def get_candidate_defs(self) -> List[ModbusCandidateDef]:
        """Return candidate definitions list with primary candidate first."""
        candidates = [
            ModbusCandidateDef(
                field_key=self.modbus_field,
                label=f"{self.label} (Primary)",
                confidence="HIGH",
                transform=self.transform if self.transform != "none" else None,
                transform_desc=self.transform_desc or (f"Transform: {self.transform}" if self.transform != "none" else None),
                notes=self.description,
            )
        ]
        for alt_key in self.modbus_candidates:
            if alt_key != self.modbus_field:
                alt_transform = self.transform if self.transform in ("sum", "sum_all", "sum_devices") else None
                candidates.append(
                    ModbusCandidateDef(
                        field_key=alt_key,
                        label=f"{self.label} (Alternative: {alt_key.split('.')[-1]})",
                        confidence="PROBABLE",
                        transform=alt_transform,
                        notes="Configured alternative candidate",
                    )
                )
        return candidates

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TelemetryMappingDef:
        return cls(
            id=data["id"],
            label=data.get("label", data["id"]),
            device_type=data.get("device_type", "inverter"),
            mqtt_field=data.get("mqtt_field", ""),
            modbus_field=data.get("modbus_field", ""),
            modbus_candidates=data.get("modbus_candidates", []),
            synonyms=data.get("synonyms", []),
            transform=data.get("transform", "none"),
            transform_desc=data.get("transform_desc", ""),
            unit=data.get("unit", ""),
            description=data.get("description", ""),
            ha_platform=data.get("ha_platform", "sensor"),
            ha_device_class=data.get("ha_device_class"),
            ha_state_class=data.get("ha_state_class"),
        )


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


def get_default_mappings() -> List[TelemetryMappingDef]:
    """Default configurable mappings loaded directly from package data telemetry_mappings.yaml."""
    pkg_data_path = Path(__file__).resolve().parent / "data" / DEFAULT_MAPPINGS_FILE
    if pkg_data_path.exists():
        try:
            with open(pkg_data_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                items = data.get("mappings", [])
                return [TelemetryMappingDef.from_dict(d) for d in items]
        except Exception as e:
            logger.error("Failed to load package telemetry_mappings.yaml from %s: %s", pkg_data_path, e)
    return []


def _resolve_mappings_path(config_path: Optional[Path | str] = None) -> Path:
    if config_path:
        return Path(config_path)
    if is_addon_data_env():
        return data_dir() / DEFAULT_MAPPINGS_FILE
    pkg_dir = Path(__file__).resolve().parent
    data_path = pkg_dir / "data" / DEFAULT_MAPPINGS_FILE
    if data_path.exists():
        return data_path
    repo_root = pkg_dir.parent
    root_path = repo_root / DEFAULT_MAPPINGS_FILE
    if root_path.exists():
        return root_path
    return data_path


def load_mappings(config_path: Optional[Path | str] = None) -> List[TelemetryMappingDef]:
    """Load telemetry mappings from yaml file, falling back to defaults and saving file if missing."""
    path = _resolve_mappings_path(config_path)

    if not path.exists():
        logger.info("Mappings configuration %s not found. Creating default configuration file.", path)
        defaults = get_default_mappings()
        save_mappings(defaults, path)
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            items = data.get("mappings", [])
            mappings = [TelemetryMappingDef.from_dict(d) for d in items]
            logger.info("Loaded %d telemetry mappings from %s", len(mappings), path)
            return mappings
    except Exception as e:
        logger.error("Failed to load mappings from %s: %s. Using built-in defaults.", path, e)
        return get_default_mappings()


def save_mappings(mappings: List[TelemetryMappingDef], config_path: Optional[Path | str] = None):
    """Save telemetry mappings list to YAML."""
    path = _resolve_mappings_path(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "mappings": [m.to_dict() for m in mappings],
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info("Saved %d telemetry mappings to %s", len(mappings), path)
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
        self.reload()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> MappingRegistry:
        if cls._instance is None:
            cls._instance = MappingRegistry(config_path)
        return cls._instance

    def reload(self):
        self._mappings = load_mappings(self.config_path)
        self._by_id = {m.id: m for m in self._mappings}
        self._by_mqtt = {m.mqtt_field: m for m in self._mappings}
        mb_to_mqtt: Dict[str, str] = {}
        raw_to_comp: Dict[str, str] = {}
        syn_index: Dict[Tuple[str, str], TelemetryMappingDef] = {}

        for m in self._mappings:
            c_key = f"{m.device_type}.compound.{m.id}"
            if m.mqtt_field:
                raw_to_comp[m.mqtt_field] = c_key
            if m.modbus_field:
                mb_to_mqtt[m.modbus_field] = m.mqtt_field
                raw_to_comp[m.modbus_field] = c_key
            for alt in m.modbus_candidates:
                mb_to_mqtt[alt] = m.mqtt_field
                raw_to_comp[alt] = c_key

            # Index synonyms for fast concept discovery
            d_type = m.device_type.lower()
            syn_index[(d_type, m.id.lower())] = m
            for s in m.synonyms:
                syn_index[(d_type, s.lower())] = m
            if m.mqtt_field:
                mqtt_name = m.mqtt_field.split(".")[-1].lower()
                syn_index[(d_type, mqtt_name)] = m
            if m.modbus_field:
                mb_name = m.modbus_field.split(".")[-1].lower()
                syn_index[(d_type, mb_name)] = m

        self._modbus_to_mqtt = mb_to_mqtt
        self._raw_to_compound = raw_to_comp
        self._synonyms_index = syn_index

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
            if m.mqtt_field and "." in m.mqtt_field:
                target_types.add(m.mqtt_field.split(".")[0].lower())
            if m.modbus_field and "." in m.modbus_field:
                target_types.add(m.modbus_field.split(".")[0].lower())
            for alt in m.modbus_candidates:
                if "." in alt:
                    target_types.add(alt.split(".")[0].lower())

            syn_names = set(s.lower() for s in m.synonyms)
            syn_names.add(m.id.lower())
            if m.mqtt_field:
                syn_names.add(m.mqtt_field.split(".")[-1].lower())
            if m.modbus_field:
                syn_names.add(m.modbus_field.split(".")[-1].lower())
            for alt in m.modbus_candidates:
                syn_names.add(alt.split(".")[-1].lower())

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
            if m.modbus_field == modbus_key or modbus_key in m.modbus_candidates:
                return m
            # Check suffix match (e.g. inverter.inverter_status.CTPow vs inverter.model_64208.CTPow)
            cand_point = m.modbus_field.split(".")[-1]
            if modbus_key.endswith(f".{cand_point}") and m.device_type in modbus_key:
                return m
        return None


# Aliases for Concept Registry unification
ConceptRegistry = MappingRegistry
ConceptDef = TelemetryMappingDef
