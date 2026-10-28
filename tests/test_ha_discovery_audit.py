"""Unit tests verifying the Home Assistant MQTT Discovery payload audit fixes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pwrcell.bridge import HomeAssistantBridge
from pwrcell.catalog import get_catalog
from pwrcell.client import PwrcellClient
from pwrcell.fixtures import MockTelemetryGenerator
from pwrcell.ha import generate_discovery_payload
from pwrcell.mqtt import MqttClient
from pwrcell.state import StateStore


class TestHaDiscoveryAudit(unittest.TestCase):

    def setUp(self):
        self.catalog = get_catalog()
        self.state = StateStore(catalog=self.catalog)

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
            model_name="PWRcell Beacon",
        )
        self.pv = self.state.register_device(
            serial_number="000100034AC7",
            slave_id=3,
            device_type="pv_link",
            model_name="PWRcell PV Link",
        )

        # Ingest telemetry snapshot to populate live telemetry fields
        gen = MockTelemetryGenerator(inverter_id="0001000714E9")
        rec = gen.tick(2.0)
        snap = MqttClient._parse_snapshot(rec)
        if snap:
            self.state.update_from_telemetry_snapshot(snap)

        # Populate SunSpec Modbus points on inverter
        self.state.update_from_modbus_points(
            serial_number="0001000714E9",
            model_id=102,
            raw_values={
                "W": 5000, "W_SF": 0,
                "A": 208, "A_SF": -1,
                "AphA": 104, "AphB": 104,
                "PhVphA": 1200, "PhVphB": 1200, "V_SF": -1,
                "VA": 5100, "VA_SF": 0,
                "VAr": 100, "VAr_SF": 0,
                "PF": 98, "PF_SF": 0,
                "DCV": 3800, "DCV_SF": -1,
                "Hz": 6000, "Hz_SF": -2,
                "TmpCab": 35, "TmpSnk": 45, "TmpTrns": 50, "TmpOt": 30, "Tmp_SF": 0,
            },
            computed_values={
                "W": 5000.0, "A": 20.8, "AphA": 10.4, "AphB": 10.4,
                "PhVphA": 120.0, "PhVphB": 120.0,
                "VA": 5100.0, "VAr": 100.0, "PF": 98.0,
                "DCV": 380.0, "Hz": 60.0,
                "TmpCab": 35.0, "TmpSnk": 45.0, "TmpTrns": 50.0, "TmpOt": 30.0,
            },
        )
        self.state.update_from_modbus_points(
            serial_number="0001000714E9",
            model_id=64207,
            raw_values={"V": 3800, "VT_sf": -1, "T": 420, "St": 2080, "I": 100, "I_sf": -1},
            computed_values={"V": 380.0, "T": 42.0, "St": 2080, "I": 10.0},
        )

        # Populate SunSpec Modbus points on battery
        self.state.update_from_modbus_points(
            serial_number="000100082128",
            model_id=802,
            raw_values={
                "SoC": 850, "SoC_SF": -1,
                "SoCMax": 950, "SoCRsvMax": 800, "SoCRsvMin": 200,
                "AChaMax": 300, "AChaDisCha_SF": -1,
                "ADisChaMax": 300,
            },
            computed_values={
                "SoC": 85.0, "SoCMax": 95.0, "SoCRsvMax": 80.0, "SoCRsvMin": 20.0,
                "AChaMax": 30.0, "ADisChaMax": 30.0,
            },
        )

        # Populate SunSpec Modbus points on PV link
        self.state.update_from_modbus_points(
            serial_number="000100034AC7",
            model_id=64207,
            raw_values={"P": 1500, "E": 120000, "V": 3800, "VT_sf": -1, "T": 380, "St": 8192, "I": 50, "I_sf": -1},
            computed_values={"P": 1500.0, "E": 120000, "V": 380.0, "T": 38.0, "St": 8192, "I": 5.0},
        )
        self.state.update_from_modbus_points(
            serial_number="000100034AC7",
            model_id=404,
            raw_values={"DCA": 85, "DCA_SF": -1},
            computed_values={"DCA": 8.5},
        )

    def test_enum_sensors_have_options(self):
        """Enum sensors like live_system_mode and live_inverter_state_name must declare non-empty options."""
        # 1. live_system_mode
        sys_mode_field = self.inv.fields.get("inverter.live.system_mode")
        self.assertIsNotNone(sys_mode_field)
        disc_sys = generate_discovery_payload(sys_mode_field, self.inv)
        payload_sys = disc_sys["payload"]
        if payload_sys.get("device_class") == "enum":
            self.assertIn("options", payload_sys)
            self.assertTrue(len(payload_sys["options"]) > 0)
            self.assertIn("CLEAN_BACKUP", payload_sys["options"])

        # 2. live_inverter_state_name
        inv_st_field = self.inv.fields.get("inverter.live.inverter_state_name")
        self.assertIsNotNone(inv_st_field)
        disc_st = generate_discovery_payload(inv_st_field, self.inv)
        payload_st = disc_st["payload"]
        self.assertEqual(payload_st.get("device_class"), "enum")
        self.assertIn("options", payload_st)
        self.assertTrue(len(payload_st["options"]) > 0)
        self.assertIn("GRID_CONNECTED", payload_st["options"])

    def test_temperature_sensors_canonical_units_and_device_class(self):
        """All temperature sensors must use unit '°C' and device_class 'temperature'."""
        for temp_name in ("TmpCab", "TmpSnk", "TmpTrns", "TmpOt"):
            f = self.inv.fields.get(f"inverter.inverter.{temp_name}")
            self.assertIsNotNone(f, f"Missing inverter.inverter.{temp_name}")
            disc = generate_discovery_payload(f, self.inv)["payload"]
            self.assertEqual(disc.get("unit_of_measurement"), "°C")
            self.assertEqual(disc.get("device_class"), "temperature")

        rebus_t = self.inv.fields.get("inverter.REbus_status.T")
        self.assertIsNotNone(rebus_t)
        disc = generate_discovery_payload(rebus_t, self.inv)["payload"]
        self.assertEqual(disc.get("unit_of_measurement"), "°C")
        self.assertEqual(disc.get("device_class"), "temperature")

        pv_t = self.pv.fields.get("pv_link.REbus_status.T")
        self.assertIsNotNone(pv_t)
        disc = generate_discovery_payload(pv_t, self.pv)["payload"]
        self.assertEqual(disc.get("unit_of_measurement"), "°C")
        self.assertEqual(disc.get("device_class"), "temperature")

    def test_power_factor_device_class_and_unit(self):
        """inverter_pf must declare device_class 'power_factor' and unit '%'."""
        f_pf = self.inv.fields.get("inverter.inverter.PF")
        self.assertIsNotNone(f_pf)
        disc = generate_discovery_payload(f_pf, self.inv)["payload"]
        self.assertEqual(disc.get("device_class"), "power_factor")
        self.assertEqual(disc.get("unit_of_measurement"), "%")

    def test_battery_soc_device_class_and_unit(self):
        """battery_soc compound view must declare device_class 'battery' and unit '%'."""
        c_soc = self.state.get_compound_view("battery_soc")
        self.assertIsNotNone(c_soc)
        disc = generate_discovery_payload(c_soc, self.bat)["payload"]
        self.assertEqual(disc.get("device_class"), "battery")
        self.assertEqual(disc.get("unit_of_measurement"), "%")

    def test_battery_soc_number_bounds_capped_at_100(self):
        """SoC limit number controls (SoCMax, SoCRsvMax, SoCRsvMin) must cap max at 100."""
        for pt_name in ("SoCMax", "SoCRsvMax", "SoCRsvMin"):
            f = self.bat.fields.get(f"battery.battery.{pt_name}")
            self.assertIsNotNone(f, f"Missing battery.battery.{pt_name}")
            disc = generate_discovery_payload(f, self.bat)["payload"]
            self.assertLessEqual(disc.get("max"), 100.0)
            self.assertGreaterEqual(disc.get("min"), 0.0)
            self.assertEqual(disc.get("unit_of_measurement"), "%")

    def test_naming_bugs_fixed(self):
        """Entity names must be clean, trimmed, and not raw unit names."""
        # 1. REbus Voltage whitespace stripped
        f_v = self.inv.fields.get("inverter.REbus_status.V")
        self.assertIsNotNone(f_v)
        disc = generate_discovery_payload(f_v, self.inv)["payload"]
        self.assertEqual(disc.get("name"), "REbus Voltage")
        self.assertFalse(disc.get("name").endswith(" "))

        # 2. Inverter active power (Watts -> Active Power)
        f_w = self.inv.fields.get("inverter.inverter.W")
        self.assertIsNotNone(f_w)
        disc = generate_discovery_payload(f_w, self.inv)["payload"]
        self.assertEqual(disc.get("name"), "Active Power")

        # 3. Inverter output current (Amps -> AC Output Current)
        f_a = self.inv.fields.get("inverter.inverter.A")
        self.assertIsNotNone(f_a)
        disc = generate_discovery_payload(f_a, self.inv)["payload"]
        self.assertEqual(disc.get("name"), "AC Output Current")

        # 4. Phase currents
        f_apha = self.inv.fields.get("inverter.inverter.AphA")
        self.assertIsNotNone(f_apha)
        disc = generate_discovery_payload(f_apha, self.inv)["payload"]
        self.assertEqual(disc.get("name"), "Phase A Current")

        f_aphb = self.inv.fields.get("inverter.inverter.AphB")
        self.assertIsNotNone(f_aphb)
        disc = generate_discovery_payload(f_aphb, self.inv)["payload"]
        self.assertEqual(disc.get("name"), "Phase B Current")

        # 5. String Current on PV Link
        f_dca = self.pv.fields.get("pv_link.string_combiner.DCA")
        self.assertIsNotNone(f_dca)
        disc = generate_discovery_payload(f_dca, self.pv)["payload"]
        self.assertIn(disc.get("name"), ("String Current", "DC Current"))

    def test_electrical_sensor_device_classes(self):
        """Apparent power, reactive power, and current limits must declare proper device_classes."""
        f_va = self.inv.fields.get("inverter.inverter.VA")
        self.assertIsNotNone(f_va)
        disc = generate_discovery_payload(f_va, self.inv)["payload"]
        self.assertEqual(disc.get("device_class"), "apparent_power")

        f_var = self.inv.fields.get("inverter.inverter.VAr")
        self.assertIsNotNone(f_var)
        disc = generate_discovery_payload(f_var, self.inv)["payload"]
        self.assertEqual(disc.get("device_class"), "reactive_power")

        f_acha = self.bat.fields.get("battery.battery.AChaMax")
        self.assertIsNotNone(f_acha)
        disc = generate_discovery_payload(f_acha, self.bat)["payload"]
        self.assertEqual(disc.get("device_class"), "current")

    def test_diagnostics_and_raw_sunspec_enabled_by_default(self):
        """Internal engineering metrics must be categorized as diagnostic, and all selected fields enabled by default."""
        f_tmpcab = self.inv.fields.get("inverter.inverter.TmpCab")
        self.assertIsNotNone(f_tmpcab)
        disc = generate_discovery_payload(f_tmpcab, self.inv)["payload"]
        self.assertEqual(disc.get("entity_category"), "diagnostic")
        self.assertTrue(disc.get("enabled_by_default", True))

        f_dcv = self.inv.fields.get("inverter.inverter.DCV")
        self.assertIsNotNone(f_dcv)
        disc = generate_discovery_payload(f_dcv, self.inv)["payload"]
        self.assertEqual(disc.get("entity_category"), "diagnostic")
        self.assertTrue(disc.get("enabled_by_default", True))

    def test_pv_link_primary_vs_diagnostic_enabled_by_default(self):
        """All selected PV Link metrics must be enabled by default; internal sensors categorized as diagnostic."""
        # Primary metrics enabled
        for pt_key in ("pv_link.REbus_status.P", "pv_link.REbus_status.E", "pv_link.string_combiner.DCA"):
            f = self.pv.fields.get(pt_key)
            self.assertIsNotNone(f, f"Missing {pt_key}")
            payload = generate_discovery_payload(f, self.pv)["payload"]
            self.assertTrue(payload.get("enabled_by_default", True), f"{pt_key} should be enabled by default")
            self.assertIsNone(payload.get("entity_category"), f"{pt_key} should not be categorized as diagnostic")

        # Internal diagnostics enabled and categorized
        for diag_key in ("pv_link.REbus_status.V", "pv_link.REbus_status.T", "pv_link.REbus_status.St", "pv_link.REbus_status.I"):
            f = self.pv.fields.get(diag_key)
            self.assertIsNotNone(f, f"Missing {diag_key}")
            payload = generate_discovery_payload(f, self.pv)["payload"]
            self.assertTrue(payload.get("enabled_by_default", True), f"{diag_key} should be enabled by default")
            self.assertEqual(payload.get("entity_category"), "diagnostic", f"{diag_key} should be diagnostic")

    def test_all_selected_metrics_enabled_by_default(self):
        """All selected metrics must be enabled by default (enabled_by_default is never false)."""
        live_keys = (
            "inverter.live.grid_power_w",
            "inverter.live.inverter_output_power_w",
            "inverter.live.solar_power_w",
        )
        for r_key in live_keys:
            f = self.inv.fields.get(r_key)
            if f is not None:
                payload = generate_discovery_payload(f, self.inv)["payload"]
                self.assertTrue(payload.get("enabled_by_default", True), f"{r_key} should be enabled by default")

        # Compound views remain enabled by default
        for c_key in ("grid_power", "inverter_output_power", "solar_power"):
            c_view = self.state.get_compound_view(c_key)
            if c_view is not None:
                payload = generate_discovery_payload(c_view, self.inv)["payload"]
                self.assertTrue(payload.get("enabled_by_default", True), f"Compound {c_key} should be enabled by default")

    def test_battery_controls_slider_mode_and_step(self):
        """Battery percentage configuration controls must use mode 'slider', step 1, min 0, max 100."""
        for pt_name in ("SoCMax", "SoCRsvMax", "SoCRsvMin"):
            f = self.bat.fields.get(f"battery.battery.{pt_name}")
            self.assertIsNotNone(f, f"Missing battery.battery.{pt_name}")
            payload = generate_discovery_payload(f, self.bat)["payload"]
            self.assertEqual(payload.get("mode"), "slider", f"{pt_name} mode must be slider")
            self.assertEqual(payload.get("step"), 1, f"{pt_name} step must be 1")
            self.assertEqual(payload.get("min"), 0, f"{pt_name} min must be 0")
            self.assertEqual(payload.get("max"), 100, f"{pt_name} max must be 100")

    def test_parent_gateway_discovery(self):
        """Top-level parent gateway device node (via_device) must be published in discovery."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            topics_file = Path(tmp_dir) / ".ha_published_topics.json"
            client = PwrcellClient(is_mock=True)
            try:
                client.start()
                bridge = HomeAssistantBridge(client=client, published_topics_path=topics_file)
                mock_mqttc = MagicMock()
                bridge._mqttc = mock_mqttc

                bridge.publish_discovery()

                # Find call publishing gateway binary_sensor discovery
                gateway = client.state.get_beacon() or client.state.get_inverter()
                self.assertIsNotNone(gateway)
                gw_sn_lower = gateway.serial_number.strip().lower()
                expected_topic = f"homeassistant/binary_sensor/pwrcell_{gw_sn_lower}/status/config"

                found_call = None
                for call_args in mock_mqttc.publish.call_args_list:
                    args, kwargs = call_args
                    if args and args[0] == expected_topic:
                        found_call = args
                        break

                self.assertIsNotNone(found_call, f"Expected discovery published on {expected_topic}")
                topic, payload_str = found_call[0], found_call[1]
                payload = json.loads(payload_str)
                self.assertTrue(payload.get("has_entity_name"))
                self.assertEqual(payload.get("name"), "Status")
                self.assertEqual(payload.get("device_class"), "connectivity")
                self.assertEqual(payload.get("entity_category"), "diagnostic")
                self.assertIn(f"pwrcell_{gw_sn_lower}", payload.get("device", {}).get("identifiers", []))
            finally:
                client.stop()

    def test_ha_category_overrides_and_persistence(self):
        """User overrides must control entity_category in discovery and persist to ha_config.yaml."""
        from pwrcell.ha import load_ha_category_overrides, save_ha_category_override, get_effective_ha_category

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "ha_config.yaml"

            # TmpCab is diagnostic by default
            f_tmpcab = self.inv.fields["inverter.inverter.TmpCab"]
            self.assertEqual(get_effective_ha_category(f_tmpcab, self.inv), "diagnostic")
            default_payload = generate_discovery_payload(f_tmpcab, self.inv)["payload"]
            self.assertEqual(default_payload.get("entity_category"), "diagnostic")

            # Override TmpCab to 'primary'
            overrides = save_ha_category_override(self.inv.serial_number, "inverter.inverter.TmpCab", "primary", config_path=cfg_path)
            self.assertIn(f"{self.inv.serial_number}:inverter.inverter.TmpCab", overrides)
            self.assertEqual(overrides[f"{self.inv.serial_number}:inverter.inverter.TmpCab"], "primary")

            loaded = load_ha_category_overrides(cfg_path)
            self.assertEqual(loaded.get(f"{self.inv.serial_number}:inverter.inverter.TmpCab"), "primary")

            # Check effective category with override
            self.assertIsNone(get_effective_ha_category(f_tmpcab, self.inv, category_overrides=loaded))
            overridden_payload = generate_discovery_payload(f_tmpcab, self.inv, category_overrides=loaded)["payload"]
            self.assertNotIn("entity_category", overridden_payload)

            # Grid power is primary by default
            c_view = self.state.get_compound_view("grid_power")
            self.assertIsNotNone(c_view)
            self.assertIsNone(get_effective_ha_category(c_view, self.inv))
            self.assertNotIn("entity_category", generate_discovery_payload(c_view, self.inv)["payload"])

            # Override grid power to 'diagnostic'
            save_ha_category_override(self.inv.serial_number, c_view.key, "diagnostic", config_path=cfg_path)
            loaded = load_ha_category_overrides(cfg_path)
            self.assertEqual(get_effective_ha_category(c_view, self.inv, category_overrides=loaded), "diagnostic")
            diag_payload = generate_discovery_payload(c_view, self.inv, category_overrides=loaded)["payload"]
            self.assertEqual(diag_payload.get("entity_category"), "diagnostic")

            # Clear override
            save_ha_category_override(self.inv.serial_number, "inverter.inverter.TmpCab", "reset", config_path=cfg_path)
            loaded = load_ha_category_overrides(cfg_path)
            self.assertNotIn(f"{self.inv.serial_number}:inverter.inverter.TmpCab", loaded)
            reset_payload = generate_discovery_payload(f_tmpcab, self.inv, category_overrides=loaded)["payload"]
            self.assertEqual(reset_payload.get("entity_category"), "diagnostic")


if __name__ == "__main__":
    unittest.main()
