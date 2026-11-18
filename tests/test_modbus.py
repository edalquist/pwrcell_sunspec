"""Unit tests for pwrcell.modbus SerializedModbusWorker."""

import time
import unittest
from pwrcell.modbus import SerializedModbusWorker


class TestSerializedModbusWorker(unittest.TestCase):

    def setUp(self):
        self.worker = SerializedModbusWorker()
        self.worker.start()

    def tearDown(self):
        self.worker.stop()

    def test_serialized_execution_order(self):
        execution_order = []

        def task(n):
            def _run():
                time.sleep(0.01)
                execution_order.append(n)
                return n
            return _run

        f1 = self.worker.submit(task(1), description="task 1")
        f2 = self.worker.submit(task(2), description="task 2")
        f3 = self.worker.submit(task(3), description="task 3")

        self.assertEqual(f1.result(timeout=2.0), 1)
        self.assertEqual(f2.result(timeout=2.0), 2)
        self.assertEqual(f3.result(timeout=2.0), 3)

        self.assertEqual(execution_order, [1, 2, 3])

    def test_retry_on_transient_error(self):
        attempts = 0

        def flaky_task():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError(f"Simulated transient error attempt {attempts}")
            return "recovered"

        fut = self.worker.submit(flaky_task, retries=3, backoff_sec=0.01)
        res = fut.result(timeout=2.0)
        self.assertEqual(res, "recovered")
        self.assertEqual(attempts, 3)

    def test_failure_propagates_exception(self):
        attempts = 0

        def failing_task():
            nonlocal attempts
            attempts += 1
            raise ValueError("Permanent failure")

        fut = self.worker.submit(failing_task, retries=3, backoff_sec=0.01)
        with self.assertRaises(ValueError):
            fut.result(timeout=2.0)
        # Deterministic errors (ValueError) must NOT be retried
        self.assertEqual(attempts, 1)

    def test_worker_retries_under_one(self):
        attempts = 0
        def task():
            nonlocal attempts
            attempts += 1
            raise RuntimeError("Failed")

        fut = self.worker.submit(task, retries=0, backoff_sec=0.01)
        with self.assertRaises(RuntimeError):
            fut.result(timeout=2.0)
        self.assertEqual(attempts, 1)

    def test_worker_drain_on_stop(self):
        # Start a slow task to occupy the worker
        blocker_started = False
        def blocker():
            nonlocal blocker_started
            blocker_started = True
            time.sleep(0.15)
            return "done"

        f_busy = self.worker.submit(blocker)
        # Wait until blocker has started running
        for _ in range(50):
            if blocker_started:
                break
            time.sleep(0.005)

        # Queue tasks that will not be executed before stop
        f_queued1 = self.worker.submit(lambda: 42)
        f_queued2 = self.worker.submit(lambda: 99)

        self.worker.stop()

        with self.assertRaises(RuntimeError):
            f_queued1.result(timeout=1.0)
        with self.assertRaises(RuntimeError):
            f_queued2.result(timeout=1.0)


class TestModbusScanRange(unittest.TestCase):

    def test_scan_range_handles_none_and_empty_serials(self):
        from unittest.mock import MagicMock
        from pwrcell.modbus import SerializedModbusClient

        mgr = SerializedModbusClient(host="localhost", port=5020)
        mgr.read_model_block = MagicMock()

        # Define 5 mock devices:
        # Slave 1: SN=None
        # Slave 2: SN="None"
        # Slave 3: SN=""
        # Slave 4: SN="PWR-1001"
        # Slave 5: SN="PWR-1001" (Duplicate serial of slave 4)
        serials = {
            1: None,
            2: "None",
            3: "",
            4: "PWR-1001",
            5: "PWR-1001",
        }

        def mock_scan_device(slave_id, full_model_read=False):
            if slave_id not in serials:
                return None
            mock_dev = MagicMock()
            mock_dev.models = {1: MagicMock()}
            common_block = MagicMock()
            common_block.SN.value = serials[slave_id]
            common_block.Md.value = f"Model_{slave_id}"
            mock_dev.common = [common_block]
            return mock_dev

        mgr.scan_device = MagicMock(side_effect=mock_scan_device)

        with self.assertLogs("pwrcell.modbus", level="WARNING") as cm:
            discovered = mgr.scan_range(start_id=1, end_id=10, stop_on_duplicate_serial=True)

        # None, "None", and "" must NOT trigger duplicate stop.
        # Slave 4 is discovered.
        # Slave 5 has duplicate "PWR-1001", which triggers warning and stop when stop_on_duplicate_serial=True.
        # Discovered should contain slaves 1, 2, 3, 4.
        self.assertIn(1, discovered)
        self.assertIn(2, discovered)
        self.assertIn(3, discovered)
        self.assertIn(4, discovered)
        self.assertNotIn(5, discovered)
        self.assertEqual(len(discovered), 4)
        self.assertTrue(any("duplicate serial" in line.lower() for line in cm.output))

    def test_scan_range_skips_duplicate_and_discovers_subsequent_devices(self):
        from unittest.mock import MagicMock
        from pwrcell.modbus import SerializedModbusClient

        mgr = SerializedModbusClient(host="localhost", port=5020)
        mgr.read_model_block = MagicMock()

        # Reproduce GitHub Issue #14:
        # Slaves 1..6: original install
        # Slave 7: duplicate serial of slave 1 (Beacon mirror/alias)
        # Slaves 8..9: newly added PV Links
        serials = {
            1: "SN-BEACON",
            2: "SN-ICM",
            3: "SN-PV3",
            4: "SN-PV4",
            5: "SN-INV5",
            6: "SN-BAT6",
            7: "SN-BEACON",  # Duplicate alias at 7
            8: "SN-PV8",     # Added PV link at 8
            9: "SN-PV9",     # Added PV link at 9
        }

        def mock_scan_device(slave_id, full_model_read=False):
            if slave_id not in serials:
                return None
            mock_dev = MagicMock()
            mock_dev.models = {1: MagicMock()}
            common_block = MagicMock()
            common_block.SN.value = serials[slave_id]
            common_block.Md.value = f"Model_{slave_id}"
            mock_dev.common = [common_block]
            return mock_dev

        mgr.scan_device = MagicMock(side_effect=mock_scan_device)

        with self.assertLogs("pwrcell.modbus", level="WARNING") as cm:
            discovered = mgr.scan_range(start_id=1, end_id=10)

        # Slave 7 should be skipped because it is an alias of Slave 1.
        # Slaves 8 and 9 must be discovered.
        self.assertIn(1, discovered)
        self.assertIn(2, discovered)
        self.assertIn(3, discovered)
        self.assertIn(4, discovered)
        self.assertIn(5, discovered)
        self.assertIn(6, discovered)
        self.assertNotIn(7, discovered)
        self.assertIn(8, discovered)
        self.assertIn(9, discovered)
        self.assertEqual(len(discovered), 8)
        self.assertTrue(any("skipping duplicate" in line.lower() for line in cm.output))

    def test_scan_range_stops_on_max_consecutive_duplicates(self):
        from unittest.mock import MagicMock
        from pwrcell.modbus import SerializedModbusClient

        mgr = SerializedModbusClient(host="localhost", port=5020)
        mgr.read_model_block = MagicMock()

        serials = {
            1: "SN-BASE",
            2: "SN-BASE",
            3: "SN-BASE",
            4: "SN-BASE",
            5: "SN-BASE",
            6: "SN-DISTANT",
        }

        def mock_scan_device(slave_id, full_model_read=False):
            if slave_id not in serials:
                return None
            mock_dev = MagicMock()
            mock_dev.models = {1: MagicMock()}
            common_block = MagicMock()
            common_block.SN.value = serials[slave_id]
            common_block.Md.value = f"Model_{slave_id}"
            mock_dev.common = [common_block]
            return mock_dev

        mgr.scan_device = MagicMock(side_effect=mock_scan_device)

        discovered = mgr.scan_range(start_id=1, end_id=10, max_consecutive_duplicates=3)
        # Should stop after slave 4 (3 consecutive duplicates of SN-BASE: slaves 2, 3, 4)
        self.assertEqual(list(discovered.keys()), [1])

    def test_write_point_value_warns_on_readback_mismatch(self):
        from unittest.mock import MagicMock
        from pwrcell.modbus import SerializedModbusClient

        mgr = SerializedModbusClient(host="localhost", port=5020)
        mgr.worker.start()
        try:
            mgr._ensure_device_connected = MagicMock()
            mock_point = MagicMock()
            mock_model = MagicMock()
            mock_model.points = {"SoCMax": mock_point}

            # When model.read() is called, simulate device clamping cvalue to 80.0 instead of 95.0
            def on_read():
                mock_point.cvalue = 80.0

            mock_model.read.side_effect = on_read
            mock_dev = MagicMock()
            mock_dev.slave_id = 9
            mock_dev.models = {802: [mock_model]}

            with self.assertLogs("pwrcell.modbus", level="WARNING") as cm:
                readback = mgr.write_point_value(mock_dev, 802, "SoCMax", 95.0)
            self.assertEqual(readback, 80.0)
            self.assertTrue(any("mismatch" in line.lower() for line in cm.output))
        finally:
            mgr.close()

    def test_scan_range_breaks_on_max_consecutive_misses(self):
        from unittest.mock import MagicMock
        from pwrcell.modbus import SerializedModbusClient

        mgr = SerializedModbusClient(host="localhost", port=5020)
        scanned_ids = []

        def mock_scan_device(slave_id, full_model_read=False):
            scanned_ids.append(slave_id)
            return None

        mgr.scan_device = MagicMock(side_effect=mock_scan_device)
        discovered = mgr.scan_range(start_id=1, end_id=100, max_consecutive_misses=5)
        self.assertEqual(discovered, {})
        self.assertEqual(scanned_ids, [1, 2, 3, 4, 5])

    def test_drain_stale_socket_bytes_reconnects_on_eof(self):
        from unittest.mock import MagicMock
        from pwrcell.modbus import SerializedModbusClient

        mgr = SerializedModbusClient(host="localhost", port=5020)
        fake_sock = MagicMock()
        # recv returning b"" means peer closed the connection (EOF)
        fake_sock.recv.return_value = b""

        fake_client = MagicMock()
        fake_client.ipport = 5020
        fake_client.socket = fake_sock
        fake_client.is_connected.return_value = True
        mgr._shared_client = fake_client

        dev = MagicMock()
        dev.slave_id = 8
        mgr._ensure_device_connected(dev)

        fake_client.disconnect.assert_called_once()
        fake_client.connect.assert_called_once()

    def test_modbus_exception_classification(self):
        from pwrcell.modbus import (
            is_address_exception,
            is_device_unavailable_exception,
            parse_modbus_exception_code,
        )

        ex2 = RuntimeError("Modbus exception 2: addr: 40316 count: 114")
        self.assertEqual(parse_modbus_exception_code(ex2), 2)
        self.assertTrue(is_address_exception(ex2))
        self.assertFalse(is_device_unavailable_exception(ex2))

        for code in (3, 4, 10, 11):
            ex = RuntimeError(f"Modbus exception {code}: addr: 40070 count: 14")
            self.assertEqual(parse_modbus_exception_code(ex), code)
            self.assertFalse(is_address_exception(ex))
            self.assertTrue(is_device_unavailable_exception(ex))

        class AttrExc(Exception):
            exception_code = 2

        self.assertTrue(is_address_exception(AttrExc("opaque")))
        self.assertIsNone(parse_modbus_exception_code(TimeoutError("timed out")))

    def test_invalidate_rescan_and_reset_connection(self):
        from unittest.mock import MagicMock, patch
        from pwrcell.modbus import SerializedModbusClient

        mock_tunnel = MagicMock()
        mock_tunnel.get_config.return_value = MagicMock(modbus_port=5020)
        mock_tunnel.force_reconnect.return_value = True
        mgr = SerializedModbusClient(host="localhost", port=5020, tunnel=mock_tunnel)

        # Populate cached device and fake shared client
        dev9 = mgr.get_or_create_device(9)
        old_shared = MagicMock()
        old_shared.ipport = 5020
        old_shared.is_connected.return_value = True
        mgr._shared_client = old_shared
        self.assertIn(9, mgr._devices)

        # invalidate_device removes device without dropping shared socket
        mgr.invalidate_device(9)
        self.assertNotIn(9, mgr._devices)
        old_shared.disconnect.assert_not_called()

        # rescan_device invalidates and triggers scan_device
        mgr.get_or_create_device(9)
        with patch.object(mgr, "scan_device", return_value=dev9) as mock_scan:
            res = mgr.rescan_device(9)
            self.assertIs(res, dev9)
            self.assertNotIn(9, mgr._devices)
            mock_scan.assert_called_once_with(9, full_model_read=False)

        # reset_connection(force_tunnel=True) invokes tunnel.force_reconnect and resets socket on next _ensure_device_connected
        mock_tunnel.get_config.return_value = MagicMock(modbus_port=5025)
        self.assertTrue(mgr.reset_connection(force_tunnel=True, reason="lost comms"))
        mock_tunnel.force_reconnect.assert_called_once_with(reason="lost comms")
        self.assertTrue(mgr._socket_reset_needed)

        with patch("pwrcell.modbus.mb.ModbusClientTCP") as mock_tcp_cls:
            new_shared = MagicMock()
            new_shared.ipport = 5025
            new_shared.is_connected.return_value = False
            mock_tcp_cls.return_value = new_shared
            mgr._ensure_device_connected(dev9)

        old_shared.disconnect.assert_called_once()
        mock_tcp_cls.assert_called_once_with(slave_id=1, ipaddr="localhost", ipport=5025, timeout=5)
        new_shared.connect.assert_called_once()
        self.assertEqual(mgr.port, 5025)
        mgr.close()


if __name__ == "__main__":
    unittest.main()
