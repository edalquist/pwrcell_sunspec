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

        with self.assertRaises(ValueError):
            poller.trigger_sync("invalid_tier")
        self.assertTrue(poller._pending_triggers.empty())

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

    def test_safe_point_cvalue_sentinel_scale_factors(self):
        """Verify safe_point_cvalue protects against math range error when scale factor is a sentinel."""
        from pwrcell.poller import safe_point_cvalue

        # Mock point with sentinel scale factor
        sf_pt = MagicMock()
        sf_pt.value = 32767  # Sentinel int16 overflow

        p = MagicMock()
        p.sf_required = True
        p.sf = "VT_sf"
        p.group = MagicMock()
        p.group.points = {"VT_sf": sf_pt}
        p.model = MagicMock()
        p.model.points = {"VT_sf": sf_pt}

        # Should return None without raising OverflowError
        res = safe_point_cvalue(p)
        self.assertIsNone(res)

        # Scale factor is 65535 (uint16 sentinel)
        sf_pt.value = 65535
        self.assertIsNone(safe_point_cvalue(p))

        # Scale factor is -32768 (unimplemented sentinel)
        sf_pt.value = -32768
        self.assertIsNone(safe_point_cvalue(p))

        # Scale factor out of [-10, 10] range
        sf_pt.value = 50
        self.assertIsNone(safe_point_cvalue(p))

        # Scale factor is None
        sf_pt.value = None
        self.assertIsNone(safe_point_cvalue(p))

        # Valid scale factor -1
        sf_pt.value = -1
        p.cvalue = 381.6
        self.assertEqual(safe_point_cvalue(p), 381.6)

    def test_safe_point_cvalue_catches_overflow_error(self):
        """Verify safe_point_cvalue catches OverflowError/ValueError/TypeError/ZeroDivisionError and logs at debug, while propagating unexpected exceptions."""
        from pwrcell.poller import safe_point_cvalue

        p = MagicMock()
        p.sf_required = False
        p.pdef = {"name": "V"}
        type(p).cvalue = unittest.mock.PropertyMock(side_effect=OverflowError("math range error"))

        with self.assertLogs("pwrcell.poller", level="DEBUG") as cm:
            self.assertIsNone(safe_point_cvalue(p))
        self.assertTrue(any("math range error" in line for line in cm.output))

        # Unexpected exception (e.g. RuntimeError) must NOT be silently swallowed
        type(p).cvalue = unittest.mock.PropertyMock(side_effect=RuntimeError("unexpected bug"))
        with self.assertRaises(RuntimeError):
            safe_point_cvalue(p)

    def test_model_64207_sentinel_scale_factors_in_state(self):
        """Verify model 64207 points with cvalue from safe_point_cvalue (or raw fallback without home-grown scaling) are handled safely in StateStore."""
        state = self.client.state
        dev = state.register_device("000100034AC7", 3, "pv_link", "PV Link")

        # Simulate polling Model 64207 where safe_point_cvalue returned None for V and T (due to invalid VT_sf=32767)
        # and 0.0 for I (due to valid I_sf=-2)
        raw_values = {
            "P": 0,
            "E": 2153252067,
            "V": 3816,
            "I": 0,
            "T": 154,
            "St": 12546,
            "Ev": 34048,
            "RB": 8225,
            "VT_sf": 32767,
            "I_sf": -2,
        }
        computed_values = {
            "P": 0,
            "E": 2153252067,
            "V": None,
            "I": 0.0,
            "T": None,
            "St": 12546,
            "Ev": 34048,
            "RB": 8225,
            "VT_sf": None,
            "I_sf": -2,
        }
        state.update_from_modbus_points(
            "000100034AC7",
            64207,
            raw_values=raw_values,
            computed_values=computed_values,
        )

        # Points V and T have computed_values=None. Their value MUST be None!
        v_field = dev.fields.get("pv_link.REbus_status.V")
        self.assertIsNotNone(v_field)
        self.assertIsNone(v_field.value)

        # Point I has computed_values=0.0
        i_field = dev.fields.get("pv_link.REbus_status.I")
        self.assertIsNotNone(i_field)
        self.assertEqual(i_field.value, 0.0)

        # Verify that without computed_values, update_from_modbus_points does NOT re-implement home-grown SF scaling
        state.update_from_modbus_points(
            "000100034AC7",
            64207,
            raw_values={"V": 380, "VT_sf": -1},
        )
        self.assertEqual(dev.fields["pv_link.REbus_status.V"].value, 380)

        # Bitfield RB should be properly decoded into symbols
        rb_field = dev.fields.get("pv_link.REbus_status.RB")
        self.assertIsNotNone(rb_field)
        self.assertIn("HEARTBEAT_GOOD", rb_field.active_flags)

        # Enum St should be decoded to LOW_SUN with substate 2
        st_field = dev.fields.get("pv_link.REbus_status.St")
        self.assertIsNotNone(st_field)
        self.assertEqual(st_field.value, "LOW_SUN")
        self.assertEqual(st_field.raw_value, 12546)
        self.assertEqual(st_field.substate, 2)

    def test_default_tier_models_match_default_paths(self):
        """Verify DEFAULT_*_MODELS are consistently derived from DEFAULT_*_PATHS."""
        from pwrcell.poller import (
            DEFAULT_CONFIG_MODELS,
            DEFAULT_CONFIG_PATHS,
            DEFAULT_FAST_MODELS,
            DEFAULT_FAST_PATHS,
            DEFAULT_SLOW_MODELS,
            DEFAULT_SLOW_PATHS,
            resolve_paths_to_models,
        )

        self.assertEqual(DEFAULT_FAST_MODELS, resolve_paths_to_models(DEFAULT_FAST_PATHS))
        self.assertEqual(DEFAULT_CONFIG_MODELS, resolve_paths_to_models(DEFAULT_CONFIG_PATHS))
        self.assertEqual(DEFAULT_SLOW_MODELS, resolve_paths_to_models(DEFAULT_SLOW_PATHS))
        self.assertIn("inverter.inverter", DEFAULT_FAST_PATHS)
        self.assertNotIn("inverter.inverter", DEFAULT_CONFIG_PATHS)

    def test_poll_device_model_reads_multiple_instances(self):
        """Verify poll_device_model reads all instances of a repeating SunSpec model without key collisions."""
        state = self.client.state
        dev = state.register_device("000100034AC7", 3, "pv_link", "PV Link")

        m_inst0 = MagicMock()
        p0 = MagicMock()
        p0.value = 1200
        p0.cvalue = 1200.0
        p0.sf_required = False
        m_inst0.points = {"DCW": p0}

        m_inst1 = MagicMock()
        p1 = MagicMock()
        p1.value = 850
        p1.cvalue = 850.0
        p1.sf_required = False
        m_inst1.points = {"DCW": p1}

        tcp_dev = MagicMock()
        tcp_dev.models = {404: [m_inst0, m_inst1]}

        mock_mb = MagicMock()
        mock_mb.get_or_create_device.return_value = tcp_dev
        mock_mb.read_model_block.side_effect = lambda d, mid, index=0: d.models[mid][index]
        self.client.modbus = mock_mb

        ok = self.client.poller.poll_device_model(3, "000100034AC7", 404)
        self.assertTrue(ok)
        self.assertIn("pv_link.string_combiner.DCW", dev.fields)
        self.assertIn("pv_link.string_combiner_1.DCW", dev.fields)
        self.assertEqual(dev.fields["pv_link.string_combiner.DCW"].value, 1200.0)
        self.assertEqual(dev.fields["pv_link.string_combiner_1.DCW"].value, 850.0)

    def test_resolve_paths_to_models_exact_match_no_prefix_collision(self):
        """Verify resolving 'battery.battery' does NOT match 'battery.battery_status' (64209) when only battery_status is in state."""
        from pwrcell.poller import resolve_paths_to_models
        from pwrcell.state import StateStore

        empty_state = StateStore(catalog=self.client.catalog)
        bat = empty_state.register_device("BAT_TEST", 9, "battery", "Battery")
        empty_state.update_from_modbus_points("BAT_TEST", 64209, raw_values={"WhIn": 100})

        resolved = resolve_paths_to_models(["battery.battery"], catalog=self.client.catalog, state_store=empty_state)
        self.assertEqual(resolved.get("battery"), [802])

    def test_poll_tier_tracks_success_separately_from_attempts(self):
        """If devices exist and every model read in a tier fails, last_poll and poll_counts must not advance (only poll_attempts)."""
        self.client.state.register_device("INV_01", 8, "inverter", "Inverter")
        mock_mb = MagicMock()
        mock_mb.get_or_create_device.side_effect = ConnectionError("Modbus down")
        self.client.modbus = mock_mb

        poller = self.client.poller
        polled = poller.poll_tier(PollingTier.FAST)
        self.assertEqual(polled, 0)
        self.assertEqual(poller.last_poll[PollingTier.FAST.value], 0.0)
        self.assertEqual(poller.poll_counts[PollingTier.FAST.value], 0)
        self.assertGreater(poller.last_poll_attempt[PollingTier.FAST.value], 0.0)
        self.assertEqual(poller.poll_attempts[PollingTier.FAST.value], 1)

    def test_poller_start_stop_exits_promptly_during_initial_stagger(self):
        """poller.stop() called immediately after poller.start() must interrupt the initial stagger and exit in < 0.5s."""
        import time

        poller = TieredModbusPoller(client=self.client, enabled=True)
        poller.start()
        try:
            time.sleep(0.05)
            t0 = time.monotonic()
            poller.stop()
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.5, f"poller.stop() took {elapsed:.2f}s due to non-stoppable initial stagger")
            self.assertFalse(poller._running)
        finally:
            poller.stop()

    @staticmethod
    def _make_mock_model(points_dict):
        m = MagicMock()
        pts = {}
        for name, (raw_val, comp_val) in points_dict.items():
            p = MagicMock()
            p.value = raw_val
            p.cvalue = comp_val
            p.sf_required = False
            pts[name] = p
        m.points = pts
        return m

    def test_modbus_exception_2_triggers_single_rescan_and_respects_cooldown(self):
        """Modbus exception 2 (Illegal Data Address) must trigger a rescan+retry and honor rescan_cooldown."""
        dev = self.client.state.register_device("000100082128", 9, "battery", "Battery")
        self.client.state.set_supported_models("000100082128", [802, 64252])

        now = [1000.0]
        poller = TieredModbusPoller(
            client=self.client,
            enabled=False,
            rescan_cooldown=60.0,
            clock=lambda: now[0],
        )

        m802 = self._make_mock_model({"SoC": (80, 80.0)})
        m64252_new = self._make_mock_model({"MaxCellV": (3450, 3.45)})

        tcp_dev_old = MagicMock()
        tcp_dev_old.models = {802: [m802], 64252: [self._make_mock_model({"MaxCellV": (0, 0.0)})]}
        tcp_dev_new = MagicMock()
        tcp_dev_new.models = {802: [m802], 64252: [m64252_new]}

        current_dev = [tcp_dev_old]
        mock_mb = MagicMock()
        mock_mb.get_or_create_device.side_effect = lambda sid: current_dev[0]

        def _do_rescan(sid, full_model_read=False):
            current_dev[0] = tcp_dev_new
            return tcp_dev_new

        mock_mb.rescan_device.side_effect = _do_rescan
        mock_mb.read_model_block.side_effect = [
            RuntimeError("Modbus exception 2: addr: 40316 count: 114"),
            m64252_new,
        ]
        self.client.modbus = mock_mb

        # 1. First Modbus exception 2 triggers rescan + retry and succeeds
        ok = poller.poll_device_model(9, "000100082128", 64252)
        self.assertTrue(ok)
        mock_mb.rescan_device.assert_called_once_with(9, full_model_read=False)
        self.assertEqual(sorted(dev.supported_models), [802, 64252])

        # 2. Another Modbus exception 2 within cooldown must NOT rescan again
        now[0] = 1015.0
        mock_mb.read_model_block.side_effect = RuntimeError("Modbus exception 2: addr: 40316 count: 114")
        ok2 = poller.poll_device_model(9, "000100082128", 64252)
        self.assertFalse(ok2)
        self.assertEqual(mock_mb.rescan_device.call_count, 1)

        # 3. Advancing past rescan_cooldown allows another rescan+retry
        now[0] = 1070.0
        mock_mb.read_model_block.side_effect = [
            RuntimeError("Modbus exception 2: addr: 40316 count: 114"),
            m64252_new,
        ]
        ok3 = poller.poll_device_model(9, "000100082128", 64252)
        self.assertTrue(ok3)
        self.assertEqual(mock_mb.rescan_device.call_count, 2)

    def test_rescan_serial_mismatch_triggers_full_client_rescan(self):
        """If Model 1 serial changes after a slave rescan, _maybe_rescan_device triggers full client rescan."""
        self.client.state.register_device("000100082128", 9, "battery", "Battery")
        poller = TieredModbusPoller(client=self.client, enabled=False)

        m1 = MagicMock()
        sn_pt = MagicMock()
        sn_pt.value = "DIFFERENT_SN"
        m1.SN = sn_pt

        rescanned = MagicMock()
        rescanned.models = {1: [m1], 802: [MagicMock()]}
        rescanned.common = [m1]

        mock_mb = MagicMock()
        mock_mb.rescan_device.return_value = rescanned
        mock_mb.read_model_block.return_value = m1
        self.client.modbus = mock_mb
        self.client.rescan_devices = MagicMock()

        ok = poller._maybe_rescan_device(9, "000100082128", reason="test serial mismatch")
        self.assertFalse(ok)
        self.client.rescan_devices.assert_called_once_with()

    def test_repeated_device_failures_mark_offline_and_recovery_restores_and_rescans(self):
        """Repeated per-device Modbus failures mark the device offline; recovery restores online and rescans."""
        inv = self.client.state.register_device("0001000714E9", 8, "inverter", "Inverter")
        pv = self.client.state.register_device("0001000361F4", 7, "pv_link", "PV Link")
        self.client.state.set_supported_models("0001000714E9", [102])
        self.client.state.set_supported_models("0001000361F4", [64207])

        now = [1000.0]
        poller = TieredModbusPoller(
            client=self.client,
            enabled=False,
            fast_models={"inverter": [102], "pv_link": [64207]},
            config_models={},
            slow_models={},
            offline_threshold=3,
            rescan_cooldown=60.0,
            clock=lambda: now[0],
        )

        m_inv = self._make_mock_model({"W": (2500, 2500.0)})
        m_pv = self._make_mock_model({"V": (385, 385.0)})
        tcp_inv = MagicMock()
        tcp_inv.models = {102: [m_inv]}
        tcp_pv = MagicMock()
        tcp_pv.models = {64207: [m_pv]}

        pv_should_fail = [True]
        mock_mb = MagicMock()
        mock_mb.get_or_create_device.side_effect = lambda sid: tcp_inv if sid == 8 else tcp_pv
        mock_mb.rescan_device.return_value = tcp_pv

        def _read_block(tcp_dev, mid, index=0):
            if tcp_dev is tcp_inv:
                return m_inv
            if pv_should_fail[0]:
                raise RuntimeError("Modbus exception 3: addr: 40070 count: 14")
            return m_pv

        mock_mb.read_model_block.side_effect = _read_block
        self.client.modbus = mock_mb
        self.client.bridge = MagicMock()

        # Cycles 1 & 2: PV Link still online
        for _ in range(2):
            now[0] += 12.0
            poller.poll_tier(PollingTier.FAST)
            self.assertTrue(pv.online)
            self.assertTrue(inv.online)
            self.client.bridge.check_availability.assert_not_called()

        # Cycle 3: reaches offline_threshold=3 -> PV Link marked offline, inverter stays online
        now[0] += 12.0
        poller.poll_tier(PollingTier.FAST)
        self.assertFalse(pv.online)
        self.assertEqual(pv.consecutive_errors, 3)
        self.assertIn("Modbus exception 3", pv.last_error or "")
        self.assertTrue(inv.online)
        self.assertTrue(poller.modbus_connected)
        self.client.bridge.check_availability.assert_called_once()

        # Cycle 4: PV Link recovers -> marked online again, bridge notified, recovery rescan run
        now[0] += 12.0
        pv_should_fail[0] = False
        poller.poll_tier(PollingTier.FAST)
        self.assertTrue(pv.online)
        self.assertEqual(pv.consecutive_errors, 0)
        self.assertIsNone(pv.last_error)
        self.assertEqual(self.client.bridge.check_availability.call_count, 2)
        mock_mb.rescan_device.assert_called_once_with(7, full_model_read=False)

    def test_global_modbus_failure_marks_disconnected_and_triggers_reconnect(self):
        """When all polled devices fail across offline_threshold cycles, poller flags Modbus down and resets connection."""
        inv = self.client.state.register_device("INV_01", 8, "inverter", "Inverter")
        self.client.state.set_supported_models("INV_01", [102])

        now = [1000.0]
        poller = TieredModbusPoller(
            client=self.client,
            enabled=False,
            fast_models={"inverter": [102]},
            config_models={},
            slow_models={},
            offline_threshold=3,
            reconnect_cooldown=30.0,
            clock=lambda: now[0],
        )

        m_inv = self._make_mock_model({"W": (1000, 1000.0)})
        tcp_inv = MagicMock()
        tcp_inv.models = {102: [m_inv]}
        should_fail = [True]

        mock_mb = MagicMock()
        mock_mb.get_or_create_device.return_value = tcp_inv
        mock_mb.rescan_device.return_value = tcp_inv
        mock_mb.read_model_block.side_effect = (
            lambda tcp_dev, mid, index=0: (_ for _ in ()).throw(TimeoutError("timed out"))
            if should_fail[0]
            else m_inv
        )
        self.client.modbus = mock_mb
        self.client.bridge = MagicMock()

        # Cycles 1 & 2: not yet at offline_threshold
        for _ in range(2):
            now[0] += 12.0
            poller.poll_tier(PollingTier.FAST)
            self.assertTrue(poller.modbus_connected)
            mock_mb.reset_connection.assert_not_called()

        # Cycle 3: crosses threshold -> modbus_connected=False and reset_connection(force_tunnel=True)
        now[0] += 12.0
        poller.poll_tier(PollingTier.FAST)
        self.assertFalse(poller.modbus_connected)
        self.assertFalse(inv.online)
        mock_mb.reset_connection.assert_called_once()
        self.assertTrue(mock_mb.reset_connection.call_args.kwargs.get("force_tunnel"))
        self.client.bridge.check_availability.assert_called_once()

        # Cycle 4 within reconnect_cooldown: must not reset again yet
        now[0] += 10.0
        poller.poll_tier(PollingTier.FAST)
        self.assertEqual(mock_mb.reset_connection.call_count, 1)

        # Cycle 5 past reconnect_cooldown: resets again
        now[0] += 25.0
        poller.poll_tier(PollingTier.FAST)
        self.assertEqual(mock_mb.reset_connection.call_count, 2)

        # Cycle 6: Modbus recovers -> modbus_connected returns True and bridge updated
        now[0] += 12.0
        should_fail[0] = False
        poller.poll_tier(PollingTier.FAST)
        self.assertTrue(poller.modbus_connected)
        self.assertTrue(inv.online)
        self.assertGreaterEqual(self.client.bridge.check_availability.call_count, 2)

    def test_missing_previously_supported_model_triggers_rescan_only_when_ever_supported(self):
        """A missing previously-supported model triggers a rescan, while a never-supported model does not."""
        self.client.state.register_device("000100082128", 9, "battery", "Battery")
        self.client.state.set_supported_models("000100082128", [802, 64252])

        now = [1000.0]
        poller = TieredModbusPoller(
            client=self.client,
            enabled=False,
            rescan_cooldown=60.0,
            clock=lambda: now[0],
        )

        m802 = self._make_mock_model({"SoC": (75, 75.0)})
        m64252 = self._make_mock_model({"MaxCellV": (3400, 3.4)})

        tcp_dev_old = MagicMock()
        tcp_dev_old.models = {802: [m802]}  # 64252 temporarily missing from cached map
        tcp_dev_new = MagicMock()
        tcp_dev_new.models = {802: [m802], 64252: [m64252]}

        current_dev = [tcp_dev_old]
        mock_mb = MagicMock()
        mock_mb.get_or_create_device.side_effect = lambda sid: current_dev[0]

        def _do_rescan(sid, full_model_read=False):
            current_dev[0] = tcp_dev_new
            return tcp_dev_new

        mock_mb.rescan_device.side_effect = _do_rescan
        mock_mb.read_model_block.return_value = m64252
        self.client.modbus = mock_mb

        # 1. Never-supported model 64299 must NOT trigger a rescan
        ok_never = poller.poll_device_model(9, "000100082128", 64299)
        self.assertFalse(ok_never)
        mock_mb.rescan_device.assert_not_called()

        # 2. Previously-supported model 64252 MUST trigger rescan and succeed on retry
        ok_prev = poller.poll_device_model(9, "000100082128", 64252)
        self.assertTrue(ok_prev)
        mock_mb.rescan_device.assert_called_once_with(9, full_model_read=False)


if __name__ == "__main__":
    unittest.main()
