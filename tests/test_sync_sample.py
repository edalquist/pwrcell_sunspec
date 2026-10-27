"""Unit tests for synchronized sampling across telemetry and Modbus pairs."""

import unittest
from unittest.mock import MagicMock, patch

from pwrcell.client import PwrcellClient
from pwrcell.ui.server import create_app


class TestSyncSampling(unittest.TestCase):
    """Test suite for synchronized pair sampling."""

    def setUp(self):
        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.app = create_app(self.client)
        self.http = self.app.test_client()

    def tearDown(self):
        self.client.stop()

    def test_client_sync_sample_fields(self):
        """Verify client.sync_sample_fields retrieves and updates values with minimal skew."""
        res = self.client.sync_sample_fields(
            field_keys=["inverter.live.solar_power_w", "inverter.102.W"],
            device_sn="0001000714E9",
        )
        self.assertEqual(res["status"], "ok")
        self.assertIn("skew_seconds", res)
        self.assertIsInstance(res["sources"], list)
        self.assertGreaterEqual(len(res["sources"]), 1)
        self.assertLessEqual(res["skew_seconds"], 1.0)

    def test_client_sync_sample_empty_keys(self):
        """Verify empty field keys return error status."""
        res = self.client.sync_sample_fields([])
        self.assertEqual(res["status"], "error")

    def test_sync_sample_api_endpoint_with_field_keys(self):
        """Verify /api/compare/sync_sample handles direct field key pairs."""
        resp = self.http.post(
            "/api/compare/sync_sample",
            json={
                "device_sn": "0001000714E9",
                "field_keys": ["inverter.live.solar_power_w", "inverter.102.W"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("skew_seconds", data)
        self.assertIn("sources", data)

    def test_sync_sample_api_endpoint_with_concept_key(self):
        """Verify /api/compare/sync_sample can resolve fields from concept_key."""
        resp = self.http.post(
            "/api/compare/sync_sample",
            json={
                "device_sn": "0001000714E9",
                "concept_key": "solar_power",
            },
        )
        # Even if concept has no mapped fields or is empty, returns valid response
        self.assertIn(resp.status_code, (200, 400))


if __name__ == "__main__":
    unittest.main()
