"""Mock fixtures and synthetic telemetry generator for Generac PWRcell offline testing.

This module provides mock devices loaded from `model_dump/` and a realistic synthetic
telemetry generator producing `EnergyRecordSet` protobuf streams.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .catalog import ModelCatalog, SunspecPointDef, get_catalog, is_sunspec_sentinel, should_ingest_model_groups

try:
    from .protos import energy_record_set_pb2
except ImportError:
    energy_record_set_pb2 = None

logger = logging.getLogger(__name__)


@dataclass
class MockPointValue:
    """A single point value on a mock device with metadata and scale-factor applied."""
    name: str
    model_id: int
    raw_value: Any
    scaled_value: Any
    label: str
    desc: str
    units: Optional[str]
    point_type: str
    access: str
    is_writable: bool
    scale_factor: Optional[int] = None
    symbol_name: Optional[str] = None
    is_bitfield: bool = False
    bitmask_flags: Optional[List[str]] = None


@dataclass
class MockDeviceModel:
    """A model instance on a mock device."""
    model_id: int
    name: str
    label: str
    points: Dict[str, MockPointValue] = field(default_factory=dict)
    groups: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MockDevice:
    """Represents a simulated Generac device loaded from model dumps."""
    slave_id: int
    serial_number: str
    model_name: str
    manufacturer: str
    version: str
    device_type: str  # 'inverter', 'battery', 'pv_link', 'rebus_beacon', 'icm'
    models: Dict[int, List[MockDeviceModel]] = field(default_factory=dict)

    def get_first_model(self, model_id: int) -> Optional[MockDeviceModel]:
        models_list = self.models.get(model_id)
        if models_list and len(models_list) > 0:
            return models_list[0]
        return None

    def get_point_value(self, model_id: int, point_name: str) -> Optional[MockPointValue]:
        model = self.get_first_model(model_id)
        if model:
            return model.points.get(point_name)
        return None

    @property
    def supported_models(self) -> List[int]:
        """List of SunSpec model IDs supported by this mock device."""
        return sorted(list(self.models.keys()))


def resolve_device_type(model_name: str) -> str:
    """Map device model string to canonical device type identifier."""
    if not model_name:
        return "unknown"
    from .catalog import classify_device_type
    return classify_device_type(model_name=model_name)


class MockFixtureLoader:
    """Loads recorded device dumps from model_dump/ directory."""

    def __init__(
        self,
        dump_dir: Optional[Path | str] = None,
        catalog: Optional[ModelCatalog] = None,
        include_bulk_table_groups: bool = False,
    ):
        repo_root = Path(__file__).resolve().parent.parent
        if dump_dir:
            self.dump_dir = Path(dump_dir)
        else:
            sanitized_dir = repo_root / "tests" / "fixtures" / "model_dump"
            self.dump_dir = sanitized_dir if sanitized_dir.exists() else (repo_root / "model_dump")
        self.catalog = catalog or get_catalog()
        self.include_bulk_table_groups = include_bulk_table_groups
        self.devices: Dict[str, MockDevice] = {}  # serial_number -> MockDevice
        self.devices_by_slave_id: Dict[int, MockDevice] = {}
        self._load()

    def _load(self):
        if not self.dump_dir.exists() or not self.dump_dir.is_dir():
            logger.warning("Mock dump directory %s not found", self.dump_dir)
            return

        for json_path in sorted(self.dump_dir.glob("*.json")):
            try:
                slave_id = int(json_path.stem)
            except ValueError:
                continue

            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    device = self._parse_device_json(slave_id, raw_data)
                    if device:
                        self.devices[device.serial_number] = device
                        self.devices_by_slave_id[slave_id] = device
            except Exception as e:
                logger.error("Failed loading mock device file %s: %s", json_path, e)

        logger.info("Loaded %d mock devices from %s", len(self.devices), self.dump_dir)

    def _parse_device_json(self, slave_id: int, raw_data: dict) -> Optional[MockDevice]:
        raw_models = raw_data.get("models", [])
        common_model = next((m for m in raw_models if m.get("ID") == 1), None)
        if not common_model:
            return None

        serial_number = str(common_model.get("SN", "")).strip()
        model_name = str(common_model.get("Md", "")).strip()
        manufacturer = str(common_model.get("Mn", "Generac")).strip()
        version = str(common_model.get("Vr", "")).strip()
        device_type = resolve_device_type(model_name)

        device = MockDevice(
            slave_id=slave_id,
            serial_number=serial_number,
            model_name=model_name,
            manufacturer=manufacturer,
            version=version,
            device_type=device_type,
        )

        for m_dict in raw_models:
            model_id = m_dict.get("ID")
            if model_id is None:
                continue
            model_id = int(model_id)

            catalog_model = self.catalog.get_model(model_id)
            model_name_str = catalog_model.name if catalog_model else f"model_{model_id}"
            model_label_str = catalog_model.label if catalog_model else model_name_str

            device_model = MockDeviceModel(
                model_id=model_id,
                name=model_name_str,
                label=model_label_str,
            )

            def _collect_block_sfs(block_dict: Dict[str, Any], grp_path: Optional[str] = None) -> Dict[str, int]:
                sfs: Dict[str, int] = {}
                for k, val in block_dict.items():
                    if k in ("ID", "L") or isinstance(val, (list, dict)):
                        continue
                    if isinstance(val, (int, float)) and not is_sunspec_sentinel(val, "sunssf") and -10 <= val <= 10:
                        if k.endswith("_sf") or k.endswith("_SF"):
                            sfs[k] = int(val)
                        elif catalog_model:
                            pd = catalog_model.get_group_point(grp_path, k) if grp_path else catalog_model.points.get(k)
                            if pd and pd.is_scale_factor:
                                sfs[k] = int(val)
                if catalog_model and not grp_path:
                    for pt_def in catalog_model.points.values():
                        if pt_def.group_path:
                            continue
                        if pt_def.sf and pt_def.sf in block_dict and pt_def.sf not in sfs:
                            sf_val = block_dict[pt_def.sf]
                            if isinstance(sf_val, (int, float)) and not is_sunspec_sentinel(sf_val, "sunssf") and -10 <= sf_val <= 10:
                                sfs[pt_def.sf] = int(sf_val)
                return sfs

            def _resolve_point_value(
                pt_name: str,
                raw_val: Any,
                pt_def: Optional[SunspecPointDef],
                sfs: Dict[str, int],
            ) -> tuple[Any, Optional[int], Optional[str], bool, Optional[List[str]]]:
                pt_type = pt_def.type if pt_def else "unknown"
                if raw_val is None or is_sunspec_sentinel(raw_val, pt_type):
                    return None, None, None, (pt_def.is_bitfield if pt_def else False), None

                scaled_val = raw_val
                sf_applied = None
                sf_name = pt_def.sf if (pt_def and pt_def.sf) else f"{pt_name}_sf"
                if sf_name not in sfs and f"{pt_name}_SF" in sfs:
                    sf_name = f"{pt_name}_SF"

                is_bf = pt_def.is_bitfield if pt_def else False
                if sf_name in sfs and isinstance(raw_val, (int, float)) and not (pt_def and (pt_def.is_enum or is_bf)):
                    sf_applied = sfs[sf_name]
                    scaled_val = raw_val * (10 ** sf_applied)
                    if sf_applied < 0:
                        scaled_val = round(scaled_val, abs(sf_applied))

                sym_name = None
                bitmask_flags = None
                if pt_def and pt_def.is_enum and isinstance(raw_val, int):
                    sym = pt_def.lookup_symbol(raw_val)
                    if sym:
                        sym_name = sym.name
                elif is_bf and isinstance(raw_val, int):
                    bitmask_flags = pt_def.decode_bitfield(raw_val)

                final_val = sym_name if sym_name is not None else (
                    bitmask_flags if is_bf and bitmask_flags is not None else scaled_val
                )
                return final_val, sf_applied, sym_name, is_bf, bitmask_flags

            def _parse_group_entries(
                grp_key: str,
                grp_val: Any,
                parent_path: str,
                parent_sfs: Dict[str, int],
            ):
                if not should_ingest_model_groups(
                    model_id,
                    grp_key,
                    include_bulk_tables=self.include_bulk_table_groups,
                ):
                    return

                if isinstance(grp_val, list):
                    instances = [
                        (idx, item)
                        for idx, item in enumerate(grp_val, start=1)
                        if isinstance(item, dict)
                    ]
                elif isinstance(grp_val, dict):
                    instances = [(None, grp_val)]
                else:
                    return

                for grp_idx, inst_dict in instances:
                    inst_path = f"{parent_path}.{grp_key}" if parent_path else grp_key
                    if grp_idx is not None:
                        inst_path = f"{inst_path}.{grp_idx}"

                    local_sfs = dict(parent_sfs)
                    local_sfs.update(_collect_block_sfs(inst_dict, grp_path=inst_path))

                    grp_raw: Dict[str, Any] = {}
                    grp_comp: Dict[str, Any] = {}
                    nested: List[tuple[str, Any]] = []

                    for k, v in inst_dict.items():
                        if k == "Pad" or k.startswith("Pad"):
                            continue
                        if isinstance(v, (list, dict)):
                            nested.append((k, v))
                            continue
                        pt_def = catalog_model.get_group_point(inst_path, k) if catalog_model else None
                        if pt_def and pt_def.type == "pad":
                            continue
                        scaled_v, _, _, _, _ = _resolve_point_value(k, v, pt_def, local_sfs)
                        grp_raw[k] = v
                        grp_comp[k] = scaled_v

                    if grp_raw:
                        device_model.groups.append({
                            "group_name": grp_key,
                            "group_index": grp_idx,
                            "group_path": inst_path,
                            "raw_values": grp_raw,
                            "computed_values": grp_comp,
                        })

                    for sub_k, sub_v in nested:
                        _parse_group_entries(sub_k, sub_v, inst_path, local_sfs)

            scale_factors = _collect_block_sfs(m_dict)

            # Build scalar points and recursively ingest sub-groups
            for pt_name, raw_val in m_dict.items():
                if isinstance(raw_val, (list, dict)):
                    _parse_group_entries(pt_name, raw_val, "", scale_factors)
                    continue
                if pt_name in ("ID", "L", "Pad", "repeating"):
                    continue
                if pt_name.startswith("Pad"):
                    continue

                pt_def = catalog_model.points.get(pt_name) if catalog_model else None
                if pt_def and pt_def.group_path:
                    pt_def = None
                label = pt_def.label if pt_def else pt_name
                desc = pt_def.desc if pt_def else ""
                units = pt_def.units if pt_def else None
                pt_type = pt_def.type if pt_def else "unknown"
                access = pt_def.access if pt_def else "R"
                is_writable = pt_def.is_writable if pt_def else False

                final_val, sf_applied, sym_name, is_bitfield, bitmask_flags = _resolve_point_value(
                    pt_name, raw_val, pt_def, scale_factors
                )

                mock_point = MockPointValue(
                    name=pt_name,
                    model_id=model_id,
                    raw_value=raw_val,
                    scaled_value=final_val,
                    label=label,
                    desc=desc,
                    units=units,
                    point_type=pt_type,
                    access=access,
                    is_writable=is_writable,
                    scale_factor=sf_applied,
                    symbol_name=sym_name,
                    is_bitfield=is_bitfield,
                    bitmask_flags=bitmask_flags,
                )
                device_model.points[pt_name] = mock_point

            models_list = device.models.setdefault(model_id, [])
            models_list.append(device_model)

        return device


class MockTelemetryGenerator:
    """Generates synthetic, physically plausible EnergyRecordSet protobuf telemetry."""

    def __init__(self, inverter_id: str = "000100070008"):
        self.inverter_id = inverter_id
        self.sim_time = time.time()
        self.soc: float = 78.5  # Battery SoC percent
        self.soh: float = 98.0  # Battery SoH percent
        self.solar_peak_w: float = 5800.0  # Max solar generation
        self.base_load_w: float = 1200.0  # Base home consumption
        self.sys_mode = energy_record_set_pb2.SELF_SUPPLY
        self.total_import_ws: int = 150_000_000_000
        self.total_export_ws: int = 85_000_000_000

    def tick(self, elapsed_seconds: float = 2.0) -> energy_record_set_pb2.EnergyRecordSet:
        """Advance simulation time and return next EnergyRecordSet protobuf."""
        self.sim_time += elapsed_seconds

        # Time-of-day sine curve (period = 120 simulated seconds for quick demo progression)
        t_phase = (self.sim_time % 120) / 120.0 * (2 * math.pi)
        solar_ratio = max(0.0, math.sin(t_phase))
        solar_w = round(self.solar_peak_w * solar_ratio, 1)

        # Fluctuating home load (base load + small wobble)
        load_w = round(self.base_load_w + 400.0 * math.sin(t_phase * 3), 1)

        # Net balance: solar - load
        net_w = round(solar_w - load_w, 1)

        # Storage (battery) behavior
        if net_w > 0:
            # Excess solar charges battery up to 98%
            if self.soc < 98.0:
                storage_w = min(net_w, 3500.0)  # Max charge rate
                self.soc = min(98.0, self.soc + (storage_w * elapsed_seconds / (17100.0 * 3600)) * 100)
                grid_w = -(net_w - storage_w)  # Remaining exported to grid
            else:
                storage_w = 0.0
                grid_w = -net_w  # All excess exported
        else:
            # Deficit: battery discharges down to 20%
            deficit = abs(net_w)
            if self.soc > 20.0:
                storage_w = -min(deficit, 3500.0)  # Discharge power
                self.soc = max(20.0, self.soc - (abs(storage_w) * elapsed_seconds / (17100.0 * 3600)) * 100)
                grid_w = deficit - abs(storage_w)  # Remainder imported from grid
            else:
                storage_w = 0.0
                grid_w = deficit  # All imported from grid

        # Update energy accumulators (watt-seconds)
        if grid_w > 0:
            self.total_import_ws += int(grid_w * elapsed_seconds)
        else:
            self.total_export_ws += int(abs(grid_w) * elapsed_seconds)

        record_set = energy_record_set_pb2.EnergyRecordSet()
        record_set.inverterId = self.inverter_id
        record_set.isHighFrequency = True
        record_set.systemFamily = energy_record_set_pb2.SYSTEM_FAMILY_PWRCELL_R1
        record_set.gatewayInfo.gateway_id = "000100120001"
        record_set.gatewayInfo.gateway_type = energy_record_set_pb2.GATEWAY_TYPE_BEACON

        record = record_set.energyRecord.add()
        record.currentTimestamp = self.sim_time
        record.previousTimestamp = self.sim_time - elapsed_seconds
        record.sysMode = self.sys_mode
        record.inverterState = getattr(energy_record_set_pb2, "INVERTER_STATE_GRID_CONNECTED", 2080)

        # Channel 1: NET (Grid)
        ch_net = record.channel.add()
        ch_net.channel = 1
        ch_net.channelType = energy_record_set_pb2.NET
        ch_net.realPower_W = int(grid_w)
        ch_net.realPower_Wf = float(grid_w)
        ch_net.voltage_V = 240.2
        ch_net.importedEnergy_Ws = self.total_import_ws
        ch_net.exportedEnergy_Ws = self.total_export_ws

        # Channel 2: GENERATION (Solar)
        ch_gen = record.channel.add()
        ch_gen.channel = 2
        ch_gen.channelType = energy_record_set_pb2.GENERATION
        ch_gen.deviceType = energy_record_set_pb2.SOLAR
        ch_gen.realPower_W = int(solar_w)
        ch_gen.realPower_Wf = float(solar_w)
        ch_gen.voltage_V = 380.5
        ch_gen.exportedEnergy_Ws = 50_000_000_000

        # Channel 3: CONSUMPTION (Home Load)
        ch_load = record.channel.add()
        ch_load.channel = 3
        ch_load.channelType = energy_record_set_pb2.CONSUMPTION
        ch_load.realPower_W = int(load_w)
        ch_load.realPower_Wf = float(load_w)
        ch_load.voltage_V = 120.1
        ch_load.importedEnergy_Ws = 40_000_000_000

        # Channel 4: STORAGE (Battery)
        ch_bat = record.channel.add()
        ch_bat.channel = 4
        ch_bat.channelType = energy_record_set_pb2.STORAGE
        ch_bat.deviceType = energy_record_set_pb2.BATTERY
        ch_bat.deviceId = "000100080009"
        ch_bat.realPower_W = int(storage_w)
        ch_bat.realPower_Wf = float(storage_w)
        ch_bat.soc = round(self.soc, 1)
        ch_bat.soh = float(self.soh)
        ch_bat.voltage_V = 381.2
        ch_bat.importedEnergy_Ws = 15_000_000_000
        ch_bat.exportedEnergy_Ws = 12_000_000_000
        ch_bat.realPowerSourceMax_W = 4500.0
        ch_bat.realPowerSinkMax_W = 4500.0

        # Channel 5: INVERTER_OUTPUT
        ch_inv = record.channel.add()
        ch_inv.channel = 5
        ch_inv.channelType = energy_record_set_pb2.INVERTER_OUTPUT
        ch_inv.deviceType = energy_record_set_pb2.INVERTER
        ch_inv.deviceId = self.inverter_id
        ch_inv.realPower_W = int(solar_w + storage_w)
        ch_inv.realPower_Wf = float(solar_w + storage_w)
        ch_inv.voltage_V = 240.2
        ch_inv.exportedEnergy_Ws = 45_000_000_000
        ch_inv.importedEnergy_Ws = 5_000_000_000

        self.latest_record_set = record_set
        return record_set
