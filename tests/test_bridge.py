"""Unit tests for pwrcell.bridge HomeAssistantBridge."""

import json
import unittest
from unittest.mock import MagicMock

from pwrcell.bridge import HomeAssistantBridge
from pwrcell.client import PwrcellClient
from pwrcell.ha import generate_discovery_payload


class TestHomeAssistantBridge(unittest.TestCase):

    def setUp(self):
        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.bridge = HomeAssistantBridge(client=self.client)
        self.mock_mqttc = MagicMock()
        self.bridge._mqttc = self.mock_mqttc

    def tearDown(self):
        self.client.stop()

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


if __name__ == "__main__":
    unittest.main()
