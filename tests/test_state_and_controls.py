"""Unit tests for pwrcell.state and pwrcell.controls."""

import unittest
from pwrcell.catalog import get_catalog
from pwrcell.controls import ControlDispatcher
from pwrcell.fixtures import MockTelemetryGenerator
from pwrcell.mqtt import MqttClient
from pwrcell.state import FieldSource, StateStore


class TestStateAndControls(unittest.TestCase):

    def setUp(self):
        self.catalog = get_catalog()
        self.state = StateStore(catalog=self.catalog)
        self.controls = ControlDispatcher(modbus_client=None, state_store=self.state, catalog=self.catalog)

        # Register mock inverter and battery
        self.inv = self.state.register_device(
            serial_number="0001000714E9",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell X7602 Inverter",
        )
        self.bat = self.state.register_device(
            serial_number="000100082128",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )
        self.beacon = self.state.register_device(
            serial_number="0001001206E8",
            slave_id=1,
            device_type="rebus_beacon",
            model_name="REbus Beacon",
        )

    def test_telemetry_snapshot_updates_state(self):
        import pwrcell.fixtures as fix_mod
        if getattr(fix_mod, "energy_record_set_pb2", None) is None:
            self.skipTest("protobuf not installed")
        gen = MockTelemetryGenerator()
        rec_set = gen.tick(2.0)
        snapshot = MqttClient._parse_snapshot(rec_set)

        self.state.update_from_telemetry_snapshot(snapshot)

        # Check inverter fields
        grid_field = self.inv.fields.get("inverter.live.grid_power_w")
        self.assertIsNotNone(grid_field)
        self.assertEqual(grid_field.units, "W")
        self.assertEqual(grid_field.source, FieldSource.MQTT_PUSH)
        self.assertEqual(grid_field.ha_hint.device_class, "power")

        # Check battery fields
        soc_field = self.bat.fields.get("battery.live.state_of_charge")
        self.assertIsNotNone(soc_field)
        self.assertEqual(soc_field.units, "%")
        self.assertGreater(soc_field.value, 0)
        self.assertEqual(soc_field.ha_hint.device_class, "battery")

    def test_listener_called_on_change(self):
        changed_keys = []

        def on_change(field):
            changed_keys.append(field.key)

        self.state.subscribe(on_change)

        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="CT Power",
            description="Power measured by CT",
            value=-1500,
            raw_value=-1500,
            units="W",
        )

        self.assertIn("inverter.CTPow", changed_keys)

    def test_control_dispatcher_set_mode(self):
        mode_val = self.controls.set_system_mode("CLEAN_BACKUP")
        self.assertEqual(mode_val, 3)

        # Field should be updated on beacon in state store
        mode_field = self.beacon.fields.get("rebus_beacon.model_64200.SysMd")
        self.assertIsNotNone(mode_field)
        self.assertEqual(mode_field.value, "CLEAN_BACKUP")
        self.assertEqual(mode_field.raw_value, 3)
        self.assertTrue(mode_field.is_writable)

    def test_scale_factor_detection_and_serialization(self):
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"A": 3500, "A_SF": -2},
            computed_values={"A": 35.0, "A_SF": -2},
        )
        a_field = self.bat.fields.get("battery.battery.A")
        sf_field = self.bat.fields.get("battery.battery.A_SF")

        self.assertIsNotNone(a_field)
        self.assertIsNotNone(sf_field)
        self.assertFalse(a_field.is_scale_factor)
        self.assertTrue(sf_field.is_scale_factor)
        self.assertEqual(a_field.value, 35.0)

        # Check serialization in to_dict
        sf_dict = sf_field.to_dict()
        self.assertTrue(sf_dict["is_scale_factor"])
        self.assertIn("Scale Factor", sf_dict["label"])

    def test_enum_point_lookup_and_serialization(self):
        self.state.update_from_modbus_points(
            serial_number=self.beacon.serial_number,
            model_id=64200,
            raw_values={"SysMd": 4},
            computed_values={"SysMd": 4},
        )
        sysmd_field = self.beacon.fields.get("rebus_beacon.REbus_dir.SysMd")
        self.assertIsNotNone(sysmd_field)
        self.assertTrue(sysmd_field.is_enum)
        self.assertEqual(sysmd_field.point_type, "enum16")
        self.assertEqual(sysmd_field.raw_value, 4)
        self.assertEqual(sysmd_field.value, "PRIORITY_BACKUP")
        self.assertIsNotNone(sysmd_field.symbols)
        symbol_names = [s["name"] for s in sysmd_field.symbols]
        self.assertIn("PRIORITY_BACKUP", symbol_names)
        self.assertIn("SELF_SUPPLY", symbol_names)

        # Check to_dict serialization
        d = sysmd_field.to_dict()
        self.assertTrue(d["is_enum"])
        self.assertEqual(d["point_type"], "enum16")
        self.assertEqual(d["value"], "PRIORITY_BACKUP")
        self.assertEqual(d["raw_value"], 4)
        self.assertIsInstance(d["symbols"], list)

    def test_bitfield_point_lookup_and_serialization(self):
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=64209,
            raw_values={"EnableBits": 5135},
        )
        eb_field = self.bat.fields.get("battery.battery_status.EnableBits")
        self.assertIsNotNone(eb_field)
        self.assertTrue(eb_field.is_bitfield)
        self.assertFalse(eb_field.is_enum)
        self.assertEqual(eb_field.point_type, "bitfield16")
        self.assertEqual(eb_field.raw_value, 5135)
        self.assertEqual(eb_field.value, ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])
        self.assertTrue(eb_field.is_flag_set("DEADMAN"))
        self.assertFalse(eb_field.is_flag_set("INT_FAN"))

        # Check to_dict serialization
        d = eb_field.to_dict()
        self.assertTrue(d["is_bitfield"])
        self.assertFalse(d["is_enum"])
        self.assertEqual(d["point_type"], "bitfield16")
        self.assertEqual(d["value"], ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])
        self.assertEqual(d["raw_value"], 5135)
        self.assertIsInstance(d["bitmask_flags"], list)
        self.assertIsInstance(d["flags_dict"], dict)
        self.assertTrue(d["flags_dict"]["DEADMAN"])
        self.assertFalse(d["flags_dict"]["INT_FAN"])

    def test_control_dispatcher_write_field_enum(self):
        # Write by symbol name
        res = self.controls.write_field("rebus_beacon.REbus_dir.SysMd", "PRIORITY_BACKUP")
        self.assertEqual(res, "PRIORITY_BACKUP")
        field = self.beacon.fields.get("rebus_beacon.REbus_dir.SysMd")
        self.assertEqual(field.value, "PRIORITY_BACKUP")
        self.assertEqual(field.raw_value, 4)

        # Write by integer value
        res2 = self.controls.write_field("rebus_beacon.REbus_dir.SysMd", 2)
        self.assertEqual(res2, "SELF_SUPPLY")
        self.assertEqual(field.value, "SELF_SUPPLY")
        self.assertEqual(field.raw_value, 2)

        # Write case-insensitive
        res3 = self.controls.write_field("rebus_beacon.REbus_dir.SysMd", "clean_backup")
        self.assertEqual(res3, "CLEAN_BACKUP")
        self.assertEqual(field.value, "CLEAN_BACKUP")
        self.assertEqual(field.raw_value, 3)

        # Write generic non-SysMd SunSpec enum (battery model 802 SetOp: CONNECT (1), DISCONNECT (2))
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"SetOp": 1},
            computed_values={"SetOp": 1},
        )
        setop_res = self.controls.write_field("battery.battery.SetOp", "DISCONNECT")
        self.assertEqual(setop_res, "DISCONNECT")
        bat_setop = self.bat.fields.get("battery.battery.SetOp")
        self.assertEqual(bat_setop.value, "DISCONNECT")
        self.assertEqual(bat_setop.raw_value, 2)

    def test_control_dispatcher_write_field_restrictions(self):
        # Initialize fields on battery
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"SoCMax": 100, "A": 3500, "SetOp": 1},
            computed_values={"SoCMax": 100, "A": 35.0, "SetOp": 1},
        )

        # 1. Invalid enum symbol name
        with self.assertRaises(ValueError):
            self.controls.write_field("rebus_beacon.REbus_dir.SysMd", "NON_EXISTENT_MODE")

        with self.assertRaises(ValueError):
            self.controls.write_field("battery.battery.SetOp", "INVALID_OP")

        # 2. Invalid enum integer value
        with self.assertRaises(ValueError):
            self.controls.write_field("rebus_beacon.REbus_dir.SysMd", 999)

        with self.assertRaises(ValueError):
            self.controls.write_field("battery.battery.SetOp", 999)

        # 3. Numeric bounds restriction (uint16: 0 - 65535)
        with self.assertRaises(ValueError):
            self.controls.write_field("battery.battery.SoCMax", -10)

        with self.assertRaises(ValueError):
            self.controls.write_field("battery.battery.SoCMax", 70000)

        # 4. Read-only field restriction
        with self.assertRaises(PermissionError):
            self.controls.write_field("battery.battery.A", 50.0)


if __name__ == "__main__":
    unittest.main()

