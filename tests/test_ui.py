"""Unit tests for pwrcell.ha and pwrcell.ui Web Explorer API."""

import json
import unittest
from pwrcell.client import PwrcellClient
from pwrcell.ha import generate_discovery_payload, get_recommended_field_keys, load_ha_config, save_ha_config
from pwrcell.ui.server import create_app


class TestWebExplorerApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.orig_ha_config = load_ha_config()
        cls.client = PwrcellClient(is_mock=True)
        cls.client.start()
        cls.app = create_app(cls.client)
        cls.test_client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()
        if hasattr(cls, "orig_ha_config"):
            save_ha_config(cls.orig_ha_config)

    def test_index_route(self):
        resp = self.test_client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"PWRcell Explorer", resp.data)
        self.assertIn(b"data-sort=\"model\"", resp.data)
        self.assertIn(b"data-sort=\"value\"", resp.data)
        self.assertIn(b"data-sort=\"ha\"", resp.data)
        self.assertIn(b"multiSortToggle", resp.data)
        self.assertIn(b"hideCombinedRaw", resp.data)
        self.assertIn(b"btnApplySameType", resp.data)
        self.assertIn(b"sortBar", resp.data)
        self.assertIn(b"groupingModal", resp.data)
        self.assertIn(b"radioGroupExisting", resp.data)
        self.assertIn(b"radioGroupUngroup", resp.data)
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
        self.assertIn("initial_poll_running", data)

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
        self.assertIn("stats", data)
        self.assertIn("unrecognized_proto_fields", data)
        self.assertIsInstance(data["comparisons"], list)
        self.assertIsInstance(data["unrecognized_proto_fields"], list)
        self.assertGreater(len(data["comparisons"]), 0)

        # Check stats summary
        self.assertIn("total_groups", data["stats"])
        self.assertIn("discrepancies_count", data["stats"])
        self.assertIn("multi_source_groups", data["stats"])

        # Check multi-source comparison row structure
        multi_rows = [r for r in data["comparisons"] if len(r.get("sources", [])) > 1]
        self.assertGreater(len(multi_rows), 0)
        sample = multi_rows[0]
        self.assertIn("status_label", sample)
        self.assertIn("is_discrepant", sample)
        self.assertIn("source_count", sample)
        self.assertIsInstance(sample["sources"], list)

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
        self.assertIn("initial_poll_running", data)

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

        # 2. Compound writable select entity: system_mode
        inv = self.client.state.get_inverter()
        c_view = self.client.state.get_compound_view("system_mode")
        self.assertIsNotNone(c_view)
        c_payload_info = generate_discovery_payload(c_view, inv)
        self.assertEqual(c_payload_info["platform"], "select")
        self.assertIn("command_topic", c_payload_info["payload"])
        self.assertIn("options", c_payload_info["payload"])
        self.assertIn("CLEAN_BACKUP", c_payload_info["payload"]["options"])
        self.assertIn("PRIORITY_BACKUP", c_payload_info["payload"]["options"])

    def test_multi_device_ha_config_isolation(self):
        """Verify that device-scoped selections prevent multiple devices of the same type from overwriting each other."""
        sn1 = "000100034AC7"
        sn2 = "000100034E68"

        # Select DCW for PV Link 1, and REbus_status.P for PV Link 2
        selected = [
            f"{sn1}:pv_link.string_combiner.DCW",
            f"{sn2}:pv_link.REbus_status.P",
        ]
        save_resp = self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": selected},
        )
        self.assertEqual(save_resp.status_code, 200)

        # Check preview
        preview_resp = self.test_client.get("/api/ha/preview")
        self.assertEqual(preview_resp.status_code, 200)
        preview = preview_resp.get_json()

        # Group preview by serial
        p1_items = [p for p in preview if p.get("device_serial") == sn1]
        p2_items = [p for p in preview if p.get("device_serial") == sn2]

        self.assertEqual(len(p1_items), 1)
        self.assertEqual(p1_items[0]["field_key"], "pv_link.string_combiner.DCW")

        self.assertEqual(len(p2_items), 1)
        self.assertEqual(p2_items[0]["field_key"], "pv_link.REbus_status.P")

        # Now simulate user changing only PV Link 2's selection to DCWh
        # (Device 1's key is retained in the saved set)
        updated_selected = [
            f"{sn1}:pv_link.string_combiner.DCW",
            f"{sn2}:pv_link.string_combiner.DCWh",
        ]
        self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": updated_selected},
        )

        preview_resp2 = self.test_client.get("/api/ha/preview")
        preview2 = preview_resp2.get_json()
        p1_after = [p for p in preview2 if p.get("device_serial") == sn1]
        p2_after = [p for p in preview2 if p.get("device_serial") == sn2]

        # PV Link 1 is still preserved!
        self.assertEqual(len(p1_after), 1)
        self.assertEqual(p1_after[0]["field_key"], "pv_link.string_combiner.DCW")

        # PV Link 2 has updated to DCWh
        self.assertEqual(len(p2_after), 1)
        self.assertEqual(p2_after[0]["field_key"], "pv_link.string_combiner.DCWh")

    def test_ha_recommended_with_device_filter(self):
        """Verify that recommended fields can be filtered to a specific device serial number."""
        sn = "000100034AC7"
        resp = self.test_client.get(f"/api/ha/recommended?serial_number={sn}")
        self.assertEqual(resp.status_code, 200)
        rec = resp.get_json().get("recommended_fields", [])
        self.assertGreater(len(rec), 0)

        # All recommendations should be scoped to the requested device
        for k in rec:
            self.assertTrue(k.startswith(f"{sn}:"), f"Key '{k}' did not start with serial {sn}")

    def test_compound_raw_fields_metadata(self):
        """Verify that raw fields mapped to compound views contain compound metadata."""
        inv = self.client.state.get_inverter()
        self.assertIsNotNone(inv)
        resp = self.test_client.get(f"/api/devices/{inv.serial_number}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        # Check raw fields for compound association
        raw_fields = data.get("fields", {})
        self.assertIn("inverter.live.grid_power_w", raw_fields)
        grid_field = raw_fields["inverter.live.grid_power_w"]
        self.assertTrue(grid_field.get("is_compound_raw"))
        self.assertEqual(grid_field.get("compound_key"), "inverter.compound.grid_power")

        # Check compound view has modbus_candidates
        compound_fields = data.get("compound_fields", [])
        grid_compound = next((c for c in compound_fields if c.get("mapping_id") == "grid_power"), None)
        self.assertIsNotNone(grid_compound)
        self.assertIn("inverter.model_64208.CTPow", grid_compound.get("modbus_candidates", []))

    def test_copy_device_selections_api(self):
        """Verify copying field selections across devices of the same type."""
        # Source PV Link: 000100034AC7
        source_sn = "000100034AC7"
        inv_sn = self.client.state.get_inverter().serial_number

        initial_selected = [
            f"{inv_sn}:inverter.compound.grid_power",
            f"{source_sn}:pv_link.string_combiner.DCW",
            f"{source_sn}:pv_link.string_combiner.DCWh",
        ]

        resp = self.test_client.post(
            "/api/ha/copy_device_selections",
            json={
                "source_serial": source_sn,
                "selected_fields": initial_selected,
                "save": False,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["source_serial"], source_sn)
        self.assertEqual(data["target_device_type"], "pv_link")
        self.assertEqual(data["peer_count"], 5)
        self.assertEqual(data["copied_fields_count"], 2)

        res_fields = data["selected_fields"]
        # Inverter field should still be preserved
        self.assertIn(f"{inv_sn}:inverter.compound.grid_power", res_fields)

        # All 5 PV Links should have both fields (5 * 2 = 10 PV Link fields + 1 Inverter field = 11 total)
        pv_links = [d for d in self.client.state.devices.values() if d.device_type == "pv_link"]
        self.assertEqual(len(pv_links), 5)
        for pv in pv_links:
            sn = pv.serial_number.strip().upper()
            self.assertIn(f"{sn}:pv_link.string_combiner.DCW", res_fields)
            self.assertIn(f"{sn}:pv_link.string_combiner.DCWh", res_fields)

        self.assertEqual(len(res_fields), 11)

    def test_ha_config_device_merge(self):
        """Verify saving with device_serial and merge=True retains settings from other devices."""
        sn1 = "000100034AC7"
        sn2 = "000100034E68"

        # Initially save both devices
        self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": [
                    f"{sn1}:pv_link.string_combiner.DCW",
                    f"{sn1}:pv_link.string_combiner.DCWh",
                    f"{sn2}:pv_link.REbus_status.P",
                ],
                "merge": False,
            },
        )

        # Update sn1 only, deselecting DCWh and keeping only DCW
        resp = self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": [
                    f"{sn1}:pv_link.string_combiner.DCW",
                ],
                "device_serial": sn1,
                "merge": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        res_fields = data["selected_fields"]

        # sn1 should only have DCW (DCWh removed)
        self.assertIn(f"{sn1}:pv_link.string_combiner.DCW", res_fields)
        self.assertNotIn(f"{sn1}:pv_link.string_combiner.DCWh", res_fields)

        # sn2 should still be preserved
        self.assertIn(f"{sn2}:pv_link.REbus_status.P", res_fields)

    def test_ha_config_multi_device_serials_merge(self):
        """Verify saving with device_serials list updates targets while retaining other devices."""
        sn1 = "000100034AC7"
        sn2 = "000100034E68"
        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()

        # Initial state on disk
        self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": [
                    f"{inv_sn}:inverter.compound.grid_power",
                    f"{sn1}:pv_link.string_combiner.DCW",
                    f"{sn2}:pv_link.string_combiner.DCW",
                ],
                "merge": False,
            },
        )

        # Update both sn1 and sn2 to DCWh, leaving inverter unmentioned in targets
        resp = self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": [
                    f"{sn1}:pv_link.string_combiner.DCWh",
                    f"{sn2}:pv_link.string_combiner.DCWh",
                ],
                "device_serials": [sn1, sn2],
                "merge": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        res_fields = resp.get_json()["selected_fields"]

        # Inverter must be retained!
        self.assertIn(f"{inv_sn}:inverter.compound.grid_power", res_fields)
        # sn1 and sn2 updated
        self.assertIn(f"{sn1}:pv_link.string_combiner.DCWh", res_fields)
        self.assertNotIn(f"{sn1}:pv_link.string_combiner.DCW", res_fields)
        self.assertIn(f"{sn2}:pv_link.string_combiner.DCWh", res_fields)
        self.assertNotIn(f"{sn2}:pv_link.string_combiner.DCW", res_fields)

    def test_ha_default_config_seeding(self):
        """Verify that ha_default_config.yaml seeds default field IDs and scopes them to devices."""
        from pwrcell.ha import get_default_seed_config_path, qualify_legacy_ha_config
        seed_path = get_default_seed_config_path()
        self.assertTrue(seed_path.exists(), f"Seed file {seed_path} should exist in repository")

        # Load from seed directly
        raw_seed = load_ha_config(seed_path, allow_default_seed=False)
        self.assertGreater(len(raw_seed), 0)
        self.assertIn("inverter.live.grid_power_w", raw_seed)
        self.assertIn("battery.live.state_of_charge", raw_seed)

        # Qualify against state store
        qualified = qualify_legacy_ha_config(raw_seed, self.client.state)
        self.assertGreater(len(qualified), len(raw_seed))

        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()
        bat_sn = self.client.state.get_battery().serial_number.strip().upper()
        self.assertIn(f"{inv_sn}:inverter.live.grid_power_w", qualified)
        self.assertIn(f"{bat_sn}:battery.live.state_of_charge", qualified)

        # PV Links should be mapped to all 5 PV links
        pv_links = [d for d in self.client.state.devices.values() if d.device_type == "pv_link"]
        self.assertEqual(len(pv_links), 5)
        for pv in pv_links:
            sn = pv.serial_number.strip().upper()
            self.assertIn(f"{sn}:pv_link.REbus_status.V", qualified)
            self.assertIn(f"{sn}:pv_link.REbus_status.P", qualified)

    def test_export_default_config_api_and_helpers(self):
        """Verify unqualify_ha_config and export_default_config helper and API endpoint."""
        from unittest.mock import patch
        from pwrcell.ha import unqualify_ha_config

        sample_qualified = [
            "000100034AC7:pv_link.string_combiner.DCW",
            "000100034E68:pv_link.string_combiner.DCW",
            "0001000714E9:inverter.live.grid_power_w",
        ]
        unqualified = unqualify_ha_config(sample_qualified)
        self.assertEqual(unqualified, [
            "inverter.live.grid_power_w",
            "pv_link.string_combiner.DCW",
        ])

        # Test API endpoint with patch to prevent overwriting repository seed file
        with patch("pwrcell.ha.export_default_config", return_value=["inverter.live.grid_power_w"]) as mock_export:
            resp = self.test_client.post("/api/ha/export_defaults")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["count"], 1)
            self.assertIn("inverter.live.grid_power_w", data["default_fields"])
            mock_export.assert_called_once()

    def test_field_modbus_details_endpoint(self):
        """Verify Modbus field details API endpoint returns raw register definitions, scale factors, and associated registers."""
        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number

        # 1. Inspect register with scale factor: inverter.inverter.W
        resp = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=inverter.inverter.W")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("device", data)
        self.assertEqual(data["device"]["serial_number"], inv_sn)
        self.assertEqual(data["device"]["slave_id"], 8)
        self.assertEqual(data["field"]["name"], "W")
        self.assertEqual(data["point_def"]["type"], "int16")
        self.assertEqual(data["point_def"]["size"], 1)
        self.assertEqual(data["point_def"]["offset"], 14)

        # Scale factor register verification
        self.assertIsNotNone(data["scale_factor"])
        self.assertEqual(data["scale_factor"]["name"], "W_SF")
        self.assertEqual(data["scale_factor"]["offset"], 15)
        self.assertEqual(data["scale_factor"]["type"], "sunssf")
        self.assertIn("formula", data["scale_factor"])

        # SunSpec bounds restrictions verification
        self.assertIn("bounds", data)
        self.assertEqual(data["bounds"]["category"], "numeric")
        self.assertEqual(data["bounds"]["raw_min"], -32768)
        self.assertEqual(data["bounds"]["raw_max"], 32767)
        self.assertIn("description", data["bounds"])

        # Associated registers verification
        self.assertGreater(len(data["associated_registers"]), 0)
        assoc_names = [a["name"] for a in data["associated_registers"]]
        self.assertIn("W_SF", assoc_names)

        # 2. Inspect vector/phase register: inverter.inverter.AphA
        resp_apha = self.test_client.get(f"/api/devices/{inv_sn}/fields/inverter.inverter.AphA/modbus_details")
        self.assertEqual(resp_apha.status_code, 200)
        data_apha = resp_apha.get_json()
        self.assertEqual(data_apha["field"]["name"], "AphA")
        self.assertIsNotNone(data_apha["scale_factor"])
        self.assertEqual(data_apha["scale_factor"]["name"], "A_SF")
        assoc_apha = [a["name"] for a in data_apha["associated_registers"]]
        self.assertIn("A_SF", assoc_apha)
        self.assertIn("AphB", assoc_apha)
        self.assertIn("AphC", assoc_apha)
        self.assertIn("A", assoc_apha)

        # 3. Inspect scale factor register itself: inverter.inverter.W_SF
        resp_sf = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=inverter.inverter.W_SF")
        self.assertEqual(resp_sf.status_code, 200)
        data_sf = resp_sf.get_json()
        self.assertTrue(data_sf["field"]["is_scale_factor"])
        self.assertGreater(len(data_sf["scaled_points"]), 0)
        scaled_names = [sp["name"] for sp in data_sf["scaled_points"]]
        self.assertIn("W", scaled_names)

        # 4. Inspect enum register: rebus_beacon.REbus_dir.SysMd
        beacon = self.client.state.get_beacon()
        b_sn = beacon.serial_number
        resp_enum = self.test_client.get(f"/api/devices/{b_sn}/field_details?field_key=rebus_beacon.REbus_dir.SysMd")
        self.assertEqual(resp_enum.status_code, 200)
        data_enum = resp_enum.get_json()
        self.assertTrue(data_enum["field"]["is_enum"])
        self.assertIsNotNone(data_enum["enum_symbols"])
        self.assertGreater(len(data_enum["enum_symbols"]), 0)
        active_symbols = [s for s in data_enum["enum_symbols"] if s["is_active"]]
        self.assertEqual(len(active_symbols), 1)

        # Verify enum bounds
        self.assertIn("bounds", data_enum)
        self.assertEqual(data_enum["bounds"]["category"], "enum")
        self.assertEqual(data_enum["bounds"]["point_type"], "enum16")
        self.assertIn("CLEAN_BACKUP", data_enum["bounds"]["valid_names"])
        self.assertIn(3, data_enum["bounds"]["valid_values"])

        # 5. Inspect compound field: inverter.compound.grid_power
        resp_comp = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=inverter.compound.grid_power")
        self.assertEqual(resp_comp.status_code, 200)
        data_comp = resp_comp.get_json()
        self.assertIsNotNone(data_comp["compound_link"])
        self.assertTrue(data_comp["compound_link"]["is_compound"])
        self.assertIn("modbus_value", data_comp["compound_link"])
        # Should also resolve underlying Modbus definition
        self.assertIsNotNone(data_comp["point_def"])

        # 6. Inspect unified concept key: inverter.concept.ac_frequency
        resp_concept = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=inverter.concept.ac_frequency")
        self.assertEqual(resp_concept.status_code, 200)
        data_concept = resp_concept.get_json()
        self.assertIsNotNone(data_concept["field"])
        self.assertIn("Hz", data_concept["field"]["name"])

        # 7. Error handling: field_key=undefined returns 400
        resp_undefined = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=undefined")
        self.assertEqual(resp_undefined.status_code, 400)

        # 8. Error handling: invalid field key returns 404
        resp_err = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=nonexistent.field.key")
        self.assertEqual(resp_err.status_code, 404)

        # 9. Error handling: invalid device serial returns 404
        resp_err_dev = self.test_client.get("/api/devices/INVALID_SERIAL/field_details?field_key=inverter.inverter.W")
        self.assertEqual(resp_err_dev.status_code, 404)

    def test_settable_fields_sunspec_bounds_restrictions(self):
        """Verify SunSpec bounds restrictions are correctly populated and enforced for settable fields."""
        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number
        beacon = self.client.state.get_beacon()
        beacon_sn = beacon.serial_number

        # 1. Settable enum field: SysMd in REbus_dir
        resp_sysmd = self.test_client.get(f"/api/devices/{beacon_sn}/field_details?field_key=rebus_beacon.REbus_dir.SysMd")
        self.assertEqual(resp_sysmd.status_code, 200)
        data_sysmd = resp_sysmd.get_json()
        b_sysmd = data_sysmd["bounds"]
        self.assertEqual(b_sysmd["category"], "enum")
        self.assertEqual(b_sysmd["point_type"], "enum16")
        self.assertEqual(b_sysmd["raw_min"], 0)
        self.assertEqual(b_sysmd["raw_max"], 6)
        self.assertIn("ARBITRAGE", b_sysmd["valid_names"])
        self.assertIn("CLEAN_BACKUP", b_sysmd["valid_names"])
        self.assertIn("SAFETY_SHUTDOWN", b_sysmd["valid_names"])
        self.assertIn("7 options:", b_sysmd["description"])

        # 2. Settable numeric field in common model: DA (Device Address - uint16, RW)
        resp_da = self.test_client.get(f"/api/devices/{inv_sn}/field_details?field_key=inverter.common.DA")
        self.assertEqual(resp_da.status_code, 200)
        data_da = resp_da.get_json()
        b_da = data_da["bounds"]
        self.assertEqual(b_da["category"], "numeric")
        self.assertEqual(b_da["point_type"], "uint16")
        self.assertEqual(b_da["raw_min"], 0)
        self.assertEqual(b_da["raw_max"], 65535)
        self.assertEqual(b_da["step"], 1)
        self.assertEqual(b_da["description"], "0 to 65,535")
        self.assertEqual(b_da["sentinel"], 65535)

        # 3. Check /api/devices/<serial_number> includes bounds in fields dictionary
        resp_dev = self.test_client.get(f"/api/devices/{beacon_sn}")
        self.assertEqual(resp_dev.status_code, 200)
        dev_data = resp_dev.get_json()
        self.assertIn("fields", dev_data)
        sysmd_field = dev_data["fields"].get("rebus_beacon.REbus_dir.SysMd")
        self.assertIsNotNone(sysmd_field)
        self.assertIn("bounds", sysmd_field)
        self.assertEqual(sysmd_field["bounds"]["category"], "enum")

        # 4. Check /api/fields includes bounds
        resp_all = self.test_client.get("/api/fields")
        self.assertEqual(resp_all.status_code, 200)
        all_fields = resp_all.get_json()
        writable_fields = [f for f in all_fields if f.get("is_writable")]
        self.assertGreater(len(writable_fields), 0)
        for wf in writable_fields:
            self.assertIn("bounds", wf)
            self.assertIsNotNone(wf["bounds"])

    def test_unified_fields_and_optimize_polling_endpoints(self):
        """Test unified field grouping and minimal model set solver endpoints."""
        inv_sn = "0001000714E9"

        # 1. Test /api/devices/<serial_number>/unified_fields
        resp = self.test_client.get(f"/api/devices/{inv_sn}/unified_fields")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["device_sn"], inv_sn)
        self.assertEqual(data["device_type"], "inverter")
        groups = data.get("unified_fields", [])
        self.assertGreater(len(groups), 0)

        # Check concept grouping of grid_power (groups M64208 CTPow, M102 W, and MQTT grid_power_w)
        grid_grp = next((g for g in groups if g["concept_key"] == "grid_power"), None)
        self.assertIsNotNone(grid_grp)
        self.assertGreaterEqual(len(grid_grp["sources"]), 2)
        source_types = {s["source_type"] for s in grid_grp["sources"]}
        self.assertIn("SUNSPEC", source_types)

        # Check concept grouping of system_mode
        sys_grp = next((g for g in groups if g["concept_key"] == "system_mode"), None)
        self.assertIsNotNone(sys_grp)
        self.assertGreaterEqual(len(sys_grp["sources"]), 2)

        # Inverter output power should group inverter.inverter.W, NOT grid_power
        inv_out_grp = next((g for g in groups if g["concept_key"] == "inverter_output_power"), None)
        self.assertIsNotNone(inv_out_grp)
        self.assertTrue(any(s["field_key"] == "inverter.inverter.W" for s in inv_out_grp["sources"]))

        grid_grp = next((g for g in groups if g["concept_key"] == "grid_power"), None)
        self.assertIsNotNone(grid_grp)
        self.assertFalse(any(s["field_key"] == "inverter.inverter.W" for s in grid_grp["sources"]))

        # 2. Test /api/devices/<serial_number>/optimize_polling
        # Select items that can be covered by Model 64208 alone
        opt_resp = self.test_client.post(
            f"/api/devices/{inv_sn}/optimize_polling",
            json={
                "selected_keys": [
                    "inverter.concept.grid_power",
                    "inverter.concept.system_mode",
                ],
                "preferred_sources": {},
            },
        )
        self.assertEqual(opt_resp.status_code, 200)
        opt_data = opt_resp.get_json()
        self.assertIn("minimal_models", opt_data)
        self.assertIn("assignments", opt_data)
        self.assertIn("models_avoided", opt_data)
        # Model 64208 covers them
        self.assertEqual(opt_data["minimal_models"], [64208])
        self.assertEqual(opt_data["stats"]["models_needed"], 1)

        # Pin system_mode to Model 64202 SysMd
        opt_pinned = self.test_client.post(
            f"/api/devices/{inv_sn}/optimize_polling",
            json={
                "selected_keys": [
                    "inverter.concept.grid_power",
                    "inverter.concept.system_mode",
                ],
                "preferred_sources": {
                    "inverter.concept.system_mode": "inverter.REbus_arb.SysMd",
                },
            },
        )
        self.assertEqual(opt_pinned.status_code, 200)
        pinned_data = opt_pinned.get_json()
        self.assertIn(64202, pinned_data["minimal_models"])
        self.assertIn(64208, pinned_data["minimal_models"])
        self.assertEqual(pinned_data["stats"]["models_needed"], 2)
        self.assertIn("unified_fields", pinned_data)
        pinned_sys = next(g for g in pinned_data["unified_fields"] if g["concept_key"] == "system_mode")
        self.assertEqual(pinned_sys["preferred_source_key"], "inverter.REbus_arb.SysMd")

        # Unpin system_mode (empty preferred_sources)
        opt_unpinned = self.test_client.post(
            f"/api/devices/{inv_sn}/optimize_polling",
            json={
                "selected_keys": [
                    "inverter.concept.grid_power",
                    "inverter.concept.system_mode",
                ],
                "preferred_sources": {},
            },
        )
        self.assertEqual(opt_unpinned.status_code, 200)
        unpinned_data = opt_unpinned.get_json()
        self.assertEqual(unpinned_data["minimal_models"], [64208])
        self.assertIn("unified_fields", unpinned_data)
        unpinned_sys = next(g for g in unpinned_data["unified_fields"] if g["concept_key"] == "system_mode")
        self.assertIsNone(unpinned_sys["preferred_source_key"])
        self.assertTrue(all(not s.get("is_pinned") for s in unpinned_sys["sources"]))
        # Optimal source MUST match the minimal polling plan model (64208), NOT avoided Model 64202!
        opt_src = next(s for s in unpinned_sys["sources"] if s.get("is_optimal"))
        self.assertEqual(opt_src["model_id"], 64208)


if __name__ == "__main__":
    unittest.main()
