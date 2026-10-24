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

    def test_load_models_dir_tofu_host_keys_and_atomic_download(self):
        """load_models_dir must use RejectPolicy once known_hosts exists, clean up version.chk, and download via a staging directory."""
        import tempfile
        from pathlib import Path
        from paramiko import AutoAddPolicy, RejectPolicy
        from pwrcell.config import AppConfig, PwrcellConfig, SshTunnel
        from pwrcell.models import load_models_dir

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            cfg = AppConfig(
                sunspec_cache_dir=str(cache_dir),
                pwrcell=PwrcellConfig(ssh_tunnel=SshTunnel(host="127.0.0.1", port=22, username="root")),
            )

            mock_ssh = MagicMock()
            mock_ssh.__enter__.return_value = mock_ssh
            mock_scp = MagicMock()
            mock_scp.__enter__.return_value = mock_scp

            def fake_scp_get(remote_path, local_path, recursive=False, preserve_times=False):
                lp = Path(local_path)
                if remote_path == "/opt/pika/sunspec-models/version":
                    lp.write_text("v2.0\n", encoding="utf-8")
                elif remote_path == "/opt/pika/sunspec-models":
                    dl_dir = lp / "sunspec-models"
                    dl_dir.mkdir(parents=True, exist_ok=True)
                    (dl_dir / "version").write_text("v2.0\n", encoding="utf-8")
                    (dl_dir / "model_1.json").write_text("{}", encoding="utf-8")

            mock_scp.get.side_effect = fake_scp_get

            # 1. First run: known_hosts does not exist -> AutoAddPolicy used, then saved to known_hosts
            with patch("pwrcell.models.SSHClient", return_value=mock_ssh), \
                 patch("pwrcell.models.SCPClient", return_value=mock_scp):
                res_dir = load_models_dir(cfg)
                self.assertEqual(res_dir, cache_dir / "sunspec-models")
                self.assertTrue((res_dir / "version").exists())
                self.assertEqual((res_dir / "version").read_text(encoding="utf-8"), "v2.0\n")
                self.assertFalse((res_dir / "version.chk").exists())
                policy_arg = mock_ssh.set_missing_host_key_policy.call_args[0][0]
                self.assertIsInstance(policy_arg, AutoAddPolicy)
                mock_ssh.save_host_keys.assert_called_once()

            # Create non-empty known_hosts to simulate subsequent run
            known_hosts_file = cache_dir / "known_hosts"
            known_hosts_file.write_text("127.0.0.1 ssh-rsa AAAAB3Nza...\n", encoding="utf-8")
            mock_ssh.reset_mock()

            # 2. Second run with existing known_hosts -> RejectPolicy used (pinned host key) and up-to-date check cleans version.chk
            with patch("pwrcell.models.SSHClient", return_value=mock_ssh), \
                 patch("pwrcell.models.SCPClient", return_value=mock_scp):
                res_dir2 = load_models_dir(cfg)
                self.assertEqual(res_dir2, cache_dir / "sunspec-models")
                self.assertFalse((res_dir2 / "version.chk").exists())
                policy_arg2 = mock_ssh.set_missing_host_key_policy.call_args[0][0]
                self.assertIsInstance(policy_arg2, RejectPolicy)

    def test_save_scanned_devices_classifies_by_models_and_skips_empty_persist(self):
        """_save_scanned_devices must classify devices by exposed SunSpec model IDs (not fragile Md substring matching) and refuse to write an empty scan."""
        from types import SimpleNamespace
        from pwrcell.config import DeviceConfig

        client = PwrcellClient(is_mock=False)

        with patch.object(DeviceConfig, "write") as mock_write:
            # 1. Empty scan must not persist devices.yaml
            client._save_scanned_devices({})
            mock_write.assert_not_called()

            # 2. Classify by SunSpec model IDs even when Md string is non-standard or contains "PV"
            def _make_dev(sn: str, md: str, models: list[int]):
                common_inst = SimpleNamespace(
                    SN=SimpleNamespace(value=sn),
                    Md=SimpleNamespace(value=md),
                )
                return SimpleNamespace(
                    common=[common_inst],
                    models={mid: [object()] for mid in models},
                )

            discovered = {
                1: _make_dev("0001000714E9", "REbus Gateway", [1, 64200, 64260]),
                8: _make_dev("00010007901A", "Generac PV Hybrid X7602", [1, 102, 64208]),
                9: _make_dev("000100083F22", "Generac Storage Pack", [1, 802, 64252]),
                10: _make_dev("00010009ABCD", "S2502 Combiner", [1, 404, 64251]),
            }
            client._save_scanned_devices(discovered)
            mock_write.assert_called_once()

            self.assertEqual(client.state.devices["0001000714E9"].device_type, "rebus_beacon")
            self.assertEqual(client.state.devices["00010007901A"].device_type, "inverter")
            self.assertEqual(client.state.devices["000100083F22"].device_type, "battery")
            self.assertEqual(client.state.devices["00010009ABCD"].device_type, "pv_link")


if __name__ == "__main__":
    unittest.main()
