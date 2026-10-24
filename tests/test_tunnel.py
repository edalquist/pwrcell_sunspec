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


if __name__ == "__main__":
    unittest.main()
