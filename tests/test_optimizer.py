"""Unit tests for Set-Cover Optimization & Unified Field Grouping."""

import time
import unittest
from pwrcell.mapping import MappingRegistry
from pwrcell.optimizer import (
    CANONICAL_SYNONYMS,
    OptimizationResult,
    UnifiedFieldGroup,
    UnifiedSource,
    clean_unit,
    find_canonical_concept,
    group_device_fields,
    resolve_minimal_models_for_paths,
    solve_minimal_model_set,
)
from pwrcell.state import FieldSource, StateField, StateStore, UnifiedDevice


class TestSetCoverOptimizer(unittest.TestCase):
    def test_solve_single_covering_model(self):
        # Model 64208 covers all requested fields
        items = {
            "hz": {102, 64208},
            "w": {102, 64208},
            "sysmd": {64200, 64202, 64208},
            "ctpow": {64208},
            "whin": {64208},
            "whout": {64208},
        }
        res = solve_minimal_model_set(items)
        self.assertEqual(res.minimal_models, [64208])
        self.assertEqual(res.stats["models_needed"], 1)
        self.assertEqual(res.stats["models_avoided"], 3)  # 102, 64200, 64202 avoided
        for k in items:
            self.assertEqual(res.assignments[k], 64208)

    def test_solve_multiple_models_needed(self):
        # Field 1 in {102, 64208}
        # Field 2 in {64208}
        # Field 3 in {120} (Nameplate only)
        # Field 4 in {126} (Volt-Var only)
        items = {
            "hz": {102, 64208},
            "ctpow": {64208},
            "nameplate": {120},
            "volt_var": {126},
        }
        res = solve_minimal_model_set(items)
        self.assertEqual(sorted(res.minimal_models), [120, 126, 64208])
        self.assertEqual(res.stats["models_needed"], 3)
        self.assertEqual(res.assignments["hz"], 64208)
        self.assertEqual(res.assignments["ctpow"], 64208)
        self.assertEqual(res.assignments["nameplate"], 120)
        self.assertEqual(res.assignments["volt_var"], 126)

    def test_solve_pinned_override(self):
        items = {
            "hz": {102, 64208},
            "ctpow": {64208},
            "sysmd": {64202, 64208},
        }
        # Pinning hz to 102 forces 102 into minimal set
        res = solve_minimal_model_set(items, pinned_sources={"hz": 102})
        self.assertIn(102, res.minimal_models)
        self.assertIn(64208, res.minimal_models)
        self.assertEqual(len(res.minimal_models), 2)
        self.assertEqual(res.assignments["hz"], 102)
        self.assertEqual(res.assignments["ctpow"], 64208)

    def test_solve_with_mqtt_sources(self):
        items = {
            "grid_power": {64208, "MQTT"},
            "battery_power": {802, 64252, "MQTT"},
            "only_modbus": {64208},
        }
        # MQTT satisfies grid_power without polling, but only_modbus requires 64208
        res = solve_minimal_model_set(items, allow_mqtt=True)
        self.assertIn(64208, res.minimal_models)

    def test_clean_unit(self):
        self.assertEqual(clean_unit("Hz"), "Hz")
        self.assertEqual(clean_unit("hz"), "Hz")
        self.assertEqual(clean_unit("°C"), "C")
        self.assertEqual(clean_unit("degC"), "C")
        self.assertEqual(clean_unit("Pct"), "%")
        self.assertEqual(clean_unit("kW"), "kW")

    def test_grid_imported_and_exported_energy_synonyms(self):
        """TotWhImp must map to grid_imported_energy and TotWhExp to grid_exported_energy."""
        imp_concept = find_canonical_concept("inverter", "TotWhImp", "Wh")
        exp_concept = find_canonical_concept("inverter", "TotWhExp", "Wh")
        self.assertEqual(imp_concept, "grid_imported_energy")
        self.assertEqual(exp_concept, "grid_exported_energy")


class TestDeviceFieldGrouping(unittest.TestCase):
    def setUp(self):
        self.dev = UnifiedDevice(
            serial_number="2000000001",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell 2P Inverter",
            manufacturer="Generac",
            version="1.0",
            supported_models=[102, 64208, 64202, 64200],
        )

        # Model 102 fields
        self.dev.fields["inverter.inverter.Hz"] = StateField(
            key="inverter.inverter.Hz",
            device_sn="2000000001",
            device_type="inverter",
            name="Hz",
            label="Frequency",
            description="Frequency",
            units="Hz",
            value=60.0,
            raw_value=6000,
            model_id=102,
            model_name="inverter",
            source=FieldSource.MODBUS_POLL,
        )
        self.dev.fields["inverter.inverter.W"] = StateField(
            key="inverter.inverter.W",
            device_sn="2000000001",
            device_type="inverter",
            name="W",
            label="Real Power",
            description="Real Power",
            units="W",
            value=3500.0,
            raw_value=350,
            model_id=102,
            model_name="inverter",
            source=FieldSource.MODBUS_POLL,
        )

        # Model 64208 fields
        self.dev.fields["inverter.inverter_status.Hz"] = StateField(
            key="inverter.inverter_status.Hz",
            device_sn="2000000001",
            device_type="inverter",
            name="Hz",
            label="AC Frequency",
            description="AC Frequency",
            units="Hz",
            value=60.01,
            raw_value=6001,
            model_id=64208,
            model_name="inverter_status",
            source=FieldSource.MODBUS_POLL,
        )
        self.dev.fields["inverter.inverter_status.CTPow"] = StateField(
            key="inverter.inverter_status.CTPow",
            device_sn="2000000001",
            device_type="inverter",
            name="CTPow",
            label="CT Meter Power",
            description="CT Meter Power",
            units="W",
            value=-1200.0,
            raw_value=-1200,
            model_id=64208,
            model_name="inverter_status",
            source=FieldSource.MODBUS_POLL,
        )
        self.dev.fields["inverter.inverter_status.SysMd"] = StateField(
            key="inverter.inverter_status.SysMd",
            device_sn="2000000001",
            device_type="inverter",
            name="SysMd",
            label="System Operating Mode",
            description="Operating mode",
            units="",
            value=1,
            raw_value=1,
            model_id=64208,
            model_name="inverter_status",
            source=FieldSource.MODBUS_CONFIG,
            access="RW",
        )

        # Push MQTT telemetry fields
        self.dev.fields["inverter.live.ac_frequency_hz"] = StateField(
            key="inverter.live.ac_frequency_hz",
            device_sn="2000000001",
            device_type="inverter",
            name="ac_frequency_hz",
            label="AC Frequency (Push)",
            description="AC Frequency (Push)",
            units="Hz",
            value=60.02,
            raw_value=60.02,
            model_id=None,
            source=FieldSource.MQTT_PUSH,
        )
        self.dev.fields["inverter.live.grid_power_w"] = StateField(
            key="inverter.live.grid_power_w",
            device_sn="2000000001",
            device_type="inverter",
            name="grid_power_w",
            label="Grid Power (Push)",
            description="Grid Power (Push)",
            units="W",
            value=1200.0,
            raw_value=1200.0,
            model_id=None,
            source=FieldSource.MQTT_PUSH,
        )

    def test_group_device_fields_collapses_duplicates(self):
        groups = group_device_fields(self.dev)
        group_ids = {g.concept_key: g for g in groups}

        # AC Frequency should group 3 sources: M102, M64208, MQTT
        self.assertIn("ac_frequency", group_ids)
        hz_grp = group_ids["ac_frequency"]
        self.assertEqual(len(hz_grp.sources), 3)
        source_types = {s.source_type for s in hz_grp.sources}
        self.assertIn("MQTT", source_types)
        self.assertIn("SUNSPEC", source_types)

        # Model 64208 should be selected as optimal SunSpec model
        sunspec_sources = [s for s in hz_grp.sources if s.source_type == "SUNSPEC"]
        optimal_sunspec = [s for s in sunspec_sources if s.is_optimal]
        self.assertTrue(len(optimal_sunspec) >= 1)

        # Grid power should group CTPow and push grid_power_w (2 sources)
        self.assertIn("grid_power", group_ids)
        grid_grp = group_ids["grid_power"]
        self.assertEqual(len(grid_grp.sources), 2)
        grid_source_keys = {s.field_key for s in grid_grp.sources}
        self.assertIn("inverter.live.grid_power_w", grid_source_keys)
        self.assertTrue(any(k.endswith(".CTPow") for k in grid_source_keys))

        # Inverter output power should group Model 102 W and push inverter_output_power_w
        self.assertIn("inverter_output_power", group_ids)
        inv_out_grp = group_ids["inverter_output_power"]
        inv_out_source_keys = {s.field_key for s in inv_out_grp.sources}
        self.assertIn("inverter.inverter.W", inv_out_source_keys)

        # System mode should be present and marked writable
        self.assertIn("system_mode", group_ids)
        sys_grp = group_ids["system_mode"]
        self.assertTrue(sys_grp.is_writable)

    def test_group_device_fields_semi_manual_pinning(self):
        # User pins ac_frequency to Model 102
        preferred = {"inverter.concept.ac_frequency": "inverter.inverter.Hz"}
        groups = group_device_fields(self.dev, preferred_sources=preferred)
        group_ids = {g.concept_key: g for g in groups}

        hz_grp = group_ids["ac_frequency"]
        self.assertEqual(hz_grp.active_source_key, "inverter.inverter.Hz")
        pinned_src = next(s for s in hz_grp.sources if s.field_key == "inverter.inverter.Hz")
        self.assertTrue(pinned_src.is_pinned)

    def test_resolve_minimal_models_for_paths(self):
        # Select paths that can be satisfied by Model 64208 alone
        paths = [
            "inverter.inverter.Hz",
            "inverter.inverter_status.CTPow",
            "inverter.concept.system_mode",
        ]
        store = StateStore()
        store.devices[self.dev.serial_number] = self.dev
        resolved = resolve_minimal_models_for_paths(paths, state_store=store)

        self.assertIn("inverter", resolved)
        # Should pick minimal model 64208 rather than [102, 64208, 64200, 64202]
        self.assertEqual(resolved["inverter"], [64208])

    def test_group_device_fields_bitfield_metadata(self):
        # Add a bitfield to self.dev
        self.dev.fields["inverter.inverter_status.RelayStatus"] = StateField(
            key="inverter.inverter_status.RelayStatus",
            device_sn="2000000001",
            device_type="inverter",
            name="RelayStatus",
            label="Relay status",
            description="Relay connection bitmask",
            units="",
            value=["REBUS_CONNECTED", "GRID_CONNECTED"],
            raw_value=3,
            model_id=64208,
            model_name="inverter_status",
            source=FieldSource.MODBUS_POLL,
            is_bitfield=True,
            point_type="bitfield16",
            symbols=[
                {"value": 0, "name": "REBUS_CONNECTED", "label": "REbus Connected"},
                {"value": 1, "name": "GRID_CONNECTED", "label": "Grid Connected"},
            ],
            bitmask_flags=["REBUS_CONNECTED", "GRID_CONNECTED"],
        )
        groups = group_device_fields(self.dev)
        relay_grp = next(g for g in groups if g.name == "RelayStatus" or "relay" in g.concept_key)
        self.assertTrue(relay_grp.is_bitfield)
        self.assertEqual(relay_grp.point_type, "bitfield16")
        self.assertEqual(relay_grp.bitmask_flags, ["REBUS_CONNECTED", "GRID_CONNECTED"])
        self.assertEqual(len(relay_grp.symbols), 2)

        d = relay_grp.to_dict()
        self.assertTrue(d["is_bitfield"])
        self.assertEqual(d["point_type"], "bitfield16")
        self.assertEqual(d["bitmask_flags"], ["REBUS_CONNECTED", "GRID_CONNECTED"])
        self.assertEqual(d["latest_value"], ["REBUS_CONNECTED", "GRID_CONNECTED"])

    def test_group_device_fields_scale_factor_metadata(self):
        # Add a scale factor field
        self.dev.fields["inverter.inverter.Hz_SF"] = StateField(
            key="inverter.inverter.Hz_SF",
            device_sn="2000000001",
            device_type="inverter",
            name="Hz_SF",
            label="Frequency Scale Factor",
            description="Frequency Scale Factor",
            units="",
            value=-2,
            raw_value=-2,
            model_id=102,
            model_name="inverter",
            source=FieldSource.MODBUS_POLL,
            is_scale_factor=True,
            point_type="sunssf",
        )
        groups = group_device_fields(self.dev)
        sf_grp = next(g for g in groups if g.name == "Hz_SF" or "hz_sf" in g.concept_key)
        self.assertTrue(sf_grp.is_scale_factor)
        d = sf_grp.to_dict()
        self.assertTrue(d["is_scale_factor"])


if __name__ == "__main__":
    unittest.main()
