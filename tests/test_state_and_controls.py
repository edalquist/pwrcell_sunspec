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
        field = self.beacon.fields.get("rebus_beacon.REbus_dir.SysMd")
        self.assertEqual(field.value, "SELF_SUPPLY")
        self.assertEqual(field.raw_value, 2)

        # Write case-insensitive
        res3 = self.controls.write_field("rebus_beacon.REbus_dir.SysMd", "clean_backup")
        self.assertEqual(res3, "CLEAN_BACKUP")
        field = self.beacon.fields.get("rebus_beacon.REbus_dir.SysMd")
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

    def test_sunspec_sentinels_evaluated_to_none(self):
        # 1. int16 sentinel 0x8000 (32768) with scale factor -2
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"A": 0x8000, "A_SF": -2},
            computed_values={"A": -327.68, "A_SF": -2},
        )
        a_field = self.bat.fields.get("battery.battery.A")
        self.assertIsNotNone(a_field)
        self.assertIsNone(a_field.value)
        self.assertIsNone(a_field.raw_value)

        # 2. uint16 sentinel 0xFFFF (65535)
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"SoC": 0xFFFF, "SoC_SF": -2},
            computed_values={"SoC": 655.35, "SoC_SF": -2},
        )
        soc_field = self.bat.fields.get("battery.battery.SoC")
        self.assertIsNotNone(soc_field)
        self.assertIsNone(soc_field.value)
        self.assertIsNone(soc_field.raw_value)

        # 3. None cvalue from sunspec2
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"SoCMax": 100},
            computed_values={"SoCMax": None},
        )
        socmax_field = self.bat.fields.get("battery.battery.SoCMax")
        self.assertIsNotNone(socmax_field)
        self.assertIsNone(socmax_field.value)
        self.assertIsNone(socmax_field.raw_value)

    def test_nan_equality_does_not_loop_notifications(self):
        notified = []
        def listener(f):
            notified.append(f.key)

        self.state.subscribe(listener)
        try:
            # Set NaN first time -> normalized to None on creation and notifies once
            f1 = self.state.set_field(
                device_sn=self.inv.serial_number,
                name="nan_test",
                value=float("nan"),
                raw_value=float("nan"),
            )
            self.assertIsNone(f1.value)
            self.assertIsNone(f1.raw_value)
            self.assertEqual(len(notified), 1)

            # Set NaN second time -> normalized to None again; None == None so does not re-notify
            f2 = self.state.set_field(
                device_sn=self.inv.serial_number,
                name="nan_test",
                value=float("nan"),
                raw_value=float("nan"),
            )
            self.assertIsNone(f2.value)
            self.assertIsNone(f2.raw_value)
            self.assertEqual(len(notified), 1)
        finally:
            self.state.unsubscribe(listener)

    def test_state_store_unsubscription(self):
        calls = 0
        def listener(f):
            nonlocal calls
            calls += 1

        self.state.subscribe(listener)
        self.state.set_field(device_sn=self.inv.serial_number, name="test_sub", value=1)
        self.assertEqual(calls, 1)

        self.state.unsubscribe(listener)
        self.state.set_field(device_sn=self.inv.serial_number, name="test_sub", value=2)
        self.assertEqual(calls, 1)

        # Compound unsubscribe
        c_calls = 0
        def c_listener(c):
            nonlocal c_calls
            c_calls += 1

        self.state.subscribe_compound(c_listener)
        self.state.set_field(device_sn=self.inv.serial_number, name="grid_power_w", value=100.0, sub_group="live")
        self.assertGreaterEqual(c_calls, 1)

        prev_c_calls = c_calls
        self.state.unsubscribe_compound(c_listener)
        self.state.set_field(device_sn=self.inv.serial_number, name="grid_power_w", value=200.0, sub_group="live")
        self.assertEqual(c_calls, prev_c_calls)

    def test_find_fields_thread_safety(self):
        import threading
        stop_threads = False

        def writer():
            idx = 0
            while not stop_threads:
                self.state.set_field(
                    device_sn=self.inv.serial_number,
                    name=f"dyn_{idx % 20}",
                    value=idx,
                    sub_group="dynamic",
                )
                idx += 1

        t = threading.Thread(target=writer)
        t.start()
        try:
            for _ in range(50):
                fields = self.state.find_fields("inverter.dynamic.*")
                self.assertIsInstance(fields, list)
        finally:
            stop_threads = True
            t.join()

    def test_validate_field_value_bounds(self):
        """Test physical plausibility validation across voltage, frequency, power, etc."""
        from pwrcell.state import validate_field_value

        # Voltage
        self.assertIsNone(validate_field_value(8225.0, units="V", name="PhVphA"))
        self.assertIsNone(validate_field_value(-20.0, units="V", name="PhVphA"))
        self.assertIsNone(validate_field_value(2500.0, units="V", name="DCV"))
        self.assertEqual(validate_field_value(121.1, units="V", name="PhVphA"), 121.1)
        self.assertEqual(validate_field_value(240.2, units="V", name="PPVphAB"), 240.2)
        self.assertEqual(validate_field_value(381.7, units="V", name="V"), 381.7)
        self.assertEqual(validate_field_value(0.0, units="V", name="PhVphA"), 0.0)

        # Frequency
        self.assertIsNone(validate_field_value(5998.0, units="Hz", name="Hz"))
        self.assertIsNone(validate_field_value(-5.0, units="Hz", name="Hz"))
        self.assertIsNone(validate_field_value(120.0, units="Hz", name="Hz"))
        self.assertEqual(validate_field_value(60.0, units="Hz", name="Hz"), 60.0)
        self.assertEqual(validate_field_value(10.0, units="Hz", name="Hz"), 10.0)
        self.assertEqual(validate_field_value(0.0, units="Hz", name="Hz"), 0.0)

        # Percentage / Battery
        self.assertIsNone(validate_field_value(655.35, units="%", name="SoC"))
        self.assertIsNone(validate_field_value(-5.0, units="%", name="SoC"))
        self.assertIsNone(validate_field_value(130.0, units="%", name="state_of_charge"))
        self.assertEqual(validate_field_value(85.0, units="%", name="SoC"), 85.0)
        self.assertEqual(validate_field_value(100.0, units="%", name="SoH"), 100.0)

        # Temperature
        self.assertIsNone(validate_field_value(300.0, units="°C", name="TmpSnk"))
        self.assertIsNone(validate_field_value(-70.0, units="C", name="TmpCab"))
        self.assertEqual(validate_field_value(45.6, units="°C", name="TmpSnk"), 45.6)
        self.assertEqual(validate_field_value(-15.0, units="°C", name="TmpCab"), -15.0)

        # Power (up to 1,000,000 W / 1 MW)
        self.assertIsNone(validate_field_value(2000000.0, units="W", name="grid_power_w"))
        self.assertIsNone(validate_field_value(-1500000.0, units="W", name="W"))
        self.assertEqual(validate_field_value(64554.0, units="W", name="WChaRteMax"), 64554.0)
        self.assertEqual(validate_field_value(64554.0, units="W", name="WDisChaRteMax"), 64554.0)
        self.assertEqual(validate_field_value(7600.0, units="W", name="W"), 7600.0)
        self.assertEqual(validate_field_value(-3500.0, units="W", name="grid_power_w"), -3500.0)

        # Current (up to 1,000 A)
        self.assertIsNone(validate_field_value(1500.0, units="A", name="A"))
        self.assertEqual(validate_field_value(25.5, units="A", name="AphA"), 25.5)
        self.assertEqual(validate_field_value(400.0, units="A", name="A"), 400.0)

    def test_total_increasing_monotonicity_drop_protection(self):
        """Verify that total_increasing cumulative energy counters reject corrupt drops to zero."""
        from pwrcell.catalog import HomeAssistantHint

        hint = HomeAssistantHint(platform="sensor", device_class="energy", state_class="total_increasing", unit_of_measurement="Wh")
        # Establish initial high cumulative energy
        f = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhIn",
            value=23491891,
            units="Wh",
            ha_hint=hint,
        )
        self.assertEqual(f.value, 23491891)

        # Modbus glitch or reboot returns 0 -> should be suppressed
        f2 = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhIn",
            value=0,
            units="Wh",
            ha_hint=hint,
        )
        self.assertEqual(f2.value, 23491891)

        # Negative value -> should be suppressed
        f3 = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhIn",
            value=-500,
            units="Wh",
            ha_hint=hint,
        )
        self.assertEqual(f3.value, 23491891)

        # Small valid increase -> should be accepted
        f4 = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="WhIn",
            value=23492000,
            units="Wh",
            ha_hint=hint,
        )
        self.assertEqual(f4.value, 23492000)

        # N=3 consecutive consistent lower positive readings (e.g. after a single high glitch or legitimate reset) must recover instead of latching forever
        f_drop1 = self.state.set_field(device_sn=self.inv.serial_number, name="WhIn", value=500000, units="Wh", ha_hint=hint)
        self.assertEqual(f_drop1.value, 23492000)
        f_drop2 = self.state.set_field(device_sn=self.inv.serial_number, name="WhIn", value=500010, units="Wh", ha_hint=hint)
        self.assertEqual(f_drop2.value, 23492000)
        f_drop3 = self.state.set_field(device_sn=self.inv.serial_number, name="WhIn", value=500020, units="Wh", ha_hint=hint)
        self.assertEqual(f_drop3.value, 500020)

    def test_pvlink_daily_energy_reset_allowed(self):
        """Verify that PV link daily/session energy counters are allowed to reset at sunrise."""
        from pwrcell.catalog import HomeAssistantHint

        pv_link = self.state.register_device(
            serial_number="000100034AC7",
            slave_id=3,
            device_type="pv_link",
            model_name="PV Link",
        )
        hint = HomeAssistantHint(platform="sensor", device_class="energy", state_class="total_increasing", unit_of_measurement="Wh")
        # Yesterday's energy reaches 4456 Wh
        f = self.state.set_field(
            device_sn=pv_link.serial_number,
            name="E",
            value=4456,
            units="Wh",
            ha_hint=hint,
            sub_group="REbus_status",
        )
        self.assertEqual(f.value, 4456)

        # Morning reset: PV link wakes up and reports 0 or session start 658 Wh
        f_reset = self.state.set_field(
            device_sn=pv_link.serial_number,
            name="E",
            value=658,
            units="Wh",
            ha_hint=hint,
            sub_group="REbus_status",
        )
        self.assertEqual(f_reset.value, 658)

        # Model 404 DCWh also resets
        f_dcwh = self.state.set_field(
            device_sn=pv_link.serial_number,
            name="DCWh",
            value=4454,
            units="Wh",
            ha_hint=hint,
            sub_group="string_combiner",
        )
        self.assertEqual(f_dcwh.value, 4454)

        f_dcwh_reset = self.state.set_field(
            device_sn=pv_link.serial_number,
            name="DCWh",
            value=698,
            units="Wh",
            ha_hint=hint,
            sub_group="string_combiner",
        )
        self.assertEqual(f_dcwh_reset.value, 698)

    def test_telemetry_snapshot_publishes_zero_grid_voltage_and_limits(self):
        """Zero grid voltage (outage) and zero charge/discharge limits must update state rather than leaving stale values."""
        from pwrcell.mqtt import ChannelTelemetry, LiveTelemetrySnapshot

        # 1. Normal grid voltage (240V) and battery limits (4500W)
        snap_normal = LiveTelemetrySnapshot(
            timestamp=1000.0,
            system_mode=2,
            system_mode_name="SELF_SUPPLY",
            inverter_state=2080,
            inverter_state_name="GRID_CONNECTED",
            channels={
                1: ChannelTelemetry(
                    channel=1,
                    channel_type=1,
                    channel_type_name="NET_GRID",
                    real_power_w=500.0,
                    voltage_v=240.2,
                    imported_energy_ws=3600000,
                    exported_energy_ws=0,
                    device_id="",
                    device_type=0,
                ),
                4: ChannelTelemetry(
                    channel=4,
                    channel_type=4,
                    channel_type_name="STORAGE_BATTERY",
                    real_power_w=0.0,
                    voltage_v=380.0,
                    imported_energy_ws=3600000,
                    exported_energy_ws=3600000,
                    device_id=self.bat.serial_number,
                    device_type=1,
                    real_power_source_max_w=4500.0,
                    real_power_sink_max_w=4500.0,
                ),
            },
        )
        self.state.update_from_telemetry_snapshot(snap_normal)
        self.assertEqual(self.inv.fields["inverter.live.grid_voltage_v"].value, 240.2)
        self.assertEqual(self.bat.fields["battery.live.max_charge_power_w"].value, 4500.0)
        self.assertEqual(self.bat.fields["battery.live.max_discharge_power_w"].value, 4500.0)

        # 2. Grid outage (voltage_v == 0.0) and battery full (sink_max_w == 0.0)
        snap_outage = LiveTelemetrySnapshot(
            timestamp=1005.0,
            system_mode=2,
            system_mode_name="SELF_SUPPLY",
            inverter_state=0,
            inverter_state_name="UNKNOWN",
            channels={
                1: ChannelTelemetry(
                    channel=1,
                    channel_type=1,
                    channel_type_name="NET_GRID",
                    real_power_w=0.0,
                    voltage_v=0.0,
                    imported_energy_ws=3600000,
                    exported_energy_ws=0,
                    device_id="",
                    device_type=0,
                ),
                4: ChannelTelemetry(
                    channel=4,
                    channel_type=4,
                    channel_type_name="STORAGE_BATTERY",
                    real_power_w=0.0,
                    voltage_v=0.0,
                    imported_energy_ws=3600000,
                    exported_energy_ws=3600000,
                    device_id=self.bat.serial_number,
                    device_type=1,
                    real_power_source_max_w=0.0,
                    real_power_sink_max_w=0.0,
                ),
            },
        )
        self.state.update_from_telemetry_snapshot(snap_outage)
        self.assertEqual(self.inv.fields["inverter.live.grid_voltage_v"].value, 0.0)
        self.assertEqual(self.inv.fields["inverter.live.inverter_state"].value, 0)
        self.assertEqual(self.bat.fields["battery.live.battery_voltage_v"].value, 0.0)
        self.assertEqual(self.bat.fields["battery.live.max_charge_power_w"].value, 0.0)
        self.assertEqual(self.bat.fields["battery.live.max_discharge_power_w"].value, 0.0)

    def test_update_from_modbus_points_accepts_list_for_bitfield(self):
        """Passing a list as raw_val for a bitfield point must not raise TypeError on SUNSPEC_SENTINELS membership."""
        # Model 802 has bitfield point Evt1
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"Evt1": ["COMMUNICATION_ERROR"]},
        )
        evt_field = self.bat.fields.get("battery.battery.Evt1")
        self.assertIsNotNone(evt_field)
        self.assertEqual(evt_field.active_flags, ["COMMUNICATION_ERROR"])

    def test_write_scaled_numeric_register_preserves_decimals_and_ha_bounds(self):
        """Writing a decimal to a scaled RW register (e.g. SF=-1) must preserve the scaled value and compute raw register value, and HA discovery must use real bounds."""
        from unittest.mock import MagicMock
        from pwrcell.ha import generate_discovery_payload

        # Model 802 has SoCMax (uint16, RW, sf='SoC_SF', units='%WHRtg')
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"SoCMax": 900, "SoC_SF": -1},
            computed_values={"SoCMax": 90.0, "SoC_SF": -1},
        )
        socmax_field = self.bat.fields.get("battery.battery.SoCMax")
        self.assertIsNotNone(socmax_field)
        self.assertEqual(socmax_field.value, 90.0)

        # Verify HA discovery payload uses real scaled bounds (min=0.0, max=6553.5, step=0.1)
        disc = generate_discovery_payload(socmax_field, self.bat)
        self.assertEqual(disc["platform"], "number")
        self.assertEqual(disc["payload"]["step"], 0.1)
        self.assertEqual(disc["payload"]["min"], 0.0)
        self.assertEqual(disc["payload"]["max"], 6553.5)

        # Attach mock modbus client to verify what value is sent to write_point_value
        mock_mb = MagicMock()
        mock_mb.write_point_value.return_value = 50.5
        self.controls.modbus_client = mock_mb

        res = self.controls.write_field("battery.battery.SoCMax", 50.5)
        self.assertEqual(res, 50.5)
        socmax_field = self.bat.fields.get("battery.battery.SoCMax")
        self.assertEqual(socmax_field.value, 50.5)
        self.assertEqual(socmax_field.raw_value, 505)
        # write_point_value assigns point.cvalue = value, so it expects the scaled engineering value 50.5
        mock_mb.write_point_value.assert_called_once()
        _, kwargs = mock_mb.write_point_value.call_args
        self.assertEqual(kwargs["value"], 50.5)

    def test_write_readback_verification_publishes_clamped_value(self):
        """If the device clamps or overrides a written value on read-back, log a warning and publish the read-back value."""
        from unittest.mock import MagicMock

        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=802,
            raw_values={"SoCMax": 900, "SoC_SF": -1},
            computed_values={"SoCMax": 90.0, "SoC_SF": -1},
        )

        # Simulate device clamping 95.0 down to 80.0 on read-back
        mock_mb = MagicMock()
        mock_mb.write_point_value.return_value = 80.0
        self.controls.modbus_client = mock_mb

        res = self.controls.write_field("battery.battery.SoCMax", 95.0)
        self.assertEqual(res, 80.0)
        socmax_field = self.bat.fields.get("battery.battery.SoCMax")
        self.assertEqual(socmax_field.value, 80.0)
        self.assertEqual(socmax_field.raw_value, 800)

    def test_type_aware_sentinels_do_not_drop_valid_uint32_or_scaled_values(self):
        """A uint32/acc32 register at 32768 or 65535, or a scaled float like 32767.4, must NOT be dropped as a 16-bit sentinel."""
        from pwrcell.bridge import format_state_value
        from pwrcell.state import is_sunspec_sentinel

        # 1. Type-aware sentinel helper
        self.assertTrue(is_sunspec_sentinel(0x8000, "int16"))
        self.assertTrue(is_sunspec_sentinel(-32768, "int16"))
        self.assertTrue(is_sunspec_sentinel(0xFFFF, "uint16"))
        self.assertFalse(is_sunspec_sentinel(0x7FFF, "int16"))  # 32767 is max int16, not sentinel
        self.assertFalse(is_sunspec_sentinel(0xFFFF, "uint32"))
        self.assertFalse(is_sunspec_sentinel(0x8000, "acc32"))
        self.assertTrue(is_sunspec_sentinel(0xFFFFFFFF, "acc32"))
        self.assertTrue(is_sunspec_sentinel(0x80000000, "int32"))

        # 2. Model 64209 WhIn is uint32/acc32: raw value 65535 or 32768 is a valid cumulative Wh reading
        self.state.update_from_modbus_points(
            serial_number=self.bat.serial_number,
            model_id=64209,
            raw_values={"WhIn": 65535, "WhOut": 32768},
            computed_values={"WhIn": 65535, "WhOut": 32768},
        )
        self.assertEqual(self.bat.fields["battery.battery_status.WhIn"].value, 65535)
        self.assertEqual(self.bat.fields["battery.battery_status.WhOut"].value, 32768)

        # 3. Post-scaling values that happen to have int(val) == 32767 or 65535 are NOT dropped
        f_power = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="W",
            value=32767.4,
            raw_value=327674,
            units="W",
        )
        self.assertEqual(f_power.value, 32767.4)
        self.assertEqual(format_state_value(32767.4), "32767.4")
        self.assertEqual(format_state_value(65535), "65535")

    def test_register_device_blank_serials_do_not_collide(self):
        """Two devices with empty/blank serial numbers on different slave IDs must be assigned distinct synthetic serials."""
        d1 = self.state.register_device(serial_number="", slave_id=11, device_type="pv_link", model_name="PV Link")
        d2 = self.state.register_device(serial_number="0", slave_id=12, device_type="pv_link", model_name="PV Link")
        self.assertNotEqual(d1.serial_number, d2.serial_number)
        self.assertIn(d1.serial_number, self.state.devices)
        self.assertIn(d2.serial_number, self.state.devices)

    def test_state_field_replaced_immutably_and_controls_route_through_set_field(self):
        """set_field and ControlDispatcher writes must replace StateField instances rather than mutating in place, and snapshot helpers must work under lock."""
        f1 = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="SysMd",
            value="SELF_SUPPLY",
            raw_value=2,
            sub_group="inverter_status",
        )
        f2 = self.state.set_field(
            device_sn=self.inv.serial_number,
            name="SysMd",
            value="CLEAN_BACKUP",
            raw_value=3,
            sub_group="inverter_status",
        )
        # f1 is an immutable snapshot and must not be mutated when f2 is stored
        self.assertIsNot(f1, f2)
        self.assertEqual(f1.value, "SELF_SUPPLY")
        self.assertEqual(f2.value, "CLEAN_BACKUP")

        # ControlDispatcher.set_system_mode must also update inverter.inverter_status.SysMd via set_field (replacing f2)
        self.controls.set_system_mode("PRIORITY_BACKUP")
        f3 = self.inv.fields.get("inverter.inverter_status.SysMd")
        self.assertIsNot(f2, f3)
        self.assertEqual(f2.value, "CLEAN_BACKUP")
        self.assertEqual(f3.value, "PRIORITY_BACKUP")

        # Snapshot helpers
        devs = self.state.get_devices_snapshot()
        self.assertEqual(len(devs), 3)
        self.assertEqual(self.state.get_device(self.inv.serial_number.lower()), self.inv)


if __name__ == "__main__":
    unittest.main()

