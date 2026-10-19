"""Unit tests for pwrcell.ha and pwrcell.ui Web Explorer API."""

import json
import unittest
from pwrcell.client import PwrcellClient
from pwrcell.ha import generate_discovery_payload, get_recommended_field_keys
from pwrcell.ui.server import create_app


class TestWebExplorerApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = PwrcellClient(is_mock=True)
        cls.client.start()
        cls.app = create_app(cls.client)
        cls.test_client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_index_route(self):
        resp = self.test_client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"PWRcell Explorer", resp.data)
        self.assertIn(b"data-sort=\"model\"", resp.data)
        self.assertIn(b"data-sort=\"value\"", resp.data)
        self.assertIn(b"data-sort=\"ha\"", resp.data)
        self.assertIn(b"multiSortToggle", resp.data)
        self.assertIn(b"sortBar", resp.data)
        resp.close()

    def test_overview_endpoint(self):
        resp = self.test_client.get("/api/overview")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["is_mock"])
        self.assertEqual(data["device_count"], 9)
        self.assertIn("grid_power_w", data)
        self.assertIn("solar_power_w", data)
        self.assertIn("system_mode", data)

    def test_devices_endpoint(self):
        resp = self.test_client.get("/api/devices")
        self.assertEqual(resp.status_code, 200)
        devices = resp.get_json()
        self.assertEqual(len(devices), 9)
        serials = [d["serial_number"] for d in devices]
        self.assertIn("0001000714E9", serials)  # Inverter
        self.assertIn("000100082128", serials)  # Battery

    def test_device_details_endpoint(self):
        resp = self.test_client.get("/api/devices/0001000714E9")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["device_type"], "inverter")
        self.assertIn("fields", data)
        self.assertGreater(len(data["fields"]), 50)

    def test_ha_recommended_and_config(self):
        resp = self.test_client.get("/api/ha/recommended")
        self.assertEqual(resp.status_code, 200)
        rec = resp.get_json().get("recommended_fields", [])
        self.assertGreater(len(rec), 3)

        # Save config
        save_resp = self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": rec},
        )
        self.assertEqual(save_resp.status_code, 200)

        # Read back config
        read_resp = self.test_client.get("/api/ha/config")
        self.assertEqual(read_resp.status_code, 200)
        saved = read_resp.get_json().get("selected_fields", [])
        self.assertEqual(set(saved), set(rec))

    def test_ha_preview_endpoint(self):
        self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": ["inverter.live.solar_power_w"]},
        )
        resp = self.test_client.get("/api/ha/preview")
        self.assertEqual(resp.status_code, 200)
        preview = resp.get_json()
        self.assertIsInstance(preview, list)
        self.assertGreater(len(preview), 0)

        item = preview[0]
        self.assertIn("config_topic", item)
        self.assertIn("state_topic", item)
        self.assertIn("payload", item)
        self.assertIn("unique_id", item["payload"])

    def test_write_field_endpoint(self):
        resp = self.test_client.post(
            "/api/fields/write",
            json={"field_key": "inverter.live.system_mode", "value": "GRID_TIE"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_device_details_enum_metadata(self):
        resp = self.test_client.get("/api/devices/0001001206E8")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        fields = data.get("fields", {})
        self.assertIn("rebus_beacon.REbus_dir.SysMd", fields)
        sysmd = fields["rebus_beacon.REbus_dir.SysMd"]
        self.assertTrue(sysmd["is_enum"])
        self.assertEqual(sysmd["point_type"], "enum16")
        self.assertIsInstance(sysmd["symbols"], list)
        self.assertGreater(len(sysmd["symbols"]), 0)
        names = [s["name"] for s in sysmd["symbols"]]
        self.assertIn("PRIORITY_BACKUP", names)
        self.assertIn("SELF_SUPPLY", names)
        # Value must be enum symbol string, not raw numeric integer
        self.assertIsInstance(sysmd["value"], str)
        self.assertIn(sysmd["value"], names)
        self.assertIsInstance(sysmd["raw_value"], int)

    def test_write_field_enum_and_restrictions(self):
        # 1. Valid enum symbol string
        resp1 = self.test_client.post(
            "/api/fields/write",
            json={"field_key": "rebus_beacon.REbus_dir.SysMd", "value": "PRIORITY_BACKUP"},
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertTrue(resp1.get_json()["success"])
        self.assertEqual(resp1.get_json()["value"], "PRIORITY_BACKUP")

        # 2. Valid enum integer
        resp2 = self.test_client.post(
            "/api/fields/write",
            json={"field_key": "rebus_beacon.REbus_dir.SysMd", "value": 2},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.get_json()["success"])
        self.assertEqual(resp2.get_json()["value"], "SELF_SUPPLY")

        # 3. Invalid enum string rejected with 400
        resp3 = self.test_client.post(
            "/api/fields/write",
            json={"field_key": "rebus_beacon.REbus_dir.SysMd", "value": "INVALID_MODE_VALUE"},
        )
        self.assertEqual(resp3.status_code, 400)
        self.assertIn("Invalid operating mode", resp3.get_json()["error"])

        # 4. Invalid enum int rejected with 400
        resp4 = self.test_client.post(
            "/api/fields/write",
            json={"field_key": "rebus_beacon.REbus_dir.SysMd", "value": 999},
        )
        self.assertEqual(resp4.status_code, 400)
        self.assertIn("Invalid operating mode integer 999", resp4.get_json()["error"])

        # 5. Read-only field rejected with 400
        resp5 = self.test_client.post(
            "/api/fields/write",
            json={"field_key": "rebus_beacon.common.SN", "value": "12345"},
        )
        self.assertEqual(resp5.status_code, 400)
        self.assertIn("read-only", resp5.get_json()["error"])

    def test_compare_endpoint(self):
        resp = self.test_client.get("/api/compare")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("comparisons", data)
        self.assertIn("unrecognized_proto_fields", data)
        self.assertIsInstance(data["comparisons"], list)
        self.assertIsInstance(data["unrecognized_proto_fields"], list)
        self.assertGreater(len(data["comparisons"]), 0)

    def test_poller_endpoints(self):
        # 1. GET /api/poller/status
        resp = self.test_client.get("/api/poller/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("intervals", data)
        self.assertIn("fast_seconds", data["intervals"])
        self.assertIn("config_seconds", data["intervals"])
        self.assertIn("slow_seconds", data["intervals"])
        self.assertIn("poll_counts", data)
        self.assertIn("models", data)

        # 2. POST /api/poller/trigger
        resp_trigger = self.test_client.post(
            "/api/poller/trigger",
            json={"tier": "config"},
        )
        self.assertEqual(resp_trigger.status_code, 200)
        trig_data = resp_trigger.get_json()
        self.assertTrue(trig_data["success"])
        self.assertEqual(trig_data["tier"], "config")

    def test_device_models_metadata(self):
        """Test that devices preserve and expose all supported SunSpec models and field links."""
        # 1. Check /api/devices includes supported_models and models summary
        resp = self.test_client.get("/api/devices")
        self.assertEqual(resp.status_code, 200)
        devices = resp.get_json()
        inv = next(d for d in devices if d["serial_number"] == "0001000714E9")
        self.assertIn("supported_models", inv)
        self.assertIn("models", inv)
        self.assertEqual(len(inv["supported_models"]), 24)
        self.assertEqual(inv["model_count"], 24)

        # 2. Check /api/devices/<serial_number> detailed response
        resp_detail = self.test_client.get("/api/devices/0001000714E9")
        self.assertEqual(resp_detail.status_code, 200)
        detail = resp_detail.get_json()
        self.assertEqual(len(detail["supported_models"]), 24)
        self.assertEqual(len(detail["models"]), 24)

        # Verify a specific model definition in the models summary
        m120 = next(m for m in detail["models"] if m["model_id"] == 120)
        self.assertEqual(m120["name"], "nameplate")
        self.assertEqual(m120["label"], "Nameplate")
        self.assertGreater(m120["field_count"], 0)

        # Verify fields link to their model_id, model_name, and model_label
        fields = detail["fields"]
        self.assertIn("inverter.nameplate.WRtg", fields)
        f_wrtg = fields["inverter.nameplate.WRtg"]
        self.assertEqual(f_wrtg["model_id"], 120)
        self.assertEqual(f_wrtg["model_name"], "nameplate")
        self.assertEqual(f_wrtg["model_label"], "Nameplate")

    def test_poll_all_device_models_endpoint(self):
        resp = self.test_client.post("/api/devices/0001000714E9/poll_all")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_sse_stream_cleanup(self):
        # Initial sse_queues should be empty
        self.assertEqual(len(self.app.sse_queues), 0)

        resp = self.test_client.get("/api/stream")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.app.sse_queues), 1)

        # Read initial connected event
        initial_chunk = next(resp.response)
        self.assertIn(b"connected", initial_chunk)

        # Close the response / generator
        resp.close()

        # The finally block in event_generator must have executed and cleaned up the queue
        self.assertEqual(len(self.app.sse_queues), 0)

    def test_ha_discovery_options_for_enum_and_select(self):
        # 1. Preview for enum select field (rebus_beacon.REbus_dir.SysMd)
        self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": ["rebus_beacon.REbus_dir.SysMd"]},
        )
        resp = self.test_client.get("/api/ha/preview")
        self.assertEqual(resp.status_code, 200)
        preview = resp.get_json()
        self.assertEqual(len(preview), 1)
        item = preview[0]
        self.assertEqual(item["platform"], "select")
        self.assertIn("options", item["payload"])
        self.assertIn("CLEAN_BACKUP", item["payload"]["options"])
        self.assertIn("SELF_SUPPLY", item["payload"]["options"])

        # 2. Compound enum sensor field: system_mode
        inv = self.client.state.get_inverter()
        c_view = self.client.state.get_compound_view("system_mode")
        self.assertIsNotNone(c_view)
        c_payload_info = generate_discovery_payload(c_view, inv)
        self.assertEqual(c_payload_info["platform"], "sensor")
        self.assertEqual(c_payload_info["payload"]["device_class"], "enum")
        self.assertIn("options", c_payload_info["payload"])
        self.assertIn("CLEAN_BACKUP", c_payload_info["payload"]["options"])
        self.assertIn("PRIORITY_BACKUP", c_payload_info["payload"]["options"])


if __name__ == "__main__":
    unittest.main()
