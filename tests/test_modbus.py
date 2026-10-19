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


if __name__ == "__main__":
    unittest.main()
