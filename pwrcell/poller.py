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
import queue
import threading
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from .client import PwrcellClient

logger = logging.getLogger(__name__)


class PollingTier(str, Enum):
    """Operational tiers for Modbus polling."""
    FAST = "fast"
    CONFIG = "config"
    SLOW = "slow"


# Default SunSpec models by device type for each polling tier
DEFAULT_FAST_MODELS: Dict[str, List[int]] = {
    "inverter": [102, 64208, 64207],
    "battery": [802, 64252],
    "pv_link": [64207],
}

DEFAULT_CONFIG_MODELS: Dict[str, List[int]] = {
    "rebus_beacon": [64200],  # Master Operating Mode (SysMd), system controls
    "inverter": [102],        # Inverter state & grid reconnect parameters
}

DEFAULT_SLOW_MODELS: Dict[str, List[int]] = {
    "battery": [64209],       # Cumulative energy charged / discharged (WhIn, WhOut)
    "inverter": [64208],      # Cumulative grid energy (WhIn, WhOut)
    "pv_link": [404],         # DC string combiner metrics, temperatures
}


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
    ):
        self.client = client
        self.fast_interval = max(1.0, float(fast_interval))
        self.config_interval = max(5.0, float(config_interval))
        self.slow_interval = max(10.0, float(slow_interval))
        self.enabled = enabled

        self.fast_models = dict(fast_models or DEFAULT_FAST_MODELS)
        self.config_models = dict(config_models or DEFAULT_CONFIG_MODELS)
        self.slow_models = dict(slow_models or DEFAULT_SLOW_MODELS)

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
        tier_val = tier.value if isinstance(tier, PollingTier) else str(tier).lower()
        with self._cond:
            self._pending_triggers.put(tier_val)
            self._cond.notify_all()
        logger.debug("Queued immediate Modbus sync trigger for tier: %s", tier_val)

    def poll_tier(self, tier: str | PollingTier) -> int:
        """Poll all devices and models for a given tier synchronously. Returns models read count."""
        tier_str = tier.value if isinstance(tier, PollingTier) else str(tier).lower()
        if tier_str == PollingTier.FAST.value:
            models_map = self.fast_models
        elif tier_str == PollingTier.CONFIG.value:
            models_map = self.config_models
        elif tier_str == PollingTier.SLOW.value:
            models_map = self.slow_models
        elif tier_str in ("all", "deep"):
            return self.poll_all_devices_all_models()
        else:
            logger.warning("Unknown polling tier requested: %s", tier_str)
            return 0

        polled_count = 0
        devices = list(self.client.state.devices.values())

        for dev in devices:
            if dev.slave_id is None:
                continue
            target_models = models_map.get(dev.device_type, [])
            for mid in target_models:
                success = self.poll_device_model(dev.slave_id, dev.serial_number, mid)
                if success:
                    polled_count += 1

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
                model_inst = self.client.modbus.read_model_block(tcp_dev, model_id)
                if model_inst:
                    raw_pts = {p_name: p.value for p_name, p in model_inst.points.items()}
                    comp_pts = {p_name: p.cvalue for p_name, p in model_inst.points.items()}
                    self.client.state.update_from_modbus_points(
                        serial_number,
                        model_id,
                        raw_values=raw_pts,
                        computed_values=comp_pts,
                    )
                    return True
        except Exception as e:
            self.poll_counts["errors"] = self.poll_counts.get("errors", 0) + 1
            logger.debug("Failed reading model %s on slave %d (%s): %s", model_id, slave_id, serial_number, e)

        return False

    def poll_device_all_models(self, slave_id: int, serial_number: str) -> int:
        """Poll all supported SunSpec models for a specific device."""
        dev = self.client.state.devices.get(serial_number)
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
        for dev in list(self.client.state.devices.values()):
            if dev.slave_id is not None:
                total += self.poll_device_all_models(dev.slave_id, dev.serial_number)
        self.last_poll["all"] = time.time()
        self.poll_counts["all"] = self.poll_counts.get("all", 0) + 1
        return total

    def to_dict(self) -> Dict[str, Any]:
        """Return JSON-serializable status dictionary for Web UI and REST API."""
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
            "models": {
                "fast": self.fast_models,
                "config": self.config_models,
                "slow": self.slow_models,
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
