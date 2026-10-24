"""Unit tests for pwrcell.bridge HomeAssistantBridge."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from pwrcell.bridge import HomeAssistantBridge, format_state_value
from pwrcell.client import PwrcellClient
from pwrcell.ha import generate_discovery_payload


class TestHomeAssistantBridge(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.topics_file = Path(self.tmp_dir.name) / ".ha_published_topics.json"
        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.bridge = HomeAssistantBridge(client=self.client, published_topics_path=self.topics_file)
        self.mock_mqttc = MagicMock()
        self.bridge._mqttc = self.mock_mqttc

    def tearDown(self):
        self.client.stop()
        self.tmp_dir.cleanup()

    def test_publish_discovery_pre_populates_unpolled_devices(self):
        """Verify that devices without pre-existing polled fields (e.g. PV Links) have discovery published."""
        # Register a fresh PV link device with empty fields
        pv_dev = self.client.state.register_device(
            serial_number="TEST_PVLINK_01",
            slave_id=20,
            device_type="pv_link",
            model_name="PV Link",
        )
        self.assertEqual(len(pv_dev.fields), 0)

        # Select a field on this PV link
        self.bridge.selected_field_keys = ["TEST_PVLINK_01:pv_link.REbus_status.P"]
        self.bridge.publish_discovery()

        # The field definition should now be instantiated and discovery published
        self.assertIn("pv_link.REbus_status.P", pv_dev.fields)
        expected_topic = "homeassistant/sensor/pwrcell_test_pvlink_01/rebus_status_p/config"
        self.assertIn(expected_topic, self.bridge._published_discovery_topics)

        # Verify MQTT publish call
        matching_calls = [
            call for call in self.mock_mqttc.publish.call_args_list
            if call[0][0] == expected_topic
        ]
        self.assertTrue(matching_calls)
        payload = json.loads(matching_calls[0][0][1])
        self.assertEqual(payload["device_class"], "power")
        self.assertEqual(payload["unit_of_measurement"], "W")
        self.assertEqual(payload.get("suggested_display_precision"), 0)
        self.assertEqual(payload["device"]["name"], "PWRcell PV Link (K_01)")

    def test_on_field_update_auto_discovers_unseen_field(self):
        """Verify that when a newly polled field updates, discovery config is published if not already sent."""
        # Subscribe bridge to field updates
        self.client.state.subscribe(self.bridge._on_field_update)

        # Clean published topics
        self.bridge._published_discovery_topics.clear()
        self.bridge.selected_field_keys = ["0001000714E9:inverter.inverter.A"]

        # Update field in state
        field = self.client.state.set_field(
            device_sn="0001000714E9",
            name="A",
            sub_group="inverter",
            value=12.5,
            label="Inverter Current",
        )

        expected_config_topic = "homeassistant/sensor/pwrcell_0001000714e9/inverter_a/config"
        self.assertIn(expected_config_topic, self.bridge._published_discovery_topics)

        # Both discovery config and state should have been published
        topics_published = [call[0][0] for call in self.mock_mqttc.publish.call_args_list]
        self.assertIn(expected_config_topic, topics_published)
        self.assertIn("pwrcell/0001000714e9/inverter_a/state", topics_published)

    def test_deduplication_suppresses_raw_field_discovery(self):
        """Verify that when a compound field is active, the backing raw live field is suppressed and cleared."""
        inv = self.client.state.get_inverter()
        self.assertIsNotNone(inv)
        sn = inv.serial_number

        # Select live system mode, which matches compound system_mode via mqtt_key
        self.bridge.selected_field_keys = [f"{sn}:inverter.live.system_mode"]
        self.bridge.publish_discovery()

        published_topics_with_payload = {
            call[0][0]: call[0][1] for call in self.mock_mqttc.publish.call_args_list
        }

        compound_config_topic = f"homeassistant/select/pwrcell_{sn.lower()}/compound_system_mode/config"
        raw_config_topic = f"homeassistant/sensor/pwrcell_{sn.lower()}/live_system_mode/config"

        # Compound discovery config must be published with non-empty payload
        self.assertIn(compound_config_topic, published_topics_with_payload)
        self.assertNotEqual(published_topics_with_payload[compound_config_topic], "")

        # Raw discovery config must be suppressed / cleared with empty payload to delete from HA
        self.assertIn(raw_config_topic, published_topics_with_payload)
        self.assertEqual(published_topics_with_payload[raw_config_topic], "")

    def test_deduplication_suppresses_raw_field_update(self):
        """Verify that _on_field_update does not publish state for a suppressed raw field."""
        inv = self.client.state.get_inverter()
        self.assertIsNotNone(inv)
        sn = inv.serial_number

        self.client.state.subscribe(self.bridge._on_field_update)
        self.bridge.selected_field_keys = [f"{sn}:inverter.live.system_mode"]
        self.bridge.publish_discovery()
        self.mock_mqttc.publish.reset_mock()

        # Update raw live field
        self.client.state.set_field(
            device_sn=sn,
            name="system_mode",
            sub_group="live",
            value="Clean Backup",
        )

        raw_state_topic = f"pwrcell/{sn.lower()}/live_system_mode/state"
        published_topics = [call[0][0] for call in self.mock_mqttc.publish.call_args_list]
        self.assertNotIn(raw_state_topic, published_topics)

    def test_persistent_startup_cleanup(self):
        """Verify that discovery topics from a previous process run are purged if no longer selected."""
        orphaned_topic = "homeassistant/sensor/pwrcell_0001000714e9/old_deprecated_field/config"
        # Pre-seed persisted topics file representing previous run
        with open(self.topics_file, "w", encoding="utf-8") as f:
            json.dump([orphaned_topic], f)

        # Start a brand new bridge instance pointing to this topics file
        new_bridge = HomeAssistantBridge(client=self.client, published_topics_path=self.topics_file)
        mock_mqttc = MagicMock()
        new_bridge._mqttc = mock_mqttc
        new_bridge.selected_field_keys = ["0001000714E9:inverter.inverter.A"]

        # Run discovery
        new_bridge.publish_discovery()

        # The orphaned topic must have received an empty retained publish to remove it
        published_calls = {call[0][0]: call[0][1] for call in mock_mqttc.publish.call_args_list}
        self.assertIn(orphaned_topic, published_calls)
        self.assertEqual(published_calls[orphaned_topic], "")

        # The persisted topics file must now be updated without the orphaned topic
        with open(self.topics_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertNotIn(orphaned_topic, persisted)
        self.assertIn("homeassistant/sensor/pwrcell_0001000714e9/inverter_a/config", persisted)

    def test_compound_write_command_execution(self):
        """Verify that incoming MQTT commands on compound command topics execute writes."""
        inv = self.client.state.get_inverter()
        sn = inv.serial_number

        self.bridge.selected_field_keys = [f"{sn}:inverter.live.system_mode"]
        self.bridge.publish_discovery()

        cmd_topic = f"pwrcell/{sn.lower()}/compound_system_mode/set"
        self.assertIn(cmd_topic, self.bridge._command_topic_to_field)

        # Simulate incoming command message
        msg = MagicMock()
        msg.topic = cmd_topic
        msg.payload = b"PRIORITY_BACKUP"

        self.bridge._on_message(self.mock_mqttc, None, msg)

        # Allow worker thread to execute
        import time
        time.sleep(0.5)

        c_view = self.client.state.get_compound_view("system_mode")
        self.assertEqual(c_view.latest_value, "PRIORITY_BACKUP")

    def test_suggested_display_precision_and_state_formatting(self):
        """Verify that suggested_display_precision is added to discovery payload and published states are formatted cleanly."""
        inv = self.client.state.get_inverter()
        sn = inv.serial_number

        self.bridge.selected_field_keys = [f"{sn}:inverter.inverter.A"]
        self.bridge.publish_discovery()

        config_topic = f"homeassistant/sensor/pwrcell_{sn.lower()}/inverter_a/config"
        matching_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == config_topic)
        payload = json.loads(matching_call[0][1])
        # Current in Amperes has precision 1
        self.assertEqual(payload.get("suggested_display_precision"), 1)

        # Update field with noisy float
        self.client.state.subscribe(self.bridge._on_field_update)
        self.mock_mqttc.publish.reset_mock()
        self.client.state.set_field(
            device_sn=sn,
            name="A",
            sub_group="inverter",
            value=12.345678,
            units="A",
        )

        state_topic = f"pwrcell/{sn.lower()}/inverter_a/state"
        state_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == state_topic)
        # Should be formatted to 1 decimal place: "12.3"
        self.assertEqual(state_call[0][1], "12.3")

    def test_format_state_value_never_scientific_notation(self):
        """Verify format_state_value never formats numbers with scientific notation."""
        # Large integer float
        self.assertEqual(format_state_value(63050200.0), "63050200")
        self.assertEqual(format_state_value(63050200.0, 0), "63050200")
        self.assertEqual(format_state_value(63050200), "63050200")
        self.assertEqual(format_state_value(63050200, 0), "63050200")

        # Large float with decimal fraction
        self.assertEqual(format_state_value(63050200.5, None), "63050200.5")
        self.assertEqual(format_state_value(63050200.5, 0), "63050200")
        self.assertEqual(format_state_value(63050200.5, 1), "63050200.5")
        self.assertEqual(format_state_value(63050200.5, 2), "63050200.50")

        # Strings must not be reinterpreted as scientific-notation floats (e.g. hex serials like "1234e5")
        self.assertEqual(format_state_value("1234e5"), "1234e5")
        self.assertEqual(format_state_value("Active"), "Active")

        # Invalid / sentinel / None values return None so callers skip publishing
        self.assertIsNone(format_state_value(None))
        self.assertIsNone(format_state_value(float("nan")))
        self.assertIsNone(format_state_value(float("inf")))
        self.assertIsNone(format_state_value(0x8000))

        # Zero and negative
        self.assertEqual(format_state_value(0.0), "0")
        self.assertEqual(format_state_value(0.0, 0), "0")
        self.assertEqual(format_state_value(-63050200.5, None), "-63050200.5")
        self.assertEqual(format_state_value(-63050200.5, 0), "-63050200")

        # Ensure no 'e+' or 'e-' in output for large/small numbers
        self.assertNotIn("e+", format_state_value(100000000.1234))
        self.assertNotIn("e-", format_state_value(0.0001))

    def test_large_energy_exported_state_publishing(self):
        """Verify that cumulative energy exported (Wh) formats cleanly without scientific notation."""
        inv = self.client.state.get_inverter()
        sn = inv.serial_number

        self.bridge.selected_field_keys = [f"{sn}:inverter.live.inverter_output_exported_energy_wh"]
        self.bridge.publish_discovery()

        config_topic = f"homeassistant/sensor/pwrcell_{sn.lower()}/compound_inverter_output_energy/config"
        matching_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == config_topic)
        payload = json.loads(matching_call[0][1])
        # Energy in Wh has suggested_display_precision 0
        self.assertEqual(payload.get("suggested_display_precision"), 0)
        self.assertEqual(payload.get("unit_of_measurement"), "Wh")

        # Update field with large energy value: 63,050,200 Wh (63.05 MWh)
        self.client.state.subscribe(self.bridge._on_field_update)
        self.client.state.subscribe_compound(self.bridge._on_compound_update)
        self.mock_mqttc.publish.reset_mock()
        self.client.state.set_field(
            device_sn=sn,
            name="inverter_output_exported_energy_wh",
            sub_group="live",
            value=63050200.4,
            units="Wh",
        )

        state_topic = f"pwrcell/{sn.lower()}/compound_inverter_output_energy/state"
        state_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == state_topic)
        self.assertEqual(state_call[0][1], "63050200")
        self.assertNotIn("e+", state_call[0][1])

    def test_start_with_empty_client_name_and_running_flag(self):
        """Verify bridge.start() falls back to HOSTNAME / default without NameError and only marks _running on success."""
        from unittest.mock import patch
        from pwrcell.config import MqttConfig

        # 1. Empty host should not leave _running=True without an active MQTT client
        no_host_bridge = HomeAssistantBridge(
            client=self.client,
            mqtt_config=MqttConfig(host="", port=1883, client_name=""),
            published_topics_path=self.topics_file,
        )

        # 2. Empty client_name with valid host should succeed without NameError
        bridge = HomeAssistantBridge(
            client=self.client,
            mqtt_config=MqttConfig(host="127.0.0.1", port=1883, client_name=""),
            published_topics_path=self.topics_file,
        )
        mock_client_inst = MagicMock()
        with patch("pwrcell.bridge.load_ha_config", return_value=[]), patch("pwrcell.bridge.mqtt.Client", return_value=mock_client_inst):
            no_host_bridge.start()
            self.assertFalse(no_host_bridge._running)

            bridge.start()
            self.assertTrue(bridge._running)
            mock_client_inst.loop_start.assert_called_once()
            mock_client_inst.connect.assert_called_once_with("127.0.0.1", 1883)
            bridge.stop()
            self.assertFalse(bridge._running)


if __name__ == "__main__":
    unittest.main()
