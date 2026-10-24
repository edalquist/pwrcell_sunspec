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


if __name__ == "__main__":
    unittest.main()
