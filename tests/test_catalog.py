"""Unit tests for pwrcell.catalog."""

import unittest
from pwrcell.catalog import ModelCatalog, get_catalog


class TestModelCatalog(unittest.TestCase):

    def setUp(self):
        self.catalog = get_catalog()

    def test_catalog_loads_models(self):
        self.assertGreater(len(self.catalog.models), 50)
        self.assertIn(1, self.catalog.models)
        self.assertIn(64208, self.catalog.models)
        self.assertIn(64209, self.catalog.models)

    def test_model_common_points(self):
        common = self.catalog.get_model(1)
        self.assertIsNotNone(common)
        self.assertEqual(common.name, "common")
        self.assertIn("Mn", common.points)
        self.assertIn("Md", common.points)
        self.assertIn("SN", common.points)
        self.assertEqual(common.points["Mn"].label, "Manufacturer")

    def test_model_64208_inverter_status(self):
        inv_status = self.catalog.get_model(64208)
        self.assertIsNotNone(inv_status)
        self.assertEqual(inv_status.name, "inverter_status")
        
        sys_md = inv_status.points.get("SysMd")
        self.assertIsNotNone(sys_md)
        self.assertTrue(sys_md.is_enum)
        self.assertFalse(sys_md.is_writable)
        self.assertGreater(len(sys_md.symbols), 3)

        ct_pow = inv_status.points.get("CTPow")
        self.assertIsNotNone(ct_pow)
        self.assertEqual(ct_pow.units, "W")
        self.assertTrue(ct_pow.is_numeric)

    def test_ha_metadata_derivation(self):
        # Power sensor
        inv_status = self.catalog.get_model(64208)
        ct_pow = inv_status.points["CTPow"]
        hint = self.catalog.derive_ha_metadata(ct_pow)
        self.assertEqual(hint.platform, "sensor")
        self.assertEqual(hint.device_class, "power")
        self.assertEqual(hint.state_class, "measurement")
        self.assertEqual(hint.unit_of_measurement, "W")

        # Energy sensor
        batt_status = self.catalog.get_model(64209)
        wh_in = batt_status.points["WhIn"]
        hint = self.catalog.derive_ha_metadata(wh_in)
        self.assertEqual(hint.platform, "sensor")
        self.assertEqual(hint.device_class, "energy")
        self.assertEqual(hint.state_class, "total_increasing")
        self.assertEqual(hint.unit_of_measurement, "Wh")

        # Writable select on 64200
        rebus_dir = self.catalog.get_model(64200)
        self.assertIsNotNone(rebus_dir)
        sys_md_rw = rebus_dir.points["SysMd"]
        self.assertTrue(sys_md_rw.is_writable)
        hint = self.catalog.derive_ha_metadata(sys_md_rw)
        self.assertEqual(hint.platform, "select")
        self.assertEqual(hint.entity_category, "config")
        self.assertIn("SELF_SUPPLY", hint.options)

    def test_is_scale_factor_point(self):
        from pwrcell.catalog import is_scale_factor_point

        self.assertTrue(is_scale_factor_point(point_type="sunssf"))
        self.assertTrue(is_scale_factor_point(name="W_SF"))
        self.assertTrue(is_scale_factor_point(name="vt_sf"))
        self.assertTrue(is_scale_factor_point(name="SF_W"))
        self.assertTrue(is_scale_factor_point(name="sf_v"))
        self.assertTrue(is_scale_factor_point(name="sunssf_1"))
        self.assertTrue(is_scale_factor_point(label="Scale Factor for Voltage"))
        self.assertTrue(is_scale_factor_point(label="Power Scale Factor"))
        self.assertTrue(is_scale_factor_point(explicit=True))
        self.assertFalse(is_scale_factor_point(name="W", point_type="int16", label="Watts"))

    def test_get_suggested_precision(self):
        from pwrcell.catalog import get_suggested_precision

        self.assertEqual(get_suggested_precision("W"), 0)
        self.assertEqual(get_suggested_precision("Wh"), 0)
        self.assertEqual(get_suggested_precision("VAh"), 0)
        self.assertEqual(get_suggested_precision("kWh"), 2)
        self.assertEqual(get_suggested_precision("Hz"), 2)
        self.assertEqual(get_suggested_precision("V"), 1)
        self.assertEqual(get_suggested_precision("A"), 1)
        self.assertEqual(get_suggested_precision("%"), 1)
        self.assertEqual(get_suggested_precision(None, device_class="power"), 0)
        self.assertEqual(get_suggested_precision(None, device_class="energy"), 0)
        self.assertEqual(get_suggested_precision("kWh", device_class="energy"), 2)
        self.assertEqual(get_suggested_precision(None, device_class="voltage"), 1)
        self.assertEqual(get_suggested_precision(None, device_class="frequency"), 2)
        self.assertIsNone(get_suggested_precision(None, None))

    def test_sunspec_model_constants_match_catalog(self):
        from pwrcell.catalog import (
            MODEL_BATTERY_BASE,
            MODEL_BATTERY_STATUS,
            MODEL_BATTERY_WARRANTY,
            MODEL_COMMON,
            MODEL_INVERTER_SPLIT_PHASE,
            MODEL_INVERTER_STATUS,
            MODEL_PVLINK_STATUS,
            MODEL_REBUS_DIR,
            MODEL_REBUS_STATUS,
            MODEL_STRING_COMBINER,
        )

        self.assertEqual(MODEL_COMMON, 1)
        self.assertEqual(MODEL_INVERTER_SPLIT_PHASE, 102)
        self.assertEqual(MODEL_STRING_COMBINER, 404)
        self.assertEqual(MODEL_BATTERY_BASE, 802)
        self.assertEqual(MODEL_REBUS_DIR, 64200)
        self.assertEqual(MODEL_REBUS_STATUS, 64207)
        self.assertEqual(MODEL_INVERTER_STATUS, 64208)
        self.assertEqual(MODEL_BATTERY_STATUS, 64209)
        self.assertEqual(MODEL_PVLINK_STATUS, 64251)
        self.assertEqual(MODEL_BATTERY_WARRANTY, 64252)

    def test_parse_model_json_offsets_and_subgroup_collision_protection(self):
        # 1. Fixed-block offset after ID and L (1 + 1 = 2 registers) should start at 0
        common = self.catalog.get_model(1)
        self.assertEqual(common.points["Mn"].offset, 0)

        # 2. A repeating sub-group point with the same name as a fixed-block point must not overwrite the fixed-block point
        cat = ModelCatalog.__new__(ModelCatalog)
        cat._models_by_id = {}
        cat._models_by_name = {}
        cat._parse_model_json({
            "id": 99999,
            "group": {
                "name": "test_model",
                "label": "Test Model",
                "points": [
                    {"name": "ID", "type": "uint16", "size": 1, "value": 99999},
                    {"name": "L", "type": "uint16", "size": 1},
                    {"name": "V", "type": "int16", "size": 1, "units": "V", "label": "Total Voltage"},
                ],
                "groups": [
                    {
                        "name": "string",
                        "points": [
                            {"name": "V", "type": "int16", "size": 1, "units": "mV", "label": "String Voltage"},
                            {"name": "StrA", "type": "int16", "size": 1, "units": "A", "label": "String Current"},
                        ],
                    }
                ],
            },
        })
        m = cat.get_model(99999)
        self.assertIsNotNone(m)
        # Fixed-block V must retain offset 0 and units "V"
        self.assertEqual(m.points["V"].offset, 0)
        self.assertEqual(m.points["V"].units, "V")
        # Colliding sub-group V is stored under "string.V"
        self.assertIn("string.V", m.points)
        self.assertEqual(m.points["string.V"].units, "mV")
        # Non-colliding sub-group StrA is accessible by both "StrA" and "string.StrA"
        self.assertIn("StrA", m.points)
        self.assertIn("string.StrA", m.points)

    def test_enum_substate_lookup_and_encoding(self):
        """Points with 4-bit substate encoding (e.g. Model 64207 St) should resolve substate integers to base symbol names."""
        rebus_status = self.catalog.get_model(64207)
        self.assertIsNotNone(rebus_status)
        st_pt = rebus_status.points.get("St")
        self.assertIsNotNone(st_pt)
        self.assertTrue(st_pt.is_enum)
        self.assertTrue(st_pt.has_substate_encoding)

        # Exact match
        sym_exact = st_pt.lookup_symbol(12544)
        self.assertIsNotNone(sym_exact)
        self.assertEqual(sym_exact.name, "LOW_SUN")
        self.assertEqual(st_pt.get_substate(12544), 0)

        # Value with substate 2 (12544 + 2 = 12546, 0x3102)
        sym_sub = st_pt.lookup_symbol(12546)
        self.assertIsNotNone(sym_sub)
        self.assertEqual(sym_sub.name, "LOW_SUN")
        self.assertEqual(st_pt.get_substate(12546), 2)

        # resolve_enum_value with substate
        int_val, sym_name = st_pt.resolve_enum_value(12546)
        self.assertEqual(int_val, 12546)
        self.assertEqual(sym_name, "LOW_SUN")

        # Standard enum without 4-bit substate encoding (Model 102 St)
        inv_model = self.catalog.get_model(102)
        inv_st = inv_model.points.get("St")
        self.assertIsNotNone(inv_st)
        self.assertTrue(inv_st.is_enum)
        self.assertFalse(inv_st.has_substate_encoding)


if __name__ == "__main__":
    unittest.main()
