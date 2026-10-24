"""Tiered Modbus Polling Engine for Generac PWRcell (v3).

Provides structured periodic polling across 4 distinct operational tiers:
1. Fast Telemetry (10-15s): Real-time power, voltage, current, SoC, operating status.
2. Config & Keypad State Sync (30-60s): System Mode (SysMd), keypad-adjusted parameters, reconnect settings.
3. Slow Monotonic & Diagnostics (3-5 min): Cumulative energy counters (kWh), temperatures, health.
4. Static / Nameplate (Startup): Model 1 serial number, model name, ratings.

Also supports:
- Event-triggered one-shot sync (e.g. MQTT detects keypad mode change -> immediate Modbus sync).
- Web UI on-demand sync endpoints.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .catalog import (
    MODEL_BATTERY_BASE,
    MODEL_BATTERY_STATUS,
    MODEL_BATTERY_WARRANTY,
    MODEL_COMMON,
    MODEL_CONTROLS,
    MODEL_EI_CONFIG,
    MODEL_FLASH_READER,
    MODEL_INVERTER_SPLIT_PHASE,
    MODEL_INVERTER_STATUS,
    MODEL_IP_SETTINGS,
    MODEL_LITHIUM_ION_STRING,
    MODEL_NAMEPLATE,
    MODEL_PVLINK_STATUS,
    MODEL_PVRSS_CONFIG,
    MODEL_PVRSS_TELEMETRY,
    MODEL_REBUS_ARB,
    MODEL_REBUS_DIR,
    MODEL_REBUS_STATUS,
    MODEL_RECONNECT,
    MODEL_SCHEDULE,
    MODEL_STRING_COMBINER,
    MODEL_TZ_CONFIG,
    MODEL_VOLT_VAR,
    MODEL_VOLT_WATT,
    is_sunspec_sentinel,
)

if TYPE_CHECKING:
    from .client import PwrcellClient

logger = logging.getLogger(__name__)


def safe_point_cvalue(point: Any) -> Any:
    """Safely obtain computed point value from SunSpec point, preventing math range errors and sentinel corruption."""
    try:
        pt_type = getattr(point, "ptype", None) or getattr(getattr(point, "point_type", None), "type", None)
        raw_val = getattr(point, "value", None)
        if raw_val is not None and is_sunspec_sentinel(raw_val, pt_type):
            return None

        # Check scale factor beforehand if point requires one
        if getattr(point, "sf_required", False):
            sf_name = getattr(point, "sf", None)
            sf_pt = None
            if sf_name:
                grp = getattr(point, "group", None)
                if grp and hasattr(grp, "points"):
                    sf_pt = grp.points.get(sf_name)
                if sf_pt is None and hasattr(point, "model") and hasattr(point.model, "points"):
                    sf_pt = point.model.points.get(sf_name)
            if sf_pt is not None:
                sf_val = getattr(sf_pt, "value", None)
                if sf_val is None or is_sunspec_sentinel(sf_val, "sunssf") or not (-10 <= sf_val <= 10):
                    return None
            elif getattr(point, "sf_value", None) is not None:
                sf_v = point.sf_value
                if is_sunspec_sentinel(sf_v, "sunssf") or not (-10 <= sf_v <= 10):
                    return None

        val = point.cvalue
        if val is not None and isinstance(val, (int, float)):
            if math.isnan(val) or math.isinf(val) or abs(val) > 1e12:
                return None
        return val
    except (OverflowError, ValueError, TypeError, ZeroDivisionError) as e:
        logger.debug("Error computing cvalue for point %s: %s", getattr(point, "pdef", {}).get("name", point), e)
        return None


class PollingTier(str, Enum):
    """Operational tiers for Modbus polling."""
    FAST = "fast"
    CONFIG = "config"
    SLOW = "slow"


# PWRcell device type to model name/ID dictionary fallback
PWRCELL_DEVICE_MODEL_MAP: Dict[str, Dict[str, int]] = {
    "inverter": {
        "inverter": MODEL_INVERTER_SPLIT_PHASE,
        "REbus_status": MODEL_REBUS_STATUS,
        "inverter_status": MODEL_INVERTER_STATUS,
        "REbus_exp": MODEL_INVERTER_STATUS,
        "EIconfig": MODEL_EI_CONFIG,
        "REbus_arb": MODEL_REBUS_ARB,
        "reconnect": MODEL_RECONNECT,
        "nameplate": MODEL_NAMEPLATE,
        "controls": MODEL_CONTROLS,
        "volt_var": MODEL_VOLT_VAR,
        "volt_watt": MODEL_VOLT_WATT,
        "common": MODEL_COMMON,
    },
    "battery": {
        "battery": MODEL_BATTERY_BASE,
        "model_64252": MODEL_BATTERY_WARRANTY,
        "DCB105_warranty": MODEL_BATTERY_WARRANTY,
        "battery_status": MODEL_BATTERY_STATUS,
        "model_64209": MODEL_BATTERY_STATUS,
        "REbus_status": MODEL_REBUS_STATUS,
        "lithium_ion_string": MODEL_LITHIUM_ION_STRING,
        "common": MODEL_COMMON,
    },
    "pv_link": {
        "string_combiner": MODEL_STRING_COMBINER,
        "REbus_status": MODEL_REBUS_STATUS,
        "pvlink_status": MODEL_PVLINK_STATUS,
        "flash_reader": MODEL_FLASH_READER,
        "pvrss_config": MODEL_PVRSS_CONFIG,
        "pvrss_telemetry": MODEL_PVRSS_TELEMETRY,
        "common": MODEL_COMMON,
    },
    "rebus_beacon": {
        "REbus_dir": MODEL_REBUS_DIR,
        "tz_config": MODEL_TZ_CONFIG,
        "schedule": MODEL_SCHEDULE,
        "ip_settings": MODEL_IP_SETTINGS,
        "common": MODEL_COMMON,
    },
    "icm": {
        "common": MODEL_COMMON,
    },
}

# Default paths for each tier using unified ha_config path notation
DEFAULT_FAST_PATHS: List[str] = [
    "inverter.inverter",
    "inverter.REbus_status",
    "inverter.inverter_status",
    "battery.battery",
    "battery.model_64252",
    "pv_link.REbus_status",
]

DEFAULT_CONFIG_PATHS: List[str] = [
    "rebus_beacon.REbus_dir",
    "inverter.inverter",
]

DEFAULT_SLOW_PATHS: List[str] = [
    "battery.battery_status",
    "inverter.inverter_status",
    "pv_link.string_combiner",
]


def resolve_subgroup_to_model_id(
    dev_type: str,
    sub_group: str,
    catalog: Optional[Any] = None,
    state_store: Optional[Any] = None,
    exact_path: Optional[str] = None,
) -> Optional[int]:
    """Resolve a single (device_type, sub_group) or exact field path to a SunSpec model ID."""
    sub = sub_group.strip()
    if not sub:
        return None
    if sub.isdigit():
        return int(sub)
    if sub.startswith("model_") and sub[6:].isdigit():
        return int(sub[6:])

    # Strip repeating instance suffix e.g. string_combiner_1 -> string_combiner
    base_sub = sub.rsplit("_", 1)[0] if ("_" in sub and sub.rsplit("_", 1)[1].isdigit() and not sub.startswith("model_")) else sub

    if state_store and hasattr(state_store, "devices"):
        for dev in state_store.devices.values():
            if dev.device_type == dev_type:
                for f in dev.fields.values():
                    if f.model_id and (
                        f.model_name in (sub, base_sub)
                        or f.key.startswith(f"{dev_type}.{sub}.")
                        or (exact_path and (f.key == exact_path or f.key.startswith(f"{exact_path}.")))
                    ):
                        return f.model_id

    dev_map = PWRCELL_DEVICE_MODEL_MAP.get(dev_type, {})
    if sub in dev_map:
        return dev_map[sub]
    if base_sub in dev_map:
        return dev_map[base_sub]

    if catalog and hasattr(catalog, "get_model_by_name"):
        m_def = catalog.get_model_by_name(sub) or catalog.get_model_by_name(base_sub)
        if m_def:
            return m_def.model_id

    return None


def resolve_paths_to_models(
    paths: List[str],
    catalog: Optional[Any] = None,
    state_store: Optional[Any] = None,
    optimize: bool = False,
) -> Dict[str, List[int]]:
    """Resolve unified path strings to SunSpec model IDs per device type.

    Accepts:
    - Model prefixes: 'pv_link.string_combiner', 'inverter.REbus_status'
    - Specific points: 'pv_link.string_combiner.DCW', 'inverter.inverter.A'
    - Compound views: 'inverter.compound.grid_power', 'battery.compound.battery_power'
    - Qualified paths with serials: '000100034AC7:pv_link.string_combiner.DCW'
    - Numeric models: 'pv_link.404', 'battery.model_64252'
    - Wildcards: 'pv_link.*', 'battery'

    When optimize=True or when concept/unified paths are supplied, uses Set Cover
    optimization to compute the exact minimal model set.
    """
    if optimize or any((".concept." in p or ".unified." in p) for p in paths if isinstance(p, str)):
        from .optimizer import resolve_minimal_models_for_paths
        return resolve_minimal_models_for_paths(paths, state_store=state_store, catalog=catalog)

    from .mapping import MappingRegistry

    result: Dict[str, Set[int]] = {}

    for raw_p in paths:
        if not raw_p or not isinstance(raw_p, str):
            continue
        p = raw_p.strip()
        if not p:
            continue

        # Strip device serial prefix if qualified (<SERIAL>:<PATH>)
        if ":" in p:
            _, p = p.split(":", 1)
            p = p.strip()

        parts = p.split(".")
        dev_type = parts[0].strip().lower()

        if len(parts) == 1 or parts[1].strip() == "*":
            # Wildcard: include all supported/known models for this device type
            models_to_add: Set[int] = set()
            if state_store and hasattr(state_store, "devices"):
                for dev in state_store.devices.values():
                    if dev.device_type == dev_type and dev.supported_models:
                        models_to_add.update(dev.supported_models)
            if not models_to_add and dev_type in PWRCELL_DEVICE_MODEL_MAP:
                models_to_add.update(PWRCELL_DEVICE_MODEL_MAP[dev_type].values())
            if models_to_add:
                result.setdefault(dev_type, set()).update(models_to_add)
            continue

        sub_group = parts[1].strip()

        # Handle compound field paths (e.g. 'battery.compound.battery_power')
        if sub_group == "compound" and len(parts) >= 3:
            comp_id = parts[2].strip()
            reg = MappingRegistry.get_instance()
            mapping = reg.get_by_id(comp_id)
            if mapping:
                candidates = list(mapping.modbus_candidates)
                if mapping.modbus_field:
                    candidates.append(mapping.modbus_field)
                if candidates:
                    sub_resolved = resolve_paths_to_models(candidates, catalog, state_store)
                    for d_t, mids in sub_resolved.items():
                        result.setdefault(d_t, set()).update(mids)
            continue

        mid = resolve_subgroup_to_model_id(
            dev_type,
            sub_group,
            catalog=catalog,
            state_store=state_store,
            exact_path=p,
        )
        if mid is not None:
            result.setdefault(dev_type, set()).add(mid)

    return {d: sorted(list(mids)) for d, mids in result.items() if mids}


# Default SunSpec models by device type for each polling tier (derived from DEFAULT_*_PATHS)
DEFAULT_FAST_MODELS: Dict[str, List[int]] = resolve_paths_to_models(DEFAULT_FAST_PATHS)
DEFAULT_CONFIG_MODELS: Dict[str, List[int]] = resolve_paths_to_models(DEFAULT_CONFIG_PATHS)
DEFAULT_SLOW_MODELS: Dict[str, List[int]] = resolve_paths_to_models(DEFAULT_SLOW_PATHS)


class TieredModbusPoller:
    """Background daemon scheduling Modbus reads across tiered intervals."""

    def __init__(
        self,
        client: PwrcellClient,
        fast_interval: float = 12.0,
        config_interval: float = 45.0,
        slow_interval: float = 300.0,
        enabled: bool = True,
        fast_models: Optional[Dict[str, List[int]]] = None,
        config_models: Optional[Dict[str, List[int]]] = None,
        slow_models: Optional[Dict[str, List[int]]] = None,
        fast_paths: Optional[List[str]] = None,
        config_paths: Optional[List[str]] = None,
        slow_paths: Optional[List[str]] = None,
    ):
        self.client = client
        self.fast_interval = max(1.0, float(fast_interval))
        self.config_interval = max(5.0, float(config_interval))
        self.slow_interval = max(10.0, float(slow_interval))
        self.enabled = enabled

        self.fast_paths = list(fast_paths) if fast_paths is not None else list(DEFAULT_FAST_PATHS)
        self.config_paths = list(config_paths) if config_paths is not None else list(DEFAULT_CONFIG_PATHS)
        self.slow_paths = list(slow_paths) if slow_paths is not None else list(DEFAULT_SLOW_PATHS)

        # Resolve models from paths if explicit model dictionaries were not supplied
        if fast_models is not None:
            self.fast_models = dict(fast_models)
        else:
            self.fast_models = resolve_paths_to_models(
                self.fast_paths,
                catalog=client.catalog if client else None,
                state_store=client.state if client else None,
            )

        if config_models is not None:
            self.config_models = dict(config_models)
        else:
            self.config_models = resolve_paths_to_models(
                self.config_paths,
                catalog=client.catalog if client else None,
                state_store=client.state if client else None,
            )

        if slow_models is not None:
            self.slow_models = dict(slow_models)
        else:
            self.slow_models = resolve_paths_to_models(
                self.slow_paths,
                catalog=client.catalog if client else None,
                state_store=client.state if client else None,
            )

        self.last_poll: Dict[str, float] = {
            PollingTier.FAST.value: 0.0,
            PollingTier.CONFIG.value: 0.0,
            PollingTier.SLOW.value: 0.0,
        }
        self.poll_counts: Dict[str, int] = {
            PollingTier.FAST.value: 0,
            PollingTier.CONFIG.value: 0,
            PollingTier.SLOW.value: 0,
            "errors": 0,
        }

        self._pending_triggers: queue.Queue[str] = queue.Queue()
        self._last_discovery_retry: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cond = threading.Condition()

    def start(self):
        """Start background polling thread."""
        with self._cond:
            if self._running or not self.enabled:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="PwrCellTieredPoller",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Started Tiered Modbus Poller (fast=%gs, config=%gs, slow=%gs)",
                self.fast_interval,
                self.config_interval,
                self.slow_interval,
            )

    def stop(self, timeout: float = 2.0):
        """Stop background polling thread."""
        with self._cond:
            if not self._running:
                return
            self._running = False
            self._cond.notify_all()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Stopped Tiered Modbus Poller")

    def trigger_sync(self, tier: str | PollingTier = "config"):
        """Queue an immediate out-of-band poll for a specific tier (e.g. on keypad mode change)."""
        tier_val = tier.value if isinstance(tier, PollingTier) else str(tier).strip().lower()
        valid_tiers = {PollingTier.FAST.value, PollingTier.CONFIG.value, PollingTier.SLOW.value, "all", "deep"}
        if tier_val not in valid_tiers:
            raise ValueError(f"Unknown polling tier: {tier!r}. Expected one of {sorted(valid_tiers)}")
        with self._cond:
            self._pending_triggers.put(tier_val)
            self._cond.notify_all()
        logger.debug("Queued immediate Modbus sync trigger for tier: %s", tier_val)

    def poll_tier(self, tier: str | PollingTier) -> int:
        """Poll all devices and models for a given tier synchronously. Returns models read count."""
        tier_str = tier.value if isinstance(tier, PollingTier) else str(tier).lower()
        with self._cond:
            if tier_str == PollingTier.FAST.value:
                models_map = {k: list(v) for k, v in self.fast_models.items()}
            elif tier_str == PollingTier.CONFIG.value:
                models_map = {k: list(v) for k, v in self.config_models.items()}
            elif tier_str == PollingTier.SLOW.value:
                models_map = {k: list(v) for k, v in self.slow_models.items()}
            elif tier_str in ("all", "deep"):
                models_map = None
            else:
                logger.warning("Unknown polling tier requested: %s", tier_str)
                return 0

        if models_map is None:
            return self.poll_all_devices_all_models()

        polled_count = 0
        devices = self.client.state.get_devices_snapshot()

        for dev in devices:
            if dev.slave_id is None:
                continue
            target_models = models_map.get(dev.device_type, [])
            for mid in target_models:
                success = self.poll_device_model(dev.slave_id, dev.serial_number, mid)
                if success:
                    polled_count += 1

        with self._cond:
            self.last_poll[tier_str] = time.time()
            self.poll_counts[tier_str] = self.poll_counts.get(tier_str, 0) + 1
        logger.debug("Completed Modbus poll for tier '%s': %d models updated", tier_str, polled_count)
        return polled_count

    def poll_device_model(self, slave_id: int, serial_number: str, model_id: int) -> bool:
        """Read a single SunSpec model block for a device and update StateStore."""
        if not self.client.modbus:
            return False

        try:
            tcp_dev = self.client.modbus.get_or_create_device(slave_id)
            if not tcp_dev.models:
                tcp_dev = self.client.modbus.scan_device(slave_id, full_model_read=False)
                if not tcp_dev:
                    return False

            if model_id in tcp_dev.models:
                models_list = tcp_dev.models.get(model_id) or []
                num_instances = len(models_list) if isinstance(models_list, (list, tuple)) else 1
                any_read = False
                for idx in range(max(1, num_instances)):
                    model_inst = self.client.modbus.read_model_block(tcp_dev, model_id, index=idx)
                    if model_inst:
                        raw_pts = {p_name: p.value for p_name, p in model_inst.points.items()}
                        comp_pts = {p_name: safe_point_cvalue(p) for p_name, p in model_inst.points.items()}
                        self.client.state.update_from_modbus_points(
                            serial_number,
                            model_id,
                            raw_values=raw_pts,
                            computed_values=comp_pts,
                            instance_index=idx,
                        )
                        any_read = True
                return any_read
        except Exception as e:
            with self._cond:
                self.poll_counts["errors"] = self.poll_counts.get("errors", 0) + 1
                err_cnt = self.poll_counts["errors"]
            if err_cnt % 20 == 1:
                logger.warning("Repeated Modbus read failure on model %s (slave %d, %s): %s (total errors: %d)", model_id, slave_id, serial_number, e, err_cnt)
            else:
                logger.debug("Failed reading model %s on slave %d (%s): %s", model_id, slave_id, serial_number, e)

        return False

    def poll_device_all_models(self, slave_id: int, serial_number: str) -> int:
        """Poll all supported SunSpec models for a specific device."""
        dev = self.client.state.get_device(serial_number)
        models_to_poll = list(dev.supported_models) if (dev and dev.supported_models) else []
        if not models_to_poll and self.client.modbus:
            tcp_dev = self.client.modbus.get_or_create_device(slave_id)
            if not tcp_dev.models:
                tcp_dev = self.client.modbus.scan_device(slave_id, full_model_read=False)
            if tcp_dev and tcp_dev.models:
                models_to_poll = [mid for mid in tcp_dev.models.keys() if isinstance(mid, int)]
                if dev:
                    self.client.state.set_supported_models(serial_number, models_to_poll)

        polled_count = 0
        for mid in sorted(models_to_poll):
            if self.poll_device_model(slave_id, serial_number, mid):
                polled_count += 1
        return polled_count

    def poll_all_devices_all_models(self) -> int:
        """Poll all supported models across all devices."""
        total = 0
        for dev in self.client.state.get_devices_snapshot():
            if dev.slave_id is not None:
                total += self.poll_device_all_models(dev.slave_id, dev.serial_number)
        with self._cond:
            self.last_poll["all"] = time.time()
            self.poll_counts["all"] = self.poll_counts.get("all", 0) + 1
        return total

    def refresh_model_resolutions(self):
        """Re-resolve model assignments against discovered devices in StateStore."""
        resolved_fast = resolve_paths_to_models(
            self.fast_paths,
            catalog=self.client.catalog if self.client else None,
            state_store=self.client.state if self.client else None,
        )
        resolved_config = resolve_paths_to_models(
            self.config_paths,
            catalog=self.client.catalog if self.client else None,
            state_store=self.client.state if self.client else None,
        )
        resolved_slow = resolve_paths_to_models(
            self.slow_paths,
            catalog=self.client.catalog if self.client else None,
            state_store=self.client.state if self.client else None,
        )
        with self._cond:
            for dev_type, mids in resolved_fast.items():
                self.fast_models[dev_type] = sorted(list(set(self.fast_models.get(dev_type, [])) | set(mids)))
            for dev_type, mids in resolved_config.items():
                self.config_models[dev_type] = sorted(list(set(self.config_models.get(dev_type, [])) | set(mids)))
            for dev_type, mids in resolved_slow.items():
                self.slow_models[dev_type] = sorted(list(set(self.slow_models.get(dev_type, [])) | set(mids)))

    def sync_ha_selected_fields(self, selected_keys: List[str]):
        """Ensure all SunSpec models backing selected Home Assistant entities are polled (minimal set)."""
        ha_models = resolve_paths_to_models(
            selected_keys,
            catalog=self.client.catalog if self.client else None,
            state_store=self.client.state if self.client else None,
            optimize=True,
        )
        with self._cond:
            for dev_type, model_ids in ha_models.items():
                current_active = (
                    set(self.fast_models.get(dev_type, []))
                    | set(self.config_models.get(dev_type, []))
                    | set(self.slow_models.get(dev_type, []))
                )
                for mid in model_ids:
                    if mid not in current_active:
                        self.slow_models.setdefault(dev_type, []).append(mid)
                        self.slow_models[dev_type] = sorted(list(set(self.slow_models[dev_type])))
                        logger.info(
                            "Auto-registered model %s on %s to slow polling tier for selected Home Assistant entity",
                            mid,
                            dev_type,
                        )

    def to_dict(self) -> Dict[str, Any]:
        """Return JSON-serializable status dictionary for Web UI and REST API."""
        with self._cond:
            return {
                "enabled": self.enabled,
                "running": self._running,
                "intervals": {
                    "fast_seconds": self.fast_interval,
                    "config_seconds": self.config_interval,
                    "slow_seconds": self.slow_interval,
                },
                "last_poll": {
                    "fast": self.last_poll.get(PollingTier.FAST.value, 0.0),
                    "config": self.last_poll.get(PollingTier.CONFIG.value, 0.0),
                    "slow": self.last_poll.get(PollingTier.SLOW.value, 0.0),
                },
                "poll_counts": dict(self.poll_counts),
                "paths": {
                    "fast": list(self.fast_paths),
                    "config": list(self.config_paths),
                    "slow": list(self.slow_paths),
                },
                "models": {
                    "fast": {k: list(v) for k, v in self.fast_models.items()},
                    "config": {k: list(v) for k, v in self.config_models.items()},
                    "slow": {k: list(v) for k, v in self.slow_models.items()},
                },
            }

    def _worker_loop(self):
        """Internal daemon loop scheduling polls and processing triggers."""
        # Initial stagger: wait 2 seconds after startup before first poll
        time.sleep(2.0)

        while True:
            with self._cond:
                if not self._running:
                    break

            # 1. Process pending immediate triggers
            triggered_tiers: Set[str] = set()
            while not self._pending_triggers.empty():
                try:
                    t = self._pending_triggers.get_nowait()
                    triggered_tiers.add(t)
                except queue.Empty:
                    break

            for t in triggered_tiers:
                try:
                    self.poll_tier(t)
                except Exception as e:
                    logger.error("Error executing triggered poll for tier %s: %s", t, e)

            # 2. Check periodic intervals
            now = time.time()

            # If no devices are registered (e.g. initial connection failed or inverter was rebooting), retry discovery
            with self.client.state._lock:
                no_devices = len(self.client.state.devices) == 0
            if no_devices and (now - self._last_discovery_retry >= 30.0):
                self._last_discovery_retry = now
                logger.info("No devices registered in StateStore; attempting Modbus discovery...")
                try:
                    self.client.load_or_discover_devices()
                    self.client._poll_device_models_live()
                except Exception as de:
                    logger.debug("Discovery retry failed: %s", de)

            # Fast Tier
            if now - self.last_poll.get(PollingTier.FAST.value, 0.0) >= self.fast_interval:
                try:
                    self.poll_tier(PollingTier.FAST)
                except Exception as e:
                    logger.error("Error during fast tier poll: %s", e)

            # Config & Keypad State Sync Tier
            now = time.time()
            if now - self.last_poll.get(PollingTier.CONFIG.value, 0.0) >= self.config_interval:
                try:
                    self.poll_tier(PollingTier.CONFIG)
                except Exception as e:
                    logger.error("Error during config tier poll: %s", e)

            # Slow Energy & Diagnostics Tier
            now = time.time()
            if now - self.last_poll.get(PollingTier.SLOW.value, 0.0) >= self.slow_interval:
                try:
                    self.poll_tier(PollingTier.SLOW)
                except Exception as e:
                    logger.error("Error during slow tier poll: %s", e)

            # 3. Wait up to 1 second before next tick or trigger notification
            with self._cond:
                if not self._running:
                    break
                self._cond.wait(timeout=1.0)
