import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from pwrcell.catalog import get_catalog
from pwrcell.controls import ControlDispatcher
from pwrcell.ha import is_ha_writable_allowed
from pwrcell.safety import (
    clear_blocked_fields_cache,
    get_blocked_mutation_fields,
    get_matched_blocked_pattern,
    is_mutation_blocked,
    load_blocked_fields,
)
from pwrcell.state import StateField, StateStore


class TestSafetyBlockedFields(unittest.TestCase):
    def setUp(self):
        clear_blocked_fields_cache()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "blocked_fields.yaml"
        self.sample_config = {
            "blocked_fields": [
                "*.ReConn*",
                "*.IslandEna",
                "*Trip*",
                "inverter.*.VNom",
                "inverter.*.AMax",
                "battery.*.SetInvState",
            ]
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.sample_config, f)

    def tearDown(self):
        self.temp_dir.cleanup()
        clear_blocked_fields_cache()

    def test_load_blocked_fields(self):
        patterns = load_blocked_fields(self.config_path)
        self.assertEqual(len(patterns), 6)
        self.assertIn("*.IslandEna", patterns)
        self.assertIn("*Trip*", patterns)

    def test_pattern_matching(self):
        # Exact point name matching
        self.assertTrue(is_mutation_blocked("IslandEna", config_path=self.config_path))
        self.assertEqual(get_matched_blocked_pattern("IslandEna", config_path=self.config_path), "*.IslandEna")

        # Wildcard matching
        self.assertTrue(is_mutation_blocked("inverter.model_121.ReConnMaxHz", config_path=self.config_path))
        self.assertTrue(is_mutation_blocked("VArTrip", config_path=self.config_path))
        self.assertTrue(is_mutation_blocked("inverter.inverter.VNom", config_path=self.config_path))
        self.assertTrue(is_mutation_blocked("battery.battery.SetInvState", config_path=self.config_path))

        # Serial number prefix stripping
        self.assertTrue(is_mutation_blocked("0001000714E9:inverter.inverter.VNom", config_path=self.config_path))

        # Safe writable fields should NOT be blocked
        self.assertFalse(is_mutation_blocked("SysMd", config_path=self.config_path))
        self.assertFalse(is_mutation_blocked("system_mode", config_path=self.config_path))
        self.assertFalse(is_mutation_blocked("battery.battery.SoCMax", config_path=self.config_path))
        self.assertFalse(is_mutation_blocked("battery.battery.AChaMax", config_path=self.config_path))

    def test_field_object_matching(self):
        field_blocked = StateField(
            name="IslandEna",
            label="Enable Islanding",
            description="",
            value=1,
            raw_value=1,
            key="inverter.EIconfig.IslandEna",
            device_sn="0001000714E9",
            device_type="inverter",
            model_name="EIconfig",
            access="RW",
        )
        self.assertTrue(is_mutation_blocked(field_blocked, config_path=self.config_path))
        self.assertTrue(field_blocked.is_mutation_blocked)
        self.assertFalse(field_blocked.is_writable)  # is_writable becomes False when mutation is blocked!

        field_safe = StateField(
            name="SoCMax",
            label="Max State of Charge",
            description="",
            value=100,
            raw_value=100,
            key="battery.battery.SoCMax",
            device_sn="0001000714E9",
            device_type="battery",
            model_name="battery",
            access="RW",
        )
        self.assertFalse(is_mutation_blocked(field_safe, config_path=self.config_path))
        self.assertFalse(field_safe.is_mutation_blocked)
        self.assertTrue(field_safe.is_writable)

    def test_controls_write_field_rejection(self):
        catalog = get_catalog()
        state = StateStore(catalog=catalog)
        dev = state.register_device(serial_number="0001000714E9", slave_id=8, device_type="inverter", model_name="Inverter")

        state.set_field(
            device_sn="0001000714E9",
            name="IslandEna",
            label="Enable Islanding",
            description="",
            value=1,
            raw_value=1,
            access="RW",
            sub_group="EIconfig",
        )

        controls = ControlDispatcher(modbus_client=None, state_store=state, catalog=catalog)

        # Writing to safety-blocked field raises PermissionError
        with self.assertRaises(PermissionError) as ctx:
            controls.write_field("inverter.EIconfig.IslandEna", 0)
        self.assertIn("blocked from mutation by safety configuration", str(ctx.exception))
        self.assertIn("blocked_fields.yaml", str(ctx.exception))

    def test_ha_writable_allowed_blocks_safety_fields(self):
        field_blocked = StateField(
            name="IslandEna",
            label="Enable Islanding",
            description="",
            value=1,
            raw_value=1,
            key="inverter.EIconfig.IslandEna",
            device_sn="0001000714E9",
            device_type="inverter",
            model_name="EIconfig",
            access="RW",
        )
        self.assertFalse(is_ha_writable_allowed(field_blocked))

    def test_get_blocked_mutation_fields_audit(self):
        catalog = get_catalog()
        state = StateStore(catalog=catalog)
        state.register_device(serial_number="0001000714E9", slave_id=8, device_type="inverter", model_name="Inverter")
        state.set_field(
            device_sn="0001000714E9",
            name="IslandEna",
            label="Enable Islanding",
            description="",
            value=1,
            raw_value=1,
            access="RW",
            sub_group="EIconfig",
        )
        state.set_field(
            device_sn="0001000714E9",
            name="W",
            label="Active Power",
            description="",
            value=1500,
            raw_value=1500,
            access="R",
            sub_group="inverter",
        )

        info = get_blocked_mutation_fields(state, config_path=self.config_path)
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["patterns_count"], 6)
        self.assertEqual(info["blocked_count"], 1)
        self.assertEqual(info["blocked_fields"][0]["name"], "IslandEna")
        self.assertIn("manually edit config/blocked_fields.yaml", info["unblock_instruction"])


if __name__ == "__main__":
    unittest.main()
