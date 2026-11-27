"""Unit tests for pwrcell.tunnel PwrCellTunnel and pwrcell_tunnel context manager."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pwrcell.config import AppConfig, PwrcellConfig, SshTunnel
from pwrcell.tunnel import PwrCellTunnel, pwrcell_tunnel


class TestPwrCellTunnel(unittest.TestCase):

    def setUp(self):
        # Use a throwaway identity file so tests don't depend on the host's ~/.ssh/id_rsa.
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        identity = Path(tmp_dir.name) / "id_test"
        identity.write_text("not-a-real-key")
        self.config = AppConfig(
            pwrcell=PwrcellConfig(
                ssh_tunnel=SshTunnel(
                    host="192.168.0.73",
                    port=22,
                    username="root",
                    identity_file=str(identity),
                )
            )
        )

    def test_tunnel_start_and_get_config_no_deadlock(self):
        tunnel = PwrCellTunnel(self.config)
        mock_server = MagicMock()
        mock_server.is_active = True
        tunnel._create_and_start_server = MagicMock(return_value=(mock_server, "127.0.0.1", 5020, 18830))

        # Test start() does not hang / deadlock
        cfg = tunnel.start()
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.modbus_port, 5020)
        self.assertEqual(cfg.mqtt_port, 18830)

        # Test calling start() when already running
        cfg2 = tunnel.start()
        self.assertEqual(cfg2.modbus_port, 5020)

        # Test calling get_config()
        cfg3 = tunnel.get_config()
        self.assertEqual(cfg3.mqtt_port, 18830)

        self.assertTrue(tunnel.is_active)
        tunnel.stop()
        self.assertFalse(tunnel.is_active)

    def test_pwrcell_tunnel_context_manager(self):
        mock_server = MagicMock()
        mock_server.is_active = True

        with patch("pwrcell.tunnel.PwrCellTunnel._create_and_start_server", return_value=(mock_server, "127.0.0.1", 5020, 18830)):
            with pwrcell_tunnel(self.config) as cfg:
                self.assertEqual(cfg.host, "127.0.0.1")
                self.assertEqual(cfg.modbus_port, 5020)
    def test_mqtt_client_stop_no_deadlock(self):
        from pwrcell.mqtt import MqttClient
        from pwrcell.tunnel import TunnelConfig

        cfg = TunnelConfig(host="127.0.0.1", mqtt_port=1883, modbus_port=502)
        client = MqttClient(cfg)
        mock_mqttc = MagicMock()
        # Simulate paho-mqtt invoking on_disconnect synchronously inside disconnect()
        def mock_disconnect():
            if mock_mqttc.on_disconnect:
                mock_mqttc.on_disconnect(mock_mqttc, None, None, 0, None)
        mock_mqttc.disconnect.side_effect = mock_disconnect

        with patch("paho.mqtt.client.Client", return_value=mock_mqttc):
            client.start()
            # Calling stop() must complete cleanly without deadlocking
            client.stop()

    def test_tunnel_reconnect_fallback_to_ephemeral_ports(self):
        """Verify that if previous ports cannot be rebound, tunnel falls back to ephemeral ports."""
        tunnel = PwrCellTunnel(self.config)
        tunnel._running = True

        mock_server = MagicMock()
        mock_server.is_active = True
        mock_server.is_alive = True
        mock_server.local_bind_hosts = ["127.0.0.1", "127.0.0.1"]
        mock_server.local_bind_ports = [55502, 55188]

        # Simulate old ports in use
        tunnel.modbus_port = 53679
        tunnel.mqtt_port = 53680

        with patch("pwrcell.tunnel.SSHTunnelForwarder") as mock_forwarder_cls:
            call_count = [0]

            def forwarder_side_effect(*args, **kwargs):
                call_count[0] += 1
                srv = MagicMock()
                # Fail first call (attempt to bind specific ports 53679, 53680)
                if call_count[0] == 1:
                    srv.start.side_effect = Exception("Couldn't open tunnel 127.0.0.1:53679 might be in use")
                    srv.is_alive = False
                else:
                    # Second call with ephemeral ports succeeds
                    srv.is_alive = True
                    srv.local_bind_hosts = ["127.0.0.1", "127.0.0.1"]
                    srv.local_bind_ports = [55502, 55188]
                return srv

            mock_forwarder_cls.side_effect = forwarder_side_effect

            res = tunnel.ensure_active()
            self.assertTrue(res)
            self.assertEqual(tunnel.modbus_port, 55502)
            self.assertEqual(tunnel.mqtt_port, 55188)
            # Verify the failed server was stopped to avoid thread leaks
            self.assertGreaterEqual(call_count[0], 2)

    def test_modbus_client_rebinds_devices_on_port_change(self):
        """Verify that registered devices are rebound when modbus port changes."""
        from pwrcell.modbus import SerializedModbusClient
        from pwrcell.tunnel import TunnelConfig

        cfg = TunnelConfig(host="127.0.0.1", mqtt_port=1883, modbus_port=5020)
        client = SerializedModbusClient(host="127.0.0.1", port=5020, tunnel=cfg)

        dev1 = client.get_or_create_device(1)
        old_shared = dev1.client

        # Simulate tunnel reconnecting to a new port
        cfg.modbus_port = 5021
        new_shared = client._get_shared_client()

        self.assertNotEqual(old_shared, new_shared)
        self.assertEqual(dev1.client, new_shared)
        self.assertEqual(client.port, 5021)
        client.close()

    def test_setup_ssh_key_creates_file_with_0600_mode(self):
        """SSH private key must be opened with 0600 permissions before key bytes are written."""
        import json
        import os
        import stat
        from pwrcell.setup_key import setup_ssh_key_from_options

        with tempfile.TemporaryDirectory() as tmp:
            opts_path = Path(tmp) / "options.json"
            target_path = Path(tmp) / "ssh" / "id_rsa_pwrcell"
            opts_path.write_text(
                json.dumps({"ssh_key": "-----BEGIN OPENSSH PRIVATE KEY-----\\nAAAA\\n-----END OPENSSH PRIVATE KEY-----"}),
                encoding="utf-8",
            )
            orig_os_open = os.open
            opened_modes = []

            def tracking_os_open(path, flags, mode=0o777, *args, **kwargs):
                if str(path) == str(target_path):
                    opened_modes.append(mode)
                return orig_os_open(path, flags, mode, *args, **kwargs)

            with patch("pwrcell.setup_key.os.open", side_effect=tracking_os_open):
                saved = setup_ssh_key_from_options(str(opts_path), str(target_path))

            self.assertEqual(saved, str(target_path))
            self.assertEqual(opened_modes, [0o600])
            self.assertEqual(stat.S_IMODE(target_path.stat().st_mode), 0o600)

    def test_mqtt_disconnect_reconnects_only_on_port_change_and_subscribes_narrowly(self):
        """MqttClient must subscribe only to energy_recordset_live topics (not '#'), and on disconnect only call connect_async when the tunnel port changed."""
        import time
        from pwrcell.mqtt import MqttClient
        from pwrcell.tunnel import TunnelConfig

        mock_manager = MagicMock()
        current_port = [18830]
        mock_manager.ensure_active.return_value = True
        mock_manager.get_config.side_effect = lambda: TunnelConfig(
            host="127.0.0.1", mqtt_port=current_port[0], modbus_port=5020, manager=mock_manager
        )

        cfg = mock_manager.get_config()
        mock_mqttc = MagicMock()
        with patch("pwrcell.mqtt.mqtt.Client", return_value=mock_mqttc):
            client = MqttClient(cfg)
            client.start()
            try:
                # 1. Verify on_connect subscribes narrowly to energy_recordset_live, not '#'
                mock_mqttc.on_connect(mock_mqttc, None, None, 0, None)
                mock_mqttc.subscribe.assert_called_once_with(
                    [("+/energy_recordset_live", 0), ("/energy_recordset_live", 0)]
                )

                # 2. Disconnect when tunnel port is unchanged (18830) -> let paho auto-reconnect without competing connect_async
                mock_mqttc.connect_async.reset_mock()
                mock_mqttc.disconnect.reset_mock()
                mock_mqttc.on_disconnect(mock_mqttc, None, None, 1, None)
                time.sleep(0.1)
                mock_manager.ensure_active.assert_called_once()
                mock_mqttc.connect_async.assert_not_called()

                # 3. Disconnect when tunnel rebuilt on a new port (55188) -> re-point client via connect_async
                current_port[0] = 55188
                mock_mqttc.on_disconnect(mock_mqttc, None, None, 1, None)
                time.sleep(0.1)
                mock_mqttc.connect_async.assert_called_once_with("127.0.0.1", 55188)
            finally:
                client.stop()

    def test_generate_config_from_options_handles_special_chars_and_sets_0600(self):
        """generate_config_from_options must safely serialize passwords with quotes, '$', '#', and newlines via yaml.safe_dump with 0600 permissions."""
        import json
        import os
        import stat
        import yaml
        from pwrcell.setup_key import generate_config_from_options

        with tempfile.TemporaryDirectory() as tmp:
            opts_path = Path(tmp) / "options.json"
            cfg_path = Path(tmp) / "pwrcell.yaml"
            tricky_beacon_pass = 'p"a$s#word\nmalicious_key: true\n\\end'
            tricky_mqtt_pass = 'm"q$t#t\ninjected: 123'
            tricky_passphrase = 'k"e$y#\npassphrase'
            opts = {
                "beacon_host": "192.168.0.73",
                "beacon_port": 22,
                "beacon_user": "root",
                "beacon_password": tricky_beacon_pass,
                "ssh_key_passphrase": tricky_passphrase,
                "mqtt_host": "core-mosquitto",
                "mqtt_port": 1883,
                "mqtt_username": "ha_user",
                "mqtt_password": tricky_mqtt_pass,
                "mqtt_client_name": "pwrcell-ha",
                "poll_rate": 15,
                "config_poll_interval": 60,
                "slow_poll_interval": 300,
                "log_level": "DEBUG",
            }
            opts_path.write_text(json.dumps(opts), encoding="utf-8")

            generate_config_from_options(
                str(opts_path),
                str(cfg_path),
                target_key_path=str(Path(tmp) / "id_rsa_pwrcell"),
            )

            self.assertTrue(cfg_path.exists())
            self.assertEqual(stat.S_IMODE(cfg_path.stat().st_mode), 0o600)

            with open(cfg_path, "r", encoding="utf-8") as f:
                raw_yaml = yaml.safe_load(f)
            self.assertNotIn("malicious_key", raw_yaml)
            self.assertNotIn("injected", raw_yaml)
            self.assertEqual(raw_yaml["pwrcell"]["ssh_tunnel"]["password"], tricky_beacon_pass)
            self.assertEqual(raw_yaml["pwrcell"]["ssh_tunnel"]["key_passphrase"], tricky_passphrase)
            self.assertEqual(raw_yaml["mqtt"]["password"], tricky_mqtt_pass)

            # Also verify AppConfig.read() loads the generated file intact
            old_env = os.environ.get("PWRCELL_CONFIG")
            os.environ["PWRCELL_CONFIG"] = str(cfg_path)
            try:
                loaded_cfg = AppConfig.read()
                self.assertEqual(loaded_cfg.pwrcell.ssh_tunnel.password, tricky_beacon_pass)
                self.assertEqual(loaded_cfg.pwrcell.ssh_tunnel.key_passphrase, tricky_passphrase)
                self.assertEqual(loaded_cfg.mqtt.password, tricky_mqtt_pass)
                self.assertEqual(loaded_cfg.poll_rate, 15)
                self.assertEqual(loaded_cfg.blocked_fields, [])
                self.assertEqual(loaded_cfg.unblocked_fields, [])
            finally:
                if old_env is None:
                    os.environ.pop("PWRCELL_CONFIG", None)
                else:
                    os.environ["PWRCELL_CONFIG"] = old_env

    def test_generate_config_from_options_roundtrips_safety_overrides(self):
        """generate_config_from_options must persist blocked_fields and unblocked_fields for AppConfig.read()."""
        import json
        import os
        import yaml
        from pwrcell.setup_key import generate_config_from_options

        with tempfile.TemporaryDirectory() as tmp:
            opts_path = Path(tmp) / "options.json"
            cfg_path = Path(tmp) / "pwrcell.yaml"
            opts = {
                "beacon_host": "192.168.0.73",
                "blocked_fields": ["  inverter.EIconfig.Conn ", "", "battery.*.SoCMax"],
                "unblocked_fields": ["inverter.EIconfig.ZExp", None, "  inverter.EIconfig.ZExpLim "],
            }
            opts_path.write_text(json.dumps(opts), encoding="utf-8")

            generate_config_from_options(
                str(opts_path),
                str(cfg_path),
                target_key_path=str(Path(tmp) / "id_rsa_pwrcell"),
            )

            with open(cfg_path, "r", encoding="utf-8") as f:
                raw_yaml = yaml.safe_load(f)
            self.assertEqual(raw_yaml["blocked_fields"], ["inverter.EIconfig.Conn", "battery.*.SoCMax"])
            self.assertEqual(raw_yaml["unblocked_fields"], ["inverter.EIconfig.ZExp", "inverter.EIconfig.ZExpLim"])

            old_env = os.environ.get("PWRCELL_CONFIG")
            os.environ["PWRCELL_CONFIG"] = str(cfg_path)
            try:
                loaded_cfg = AppConfig.read()
                self.assertEqual(loaded_cfg.blocked_fields, ["inverter.EIconfig.Conn", "battery.*.SoCMax"])
                self.assertEqual(loaded_cfg.unblocked_fields, ["inverter.EIconfig.ZExp", "inverter.EIconfig.ZExpLim"])
            finally:
                if old_env is None:
                    os.environ.pop("PWRCELL_CONFIG", None)
                else:
                    os.environ["PWRCELL_CONFIG"] = old_env

    def test_force_reconnect_tears_down_active_tunnel_invokes_callbacks_and_respects_cooldown(self):
        """force_reconnect() rebuilds an active tunnel, notifies callbacks outside locks, and respects cooldown."""
        tunnel = PwrCellTunnel(self.config)
        old_server = MagicMock()
        old_server.is_active = True
        old_server.is_alive = True

        new_server = MagicMock()
        new_server.is_active = True
        new_server.is_alive = True

        tunnel._running = True
        tunnel._server = old_server
        tunnel.modbus_port = 5020
        tunnel.mqtt_port = 18830

        callback_configs = []
        tunnel.register_reconnect_callback(lambda cfg: callback_configs.append(cfg))

        with patch.object(
            tunnel,
            "_create_and_start_server",
            return_value=(new_server, "127.0.0.1", 5021, 18831),
        ) as mock_create, patch("pwrcell.tunnel.time.monotonic", side_effect=[100.0, 105.0]):
            res1 = tunnel.force_reconnect(reason="stalled stream", min_interval_sec=15.0)
            self.assertTrue(res1)
            old_server.stop.assert_called_once_with(force=True)
            mock_create.assert_called_once()
            self.assertEqual(tunnel.modbus_port, 5021)
            self.assertEqual(tunnel.mqtt_port, 18831)
            self.assertEqual(len(callback_configs), 1)
            self.assertEqual(callback_configs[0].mqtt_port, 18831)
            self.assertEqual(tunnel.get_status()["reconnect_count"], 1)

            # Second call within 15s cooldown (105.0 - 100.0 = 5.0 < 15.0) must be skipped
            res2 = tunnel.force_reconnect(reason="too soon", min_interval_sec=15.0)
            self.assertTrue(res2)
            self.assertEqual(mock_create.call_count, 1)
            self.assertEqual(len(callback_configs), 1)

    def test_mqtt_client_tunnel_reconnected_callback_and_health_watchdog(self):
        """MqttClient detects port drift, prolonged disconnect escalation, and silent zombie streams."""
        from pwrcell.mqtt import MqttClient
        from pwrcell.tunnel import TunnelConfig

        fake_now = [1000.0]
        current_port = [18830]
        mock_manager = MagicMock()
        mock_manager.ensure_active.return_value = True
        mock_manager.force_reconnect.return_value = True
        mock_manager.get_config.side_effect = lambda: TunnelConfig(
            host="127.0.0.1", mqtt_port=current_port[0], modbus_port=5020, manager=mock_manager
        )

        mock_mqttc = MagicMock()
        with patch("pwrcell.mqtt.mqtt.Client", return_value=mock_mqttc):
            client = MqttClient(mock_manager.get_config(), clock=lambda: fake_now[0])
            client.start()
            try:
                # 1. _on_tunnel_reconnected re-points Paho to new port
                client._on_tunnel_reconnected(TunnelConfig(host="127.0.0.1", mqtt_port=18831))
                mock_mqttc.connect_async.assert_called_with("127.0.0.1", 18831)
                self.assertEqual(client.get_status()["reconnect_count"], 1)

                # 2. Simulate healthy connection + message at t=1000, then silence > stale_timeout (120s)
                current_port[0] = 18831
                mock_mqttc.on_connect(mock_mqttc, None, None, 0, None)
                self.assertTrue(client.is_connected)
                self.assertTrue(client.is_healthy(stale_timeout=120.0))

                fake_now[0] = 1130.0  # 130s silent > 120s
                self.assertFalse(client.is_healthy(stale_timeout=120.0))
                mock_manager.force_reconnect.reset_mock()
                triggered = client.check_health_and_reconnect(stale_timeout=120.0, reconnect_cooldown=30.0)
                self.assertTrue(triggered)
                mock_manager.force_reconnect.assert_called_once()

                # 3. Prolonged disconnect: 1st failure calls ensure_active, 2nd escalates to force_reconnect
                import time as _time
                mock_mqttc.on_disconnect(mock_mqttc, None, None, 1, None)
                _time.sleep(0.05)  # allow MqttTunnelReconnect thread to finish before resetting mocks
                mock_manager.ensure_active.reset_mock()
                mock_manager.force_reconnect.reset_mock()
                fake_now[0] = 1200.0
                self.assertTrue(client.check_health_and_reconnect(stale_timeout=120.0, reconnect_cooldown=30.0))
                mock_manager.ensure_active.assert_called_once()
                mock_manager.force_reconnect.assert_not_called()

                fake_now[0] = 1235.0
                self.assertTrue(client.check_health_and_reconnect(stale_timeout=120.0, reconnect_cooldown=30.0))
                mock_manager.force_reconnect.assert_called_once()

                # 4. Port drift while connected triggers reconnect
                mock_mqttc.on_connect(mock_mqttc, None, None, 0, None)
                current_port[0] = 18899
                fake_now[0] = 1270.0
                mock_mqttc.connect_async.reset_mock()
                self.assertTrue(client.check_health_and_reconnect(stale_timeout=120.0, reconnect_cooldown=30.0))
                mock_mqttc.connect_async.assert_called_with("127.0.0.1", 18899)
            finally:
                client.stop()


if __name__ == "__main__":
    unittest.main()
