"""Unit tests for pwrcell.poller (Tiered Modbus Poller)."""

import time
import unittest
from unittest.mock import MagicMock, patch

from pwrcell.client import PwrcellClient
from pwrcell.config import AppConfig
from pwrcell.mqtt import LiveTelemetrySnapshot
from pwrcell.poller import PollingTier, TieredModbusPoller


class TestTieredModbusPoller(unittest.TestCase):

    def setUp(self):
        self.config = AppConfig(
            poll_rate=5,
            config_poll_interval=20,
            slow_poll_interval=60,
            enable_polling=True,
        )
        self.client = PwrcellClient(config=self.config, is_mock=True)

    def tearDown(self):
        self.client.stop()

    def test_poller_init_and_to_dict(self):
        poller = self.client.poller
        self.assertIsNotNone(poller)
        self.assertEqual(poller.fast_interval, 5.0)
        self.assertEqual(poller.config_interval, 20.0)
        self.assertEqual(poller.slow_interval, 60.0)
        self.assertTrue(poller.enabled)

        d = poller.to_dict()
        self.assertTrue(d["enabled"])
        self.assertEqual(d["intervals"]["fast_seconds"], 5.0)
        self.assertEqual(d["intervals"]["config_seconds"], 20.0)
        self.assertEqual(d["intervals"]["slow_seconds"], 60.0)
        self.assertIn("fast", d["models"])
        self.assertIn("config", d["models"])
        self.assertIn("slow", d["models"])

    def test_poller_poll_tier(self):
        poller = self.client.poller
        # In mock mode with no real Modbus client, poll_tier should complete gracefully without throwing errors
        polled_fast = poller.poll_tier(PollingTier.FAST)
        self.assertEqual(polled_fast, 0)
        self.assertGreater(poller.last_poll[PollingTier.FAST.value], 0)
        self.assertEqual(poller.poll_counts[PollingTier.FAST.value], 1)

        polled_cfg = poller.poll_tier(PollingTier.CONFIG)
        self.assertEqual(polled_cfg, 0)
        self.assertGreater(poller.last_poll[PollingTier.CONFIG.value], 0)
        self.assertEqual(poller.poll_counts[PollingTier.CONFIG.value], 1)

        polled_slow = poller.poll_tier(PollingTier.SLOW)
        self.assertEqual(polled_slow, 0)
        self.assertGreater(poller.last_poll[PollingTier.SLOW.value], 0)
        self.assertEqual(poller.poll_counts[PollingTier.SLOW.value], 1)

    def test_trigger_sync(self):
        poller = self.client.poller
        poller.trigger_sync("config")
        self.assertFalse(poller._pending_triggers.empty())
        tier = poller._pending_triggers.get_nowait()
        self.assertEqual(tier, "config")

    def test_mqtt_keypad_mode_change_triggers_config_sync(self):
        """Verify that when MQTT push detects a change in system_mode (from physical panel), poller triggers config sync."""
        with patch.object(self.client.poller, "trigger_sync") as mock_trigger:
            # 1. First snapshot: establish initial mode SELF_SUPPLY (1)
            snap1 = LiveTelemetrySnapshot(
                timestamp=time.time(),
                system_mode=1,
                system_mode_name="SELF_SUPPLY",
                inverter_state=2080,
                inverter_state_name="GRID_CONNECTED",
                channels={},
            )
            self.client._on_mqtt_snapshot(snap1)
            mock_trigger.assert_not_called()
            self.assertEqual(self.client._last_known_sys_mode, 1)

            # 2. Second snapshot with SAME mode: should not trigger
            self.client._on_mqtt_snapshot(snap1)
            mock_trigger.assert_not_called()

            # 3. Third snapshot with CHANGED mode (e.g. user switched to CLEAN_BACKUP = 2 on keypad)
            snap2 = LiveTelemetrySnapshot(
                timestamp=time.time(),
                system_mode=2,
                system_mode_name="CLEAN_BACKUP",
                inverter_state=2080,
                inverter_state_name="GRID_CONNECTED",
                channels={},
            )
            self.client._on_mqtt_snapshot(snap2)
            # Must trigger immediate config sync
            mock_trigger.assert_called_once_with("config")
            self.assertEqual(self.client._last_known_sys_mode, 2)


if __name__ == "__main__":
    unittest.main()
