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
             patch("pwrcell.model_sync.load_models_dir", side_effect=RuntimeError("skip scp")), \
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
        from pwrcell.model_sync import load_models_dir

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
            with patch("pwrcell.model_sync.SSHClient", return_value=mock_ssh), \
                 patch("pwrcell.model_sync.SCPClient", return_value=mock_scp):
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
            with patch("pwrcell.model_sync.SSHClient", return_value=mock_ssh), \
                 patch("pwrcell.model_sync.SCPClient", return_value=mock_scp):
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

    def test_no_locks_held_across_blocking_stop_operations(self):
        """Stopping SerializedModbusClient while a worker job acquires client._lock must not deadlock, and PwrCellTunnel.stop() wakes backoff sleeps immediately."""
        import threading
        from pwrcell.config import AppConfig, PwrcellConfig, SshTunnel
        from pwrcell.modbus import SerializedModbusClient
        from pwrcell.tunnel import PwrCellTunnel

        # 1. SerializedModbusClient.close() must not hold self._lock while waiting on worker.execute_sync,
        # otherwise a running worker job that acquires self._lock (e.g. _reset_shared_client) deadlocks!
        mb_client = SerializedModbusClient(host="127.0.0.1", port=5020)
        mb_client._shared_client = MagicMock()
        mb_client.worker.start()

        job_entered = threading.Event()
        allow_job_proceed = threading.Event()

        def blocking_job():
            job_entered.set()
            allow_job_proceed.wait(timeout=2.0)
            # Worker thread acquires mb_client._lock during normal error/reset handling
            with mb_client._lock:
                return "ok"

        mb_client.worker.submit(blocking_job, retries=1)
        self.assertTrue(job_entered.wait(timeout=1.0))

        close_done = threading.Event()

        def run_close():
            mb_client.close()
            close_done.set()

        t = threading.Thread(target=run_close, daemon=True)
        t.start()
        time.sleep(0.05)
        allow_job_proceed.set()
        self.assertTrue(close_done.wait(timeout=1.5), "mb_client.close() deadlocked with worker acquiring mb_client._lock")

        # 2. PwrCellTunnel.stop() must interrupt retry backoff wait in ensure_active() immediately
        cfg = AppConfig(pwrcell=PwrcellConfig(ssh_tunnel=SshTunnel(host="127.0.0.1", port=22, username="root")))
        tunnel = PwrCellTunnel(cfg)
        tunnel._running = True
        with patch.object(tunnel, "_create_and_start_server", side_effect=RuntimeError("conn refused")):
            ensure_done = threading.Event()

            def run_ensure():
                tunnel.ensure_active()
                ensure_done.set()

            et = threading.Thread(target=run_ensure, daemon=True)
            et.start()
            time.sleep(0.1)
            t0 = time.monotonic()
            tunnel.stop()
            self.assertTrue(ensure_done.wait(timeout=0.5), "ensure_active() did not wake promptly on tunnel.stop()")
            self.assertLess(time.monotonic() - t0, 0.5)

    def test_startup_shutdown_ordering_and_no_worker_resurrection(self):
        """After close(), SerializedModbusWorker.submit() must not resurrect the worker thread; PwrcellClient.stop() stops self.bridge; _poll_device_models_live reuses already-scanned devices."""
        from types import SimpleNamespace
        from pwrcell.modbus import SerializedModbusClient

        # 1. Submitting a job after close() must fail without restarting the worker thread
        mb_client = SerializedModbusClient(host="127.0.0.1", port=5020)
        mb_client.worker.start()
        self.assertTrue(mb_client.worker._running)
        mb_client.close()
        self.assertFalse(mb_client.worker._running)

        with self.assertRaises(RuntimeError):
            mb_client.worker.execute_sync(lambda: "should not run", retries=1, timeout=1.0)
        self.assertFalse(mb_client.worker._running)

        # 2. PwrcellClient.stop() stops attached self.bridge
        client = PwrcellClient(is_mock=True)
        mock_bridge = MagicMock()
        client.bridge = mock_bridge
        client.start()
        client.stop()
        mock_bridge.stop.assert_called_once()

        # 3. _poll_device_models_live reuses existing tcp_dev.models from get_or_create_device instead of re-scanning
        live_client = PwrcellClient(is_mock=False)
        live_client._running = True
        live_client.state.register_device("0001000714E9", 8, "inverter", "Inverter")
        fake_tcp_dev = SimpleNamespace(
            models={1: [object()], 102: [object()]},
            common=[SimpleNamespace(Md=SimpleNamespace(value="X7602"), Vr=SimpleNamespace(value="1.2"))],
        )
        mock_modbus = MagicMock()
        mock_modbus.get_or_create_device.return_value = fake_tcp_dev
        mock_modbus.read_model_block.return_value = SimpleNamespace(points={})
        live_client.modbus = mock_modbus
        with patch.object(live_client.poller, "poll_device_model"):
            live_client._poll_device_models_live()
        mock_modbus.scan_device.assert_not_called()

    def test_discovery_cache_revalidation_on_serial_mismatch_and_rescan(self):
        """If Model 1 on a cached slave ID reports a different serial number than cached in devices.yaml, rescan_devices() replaces stale devices."""
        from types import SimpleNamespace
        from pwrcell.config import DeviceConfig

        live_client = PwrcellClient(is_mock=False)
        live_client._running = True
        # Cached stale device on slave 8
        live_client.state.register_device("OLD_SERIAL_999", 8, "inverter", "Inverter")

        # Live hardware on slave 8 actually has NEW_SERIAL_123
        live_tcp_dev = SimpleNamespace(
            models={1: [object()], 102: [object()]},
            common=[
                SimpleNamespace(
                    SN=SimpleNamespace(value="NEW_SERIAL_123"),
                    Md=SimpleNamespace(value="PWRcell X7602"),
                    Vr=SimpleNamespace(value="1.5"),
                )
            ],
        )
        mock_modbus = MagicMock()
        mock_modbus.get_or_create_device.return_value = live_tcp_dev
        mock_modbus.read_model_block.return_value = SimpleNamespace(points={})
        mock_modbus.scan_range.return_value = {8: live_tcp_dev}
        live_client.modbus = mock_modbus

        with patch.object(DeviceConfig, "write") as mock_write, \
             patch.object(live_client.poller, "poll_device_model"):
            live_client._poll_device_models_live()
            mock_modbus.scan_range.assert_called_once()
            mock_write.assert_called_once()

        self.assertNotIn("OLD_SERIAL_999", live_client.state.devices)
        self.assertIn("NEW_SERIAL_123", live_client.state.devices)
        self.assertEqual(live_client.state.devices["NEW_SERIAL_123"].device_type, "inverter")

    def test_data_dir_persists_all_runtime_files_under_data_dir_override(self):
        """With PWRCELL_DATA_DIR set, devices.yaml, ha_config.yaml, .ha_published_topics.json, telemetry_mappings.yaml, custom_groupings.yaml, and sunspec_cache_dir all resolve under data_dir()."""
        import os
        import tempfile
        from pathlib import Path
        from pwrcell.bridge import get_default_published_topics_path
        from pwrcell.config import AppConfig, DeviceConfig, data_dir
        from pwrcell.grouping import get_default_grouping_config_path, save_custom_groupings
        from pwrcell.ha import get_default_ha_config_path, save_ha_config
        from pwrcell.mapping import _resolve_mappings_path, get_default_mappings, save_mappings
        from pwrcell.model_sync import load_models_dir

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.dict(os.environ, {"PWRCELL_DATA_DIR": str(tmp_path)}):
                self.assertEqual(data_dir(), tmp_path)
                self.assertEqual(get_default_ha_config_path(), tmp_path / "ha_config.yaml")
                self.assertEqual(get_default_published_topics_path(), tmp_path / ".ha_published_topics.json")
                self.assertEqual(get_default_grouping_config_path(), tmp_path / "custom_groupings.yaml")
                self.assertEqual(_resolve_mappings_path(), tmp_path / "groupings.yaml")

                # 1. DeviceConfig.write() writes to tmp_path / devices.yaml even when it did not exist beforehand
                dev_cfg = DeviceConfig(inverter={"0001000714E9": 8})
                dev_cfg.write()
                self.assertTrue((tmp_path / "devices.yaml").exists())
                loaded_dev = DeviceConfig.read()
                self.assertIsNotNone(loaded_dev)
                self.assertEqual(loaded_dev.inverter.get("0001000714E9"), 8)

                # 2. save_ha_config writes to tmp_path / ha_config.yaml
                save_ha_config(["0001000714E9:inverter.live.grid_power_w"])
                self.assertTrue((tmp_path / "ha_config.yaml").exists())

                # 3. save_custom_groupings writes to tmp_path / custom_groupings.yaml
                save_custom_groupings({"field_overrides": {"0001000714E9:inverter.inverter.W": "inverter_output_power"}})
                self.assertTrue((tmp_path / "custom_groupings.yaml").exists())

                # 4. save_mappings writes to tmp_path / groupings.yaml (not package pwrcell/data/)
                save_mappings(get_default_mappings())
                self.assertTrue((tmp_path / "groupings.yaml").exists())

                # 5. load_models_dir without explicit sunspec_cache_dir uses data_dir() / sunspec-models
                models_dir = load_models_dir(AppConfig(pwrcell=None))
                self.assertEqual(models_dir, tmp_path / "sunspec-models")


if __name__ == "__main__":
    unittest.main()
