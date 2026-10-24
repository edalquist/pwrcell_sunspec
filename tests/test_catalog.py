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


if __name__ == "__main__":
    unittest.main()
