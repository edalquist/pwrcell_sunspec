import os
import tempfile
import unittest
from pathlib import Path

from pwrcell.client import PwrcellClient
from pwrcell.state import FieldSource
from pwrcell.recommender import find_suggested_groupings, tokenize_name, find_semantic_cluster
from pwrcell.grouping import (
    load_custom_groupings,
    approve_suggestion,
    dismiss_suggestion,
)
from pwrcell.optimizer import group_device_fields
from pwrcell.ui.server import create_app


class TestRecommenderEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "custom_groupings.yaml"

        self._orig_config = None
        orig_p = Path("config/custom_groupings.yaml")
        if orig_p.exists():
            self._orig_config = orig_p.read_text(encoding="utf-8")

        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.inv = self.client.state.get_inverter()

        # Add two single-source candidate fields on the inverter that have compatible units and matching values
        # e.g., SunSpec M102 Wh exported energy (Wh) vs Generac vendor M64207 E energy (Wh)
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="Wh_Test",
            label="Inverter Energy Export Wh",
            value=123456.0,
            raw_value=123456,
            units="Wh",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="E_Test",
            label="REbus Inverter Energy E",
            value=123456.0,
            raw_value=123456,
            units="Wh",
            model_id=64207,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_test",
        )

    def tearDown(self):
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

    def test_tokenize_name_and_semantic_clusters(self):
        toks = tokenize_name("Inverter_Output_Exported_Energy_Wh")
        self.assertIn("inverter", toks)
        self.assertIn("energy", toks)
        self.assertIn("wh", toks)

        cluster = find_semantic_cluster(toks, "Wh")
        self.assertIsNotNone(cluster)
        self.assertEqual(cluster["concept"], "energy")
        self.assertEqual(cluster["units"], "Wh")

    def test_find_suggested_groupings(self):
        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        self.assertGreater(len(suggestions), 0)

        match = next(
            (
                s
                for s in suggestions
                if any(src.name == "Wh_Test" for src in s.sources)
                and any(src.name == "E_Test" for src in s.sources)
            ),
            None,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.device_sn, self.inv.serial_number)
        self.assertEqual(match.units, "Wh")
        self.assertEqual(match.confidence_label, "HIGH")
        self.assertGreaterEqual(match.confidence, 0.85)
        # Check reasons
        self.assertTrue(any("Exact live value match" in r for r in match.reasons))
        self.assertTrue(any("semantic" in r.lower() or "naming" in r.lower() for r in match.reasons))

    def test_approve_and_dismiss_suggestion(self):
        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        match = next(
            (
                s
                for s in suggestions
                if any(src.name == "Wh_Test" for src in s.sources)
                and any(src.name == "E_Test" for src in s.sources)
            ),
            None,
        )
        self.assertIsNotNone(match)

        # 1. Dismiss suggestion
        dismiss_suggestion(match.id, config_path=self.config_path)
        overrides = load_custom_groupings(self.config_path)
        self.assertIn(match.id, overrides["dismissed_suggestions"])

        # 2. Verify find_suggested_groupings with dismissed_ids excludes it
        suggs_after_dismiss = find_suggested_groupings(
            self.client.state,
            dismissed_ids=set(overrides["dismissed_suggestions"]),
        )
        self.assertFalse(any(s.id == match.id for s in suggs_after_dismiss))

        # 3. Approve suggestion
        field_keys = [s.field_key for s in match.sources]
        approve_suggestion(
            device_sn=match.device_sn,
            field_keys=field_keys,
            target_concept=match.suggested_concept_key,
            custom_label=match.suggested_label,
            suggestion_id=match.id,
            config_path=self.config_path,
        )

        overrides_after_approve = load_custom_groupings(self.config_path)
        # Verify both fields now share the target concept
        for f_key in field_keys:
            qual_key = f"{match.device_sn}:{f_key}"
            self.assertEqual(overrides_after_approve["field_overrides"].get(qual_key), match.suggested_concept_key)

        # Verify optimizer groups them together
        groups = group_device_fields(self.inv, custom_groupings=overrides_after_approve)
        merged_grp = next((g for g in groups if g.concept_key == match.suggested_concept_key), None)
        self.assertIsNotNone(merged_grp)
        grp_field_names = [s.name for s in merged_grp.sources]
        self.assertIn("Wh_Test", grp_field_names)
        self.assertIn("E_Test", grp_field_names)

    def test_recommender_api_endpoints(self):
        app = create_app(self.client)
        app.config["TESTING"] = True
        test_client = app.test_client()

        # 1. GET /api/grouping/suggestions
        resp = test_client.get("/api/grouping/suggestions")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("suggestions", data)
        self.assertIn("count", data)
        self.assertGreater(data["count"], 0)

        sugg = data["suggestions"][0]
        s_id = sugg["id"]

        # 2. POST /api/grouping/suggestions/dismiss
        resp_dismiss = test_client.post(
            "/api/grouping/suggestions/dismiss",
            json={"suggestion_id": s_id},
        )
        self.assertEqual(resp_dismiss.status_code, 200)
        dismiss_data = resp_dismiss.get_json()
        self.assertEqual(dismiss_data.get("status"), "ok")

        # 3. POST /api/grouping/suggestions/approve
        resp_approve = test_client.post(
            "/api/grouping/suggestions/approve",
            json={
                "device_sn": sugg["device_sn"],
                "field_keys": [src["field_key"] for src in sugg["sources"]],
                "target_concept": sugg["suggested_concept_key"],
                "label": sugg["suggested_label"],
                "suggestion_id": s_id,
            },
        )
        self.assertEqual(resp_approve.status_code, 200)
        approve_data = resp_approve.get_json()
        self.assertEqual(approve_data.get("status"), "ok")

    def test_scale_factors_excluded_from_suggestions(self):
        # Add two scale factor fields with identical values
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="W_SF",
            label="Scale Factor: Power",
            value=0,
            raw_value=0,
            units=None,
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="V_SF",
            label="Scale Factor: Voltage",
            value=0,
            raw_value=0,
            units=None,
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_test",
        )

        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        # Assert neither W_SF nor V_SF appears in any suggestion
        for s in suggestions:
            for src in s.sources:
                self.assertNotIn("W_SF", src.name)
                self.assertNotIn("V_SF", src.name)
                self.assertFalse(src.name.endswith("_SF"))

    def test_recommender_filters_settings_phases_and_directions(self):
        # 1. Protection trip setting vs live telemetry (Hz vs ReConnMaxHz)
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="Hz_Live",
            label="Grid Frequency",
            value=60.01,
            raw_value=6001,
            units="Hz",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="ReConnMaxHz",
            label="Reconnect Max Frequency Trip Setting",
            value=60.50,
            raw_value=6050,
            units="Hz",
            model_id=64203,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )

        # 2. Phase A vs Phase B voltage
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="PhVphA_Test",
            label="Phase A Voltage",
            value=120.0,
            raw_value=1200,
            units="V",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="PhVphB_Test",
            label="Phase B Voltage",
            value=120.2,
            raw_value=1202,
            units="V",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )

        # 3. Cabinet vs Transformer temp
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="TmpCab_Test",
            label="Cabinet Temperature",
            value=45.0,
            raw_value=450,
            units="C",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="TmpTrns_Test",
            label="Transformer Temperature",
            value=45.2,
            raw_value=452,
            units="C",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )

        # 4. Energy export vs energy import
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhExp_Test",
            label="Lifetime Exported Energy",
            value=50000.0,
            raw_value=50000,
            units="Wh",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhImp_Test",
            label="Lifetime Imported Energy",
            value=50000.0,
            raw_value=50000,
            units="Wh",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inv_test",
        )

        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        
        # Verify no illegal pairings exist in suggestions
        for s in suggestions:
            names = {src.name for src in s.sources}
            self.assertFalse({"Hz_Live", "ReConnMaxHz"}.issubset(names))
            self.assertFalse({"PhVphA_Test", "PhVphB_Test"}.issubset(names))
            self.assertFalse({"TmpCab_Test", "TmpTrns_Test"}.issubset(names))
            self.assertFalse({"WhExp_Test", "WhImp_Test"}.issubset(names))

    def test_batch_api_endpoints(self):
        app = create_app(self.client)
        app.config["TESTING"] = True
        test_client = app.test_client()

        # 1. Fetch suggestions
        resp = test_client.get("/api/grouping/suggestions")
        self.assertEqual(resp.status_code, 200)
        suggs = resp.get_json().get("suggestions", [])
        self.assertGreater(len(suggs), 0)

        # 2. Batch dismiss
        ids_to_dismiss = [s["id"] for s in suggs[:2]]
        resp_dismiss = test_client.post(
            "/api/grouping/suggestions/batch-dismiss",
            json={"suggestion_ids": ids_to_dismiss},
        )
        self.assertEqual(resp_dismiss.status_code, 200)
        self.assertEqual(resp_dismiss.get_json()["count"], 2)

        # 3. Batch approve
        items_to_approve = [
            {
                "device_sn": s["device_sn"],
                "field_keys": [src["field_key"] for src in s["sources"]],
                "target_concept": s["suggested_concept_key"],
                "label": s["suggested_label"],
                "suggestion_id": s["id"],
            }
            for s in suggs[2:4]
        ]
        resp_approve = test_client.post(
            "/api/grouping/suggestions/batch-approve",
            json={"suggestions": items_to_approve},
        )
        self.assertEqual(resp_approve.status_code, 200)
        self.assertEqual(resp_approve.get_json()["count"], len(items_to_approve))

    def test_distinct_concepts_for_different_energy_pairs(self):
        """Ensure distinct energy register pairs receive unique, specific concepts instead of all collapsing into 'energy'."""
        # Pair A: Exported energy (WhOut vs Whx) at 30,000,000 Wh
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhOut_A",
            label="Total AC Energy Exported",
            value=31963504.0,
            raw_value=31963504,
            units="Wh",
            model_id=64208,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="Whx_A",
            label="Accumulated Export Energy",
            value=31963504.0,
            raw_value=31963504,
            units="Wh",
            model_id=64204,
            source=FieldSource.MODBUS_POLL,
            sub_group="REbus_exp_test",
        )

        # Pair B: Output energy (WH vs E) at 1,120,750,000 Wh
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="WH_B",
            label="Inverter Output AC Energy",
            value=1120750797.0,
            raw_value=1120750797,
            units="Wh",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_test",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="E_B",
            label="Accumulated Output Energy",
            value=1120750797.0,
            raw_value=1120750797,
            units="Wh",
            model_id=64207,
            source=FieldSource.MODBUS_POLL,
            sub_group="REbus_status_test",
        )

        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())

        # Find suggestion for Pair A
        sugg_a = next(
            (s for s in suggestions if {"WhOut_A", "Whx_A"}.issubset({src.name for src in s.sources})),
            None,
        )
        # Find suggestion for Pair B
        sugg_b = next(
            (s for s in suggestions if {"WH_B", "E_B"}.issubset({src.name for src in s.sources})),
            None,
        )

        self.assertIsNotNone(sugg_a, "Pair A (WhOut_A/Whx_A) should have a suggestion")
        self.assertIsNotNone(sugg_b, "Pair B (WH_B/E_B) should have a suggestion")

        # Crucial checks:
        # 1. Neither pair should be assigned generic "energy"
        self.assertNotEqual(sugg_a.suggested_concept_key, "energy")
        self.assertNotEqual(sugg_b.suggested_concept_key, "energy")

        # 2. The two distinct pairs MUST receive different concept keys so they do NOT merge into each other
        self.assertNotEqual(
            sugg_a.suggested_concept_key,
            sugg_b.suggested_concept_key,
            f"Distinct pairs should not share concept key: {sugg_a.suggested_concept_key}",
        )

    def test_find_suggested_groupings_inverted_polarity(self):
        # Add two power fields on the inverter with opposite signs:
        # e.g., grid_power (+2800 W) vs CTPow (-2800 W)
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="grid_power_live",
            label="Grid Power",
            value=2800.0,
            raw_value=2800.0,
            units="W",
            model_id=None,
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow_raw",
            label="Current Transformer Power",
            value=-2800.0,
            raw_value=-2800.0,
            units="W",
            model_id=64208,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_ct",
        )

        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        inv_sugg = next(
            (
                s for s in suggestions
                if any(src.name == "grid_power_live" for src in s.sources)
                and any(src.name == "CTPow_raw" for src in s.sources)
            ),
            None,
        )
        self.assertIsNotNone(inv_sugg, "Should generate grouping suggestion for opposite-polarity pair")
        self.assertTrue(inv_sugg.inverted_pair)
        self.assertEqual(inv_sugg.suggested_transform, "negate")
        self.assertTrue(any("Inverted polarity live match" in r for r in inv_sugg.reasons))
        self.assertEqual(inv_sugg.units, "W")

    def test_never_merge_across_fields_from_same_model(self):
        """Fields belonging to the same model (e.g. M802 CellVMax vs CellVMin) must NEVER be merged or suggested."""
        bat = next((d for d in self.client.state.devices.values() if d.device_type == "battery"), None)
        if not bat:
            bat = self.client.state.get_or_create_device("TEST_BAT_01", "battery")

        # 1. Add CellVMax and CellVMin on M802 with nearly identical live voltages
        self.client.state.set_field(
            device_sn=bat.serial_number,
            name="CellVMax",
            label="Max Cell Voltage (M802)",
            value=3.85,
            raw_value=3852,
            units="V",
            model_id=802,
            source=FieldSource.MODBUS_POLL,
            sub_group="battery",
        )
        self.client.state.set_field(
            device_sn=bat.serial_number,
            name="CellVMin",
            label="Min Cell Voltage (M802)",
            value=3.83,
            raw_value=3825,
            units="V",
            model_id=802,
            source=FieldSource.MODBUS_POLL,
            sub_group="battery",
        )

        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        
        # Verify NO suggestion merges CellVMax and CellVMin
        bad_sugg = next(
            (
                s for s in suggestions
                if any(src.name == "CellVMax" for src in s.sources)
                and any(src.name == "CellVMin" for src in s.sources)
            ),
            None,
        )
        self.assertIsNone(bad_sugg, "CellVMax and CellVMin from the same model M802 must NEVER be suggested for merging")

        # 2. Add two fields from MQTT push on the same device with identical values
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="val_a",
            label="Metric A",
            value=120.0,
            units="V",
            model_id=None,
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.client.state.set_field(
            device_sn=self.inv.serial_number,
            name="val_b",
            label="Metric B",
            value=120.0,
            units="V",
            model_id=None,
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )

        suggestions_after = find_suggested_groupings(self.client.state, dismissed_ids=set())
        bad_mqtt = next(
            (
                s for s in suggestions_after
                if any(src.name == "val_a" for src in s.sources)
                and any(src.name == "val_b" for src in s.sources)
            ),
            None,
        )
        self.assertIsNone(bad_mqtt, "Two MQTT fields from the same device must NEVER be suggested for merging")


if __name__ == "__main__":
    unittest.main()
