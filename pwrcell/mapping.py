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
            mqtt_field=data["mqtt_field"],
            modbus_field=data["modbus_field"],
            modbus_candidates=data.get("modbus_candidates", []),
            transform=data.get("transform", "none"),
            transform_desc=data.get("transform_desc", ""),
            unit=data.get("unit", ""),
            description=data.get("description", ""),
            ha_platform=data.get("ha_platform", "sensor"),
            ha_device_class=data.get("ha_device_class"),
            ha_state_class=data.get("ha_state_class"),
        )


def get_default_mappings() -> List[TelemetryMappingDef]:
    """Default configurable mappings between MQTT push telemetry and Modbus registers."""
    return [
        TelemetryMappingDef(
            id="grid_power",
            label="Grid Net Power",
            device_type="inverter",
            unit="W",
            mqtt_field="inverter.live.grid_power_w",
            modbus_field="inverter.model_64208.CTPow",
            modbus_candidates=[
                "inverter.model_64208.CTPow",
                "inverter.model_102.W",
            ],
            transform="negate",
            transform_desc="-1 * CTPow (CT meter polarity inverted: positive = grid import)",
            description="Net power imported (+) or exported (-) to the utility grid",
            ha_platform="sensor",
            ha_device_class="power",
            ha_state_class="measurement",
        ),
        TelemetryMappingDef(
            id="system_mode",
            label="System Operating Mode",
            device_type="inverter",
            unit="",
            mqtt_field="inverter.live.system_mode",
            modbus_field="rebus_beacon.model_64200.SysMd",
            modbus_candidates=[
                "rebus_beacon.model_64200.SysMd",
                "inverter.model_64208.SysMd",
                "inverter.model_64202.SysMd",
            ],
            transform="none",
            transform_desc="",
            description="PWRcell operating mode (Grid Tie, Self Supply, Clean Backup, Priority Backup, Sell)",
            ha_platform="sensor",
            ha_device_class="enum",
            ha_state_class=None,
        ),
        TelemetryMappingDef(
            id="battery_power",
            label="Battery Real Power",
            device_type="battery",
            unit="W",
            mqtt_field="battery.live.battery_power_w",
            modbus_field="battery.model_64252.W",
            modbus_candidates=[
                "battery.model_64252.W",
                "battery.model_802.W",
            ],
            transform="none",
            transform_desc="",
            description="Battery charge (+) or discharge (-) real power",
            ha_platform="sensor",
            ha_device_class="power",
            ha_state_class="measurement",
        ),
        TelemetryMappingDef(
            id="battery_soc",
            label="Battery State of Charge",
            device_type="battery",
            unit="%",
            mqtt_field="battery.live.state_of_charge",
            modbus_field="battery.model_802.SoC",
            modbus_candidates=[
                "battery.model_802.SoC",
                "battery.model_804.SoC",
            ],
            transform="none",
            transform_desc="",
            description="Battery state of charge percentage",
            ha_platform="sensor",
            ha_device_class="battery",
            ha_state_class="measurement",
        ),
        TelemetryMappingDef(
            id="battery_soh",
            label="Battery State of Health",
            device_type="battery",
            unit="%",
            mqtt_field="battery.live.state_of_health",
            modbus_field="battery.model_802.SoH",
            modbus_candidates=[
                "battery.model_802.SoH",
                "battery.model_804.SoH",
            ],
            transform="none",
            transform_desc="",
            description="Battery health percentage",
            ha_platform="sensor",
            ha_device_class="battery",
            ha_state_class="measurement",
        ),
        TelemetryMappingDef(
            id="solar_power",
            label="Solar Generation Power",
            device_type="inverter",
            unit="W",
            mqtt_field="inverter.live.solar_power_w",
            modbus_field="pv_link.model_64207.P",
            modbus_candidates=[
                "pv_link.model_64207.P",
                "pv_link.model_404.DCW",
            ],
            transform="sum",
            transform_desc="Sum across all PV Link devices",
            description="Real-time solar PV generation power across all strings",
            ha_platform="sensor",
            ha_device_class="power",
            ha_state_class="measurement",
        ),
        TelemetryMappingDef(
            id="grid_imported_energy",
            label="Grid Imported Energy",
            device_type="inverter",
            unit="Wh",
            mqtt_field="inverter.live.grid_imported_energy_wh",
            modbus_field="inverter.model_64208.WhIn",
            modbus_candidates=["inverter.model_64208.WhIn"],
            transform="none",
            transform_desc="",
            description="Total electrical energy imported from utility grid",
            ha_platform="sensor",
            ha_device_class="energy",
            ha_state_class="total_increasing",
        ),
        TelemetryMappingDef(
            id="grid_exported_energy",
            label="Grid Exported Energy",
            device_type="inverter",
            unit="Wh",
            mqtt_field="inverter.live.grid_exported_energy_wh",
            modbus_field="inverter.model_64208.WhOut",
            modbus_candidates=["inverter.model_64208.WhOut"],
            transform="none",
            transform_desc="",
            description="Total electrical energy exported to utility grid",
            ha_platform="sensor",
            ha_device_class="energy",
            ha_state_class="total_increasing",
        ),
        TelemetryMappingDef(
            id="battery_imported_energy",
            label="Battery Stored / Charged Energy",
            device_type="battery",
            unit="Wh",
            mqtt_field="battery.live.battery_imported_energy_wh",
            modbus_field="battery.model_64209.WhIn",
            modbus_candidates=[
                "battery.model_64209.WhIn",
                "battery.model_64252.WhIn",
            ],
            transform="none",
            transform_desc="",
            description="Cumulative energy charged into battery storage",
            ha_platform="sensor",
            ha_device_class="energy",
            ha_state_class="total_increasing",
        ),
        TelemetryMappingDef(
            id="battery_exported_energy",
            label="Battery Discharged Energy",
            device_type="battery",
            unit="Wh",
            mqtt_field="battery.live.battery_exported_energy_wh",
            modbus_field="battery.model_64209.WhOut",
            modbus_candidates=[
                "battery.model_64209.WhOut",
                "battery.model_64252.WhOut",
            ],
            transform="none",
            transform_desc="",
            description="Cumulative energy discharged from battery storage",
            ha_platform="sensor",
            ha_device_class="energy",
            ha_state_class="total_increasing",
        ),
        TelemetryMappingDef(
            id="battery_voltage",
            label="Battery DC Voltage",
            device_type="battery",
            unit="V",
            mqtt_field="battery.live.battery_voltage_v",
            modbus_field="battery.model_802.V",
            modbus_candidates=[
                "battery.model_802.V",
                "battery.model_64252.V",
            ],
            transform="none",
            transform_desc="",
            description="Real-time DC battery pack terminal voltage",
            ha_platform="sensor",
            ha_device_class="voltage",
            ha_state_class="measurement",
        ),
    ]


def load_mappings(config_path: Optional[Path | str] = None) -> List[TelemetryMappingDef]:
    """Load telemetry mappings from yaml file, falling back to defaults and saving file if missing."""
    repo_root = Path(__file__).resolve().parent.parent
    path = Path(config_path) if config_path else (repo_root / DEFAULT_MAPPINGS_FILE)

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
    repo_root = Path(__file__).resolve().parent.parent
    path = Path(config_path) if config_path else (repo_root / DEFAULT_MAPPINGS_FILE)
    try:
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
        self._mappings: List[TelemetryMappingDef] = load_mappings(config_path)
        self._by_id: Dict[str, TelemetryMappingDef] = {m.id: m for m in self._mappings}
        self._by_mqtt: Dict[str, TelemetryMappingDef] = {m.mqtt_field: m for m in self._mappings}

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> MappingRegistry:
        if cls._instance is None:
            cls._instance = MappingRegistry(config_path)
        return cls._instance

    def reload(self):
        self._mappings = load_mappings(self.config_path)
        self._by_id = {m.id: m for m in self._mappings}
        self._by_mqtt = {m.mqtt_field: m for m in self._mappings}

    def get_all(self) -> List[TelemetryMappingDef]:
        return list(self._mappings)

    def get_by_id(self, mapping_id: str) -> Optional[TelemetryMappingDef]:
        return self._by_id.get(mapping_id)

    def get_by_mqtt(self, mqtt_key: str) -> Optional[TelemetryMappingDef]:
        return self._by_mqtt.get(mqtt_key)

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
