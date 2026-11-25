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
                "inverter.*.ZExp",
                "inverter.*.ZExpLim",
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
        self.assertEqual(len(patterns), 8)
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
        self.assertTrue(is_mutation_blocked("inverter.model_64208.ZExp", config_path=self.config_path))
        self.assertTrue(is_mutation_blocked("inverter.model_64208.ZExpLim", config_path=self.config_path))

        # Serial number prefix stripping
        self.assertTrue(is_mutation_blocked("000100070008:inverter.inverter.VNom", config_path=self.config_path))

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
            device_sn="000100070008",
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
            device_sn="000100070008",
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
        dev = state.register_device(serial_number="000100070008", slave_id=8, device_type="inverter", model_name="Inverter")

        state.set_field(
            device_sn="000100070008",
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
            device_sn="000100070008",
            device_type="inverter",
            model_name="EIconfig",
            access="RW",
        )
        self.assertFalse(is_ha_writable_allowed(field_blocked))

    def test_get_blocked_mutation_fields_audit(self):
        catalog = get_catalog()
        state = StateStore(catalog=catalog)
        state.register_device(serial_number="000100070008", slave_id=8, device_type="inverter", model_name="Inverter")
        state.set_field(
            device_sn="000100070008",
            name="IslandEna",
            label="Enable Islanding",
            description="",
            value=1,
            raw_value=1,
            access="RW",
            sub_group="EIconfig",
        )
        state.set_field(
            device_sn="000100070008",
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
        self.assertEqual(info["patterns_count"], 8)
        self.assertEqual(info["blocked_count"], 1)
        self.assertEqual(info["blocked_fields"][0]["name"], "IslandEna")
        self.assertIn("manually edit config/blocked_fields.yaml", info["unblock_instruction"])

    def test_protected_rw_enum_and_numeric_export_as_readonly_sensors(self):
        """Issue #35: Protected RW fields with catalog ha_hint must export as read-only sensors."""
        from unittest.mock import patch
        from pwrcell.catalog import HomeAssistantHint
        from pwrcell.ha import generate_discovery_payload
        from pwrcell.state import FieldSource

        catalog = get_catalog()
        state = StateStore(catalog=catalog)
        bat = state.register_device(
            serial_number="000100080009",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )
        inv = state.register_device(
            serial_number="000100070008",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
        )

        with patch("pwrcell.safety.get_blocked_fields_path", return_value=self.config_path):
            clear_blocked_fields_cache()

            # 1. Protected RW enum from catalog (SetInvState in Model 802)
            state.update_from_modbus_points(
                serial_number="000100080009",
                model_id=802,
                raw_values={"SetInvState": 1},
                computed_values={"SetInvState": 1},
            )
            set_inv_field = bat.fields.get("battery.battery.SetInvState")
            self.assertIsNotNone(set_inv_field)
            self.assertEqual(set_inv_field.access, "RW")
            self.assertTrue(set_inv_field.is_mutation_blocked)
            self.assertFalse(set_inv_field.is_writable)
            self.assertEqual(set_inv_field.ha_hint.platform, "select")

            disc_enum = generate_discovery_payload(set_inv_field, bat)
            self.assertEqual(disc_enum["platform"], "sensor")
            self.assertIn("/sensor/", disc_enum["config_topic"])
            self.assertIsNone(disc_enum["command_topic"])
            self.assertNotIn("command_topic", disc_enum["payload"])
            self.assertNotIn("options", disc_enum["payload"])
            self.assertEqual(disc_enum["payload"].get("entity_category"), "diagnostic")
            self.assertIn(
                "homeassistant/select/pwrcell_000100080009/battery_setinvstate/config",
                disc_enum["legacy_config_topics"],
            )

            # 2. Protected RW numeric with catalog-style number ha_hint (VNom on inverter)
            vnom_hint = HomeAssistantHint(
                platform="number",
                device_class="voltage",
                unit_of_measurement="V",
                entity_category="config",
                min_value=0.0,
                max_value=500.0,
                step=1.0,
            )
            state.set_field(
                device_sn="000100070008",
                name="VNom",
                label="Nominal Voltage",
                description="Nominal AC voltage",
                value=240.0,
                raw_value=240,
                units="V",
                source=FieldSource.MODBUS_POLL,
                access="RW",
                point_type="uint16",
                ha_hint=vnom_hint,
                sub_group="inverter",
                model_id=121,
            )
            vnom_field = inv.fields["inverter.inverter.VNom"]
            self.assertTrue(vnom_field.is_mutation_blocked)
            self.assertFalse(vnom_field.is_writable)

            disc_num = generate_discovery_payload(vnom_field, inv)
            self.assertEqual(disc_num["platform"], "sensor")
            self.assertIn("/sensor/", disc_num["config_topic"])
            self.assertIsNone(disc_num["command_topic"])
            for forbidden_key in ("command_topic", "min", "max", "step", "mode"):
                self.assertNotIn(forbidden_key, disc_num["payload"])
            self.assertEqual(disc_num["payload"].get("device_class"), "voltage")
            self.assertEqual(disc_num["payload"].get("unit_of_measurement"), "V")
            self.assertEqual(disc_num["payload"].get("entity_category"), "diagnostic")
            self.assertIn(
                "homeassistant/number/pwrcell_000100070008/inverter_vnom/config",
                disc_num["legacy_config_topics"],
            )

    def test_dynamic_block_unblock_and_serialized_metadata(self):
        """Blocking/unblocking in blocked_fields.yaml switches HA discovery, StateField, ConceptView, and UnifiedFieldGroup."""
        from unittest.mock import patch
        from pwrcell.ha import generate_discovery_payload
        from pwrcell.state import FieldSource

        catalog = get_catalog()
        state = StateStore(catalog=catalog)
        bat = state.register_device(
            serial_number="000100080009",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )
        beacon = state.register_device(
            serial_number="000100120001",
            slave_id=1,
            device_type="rebus_beacon",
            model_name="PWRcell Beacon",
        )
        inv = state.register_device(
            serial_number="000100070008",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
        )

        state.update_from_modbus_points(
            serial_number="000100080009",
            model_id=802,
            raw_values={"SoCMax": 950, "SoC_SF": -1},
            computed_values={"SoCMax": 95.0, "SoC_SF": -1},
        )
        state.update_from_modbus_points(
            serial_number="000100120001",
            model_id=64200,
            raw_values={"SysMd": 1},
            computed_values={"SysMd": "GRID_TIE"},
        )
        state.set_field(
            device_sn="000100070008",
            name="system_mode",
            sub_group="live",
            value="SELF_SUPPLY",
            raw_value=3,
            source=FieldSource.MQTT_PUSH,
        )

        # Write a temporary blocked_fields.yaml that blocks SoCMax, SysMd, and system_mode
        blocked_cfg = Path(self.temp_dir.name) / "dynamic_blocked.yaml"
        with open(blocked_cfg, "w", encoding="utf-8") as f:
            yaml.dump({"blocked_fields": ["battery.*.SoCMax", "*.SysMd", "*system_mode*"]}, f)

        with patch("pwrcell.safety.get_blocked_fields_path", return_value=blocked_cfg):
            clear_blocked_fields_cache()

            soc_f = bat.fields["battery.battery.SoCMax"]
            sysmd_f = beacon.fields["rebus_beacon.REbus_dir.SysMd"]
            c_sys = state.get_compound_view("system_mode", inv.serial_number)

            # Discovery downgrades all three to read-only sensor + diagnostic
            disc_soc = generate_discovery_payload(soc_f, bat)
            self.assertEqual(disc_soc["platform"], "sensor")
            self.assertIsNone(disc_soc["command_topic"])
            self.assertEqual(disc_soc["payload"].get("entity_category"), "diagnostic")
            self.assertNotIn("min", disc_soc["payload"])

            disc_sysmd = generate_discovery_payload(sysmd_f, beacon)
            self.assertEqual(disc_sysmd["platform"], "sensor")
            self.assertIsNone(disc_sysmd["command_topic"])
            self.assertNotIn("options", disc_sysmd["payload"])
            self.assertEqual(disc_sysmd["payload"].get("entity_category"), "diagnostic")

            disc_comp = generate_discovery_payload(c_sys, inv)
            self.assertEqual(disc_comp["platform"], "sensor")
            self.assertIsNone(disc_comp["command_topic"])
            self.assertNotIn("options", disc_comp["payload"])
            self.assertNotIn("entity_category", disc_comp["payload"])

            # Explicit primary override still honored; config override coerced to diagnostic
            disc_primary = generate_discovery_payload(
                soc_f, bat, category_overrides={f"{bat.serial_number}:battery.battery.SoCMax": "primary"}
            )
            self.assertNotIn("entity_category", disc_primary["payload"])
            disc_cfg = generate_discovery_payload(
                soc_f, bat, category_overrides={f"{bat.serial_number}:battery.battery.SoCMax": "config"}
            )
            self.assertEqual(disc_cfg["payload"].get("entity_category"), "diagnostic")

            # Serialized API payloads (StateField, ConceptView, UnifiedFieldGroup) all align
            soc_dict = soc_f.to_dict()
            self.assertEqual(soc_dict["ha_platform"], "sensor")
            self.assertEqual(soc_dict["ha_category"], "diagnostic")
            self.assertIsNone(soc_dict["ha_options"])

            sysmd_dict = sysmd_f.to_dict()
            self.assertEqual(sysmd_dict["ha_platform"], "sensor")
            self.assertEqual(sysmd_dict["ha_category"], "diagnostic")
            self.assertIsNone(sysmd_dict["ha_options"])
            self.assertTrue(sysmd_dict["symbols"])  # symbols preserved for Web UI display

            c_dict = c_sys.to_dict()
            self.assertEqual(c_dict["ha_platform"], "sensor")
            self.assertIsNone(c_dict["ha_category"])
            self.assertFalse(c_dict["is_writable"])

            bat_groups = state.get_unified_fields(bat.serial_number)
            soc_grp = next((g for g in bat_groups if g.name == "SoCMax" or g.concept_key == "socmax_802"), None)
            self.assertIsNotNone(soc_grp)
            self.assertEqual(soc_grp.ha_platform, "sensor")
            self.assertEqual(soc_grp.ha_category, "diagnostic")
            self.assertIsNone(soc_grp.ha_options)

            # Unblock all fields on disk -> immediately reverts to interactive controls
            with open(blocked_cfg, "w", encoding="utf-8") as f:
                yaml.dump({"blocked_fields": []}, f)
            clear_blocked_fields_cache()

            disc_soc_unblocked = generate_discovery_payload(soc_f, bat)
            self.assertEqual(disc_soc_unblocked["platform"], "number")
            self.assertIsNotNone(disc_soc_unblocked["command_topic"])
            self.assertEqual(disc_soc_unblocked["payload"].get("entity_category"), "config")
            self.assertIsNotNone(disc_soc_unblocked["old_sensor_topic"])

            disc_sysmd_unblocked = generate_discovery_payload(sysmd_f, beacon)
            self.assertEqual(disc_sysmd_unblocked["platform"], "select")
            self.assertIsNotNone(disc_sysmd_unblocked["command_topic"])
            self.assertEqual(disc_sysmd_unblocked["payload"].get("entity_category"), "config")
            self.assertIn("options", disc_sysmd_unblocked["payload"])


if __name__ == "__main__":
    unittest.main()
