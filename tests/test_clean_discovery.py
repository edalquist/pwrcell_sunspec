"""Unit tests for pwrcell.clean_discovery."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pwrcell.clean_discovery import is_pwrcell_origin, purge_pwrcell_discovery_topics
from pwrcell.ha import ORIGIN_INFO


class TestCleanDiscovery(unittest.TestCase):

    def test_is_pwrcell_origin(self):
        # Exact match
        payload_exact = {"origin": dict(ORIGIN_INFO)}
        self.assertTrue(is_pwrcell_origin(payload_exact, match_exact=True))
        self.assertTrue(is_pwrcell_origin(payload_exact, match_exact=False))

        # Different sw_version with exact match vs loose match
        payload_diff_version = {
            "origin": {
                "name": "PWRcell SunSpec",
                "sw_version": "2.9.0",
                "support_url": "https://github.com/edalquist/pwrcell_sunspec",
            }
        }
        self.assertFalse(is_pwrcell_origin(payload_diff_version, match_exact=True))
        self.assertTrue(is_pwrcell_origin(payload_diff_version, match_exact=False))

        # Different integration
        payload_other = {"origin": {"name": "Zigbee2MQTT"}}
        self.assertFalse(is_pwrcell_origin(payload_other, match_exact=False))

        # Missing origin
        self.assertFalse(is_pwrcell_origin({}, match_exact=False))
        self.assertFalse(is_pwrcell_origin({"origin": "string"}, match_exact=False))

    @patch("pwrcell.clean_discovery.mqtt.Client")
    def test_purge_pwrcell_discovery_topics(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Create temporary cache file
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_cache = Path(tmp_dir) / ".ha_published_topics.json"
            tmp_cache.write_text('["homeassistant/sensor/pwrcell_0001000714e9/live_system_mode/config"]')

            # Simulate message callbacks when subscribe is called
            def fake_subscribe(*args, **kwargs):
                on_msg = mock_client.on_message

                # Matching PWRcell discovery message
                pwrcell_msg = MagicMock()
                pwrcell_msg.topic = "homeassistant/sensor/pwrcell_0001000714e9/live_system_mode/config"
                pwrcell_msg.payload = json.dumps({
                    "name": "Live System Mode",
                    "state_topic": "pwrcell/0001000714e9/live_system_mode/state",
                    "origin": ORIGIN_INFO,
                }).encode("utf-8")
                on_msg(mock_client, None, pwrcell_msg)

                # Non-matching message (e.g. Zigbee2MQTT)
                other_msg = MagicMock()
                other_msg.topic = "homeassistant/sensor/z2m_switch/config"
                other_msg.payload = json.dumps({
                    "name": "Z2M Switch",
                    "origin": {"name": "Zigbee2MQTT"},
                }).encode("utf-8")
                on_msg(mock_client, None, other_msg)

            mock_client.subscribe.side_effect = fake_subscribe

            with patch("pwrcell.clean_discovery.get_default_published_topics_path", return_value=tmp_cache):
                purged = purge_pwrcell_discovery_topics(
                    broker_host="localhost",
                    broker_port=1883,
                    timeout=0.5,
                    dry_run=False,
                    clear_cache=True,
                )

            self.assertEqual(len(purged), 1)
            self.assertEqual(purged[0], "homeassistant/sensor/pwrcell_0001000714e9/live_system_mode/config")

            # Verify that publish was called with empty payload and retain=True for config & state
            published_calls = mock_client.publish.call_args_list
            topics_published = {call[0][0]: call[0][1] for call in published_calls}

            self.assertIn("homeassistant/sensor/pwrcell_0001000714e9/live_system_mode/config", topics_published)
            self.assertEqual(topics_published["homeassistant/sensor/pwrcell_0001000714e9/live_system_mode/config"], "")
            self.assertIn("pwrcell/0001000714e9/live_system_mode/state", topics_published)
            self.assertEqual(topics_published["pwrcell/0001000714e9/live_system_mode/state"], "")

            # Non-matching topic was not touched
            self.assertNotIn("homeassistant/sensor/z2m_switch/config", topics_published)

            # Cache file was deleted
            self.assertFalse(tmp_cache.exists())


if __name__ == "__main__":
    unittest.main()
