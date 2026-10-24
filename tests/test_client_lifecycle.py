import time
import unittest

from pwrcell.client import PwrcellClient


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


if __name__ == "__main__":
    unittest.main()
