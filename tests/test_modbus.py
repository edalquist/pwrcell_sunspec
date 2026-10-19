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
        def failing_task():
            raise ValueError("Permanent failure")

        fut = self.worker.submit(failing_task, retries=2, backoff_sec=0.01)
        with self.assertRaises(ValueError):
            fut.result(timeout=2.0)

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

        discovered = mgr.scan_range(start_id=1, end_id=10, stop_on_duplicate_serial=True)

        # None, "None", and "" must NOT trigger duplicate stop.
        # Slave 4 is discovered.
        # Slave 5 has duplicate "PWR-1001", which triggers stop.
        # Discovered should contain slaves 1, 2, 3, 4.
        self.assertIn(1, discovered)
        self.assertIn(2, discovered)
        self.assertIn(3, discovered)
        self.assertIn(4, discovered)
        self.assertNotIn(5, discovered)
        self.assertEqual(len(discovered), 4)


if __name__ == "__main__":
    unittest.main()
