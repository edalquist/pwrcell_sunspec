"""Master PWRCell Client Library (v3).

Unifies Serialized Modbus, Push MQTT Telemetry, State Store, and Controls into
a single clean interface supporting both live hardware and offline simulation.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Generator, List, Optional

from .catalog import (
    MODEL_BATTERY_BASE,
    MODEL_BATTERY_STATUS,
    MODEL_BATTERY_WARRANTY,
    MODEL_FLASH_READER,
    MODEL_INVERTER_SPLIT_PHASE,
    MODEL_INVERTER_STATUS,
    MODEL_LITHIUM_ION_STRING,
    MODEL_PVLINK_STATUS,
    MODEL_PVRSS_CONFIG,
    MODEL_PVRSS_TELEMETRY,
    MODEL_REBUS_ARB,
    MODEL_REBUS_DIR,
    MODEL_RECONNECT,
    MODEL_STRING_COMBINER,
    ModelCatalog,
    get_catalog,
)
from .config import AppConfig, DeviceConfig
from .controls import ControlDispatcher
from .fixtures import MockFixtureLoader, MockTelemetryGenerator
from .modbus import SerializedModbusClient
from .mqtt import LiveTelemetrySnapshot, MqttClient
from .poller import PollingTier, TieredModbusPoller, safe_point_cvalue
from .state import FieldSource, StateStore
from .tunnel import TunnelConfig, pwrcell_tunnel

logger = logging.getLogger(__name__)

# Simulated telemetry tick; the generator advance and the loop wait must stay in lockstep
MOCK_TICK_SECONDS = 1.5


class PwrcellClient:
    """Master Generac PWRcell client instance."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        modbus_client: Optional[SerializedModbusClient] = None,
        mqtt_client: Optional[MqttClient] = None,
        is_mock: bool = False,
    ):
        self.config = config or AppConfig()
        self.catalog = get_catalog()
        self.state = StateStore(catalog=self.catalog)
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self.bridge: Optional[Any] = None
        self.controls = ControlDispatcher(self.modbus, self.state, self.catalog)
        self.is_mock = is_mock
        self._mock_generator: Optional[MockTelemetryGenerator] = None
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_stop = threading.Event()
        fast_interval = float(self.config.poll_rate)
        config_interval = float(self.config.config_poll_interval)
        slow_interval = float(self.config.slow_poll_interval)
        fast_paths: Optional[List[str]] = None
        config_paths: Optional[List[str]] = None
        slow_paths: Optional[List[str]] = None

        tiers = self.config.polling_tiers or {}
        fast_interval, fast_paths = self._parse_tier_config(tiers.get("fast"), fast_interval)
        config_interval, config_paths = self._parse_tier_config(tiers.get("config"), config_interval)
        slow_interval, slow_paths = self._parse_tier_config(tiers.get("slow"), slow_interval)

        self.poller = TieredModbusPoller(
            client=self,
            fast_interval=fast_interval,
            config_interval=config_interval,
            slow_interval=slow_interval,
            enabled=self.config.enable_polling,
            fast_paths=fast_paths,
            config_paths=config_paths,
            slow_paths=slow_paths,
        )
        self._last_known_sys_mode: Optional[int] = None
        self._init_poll_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    @staticmethod
    def _parse_tier_config(cfg, default_interval: float):
        """Parse a polling tier entry: either a list of paths or {interval, paths}."""
        if isinstance(cfg, dict):
            interval = float(cfg["interval"]) if "interval" in cfg else default_interval
            paths = cfg["paths"] if isinstance(cfg.get("paths"), list) else None
            return interval, paths
        if isinstance(cfg, list):
            return default_interval, cfg
        return default_interval, None

    @property
    def is_initial_poll_running(self) -> bool:
        """Return True if background initial SunSpec model scan is currently running."""
        return bool(self._init_poll_thread and self._init_poll_thread.is_alive())

    def start(self):
        """Start client background workers and initialize device discovery."""
        with self._lock:
            if self._running:
                return
            self._running = True

        if self.is_mock:
            self._start_mock_mode()
        else:
            self._start_live_mode()

    def stop(self):
        """Stop all background workers and disconnect clients."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._sim_stop.set()
            init_poll_thread = self._init_poll_thread
            sim_thread = self._sim_thread
            poller = self.poller
            bridge = self.bridge
            mqtt = self.mqtt
            modbus = self.modbus

        if init_poll_thread and init_poll_thread.is_alive():
            init_poll_thread.join(timeout=1.0)
            if init_poll_thread.is_alive():
                logger.warning("Initial model poll thread did not exit within 1.0s")

        if poller:
            poller.stop()

        if sim_thread and sim_thread.is_alive():
            sim_thread.join(timeout=2.0)
            if sim_thread.is_alive():
                logger.warning("Mock simulation thread did not exit within 2.0s")

        if bridge:
            try:
                bridge.stop()
            except Exception as e:
                logger.debug("Error stopping HA bridge: %s", e)

        if mqtt:
            mqtt.stop()

        if modbus:
            modbus.close()

        logger.info("PWRcell client stopped")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def _start_mock_mode(self):
        """Populate state store from model_dump and start synthetic telemetry simulator."""
        logger.info("Initializing PWRcell client in MOCK/SIMULATION mode")
        loader = MockFixtureLoader(catalog=self.catalog)
        for sn, mock_dev in loader.devices.items():
            self.state.register_device(
                serial_number=sn,
                slave_id=mock_dev.slave_id,
                device_type=mock_dev.device_type,
                model_name=mock_dev.model_name,
                manufacturer=mock_dev.manufacturer,
                version=mock_dev.version,
                supported_models=mock_dev.supported_models,
            )
            # Ingest points from mock models
            for model_id, models_list in mock_dev.models.items():
                for model_inst in models_list:
                    raw_pts = {p.name: p.raw_value for p in model_inst.points.values()}
                    comp_pts = {p.name: p.scaled_value for p in model_inst.points.values()}
                    self.state.update_from_modbus_points(sn, model_id, raw_values=raw_pts, computed_values=comp_pts)

        # Refresh model assignments with discovered mock device state
        self.poller.refresh_model_resolutions()

        # Start simulated telemetry ticker thread
        self._mock_generator = MockTelemetryGenerator()
        self._sim_stop.clear()
        self._sim_thread = threading.Thread(
            target=self._mock_sim_loop,
            name="PwrCellMockSim",
            daemon=True,
        )
        self._sim_thread.start()

    def _mock_sim_loop(self):
        logger.debug("Mock simulation telemetry loop running")
        while self._running and not self._sim_stop.is_set():
            if self._mock_generator:
                rec_set = self._mock_generator.tick(elapsed_seconds=MOCK_TICK_SECONDS)
                snapshot = MqttClient._parse_snapshot(rec_set)
                self.state.update_from_telemetry_snapshot(snapshot)

                # Dynamically sync mock Modbus registers with simulated telemetry
                inv = self.state.get_inverter()
                if inv:
                    self.state.set_field(
                        device_sn=inv.serial_number,
                        name="CTPow",
                        label="Current Transformer Power",
                        description="Grid CT power",
                        value=-round(snapshot.grid_power_w, 1),
                        raw_value=-round(snapshot.grid_power_w, 1),
                        units="W",
                        sub_group="inverter_status",
                    )
                    self.state.set_field(
                        device_sn=inv.serial_number,
                        name="SysMd",
                        label="System Operating Mode",
                        description="Inverter operating mode",
                        value=snapshot.system_mode_name,
                        raw_value=snapshot.system_mode,
                        sub_group="inverter_status",
                    )
                bat = self.state.get_battery()
                if bat:
                    self.state.set_field(
                        device_sn=bat.serial_number,
                        name="W",
                        label="Battery Real Power",
                        description="Battery DC power",
                        value=round(snapshot.battery_power_w, 1),
                        raw_value=round(snapshot.battery_power_w, 1),
                        units="W",
                        sub_group="DCB105_warranty",
                    )
                    if snapshot.battery_soc is not None:
                        self.state.set_field(
                            device_sn=bat.serial_number,
                            name="SoC",
                            label="State of Charge",
                            description="Battery state of charge",
                            value=round(snapshot.battery_soc, 1),
                            raw_value=round(snapshot.battery_soc, 1),
                            units="%",
                            sub_group="battery",
                        )
                    if snapshot.battery_soh is not None:
                        self.state.set_field(
                            device_sn=bat.serial_number,
                            name="SoH",
                            label="State of Health",
                            description="Battery state of health",
                            value=round(snapshot.battery_soh, 1),
                            raw_value=round(snapshot.battery_soh, 1),
                            units="%",
                            sub_group="battery",
                        )
                beacon = self.state.get_beacon()
                if beacon:
                    self.state.set_field(
                        device_sn=beacon.serial_number,
                        name="SysMd",
                        label="System Operating Mode",
                        description="Beacon master operating mode",
                        value=snapshot.system_mode_name,
                        raw_value=snapshot.system_mode,
                        sub_group="REbus_dir",
                    )

            self._sim_stop.wait(MOCK_TICK_SECONDS)

    def _start_live_mode(self):
        """Connect Modbus and MQTT and load discovered devices."""
        # Sync models from unit over SCP if possible, fallback to cached
        try:
            from .model_sync import load_models_dir
            sunspec_dir = load_models_dir(self.config)
            from .modbus import configure_sunspec_model_paths
            configure_sunspec_model_paths(sunspec_dir)
            self.catalog = get_catalog()
        except Exception as e:
            logger.warning("Failed to sync SunSpec models over SCP; using cached sunspec models (%s)", e)
            from .modbus import configure_sunspec_model_paths
            configure_sunspec_model_paths()

        if self.modbus:
            self.modbus.worker.start()

        if self.mqtt:
            self.mqtt.register_snapshot_callback(self._on_mqtt_snapshot)
            self.mqtt.start()

        self.load_or_discover_devices()

        if self.config.enable_polling:
            self.poller.start()

        # Start initial deep SunSpec model poll asynchronously in the background
        # so Web Explorer UI, Home Assistant bridge, and live MQTT telemetry start immediately!
        self._init_poll_thread = threading.Thread(
            target=self._poll_device_models_live,
            name="PwrCellInitialModelPoll",
            daemon=True,
        )
        self._init_poll_thread.start()

    def _on_mqtt_snapshot(self, snapshot: LiveTelemetrySnapshot):
        """Process incoming MQTT push snapshot and detect panel mode changes for instant sync."""
        self.state.update_from_telemetry_snapshot(snapshot)

        # If system mode changed (e.g. from physical front panel keypad), trigger immediate Modbus sync
        if snapshot.system_mode is not None:
            if (
                self._last_known_sys_mode is not None
                and snapshot.system_mode != self._last_known_sys_mode
            ):
                logger.info(
                    "Detected system mode change via MQTT push (%s -> %s), triggering immediate Modbus config sync",
                    self._last_known_sys_mode,
                    snapshot.system_mode,
                )
                self.poller.trigger_sync("config")
            self._last_known_sys_mode = snapshot.system_mode

    def _poll_device_models_live(self):
        """Read all supported SunSpec models and common metadata for all devices asynchronously."""
        if not self.modbus:
            return

        logger.info("Starting background initial SunSpec model poll across devices...")
        for dev in self.state.get_devices_snapshot():
            if not self._running:
                break
            if dev.slave_id is None:
                continue

            try:
                tcp_dev = self.modbus.get_or_create_device(dev.slave_id)
                if not getattr(tcp_dev, "models", None):
                    tcp_dev = self.modbus.scan_device(dev.slave_id, full_model_read=False)
                if not tcp_dev or not self._running:
                    continue

                # Discover and register all supported SunSpec model IDs on this device
                supported = [mid for mid in tcp_dev.models.keys() if isinstance(mid, int)]
                self.state.set_supported_models(dev.serial_number, supported)

                if 1 in tcp_dev.models or "common" in tcp_dev.models:
                    model_inst = self.modbus.read_model_block(tcp_dev, 1)
                    if model_inst and hasattr(tcp_dev, "common") and tcp_dev.common:
                        sn_pt = getattr(tcp_dev.common[0], "SN", None)
                        live_sn = str(sn_pt.value).strip() if (sn_pt is not None and getattr(sn_pt, "value", None) is not None) else ""
                        if live_sn and live_sn not in ("0", "None") and live_sn.upper() != dev.serial_number.strip().upper():
                            logger.warning(
                                "Device serial mismatch on slave %d (cached=%s, live=%s); triggering Modbus device rescan",
                                dev.slave_id,
                                dev.serial_number,
                                live_sn,
                            )
                            self.rescan_devices()
                            break
                        self.state.update_device_metadata(
                            dev.serial_number,
                            model_name=str(tcp_dev.common[0].Md.value).strip() or dev.model_name,
                            version=str(tcp_dev.common[0].Vr.value).strip() or dev.version,
                        )
                        raw_pts = {p_name: p.value for p_name, p in model_inst.points.items()}
                        comp_pts = {p_name: safe_point_cvalue(p) for p_name, p in model_inst.points.items()}
                        self.state.update_from_modbus_points(dev.serial_number, 1, raw_values=raw_pts, computed_values=comp_pts)

                # Poll all remaining supported models on initial startup so state and Web UI are fully populated
                for mid in supported:
                    if not self._running:
                        break
                    if mid != 1:
                        self.poller.poll_device_model(dev.slave_id, dev.serial_number, mid)

            except Exception as e:
                logger.warning("Failed polling device %s (slave %d): %s", dev.serial_number, dev.slave_id, e)

        logger.info("Completed background initial SunSpec model poll across devices")
        self.poller.refresh_model_resolutions()
        if self.bridge:
            try:
                self.bridge.publish_discovery()
            except Exception as e:
                logger.debug("Error refreshing HA discovery after initial model poll: %s", e)

    def poll_telemetry_models_live(self):
        """Quickly read ONLY the models relevant to live power, energy, and telemetry comparisons."""
        if not self.modbus:
            return 0
        return self.poller.poll_tier("fast")

    def load_or_discover_devices(self):
        """Load devices from devices.yaml or perform a fresh scan."""
        device_config = DeviceConfig.read()
        if device_config and not self._is_empty_device_config(device_config):
            logger.info("Loading pre-configured devices from devices.yaml")
            self._load_from_device_config(device_config)
        elif self.modbus:
            logger.info("No saved devices found, performing Modbus device scan")
            self.rescan_devices(1, 100)

    def rescan_devices(self, start: int = 1, end: int = 100) -> int:
        """Perform a fresh Modbus scan across start..end, replacing stale cached devices if new devices are found."""
        if not self.modbus:
            return len(self.state.get_devices_snapshot())
        discovered = self.modbus.scan_range(start, end)
        if discovered:
            with self.state._lock:
                self.state.devices.clear()
                self.state.devices_by_slave_id.clear()
            self._save_scanned_devices(discovered)
            self.poller.refresh_model_resolutions()
        return len(discovered)

    def _is_empty_device_config(self, cfg: DeviceConfig) -> bool:
        return not (cfg.rebus_beacon or cfg.inverter or cfg.battery or cfg.pv_link or cfg.icm)

    def get_latest_record_set(self) -> Optional[Any]:
        """Return the latest raw EnergyRecordSet protobuf received via MQTT or simulator."""
        if self.is_mock and self._mock_generator:
            return getattr(self._mock_generator, "latest_record_set", None)
        if self.mqtt:
            return self.mqtt.get_energy_record_set_live()
        return None

    def get_unrecognized_proto_fields(self) -> List[Dict[str, Any]]:
        """Scan latest MQTT protobuf for unrecognized/unknown fields and unmapped channels."""
        from .mqtt import inspect_unrecognized_proto_fields
        erl = self.get_latest_record_set()
        unrecognized_topics = self.mqtt.get_unrecognized_topics() if self.mqtt else []
        return inspect_unrecognized_proto_fields(erl, unrecognized_topics)


    def _load_from_device_config(self, cfg: DeviceConfig):
        for dev_type, sn_map in cfg.to_dict().items():
            if isinstance(sn_map, dict):
                for sn, slave_id in sn_map.items():
                    self.state.register_device(
                        serial_number=sn,
                        slave_id=slave_id,
                        device_type=dev_type,
                        model_name=dev_type.replace("_", " ").title(),
                    )

    def _save_scanned_devices(self, discovered: dict):
        if not discovered:
            logger.warning("No devices discovered during Modbus scan; skipping devices.yaml save")
            return

        cfg = DeviceConfig()
        for slave_id, dev in discovered.items():
            if not hasattr(dev, "common") or not dev.common:
                continue
            sn = str(dev.common[0].SN.value).strip()
            md = str(dev.common[0].Md.value).strip()
            supported = [mid for mid in dev.models.keys() if isinstance(mid, int)] if hasattr(dev, "models") else []
            dev_type = self._classify_device_type(supported, md)
            dev_state = self.state.register_device(
                serial_number=sn,
                slave_id=slave_id,
                device_type=dev_type,
                model_name=md,
                supported_models=supported,
            )
            cfg.get_device_map(dev_type)[dev_state.serial_number] = slave_id

        if self._is_empty_device_config(cfg):
            logger.warning("No valid devices discovered during Modbus scan; skipping devices.yaml save")
            return

        cfg.write()
        logger.info("Saved discovered devices to devices.yaml")

    @staticmethod
    def _classify_device_type(supported_models: List[int], model_name: str = "") -> str:
        """Classify a discovered PWRcell device by its supported SunSpec model IDs first, then model name."""
        from pathlib import Path
        try:
            import yaml
            cfg_path = Path(__file__).resolve().parent / "data" / "device_types.yaml"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    rules = yaml.safe_load(f).get("device_types", {})
                models_set = set(supported_models)
                # 1. Model ID matching
                for dev_type, info in rules.items():
                    req_ids = set(info.get("model_ids", []))
                    if req_ids and (models_set & req_ids):
                        return dev_type
                # 2. Keyword matching on model_name
                md_lower = (model_name or "").lower()
                for dev_type, info in rules.items():
                    keywords = info.get("model_keywords", [])
                    if any(kw in md_lower for kw in keywords):
                        return dev_type
        except Exception:
            pass

        models_set = set(supported_models)
        if MODEL_REBUS_DIR in models_set:
            return "rebus_beacon"
        if models_set & {MODEL_INVERTER_SPLIT_PHASE, MODEL_INVERTER_STATUS, MODEL_REBUS_ARB, MODEL_RECONNECT}:
            return "inverter"
        if models_set & {MODEL_BATTERY_BASE, MODEL_BATTERY_STATUS, MODEL_BATTERY_WARRANTY, MODEL_LITHIUM_ION_STRING}:
            return "battery"
        if models_set & {MODEL_STRING_COMBINER, MODEL_PVLINK_STATUS, MODEL_PVRSS_CONFIG, MODEL_PVRSS_TELEMETRY, MODEL_FLASH_READER}:
            return "pv_link"

        md_lower = (model_name or "").lower()
        if "beacon" in md_lower:
            return "rebus_beacon"
        if "inverter" in md_lower:
            return "inverter"
        if "battery" in md_lower:
            return "battery"
        if "pv" in md_lower:
            return "pv_link"
        return "icm"


@contextmanager
def create_client(config: Optional[AppConfig] = None, mock: bool = False) -> Generator[PwrcellClient, None, None]:
    """Factory creating a fully managed PwrcellClient within a context manager."""
    cfg = config or AppConfig()

    if mock:
        client = PwrcellClient(config=cfg, is_mock=True)
        with client:
            yield client
        return

    with pwrcell_tunnel(cfg) as tunnel_cfg:
        modbus_client = SerializedModbusClient(
            host=tunnel_cfg.host or "127.0.0.1",
            port=tunnel_cfg.modbus_port or 502,
            tunnel=tunnel_cfg.manager,
        )
        mqtt_client = MqttClient(tunnel_cfg)

        client = PwrcellClient(
            config=cfg,
            modbus_client=modbus_client,
            mqtt_client=mqtt_client,
            is_mock=False,
        )
        with client:
            yield client
