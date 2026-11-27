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

    def test_all_mock_rw_fields_ha_writability_matches_blocked_policy(self):
        """Every mock RW field's HA writability must match blocked_fields.yaml and data-type safety rules."""
        from pwrcell.client import create_client
        from pwrcell.ha import NON_INTERACTIVE_HA_POINT_TYPES, generate_discovery_payload

        clear_blocked_fields_cache()
        found_keys = {}

        with create_client(mock=True) as client:
            for dev in client.state.get_devices_snapshot():
                for f_key, f in list(dev.fields.items()):
                    if f.access != "RW":
                        continue
                    found_keys.setdefault(f_key, (f, dev))
                    disc = generate_discovery_payload(f, dev)
                    f_dict = f.to_dict()
                    pt_type = (f.point_type or "").strip().lower()

                    if f.is_mutation_blocked:
                        self.assertFalse(f.is_writable, f"Blocked field {f_key} must have is_writable=False")
                        self.assertFalse(is_ha_writable_allowed(f), f"Blocked field {f_key} must not be HA-writable")
                        self.assertEqual(disc["platform"], "sensor", f"Blocked field {f_key} must export as sensor")
                        self.assertIsNone(disc["command_topic"], f"Blocked field {f_key} must have no command_topic")
                        self.assertNotIn("command_topic", disc["payload"])
                        self.assertNotEqual(disc["payload"].get("entity_category"), "config")
                        self.assertEqual(f_dict["ha_platform"], "sensor")
                    elif (
                        f.is_bitfield
                        or pt_type.startswith("bitfield")
                        or pt_type in NON_INTERACTIVE_HA_POINT_TYPES
                        or f.is_scale_factor
                    ):
                        self.assertFalse(
                            is_ha_writable_allowed(f),
                            f"Non-interactive RW type {f_key} ({pt_type}) must not be HA-writable",
                        )
                        self.assertEqual(disc["platform"], "sensor")
                        self.assertIsNone(disc["command_topic"])
                        self.assertNotIn("command_topic", disc["payload"])
                        self.assertEqual(f_dict["ha_platform"], "sensor")
                    else:
                        self.assertTrue(f.is_writable, f"Unblocked RW field {f_key} must have is_writable=True")
                        self.assertTrue(
                            is_ha_writable_allowed(f),
                            f"Unblocked RW field {f_key} must be HA-writable",
                        )
                        self.assertIn(
                            disc["platform"],
                            ("select", "number"),
                            f"Unblocked RW field {f_key} must export as select or number",
                        )
                        self.assertIsNotNone(disc["command_topic"], f"Unblocked RW field {f_key} needs command_topic")
                        self.assertEqual(disc["payload"].get("command_topic"), disc["command_topic"])
                        self.assertEqual(f_dict["ha_platform"], disc["platform"])

            # User-reported device enable/connect controls must be unblocked & exported as select controls
            for expected_select in (
                "inverter.EIconfig.Conn",
                "inverter.controls.Conn",
                "pv_link.pvlink_status.Ena",
                "battery.lithium_ion_string.SetEna",
                "battery.lithium_ion_string.SetCon",
                "battery.battery.SetOp",
                "rebus_beacon.REbus_dir.devices.1.Ena",
            ):
                self.assertIn(expected_select, found_keys, f"Expected mock field {expected_select} missing")
                f_obj, dev_obj = found_keys[expected_select]
                self.assertFalse(f_obj.is_mutation_blocked, f"{expected_select} must not be mutation blocked")
                self.assertTrue(is_ha_writable_allowed(f_obj), f"{expected_select} must be HA-writable")
                disc = generate_discovery_payload(f_obj, dev_obj)
                self.assertEqual(disc["platform"], "select", f"{expected_select} must export as select")
                self.assertIsNotNone(disc["command_topic"])

            # Newly hardened hazardous/internal RW fields must be blocked & read-only sensors
            for expected_blocked in (
                "inverter.SA_defaults.SRD",
                "inverter.volt_var.ActCrv",
                "pv_link.flash_reader.cmd",
                "pv_link.pvrss_config.EnablePVRSS",
                "pv_link.pvlink_status.AMax",
                "rebus_beacon.REbus_dir.Clr",
                "rebus_beacon.common.DA",
                "inverter.EIconfig.Pwd",
            ):
                self.assertIn(expected_blocked, found_keys, f"Expected mock field {expected_blocked} missing")
                f_obj, dev_obj = found_keys[expected_blocked]
                self.assertTrue(f_obj.is_mutation_blocked, f"{expected_blocked} must be mutation blocked")
                self.assertFalse(is_ha_writable_allowed(f_obj), f"{expected_blocked} must not be HA-writable")
                disc = generate_discovery_payload(f_obj, dev_obj)
                self.assertEqual(disc["platform"], "sensor", f"{expected_blocked} must export as sensor")
                self.assertIsNone(disc["command_topic"])

    def test_unblocking_default_protected_field_enables_ha_control(self):
        """Unblocking a non-allowlisted protected field in blocked_fields.yaml must immediately expose it in HA."""
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

        state.update_from_modbus_points(
            serial_number="000100080009",
            model_id=802,
            raw_values={"SetInvState": 1},
            computed_values={"SetInvState": 1},
        )
        state.set_field(
            device_sn="000100070008",
            name="ZExp",
            label="Export Limiting",
            description="Zero export mode",
            value="DISABLED",
            raw_value=0,
            source=FieldSource.MODBUS_POLL,
            access="RW",
            point_type="enum16",
            is_enum=True,
            symbols=[{"name": "DISABLED", "value": 0}, {"name": "ENABLED", "value": 1}],
            ha_hint=HomeAssistantHint(
                platform="select",
                entity_category="config",
                options=["DISABLED", "ENABLED"],
            ),
            sub_group="EIconfig",
            model_id=64208,
        )

        temp_blocked = Path(self.temp_dir.name) / "custom_blocked.yaml"
        with open(temp_blocked, "w", encoding="utf-8") as f:
            yaml.dump({"blocked_fields": ["inverter.*.ZExp", "battery.*.SetInvState"]}, f)

        with patch("pwrcell.safety.get_blocked_fields_path", return_value=temp_blocked):
            clear_blocked_fields_cache()
            zexp_f = inv.fields["inverter.EIconfig.ZExp"]
            set_inv_f = bat.fields["battery.battery.SetInvState"]

            for fld, dev in ((zexp_f, inv), (set_inv_f, bat)):
                self.assertFalse(is_ha_writable_allowed(fld))
                disc = generate_discovery_payload(fld, dev)
                self.assertEqual(disc["platform"], "sensor")
                self.assertIsNone(disc["command_topic"])
                self.assertEqual(disc["payload"].get("entity_category"), "diagnostic")

            # Remove both from blocked_fields.yaml -> both immediately become writable select controls
            with open(temp_blocked, "w", encoding="utf-8") as f:
                yaml.dump({"blocked_fields": []}, f)
            clear_blocked_fields_cache()

            for fld, dev in ((zexp_f, inv), (set_inv_f, bat)):
                self.assertTrue(is_ha_writable_allowed(fld))
                disc = generate_discovery_payload(fld, dev)
                self.assertEqual(disc["platform"], "select")
                self.assertIsNotNone(disc["command_topic"])
                self.assertTrue(disc["payload"].get("options"))
                self.assertEqual(disc["payload"].get("entity_category"), "config")
                self.assertIsNotNone(disc["old_sensor_topic"])

    def test_positive_and_negative_overrides_precedence_and_ha_discovery(self):
        """Positive (blocked_fields) and negative (unblocked_fields) overrides layer over defaults with unblock precedence."""
        from unittest.mock import patch
        from pwrcell.catalog import HomeAssistantHint
        from pwrcell.ha import generate_discovery_payload
        from pwrcell.state import FieldSource

        catalog = get_catalog()
        state = StateStore(catalog=catalog)
        inv = state.register_device(
            serial_number="000100070008",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
        )
        pv1 = state.register_device(
            serial_number="000100030003",
            slave_id=3,
            device_type="pv_link",
            model_name="PV Link",
        )
        pv2 = state.register_device(
            serial_number="000100030004",
            slave_id=4,
            device_type="pv_link",
            model_name="PV Link",
        )
        trip_sn_bat = state.register_device(
            serial_number="SN_TRIP_01",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )

        # Register fields: ZExp (default blocked), PV Link Ena on two serials, REbus_arb.Conn & PQSet_Ena, and SoCMax on SN_TRIP_01
        state.set_field(
            device_sn="000100070008",
            name="ZExp",
            label="Export Limiting",
            value="DISABLED",
            raw_value=0,
            source=FieldSource.MODBUS_POLL,
            access="RW",
            point_type="enum16",
            is_enum=True,
            symbols=[{"name": "DISABLED", "value": 0}, {"name": "ENABLED", "value": 1}],
            ha_hint=HomeAssistantHint(platform="select", entity_category="config", options=["DISABLED", "ENABLED"]),
            sub_group="EIconfig",
            model_id=64208,
        )
        for name, label, val, opts in (
            ("Conn", "Connect", "CONNECT", ["DISCONNECT", "CONNECT"]),
            ("PQSet_Ena", "Enable arbitrage control", "DISABLE", ["DISABLE", "ENABLE"]),
        ):
            state.set_field(
                device_sn="000100070008",
                name=name,
                label=label,
                value=val,
                raw_value=1,
                source=FieldSource.MODBUS_POLL,
                access="RW",
                point_type="enum16",
                is_enum=True,
                symbols=[{"name": o, "value": idx} for idx, o in enumerate(opts)],
                ha_hint=HomeAssistantHint(platform="select", entity_category="config", options=opts),
                sub_group="REbus_arb",
                model_id=64204,
            )
        for pv_sn in ("000100030003", "000100030004"):
            state.set_field(
                device_sn=pv_sn,
                name="Ena",
                label="Enable or Disable PV Link",
                value="ENABLE",
                raw_value=1,
                source=FieldSource.MODBUS_POLL,
                access="RW",
                point_type="enum16",
                is_enum=True,
                symbols=[{"name": "DISABLE", "value": 0}, {"name": "ENABLE", "value": 1}],
                ha_hint=HomeAssistantHint(platform="select", entity_category="config", options=["DISABLE", "ENABLE"]),
                sub_group="pvlink_status",
                model_id=64251,
            )
        state.update_from_modbus_points(
            serial_number="SN_TRIP_01",
            model_id=802,
            raw_values={"SoCMax": 950, "SoC_SF": -1},
            computed_values={"SoCMax": 95.0, "SoC_SF": -1},
        )

        ov_path = Path(self.temp_dir.name) / "pwrcell.yaml"
        with open(ov_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "blocked_fields": [
                        "000100030004:pv_link.pvlink_status.Ena",
                        "inverter.REbus_arb.*",
                    ],
                    "unblocked_fields": [
                        "inverter.EIconfig.ZExp",
                        "inverter.REbus_arb.Conn",
                    ],
                },
                f,
            )

        with patch("pwrcell.safety.get_safety_overrides_path", return_value=ov_path):
            clear_blocked_fields_cache()
            controls = ControlDispatcher(modbus_client=None, state_store=state, catalog=catalog)

            zexp_f = inv.fields["inverter.EIconfig.ZExp"]
            arb_conn_f = inv.fields["inverter.REbus_arb.Conn"]
            arb_pq_f = inv.fields["inverter.REbus_arb.PQSet_Ena"]
            pv1_ena_f = pv1.fields["pv_link.pvlink_status.Ena"]
            pv2_ena_f = pv2.fields["pv_link.pvlink_status.Ena"]
            trip_soc_f = trip_sn_bat.fields["battery.battery.SoCMax"]

            # 1. Negative override unblocks default-protected inverter.EIconfig.ZExp
            self.assertFalse(zexp_f.is_mutation_blocked)
            self.assertTrue(is_ha_writable_allowed(zexp_f))
            disc_zexp = generate_discovery_payload(zexp_f, inv)
            self.assertEqual(disc_zexp["platform"], "select")
            self.assertIsNotNone(disc_zexp["command_topic"])
            self.assertEqual(controls.write_field("inverter.EIconfig.ZExp", "ENABLED", device_sn="000100070008"), "ENABLED")

            # 2. Broad block + narrow unblock: REbus_arb.PQSet_Ena blocked, REbus_arb.Conn allowed
            self.assertTrue(arb_pq_f.is_mutation_blocked)
            self.assertFalse(is_ha_writable_allowed(arb_pq_f))
            self.assertEqual(generate_discovery_payload(arb_pq_f, inv)["platform"], "sensor")
            with self.assertRaises(PermissionError):
                controls.write_field("inverter.REbus_arb.PQSet_Ena", "ENABLE", device_sn="000100070008")

            self.assertFalse(arb_conn_f.is_mutation_blocked)
            self.assertTrue(is_ha_writable_allowed(arb_conn_f))
            self.assertEqual(generate_discovery_payload(arb_conn_f, inv)["platform"], "select")

            # 3. Serial-scoped positive override blocks 000100030004 only; sibling 000100030003 stays writable
            self.assertTrue(pv2_ena_f.is_mutation_blocked)
            self.assertFalse(is_ha_writable_allowed(pv2_ena_f))
            self.assertEqual(generate_discovery_payload(pv2_ena_f, pv2)["platform"], "sensor")
            with self.assertRaises(PermissionError):
                controls.write_field("pv_link.pvlink_status.Ena", "DISABLE", device_sn="000100030004")

            self.assertFalse(pv1_ena_f.is_mutation_blocked)
            self.assertTrue(is_ha_writable_allowed(pv1_ena_f))
            self.assertEqual(generate_discovery_payload(pv1_ena_f, pv1)["platform"], "select")

            # 4. Plain *Trip* rule must not match serial number "SN_TRIP_01"
            self.assertFalse(trip_soc_f.is_mutation_blocked)
            self.assertTrue(is_ha_writable_allowed(trip_soc_f))

            # 5. Audit payload reports both blocked items and overridden/unblocked items
            audit = get_blocked_mutation_fields(state)
            self.assertEqual(audit["extra_blocked_patterns"], [
                "000100030004:pv_link.pvlink_status.Ena",
                "inverter.REbus_arb.*",
            ])
            self.assertEqual(audit["unblocked_patterns"], [
                "inverter.EIconfig.ZExp",
                "inverter.REbus_arb.Conn",
            ])
            unblocked_keys = {it["key"] for it in audit["unblocked_fields"]}
            self.assertEqual(unblocked_keys, {"inverter.EIconfig.ZExp", "inverter.REbus_arb.Conn"})
            blocked_by_sn = {(it["device_sn"], it["key"]): it for it in audit["blocked_fields"]}
            self.assertIn(("000100030004", "pv_link.pvlink_status.Ena"), blocked_by_sn)
            self.assertEqual(blocked_by_sn[("000100030004", "pv_link.pvlink_status.Ena")]["source"], "override")
            self.assertNotIn(("000100030003", "pv_link.pvlink_status.Ena"), blocked_by_sn)

        # 6. Also verify PWRCELL_CONFIG env var picks up overrides without patching get_safety_overrides_path
        old_env = os.environ.get("PWRCELL_CONFIG")
        os.environ["PWRCELL_CONFIG"] = str(ov_path)
        try:
            clear_blocked_fields_cache()
            self.assertFalse(is_mutation_blocked("inverter.EIconfig.ZExp"))
            self.assertTrue(is_mutation_blocked("pv_link.pvlink_status.Ena", device_sn="000100030004"))
            self.assertFalse(is_mutation_blocked("pv_link.pvlink_status.Ena", device_sn="000100030003"))
        finally:
            if old_env is None:
                os.environ.pop("PWRCELL_CONFIG", None)
            else:
                os.environ["PWRCELL_CONFIG"] = old_env
            clear_blocked_fields_cache()


if __name__ == "__main__":
    unittest.main()
