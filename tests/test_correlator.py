"""Unit tests for pwrcell.correlator."""

import unittest
from pwrcell.catalog import get_catalog
from pwrcell.correlator import evaluate_comparisons, format_comparison_table
from pwrcell.fixtures import MockTelemetryGenerator
from pwrcell.mqtt import MqttClient
from pwrcell.state import StateStore


class TestCorrelator(unittest.TestCase):

    def setUp(self):
        self.catalog = get_catalog()
        self.state = StateStore(catalog=self.catalog)

        # Register mock inverter and battery
        self.inv = self.state.register_device(
            serial_number="0001000714E9",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
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

    def test_evaluate_comparisons_exact_match(self):
        # 1. Ingest simulated MQTT snapshot
        gen = MockTelemetryGenerator()
        rec_set = gen.tick(2.0)
        snapshot = MqttClient._parse_snapshot(rec_set)
        self.state.update_from_telemetry_snapshot(snapshot)

        # 2. Ingest matching Modbus points
        self.state.set_field(
            device_sn=self.beacon.serial_number,
            name="SysMd",
            label="System Operating Mode",
            description="Beacon SysMd",
            value=snapshot.system_mode,
            raw_value=snapshot.system_mode,
            sub_group="REbus_dir",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="Current Transformer Power",
            description="Grid CT power",
            value=-snapshot.grid_power_w,
            raw_value=-snapshot.grid_power_w,
            units="W",
            sub_group="inverter_status",
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="SoC",
            label="Battery State of Charge",
            description="Battery SoC",
            value=snapshot.battery_soc,
            raw_value=snapshot.battery_soc,
            units="%",
            sub_group="battery",
        )

        results = evaluate_comparisons(self.state)
        self.assertGreater(len(results), 0)

        # Verify exact matches
        row_map = {r.mapping_id: r for r in results}
        self.assertIn("system_mode", row_map)
        self.assertEqual(row_map["system_mode"].status, "EXACT")
        self.assertEqual(row_map["system_mode"].match_pct, 100.0)

        self.assertIn("grid_power", row_map)
        self.assertEqual(row_map["grid_power"].status, "EXACT")
        self.assertEqual(row_map["grid_power"].match_pct, 100.0)

        self.assertIn("battery_soc", row_map)
        self.assertEqual(row_map["battery_soc"].status, "EXACT")
        self.assertEqual(row_map["battery_soc"].match_pct, 100.0)

        # Test table formatting
        table_str = format_comparison_table(results)
        self.assertIn("EXACT MATCH", table_str)

    def test_unrecognized_proto_fields_logging_and_formatting(self):
        from pwrcell.correlator import log_unrecognized_proto_fields
        from pwrcell.mqtt import inspect_unrecognized_proto_fields

        gen = MockTelemetryGenerator()
        rec_set = gen.tick(2.0)
        unrecognized = inspect_unrecognized_proto_fields(rec_set, unrecognized_topics=["beacon/telemetry/extra"])
        self.assertGreater(len(unrecognized), 0)

        # Ensure logging doesn't fail
        log_unrecognized_proto_fields(unrecognized)

        # Test table formatting with unrecognized items
        results = evaluate_comparisons(self.state)
        table_with_unrec = format_comparison_table(results, unrecognized_fields=unrecognized)
        self.assertIn("Unrecognized / Unmapped MQTT Protobuf Fields", table_with_unrec)
        self.assertIn("beacon/telemetry/extra", table_with_unrec)

        # Test table formatting with empty unrecognized items
        table_empty_unrec = format_comparison_table(results, unrecognized_fields=[])
        self.assertIn("No unrecognized or unknown protobuf fields", table_empty_unrec)

    def test_solar_power_multi_pv_link_sum(self):
        """Verify multiple PV link power values sum together to match inverter solar power."""
        from pwrcell.correlator import find_heuristic_matches
        from pwrcell.state import FieldSource

        # Set MQTT solar generation power to 978.0 W on inverter
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="solar_power_w",
            label="Solar Generation Power",
            description="MQTT solar power",
            value=978.0,
            raw_value=978.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )

        # Register 5 PV Link devices with individual powers summing to 978.0 W
        pv_powers = [201.0, 195.0, 200.0, 192.0, 190.0]  # Sum = 978.0
        pv_sns = ["000100034AC7", "000100034E68", "000100034FAC", "0001000361C7", "0001000361F4"]

        for sn, pwr in zip(pv_sns, pv_powers):
            pv_dev = self.state.register_device(
                serial_number=sn,
                slave_id=None,
                device_type="pv_link",
                model_name="PV Link",
            )
            self.state.set_field(
                device_sn=sn,
                name="P",
                label="Real Power",
                description="PV Link DC Power",
                value=pwr,
                raw_value=pwr,
                units="W",
                source=FieldSource.MODBUS_POLL,
                sub_group="model_64207",
            )

        # Evaluate comparison rows
        results = evaluate_comparisons(self.state)
        row_map = {r.mapping_id: r for r in results}

        self.assertIn("solar_power", row_map)
        solar_row = row_map["solar_power"]

        self.assertEqual(solar_row.mqtt_value, 978.0)
        self.assertEqual(solar_row.modbus_value, 978.0)
        self.assertEqual(solar_row.status, "EXACT")
        self.assertEqual(solar_row.match_pct, 100.0)
        self.assertEqual(solar_row.delta, 0.0)
        self.assertIn("Sum across 5 devices", solar_row.notes)

        # Check compound view in StateStore
        c_view = self.state.get_compound_view("solar_power")
        self.assertIsNotNone(c_view)
        self.assertEqual(c_view.modbus_value, 978.0)
        self.assertEqual(c_view.mqtt_value, 978.0)
        self.assertEqual(c_view.match_pct, 100.0)
        self.assertEqual(c_view.delta, 0.0)

        # Check heuristic scanner detects the 978.0 W sum
        matches = find_heuristic_matches(self.state, target_value=978.0, tolerance_pct=1.0)
        self.assertTrue(any("sum of 5" in m["device"].lower() for m in matches))


if __name__ == "__main__":
    unittest.main()
