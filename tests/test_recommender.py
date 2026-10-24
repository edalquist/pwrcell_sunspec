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
        for p in [Path("config/custom_groupings.yaml"), Path("custom_groupings.yaml")]:
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


if __name__ == "__main__":
    unittest.main()
