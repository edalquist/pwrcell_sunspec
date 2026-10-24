import os
import tempfile
import unittest
from pathlib import Path

from pwrcell.client import PwrcellClient
from pwrcell.state import FieldSource
from pwrcell.grouping import (
    load_custom_groupings,
    save_custom_groupings,
    set_field_grouping_override,
    reset_field_grouping_override,
    ungroup_entire_concept,
)
from pwrcell.optimizer import group_device_fields
from pwrcell.ui.server import create_app


class TestGroupingOverrides(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "custom_groupings.yaml"

        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.inv = self.client.state.get_inverter()

        # Set up a couple of fields
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="W",
            label="Inverter Power",
            value=1500.0,
            raw_value=1500,
            units="W",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="Grid Net Power",
            value=-1500.0,
            raw_value=-1500,
            units="W",
            model_id=64208,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )

    def tearDown(self):
        self.client.stop()
        self.temp_dir.cleanup()
        for p in [Path("config/custom_groupings.yaml"), Path("custom_groupings.yaml")]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_load_and_save_custom_groupings(self):
        data = load_custom_groupings(self.config_path)
        self.assertEqual(data["field_overrides"], {})
        self.assertEqual(data["custom_concepts"], {})

        set_field_grouping_override(
            device_sn=self.inv.serial_number,
            field_key="inverter.inverter.W",
            target_concept="custom_concept",
            custom_label="My Custom Concept",
            config_path=self.config_path,
        )

        loaded = load_custom_groupings(self.config_path)
        qual_key = f"{self.inv.serial_number}:inverter.inverter.W"
        self.assertEqual(loaded["field_overrides"].get(qual_key), "custom_concept")
        self.assertEqual(loaded["custom_concepts"].get("custom_concept", {}).get("label"), "My Custom Concept")

        # Reset override
        reset_field_grouping_override(
            device_sn=self.inv.serial_number,
            field_key="inverter.inverter.W",
            config_path=self.config_path,
        )
        reloaded = load_custom_groupings(self.config_path)
        self.assertNotIn(qual_key, reloaded["field_overrides"])

    def test_ungroup_field_creates_standalone_concept(self):
        # By default, W is grouped under inverter_output_power
        default_groups = group_device_fields(self.inv, custom_groupings={"field_overrides": {}})
        w_grp = next((g for g in default_groups if any(s.name == "W" for s in g.sources)), None)
        self.assertIsNotNone(w_grp)
        self.assertEqual(w_grp.concept_key, "inverter_output_power")

        # Explicitly ungroup W
        set_field_grouping_override(
            device_sn=self.inv.serial_number,
            field_key="inverter.inverter.W",
            target_concept=None,  # Ungroup / standalone
            config_path=self.config_path,
        )

        overrides = load_custom_groupings(self.config_path)
        ungrouped_groups = group_device_fields(self.inv, custom_groupings=overrides)
        standalone_grp = next((g for g in ungrouped_groups if any(s.name == "W" for s in g.sources)), None)
        self.assertIsNotNone(standalone_grp)
        self.assertIn("standalone", standalone_grp.id)
        self.assertTrue(standalone_grp.is_custom_override)
        self.assertIn("Ungrouped", standalone_grp.label)

    def test_regroup_field_to_different_concept(self):
        # Regroup CTPow into inverter_output_power
        set_field_grouping_override(
            device_sn=self.inv.serial_number,
            field_key="inverter.inverter_status.CTPow",
            target_concept="inverter_output_power",
            config_path=self.config_path,
        )

        overrides = load_custom_groupings(self.config_path)
        groups = group_device_fields(self.inv, custom_groupings=overrides)
        pwr_grp = next((g for g in groups if g.concept_key == "inverter_output_power"), None)
        self.assertIsNotNone(pwr_grp)
        # Should now contain both W and CTPow
        keys = [s.name for s in pwr_grp.sources]
        self.assertIn("W", keys)
        self.assertIn("CTPow", keys)
        self.assertTrue(pwr_grp.is_custom_override)

    def test_grouping_api_endpoints(self):
        app = create_app(self.client)
        app.config["TESTING"] = True
        test_client = app.test_client()

        # 1. GET overrides
        resp = test_client.get("/api/grouping/overrides")
        self.assertEqual(resp.status_code, 200)

        # 2. POST override (group with custom concept)
        resp = test_client.post(
            "/api/grouping/override",
            json={
                "device_sn": self.inv.serial_number,
                "field_key": "inverter.inverter.W",
                "target_concept": "special_inverter_power",
                "custom_label": "Special Inverter Power",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "ok")

        # 3. POST reset
        resp = test_client.post(
            "/api/grouping/reset",
            json={
                "device_sn": self.inv.serial_number,
                "field_key": "inverter.inverter.W",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "ok")

    def test_export_generalized_and_telemetry_mappings(self):
        from pwrcell.grouping import export_generalized_groupings, export_as_telemetry_mappings
        # Add an override with device serial prefix
        set_field_grouping_override(
            device_sn=self.inv.serial_number,
            field_key="inverter.inverter.W",
            target_concept="custom_inverter_power",
            custom_label="Custom Inverter Power",
            config_path=self.config_path,
        )

        # 1. Test export_generalized_groupings
        gen_res = export_generalized_groupings(self.config_path)
        self.assertIn("custom_concepts", gen_res["data"])
        self.assertIn("field_overrides", gen_res["data"])
        # Serial prefix should be stripped
        self.assertIn("inverter.inverter.W", gen_res["data"]["field_overrides"])
        self.assertEqual(gen_res["data"]["field_overrides"]["inverter.inverter.W"], "custom_inverter_power")
        self.assertIn("custom_inverter_power", gen_res["data"]["custom_concepts"])
        self.assertIn("custom_inverter_power", gen_res["yaml"])
        self.assertNotIn(self.inv.serial_number, gen_res["yaml"])

        # 2. Test export_as_telemetry_mappings
        tel_res = export_as_telemetry_mappings(self.client.state, config_path=self.config_path)
        self.assertIn("mappings", tel_res)
        self.assertIn("yaml", tel_res)
        self.assertIn("version: '1.0'", tel_res["yaml"])
        # Custom concept should be in mappings
        match = next((m for m in tel_res["mappings"] if m["id"] == "custom_inverter_power"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["device_type"], "inverter")
        self.assertEqual(match["label"], "Custom Inverter Power")

        # 3. Test API export routes
        app = create_app(self.client)
        app.config["TESTING"] = True
        test_client = app.test_client()

        resp_gen = test_client.get("/api/grouping/export?format=generalized")
        self.assertEqual(resp_gen.status_code, 200)
        gen_json = resp_gen.get_json()
        self.assertEqual(gen_json["status"], "ok")
        self.assertEqual(gen_json["filename"], "custom_groupings.yaml")

        resp_tel = test_client.get("/api/grouping/export?format=telemetry_mappings")
        self.assertEqual(resp_tel.status_code, 200)
        tel_json = resp_tel.get_json()
        self.assertEqual(tel_json["status"], "ok")
        self.assertEqual(tel_json["filename"], "telemetry_mappings.yaml")

        # Download format
        resp_dl = test_client.get("/api/grouping/export?format=generalized&download=true")
        self.assertEqual(resp_dl.status_code, 200)
        self.assertEqual(resp_dl.mimetype, "text/yaml")
        self.assertIn("attachment; filename=custom_groupings.yaml", resp_dl.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main()
