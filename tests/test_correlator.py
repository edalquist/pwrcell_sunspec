"""Unit tests for pwrcell.correlator."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pwrcell.catalog import get_catalog
from pwrcell.correlator import evaluate_comparisons, format_comparison_table
from pwrcell.fixtures import MockTelemetryGenerator
from pwrcell.grouping import clear_custom_groupings_cache
from pwrcell.mqtt import MqttClient
from pwrcell.state import StateStore


class TestCorrelator(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self._grouping_patch = patch(
            "pwrcell.grouping.get_default_grouping_config_path",
            return_value=Path(self.tmp_dir.name) / "custom_groupings.yaml",
        )
        self._grouping_patch.start()
        clear_custom_groupings_cache()

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

    def tearDown(self):
        self._grouping_patch.stop()
        clear_custom_groupings_cache()
        self.tmp_dir.cleanup()
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
            device_sn=self.inv.serial_number,
            name="SysMd",
            label="System Operating Mode",
            description="Inverter SysMd",
            value=snapshot.system_mode,
            raw_value=snapshot.system_mode,
            sub_group="inverter_status",
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

        # Evaluate comparison rows - solar_power on inverter is single-source MQTT (no cross-device grouping)
        results = evaluate_comparisons(self.state)
        row_map = {r.mapping_id: r for r in results}

        self.assertIn("solar_power", row_map)
        solar_row = row_map["solar_power"]
        self.assertEqual(solar_row.mqtt_value, 978.0)

        # Check compound view in StateStore
        c_view = self.state.get_compound_view("solar_power")
        self.assertIsNotNone(c_view)
        self.assertEqual(c_view.mqtt_value, 978.0)

        # Check heuristic scanner detects the 978.0 W sum
        matches = find_heuristic_matches(self.state, target_value=978.0, tolerance_pct=1.0)
        self.assertTrue(any("sum of 5" in m["device"].lower() for m in matches))

    def test_evaluate_grouped_registers_discrepancy_and_outliers(self):
        """Test comparing all grouped registers in a concept, detecting discrepancies and outliers."""
        from pwrcell.state import FieldSource

        # 1. Matching sources: AC frequency in Model 102 and Model 64208 both 60.0 Hz
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="Hz",
            label="Frequency (M102)",
            value=60.0,
            raw_value=6000,
            units="Hz",
            model_id=102,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="Hz",
            label="Frequency (M64208)",
            value=60.0,
            raw_value=6000,
            units="Hz",
            model_id=64208,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )

        results = evaluate_comparisons(self.state)
        hz_row = next((r for r in results if r.concept_key == "ac_frequency" and r.device_sn == self.inv.serial_number), None)
        self.assertIsNotNone(hz_row)
        self.assertEqual(hz_row.status, "EXACT")
        self.assertFalse(hz_row.is_discrepant)
        self.assertEqual(hz_row.source_count, 2)
        self.assertEqual(len(hz_row.sources), 2)
        self.assertFalse(any(s["is_divergent"] for s in hz_row.sources))

        # 2. Divergent sources: introduce a discrepancy where M64208 Hz drops to 45.0 Hz
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="Hz",
            label="Frequency (M64208)",
            value=45.0,
            raw_value=4500,
            units="Hz",
            model_id=64208,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )

        results_div = evaluate_comparisons(self.state)
        hz_div = next((r for r in results_div if r.concept_key == "ac_frequency" and r.device_sn == self.inv.serial_number), None)
        self.assertIsNotNone(hz_div)
        self.assertEqual(hz_div.status, "DIVERGENT")
        self.assertTrue(hz_div.is_discrepant)
        self.assertEqual(hz_div.delta, 15.0)
        self.assertIn("15.00 Hz", hz_div.discrepancy_reason)
        # Verify outliers tagged
        self.assertTrue(any(s["is_divergent"] for s in hz_div.sources))

        # 3. Unit mismatch: one register in grid_power has W and another has Wh
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="CT Power (M64208)",
            value=100.0,
            raw_value=100,
            units="W",
            model_id=64208,
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="CT Power (M64202 Wh)",
            value=100.0,
            raw_value=100,
            units="Wh",
            model_id=64202,
            source=FieldSource.MODBUS_POLL,
            sub_group="REbus_arb",
        )

        results_unit = evaluate_comparisons(self.state)
        unit_row = next((r for r in results_unit if r.concept_key == "grid_power" and r.device_sn == self.inv.serial_number), None)
        self.assertIsNotNone(unit_row)
        self.assertEqual(unit_row.status, "UNIT_MISMATCH")
        self.assertTrue(unit_row.is_discrepant)
        self.assertIn("Conflicting units", unit_row.discrepancy_reason)

    def test_safety_shutdown_modbus_0_matches_mqtt_16(self):
        """Modbus SysMd=0 (SAFETY_SHUTDOWN) must decode using SunSpec mode names rather than MQTT proto mode 0 (UNKNOWN)."""
        from pwrcell.correlator import KNOWN_TELEMETRY_MAPPINGS, _build_comparison_row

        # MQTT reports SAFETY_SHUTDOWN (proto value 16 -> name "SAFETY_SHUTDOWN")
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="system_mode",
            value="SAFETY_SHUTDOWN",
            raw_value=16,
            sub_group="live",
        )
        # Modbus reports raw integer 0 on SysMd (SunSpec Model 64200 value 0 -> SAFETY_SHUTDOWN)
        mb_field = self.state.set_field(
            device_sn=self.beacon.serial_number,
            name="SysMd",
            value=0,
            raw_value=0,
            sub_group="REbus_dir",
        )

        sys_mapping = next(m for m in KNOWN_TELEMETRY_MAPPINGS if m.mapping_id == "system_mode")
        row = _build_comparison_row(
            sys_mapping,
            sys_mapping.primary_candidate,
            mqtt_val="SAFETY_SHUTDOWN",
            mb_field=mb_field,
            state_store=self.state,
        )
        self.assertEqual(row.modbus_value, "SAFETY_SHUTDOWN")
        self.assertEqual(row.status, "EXACT")

    def test_comparison_row_has_device_sn(self):
        """Telemetry comparison rows and sources must contain device_sn for grouping actions."""
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="Current Transformer Power",
            description="Grid CT power",
            value=-1500.0,
            raw_value=-1500.0,
            units="W",
            sub_group="inverter_status",
        )
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="grid_power_w",
            value=1500.0,
            raw_value=1500.0,
            sub_group="live",
        )
        results = evaluate_comparisons(self.state)
        grid_row = next((r for r in results if r.mapping_id == "grid_power"), None)
        self.assertIsNotNone(grid_row)
        self.assertEqual(grid_row.device_sn, self.inv.serial_number)
        self.assertGreaterEqual(len(grid_row.sources), 1)
        for s in grid_row.sources:
            self.assertEqual(s.get("device_sn"), self.inv.serial_number)

    def test_is_field_excluded_from_mapping_helper(self):
        """is_field_excluded_from_mapping accurately identifies ungrouped and reassigned fields."""
        from pwrcell.grouping import is_field_excluded_from_mapping
        overrides = {
            "field_overrides": {
                "000100082128:battery.live.battery_voltage_v": None,
                "000100082128:battery.REbus_status.V": None,
                "0001000714E9:inverter.inverter_status.CTPow": "inverter_output_power",
            }
        }
        # Ungrouped via exact match
        self.assertTrue(is_field_excluded_from_mapping("000100082128", "battery.live.battery_voltage_v", "battery_voltage", overrides))
        # Ungrouped via model suffix fallback (REbus_status.V matching model_64252.V)
        self.assertTrue(is_field_excluded_from_mapping("000100082128", "battery.model_64252.V", "battery_voltage", overrides))
        # Reassigned away from grid_power
        self.assertTrue(is_field_excluded_from_mapping("0001000714E9", "inverter.inverter_status.CTPow", "grid_power", overrides))
        # Not excluded from the reassigned concept
        self.assertFalse(is_field_excluded_from_mapping("0001000714E9", "inverter.inverter_status.CTPow", "inverter_output_power", overrides))
        # Unaffected field
        self.assertFalse(is_field_excluded_from_mapping("0001000714E9", "inverter.model_102.W", "inverter_output_power", overrides))

    def test_ungrouped_field_excluded_from_baseline_telemetry_comparison(self):
        """Ungrouping a field prevents it from being grouped with baseline Modbus candidates."""
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="battery_voltage_v",
            label="Battery Voltage",
            value=380.0,
            raw_value=380.0,
            sub_group="live",
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="V",
            label="DC Voltage",
            value=380.0,
            raw_value=380.0,
            sub_group="model_64252",
            model_id=64252,
        )

        custom_groupings = {
            "field_overrides": {
                f"{self.bat.serial_number}:battery.live.battery_voltage_v": None,
            }
        }
        results = evaluate_comparisons(self.state, custom_groupings=custom_groupings)

        # Baseline battery_voltage row should NOT pair them as an EXACT match
        exact_paired = next((r for r in results if r.mapping_id == "battery_voltage" and r.status == "EXACT"), None)
        self.assertIsNone(exact_paired, "Ungrouped field should not appear in EXACT match pair")

        # An ungrouped standalone row should be created for the ungrouped field
        ungrouped_row = next((r for r in results if "battery_voltage_v" in r.mapping_id or "Ungrouped" in r.label), None)
        self.assertIsNotNone(ungrouped_row)
        self.assertEqual(ungrouped_row.status, "SINGLE_SOURCE")

    def test_all_ungrouped_sources_suppress_baseline_mapping_row(self):
        """When all sources for a baseline mapping are ungrouped, the baseline row is suppressed."""
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="battery_voltage_v",
            label="Battery Voltage",
            value=380.0,
            raw_value=380.0,
            sub_group="live",
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="V",
            label="DC Voltage",
            value=380.0,
            raw_value=380.0,
            sub_group="model_64252",
            model_id=64252,
        )

        custom_groupings = {
            "field_overrides": {
                f"{self.bat.serial_number}:battery.live.battery_voltage_v": None,
                f"{self.bat.serial_number}:battery.model_64252.V": None,
            }
        }
        results = evaluate_comparisons(self.state, custom_groupings=custom_groupings)

        # Baseline battery_voltage mapping row must be suppressed entirely
        base_row = next((r for r in results if r.mapping_id == "battery_voltage"), None)
        self.assertIsNone(base_row, "Baseline row must be suppressed when all sources are ungrouped")

        # Both fields exist as standalone ungrouped rows
        ungrouped_rows = [r for r in results if r.is_custom_override and not r.is_explicitly_grouped]
        self.assertGreaterEqual(len(ungrouped_rows), 2)

    def test_ungrouped_field_suppressed_from_compound_view(self):
        """get_compound_view excludes ungrouped fields and returns None when all sources are ungrouped."""
        import tempfile
        from pathlib import Path
        import pwrcell.grouping

        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="battery_voltage_v",
            label="Battery Voltage",
            value=380.0,
            raw_value=380.0,
            sub_group="live",
        )
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="V",
            label="DC Voltage",
            value=380.0,
            raw_value=380.0,
            sub_group="model_64252",
            model_id=64252,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "custom_groupings.yaml"
            pwrcell.grouping.set_field_grouping_override(self.bat.serial_number, "battery.live.battery_voltage_v", None, config_path=cfg)
            orig_path_fn = pwrcell.grouping.get_default_grouping_config_path
            pwrcell.grouping.get_default_grouping_config_path = lambda: cfg
            pwrcell.grouping.clear_custom_groupings_cache()
            try:
                # 1. Only MQTT ungrouped: compound view has only SUNSPEC source
                cv = self.state.get_compound_view("battery_voltage")
                self.assertIsNotNone(cv)
                self.assertEqual(len(cv.sources), 1)
                self.assertEqual(cv.sources[0].source_type, "SUNSPEC")

                # 2. Both ungrouped: compound view returns None
                pwrcell.grouping.set_field_grouping_override(self.bat.serial_number, "battery.model_64252.V", None, config_path=cfg)
                pwrcell.grouping.clear_custom_groupings_cache()
                cv_both = self.state.get_compound_view("battery_voltage")
                self.assertIsNone(cv_both)
            finally:
                pwrcell.grouping.get_default_grouping_config_path = orig_path_fn
                pwrcell.grouping.clear_custom_groupings_cache()

    def test_evaluate_comparisons_with_empty_candidates_no_index_error(self):
        """Mappings with empty modbus_fields or empty candidate lists should not raise IndexError."""
        from pwrcell.mapping import MappingRegistry, TelemetryMappingDef
        from pwrcell.tools.correlator import _load_correlator_mappings

        empty_mapping = TelemetryMappingDef(
            id="empty_modbus_test",
            label="Empty Modbus Test",
            device_type="inverter",
            mqtt_fields=["inverter.live.test"],
            modbus_fields=[],
        )
        reg = MappingRegistry.get_instance()
        reg._mappings.append(empty_mapping)
        reg._by_id["empty_modbus_test"] = empty_mapping
        try:
            # Must not raise IndexError
            correlator_mappings = _load_correlator_mappings()
            found = [m for m in correlator_mappings if m.mapping_id == "empty_modbus_test"]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].primary_candidate.field_key, "")

            # Full evaluate_comparisons should also run without error
            results = evaluate_comparisons(self.state)
            empty_result = [r for r in results if r.mapping_id == "empty_modbus_test"]
            self.assertEqual(len(empty_result), 1)
        finally:
            reg._mappings.remove(empty_mapping)
            reg._by_id.pop("empty_modbus_test", None)


if __name__ == "__main__":
    unittest.main()
