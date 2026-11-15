"""Regression tests for GitHub Issue #17 (HA config & MQTT discovery preview updates)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from pwrcell import mapping as mapping_module
from pwrcell.bridge import HomeAssistantBridge
from pwrcell.client import PwrcellClient
from pwrcell.grouping import clear_custom_groupings_cache, set_field_grouping_override
from pwrcell.ha import (
    clear_ha_config_cache,
    generate_discovery_payload,
    load_ha_config,
    qualify_legacy_ha_config,
    save_ha_config,
)
from pwrcell.optimizer import group_device_fields, resolve_minimal_models_for_paths
from pwrcell.state import StateStore
from pwrcell.ui.server import create_app


class TestIssue17HaConfigAndPreview(unittest.TestCase):
    """Verify end-to-end selection, save, preview, migration, and discovery fixes for Issue #17."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_dir.name)
        self.ha_config_path = tmp / "ha_config.yaml"
        self.groupings_path = tmp / "groupings.yaml"
        self.custom_groupings_path = tmp / "custom_groupings.yaml"
        self.topics_path = tmp / ".ha_published_topics.json"

        pkg_groupings = Path(mapping_module.__file__).resolve().parent / "data" / "groupings.yaml"
        shutil.copy(pkg_groupings, self.groupings_path)

        self._patches = [
            mock.patch("pwrcell.ha.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.grouping.get_default_grouping_config_path", return_value=self.custom_groupings_path),
            mock.patch("pwrcell.mapping._resolve_mappings_path", return_value=self.groupings_path),
        ]
        for p in self._patches:
            p.start()

        clear_ha_config_cache()
        clear_custom_groupings_cache()
        mapping_module.MappingRegistry._instance = None

        self.client = PwrcellClient(is_mock=True)
        self.client.start()
        self.app = create_app(self.client)
        self.test_client = self.app.test_client()

    def tearDown(self):
        self.client.stop()
        for p in reversed(self._patches):
            p.stop()
        clear_ha_config_cache()
        clear_custom_groupings_cache()
        mapping_module.MappingRegistry._instance = None
        self._tmp_dir.cleanup()

    def test_frontend_app_js_selection_and_toggle_via_node(self):
        """Verify real app.js getCompoundKeyForItem/isFieldSelected/toggleHaSelection against API payloads."""
        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()
        bat_sn = self.client.state.get_battery().serial_number.strip().upper()

        inv_unified = self.test_client.get(f"/api/devices/{inv_sn}/unified_fields").get_json()["unified_fields"]
        inv_raw = self.test_client.get(f"/api/devices/{inv_sn}").get_json()
        bat_unified = self.test_client.get(f"/api/devices/{bat_sn}/unified_fields").get_json()["unified_fields"]
        bat_raw = self.test_client.get(f"/api/devices/{bat_sn}").get_json()

        payload = {
            "invSn": inv_sn,
            "batSn": bat_sn,
            "invUnified": inv_unified,
            "invRawFields": inv_raw["fields"],
            "invCompoundFields": inv_raw["compound_fields"],
            "batUnified": bat_unified,
            "batRawFields": bat_raw["fields"],
        }

        node_script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const appJs = fs.readFileSync('pwrcell/ui/static/app.js', 'utf8');
const startIdx = appJs.indexOf('function getFieldDeviceSn(f)');
const endIdx = appJs.indexOf('// Value extraction helpers for multi-column sorting');
assert(startIdx !== -1 && endIdx !== -1 && endIdx > startIdx, 'Could not locate HA selection helper slice in app.js');
const helperCode = appJs.slice(startIdx, endIdx);

const data = JSON.parse(fs.readFileSync(0, 'utf8'));

const sandbox = {
  state: {
    activeDevice: { serial_number: data.invSn },
    selectedHaKeys: new Set(),
    modifiedDeviceSerials: new Set(),
    haCategoryOverrides: {},
  },
  updateHaCounter: () => {},
  updateFilterCounts: () => {},
  escapeHtml: (s) => String(s),
  renderFieldTable: () => {},
  apiPath: (p) => p,
  showToast: () => {},
  fetchHaConfig: async () => {},
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  console: { debug: () => {}, error: () => {}, warn: () => {}, log: () => {} },
};

vm.createContext(sandbox);
vm.runInContext(helperCode, sandbox);

// 1. Standalone Unified View rows must NEVER produce .compound. keys
const standaloneLoad = data.invUnified.find(g => g.active_source_key === 'inverter.live.load_power_w' || (g.id || '').includes('.standalone.load_power_w'));
assert(standaloneLoad, 'Expected standalone load_power_w row in inverter unified_fields');
assert.strictEqual(standaloneLoad.is_compound, false, 'Standalone Unified row must serialize is_compound=false');
assert.strictEqual(sandbox.getCompoundKeyForItem(standaloneLoad), null, 'Standalone Unified row must return null from getCompoundKeyForItem');

sandbox.toggleHaSelection(standaloneLoad, true);
assert(sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.live.load_power_w`), 'Selecting standalone load_power_w must add raw key');
for (const k of sandbox.state.selectedHaKeys) {
  assert(!k.includes('.compound.'), `Standalone toggle must not fabricate compound key: ${k}`);
}
assert.strictEqual(sandbox.isFieldSelected(standaloneLoad), true);
sandbox.toggleHaSelection(standaloneLoad, false);
assert.strictEqual(sandbox.isFieldSelected(standaloneLoad), false);

// 2. Standalone Modbus Unified row (Battery SoCMin) selects its active Modbus key, not .compound.
sandbox.state.activeDevice = { serial_number: data.batSn };
const standaloneSocMin = data.batUnified.find(g => (g.id || '').includes('.standalone.socmin'));
assert(standaloneSocMin, 'Expected standalone socmin row in battery unified_fields');
assert.strictEqual(standaloneSocMin.is_compound, false);
assert.strictEqual(sandbox.getCompoundKeyForItem(standaloneSocMin), null);
sandbox.toggleHaSelection(standaloneSocMin, true);
assert(sandbox.state.selectedHaKeys.has(`${data.batSn}:${standaloneSocMin.active_source_key}`));

// 3. Compound row in Raw mode (compound_fields) where cf.id === '<dev>.compound.<id>' and cf.key is active_source_key
sandbox.state.activeDevice = { serial_number: data.invSn };
sandbox.state.selectedHaKeys.clear();
const rawCompInvState = data.invCompoundFields.find(cf => cf.id === 'inverter.compound.inverter_state');
assert(rawCompInvState, 'Expected inverter.compound.inverter_state in compound_fields');
const compInvState = { ...rawCompInvState, is_compound: true };
assert.strictEqual(compInvState.key, 'inverter.live.inverter_state_name', 'ConceptView.to_dict serializes key as active_source_key');
assert.strictEqual(sandbox.getCompoundKeyForItem(compInvState), 'inverter.compound.inverter_state');
assert(Array.isArray(compInvState.member_keys) && compInvState.member_keys.includes('inverter.live.inverter_state_name'));
sandbox.toggleHaSelection(compInvState, true);
assert(sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.compound.inverter_state`), 'Selecting compound_fields row must keep scoped compound key');
assert(!sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.live.inverter_state_name`), 'Selecting compound_fields row must not leave active_source_key in selectedHaKeys');

// 4. Raw member row ("Inverter State Name") must recognize parent compound selection and toggle cleanly
const rawStateName = { ...data.invRawFields['inverter.live.inverter_state_name'], compound_key: 'inverter.compound.inverter_state' };
assert.strictEqual(sandbox.isFieldSelected(rawStateName), true, 'Inverter State Name raw row must appear selected when inverter.compound.inverter_state is selected');
sandbox.toggleHaSelection(rawStateName, false);
assert(!sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.compound.inverter_state`), 'Unchecking raw member must remove parent compound key');
assert.strictEqual(sandbox.isFieldSelected(rawStateName), false);

// Checking raw member selects compound key (never leaving orphan raw key)
sandbox.toggleHaSelection(rawStateName, true);
assert(sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.compound.inverter_state`));
assert(!sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.live.inverter_state_name`));

// 5. Deselecting Unified compound row (Battery SoC) purges both compound key AND legacy unpopulated member key
sandbox.state.activeDevice = { serial_number: data.batSn };
sandbox.state.selectedHaKeys.clear();
sandbox.state.selectedHaKeys.add(`${data.batSn}:battery.compound.battery_soc`);
sandbox.state.selectedHaKeys.add(`${data.batSn}:battery.live.state_of_charge`);
const unifiedSoc = data.batUnified.find(g => g.id === 'battery.concept.battery_soc');
assert(unifiedSoc, 'Expected battery.concept.battery_soc in battery unified_fields');
assert(Array.isArray(unifiedSoc.member_keys) && unifiedSoc.member_keys.includes('battery.live.state_of_charge'));
assert.strictEqual(sandbox.isFieldSelected(unifiedSoc), true);
sandbox.toggleHaSelection(unifiedSoc, false);
assert(!sandbox.state.selectedHaKeys.has(`${data.batSn}:battery.compound.battery_soc`), 'Compound key must be deleted on deselect');
assert(!sandbox.state.selectedHaKeys.has(`${data.batSn}:battery.live.state_of_charge`), 'Legacy duplicate member_key must be deleted on deselect');

// 6. Ungrouped raw row (compound_key: null) toggles its own raw key directly
const ungroupedRaw = { ...rawStateName, compound_key: null, is_compound_raw: false };
assert.strictEqual(sandbox.getCompoundKeyForItem(ungroupedRaw), null);
sandbox.toggleHaSelection(ungroupedRaw, true);
assert(sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.live.inverter_state_name`));
sandbox.toggleHaSelection(ungroupedRaw, false);
assert(!sandbox.state.selectedHaKeys.has(`${data.invSn}:inverter.live.inverter_state_name`));

console.log('NODE_JS_TESTS_OK');
"""
        proc = subprocess.run(
            ["node", "-e", node_script],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, f"Node script failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        self.assertIn("NODE_JS_TESTS_OK", proc.stdout)

    def test_standalone_unified_view_save_preview_and_bridge_roundtrip(self):
        """Selecting standalone Unified View fields persists real keys and publishes them in preview & bridge."""
        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()
        bat_sn = self.client.state.get_battery().serial_number.strip().upper()

        selected_payload = [
            f"{inv_sn}:inverter.live.load_power_w",
            f"{bat_sn}:battery.battery.SoCMin",
            f"{inv_sn}:inverter.inverter.PF",
        ]
        save_resp = self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": selected_payload,
                "device_serials": [inv_sn, bat_sn],
                "merge": False,
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        saved_fields = save_resp.get_json()["selected_fields"]
        self.assertEqual(sorted(saved_fields), sorted(selected_payload))

        preview = self.test_client.get("/api/ha/preview").get_json()
        preview_keys = {(item["device_serial"].upper(), item["field_key"]) for item in preview}
        self.assertIn((inv_sn, "inverter.live.load_power_w"), preview_keys)
        self.assertIn((bat_sn, "battery.battery.SoCMin"), preview_keys)
        self.assertIn((inv_sn, "inverter.inverter.PF"), preview_keys)

        bridge = HomeAssistantBridge(client=self.client, published_topics_path=self.topics_path)
        mock_mqttc = MagicMock()
        bridge._mqttc = mock_mqttc
        bridge.reload_config_and_republish()

        published_topics = {call[0][0] for call in mock_mqttc.publish.call_args_list if call[0][1]}
        expected_load_topic = generate_discovery_payload(
            self.client.state.devices[self.client.state.get_inverter().serial_number].fields["inverter.live.load_power_w"],
            self.client.state.get_inverter(),
        )["config_topic"]
        self.assertIn(expected_load_topic, published_topics)

    def test_cold_start_preview_includes_inverter_state_and_battery_soc(self):
        """Freshly registered devices with zero polled fields still preview all default entities including inverter_state and battery_soc."""
        cold_client = PwrcellClient(is_mock=False)
        cold_client.state = StateStore()
        inv = cold_client.state.register_device("0001000714E9", slave_id=8, device_type="inverter", model_name="PWRcell Inverter")
        bat = cold_client.state.register_device("000100082128", slave_id=9, device_type="battery", model_name="PWRcell Battery")
        cold_client.state.register_device("BEACON01", slave_id=1, device_type="rebus_beacon", model_name="REbus Beacon")

        self.assertEqual(len(inv.fields), 0)
        self.assertEqual(len(bat.fields), 0)

        cold_app = create_app(cold_client)
        cold_test_client = cold_app.test_client()

        preview = cold_test_client.get("/api/ha/preview").get_json()
        by_key = {(item["device_serial"].upper(), item["field_key"]): item for item in preview}

        self.assertIn(("0001000714E9", "inverter.compound.inverter_state"), by_key)
        inv_state_payload = by_key[("0001000714E9", "inverter.compound.inverter_state")]["payload"]
        self.assertEqual(inv_state_payload.get("device_class"), "enum")
        self.assertTrue(inv_state_payload.get("options"))
        self.assertIn("GRID_CONNECTED", inv_state_payload["options"])

        self.assertIn(("000100082128", "battery.compound.battery_soc"), by_key)
        bat_soc_payload = by_key[("000100082128", "battery.compound.battery_soc")]["payload"]
        self.assertEqual(bat_soc_payload.get("unit_of_measurement"), "%")
        self.assertEqual(bat_soc_payload.get("device_class"), "battery")

        # Also check pre-populated conditional live sensor metadata
        self.assertIn(("0001000714E9", "inverter.live.inverter_max_power_w"), by_key)
        self.assertEqual(by_key[("0001000714E9", "inverter.live.inverter_max_power_w")]["payload"].get("unit_of_measurement"), "W")

    def test_modbus_only_inverter_state_preserves_enum_device_class(self):
        """inverter_state compound view keeps ha_device_class='enum' even when only Model 64207 St is populated."""
        store = StateStore()
        inv = store.register_device("0001000714E9", slave_id=8, device_type="inverter", model_name="PWRcell Inverter")
        store.ensure_field_definition(inv.serial_number, "inverter.model_64207.St")

        c_view = store.get_compound_view("inverter_state", device_sn=inv.serial_number)
        self.assertIsNotNone(c_view)
        self.assertEqual(c_view.ha_device_class, "enum")
        self.assertTrue(c_view.ha_options)

        disc = generate_discovery_payload(c_view, inv)["payload"]
        self.assertEqual(disc.get("device_class"), "enum")
        self.assertTrue(disc.get("options"))

    def test_ungrouping_inverter_state_name_allows_independent_exposure(self):
        """Ungrouping inverter.live.inverter_state_name preserves it in ha_config and exposes it alongside inverter.compound.inverter_state."""
        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number.strip().upper()

        set_field_grouping_override(inv_sn, "inverter.live.inverter_state_name", None)
        self.client.state.refresh_compound_links()

        save_resp = self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": [
                    f"{inv_sn}:inverter.live.inverter_state_name",
                    f"{inv_sn}:inverter.compound.inverter_state",
                ],
                "device_serial": inv_sn,
                "merge": False,
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        saved = save_resp.get_json()["selected_fields"]
        self.assertIn(f"{inv_sn}:inverter.live.inverter_state_name", saved)
        self.assertIn(f"{inv_sn}:inverter.compound.inverter_state", saved)

        preview = self.test_client.get("/api/ha/preview").get_json()
        preview_keys = [item["field_key"] for item in preview if item["device_serial"].upper() == inv_sn]
        self.assertIn("inverter.live.inverter_state_name", preview_keys)
        self.assertIn("inverter.compound.inverter_state", preview_keys)

        bridge = HomeAssistantBridge(client=self.client, published_topics_path=self.topics_path)
        mock_mqttc = MagicMock()
        bridge._mqttc = mock_mqttc
        bridge.reload_config_and_republish()

        live_field = inv.fields["inverter.live.inverter_state_name"]
        self.assertFalse(bridge._is_field_suppressed_by_compound(live_field))
        live_topic = generate_discovery_payload(live_field, inv)["config_topic"]
        comp_topic = generate_discovery_payload(
            self.client.state.get_compound_view("inverter_state", device_sn=inv_sn),
            inv,
        )["config_topic"]
        published_non_empty = {call[0][0] for call in mock_mqttc.publish.call_args_list if call[0][1]}
        self.assertIn(live_topic, published_non_empty)
        self.assertIn(comp_topic, published_non_empty)

    def test_deselecting_battery_soc_with_legacy_member_duplicate_and_803_soc(self):
        """Deduplicates legacy battery.live.state_of_charge, removes SoC from preview on deselect, and links Model 803 SoC."""
        bat_sn = self.client.state.get_battery().serial_number.strip().upper()
        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()

        # Model 803 lithium_ion_string.SoC must map to battery.compound.battery_soc
        raw_map = mapping_module.MappingRegistry.get_instance().get_raw_to_compound_map()
        self.assertEqual(raw_map.get("battery.lithium_ion_string.SoC"), "battery.compound.battery_soc")

        # Duplicate raw + compound collapses to compound only
        qualified = qualify_legacy_ha_config(
            [
                f"{bat_sn}:battery.compound.battery_soc",
                f"{bat_sn}:battery.live.state_of_charge",
                f"{inv_sn}:inverter.compound.grid_power",
            ],
            self.client.state,
        )
        self.assertIn(f"{bat_sn}:battery.compound.battery_soc", qualified)
        self.assertNotIn(f"{bat_sn}:battery.live.state_of_charge", qualified)

        # Save without battery_soc
        save_ha_config(qualified)
        resp = self.test_client.post(
            "/api/ha/config",
            json={
                "selected_fields": [f"{inv_sn}:inverter.compound.grid_power"],
                "device_serial": bat_sn,
                "merge": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        preview = self.test_client.get("/api/ha/preview").get_json()
        bat_preview_keys = {item["field_key"] for item in preview if item["device_serial"].upper() == bat_sn}
        self.assertNotIn("battery.compound.battery_soc", bat_preview_keys)
        self.assertNotIn("battery.live.state_of_charge", bat_preview_keys)

    def test_live_ui_preview_post_reflects_unsaved_changes_without_mutating_disk(self):
        """POST /api/ha/preview reflects unsaved selections & category overrides while disk config stays unchanged."""
        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()
        save_ha_config([f"{inv_sn}:inverter.compound.grid_power"])

        post_preview = self.test_client.post(
            "/api/ha/preview",
            json={
                "selected_fields": [
                    f"{inv_sn}:inverter.compound.grid_power",
                    f"{inv_sn}:inverter.compound.inverter_state",
                ],
                "category_overrides": {
                    f"{inv_sn}:inverter.compound.inverter_state": "primary",
                },
            },
        )
        self.assertEqual(post_preview.status_code, 200)
        items = post_preview.get_json()
        inv_state = next(
            (i for i in items if i["device_serial"].upper() == inv_sn and i["field_key"] == "inverter.compound.inverter_state"),
            None,
        )
        self.assertIsNotNone(inv_state)
        self.assertNotIn("entity_category", inv_state["payload"])

        # Disk ha_config.yaml and GET preview must remain unchanged
        disk_keys = load_ha_config(allow_default_seed=False)
        self.assertEqual(disk_keys, [f"{inv_sn}:inverter.compound.grid_power"])
        get_preview = self.test_client.get("/api/ha/preview").get_json()
        self.assertFalse(
            any(i["device_serial"].upper() == inv_sn and i["field_key"] == "inverter.compound.inverter_state" for i in get_preview)
        )

    def test_corrupted_v316_to_v3114_config_migration(self):
        """Repairs .standalone. and bogus .compound. keys created by v3.1.6-v3.1.14 and drops unresolvable ones."""
        cold_client = PwrcellClient(is_mock=False)
        cold_client.state = StateStore()
        inv_sn = "0001000714E9"
        bat_sn = "000100082128"
        cold_client.state.register_device(inv_sn, slave_id=8, device_type="inverter", model_name="PWRcell Inverter")
        cold_client.state.register_device(bat_sn, slave_id=9, device_type="battery", model_name="PWRcell Battery")

        corrupted = [
            f"{bat_sn}:battery.standalone.socmin_802",
            f"{inv_sn}:inverter.compound.load_power_w",
            f"{inv_sn}:inverter.compound.relaystatus_64208",
            f"{inv_sn}:inverter.compound.does_not_exist",
        ]
        repaired = qualify_legacy_ha_config(corrupted, cold_client.state)

        self.assertIn(f"{bat_sn}:battery.battery.SoCMin", repaired)
        self.assertIn(f"{inv_sn}:inverter.live.load_power_w", repaired)
        self.assertIn(f"{inv_sn}:inverter.inverter_status.RelayStatus", repaired)
        self.assertNotIn(f"{inv_sn}:inverter.compound.does_not_exist", repaired)

        save_ha_config(repaired)
        cold_app = create_app(cold_client)
        preview = cold_app.test_client().get("/api/ha/preview").get_json()
        p_keys = {(item["device_serial"].upper(), item["field_key"]) for item in preview}
        self.assertIn((bat_sn, "battery.battery.SoCMin"), p_keys)
        self.assertIn((inv_sn, "inverter.live.load_power_w"), p_keys)
        self.assertIn((inv_sn, "inverter.inverter_status.RelayStatus"), p_keys)

    def test_optimizer_compound_selection_and_addon_first_boot_groupings_seeding(self):
        """Optimizer honors .compound. keys, and add-on first boot preserves groupings.yaml transforms and metadata."""
        inv = self.client.state.get_inverter()
        inv_sn = inv.serial_number.strip().upper()
        groups = group_device_fields(
            inv,
            ha_selected_keys={f"{inv_sn}:inverter.compound.grid_power", f"{inv_sn}:inverter.compound.inverter_state"},
        )
        grid_grp = next((g for g in groups if g.id == "inverter.concept.grid_power"), None)
        state_grp = next((g for g in groups if g.id == "inverter.concept.inverter_state"), None)
        self.assertIsNotNone(grid_grp)
        self.assertIsNotNone(state_grp)
        self.assertTrue(grid_grp.is_selected)
        self.assertTrue(state_grp.is_selected)

        resolved_models = resolve_minimal_models_for_paths(
            [f"{inv_sn}:inverter.compound.grid_power", f"{inv_sn}:inverter.compound.inverter_state"],
            state_store=self.client.state,
        )
        self.assertIn("inverter", resolved_models)
        self.assertTrue(resolved_models["inverter"])

        # Add-on first boot seeding into empty PWRCELL_DATA_DIR
        fresh_data_dir = Path(self._tmp_dir.name) / "addon_data"
        target_groupings = fresh_data_dir / "groupings.yaml"
        self._patches[3].stop()
        try:
            with mock.patch("pwrcell.mapping.is_addon_data_env", return_value=True), mock.patch(
                "pwrcell.mapping.data_dir", return_value=fresh_data_dir
            ):
                mappings = mapping_module.load_mappings()
                self.assertTrue(target_groupings.exists())
                import yaml
                doc = yaml.safe_load(target_groupings.read_text(encoding="utf-8"))
                self.assertIs(doc.get("auto_group_heuristics"), False)
                grid_doc = next(g for g in doc["groups"] if g["id"] == "grid_power")
                self.assertEqual(grid_doc.get("device_type"), "inverter")
                self.assertEqual(grid_doc["fields"][0], "inverter.live.grid_power_w")
                self.assertEqual(grid_doc["fields"][1], {"path": "inverter.inverter_status.CTPow", "transform": "negate"})
                soc_m = next(m for m in mappings if m.id == "battery_soc")
                self.assertIn("battery.lithium_ion_string.SoC", soc_m.modbus_fields)

                # Verify save_mappings round-trip preserves device_type, auto_group_heuristics, and member_transforms
                resaved_path = fresh_data_dir / "resaved_groupings.yaml"
                mapping_module.save_mappings(mappings, resaved_path, auto_group_heuristics=False)
                resaved_doc = yaml.safe_load(resaved_path.read_text(encoding="utf-8"))
                self.assertIs(resaved_doc.get("auto_group_heuristics"), False)
                resaved_grid = next(g for g in resaved_doc["groups"] if g["id"] == "grid_power")
                self.assertEqual(resaved_grid.get("device_type"), "inverter")
                self.assertEqual(resaved_grid["fields"][0], "inverter.live.grid_power_w")
                self.assertEqual(resaved_grid["fields"][1], {"path": "inverter.inverter_status.CTPow", "transform": "negate"})
        finally:
            self._patches[3].start()

    def test_debug_logging_diagnostics(self):
        """DEBUG logs surface save diffs, repaired/collapsed keys, pre-populated definitions, and unmatched preview keys."""
        inv_sn = self.client.state.get_inverter().serial_number.strip().upper()

        with self.assertLogs("pwrcell.ui.routes.ha", level="DEBUG") as cm_route:
            resp = self.test_client.post(
                "/api/ha/config",
                json={"selected_fields": [f"{inv_sn}:inverter.compound.grid_power"], "device_serial": inv_sn, "merge": False},
            )
            self.assertEqual(resp.status_code, 200)
        self.assertTrue(any("POST /api/ha/config saving:" in line and "added=" in line and "removed=" in line for line in cm_route.output))

        with self.assertLogs("pwrcell.ha", level="DEBUG") as cm_ha:
            qualify_legacy_ha_config(
                [
                    f"{inv_sn}:inverter.compound.load_power_w",
                    f"{inv_sn}:inverter.compound.grid_power",
                    f"{inv_sn}:inverter.live.grid_power_w",
                ],
                self.client.state,
            )
        self.assertTrue(any("Repaired invalid compound HA key" in line for line in cm_ha.output))
        self.assertTrue(any("Collapsed redundant raw member" in line for line in cm_ha.output))

        fresh_store = StateStore()
        fresh_store.register_device(inv_sn, slave_id=8, device_type="inverter", model_name="PWRcell Inverter")
        with self.assertLogs("pwrcell.state", level="DEBUG") as cm_state:
            fresh_store.ensure_field_definition(inv_sn, "inverter.live.load_power_w")
        self.assertTrue(any("Pre-populated field definition 'inverter.live.load_power_w'" in line for line in cm_state.output))

        with self.assertLogs("pwrcell.ui.routes.ha", level="DEBUG") as cm_preview:
            self.test_client.post(
                "/api/ha/preview",
                json={"selected_fields": ["UNKNOWNSN999:inverter.live.load_power_w"]},
            )
        self.assertTrue(any("unmatched" in line and "device_not_registered" in line for line in cm_preview.output))


if __name__ == "__main__":
    unittest.main()
