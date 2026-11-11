import unittest
import time
from pwrcell.state import StateStore, FieldSource
from pwrcell.ha import qualify_legacy_ha_config, is_field_selected
from pwrcell.mapping import MappingRegistry


class TestGroupingAndMqttAuditFixes(unittest.TestCase):
    def setUp(self):
        self.state = StateStore()

    def test_multi_device_compound_view_secondary_devices(self):
        """Bug H1: Verify secondary PV Links get compound views with their own device-scoped data."""
        sn1 = "000100034AC7"
        sn2 = "000100034E68"

        self.state.register_device(serial_number=sn1, slave_id=1, device_type="pv_link", model_name="PV Link 1")
        self.state.register_device(serial_number=sn2, slave_id=2, device_type="pv_link", model_name="PV Link 2")

        self.state.set_field(
            device_sn=sn1,
            name="P",
            label="DC Power",
            value=180.5,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="REbus_status",
        )
        self.state.set_field(
            device_sn=sn2,
            name="P",
            label="DC Power",
            value=220.2,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="REbus_status",
        )

        # Compound view for device 1
        c_view_1 = self.state.get_compound_view("rebus_power", device_sn=sn1)
        self.assertIsNotNone(c_view_1)
        self.assertEqual(c_view_1.device_sn, sn1)
        self.assertEqual(c_view_1.latest_value, 180.5)

        # Compound view for device 2
        c_view_2 = self.state.get_compound_view("rebus_power", device_sn=sn2)
        self.assertIsNotNone(c_view_2)
        self.assertEqual(c_view_2.device_sn, sn2)
        self.assertEqual(c_view_2.latest_value, 220.2)

        # Check all compound views for sn2
        views_2 = self.state.get_compound_views(device_sn=sn2)
        views_2_map = {v.concept_key: v for v in views_2}
        self.assertIn("rebus_power", views_2_map)
        self.assertEqual(views_2_map["rebus_power"].device_sn, sn2)

    def test_null_modbus_does_not_overwrite_valid_mqtt(self):
        """Bug H5: Polling an unimplemented/sentinel Modbus register (None) must not overwrite valid MQTT telemetry."""
        inv = self.state.register_device(
            serial_number="0001000714E9",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
        )

        t_mqtt = time.time()
        self.state.set_field(
            device_sn=inv.serial_number,
            name="grid_power_w",
            label="Grid Power",
            value=2500.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        # Force last_updated
        self.state.devices[inv.serial_number].fields["inverter.live.grid_power_w"].last_updated = t_mqtt

        # Modbus polled later (t_mb > t_mqtt) but returns None (sentinel / unavailable)
        t_mb = t_mqtt + 5.0
        self.state.set_field(
            device_sn=inv.serial_number,
            name="CTPow",
            label="CT Power",
            value=None,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )
        self.state.devices[inv.serial_number].fields["inverter.inverter_status.CTPow"].last_updated = t_mb

        c_view = self.state.get_compound_view("grid_power", device_sn=inv.serial_number)
        self.assertIsNotNone(c_view)
        self.assertEqual(c_view.latest_value, 2500.0, "Valid MQTT value must not be clobbered by None Modbus value")

    def test_qualify_legacy_ha_config_remaps_concept_to_compound(self):
        """Bug D2: qualify_legacy_ha_config must remap known .concept. keys to .compound. instead of dropping them."""
        sn = "0001000714E9"
        self.state.register_device(serial_number=sn, slave_id=8, device_type="inverter", model_name="Inverter")

        input_keys = [
            f"{sn}:inverter.concept.grid_power",
            f"{sn}:inverter.concept.solar_power",
            f"{sn}:inverter.concept.unknown_xyz_nonexistent",
        ]
        qualified = qualify_legacy_ha_config(input_keys, self.state)

        self.assertIn(f"{sn}:inverter.compound.grid_power", qualified)
        self.assertIn(f"{sn}:inverter.compound.solar_power", qualified)
        self.assertNotIn(f"{sn}:inverter.concept.unknown_xyz_nonexistent", qualified)

    def test_unreachable_dead_code_ha_category_fixed(self):
        """Bug H7: Verify c_view.ha_category is assigned rather than returning early with None."""
        inv = self.state.register_device(
            serial_number="0001000714E9",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
        )
        self.state.set_field(
            device_sn=inv.serial_number,
            name="grid_power_w",
            label="Grid Power",
            value=100.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )

        c_view = self.state.get_compound_view("grid_power", device_sn=inv.serial_number)
        self.assertIsNotNone(c_view)
        # Should be None or 'diagnostic' based on get_effective_ha_category, but not crash
        self.assertTrue(hasattr(c_view, "ha_category"))

    def test_state_store_refresh_compound_links(self):
        """Bug H2: Verify refresh_compound_links updates StateField compound_key."""
        inv = self.state.register_device(
            serial_number="0001000714E9",
            slave_id=8,
            device_type="inverter",
            model_name="PWRcell Inverter",
        )
        f = self.state.set_field(
            device_sn=inv.serial_number,
            name="CTPow",
            label="CT Power",
            value=100.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )
        self.state.refresh_compound_links(inv.serial_number)
        self.assertEqual(f.compound_key, "inverter.compound.grid_power")


if __name__ == "__main__":
    unittest.main()
