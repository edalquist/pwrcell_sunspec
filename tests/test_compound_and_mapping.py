"""Unit tests for configurable telemetry mappings and compound state views."""

import json
import time
import unittest
from pwrcell.client import PwrcellClient
from pwrcell.mapping import MappingRegistry, TelemetryMappingDef, apply_transform
from pwrcell.state import FieldSource, StateStore
from pwrcell.ui.server import create_app


class TestConfigurableMappingsAndCompoundViews(unittest.TestCase):

    def setUp(self):
        self.state = StateStore()
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

    def test_apply_transform(self):
        # Negate
        self.assertEqual(apply_transform(-2500, "negate"), 2500)
        self.assertEqual(apply_transform(3200, "negate"), -3200)
        self.assertEqual(apply_transform(-1200, "-x"), 1200)
        # None/Identity
        self.assertEqual(apply_transform(100, "none"), 100)
        self.assertEqual(apply_transform(100, ""), 100)
        self.assertEqual(apply_transform(100, None), 100)

    def test_state_tracks_both_separate_values(self):
        """Verify the state store tracks MQTT and Modbus values separately without overwriting."""
        # 1. Update Modbus CT Power (-3500 W, representing import in Modbus polarity)
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="Inverter CT Power",
            description="Modbus CT power",
            value=-3500.0,
            raw_value=-3500.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )

        # 2. Update MQTT Grid Power (+3510 W, representing import in MQTT polarity)
        self.state.set_field(
            device_sn=self.inv.serial_number,
            name="grid_power_w",
            label="Grid Net Power",
            description="MQTT grid power",
            value=3510.0,
            raw_value=3510.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )

        # Both distinct fields must exist independently in dev.fields
        mb_field = self.inv.fields.get("inverter.inverter_status.CTPow")
        mqtt_field = self.inv.fields.get("inverter.live.grid_power_w")

        self.assertIsNotNone(mb_field)
        self.assertIsNotNone(mqtt_field)
        self.assertEqual(mb_field.value, -3500.0)
        self.assertEqual(mb_field.source, FieldSource.MODBUS_POLL)
        self.assertEqual(mqtt_field.value, 3510.0)
        self.assertEqual(mqtt_field.source, FieldSource.MQTT_PUSH)

    def test_compound_view_surfaces_all_three_values(self):
        """Verify the compound view presents MQTT, Modbus, and Latest values with transform applied."""
        # Step 1: Modbus update at t0
        t0 = time.time() - 5.0
        mb_field = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="Inverter CT Power",
            description="Modbus CT power",
            value=-2800.0,
            raw_value=-2800.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )
        mb_field.last_updated = t0

        # Step 2: MQTT update at t1 (more recent than Modbus)
        t1 = time.time() - 1.0
        mqtt_field = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="grid_power_w",
            label="Grid Net Power",
            description="MQTT grid power",
            value=2810.0,
            raw_value=2810.0,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        mqtt_field.last_updated = t1

        # Retrieve compound view for grid_power
        c_view = self.state.get_compound_view("grid_power")
        self.assertIsNotNone(c_view)

        # Verify all 3 values:
        # 1. Latest value is MQTT (+2810.0) because t1 > t0
        self.assertEqual(c_view.latest_value, 2810.0)
        self.assertEqual(c_view.latest_source, FieldSource.MQTT_PUSH.value)

        # 2. MQTT value
        self.assertEqual(c_view.mqtt_value, 2810.0)

        # 3. Modbus value with transform applied (-1 * -2800 = +2800.0)
        self.assertEqual(c_view.modbus_value, 2800.0)
        self.assertEqual(c_view.modbus_raw_value, -2800.0)

        # Verify delta computation (2810 - 2800 = 10)
        self.assertAlmostEqual(c_view.delta, 10.0, places=1)
        self.assertGreater(c_view.match_pct, 99.0)

        # Step 3: Now simulate a new Modbus poll arriving at t2 (newer than MQTT)
        t2 = time.time()
        mb_field2 = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="CTPow",
            label="Inverter CT Power",
            description="Modbus CT power",
            value=-2950.0,
            raw_value=-2950.0,
            units="W",
            source=FieldSource.MODBUS_POLL,
            sub_group="inverter_status",
        )
        mb_field2.last_updated = t2

        c_view_updated = self.state.get_compound_view("grid_power")
        # Now Latest value must switch to Modbus (+2950.0) because t2 > t1!
        self.assertEqual(c_view_updated.latest_value, 2950.0)
        self.assertEqual(c_view_updated.latest_source, FieldSource.MODBUS_POLL.value)
        self.assertEqual(c_view_updated.mqtt_value, 2810.0)
        self.assertEqual(c_view_updated.modbus_value, 2950.0)

    def test_compound_subscriber_notified_on_either_source(self):
        """Verify compound subscribers are notified when either MQTT or Modbus updates."""
        received_views = []
        self.state.subscribe_compound(lambda v: received_views.append(v))

        # Modbus update
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="SoC",
            label="Battery State of Charge",
            description="Battery SoC",
            value=82.5,
            raw_value=82.5,
            units="%",
            source=FieldSource.MODBUS_POLL,
            sub_group="model_802",
        )
        self.assertEqual(len(received_views), 1)
        self.assertEqual(received_views[0].mapping_id, "battery_soc")
        self.assertEqual(received_views[0].latest_value, 82.5)

        # MQTT update
        self.state.set_field(
            device_sn=self.bat.serial_number,
            name="state_of_charge",
            label="State of Charge",
            description="Live SoC",
            value=83.0,
            raw_value=83.0,
            units="%",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        self.assertEqual(len(received_views), 2)
        self.assertEqual(received_views[1].mapping_id, "battery_soc")
        self.assertEqual(received_views[1].latest_value, 83.0)

    def test_api_device_compound_fields_and_mappings(self):
        """Test API endpoints for compound fields and mappings."""
        client = PwrcellClient(is_mock=True)
        client.start()
        try:
            app = create_app(client)
            test_client = app.test_client()

            # 1. Device details includes compound_fields
            resp = test_client.get("/api/devices/0001000714E9")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn("compound_fields", data)
            compound_fields = data["compound_fields"]
            self.assertGreater(len(compound_fields), 0)

            # Check grid_power compound field contains 3 values
            gp = next((c for c in compound_fields if c["mapping_id"] == "grid_power"), None)
            self.assertIsNotNone(gp)
            self.assertIn("latest_value", gp)
            self.assertIn("latest_source", gp)
            self.assertIn("mqtt_value", gp)
            self.assertIn("modbus_value", gp)

            # 2. GET /api/mappings
            map_resp = test_client.get("/api/mappings")
            self.assertEqual(map_resp.status_code, 200)
            map_data = map_resp.get_json()
            self.assertIn("mappings", map_data)
            mappings = map_data["mappings"]
            self.assertGreater(len(mappings), 5)
            self.assertTrue(any(m["id"] == "grid_power" for m in mappings))
        finally:
            client.stop()


if __name__ == "__main__":
    unittest.main()
