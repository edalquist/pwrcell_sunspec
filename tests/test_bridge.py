"""Unit tests for pwrcell.bridge HomeAssistantBridge."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pwrcell.bridge import HomeAssistantBridge, format_state_value
from pwrcell.client import PwrcellClient
from pwrcell.ha import generate_discovery_payload
from pwrcell.grouping import clear_custom_groupings_cache


class TestHomeAssistantBridge(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.topics_file = Path(self.tmp_dir.name) / ".ha_published_topics.json"
        self._grouping_patch = patch(
            "pwrcell.grouping.get_default_grouping_config_path",
            return_value=Path(self.tmp_dir.name) / "custom_groupings.yaml",
        )
        self._grouping_patch.start()
        clear_custom_groupings_cache()

        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.bridge = HomeAssistantBridge(client=self.client, published_topics_path=self.topics_file)
        self.mock_mqttc = MagicMock()
        self.bridge._mqttc = self.mock_mqttc

    def tearDown(self):
        self.client.stop()
        self._grouping_patch.stop()
        clear_custom_groupings_cache()
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

        compound_config_topic = f"homeassistant/select/pwrcell_{sn.lower()}/system_mode/config"
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

        cmd_topic = f"pwrcell/{sn.lower()}/system_mode/set"
        self.assertIn(cmd_topic, self.bridge._command_topic_to_field)

        # Simulate incoming command message
        msg = MagicMock()
        msg.topic = cmd_topic
        msg.payload = b"PRIORITY_BACKUP"
        msg.retain = False

        self.bridge._on_message(self.mock_mqttc, None, msg)

        # Allow worker thread to execute
        import time
        time.sleep(0.5)

        c_view = self.client.state.get_compound_view("system_mode")
        self.assertEqual(c_view.latest_value, "PRIORITY_BACKUP")

    def test_suggested_display_precision_and_state_formatting(self):
        """Verify that suggested_display_precision reflects scale factors and published states are never truncated/rounded."""
        inv = self.client.state.get_inverter()
        sn = inv.serial_number

        self.bridge.selected_field_keys = [f"{sn}:inverter.inverter.A"]
        self.bridge.publish_discovery()

        config_topic = f"homeassistant/sensor/pwrcell_{sn.lower()}/inverter_a/config"
        matching_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == config_topic)
        payload = json.loads(matching_call[0][1])
        # Current in Amperes with A_SF=-2 has precision 2
        self.assertEqual(payload.get("suggested_display_precision"), 2)

        # Update field with high-precision value and float representation artifact
        self.client.state.subscribe(self.bridge._on_field_update)
        state_topic = f"pwrcell/{sn.lower()}/inverter_a/state"
        self.mock_mqttc.publish.reset_mock()
        self.client.state.set_field(
            device_sn=sn,
            name="A",
            sub_group="inverter",
            value=12.345,
            units="A",
        )
        state_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == state_topic)
        self.assertEqual(state_call[0][1], "12.345")

        self.mock_mqttc.publish.reset_mock()
        self.client.state.set_field(
            device_sn=sn,
            name="A",
            sub_group="inverter",
            value=12.34500000000001,
            units="A",
        )
        state_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == state_topic)
        self.assertEqual(state_call[0][1], "12.345")

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

        # Invalid / None values return None so callers skip publishing
        self.assertIsNone(format_state_value(None))
        self.assertIsNone(format_state_value(float("nan")))
        self.assertIsNone(format_state_value(float("inf")))
        self.assertIsNone(format_state_value(1e15))

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

        config_topic = f"homeassistant/sensor/pwrcell_{sn.lower()}/inverter_output_energy/config"
        matching_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == config_topic)
        payload = json.loads(matching_call[0][1])
        # Energy in Wh has suggested_display_precision 0
        self.assertEqual(payload.get("suggested_display_precision"), 0)
        self.assertEqual(payload.get("unit_of_measurement"), "Wh")

        # Update field with large energy value: 63,050,200.4 Wh (untruncated)
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

        state_topic = f"pwrcell/{sn.lower()}/inverter_output_energy/state"
        state_call = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == state_topic)
        self.assertEqual(state_call[0][1], "63050200.4")
        self.assertNotIn("e+", state_call[0][1])

        self.mock_mqttc.publish.reset_mock()
        self.client.state.set_field(
            device_sn=sn,
            name="inverter_output_exported_energy_wh",
            sub_group="live",
            value=63050201.0,
            units="Wh",
        )
        state_call_int = next(call for call in self.mock_mqttc.publish.call_args_list if call[0][0] == state_topic)
        self.assertEqual(state_call_int[0][1], "63050201")

    def test_battery_module_3_decimal_precision_and_unrounded_state(self):
        """3-decimal battery module cell voltages and 2-decimal pack voltages preserve precision in discovery and state."""
        from pwrcell.optimizer import group_device_fields

        bat = self.client.state.get_battery()
        self.assertIsNotNone(bat)
        bat_sn = bat.serial_number
        bat_sn_lower = bat_sn.strip().lower()

        self.client.state.update_from_modbus_points(
            serial_number=bat_sn,
            model_id=802,
            raw_values={"CellV_SF": -3, "CellVMin": 3939, "CellVMax": 3945},
            computed_values={"CellVMin": 3.939, "CellVMax": 3.945},
        )
        self.client.state.update_from_modbus_points(
            serial_number=bat_sn,
            model_id=64252,
            raw_values={"sf_1000": -3},
            computed_values={},
            groups_data=[
                {
                    "group_name": "DCB105_module",
                    "group_index": 3,
                    "group_path": "DCB105_module.3",
                    "raw_values": {"MinCellV": 3939},
                    "computed_values": {"MinCellV": 3.939},
                }
            ],
        )
        self.client.state.update_from_modbus_points(
            serial_number=bat_sn,
            model_id=804,
            raw_values={"CellV_SF": -3, "CellVMin": 3939, "CellVMax": 3945},
            computed_values={"CellVMin": 3.939, "CellVMax": 3.945},
            groups_data=[
                {
                    "group_name": "lithium_ion_string_module",
                    "group_index": 3,
                    "group_path": "lithium_ion_string_module.3",
                    "raw_values": {"ModCellVMin": 3939, "ModCellVMax": 3945},
                    "computed_values": {"ModCellVMin": 3.939, "ModCellVMax": 3.945},
                }
            ],
        )

        self.bridge.selected_field_keys = [
            f"{bat_sn}:battery.lithium_ion_string.lithium_ion_string_module.3.ModCellVMin",
            f"{bat_sn}:battery.DCB105_warranty.DCB105_module.1.MaxCellV",
            f"{bat_sn}:battery.DCB105_warranty.DCB105_module.1.PackV",
            f"{bat_sn}:battery.compound.min_cell_voltage",
            f"{bat_sn}:battery.compound.max_cell_voltage",
        ]
        self.mock_mqttc.publish.reset_mock()
        self.bridge.publish_discovery()

        published = {call[0][0]: call[0][1] for call in self.mock_mqttc.publish.call_args_list}

        # 1. Model 804 ModCellVMin (CellV_SF=-3)
        m804_cfg_topic = f"homeassistant/sensor/pwrcell_{bat_sn_lower}/lithium_ion_string_lithium_ion_string_module_3_modcellvmin/config"
        m804_state_topic = f"pwrcell/{bat_sn_lower}/lithium_ion_string_lithium_ion_string_module_3_modcellvmin/state"
        self.assertIn(m804_cfg_topic, published)
        m804_cfg = json.loads(published[m804_cfg_topic])
        self.assertEqual(m804_cfg.get("suggested_display_precision"), 3)
        self.assertEqual(published.get(m804_state_topic), "3.939")

        # 2. Model 64252 DCB105_module MaxCellV (sf_1000=-3) and PackV (sf_100=-2)
        dcb_max_cfg_topic = f"homeassistant/sensor/pwrcell_{bat_sn_lower}/dcb105_warranty_dcb105_module_1_maxcellv/config"
        dcb_pack_cfg_topic = f"homeassistant/sensor/pwrcell_{bat_sn_lower}/dcb105_warranty_dcb105_module_1_packv/config"
        dcb_pack_state_topic = f"pwrcell/{bat_sn_lower}/dcb105_warranty_dcb105_module_1_packv/state"
        self.assertEqual(json.loads(published[dcb_max_cfg_topic]).get("suggested_display_precision"), 3)
        self.assertEqual(json.loads(published[dcb_pack_cfg_topic]).get("suggested_display_precision"), 2)
        self.assertEqual(published.get(dcb_pack_state_topic), "49.79")

        # 3. Compound min_cell_voltage / max_cell_voltage
        min_cv_cfg_topic = f"homeassistant/sensor/pwrcell_{bat_sn_lower}/min_cell_voltage/config"
        min_cv_state_topic = f"pwrcell/{bat_sn_lower}/min_cell_voltage/state"
        max_cv_cfg_topic = f"homeassistant/sensor/pwrcell_{bat_sn_lower}/max_cell_voltage/config"
        self.assertEqual(json.loads(published[min_cv_cfg_topic]).get("suggested_display_precision"), 3)
        self.assertEqual(json.loads(published[max_cv_cfg_topic]).get("suggested_display_precision"), 3)
        self.assertEqual(published.get(min_cv_state_topic), "3.939")

        # 4. Custom wildcard concept module_3_minimum_cell_voltage
        unified = group_device_fields(
            bat,
            custom_groupings={
                "field_overrides": {
                    f"{bat_sn}:battery.lithium_ion_string.lithium_ion_string_module.*.ModCellVMin": "module_*_minimum_cell_voltage",
                    f"{bat_sn}:battery.DCB105_warranty.DCB105_module.*.MinCellV": "module_*_minimum_cell_voltage",
                },
                "custom_concepts": {
                    "module_*_minimum_cell_voltage": {"label": "Module * Minimum Cell Voltage"},
                },
            },
        )
        mod3_concept = next((g for g in unified if g.concept_key == "module_3_minimum_cell_voltage"), None)
        self.assertIsNotNone(mod3_concept)
        mod3_disc = generate_discovery_payload(mod3_concept, bat)
        self.assertEqual(mod3_disc["payload"].get("suggested_display_precision"), 3)
        self.assertEqual(format_state_value(mod3_concept.latest_value), "3.939")

        # 5. Cold-start discovery refresh when scale factor becomes available on later poll
        self.bridge.selected_field_keys = [f"{bat_sn}:battery.custom_model.CustomPackV"]
        self.bridge._selected_set = set(self.bridge.selected_field_keys)
        self.client.state.set_field(
            device_sn=bat_sn,
            name="CustomPackV",
            sub_group="custom_model",
            model_id=64999,
            value=49.7,
            raw_value=497,
            units="V",
            scale_factor_point="CustomSF",
        )
        self.mock_mqttc.publish.reset_mock()
        self.bridge.publish_discovery()

        custom_cfg_topic = f"homeassistant/sensor/pwrcell_{bat_sn_lower}/custom_model_custompackv/config"
        custom_state_topic = f"pwrcell/{bat_sn_lower}/custom_model_custompackv/state"
        initial_cfg = next(
            json.loads(c[0][1]) for c in self.mock_mqttc.publish.call_args_list if c[0][0] == custom_cfg_topic
        )
        self.assertEqual(initial_cfg.get("suggested_display_precision"), 1)

        # Now poll CustomSF=-3 and update CustomPackV=49.795 via StateStore subscription
        self.client.state.subscribe(self.bridge._on_field_update)
        self.mock_mqttc.publish.reset_mock()
        self.client.state.set_field(
            device_sn=bat_sn,
            name="CustomSF",
            sub_group="custom_model",
            model_id=64999,
            value=-3,
            raw_value=-3,
            is_scale_factor=True,
        )
        self.client.state.set_field(
            device_sn=bat_sn,
            name="CustomPackV",
            sub_group="custom_model",
            model_id=64999,
            value=49.795,
            raw_value=49795,
            units="V",
            scale_factor_point="CustomSF",
        )
        refreshed_calls = {c[0][0]: c[0][1] for c in self.mock_mqttc.publish.call_args_list}
        self.assertIn(custom_cfg_topic, refreshed_calls)
        self.assertEqual(json.loads(refreshed_calls[custom_cfg_topic]).get("suggested_display_precision"), 3)
        self.assertEqual(refreshed_calls.get(custom_state_topic), "49.795")

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

    def test_save_ha_config_atomic_and_distinct_object_ids_for_same_suffix_serials(self):
        """save_ha_config must write atomically via Path.replace, and devices with identical last-4 serial digits must not collide on object_id."""
        from unittest.mock import patch
        from pwrcell.ha import export_default_config, save_ha_config
        from pwrcell.state import StateField, UnifiedDevice

        cfg_file = Path(self.tmp_dir.name) / "ha_config.yaml"
        seed_file = Path(self.tmp_dir.name) / "ha_default_config.yaml"
        replaced_targets = []
        orig_replace = Path.replace

        def tracking_replace(path_self, target):
            replaced_targets.append(Path(target))
            return orig_replace(path_self, target)

        with patch.object(Path, "replace", autospec=True, side_effect=tracking_replace):
            save_ha_config(["0001000714E9:inverter.live.grid_power_w"], config_path=cfg_file)
            export_default_config(source_path=cfg_file, target_path=seed_file)

        self.assertIn(cfg_file, replaced_targets)
        self.assertIn(seed_file, replaced_targets)

        # Devices sharing the last 4 serial characters must have distinct payload['object_id']
        dev1 = UnifiedDevice(serial_number="00010000ABCD", slave_id=2, device_type="pv_link", model_name="PV Link", manufacturer="Generac", version="1.0")
        dev2 = UnifiedDevice(serial_number="00020000ABCD", slave_id=3, device_type="pv_link", model_name="PV Link", manufacturer="Generac", version="1.0")
        f1 = StateField(key="pv_link.string_combiner.DCW", device_sn=dev1.serial_number, device_type="pv_link", name="DCW", label="DC Power", description="", value=100.0, raw_value=100.0)
        f2 = StateField(key="pv_link.string_combiner.DCW", device_sn=dev2.serial_number, device_type="pv_link", name="DCW", label="DC Power", description="", value=100.0, raw_value=100.0)
        p1 = generate_discovery_payload(f1, dev1)["payload"]
        p2 = generate_discovery_payload(f2, dev2)["payload"]
        self.assertNotEqual(p1["object_id"], p2["object_id"])

    def test_device_availability_staleness_and_ha_birth_republish(self):
        """Entities must include per-device availability, transition to offline when stale (injected clock), and republish on HA birth."""
        if hasattr(self.client, "_sim_stop"):
            self.client._sim_stop.set()
        if getattr(self.client, "_sim_thread", None):
            self.client._sim_thread.join(timeout=1.0)
        fake_now = [1000.0]
        inv = self.client.state.get_inverter()
        sn = inv.serial_number
        inv.last_seen = 1000.0

        bridge = HomeAssistantBridge(
            client=self.client,
            published_topics_path=self.topics_file,
            stale_timeout=300.0,
            clock=lambda: fake_now[0],
        )
        mock_mqttc = MagicMock()
        bridge._mqttc = mock_mqttc
        bridge.selected_field_keys = [f"{sn}:inverter.inverter.A"]

        # 1. Discovery payload includes both process and per-device availability topics
        bridge.publish_discovery()
        config_topic = f"homeassistant/sensor/pwrcell_{sn.lower()}/inverter_a/config"
        matching_call = next(call for call in mock_mqttc.publish.call_args_list if call[0][0] == config_topic)
        payload = json.loads(matching_call[0][1])
        avail_topics = [a["topic"] for a in payload["availability"]]
        self.assertIn("pwrcell/status", avail_topics)
        self.assertIn(f"pwrcell/{sn.lower()}/status", avail_topics)
        self.assertEqual(payload.get("availability_mode"), "all")

        # Initial device status is online
        dev_status_topic = f"pwrcell/{sn.lower()}/status"
        status_calls = [c for c in mock_mqttc.publish.call_args_list if c[0][0] == dev_status_topic]
        self.assertTrue(status_calls)
        self.assertEqual(status_calls[-1][0][1], "online")

        # 2. Advance injected clock past stale_timeout -> check_availability marks device offline
        mock_mqttc.publish.reset_mock()
        fake_now[0] = 1400.0
        bridge.check_availability()
        offline_calls = [c for c in mock_mqttc.publish.call_args_list if c[0][0] == dev_status_topic]
        self.assertTrue(offline_calls)
        self.assertEqual(offline_calls[-1][0][1], "offline")

        # 3. HA birth message on homeassistant/status='online' triggers discovery and state republish
        mock_mqttc.publish.reset_mock()
        inv.last_seen = 1400.0
        birth_msg = MagicMock()
        birth_msg.topic = "homeassistant/status"
        birth_msg.payload = b"online"
        birth_msg.retain = False
        bridge._on_message(mock_mqttc, None, birth_msg)
        republished_topics = [c[0][0] for c in mock_mqttc.publish.call_args_list]
        self.assertIn(config_topic, republished_topics)

    def test_command_executor_and_listener_warning_logging(self):
        """Incoming HA commands must be dispatched via bounded ThreadPoolExecutor (not per-message Thread), and listener errors must log at WARNING."""
        from unittest.mock import patch

        inv = self.client.state.get_inverter()
        sn = inv.serial_number
        self.bridge.selected_field_keys = [f"{sn}:inverter.live.system_mode"]
        self.bridge.publish_discovery()
        cmd_topic = f"pwrcell/{sn.lower()}/system_mode/set"

        # 1. Verify _cmd_executor exists (max_workers=1) and commands are submitted to it
        self.assertIsNotNone(getattr(self.bridge, "_cmd_executor", None))
        self.assertEqual(self.bridge._cmd_executor._max_workers, 1)
        msg = MagicMock()
        msg.topic = cmd_topic
        msg.payload = b"SELF_SUPPLY"
        msg.retain = False

        with patch.object(self.bridge._cmd_executor, "submit", wraps=self.bridge._cmd_executor.submit) as mock_submit:
            self.bridge._on_message(self.mock_mqttc, None, msg)
            mock_submit.assert_called_once_with(
                self.bridge._execute_command_async,
                "inverter.compound.system_mode",
                "SELF_SUPPLY",
                "0001000714E9",
            )

        # Wait briefly for single-worker executor
        import time
        time.sleep(0.2)
        c_view = self.client.state.get_compound_view("system_mode")
        self.assertEqual(c_view.latest_value, "SELF_SUPPLY")

        # 2. Verify failing state listener logs at WARNING instead of swallowing at DEBUG
        def broken_listener(_field):
            raise RuntimeError("listener boom")

        self.client.state.subscribe(broken_listener)
        try:
            with self.assertLogs("pwrcell.state", level="WARNING") as cm:
                self.client.state.set_field(
                    device_sn=sn,
                    name="A",
                    sub_group="inverter",
                    value=99.9,
                    units="A",
                )
            self.assertTrue(any("listener boom" in line for line in cm.output))
        finally:
            self.client.state.unsubscribe(broken_listener)

    def test_retained_command_messages_are_ignored(self):
        """Retained messages on command topics must be ignored (and logged at WARNING) so reconnects do not replay old writes."""
        inv = self.client.state.get_inverter()
        sn = inv.serial_number
        self.bridge.selected_field_keys = [f"{sn}:inverter.live.system_mode"]
        self.bridge.publish_discovery()
        cmd_topic = f"pwrcell/{sn.lower()}/system_mode/set"

        # Set known baseline mode
        self.client.controls.write_field("inverter.compound.system_mode", "SELF_SUPPLY")
        self.assertEqual(self.client.state.get_compound_view("system_mode").latest_value, "SELF_SUPPLY")

        # Send retained command attempting to change mode to CLEAN_BACKUP
        retained_msg = MagicMock()
        retained_msg.topic = cmd_topic
        retained_msg.payload = b"CLEAN_BACKUP"
        retained_msg.retain = True

        with self.assertLogs("pwrcell.bridge", level="WARNING") as cm:
            self.bridge._on_message(self.mock_mqttc, None, retained_msg)
        self.assertTrue(any("retain" in line.lower() for line in cm.output))

        import time
        time.sleep(0.1)
        # System mode must remain unchanged
        self.assertEqual(self.client.state.get_compound_view("system_mode").latest_value, "SELF_SUPPLY")

    def test_writable_exposure_allowlist_and_safety_shutdown_exclusion(self):
        """Only explicitly allow-listed points are exposed as writable in HA discovery, and SAFETY_SHUTDOWN is excluded from HA select options."""
        from pwrcell.ha import is_ha_writable_allowed
        from pwrcell.state import StateField

        inv = self.client.state.get_inverter()
        bat = self.client.state.get_battery()
        beacon = self.client.state.get_beacon()

        # 1. Non-allowlisted RW register (e.g. grid code / volt-var curve point V1 on model 126) must be exposed as read-only sensor
        grid_code_field = StateField(
            key="inverter.volt_var.V1",
            device_sn=inv.serial_number,
            device_type="inverter",
            name="V1",
            label="Volt-Var V1",
            description="Volt-Var curve point 1",
            value=240.0,
            raw_value=2400,
            units="V",
            access="RW",
            point_type="uint16",
            model_id=126,
        )
        self.assertFalse(is_ha_writable_allowed(grid_code_field))
        grid_payload = generate_discovery_payload(grid_code_field, inv)
        self.assertEqual(grid_payload["platform"], "sensor")
        self.assertIsNone(grid_payload["command_topic"])
        self.assertNotIn("command_topic", grid_payload["payload"])

        # 2. Allow-listed battery reserve register (SoCRsvMin on model 802) is exposed as writable number with bounds
        soc_rsv_field = bat.fields.get("battery.battery.SoCRsvMin")
        self.assertIsNotNone(soc_rsv_field)
        self.assertTrue(is_ha_writable_allowed(soc_rsv_field))
        rsv_payload = generate_discovery_payload(soc_rsv_field, bat)
        self.assertEqual(rsv_payload["platform"], "number")
        self.assertIsNotNone(rsv_payload["command_topic"])
        self.assertIn("min", rsv_payload["payload"])
        self.assertIn("max", rsv_payload["payload"])

        # 3. Allow-listed system_mode (both compound and raw SysMd) is exposed as writable select WITHOUT SAFETY_SHUTDOWN
        c_sys_mode = self.client.state.get_compound_view("system_mode")
        self.assertTrue(is_ha_writable_allowed(c_sys_mode))
        c_payload = generate_discovery_payload(c_sys_mode, inv)
        self.assertEqual(c_payload["platform"], "select")
        self.assertIsNotNone(c_payload["command_topic"])
        self.assertNotIn("SAFETY_SHUTDOWN", c_payload["payload"]["options"])
        self.assertIn("SELF_SUPPLY", c_payload["payload"]["options"])

        raw_sysmd = beacon.fields.get("rebus_beacon.REbus_dir.SysMd")
        if raw_sysmd:
            self.assertTrue(is_ha_writable_allowed(raw_sysmd))
            raw_payload = generate_discovery_payload(raw_sysmd, beacon)
            self.assertEqual(raw_payload["platform"], "select")
            self.assertNotIn("SAFETY_SHUTDOWN", raw_payload["payload"].get("options", []))

    def test_is_field_selected_uses_normalized_uppercase_serial(self):
        """Selection is an exact match on normalized '<SERIAL_UPPER>:<key>' (plus legacy global keys); no lowercase-serial variant."""
        from pwrcell.ha import is_field_selected

        sel = {"ABC123:inverter.live.grid_power_w", "battery.live.state_of_charge"}
        self.assertTrue(is_field_selected("inverter.live.grid_power_w", "abc123", sel))
        self.assertFalse(is_field_selected("inverter.live.grid_power_w", "OTHER", sel))
        self.assertTrue(is_field_selected("battery.live.state_of_charge", "ANY", sel))
        self.assertFalse(is_field_selected("inverter.live.grid_power_w", "ABC123", {"abc123:inverter.live.grid_power_w"}))

    def test_inverter_state_group_single_entity_and_member_suppression(self):
        """Selecting inverter_state group results in a single clean enum entity in HA and suppresses all raw members."""
        from pwrcell.state import FieldSource

        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number.strip().upper()

        # Ingest MQTT telemetry for both state code and state name
        self.client.state.set_field(
            device_sn=inv_sn,
            name="inverter_state_name",
            sub_group="live",
            value="GRID_CONNECTED",
            raw_value="GRID_CONNECTED",
            source=FieldSource.MQTT_PUSH,
        )
        self.client.state.set_field(
            device_sn=inv_sn,
            name="inverter_state",
            sub_group="live",
            value=2080,
            raw_value=2080,
            source=FieldSource.MQTT_PUSH,
        )

        # Select only the compound group
        self.bridge.selected_field_keys = [f"{inv_sn}:inverter.compound.inverter_state"]
        self.bridge._selected_set = set(self.bridge.selected_field_keys)
        self.mock_mqttc.reset_mock()

        self.bridge.publish_discovery()

        published_configs = {}
        for call in self.mock_mqttc.publish.call_args_list:
            topic, payload = call[0][0], call[0][1]
            if "config" in topic and payload != "":
                published_configs[topic] = json.loads(payload)

        # 1. Compound entity must be published with friendly name and enum options
        comp_topic = f"homeassistant/sensor/pwrcell_{inv_sn.lower()}/inverter_state/config"
        self.assertIn(comp_topic, published_configs)
        comp_payload = published_configs[comp_topic]
        self.assertEqual(comp_payload["name"], "Inverter Operational State")
        self.assertEqual(comp_payload.get("device_class"), "enum")
        self.assertIn("GRID_CONNECTED", comp_payload.get("options", []))

        # 2. Raw member entities must NOT have active configs published
        raw_name_topic = f"homeassistant/sensor/pwrcell_{inv_sn.lower()}/live_inverter_state_name/config"
        raw_code_topic = f"homeassistant/sensor/pwrcell_{inv_sn.lower()}/live_inverter_state/config"
        self.assertNotIn(raw_name_topic, published_configs)
        self.assertNotIn(raw_code_topic, published_configs)

        # 3. An update on raw member field must be suppressed and not publish a new discovery config
        self.mock_mqttc.reset_mock()
        f_name = inv.fields.get("inverter.live.inverter_state_name")
        self.assertIsNotNone(f_name)
        self.bridge._on_field_update(f_name)
        for call in self.mock_mqttc.publish.call_args_list:
            topic = call[0][0]
            self.assertNotIn("live_inverter_state_name/config", topic)

    def test_inverter_state_numeric_conversion_and_retained_compound_publish(self):
        """Inverter operational state converts numeric code 2080 to GRID_CONNECTED and retains state updates."""
        from pwrcell.state import FieldSource

        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number.strip().upper()

        # Set only raw numeric StVnd on model 102 (no live string telemetry)
        self.client.state.set_field(
            device_sn=inv_sn,
            name="StVnd",
            model_id=102,
            sub_group="model_102",
            value=2080,
            raw_value=2080,
            source=FieldSource.MODBUS_POLL,
        )

        c_view = self.client.state.get_compound_view("inverter_state", inv_sn)
        self.assertIsNotNone(c_view)
        self.assertEqual(c_view.latest_value, "GRID_CONNECTED")
        self.assertEqual(c_view.ha_device_class, "enum")
        self.assertIn("GRID_CONNECTED", c_view.ha_options)

        # Verify discovery payload has enum and valid options
        disc = generate_discovery_payload(c_view, inv)
        self.assertEqual(disc["payload"]["device_class"], "enum")
        self.assertIn("GRID_CONNECTED", disc["payload"]["options"])

        # Verify _on_compound_update publishes with retain=True
        self.bridge.selected_field_keys = [f"{inv_sn}:inverter.compound.inverter_state"]
        self.bridge._selected_set = set(self.bridge.selected_field_keys)
        self.mock_mqttc.reset_mock()

        self.bridge._on_compound_update(c_view)
        state_calls = [
            call for call in self.mock_mqttc.publish.call_args_list
            if call[0][0] == f"pwrcell/{inv_sn.lower()}/inverter_state/state"
        ]
        self.assertTrue(len(state_calls) >= 1)
        # Check retain=True keyword argument
        self.assertTrue(state_calls[0].kwargs.get("retain") is True)
        self.assertEqual(state_calls[0][0][1], "GRID_CONNECTED")

    def test_system_mode_canonical_options_and_alias_normalization(self):
        """System operating mode publishes canonical options in HA without duplicate synonyms."""
        from pwrcell.state import FieldSource

        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number.strip().upper()

        # Set live system mode with alias 'GRID_CONNECT'
        self.client.state.set_field(
            device_sn=inv_sn,
            name="system_mode",
            sub_group="live",
            value="GRID_CONNECT",
            raw_value=1,
            source=FieldSource.MQTT_PUSH,
        )

        c_view = self.client.state.get_compound_view("system_mode", inv_sn)
        self.assertIsNotNone(c_view)
        # Aliases normalized to canonical SunSpec names
        self.assertEqual(c_view.latest_value, "GRID_TIE")

        disc = generate_discovery_payload(c_view, inv)
        self.assertEqual(disc["platform"], "select")
        # Ensure HA select options do not contain duplicate synonyms
        options = disc["payload"]["options"]
        self.assertIn("GRID_TIE", options)
        self.assertNotIn("GRID_CONNECT", options)
        self.assertIn("SELL", options)
        self.assertNotIn("FULL_EXPORT", options)
        self.assertIn("REMOTE_ARBITRAGE", options)
        self.assertNotIn("ARBITRAGE", options)
        self.assertNotIn("SAFETY_SHUTDOWN", options)  # Excluded by default security policy

    def test_on_field_update_retains_state_to_prevent_stale_broker_values(self):
        """Live raw field updates must publish with retain=True so HA reconnects never read stale broker values."""
        self.client.state.subscribe(self.bridge._on_field_update)
        self.bridge.selected_field_keys = ["0001000714E9:inverter.inverter.A"]

        self.client.state.set_field(
            device_sn="0001000714E9",
            name="A",
            sub_group="inverter",
            value=14.2,
            label="Inverter Current",
        )

        state_calls = [
            call for call in self.mock_mqttc.publish.call_args_list
            if call[0][0] == "pwrcell/0001000714e9/inverter_a/state"
        ]
        self.assertTrue(len(state_calls) >= 1)
        self.assertTrue(state_calls[-1].kwargs.get("retain") is True)
        self.assertEqual(state_calls[-1][0][1], "14.2")

    def test_device_online_flag_publishes_offline_and_online_status(self):
        """Marking a device offline/online in StateStore must publish retained offline/online status on check_availability()."""
        inv = self.client.state.get_inverter()
        self.assertIsNotNone(inv)
        inv_sn = inv.serial_number
        status_topic = f"pwrcell/{inv_sn.lower()}/status"

        # Seed initial online availability state
        self.bridge.check_availability()
        self.mock_mqttc.reset_mock()

        # Mark inverter offline -> check_availability publishes retained "offline"
        self.client.state.set_device_online(inv_sn, False, error="Modbus exception 3")
        self.bridge.check_availability()
        offline_calls = [c for c in self.mock_mqttc.publish.call_args_list if c[0][0] == status_topic]
        self.assertEqual(len(offline_calls), 1)
        self.assertEqual(offline_calls[0][0][1], "offline")
        self.assertTrue(offline_calls[0].kwargs.get("retain") is True)

        # Restore inverter online -> check_availability publishes retained "online"
        self.mock_mqttc.reset_mock()
        self.client.state.set_device_online(inv_sn, True)
        self.bridge.check_availability()
        online_calls = [c for c in self.mock_mqttc.publish.call_args_list if c[0][0] == status_topic]
        self.assertEqual(len(online_calls), 1)
        self.assertEqual(online_calls[0][0][1], "online")
        self.assertTrue(online_calls[0].kwargs.get("retain") is True)

    def test_publish_discovery_respects_gateway_availability(self):
        """publish_discovery() must publish actual gateway availability ('offline' when down), not hardcoded 'online'."""
        beacon = self.client.state.get_beacon()
        self.assertIsNotNone(beacon)
        gw_status_topic = f"pwrcell/{beacon.serial_number.strip().lower()}/status"

        orig_is_mock = self.client.is_mock
        orig_mqtt = self.client.mqtt
        orig_mb_connected = self.client.poller._modbus_connected
        try:
            self.client.is_mock = False
            mock_internal_mqtt = MagicMock()
            mock_internal_mqtt.is_healthy.return_value = False
            self.client.mqtt = mock_internal_mqtt
            self.client.poller._modbus_connected = False

            self.bridge.selected_field_keys = [f"{beacon.serial_number}:rebus_beacon.REbus_dir.SysMd"]
            self.bridge._selected_set = set(self.bridge.selected_field_keys)
            self.mock_mqttc.reset_mock()

            self.bridge.publish_discovery()
            gw_calls = [c for c in self.mock_mqttc.publish.call_args_list if c[0][0] == gw_status_topic]
            self.assertTrue(gw_calls)
            self.assertEqual(gw_calls[-1][0][1], "offline")

            # When Modbus recovers, publish_discovery reports gateway 'online'
            self.client.poller._modbus_connected = True
            self.mock_mqttc.reset_mock()
            self.bridge.publish_discovery()
            gw_calls_up = [c for c in self.mock_mqttc.publish.call_args_list if c[0][0] == gw_status_topic]
            self.assertTrue(gw_calls_up)
            self.assertEqual(gw_calls_up[-1][0][1], "online")
        finally:
            self.client.is_mock = orig_is_mock
            self.client.mqtt = orig_mqtt
            self.client.poller._modbus_connected = orig_mb_connected

    def test_start_falls_back_to_connect_async_and_watchdog_reconnects_ha_broker(self):
        """start() falls back to connect_async() on connect error and check_availability() retries HA broker after 60s."""
        from pwrcell.config import MqttConfig

        now = [1000.0]
        mock_mqttc = MagicMock()
        mock_mqttc.connect.side_effect = OSError("broker unreachable")

        bridge = HomeAssistantBridge(
            client=self.client,
            mqtt_config=MqttConfig(host="127.0.0.1", port=1883, client_name="pwrcell_test"),
            published_topics_path=self.topics_file,
            clock=lambda: now[0],
        )

        with patch("pwrcell.bridge.load_ha_config", return_value=[]), patch(
            "pwrcell.bridge.mqtt.Client", return_value=mock_mqttc
        ):
            bridge.start()
            try:
                self.assertTrue(bridge._running)
                self.assertFalse(bridge.get_status()["connected"])
                mock_mqttc.connect_async.assert_called_once_with("127.0.0.1", 1883)

                # At +30s (< 60s): watchdog must NOT reconnect yet
                now[0] = 1030.0
                bridge.check_availability()
                self.assertEqual(mock_mqttc.connect_async.call_count, 1)

                # At +65s (>= 60s): watchdog triggers connect_async()
                now[0] = 1065.0
                bridge.check_availability()
                self.assertEqual(mock_mqttc.connect_async.call_count, 2)
                self.assertEqual(mock_mqttc.connect_async.call_args_list[-1][0], ("127.0.0.1", 1883))

                # At +90s (only 25s after last attempt): 60s cooldown prevents spam
                now[0] = 1090.0
                bridge.check_availability()
                self.assertEqual(mock_mqttc.connect_async.call_count, 2)
            finally:
                bridge.stop()


if __name__ == "__main__":
    unittest.main()
