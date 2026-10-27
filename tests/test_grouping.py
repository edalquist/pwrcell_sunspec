import os
import tempfile
import unittest
from pathlib import Path

from pwrcell.client import PwrcellClient
from pwrcell.state import FieldSource, UnifiedDevice, StateField
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
        from pwrcell.mapping import MappingRegistry
        from pwrcell.grouping import clear_custom_groupings_cache
        MappingRegistry._instance = None
        clear_custom_groupings_cache()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "custom_groupings.yaml"

        self._orig_config = None
        orig_p = Path("config/custom_groupings.yaml")
        if orig_p.exists():
            self._orig_config = orig_p.read_text(encoding="utf-8")

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
        from pwrcell.mapping import MappingRegistry
        from pwrcell.grouping import clear_custom_groupings_cache
        MappingRegistry._instance = None
        clear_custom_groupings_cache()

        self.client.stop()
        self.temp_dir.cleanup()
        orig_p = Path("config/custom_groupings.yaml")
        if self._orig_config is not None:
            orig_p.write_text(self._orig_config, encoding="utf-8")
        elif orig_p.exists():
            try:
                orig_p.unlink()
            except Exception:
                pass
        for p in [Path("custom_groupings.yaml")]:
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
        self.assertEqual(standalone_grp.label, "Inverter Power")

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

    def test_cross_device_grouping_forbidden(self):
        """Grouping fields across different device types is strictly rejected."""
        with self.assertRaises(ValueError) as ctx:
            set_field_grouping_override(
                device_sn="000100034AC7",
                field_key="pv_link.model_64207.P",
                target_concept="inverter_output_power",
                config_path=self.config_path,
            )
        self.assertIn("grouping across devices is not permitted", str(ctx.exception).lower())

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

        # 4. POST override (ungroup) without device_sn (inferred from field_key)
        resp = test_client.post(
            "/api/grouping/override",
            json={
                "device_sn": "",
                "field_key": "inverter.inverter.W",
                "target_concept": None,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "ok")
        qual_key = f"{self.inv.serial_number}:inverter.inverter.W"
        self.assertIn(qual_key, data["overrides"]["field_overrides"])
        self.assertIsNone(data["overrides"]["field_overrides"][qual_key])

        # 5. POST reset without device_sn (inferred from field_key)
        resp = test_client.post(
            "/api/grouping/reset",
            json={
                "device_sn": "",
                "field_key": "inverter.inverter.W",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "ok")
        self.assertNotIn(qual_key, data["overrides"]["field_overrides"])

        # 6. POST ungroup_all without device_sn (inferred from concept_key)
        resp = test_client.post(
            "/api/grouping/ungroup_all",
            json={
                "device_sn": "",
                "concept_key": "inverter_output_power",
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
        self.assertIn("groups", tel_res)
        self.assertIn("yaml", tel_res)
        self.assertIn("version: '2.0'", tel_res["yaml"])
        # Custom concept should be in groups
        match = next((m for m in tel_res["groups"] if m["id"] == "custom_inverter_power"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["name"], "Custom Inverter Power")
        self.assertIn("inverter.model_102.W", match["fields"])

        # 3. Test API export routes
        app = create_app(self.client)
        app.config["TESTING"] = True
        test_client = app.test_client()

        resp_gen = test_client.get("/api/grouping/export?format=generalized")
        self.assertEqual(resp_gen.status_code, 200)
        gen_json = resp_gen.get_json()
        self.assertEqual(gen_json["status"], "ok")
        self.assertEqual(gen_json["filename"], "custom_groupings.yaml")

        resp_tel = test_client.get("/api/grouping/export?format=groupings")
        self.assertEqual(resp_tel.status_code, 200)
        tel_json = resp_tel.get_json()
        self.assertEqual(tel_json["status"], "ok")
        self.assertEqual(tel_json["filename"], "groupings.yaml")

        # Download format
        resp_dl = test_client.get("/api/grouping/export?format=generalized&download=true")
        self.assertEqual(resp_dl.status_code, 200)
        self.assertEqual(resp_dl.mimetype, "text/yaml")
        self.assertIn("attachment; filename=custom_groupings.yaml", resp_dl.headers.get("Content-Disposition", ""))

    def test_infer_ha_classes_and_export_inference(self):
        """Verify that infer_ha_classes correctly maps units and names to Home Assistant classes."""
        from pwrcell.catalog import infer_ha_classes
        from pwrcell.grouping import export_as_telemetry_mappings

        # Unit-based inference tests
        self.assertEqual(infer_ha_classes(units="Wh", name="accumulated_energy"), ("energy", "total_increasing"))
        self.assertEqual(infer_ha_classes(units="kWh", name="tot_energy"), ("energy", "total_increasing"))
        self.assertEqual(infer_ha_classes(units="W", name="rebus_power"), ("power", "measurement"))
        self.assertEqual(infer_ha_classes(units="kW", name="inverter_power"), ("power", "measurement"))
        self.assertEqual(infer_ha_classes(units="V", name="rebus_voltage"), ("voltage", "measurement"))
        self.assertEqual(infer_ha_classes(units="A", name="rebus_current"), ("current", "measurement"))
        self.assertEqual(infer_ha_classes(units="Hz", name="grid_freq"), ("frequency", "measurement"))
        self.assertEqual(infer_ha_classes(units="°C", name="cabinet_temp"), ("temperature", "measurement"))
        self.assertEqual(infer_ha_classes(units="C", name="ambient_temp"), ("temperature", "measurement"))
        self.assertEqual(infer_ha_classes(units="%", name="state_of_charge"), ("battery", "measurement"))

        # Non-sensor / enum / text entities remain None
        self.assertEqual(infer_ha_classes(units="", name="system_mode", platform="select"), (None, None))
        self.assertEqual(infer_ha_classes(units="", name="inverter_serial", platform="sensor"), (None, None))

        # Register live push telemetry with unit Wh but without explicit ha_hint
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="accumulated_energy",
            label="Inverter Output Accumulated Energy",
            value=999999.0,
            units="Wh",
            sub_group="live",
        )
        field = self.inv.fields.get("inverter.live.accumulated_energy")
        self.assertIsNotNone(field)
        self.assertIsNotNone(field.ha_hint)
        self.assertEqual(field.ha_hint.device_class, "energy")
        self.assertEqual(field.ha_hint.state_class, "total_increasing")

    def test_approve_polarity_positive_and_negative_conventions(self):
        """Verify approving an inverted pair with Positive or Negative convention correctly applies transform."""
        from pwrcell.grouping import approve_suggestion, save_current_as_telemetry_mappings
        from pwrcell.tools.correlator import evaluate_comparisons
        from pwrcell.mapping import MappingRegistry

        test_sn = "TEST_INV_POLARITY"
        dev = self.client.state.register_device(test_sn, 99, "inverter", "Test Inverter")

        # Add live push telemetry
        self.client.state.set_field(
            device_sn=test_sn,
            name="grid_power_w",
            label="Grid Net Power",
            value=4029.0,
            raw_value=4029.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.client.state.set_field(
            device_sn=test_sn,
            name="CTPow",
            label="External CT Power measurement",
            value=-4007.0,
            raw_value=-4007.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
            model_id=64208,
        )

        # 1. Approve with Positive Convention (inverts negative field CTPow)
        approve_suggestion(
            device_sn=test_sn,
            field_keys=["inverter.inverter_status.CTPow", "inverter.live.grid_power_w"],
            target_concept="grid_power",
            custom_label="Grid Net Power",
            suggestion_id="sugg_test_pos",
            transform="negate",
            negate_field_key="inverter.inverter_status.CTPow",
            polarity_convention="positive",
            config_path=self.config_path,
        )

        custom_data = load_custom_groupings(self.config_path)
        rows = evaluate_comparisons(self.client.state, custom_groupings=custom_data)
        grid_row = next((r for r in rows if r.mapping_id == f"{test_sn}_grid_power"), None)
        self.assertIsNotNone(grid_row)
        self.assertFalse(grid_row.is_discrepant, f"Should not be discrepant: {grid_row.discrepancy_reason}")
        val_map = {s["field_key"]: s["value"] for s in grid_row.sources}
        self.assertEqual(val_map["inverter.inverter_status.CTPow"], 4007.0)
        self.assertEqual(val_map["inverter.live.grid_power_w"], 4029.0)

        # 2. Approve with Negative Convention (inverts positive field grid_power_w)
        approve_suggestion(
            device_sn=test_sn,
            field_keys=["inverter.inverter_status.CTPow", "inverter.live.grid_power_w"],
            target_concept="grid_power",
            custom_label="Grid Net Power",
            suggestion_id="sugg_test_neg",
            transform="negate",
            negate_field_key="inverter.live.grid_power_w",
            polarity_convention="negative",
            config_path=self.config_path,
        )

        custom_data = load_custom_groupings(self.config_path)
        rows = evaluate_comparisons(self.client.state, custom_groupings=custom_data)
        grid_row = next((r for r in rows if r.mapping_id == f"{test_sn}_grid_power"), None)
        self.assertIsNotNone(grid_row)
        self.assertFalse(grid_row.is_discrepant, f"Should not be discrepant: {grid_row.discrepancy_reason}")
        val_map = {s["field_key"]: s["value"] for s in grid_row.sources}
        self.assertEqual(val_map["inverter.inverter_status.CTPow"], -4007.0)
        self.assertEqual(val_map["inverter.live.grid_power_w"], -4029.0)

        # 3. Save to Mappings and Clean Slate
        tmppath = Path(self.temp_dir.name) / "telemetry_mappings.yaml"
        # Reset to positive convention before exporting
        approve_suggestion(
            device_sn=test_sn,
            field_keys=["inverter.inverter_status.CTPow", "inverter.live.grid_power_w"],
            target_concept="grid_power",
            custom_label="Grid Net Power",
            suggestion_id="sugg_test_pos",
            transform="negate",
            negate_field_key="inverter.inverter_status.CTPow",
            polarity_convention="positive",
            config_path=self.config_path,
        )
        save_current_as_telemetry_mappings(
            self.client.state,
            config_path=tmppath,
            custom_groupings_path=self.config_path,
            only_custom=False,
            clear_custom_overrides=True,
        )
        reg = MappingRegistry.get_instance(str(tmppath))
        reg.reload()
        custom_data_clean = load_custom_groupings(self.config_path)
        self.assertEqual(custom_data_clean.get("field_overrides"), {})
        self.assertEqual(custom_data_clean.get("field_transforms"), {})

        rows_after = evaluate_comparisons(self.client.state, custom_groupings=custom_data_clean)
        grid_row_after = next((r for r in rows_after if r.mapping_id == f"{test_sn}_grid_power"), None)
        self.assertIsNotNone(grid_row_after)
        self.assertFalse(grid_row_after.is_discrepant)

    def test_manual_grouping_merges_standalone_fields(self):
        """When grouping a field with an existing standalone concept, both fields merge into one group."""
        pv_dev = UnifiedDevice(
            serial_number="000100034AC7",
            slave_id=1,
            device_type="pv_link",
            model_name="pv_link",
            manufacturer="Generac",
            version="1.0",
        )
        f1 = StateField(
            key="pv_link.pvlink_status.Iin",
            device_sn=pv_dev.serial_number,
            device_type="pv_link",
            name="Iin",
            label="PV String Current",
            description="",
            value=4.5,
            raw_value=45,
            units="A",
            model_id=64251,
            model_name="pvlink_status",
        )
        f2 = StateField(
            key="pv_link.string_combiner.DCA",
            device_sn=pv_dev.serial_number,
            device_type="pv_link",
            name="DCA",
            label="PV String Current",
            description="",
            value=4.4,
            raw_value=44,
            units="A",
            model_id=64252,
            model_name="string_combiner",
        )
        pv_dev.fields[f1.key] = f1
        pv_dev.fields[f2.key] = f2
        self.client.state.devices[pv_dev.serial_number] = pv_dev

        # Test API endpoint override with member_field_keys
        app = create_app(self.client)
        app.config["TESTING"] = True
        test_client = app.test_client()

        resp = test_client.post(
            "/api/grouping/override",
            json={
                "device_sn": pv_dev.serial_number,
                "field_key": f2.key,
                "member_field_keys": [f1.key, f2.key],
                "target_concept": "iin_64251",
                "custom_label": "PV String Current",
            },
        )
        self.assertEqual(resp.status_code, 200)

        # Run group_device_fields
        groups = group_device_fields(pv_dev)
        curr_groups = [g for g in groups if "iin" in g.concept_key.lower()]
        # There must only be exactly 1 group, NOT two rows with the same name
        self.assertEqual(len(curr_groups), 1)
        grp = curr_groups[0]
        self.assertEqual(grp.label, "PV String Current")
        src_keys = [s.field_key for s in grp.sources]
        self.assertIn("pv_link.pvlink_status.Iin", src_keys)
        self.assertIn("pv_link.string_combiner.DCA", src_keys)


if __name__ == "__main__":
    unittest.main()
