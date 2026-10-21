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

    def test_resolve_paths_to_models(self):
        """Verify resolve_paths_to_models converts path strings into device model mappings."""
        from pwrcell.poller import resolve_paths_to_models

        paths = [
            "inverter.inverter",
            "inverter.REbus_status",
            "pv_link.string_combiner.DCW",
            "000100034AC7:pv_link.REbus_status.P",
            "battery.model_64252.W",
            "battery.compound.battery_power",
            "rebus_beacon.REbus_dir.SysMd",
            "pv_link.404",
        ]
        resolved = resolve_paths_to_models(
            paths,
            catalog=self.client.catalog,
            state_store=self.client.state,
        )

        self.assertIn("inverter", resolved)
        self.assertIn(102, resolved["inverter"])
        self.assertIn(64207, resolved["inverter"])

        self.assertIn("pv_link", resolved)
        self.assertIn(404, resolved["pv_link"])
        self.assertIn(64207, resolved["pv_link"])

        self.assertIn("battery", resolved)
        self.assertIn(64252, resolved["battery"])
        self.assertIn(802, resolved["battery"])  # From compound battery_power

        self.assertIn("rebus_beacon", resolved)
        self.assertIn(64200, resolved["rebus_beacon"])

    def test_client_init_with_polling_tiers_config(self):
        """Verify PwrcellClient properly configures poller when polling_tiers is set in AppConfig."""
        config = AppConfig(
            polling_tiers={
                "fast": {
                    "interval": 8,
                    "paths": [
                        "inverter.inverter",
                        "pv_link.string_combiner",
                    ],
                },
                "config": {
                    "interval": 30,
                    "paths": [
                        "rebus_beacon.REbus_dir",
                    ],
                },
                "slow": [
                    "battery.battery_status",
                ],
            }
        )
        client = PwrcellClient(config=config, is_mock=True)
        try:
            poller = client.poller
            self.assertEqual(poller.fast_interval, 8.0)
            self.assertEqual(poller.config_interval, 30.0)
            self.assertEqual(poller.slow_interval, 300.0)  # default slow

            self.assertIn("inverter.inverter", poller.fast_paths)
            self.assertIn("pv_link.string_combiner", poller.fast_paths)
            self.assertIn(102, poller.fast_models["inverter"])
            self.assertIn(404, poller.fast_models["pv_link"])

            self.assertIn("rebus_beacon.REbus_dir", poller.config_paths)
            self.assertIn(64200, poller.config_models["rebus_beacon"])

            self.assertIn("battery.battery_status", poller.slow_paths)
            self.assertIn(64209, poller.slow_models["battery"])

            d = poller.to_dict()
            self.assertIn("paths", d)
            self.assertEqual(d["paths"]["fast"], poller.fast_paths)
            self.assertEqual(d["paths"]["config"], poller.config_paths)
            self.assertEqual(d["paths"]["slow"], poller.slow_paths)
        finally:
            client.stop()

    def test_sync_ha_selected_fields(self):
        """Verify selecting a field in Home Assistant auto-promotes its model to the slow poller tier."""
        poller = self.client.poller
        # Initially, pv_link 404 is in slow_models
        self.assertIn(404, poller.slow_models.get("pv_link", []))

        # Clear slow_models for pv_link
        poller.slow_models["pv_link"] = []

        # Sync an HA entity that uses pv_link Model 404
        poller.sync_ha_selected_fields(["000100034AC7:pv_link.string_combiner.DCW"])

        # Model 404 should now be auto-registered in slow_models
        self.assertIn(404, poller.slow_models["pv_link"])


if __name__ == "__main__":
    unittest.main()
