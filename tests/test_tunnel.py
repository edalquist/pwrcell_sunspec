"""Unit tests for pwrcell.tunnel PwrCellTunnel and pwrcell_tunnel context manager."""

import unittest
from unittest.mock import MagicMock, patch
from pwrcell.config import AppConfig, PwrcellConfig, SshTunnel
from pwrcell.tunnel import PwrCellTunnel, pwrcell_tunnel


class TestPwrCellTunnel(unittest.TestCase):

    def setUp(self):
        self.config = AppConfig(
            pwrcell=PwrcellConfig(
                ssh_tunnel=SshTunnel(
                    host="192.168.0.73",
                    port=22,
                    username="root",
                    identity_file="~/.ssh/id_rsa",
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


if __name__ == "__main__":
    unittest.main()
