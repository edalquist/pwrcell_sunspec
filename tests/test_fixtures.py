"""Unit tests for pwrcell.fixtures."""

import unittest
from pwrcell.fixtures import MockFixtureLoader, MockTelemetryGenerator
from pwrcell.protos import energy_record_set_pb2


class TestMockFixtures(unittest.TestCase):

    def setUp(self):
        self.loader = MockFixtureLoader()

    def test_mock_loader_finds_all_devices(self):
        self.assertEqual(len(self.loader.devices), 9)
        self.assertIn(1, self.loader.devices_by_slave_id)
        self.assertIn(8, self.loader.devices_by_slave_id)
        self.assertIn(9, self.loader.devices_by_slave_id)

    def test_inverter_device_loaded(self):
        inverter = self.loader.devices_by_slave_id[8]
        self.assertEqual(inverter.device_type, "inverter")
        self.assertEqual(inverter.manufacturer, "Generac")
        self.assertEqual(inverter.serial_number, "0001000714E9")
        
        # Test scale factor calculation
        v_pt = inverter.get_point_value(64207, "V")
        self.assertIsNotNone(v_pt)
        self.assertEqual(v_pt.raw_value, 3817)
        self.assertEqual(v_pt.scale_factor, -1)
        self.assertEqual(v_pt.scaled_value, 381.7)
        self.assertEqual(v_pt.units, "V")

    def test_battery_device_loaded(self):
        battery = self.loader.devices_by_slave_id[9]
        self.assertEqual(battery.device_type, "battery")
        self.assertEqual(battery.serial_number, "000100082128")

    def test_telemetry_generator(self):
        gen = MockTelemetryGenerator()
        rec_set = gen.tick(2.0)
        self.assertIsNotNone(rec_set)
        self.assertEqual(rec_set.inverterId, "0001000714E9")
        self.assertEqual(len(rec_set.energyRecord), 1)

        rec = rec_set.energyRecord[0]
        self.assertEqual(len(rec.channel), 5)

        # Check that Net, Generation, Consumption, Storage channels exist
        channel_types = [ch.channelType for ch in rec.channel]
        self.assertIn(energy_record_set_pb2.NET, channel_types)
        self.assertIn(energy_record_set_pb2.GENERATION, channel_types)
        self.assertIn(energy_record_set_pb2.CONSUMPTION, channel_types)
        self.assertIn(energy_record_set_pb2.STORAGE, channel_types)

        # Battery channel SoC
        storage_ch = next(ch for ch in rec.channel if ch.channelType == energy_record_set_pb2.STORAGE)
        self.assertGreater(storage_ch.soc, 0.0)
        self.assertLessEqual(storage_ch.soc, 100.0)


if __name__ == "__main__":
    unittest.main()
