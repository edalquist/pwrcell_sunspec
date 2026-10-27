"""Tests for custom bounds on mutable fields, proxy validation, and Home Assistant discovery."""

import unittest
from unittest.mock import MagicMock
from pwrcell.bounds import (
    clear_custom_bounds_cache,
    get_custom_bounds,
    load_custom_bounds,
    normalize_bounds,
    save_custom_bound,
)
from pwrcell.catalog import get_catalog
from pwrcell.concept import CompoundFieldView, ConceptSource
from pwrcell.controls import ControlDispatcher
from pwrcell.ha import generate_discovery_payload, is_ha_writable_allowed
from pwrcell.state import FieldSource, StateField, StateStore


class TestCustomBounds(unittest.TestCase):
    def setUp(self):
        clear_custom_bounds_cache()
        self.catalog = get_catalog()
        self.state = StateStore()
        self.bat = self.state.register_device(
            serial_number="000100082128",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )
        self.state.set_field(
            device_sn="000100082128",
            name="AMax_SF",
            value=-2,
            raw_value=-2,
            source=FieldSource.MODBUS_POLL,
            sub_group="battery",
            model_id=802,
        )
        self.state.set_field(
            device_sn="000100082128",
            name="AChaMax",
            value=25.0,
            raw_value=2500,
            source=FieldSource.MODBUS_POLL,
            sub_group="battery",
            model_id=802,
            scale_factor_point="AMax_SF",
        )
        self.achamax_field = self.bat.fields["battery.battery.AChaMax"]
        self.achamax_field.access = "RW"

    def tearDown(self):
        clear_custom_bounds_cache()

    def test_normalize_bounds(self):
        # Dict formats
        self.assertEqual(
            normalize_bounds({"min": 0, "max": 35}),
            {"min_value": 0.0, "max_value": 35.0, "step": None},
        )
        self.assertEqual(
            normalize_bounds({"min_value": 5, "max_value": 30, "step": 0.5}),
            {"min_value": 5.0, "max_value": 30.0, "step": 0.5},
        )

        # List / tuple formats
        self.assertEqual(
            normalize_bounds([0, 35]),
            {"min_value": 0.0, "max_value": 35.0, "step": None},
        )
        self.assertEqual(
            normalize_bounds((0, 35, 0.1)),
            {"min_value": 0.0, "max_value": 35.0, "step": 0.1},
        )

        # Scalar
        self.assertEqual(
            normalize_bounds(35),
            {"min_value": None, "max_value": 35.0, "step": None},
        )

        # Invalid
        self.assertIsNone(normalize_bounds(None))
        self.assertIsNone(normalize_bounds({}))

    def test_get_custom_bounds_matching(self):
        test_bounds = {
            "battery.battery.AChaMax": {"min_value": 0.0, "max_value": 35.0, "step": None},
            "000100082128:SoCMax": {"min_value": 50.0, "max_value": 90.0, "step": 1.0},
        }

        # Exact match
        res = get_custom_bounds("battery.battery.AChaMax", custom_bounds_dict=test_bounds)
        self.assertIsNotNone(res)
        self.assertEqual(res["min_value"], 0.0)
        self.assertEqual(res["max_value"], 35.0)

        # Serial-specific match
        res_soc = get_custom_bounds("battery.battery.SoCMax", device_sn="000100082128", point_name="SoCMax", custom_bounds_dict=test_bounds)
        self.assertIsNotNone(res_soc)
        self.assertEqual(res_soc["min_value"], 50.0)
        self.assertEqual(res_soc["max_value"], 90.0)

        # Fallback by point name
        res_pt = get_custom_bounds("battery.model_802.AChaMax", point_name="AChaMax", custom_bounds_dict=test_bounds)
        self.assertIsNotNone(res_pt)
        self.assertEqual(res_pt["max_value"], 35.0)

    def test_state_field_get_bounds_with_custom_bounds(self):
        # AChaMax has AMax_SF = -2, default uint16 is 0..655.35 A
        # With default custom_bounds in ha_default_config.yaml: 0..35 A
        bounds = self.achamax_field.get_bounds(sf_value=-2)
        self.assertEqual(bounds["min_value"], 0.0)
        self.assertEqual(bounds["max_value"], 35.0)
        self.assertEqual(bounds["raw_min"], 0)
        self.assertEqual(bounds["raw_max"], 3500)
        self.assertEqual(bounds["step"], 0.01)
        self.assertTrue(bounds["is_custom"])
        self.assertIn("custom bounds", bounds["description"])

    def test_ha_discovery_payload_with_custom_bounds(self):
        payload = generate_discovery_payload(
            self.achamax_field,
            self.bat,
            gateway_device=self.bat,
        )
        self.assertEqual(payload["platform"], "number")
        self.assertEqual(payload["payload"]["min"], 0.0)
        self.assertEqual(payload["payload"]["max"], 35.0)
        self.assertEqual(payload["payload"]["step"], 0.01)

    def test_proxy_write_validation_enforces_bounds(self):
        controls = ControlDispatcher(modbus_client=None, state_store=self.state, catalog=self.catalog)

        # Above custom max (35)
        with self.assertRaises(ValueError) as ctx:
            controls.write_field("battery.battery.AChaMax", 40.0)
        self.assertIn("exceeds custom maximum bound 35", str(ctx.exception))

        # Below custom min (0)
        with self.assertRaises(ValueError) as ctx:
            controls.write_field("battery.battery.AChaMax", -5.0)
        self.assertIn("below custom minimum bound 0", str(ctx.exception))

        # Valid value (30)
        res = controls.write_field("battery.battery.AChaMax", 30.0)
        self.assertEqual(res, 30.0)

    def test_compound_field_bounds_override(self):
        cv = CompoundFieldView(
            id="battery_charge_limit",
            concept_key="battery_charge_limit",
            device_sn="000100082128",
            device_type="battery",
            name="battery_charge_limit",
            label="Charge Limit",
            description="Battery Charge Limit",
            is_writable=True,
            units="A",
            bounds={"min_value": 0.0, "max_value": 655.35, "step": 0.01},
        )
        test_bounds = {"battery_charge_limit": {"min_value": 0.0, "max_value": 32.0, "step": 0.5}}
        from unittest.mock import patch
        with patch("pwrcell.bounds.load_custom_bounds", return_value=test_bounds):
            b = cv.get_bounds()
            self.assertIsNotNone(b)
            self.assertEqual(b["max_value"], 32.0)
            self.assertEqual(b["step"], 0.5)


if __name__ == "__main__":
    unittest.main()
