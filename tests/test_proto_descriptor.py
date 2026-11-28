"""Unit tests for the version-independent protobuf descriptor loader and drift checker."""

import importlib
import shutil
import tempfile
import unittest
from pathlib import Path

from google.protobuf import text_format
from google.protobuf.unknown_fields import UnknownFieldSet

from pwrcell.protos import energy_record_set_pb2
from util.proto_descriptor import (
    DEFAULT_DESC_PATH,
    DEFAULT_PROTO_PATH,
    check_descriptor,
)


class TestEnergyRecordSetPb2Loader(unittest.TestCase):
    """Verify energy_record_set_pb2 exposes the full pb2 API without version lock-in."""

    def test_expected_messages_enums_and_constants_present(self):
        self.assertTrue(hasattr(energy_record_set_pb2, "DESCRIPTOR"))

        for msg_name in ("EnergyRecordSet", "EnergyRecord", "ChannelSample", "GatewayInfo"):
            self.assertTrue(hasattr(energy_record_set_pb2, msg_name), f"Missing message {msg_name}")

        for enum_name in (
            "ChannelType",
            "EnergyDeviceType",
            "AnomalyCode",
            "SystemMode",
            "GatewayType",
            "SystemFamily",
            "InverterState",
        ):
            self.assertTrue(hasattr(energy_record_set_pb2, enum_name), f"Missing enum {enum_name}")

        expected_constants = {
            "NET": 1,
            "GENERATION": 2,
            "CONSUMPTION": 3,
            "STORAGE": 4,
            "BATTERY": 1,
            "SELF_SUPPLY": 2,
            "SYSTEM_FAMILY_PWRCELL_R1": 1,
            "GATEWAY_TYPE_BEACON": 1,
            "INVERTER_STATE_GRID_CONNECTED": 2080,
        }
        for const_name, expected_val in expected_constants.items():
            self.assertEqual(getattr(energy_record_set_pb2, const_name), expected_val)

    def test_enum_wrapper_methods_and_errors(self):
        ch_type = energy_record_set_pb2.ChannelType
        self.assertGreater(len(ch_type.DESCRIPTOR.values), 0)
        self.assertEqual(ch_type.Name(1), "NET")
        self.assertEqual(ch_type.Value("NET"), 1)
        self.assertEqual(ch_type.NET, 1)
        self.assertIn("NET", ch_type.keys())
        self.assertIn(1, ch_type.values())
        self.assertIn(("NET", 1), ch_type.items())

        with self.assertRaises(ValueError):
            ch_type.Name(999999)
        with self.assertRaises(ValueError):
            ch_type.Value("DOES_NOT_EXIST")
        with self.assertRaises(AttributeError):
            _ = ch_type.DOES_NOT_EXIST

    def test_wire_roundtrip_unknown_fields_and_text_format(self):
        msg = energy_record_set_pb2.EnergyRecordSet()
        msg.inverterId = "000100070008"
        msg.isHighFrequency = True
        msg.systemFamily = energy_record_set_pb2.SYSTEM_FAMILY_PWRCELL_R1
        msg.gatewayInfo.gateway_id = "000100120001"
        msg.gatewayInfo.gateway_type = energy_record_set_pb2.GATEWAY_TYPE_BEACON

        rec = msg.energyRecord.add()
        rec.currentTimestamp = 1700000000.5
        rec.sysMode = energy_record_set_pb2.SELF_SUPPLY
        rec.inverterState = energy_record_set_pb2.INVERTER_STATE_GRID_CONNECTED

        ch = rec.channel.add()
        ch.channel = 1
        ch.channelType = energy_record_set_pb2.NET
        ch.realPower_W = -450
        ch.realPower_Wf = -450.5

        # Append an unknown varint field #99: tag=(99<<3)|0=792 (0x98 0x06), value=42 (0x2a)
        wire_bytes = msg.SerializeToString() + bytes([0x98, 0x06, 0x2A])

        parsed = energy_record_set_pb2.EnergyRecordSet()
        parsed.ParseFromString(wire_bytes)

        self.assertTrue(parsed.HasField("gatewayInfo"))
        self.assertEqual(parsed.gatewayInfo.gateway_id, "000100120001")
        self.assertEqual(parsed.gatewayInfo.gateway_type, energy_record_set_pb2.GATEWAY_TYPE_BEACON)
        self.assertEqual(len(parsed.energyRecord), 1)
        self.assertEqual(parsed.energyRecord[0].channel[0].realPower_W, -450)

        ufs = list(UnknownFieldSet(parsed))
        self.assertEqual(len(ufs), 1)
        self.assertEqual(ufs[0].field_number, 99)
        self.assertEqual(ufs[0].data, 42)

        text = text_format.MessageToString(parsed)
        self.assertIn("000100070008", text)

    def test_module_reload_succeeds(self):
        reloaded = importlib.reload(energy_record_set_pb2)
        self.assertEqual(reloaded.NET, 1)

    def test_no_runtime_version_lock_or_internal_imports(self):
        source = Path(energy_record_set_pb2.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ValidateProtobufRuntimeVersion", source)
        self.assertNotIn("google.protobuf.internal", source)


class TestProtoDescriptorDriftCheck(unittest.TestCase):
    """Verify util.proto_descriptor.check_descriptor detects .proto/.desc drift."""

    def test_committed_descriptor_in_sync_with_proto(self):
        if shutil.which("protoc") is None:
            self.skipTest("protoc not installed")
        ok, message = check_descriptor(DEFAULT_PROTO_PATH, DEFAULT_DESC_PATH)
        self.assertTrue(ok, message)

    def test_modified_proto_triggers_drift_failure(self):
        if shutil.which("protoc") is None:
            self.skipTest("protoc not installed")

        proto_text = DEFAULT_PROTO_PATH.read_text(encoding="utf-8")
        modified_text = proto_text.replace(
            "GATEWAY_TYPE_PENGUIN = 2;",
            "GATEWAY_TYPE_PENGUIN = 2;\n  GATEWAY_TYPE_TEST_DRIFT = 3;",
        )
        self.assertNotEqual(proto_text, modified_text)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_proto = Path(tmpdir) / "energy_record_set.proto"
            tmp_proto.write_text(modified_text, encoding="utf-8")
            ok, diff_message = check_descriptor(tmp_proto, DEFAULT_DESC_PATH)

        self.assertFalse(ok)
        self.assertIn("GATEWAY_TYPE_TEST_DRIFT", diff_message)


if __name__ == "__main__":
    unittest.main()
