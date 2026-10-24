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

    def test_config_read_missing_and_malformed(self):
        """AppConfig.read returns defaults when missing, fails loudly when malformed; DeviceConfig.read is Optional."""
        import os
        import tempfile
        from pathlib import Path
        from typing import get_type_hints
        from pwrcell.config import AppConfig, DeviceConfig

        # 1. Verify DeviceConfig.read return annotation includes None
        hints = get_type_hints(DeviceConfig.read)
        self.assertIn(type(None), getattr(hints.get("return"), "__args__", ()))

        with tempfile.TemporaryDirectory() as tmp:
            missing_cfg = Path(tmp) / "nonexistent_pwrcell.yaml"
            with patch.dict(os.environ, {"PWRCELL_CONFIG": str(missing_cfg)}):
                cfg = AppConfig.read()
                self.assertIsInstance(cfg, AppConfig)

            bad_cfg = Path(tmp) / "malformed_pwrcell.yaml"
            bad_cfg.write_text("poll_rate: [not_an_int\n", encoding="utf-8")
            with patch.dict(os.environ, {"PWRCELL_CONFIG": str(bad_cfg)}):
                with self.assertRaises(Exception):
                    AppConfig.read()

    def test_version_consistency(self):
        """Package __version__, HA ORIGIN_INFO['sw_version'], and add-on config.yaml version must match."""
        from pathlib import Path
        import yaml
        import pwrcell
        from pwrcell.ha import ORIGIN_INFO

        self.assertEqual(ORIGIN_INFO["sw_version"], pwrcell.__version__)
        addon_cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(addon_cfg.get("version"), pwrcell.__version__)


if __name__ == "__main__":
    unittest.main()
