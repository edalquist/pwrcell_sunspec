import time
import unittest
from unittest.mock import MagicMock, patch

from pwrcell.client import PwrcellClient
from pwrcell.mqtt import MqttClient
from pwrcell.tunnel import TunnelConfig


class TestClientLifecycle(unittest.TestCase):
    def test_mock_client_stops_promptly(self):
        """The mock simulator thread must wake immediately on stop, not after its 1.5s tick."""
        client = PwrcellClient(is_mock=True)
        client.start()
        time.sleep(0.2)  # let the sim thread enter its wait
        started = time.monotonic()
        client.stop()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertFalse(client._sim_thread.is_alive())

    def test_mqtt_initial_connect_failure_does_not_abort_live_start(self):
        """If the internal MQTT broker is not ready at startup, MqttClient.start() must not abort PwrcellClient.start()."""
        cfg = TunnelConfig(host="127.0.0.1", mqtt_port=18830, modbus_port=5020)
        mock_mqttc = MagicMock()
        mock_mqttc.connect.side_effect = ConnectionRefusedError("broker not ready")

        with patch("pwrcell.mqtt.mqtt.Client", return_value=mock_mqttc), \
             patch("pwrcell.models.load_models_dir", side_effect=RuntimeError("skip scp")), \
             patch("pwrcell.modbus.configure_sunspec_model_paths"), \
             patch.object(PwrcellClient, "load_or_discover_devices"), \
             patch.object(PwrcellClient, "_poll_device_models_live"):
            mqtt_client = MqttClient(cfg)
            client = PwrcellClient(mqtt_client=mqtt_client, is_mock=False)
            client.start()
            try:
                self.assertTrue(client.poller._running)
                mock_mqttc.loop_start.assert_called_once()
                mock_mqttc.connect.assert_called_once_with("127.0.0.1", 18830)
                mock_mqttc.connect_async.assert_called_once_with("127.0.0.1", 18830)
            finally:
                client.stop()


if __name__ == "__main__":
    unittest.main()
