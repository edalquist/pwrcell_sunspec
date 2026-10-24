"""Golden baseline tests for Concept Grouping, Comparison, and Model Resolution.

These tests capture the end-to-end grouping behavior across representative
PWRcell devices (Inverter, Battery, PV Link) with concurrent MQTT push
telemetry and Modbus SunSpec registers.
"""

import time
import unittest
from pwrcell.mapping import MappingRegistry
from pwrcell.optimizer import group_device_fields, solve_minimal_model_set
from pwrcell.state import FieldSource, StateField, StateStore, UnifiedDevice


class TestGoldenGrouping(unittest.TestCase):

    def setUp(self):
        self.state = StateStore()
        self.inv = self.state.register_device(
            serial_number="0001000714E9",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell 2P Inverter",
        )
        self.bat = self.state.register_device(
            serial_number="000100082128",
            slave_id=9,
            device_type="battery",
            model_name="PWRcell Battery",
        )

    def _populate_inverter_telemetry(self):
        """Populate realistic dual-source telemetry on inverter."""
        t0 = time.time() - 2.0
        # 1. Modbus registers
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="CT Net Power",
            description="Modbus CT power reading",
            value=-3450.0,
            raw_value=-3450.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="model_64208",
            model_id=64208,
            model_name="inverter_status",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="W",
            label="Inverter AC Output Power",
            description="Real AC output power",
            value=4500.0,
            raw_value=4500.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="model_102",
            model_id=102,
            model_name="split_phase",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="Hz",
            label="AC Line Frequency",
            description="Frequency in Hz",
            value=60.01,
            raw_value=6001,
            units="Hz",
            source=FieldSource.MODBUS_POLL,
            sub_group="model_102",
            model_id=102,
            model_name="split_phase",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="SysMd",
            label="System Operating Mode",
            description="Current system operating mode",
            value="SELF_SUPPLY",
            raw_value=2,
            units="",
            source=FieldSource.MODBUS_POLL,
            sub_group="model_64208",
            model_id=64208,
            model_name="inverter_status",
            access="RW",
        )

        # 2. MQTT Push telemetry (slightly newer)
        t1 = time.time() - 0.5
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="grid_power_w",
            label="Grid Net Power",
            description="MQTT Net grid power",
            value=3460.0,
            raw_value=3460.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="inverter_output_power_w",
            label="Inverter Output Power",
            description="MQTT AC power",
            value=4510.0,
            raw_value=4510.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="system_mode",
            label="System Operating Mode",
            description="MQTT System mode",
            value="SELF_SUPPLY",
            raw_value=2,
            units="",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
            access="RW",
        )

    def test_inverter_concept_grouping(self):
        """Verify inverter fields group cleanly into expected canonical concepts."""
        self._populate_inverter_telemetry()
        groups = group_device_fields(self.inv)
        group_keys = {g.concept_key: g for g in groups}

        # Expected core concepts
        self.assertIn("grid_power", group_keys)
        self.assertIn("inverter_output_power", group_keys)
        self.assertIn("ac_frequency", group_keys)
        self.assertIn("system_mode", group_keys)

        # Verify grid_power merges MQTT grid_power_w and Modbus CTPow
        gp = group_keys["grid_power"]
        source_keys = {s.field_key for s in gp.sources}
        self.assertIn("inverter.live.grid_power_w", source_keys)
        self.assertIn("inverter.model_64208.CTPow", source_keys)
        # Transform negate was applied to -3450 => 3450
        modbus_source = next(s for s in gp.sources if s.source_type == "SUNSPEC")
        self.assertEqual(modbus_source.value, 3450.0)

        # Verify system_mode is writable and merged
        sm = group_keys["system_mode"]
        self.assertTrue(sm.is_writable)
        sm_source_keys = {s.field_key for s in sm.sources}
        self.assertIn("inverter.live.system_mode", sm_source_keys)
        self.assertIn("inverter.model_64208.SysMd", sm_source_keys)

    def test_minimal_model_resolution(self):
        """Verify model resolver selects minimal models needed for requested items."""
        # Concept items with candidate models
        items = {
            "grid_power": {64208},
            "inverter_output_power": {102, 64208},
            "ac_frequency": {102, 64208},
        }
        res = solve_minimal_model_set(items)
        # Model 64208 satisfies all three concepts
        self.assertEqual(res.minimal_models, [64208])
        self.assertEqual(res.assignments["grid_power"], 64208)
        self.assertEqual(res.assignments["inverter_output_power"], 64208)
        self.assertEqual(res.assignments["ac_frequency"], 64208)

    def test_battery_concept_grouping(self):
        """Verify battery fields group into SoC, SoH, battery_power, and voltage."""
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="SoC",
            label="State of Charge",
            description="Battery SoC percentage",
            value=85.0,
            raw_value=8500,
            units="%",
            source=FieldSource.MODBUS_POLL,
            model_id=802,
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="state_of_charge",
            label="State of Charge",
            description="MQTT Battery SoC",
            value=85.0,
            raw_value=85.0,
            units="%",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="W",
            label="Battery Real Power",
            description="Modbus Battery power",
            value=-1200.0,
            raw_value=-1200.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            model_id=64252,
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="battery_power_w",
            label="Battery Power",
            description="MQTT Battery power",
            value=1210.0,
            raw_value=1210.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )

        groups = group_device_fields(self.bat)
        group_keys = {g.concept_key: g for g in groups}

        self.assertIn("battery_soc", group_keys)
        self.assertIn("battery_power", group_keys)

        soc = group_keys["battery_soc"]
        self.assertEqual(len(soc.sources), 2)
        soc_src_types = {s.source_type for s in soc.sources}
        self.assertEqual(soc_src_types, {"MQTT", "SUNSPEC"})


if __name__ == "__main__":
    unittest.main()
