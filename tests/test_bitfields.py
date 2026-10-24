"""Unit tests for bitfield / bitmask support in PWRcell."""

import unittest
from pwrcell.catalog import get_catalog
from pwrcell.controls import ControlDispatcher
from pwrcell.ha import generate_discovery_payload
from pwrcell.state import StateStore


class TestBitfieldSupport(unittest.TestCase):

    def setUp(self):
        self.catalog = get_catalog()
        self.state = StateStore(catalog=self.catalog)
        self.controls = ControlDispatcher(modbus_client=None, state_store=self.state, catalog=self.catalog)

        # Register a mock battery device
        self.battery = self.state.register_device(
            serial_number="000100082128",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )

    def test_catalog_point_def_bitfield_properties(self):
        # Model 64209 is battery_status
        model_64209 = self.catalog.get_model(64209)
        self.assertIsNotNone(model_64209)
        self.assertIn("EnableBits", model_64209.points)
        
        enable_bits = model_64209.points["EnableBits"]
        self.assertTrue(enable_bits.is_bitfield)
        self.assertFalse(enable_bits.is_enum)
        self.assertEqual(enable_bits.type, "bitfield16")
        self.assertGreaterEqual(len(enable_bits.symbols), 10)

        # Check symbol bit mappings
        sym_map = {s.name: s.value for s in enable_bits.symbols}
        self.assertEqual(sym_map["DEADMAN"], 0)
        self.assertEqual(sym_map["GATEDRIVE"], 1)
        self.assertEqual(sym_map["REBUS_CONNECT"], 2)
        self.assertEqual(sym_map["BATT_CONNECT"], 3)
        self.assertEqual(sym_map["AUTOMODE"], 10)
        self.assertEqual(sym_map["BMS"], 12)

        # Check symbols_by_bit
        self.assertEqual(enable_bits.symbols_by_bit[0].name, "DEADMAN")
        self.assertEqual(enable_bits.symbols_by_bit[12].name, "BMS")

    def test_decode_bitfield(self):
        enable_bits = self.catalog.get_point(64209, "EnableBits")
        self.assertIsNotNone(enable_bits)

        # Real dump value: 5135 = 1 + 2 + 4 + 8 + 1024 + 4096 (0x140F)
        decoded = enable_bits.decode_bitfield(5135)
        self.assertEqual(decoded, ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])

        # Zero value
        self.assertEqual(enable_bits.decode_bitfield(0), [])

        # Single bit
        self.assertEqual(enable_bits.decode_bitfield(1), ["DEADMAN"])
        self.assertEqual(enable_bits.decode_bitfield(4096), ["BMS"])

    def test_decode_bitfield_dict(self):
        enable_bits = self.catalog.get_point(64209, "EnableBits")
        flags_dict = enable_bits.decode_bitfield_dict(5135)
        self.assertTrue(flags_dict["DEADMAN"])
        self.assertTrue(flags_dict["GATEDRIVE"])
        self.assertTrue(flags_dict["REBUS_CONNECT"])
        self.assertTrue(flags_dict["BATT_CONNECT"])
        self.assertFalse(flags_dict["INT_FAN"])
        self.assertFalse(flags_dict["EXT_FAN"])
        self.assertTrue(flags_dict["AUTOMODE"])
        self.assertTrue(flags_dict["BMS"])
        self.assertFalse(flags_dict["USB_RCP"])

    def test_encode_bitfield(self):
        enable_bits = self.catalog.get_point(64209, "EnableBits")

        # Encode from list of symbol names
        mask = enable_bits.encode_bitfield(["DEADMAN", "BMS"])
        self.assertEqual(mask, 1 | 4096)  # 4097

        # Encode from comma-separated string
        self.assertEqual(enable_bits.encode_bitfield("DEADMAN, BMS"), 4097)
        self.assertEqual(enable_bits.encode_bitfield("DEADMAN BMS"), 4097)

        # Encode from int
        self.assertEqual(enable_bits.encode_bitfield(5135), 5135)

        # Invalid symbol raises ValueError
        with self.assertRaises(ValueError):
            enable_bits.encode_bitfield(["NON_EXISTENT_FLAG"])

    def test_validate_and_convert(self):
        enable_bits = self.catalog.get_point(64209, "EnableBits")

        # Read-only check
        with self.assertRaises(PermissionError):
            enable_bits.validate_and_convert(5135)

        # By integer with ignore_access
        raw_val, display_val = enable_bits.validate_and_convert(5135, ignore_access=True)
        self.assertEqual(raw_val, 5135)
        self.assertEqual(display_val, ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])

        # By list of symbols with ignore_access
        raw_val2, display_val2 = enable_bits.validate_and_convert(["DEADMAN", "BATT_CONNECT"], ignore_access=True)
        self.assertEqual(raw_val2, 1 | 8)  # 9
        self.assertEqual(display_val2, ["DEADMAN", "BATT_CONNECT"])

    def test_state_store_modbus_update_decodes_bitfield(self):
        # Ingest model 64209 with EnableBits=5135, ErrorWord=0, InhibitBits=0
        self.state.update_from_modbus_points(
            serial_number=self.battery.serial_number,
            model_id=64209,
            raw_values={
                "WhIn": 1593509,
                "WhOut": 1390925,
                "ErrorWord": 0,
                "EnableBits": 5135,
                "InhibitBits": 0,
            },
        )

        field = self.battery.fields.get("battery.battery_status.EnableBits")
        self.assertIsNotNone(field)
        self.assertTrue(field.is_bitfield)
        self.assertFalse(field.is_enum)
        self.assertEqual(field.raw_value, 5135)
        self.assertEqual(field.value, ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])
        self.assertEqual(field.active_flags, ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])

        # Test helper methods on StateField
        self.assertTrue(field.is_flag_set("DEADMAN"))
        self.assertTrue(field.is_flag_set("deadman"))  # case-insensitive
        self.assertTrue(field.is_flag_set("BMS"))
        self.assertFalse(field.is_flag_set("INT_FAN"))
        self.assertFalse(field.is_flag_set("USB_RCP"))

        # Test dictionary of flags
        self.assertIsNotNone(field.flags_dict)
        self.assertTrue(field.flags_dict["DEADMAN"])
        self.assertFalse(field.flags_dict["INT_FAN"])

        # Test to_dict serialization
        d = field.to_dict()
        self.assertTrue(d["is_bitfield"])
        self.assertEqual(d["value"], ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])
        self.assertEqual(d["raw_value"], 5135)
        self.assertEqual(d["bitmask_flags"], ["DEADMAN", "GATEDRIVE", "REBUS_CONNECT", "BATT_CONNECT", "AUTOMODE", "BMS"])
        self.assertIsInstance(d["flags_dict"], dict)
        self.assertTrue(d["flags_dict"]["DEADMAN"])

    def test_controls_fallback_bitfield_validation(self):
        # Create a field with bitfield symbols directly
        field = self.state.set_field(
            device_sn=self.battery.serial_number,
            name="CustomBits",
            label="Custom Bits",
            description="Custom test bitfield",
            value=[],
            raw_value=0,
            access="RW",
            symbols=[
                {"name": "BIT_A", "value": 0},
                {"name": "BIT_B", "value": 1},
                {"name": "BIT_C", "value": 2},
            ],
            point_type="bitfield16",
            is_bitfield=True,
            sub_group="test_group",
        )

        res = self.controls.write_field("battery.test_group.CustomBits", ["BIT_A", "BIT_C"])
        self.assertEqual(res, ["BIT_A", "BIT_C"])
        field = self.battery.fields.get("battery.test_group.CustomBits")
        self.assertEqual(field.value, ["BIT_A", "BIT_C"])
        self.assertEqual(field.raw_value, 5)  # 1 | 4
        self.assertTrue(field.is_flag_set("BIT_A"))
        self.assertFalse(field.is_flag_set("BIT_B"))
        self.assertTrue(field.is_flag_set("BIT_C"))

    def test_ha_discovery_attributes_topic(self):
        self.state.update_from_modbus_points(
            serial_number=self.battery.serial_number,
            model_id=64209,
            raw_values={"EnableBits": 5135},
        )
        field = self.battery.fields.get("battery.battery_status.EnableBits")
        self.assertIsNotNone(field)

        payload_info = generate_discovery_payload(field, self.battery)
        self.assertIsNotNone(payload_info["attributes_topic"])
        self.assertIn("/attributes", payload_info["attributes_topic"])
        self.assertIn("json_attributes_topic", payload_info["payload"])
        self.assertEqual(payload_info["payload"]["json_attributes_topic"], payload_info["attributes_topic"])


if __name__ == "__main__":
    unittest.main()
