"""Unit tests for generic SunSpec sub-group (groups) support."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
from unittest.mock import MagicMock

from pwrcell import mapping as mapping_module
from pwrcell.catalog import (
    format_group_field_label,
    format_group_label,
    get_catalog,
    group_wildcard_matches_field_key,
    is_group_wildcard_key,
    should_ingest_model_groups,
    strip_group_indices,
    wildcard_group_path,
    wildcardize_group_field_key,
)
from pwrcell.client import PwrcellClient
from pwrcell.config import AppConfig
from pwrcell.controls import ControlDispatcher
from pwrcell.fixtures import MockFixtureLoader
from pwrcell.grouping import (
    clear_custom_groupings_cache,
    export_repo_groupings,
    is_field_excluded_from_mapping,
    load_custom_groupings,
)
from pwrcell.tools.correlator import evaluate_comparisons
from pwrcell.tools.recommender import extract_extremum, find_suggested_groupings
from pwrcell.ha import (
    _resolve_standalone_or_orphan_slug,
    clear_ha_config_cache,
    ensure_selected_field_definitions,
    generate_discovery_payload,
    generate_ha_default_config,
    get_effective_ha_category,
    is_field_selected,
    load_ha_config,
    qualify_legacy_ha_config,
    save_ha_config,
)
from pwrcell.modbus import SerializedModbusClient
from pwrcell.optimizer import group_device_fields, resolve_minimal_models_for_paths
from pwrcell.poller import DEFAULT_SLOW_PATHS, extract_model_groups
from pwrcell.state import FieldSource, StateStore
from pwrcell.ui.server import create_app


class TestCatalogSunspecGroups(unittest.TestCase):
    def setUp(self):
        self.catalog = get_catalog()

    def test_group_definitions_parsed_for_battery_and_nested_models(self):
        m804 = self.catalog.get_model(804)
        self.assertIsNotNone(m804)
        self.assertIn("lithium_ion_string_module", m804.groups)
        grp804 = m804.groups["lithium_ion_string_module"]
        self.assertTrue(grp804.is_repeating)
        self.assertGreater(grp804.base_offset, 0)
        self.assertGreater(grp804.size, 0)

        pt_modsoc = m804.get_group_point("lithium_ion_string_module.1", "ModSoC")
        self.assertIsNotNone(pt_modsoc)
        self.assertEqual(pt_modsoc.sf, "SoC_SF")
        self.assertEqual(pt_modsoc.units, "%")

        # Generac/SMDX metadata cleanup for 804.ModCellVMinCell
        pt_vmin_cell = m804.get_group_point("lithium_ion_string_module.1", "ModCellVMinCell")
        self.assertIsNotNone(pt_vmin_cell)
        self.assertIsNone(pt_vmin_cell.units)
        self.assertIsNone(pt_vmin_cell.sf)

        # 64252 DCB105_module defaults % unit on SOC/SOH
        m64252 = self.catalog.get_model(64252)
        self.assertIsNotNone(m64252)
        self.assertIn("DCB105_module", m64252.groups)
        self.assertEqual(m64252.get_group_point("DCB105_module.1", "SOC").units, "%")
        self.assertEqual(m64252.get_group_point("DCB105_module.1", "SOH").units, "%")

        # 64200 fixed block "ID" must not be clobbered by devices[].ID
        m64200 = self.catalog.get_model(64200)
        self.assertIsNotNone(m64200)
        fixed_id = m64200.points.get("ID")
        grp_id = m64200.get_group_point("devices.1", "ID")
        self.assertIsNotNone(fixed_id)
        self.assertIsNotNone(grp_id)
        self.assertIsNone(fixed_id.group_path)
        self.assertEqual(grp_id.group_path, "devices")
        self.assertNotEqual(fixed_id, grp_id)

        # 705 nested Crv.Pt
        m705 = self.catalog.get_model(705)
        self.assertIsNotNone(m705)
        self.assertIn("Crv", m705.groups)
        self.assertIn("Crv.Pt", m705.groups)
        pt_v = m705.get_group_point("Crv.1.Pt.2", "V")
        self.assertIsNotNone(pt_v)
        self.assertEqual(pt_v.group_path, "Crv.Pt")

    def test_group_filtering_and_label_helpers(self):
        # Raw flash buffer model 64258 is ALWAYS excluded
        self.assertFalse(should_ingest_model_groups(64258, "sector", include_bulk_tables=False))
        self.assertFalse(should_ingest_model_groups(64258, "sector", include_bulk_tables=True))

        # Bulk curve/schedule tables are opt-in
        for bulk_mid in (126, 133, 705):
            self.assertFalse(should_ingest_model_groups(bulk_mid, "repeating", include_bulk_tables=False))
            self.assertTrue(should_ingest_model_groups(bulk_mid, "repeating", include_bulk_tables=True))

        # Telemetry/status subgroups enabled by default
        for telemetry_mid in (401, 804, 64200, 64252):
            self.assertTrue(should_ingest_model_groups(telemetry_mid, "module", include_bulk_tables=False))

        self.assertEqual(strip_group_indices("lithium_ion_string_module.1"), "lithium_ion_string_module")
        self.assertEqual(strip_group_indices("Crv.1.Pt.2"), "Crv.Pt")
        self.assertEqual(format_group_label("lithium_ion_string_module.1", None, model_id=804), "Module 1")
        self.assertEqual(format_group_label("DCB105_module.4", None, model_id=64252), "Module 4")
        self.assertEqual(format_group_label("Crv.1.Pt.2", None, model_id=705), "Curve 1 / Point 2")
        self.assertEqual(
            format_group_field_label("Module 1", "Module State of Charge"),
            "Module 1 State of Charge",
        )


class TestMockFixturesAndStateStoreGroups(unittest.TestCase):
    def _ingest_fixtures(self, include_bulk: bool = False):
        loader = MockFixtureLoader(include_bulk_table_groups=include_bulk)
        store = StateStore(catalog=loader.catalog)
        for sn, mock_dev in loader.devices.items():
            store.register_device(
                serial_number=sn,
                slave_id=mock_dev.slave_id,
                device_type=mock_dev.device_type,
                model_name=mock_dev.model_name,
                manufacturer=mock_dev.manufacturer,
                version=mock_dev.version,
                supported_models=mock_dev.supported_models,
            )
            for model_id, models_list in mock_dev.models.items():
                for idx, model_inst in enumerate(models_list):
                    raw_pts = {p.name: p.raw_value for p in model_inst.points.values()}
                    comp_pts = {p.name: p.scaled_value for p in model_inst.points.values()}
                    store.update_from_modbus_points(
                        sn,
                        model_id,
                        raw_values=raw_pts,
                        computed_values=comp_pts,
                        instance_index=idx,
                        groups_data=model_inst.groups,
                        include_bulk_tables=include_bulk,
                    )
        return loader, store

    def test_battery_dump_ingests_all_six_modules_and_modbus_details(self):
        _, store = self._ingest_fixtures(include_bulk=False)
        bat = store.get_device("000100080009")
        self.assertIsNotNone(bat)

        # Model 804: 6 modules
        for idx in range(1, 7):
            f_soc = bat.fields.get(f"battery.lithium_ion_string.lithium_ion_string_module.{idx}.ModSoC")
            self.assertIsNotNone(f_soc, f"Missing 804 ModSoC for Module {idx}")
            self.assertEqual(f_soc.group_name, "lithium_ion_string_module")
            self.assertEqual(f_soc.group_index, idx)
            self.assertEqual(f_soc.group_path, f"lithium_ion_string_module.{idx}")
            self.assertEqual(f_soc.group_label, f"Module {idx}")

        m1_soc = bat.fields["battery.lithium_ion_string.lithium_ion_string_module.1.ModSoC"]
        self.assertEqual(m1_soc.value, 80.7)
        self.assertEqual(m1_soc.units, "%")
        m1_vmax = bat.fields["battery.lithium_ion_string.lithium_ion_string_module.1.ModCellVMax"]
        self.assertEqual(m1_vmax.value, 3.814)
        self.assertEqual(m1_vmax.units, "V")
        m1_tmax = bat.fields["battery.lithium_ion_string.lithium_ion_string_module.1.ModCellTmpMax"]
        self.assertEqual(m1_tmax.value, 21.8)
        m1_ncell = bat.fields["battery.lithium_ion_string.lithium_ion_string_module.1.ModNCell"]
        self.assertEqual(m1_ncell.value, 13)
        m1_vmin_cell = bat.fields["battery.lithium_ion_string.lithium_ion_string_module.1.ModCellVMinCell"]
        self.assertIsNone(m1_vmin_cell.value)

        m2_soc = bat.fields["battery.lithium_ion_string.lithium_ion_string_module.2.ModSoC"]
        self.assertEqual(m2_soc.value, 82.6)

        # Model 64252: 6 DCB105 modules
        dcb1_sn = bat.fields["battery.DCB105_warranty.DCB105_module.1.SN"]
        dcb1_soc = bat.fields["battery.DCB105_warranty.DCB105_module.1.SOC"]
        dcb1_packv = bat.fields["battery.DCB105_warranty.DCB105_module.1.PackV"]
        dcb2_sn = bat.fields["battery.DCB105_warranty.DCB105_module.2.SN"]
        dcb6_sn = bat.fields["battery.DCB105_warranty.DCB105_module.6.SN"]
        self.assertEqual(dcb1_sn.value, 13)
        self.assertEqual(dcb1_soc.value, 80.7)
        self.assertEqual(dcb1_packv.value, 49.79)
        self.assertEqual(dcb2_sn.value, 19)
        self.assertEqual(dcb6_sn.value, 21)

        # Offsets strictly increase across module instances
        self.assertGreater(m2_soc.offset, m1_soc.offset)

        # get_field_modbus_details resolves group metadata & parent scale factors
        details = store.get_field_modbus_details("000100080009", m1_soc.key)
        self.assertIsNotNone(details)
        self.assertEqual(details["group"]["index"], 1)
        self.assertEqual(details["group"]["label"], "Module 1")
        self.assertEqual(details["group"]["path"], "lithium_ion_string_module.1")
        self.assertIsNotNone(details["scale_factor"])
        self.assertEqual(details["scale_factor"]["name"], "SoC_SF")
        self.assertEqual(details["scale_factor"]["value"], -1)
        self.assertGreater(len(details["associated_registers"]), 0)

    def test_raw_buffers_excluded_and_bulk_tables_opt_in(self):
        _, store_default = self._ingest_fixtures(include_bulk=False)
        beacon_default = store_default.get_device("000100120001")
        pv_default = store_default.get_device("000100030003")
        self.assertIsNotNone(beacon_default)
        self.assertIsNotNone(pv_default)

        # Model 64200 devices ingested by default, including subgroup "ID"
        self.assertIn("rebus_beacon.REbus_dir.devices.1.ID", beacon_default.fields)
        self.assertFalse(any(k.startswith("rebus_beacon.schedule.repeating.") for k in beacon_default.fields))
        self.assertFalse(any(k.startswith("pv_link.flash_reader.sector.") for k in pv_default.fields))

        _, store_bulk = self._ingest_fixtures(include_bulk=True)
        beacon_bulk = store_bulk.get_device("000100120001")
        pv_bulk = store_bulk.get_device("000100030003")
        self.assertTrue(any(k.startswith("rebus_beacon.schedule.repeating.1.") for k in beacon_bulk.fields))
        # Model 64258 raw flash buffer stays excluded even when include_bulk_table_groups=True
        self.assertFalse(any(k.startswith("pv_link.flash_reader.sector.") for k in pv_bulk.fields))


class TestPollerAndControlsGroups(unittest.TestCase):
    def test_extract_model_groups_magicmock_and_real_groups(self):
        self.assertIn("battery.lithium_ion_string", DEFAULT_SLOW_PATHS)
        self.assertEqual(extract_model_groups(MagicMock(), 804), [])

        fake_pt = SimpleNamespace(value=807, cvalue=80.7, sf_point=None, sf_value=-1, pdef={"type": "uint16"})
        fake_grp1 = SimpleNamespace(points={"ModSoC": fake_pt}, groups=None)
        fake_model = SimpleNamespace(groups={"lithium_ion_string_module": [fake_grp1]})
        extracted = extract_model_groups(fake_model, 804, include_bulk_tables=False)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["group_name"], "lithium_ion_string_module")
        self.assertEqual(extracted[0]["group_index"], 1)
        self.assertEqual(extracted[0]["group_path"], "lithium_ion_string_module.1")
        self.assertEqual(extracted[0]["raw_values"]["ModSoC"], 807)
        self.assertEqual(extracted[0]["computed_values"]["ModSoC"], 80.7)

        # Raw buffer 64258 blocked at extraction time too
        self.assertEqual(extract_model_groups(SimpleNamespace(groups={"sector": [fake_grp1]}), 64258, True), [])

    def test_modbus_write_point_value_traverses_nested_group_path(self):
        client = SerializedModbusClient(host="127.0.0.1", port=502)
        client.worker.execute_sync = lambda fn, description="", retries=3: fn()
        client._ensure_device_connected = MagicMock()

        pt1 = MagicMock()
        pt1.cvalue = 100
        pt2 = MagicMock()
        pt2.cvalue = 102
        crv_inst = SimpleNamespace(
            groups={"Pt": [SimpleNamespace(points={"V": pt1}), SimpleNamespace(points={"V": pt2})]}
        )
        model_inst = MagicMock()
        model_inst.points = {}
        model_inst.groups = {"Crv": [crv_inst]}
        tcp_dev = SimpleNamespace(slave_id=8, models={705: [model_inst]})

        readback = client.write_point_value(
            tcp_dev,
            705,
            "V",
            105,
            group_path="Crv.1.Pt.2",
        )
        self.assertEqual(pt2.cvalue, 105)
        pt2.write.assert_called_once()
        model_inst.read.assert_called_once()
        self.assertEqual(readback, 105)

        with self.assertRaises(ValueError):
            client.write_point_value(tcp_dev, 705, "V", 105, group_path="Crv.99.Pt.1")

    def test_controls_write_field_forwards_group_path_and_preserves_metadata(self):
        store = StateStore()
        store.register_device("SN_TEST", 8, "inverter", "PWRcell Inverter")
        store.set_field(
            device_sn="SN_TEST",
            name="V_SF",
            label="Voltage Scale Factor",
            value=0,
            raw_value=0,
            source=FieldSource.MODBUS_POLL,
            access="R",
            point_type="sunssf",
            is_scale_factor=True,
            sub_group="DERVoltVar",
            model_id=705,
            model_name="DERVoltVar",
            model_label="DER Volt-Var",
        )
        store.set_field(
            device_sn="SN_TEST",
            name="V",
            label="Curve 1 / Point 2 Voltage Point",
            value=102,
            raw_value=102,
            units="VNomPct",
            source=FieldSource.MODBUS_POLL,
            access="RW",
            point_type="uint16",
            scale_factor_point="V_SF",
            sub_group="DERVoltVar",
            model_id=705,
            model_name="DERVoltVar",
            model_label="DER Volt-Var",
            group_name="Pt",
            group_index=2,
            group_path="Crv.1.Pt.2",
            group_label="Curve 1 / Point 2",
        )

        mock_mb = MagicMock()
        mock_mb.get_or_create_device.return_value = MagicMock()
        mock_mb.write_point_value.return_value = 105

        ctrl = ControlDispatcher(modbus_client=mock_mb, state_store=store)
        f_key = "inverter.DERVoltVar.Crv.1.Pt.2.V"
        res = ctrl.write_field(f_key, 105, device_sn="SN_TEST")
        self.assertEqual(res, 105)
        _, kwargs = mock_mb.write_point_value.call_args
        self.assertEqual(kwargs.get("group_path"), "Crv.1.Pt.2")

        updated = store.get_device("SN_TEST").fields[f_key]
        self.assertEqual(updated.group_name, "Pt")
        self.assertEqual(updated.group_index, 2)
        self.assertEqual(updated.group_path, "Crv.1.Pt.2")
        self.assertEqual(updated.group_label, "Curve 1 / Point 2")


class TestOptimizerAndHomeAssistantGroups(unittest.TestCase):
    def setUp(self):
        loader = MockFixtureLoader(include_bulk_table_groups=False)
        self.store = StateStore(catalog=loader.catalog)
        bat_mock = loader.devices_by_slave_id[9]
        self.store.register_device(
            serial_number=bat_mock.serial_number,
            slave_id=bat_mock.slave_id,
            device_type=bat_mock.device_type,
            model_name=bat_mock.model_name,
            manufacturer=bat_mock.manufacturer,
            version=bat_mock.version,
            supported_models=bat_mock.supported_models,
        )
        for model_id, models_list in bat_mock.models.items():
            for idx, model_inst in enumerate(models_list):
                self.store.update_from_modbus_points(
                    bat_mock.serial_number,
                    model_id,
                    raw_values={p.name: p.raw_value for p in model_inst.points.values()},
                    computed_values={p.name: p.scaled_value for p in model_inst.points.values()},
                    instance_index=idx,
                    groups_data=model_inst.groups,
                    include_bulk_tables=False,
                )
        self.bat = self.store.get_device(bat_mock.serial_number)

    def test_optimizer_isolates_per_module_concepts(self):
        groups = group_device_fields(self.bat, custom_groupings={}, category_overrides={})
        mod_soc_groups = [
            g for g in groups
            if g.group_name == "lithium_ion_string_module" and g.name == "ModSoC"
        ]
        self.assertEqual(len(mod_soc_groups), 6)
        self.assertEqual([g.group_index for g in mod_soc_groups], [1, 2, 3, 4, 5, 6])
        for g in mod_soc_groups:
            self.assertFalse(g.is_compound)
            self.assertEqual(len(g.sources), 1)
            self.assertEqual(g.ha_category, "diagnostic")

        dcb_soc_groups = [
            g for g in groups
            if g.group_name == "DCB105_module" and g.name == "SOC"
        ]
        self.assertEqual(len(dcb_soc_groups), 6)

    def test_ha_discovery_on_parent_device_and_slug_resolution(self):
        m1_soc = self.bat.fields["battery.lithium_ion_string.lithium_ion_string_module.1.ModSoC"]
        self.assertEqual(get_effective_ha_category(m1_soc, self.bat, category_overrides={}), "diagnostic")

        # Raw StateField discovery payload attaches to parent Battery device
        raw_payload_info = generate_discovery_payload(m1_soc, self.bat, category_overrides={})
        raw_pl = raw_payload_info["payload"]
        self.assertEqual(raw_pl["device"]["identifiers"], [f"pwrcell_{self.bat.serial_number}"])
        self.assertEqual(raw_pl["entity_category"], "diagnostic")
        self.assertEqual(raw_pl["name"], "Module 1 SoC")
        self.assertNotIn("concept_modsoc", " ".join(raw_payload_info["legacy_config_topics"]))

        # ConceptView discovery payload for subgroup field also attaches safely without crashing on ha_hint
        groups = group_device_fields(self.bat, custom_groupings={}, category_overrides={})
        m1_dcb_soc_cv = next(
            g for g in groups
            if g.group_path == "DCB105_module.1" and g.name == "SOC"
        )
        cv_payload_info = generate_discovery_payload(m1_dcb_soc_cv, self.bat, category_overrides={})
        cv_pl = cv_payload_info["payload"]
        self.assertEqual(cv_pl["device"]["identifiers"], [f"pwrcell_{self.bat.serial_number}"])
        self.assertEqual(cv_pl["entity_category"], "diagnostic")
        self.assertEqual(cv_pl["name"], "Module 1 State of Charge")
        self.assertEqual(cv_pl["unit_of_measurement"], "%")
        self.assertNotIn("concept_soc", " ".join(cv_payload_info["legacy_config_topics"]))

        # Slug resolution restores both raw sub-key slugs and concept slugs
        self.assertEqual(
            _resolve_standalone_or_orphan_slug(
                "battery",
                "lithium_ion_string_lithium_ion_string_module_1_modsoc",
                state_store=self.store,
                sn_hint=self.bat.serial_number,
            ),
            m1_soc.key,
        )
        self.assertEqual(
            _resolve_standalone_or_orphan_slug(
                "battery",
                "m804_lithium_ion_string_module_1_modsoc",
                state_store=self.store,
                sn_hint=self.bat.serial_number,
            ),
            m1_soc.key,
        )


class TestCatalogWildcardHelpers(unittest.TestCase):
    def test_wildcard_generation_and_matching(self):
        # Single-level repeating groups (M804 & M64252)
        self.assertEqual(
            wildcard_group_path("lithium_ion_string_module.1"),
            "lithium_ion_string_module.*",
        )
        self.assertEqual(wildcard_group_path("Crv.1.Pt.2"), "Crv.*.Pt.*")
        self.assertEqual(wildcard_group_path("live"), "live")

        wk_804 = wildcardize_group_field_key("battery.lithium_ion_string.lithium_ion_string_module.1.ModSoC")
        self.assertEqual(wk_804, "battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC")
        self.assertTrue(is_group_wildcard_key(wk_804))
        self.assertTrue(is_group_wildcard_key(f"000100080009:{wk_804}"))

        wk_dcb = wildcardize_group_field_key("000100080009:battery.DCB105_warranty.DCB105_module.6.SOC")
        self.assertEqual(wk_dcb, "000100080009:battery.DCB105_warranty.DCB105_module.*.SOC")

        # Nested group (M705 Crv.1.Pt.2) full and partial wildcards
        self.assertEqual(
            wildcardize_group_field_key("inverter.DERVoltVar.Crv.1.Pt.2.V"),
            "inverter.DERVoltVar.Crv.*.Pt.*.V",
        )
        self.assertTrue(
            group_wildcard_matches_field_key(
                "inverter.DERVoltVar.Crv.*.Pt.*.V",
                "inverter.DERVoltVar.Crv.3.Pt.12.V",
            )
        )
        self.assertTrue(
            group_wildcard_matches_field_key(
                "inverter.DERVoltVar.Crv.1.Pt.*.V",
                "inverter.DERVoltVar.Crv.1.Pt.4.V",
            )
        )
        self.assertFalse(
            group_wildcard_matches_field_key(
                "inverter.DERVoltVar.Crv.1.Pt.*.V",
                "inverter.DERVoltVar.Crv.2.Pt.4.V",
            )
        )

        # Non-group subdomains never produce wildcards or match
        for non_group in [
            "inverter.live.load_power_w",
            "inverter.compound.grid_power",
            "inverter.concept.grid_power",
            "inverter.unified.grid_power",
            "battery.battery.SoCMin",
            "battery.lithium_ion_string.SoC",
        ]:
            self.assertIsNone(wildcardize_group_field_key(non_group))
            self.assertFalse(is_group_wildcard_key(non_group))

        # Serial prefix mismatch must not match
        self.assertTrue(
            group_wildcard_matches_field_key(
                "SN_A:battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC",
                "SN_A:battery.lithium_ion_string.lithium_ion_string_module.3.ModSoC",
            )
        )
        self.assertFalse(
            group_wildcard_matches_field_key(
                "SN_A:battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC",
                "SN_B:battery.lithium_ion_string.lithium_ion_string_module.3.ModSoC",
            )
        )


class TestHaWildcardAndExplicitRules(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_dir.name)
        self.ha_config_path = tmp / "ha_config.yaml"
        self.groupings_path = tmp / "groupings.yaml"
        self.custom_groupings_path = tmp / "custom_groupings.yaml"
        pkg_groupings = Path(mapping_module.__file__).resolve().parent / "data" / "groupings.yaml"
        shutil.copy(pkg_groupings, self.groupings_path)

        self._patches = [
            mock.patch("pwrcell.ha.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_published_topics_path", return_value=tmp / ".ha_published_topics.json"),
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
        self.bat = self.client.state.get_battery()
        self.bat_sn = self.bat.serial_number.strip().upper()

    def tearDown(self):
        self.client.stop()
        for p in reversed(self._patches):
            p.stop()
        clear_ha_config_cache()
        clear_custom_groupings_cache()
        mapping_module.MappingRegistry._instance = None
        self._tmp_dir.cleanup()

    def test_wildcard_and_explicit_ha_config_save_and_preview_roundtrip(self):
        wk_modsoc = f"{self.bat_sn}:battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC"

        # 1. Save wildcard rule -> persists as 1 wildcard rule and previews 6 entities
        save_resp = self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": [wk_modsoc], "device_serial": self.bat_sn, "merge": False},
        )
        self.assertEqual(save_resp.status_code, 200)
        cfg_data = self.test_client.get("/api/ha/config").get_json()
        self.assertEqual(cfg_data["selected_fields"], [wk_modsoc])

        dev_data = self.test_client.get(f"/api/devices/{self.bat_sn}").get_json()
        mod_soc_raw = [f for f in dev_data["fields"].values() if f.get("group_name") == "lithium_ion_string_module" and f.get("name") == "ModSoC"]
        self.assertEqual(len(mod_soc_raw), 6)
        self.assertTrue(all(is_field_selected(f["key"], self.bat_sn, [wk_modsoc]) for f in mod_soc_raw))

        unified_data = self.test_client.get(f"/api/devices/{self.bat_sn}/unified_fields").get_json()["unified_fields"]
        mod_soc_uni = [f for f in unified_data if f.get("group_name") == "lithium_ion_string_module" and f.get("name") == "ModSoC"]
        self.assertEqual(len(mod_soc_uni), 6)
        self.assertTrue(all(f["is_selected"] for f in mod_soc_uni))

        preview = self.test_client.get("/api/ha/preview").get_json()
        mod_preview = [item for item in preview if item["device_serial"].upper() == self.bat_sn and ".ModSoC" in item["field_key"]]
        self.assertEqual(len(mod_preview), 6)
        self.assertEqual(len({item["payload"]["unique_id"] for item in mod_preview}), 6)

        # 2. Explicit partial selection (modules 1, 3, 5) persists explicit keys and previews 3 entities
        explicit_keys = [
            f"{self.bat_sn}:battery.lithium_ion_string.lithium_ion_string_module.{idx}.ModSoC"
            for idx in (1, 3, 5)
        ]
        self.test_client.post(
            "/api/ha/config",
            json={"selected_fields": explicit_keys, "device_serial": self.bat_sn, "merge": False},
        )
        cfg_explicit = self.test_client.get("/api/ha/config").get_json()
        self.assertEqual(cfg_explicit["selected_fields"], explicit_keys)

        preview_explicit = self.test_client.get("/api/ha/preview").get_json()
        self.assertEqual(
            [item["field_key"] for item in preview_explicit if ".ModSoC" in item["field_key"]],
            [
                "battery.lithium_ion_string.lithium_ion_string_module.1.ModSoC",
                "battery.lithium_ion_string.lithium_ion_string_module.3.ModSoC",
                "battery.lithium_ion_string.lithium_ion_string_module.5.ModSoC",
            ],
        )

        # 3. qualify_legacy_ha_config collapses redundant concrete keys when wildcard is also present
        collapsed = qualify_legacy_ha_config(
            [wk_modsoc] + explicit_keys,
            self.client.state,
        )
        self.assertEqual(collapsed, [wk_modsoc])

    def test_cold_start_wildcard_safety_creates_no_literal_star_field(self):
        cold_store = StateStore()
        cold_store.register_device(self.bat_sn, slave_id=9, device_type="battery", model_name="PWRcell Battery")
        bat_dev = cold_store.get_device(self.bat_sn)
        wk = "battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC"
        self.assertIsNone(cold_store.ensure_field_definition(self.bat_sn, wk))
        ensure_selected_field_definitions(cold_store, bat_dev, [f"{self.bat_sn}:{wk}"])
        self.assertFalse(any("*" in k for k in bat_dev.fields.keys()))

        cold_client = PwrcellClient(is_mock=False)
        cold_client.state = cold_store
        cold_app = create_app(cold_client)
        with self.assertLogs("pwrcell.ui.routes.ha", level="DEBUG") as cm:
            resp = cold_app.test_client().post(
                "/api/ha/preview",
                json={"selected_fields": [f"{self.bat_sn}:{wk}"]},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])
        self.assertTrue(any("group_wildcard_awaiting_poll" in line for line in cm.output))

    def test_wildcard_and_single_instance_category_overrides(self):
        wk_raw = "battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC"
        m2_raw = "battery.lithium_ion_string.lithium_ion_string_module.2.ModSoC"

        # 1. Wildcard override sets all 6 modules to primary (entity_category=None)
        res = self.test_client.post(
            "/api/ha/category_override",
            json={"device_serial": self.bat_sn, "field_key": wk_raw, "category": "primary"},
        )
        self.assertEqual(res.status_code, 200)
        overrides = res.get_json()["category_overrides"]
        for i in range(1, 7):
            f = self.bat.fields[f"battery.lithium_ion_string.lithium_ion_string_module.{i}.ModSoC"]
            self.assertIsNone(get_effective_ha_category(f, self.bat, overrides))

        # 2. Exact instance override on module 2 overrides the wildcard without affecting 1,3,4,5,6
        res2 = self.test_client.post(
            "/api/ha/category_override",
            json={"device_serial": self.bat_sn, "field_key": m2_raw, "category": "diagnostic"},
        )
        self.assertEqual(res2.status_code, 200)
        overrides2 = res2.get_json()["category_overrides"]
        self.assertEqual(
            get_effective_ha_category(self.bat.fields[m2_raw], self.bat, overrides2),
            "diagnostic",
        )
        for i in (1, 3, 4, 5, 6):
            f = self.bat.fields[f"battery.lithium_ion_string.lithium_ion_string_module.{i}.ModSoC"]
            self.assertIsNone(get_effective_ha_category(f, self.bat, overrides2))

        # 3. Updating wildcard override clears stale concrete instance override
        res3 = self.test_client.post(
            "/api/ha/category_override",
            json={"device_serial": self.bat_sn, "field_key": wk_raw, "category": "reset"},
        )
        self.assertEqual(res3.status_code, 200)
        overrides3 = res3.get_json()["category_overrides"]
        self.assertNotIn(f"{self.bat_sn}:{m2_raw}", overrides3)
        self.assertNotIn(f"{self.bat_sn}:{wk_raw}", overrides3)
        self.assertEqual(
            get_effective_ha_category(self.bat.fields[m2_raw], self.bat, overrides3),
            "diagnostic",
        )


class TestOptimizerWildcardResolution(unittest.TestCase):
    def setUp(self):
        loader = MockFixtureLoader(include_bulk_table_groups=False)
        self.store = StateStore(catalog=loader.catalog)
        bat_mock = loader.devices_by_slave_id[9]
        self.store.register_device(
            serial_number=bat_mock.serial_number,
            slave_id=bat_mock.slave_id,
            device_type=bat_mock.device_type,
            model_name=bat_mock.model_name,
            manufacturer=bat_mock.manufacturer,
            version=bat_mock.version,
            supported_models=bat_mock.supported_models,
        )
        for model_id, models_list in bat_mock.models.items():
            for idx, model_inst in enumerate(models_list):
                self.store.update_from_modbus_points(
                    bat_mock.serial_number,
                    model_id,
                    raw_values={p.name: p.raw_value for p in model_inst.points.values()},
                    computed_values={p.name: p.scaled_value for p in model_inst.points.values()},
                    instance_index=idx,
                    groups_data=model_inst.groups,
                    include_bulk_tables=False,
                )
        self.bat = self.store.get_device(bat_mock.serial_number)
        self.bat_sn = self.bat.serial_number.strip().upper()

    def test_optimizer_wildcard_marks_only_matching_group_and_model(self):
        wk_dcb_soc = f"{self.bat_sn}:battery.DCB105_warranty.DCB105_module.*.SOC"
        groups = group_device_fields(
            self.bat,
            custom_groupings={},
            ha_selected_keys={wk_dcb_soc},
            category_overrides={},
        )
        dcb_socs = [g for g in groups if g.group_name == "DCB105_module" and g.name == "SOC"]
        mod_socs = [g for g in groups if g.group_name == "lithium_ion_string_module" and g.name == "ModSoC"]
        self.assertEqual(len(dcb_socs), 6)
        self.assertTrue(all(g.is_selected for g in dcb_socs))
        self.assertTrue(all(not g.is_selected for g in mod_socs))

        resolved = resolve_minimal_models_for_paths([wk_dcb_soc], state_store=self.store)
        self.assertEqual(resolved.get("battery"), [64252])


class TestFrontendRollupAndWildcardSelection(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_dir.name)
        self.ha_config_path = tmp / "ha_config.yaml"
        self.groupings_path = tmp / "groupings.yaml"
        self.custom_groupings_path = tmp / "custom_groupings.yaml"
        pkg_groupings = Path(mapping_module.__file__).resolve().parent / "data" / "groupings.yaml"
        shutil.copy(pkg_groupings, self.groupings_path)

        self._patches = [
            mock.patch("pwrcell.ha.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_published_topics_path", return_value=tmp / ".ha_published_topics.json"),
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

    def test_frontend_rollup_builder_and_wildcard_selection_via_node(self):
        if shutil.which("node") is None:
            self.skipTest("node runtime unavailable")

        bat_sn = self.client.state.get_battery().serial_number.strip().upper()
        bat_unified = self.test_client.get(f"/api/devices/{bat_sn}/unified_fields").get_json()["unified_fields"]
        bat_raw = list(self.test_client.get(f"/api/devices/{bat_sn}").get_json()["fields"].values())

        node_script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const appJs = fs.readFileSync('pwrcell/ui/static/app.js', 'utf8');
const startIdx = appJs.indexOf('function getFieldDeviceSn(f)');
const endIdx = appJs.indexOf('// Value extraction helpers for multi-column sorting');
assert(startIdx !== -1 && endIdx !== -1 && endIdx > startIdx, 'Could not locate helper slice in app.js');
const helperCode = appJs.slice(startIdx, endIdx);

const data = JSON.parse(fs.readFileSync(0, 'utf8'));

const sandbox = {
  state: {
    activeDevice: { serial_number: data.batSn },
    activeFields: data.batRaw,
    unifiedFields: data.batUnified,
    selectedHaKeys: new Set(),
    modifiedDeviceSerials: new Set(),
    haCategoryOverrides: {},
    preferWildcardForGroups: true,
    searchQuery: '',
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

// 1. Subgroup items never return a compound key
const m1SocUni = data.batUnified.find(f => f.group_name === 'lithium_ion_string_module' && f.name === 'ModSoC' && f.group_index === 1);
assert(m1SocUni, 'Expected Module 1 ModSoC in battery unified_fields');
assert.strictEqual(sandbox.getCompoundKeyForItem(m1SocUni), null);

// 2. Rollup builder collapses 6-module points in unified and raw modes, leaving flat fields intact
const uniDisplay = sandbox.buildSubgroupRollups(data.batUnified, data.batUnified, true);
const modSocRollup = uniDisplay.find(x => x.isRollup && x.name === 'ModSoC' && x.group_name === 'lithium_ion_string_module');
assert(modSocRollup, 'Expected rolled-up ModSoC row');
assert.strictEqual(modSocRollup.instances.length, 6);
assert.strictEqual(modSocRollup.wildcardKey, 'battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC');
assert.strictEqual(uniDisplay.filter(x => x.isRollup && x.name === 'ModSoC').length, 1);

const flatSocRow = uniDisplay.find(x => !x.isRollup && (x.id === 'battery.compound.battery_soc' || x.active_source_key === 'battery.live.state_of_charge'));
assert(flatSocRow, 'Expected flat top-level SoC field to remain unrolled');

// Searching for Module 3 unrolls matched subset to concrete rows
sandbox.state.searchQuery = 'Module 3';
const mod3Matches = data.batUnified.filter(f => (f.label || '').includes('Module 3'));
const searchedDisplay = sandbox.buildSubgroupRollups(mod3Matches, data.batUnified, true);
const concreteMod3Soc = searchedDisplay.find(x => !x.isRollup && x.group_index === 3 && x.name === 'ModSoC');
assert(concreteMod3Soc, 'Expected Module 3 ModSoC to render as concrete row during targeted search');
sandbox.state.searchQuery = '';

// 3. Selecting rollup defaults to single wildcard key
sandbox.toggleRollupSelection(modSocRollup, true);
const expectedWk = `${data.batSn}:battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC`;
assert.strictEqual(sandbox.state.selectedHaKeys.size, 1);
assert(sandbox.state.selectedHaKeys.has(expectedWk), 'Rollup select-all must default to wildcard key');
let sel = sandbox.getRollupSelectionState(modSocRollup);
assert.strictEqual(sel.selectedCount, 6);
assert.strictEqual(sel.isAllSelected, true);
assert.strictEqual(sel.isIndeterminate, false);
assert.strictEqual(sel.mode, 'wildcard');

// 4. Switching rule mode toggles cleanly between Wildcard and 6 Explicit keys
sandbox.setRollupRuleMode(modSocRollup, 'explicit');
assert.strictEqual(sandbox.state.selectedHaKeys.size, 6);
assert(!sandbox.state.selectedHaKeys.has(expectedWk));
sel = sandbox.getRollupSelectionState(modSocRollup);
assert.strictEqual(sel.mode, 'explicit');
assert.strictEqual(sel.isAllSelected, true);

sandbox.setRollupRuleMode(modSocRollup, 'wildcard');
assert.strictEqual(sandbox.state.selectedHaKeys.size, 1);
assert(sandbox.state.selectedHaKeys.has(expectedWk));

// 5. Unchecking single instance (Module 2) splits wildcard -> 5 explicit keys
sandbox.toggleHaSelection(modSocRollup.instances[1], false);
sel = sandbox.getRollupSelectionState(modSocRollup);
assert.strictEqual(sel.selectedCount, 5);
assert.strictEqual(sel.isIndeterminate, true);
assert.strictEqual(sel.mode, 'explicit');
assert.strictEqual(sandbox.state.selectedHaKeys.size, 5);
assert(!sandbox.state.selectedHaKeys.has(`${data.batSn}:battery.lithium_ion_string.lithium_ion_string_module.2.ModSoC`));

// 6. Re-checking Module 2 auto-collapses 6 explicit keys back to single wildcard
sandbox.toggleHaSelection(modSocRollup.instances[1], true);
sel = sandbox.getRollupSelectionState(modSocRollup);
assert.strictEqual(sel.selectedCount, 6);
assert.strictEqual(sel.isAllSelected, true);
assert.strictEqual(sel.mode, 'wildcard');
assert.strictEqual(sandbox.state.selectedHaKeys.size, 1);
assert(sandbox.state.selectedHaKeys.has(expectedWk));

// 7. Raw mode rollup builds cleanly too
const rawDisplay = sandbox.buildSubgroupRollups(data.batRaw, data.batRaw, false);
const rawRollup = rawDisplay.find(x => x.isRollup && x.name === 'ModSoC' && x.group_name === 'lithium_ion_string_module');
assert(rawRollup && rawRollup.instances.length === 6, 'Expected raw-mode rollup for ModSoC');
"""
        proc = subprocess.run(
            ["node", "-e", node_script],
            input=json.dumps({"batSn": bat_sn, "batUnified": bat_unified, "batRaw": bat_raw}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Node VM check failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")


class TestSubgroupRecommenderAndCorrelator(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_dir.name)
        self.ha_config_path = tmp / "ha_config.yaml"
        self.groupings_path = tmp / "groupings.yaml"
        self.custom_groupings_path = tmp / "custom_groupings.yaml"
        pkg_groupings = Path(mapping_module.__file__).resolve().parent / "data" / "groupings.yaml"
        shutil.copy(pkg_groupings, self.groupings_path)

        self._patches = [
            mock.patch("pwrcell.ha.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_ha_config_path", return_value=self.ha_config_path),
            mock.patch("pwrcell.bridge.get_default_published_topics_path", return_value=tmp / ".ha_published_topics.json"),
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
        self.bat = self.client.state.get_battery()
        self.bat_sn = self.bat.serial_number.strip().upper()

    def tearDown(self):
        self.client.stop()
        for p in reversed(self._patches):
            p.stop()
        clear_ha_config_cache()
        clear_custom_groupings_cache()
        mapping_module.MappingRegistry._instance = None
        self._tmp_dir.cleanup()

    def test_strict_instance_isolation_and_rollup_suggestions(self):
        suggestions = find_suggested_groupings(self.client.state, dismissed_ids=set())
        bat_suggs = [s for s in suggestions if s.device_type == "battery"]
        self.assertGreater(len(bat_suggs), 0)

        for s in bat_suggs:
            # Verify no AVG vs MIN/MAX mixing
            exts = {extract_extremum(src.name, src.label) for src in s.sources}
            self.assertLessEqual(len(exts), 1, f"Mixed extremum/avg in {s.suggested_concept_key}: {exts}")

            # Verify no flat-vs-subgroup mixing and strict per-instance alignment
            gp_flags = {bool(src.group_path) for src in s.sources}
            self.assertEqual(len(gp_flags), 1, f"Mixed bank and subgroup in {s.suggested_concept_key}")
            if s.is_group_rollup:
                self.assertEqual(s.instance_count, 6)
                for inst in s.instances:
                    inst_indices = set()
                    for isrc in inst["sources"]:
                        f_obj = self.bat.fields[isrc["field_key"]]
                        inst_indices.add(f_obj.group_index)
                    self.assertEqual(len(inst_indices), 1, f"Cross-instance pairing in {inst}")

        soc_rollup = next(
            (
                s for s in bat_suggs
                if s.is_group_rollup
                and {src.field_key for src in s.sources} == {
                    "battery.DCB105_warranty.DCB105_module.*.SOC",
                    "battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC",
                }
            ),
            None,
        )
        self.assertIsNotNone(soc_rollup, "Expected single rolled-up M804 ModSoC <-> M64252 SOC suggestion")
        self.assertEqual(soc_rollup.instance_count, 6)
        self.assertEqual(soc_rollup.suggested_concept_key, "module_*_state_of_charge")

    def test_approve_rollup_compare_divergence_and_ungroup_all(self):
        # Mismatched instance merge must be rejected (HTTP 400)
        bad_resp = self.test_client.post(
            "/api/grouping/override",
            json={
                "device_sn": self.bat_sn,
                "field_key": "battery.lithium_ion_string.lithium_ion_string_module.1.ModSoC",
                "member_field_keys": ["battery.DCB105_warranty.DCB105_module.2.SOC"],
                "target_concept": "bad_cross_inst",
            },
        )
        self.assertEqual(bad_resp.status_code, 400)

        # Approve rolled-up suggestion via API
        suggs = self.test_client.get("/api/grouping/suggestions").get_json()["suggestions"]
        soc_sugg = next(
            s for s in suggs
            if s.get("is_group_rollup")
            and "battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC" in [src["field_key"] for src in s["sources"]]
        )
        approve_resp = self.test_client.post(
            "/api/grouping/suggestions/approve",
            json={
                "device_sn": soc_sugg["device_sn"],
                "field_keys": [src["field_key"] for src in soc_sugg["sources"]],
                "target_concept": soc_sugg["suggested_concept_key"],
                "label": soc_sugg["suggested_label"],
                "suggestion_id": soc_sugg["id"],
            },
        )
        self.assertEqual(approve_resp.status_code, 200)

        # Top-level battery_soc must remain unexcluded despite wildcard *.SOC override
        self.assertFalse(is_field_excluded_from_mapping(self.bat_sn, "battery.lithium_ion_string.SoC", "battery_soc"))
        self.assertIsNotNone(self.client.state.get_compound_view("battery_soc", device_sn=self.bat_sn))

        # Optimizer builds 6 aligned multi-source instance groups
        groups = group_device_fields(self.bat, custom_groupings=load_custom_groupings())
        soc_groups = [g for g in groups if g.concept_template == "module_*_state_of_charge"]
        self.assertEqual(len(soc_groups), 6)
        self.assertTrue(all(len(g.sources) == 2 for g in soc_groups))

        # /api/compare rolls up all 6 merged instances into one agreement row
        cmp_data = self.test_client.get("/api/compare").get_json()
        rollup_row = next(
            (r for r in cmp_data["comparisons"] if r.get("is_group_rollup") and r.get("concept_key") == "module_*_state_of_charge"),
            None,
        )
        self.assertIsNotNone(rollup_row)
        self.assertEqual(rollup_row["instance_count"], 6)
        self.assertIn(rollup_row["status"], ("EXACT", "CLOSE"))
        self.assertEqual(len(rollup_row["instances"]), 6)
        self.assertEqual(len(rollup_row["sample_field_keys"]), 12)

        # Divergence on a single instance surfaces on the rolled-up row and highlights that instance
        self.bat.fields["battery.lithium_ion_string.lithium_ion_string_module.3.ModSoC"].value = 25.0
        cmp_div = self.test_client.get("/api/compare").get_json()
        div_row = next(
            r for r in cmp_div["comparisons"]
            if r.get("is_group_rollup") and r.get("concept_key") == "module_*_state_of_charge"
        )
        self.assertTrue(div_row["is_discrepant"])
        self.assertEqual(div_row["status"], "DIVERGENT")
        self.assertIn("1/6 Divergent", div_row["status_label"])
        self.assertTrue(div_row["instances"][2]["is_discrepant"])
        self.assertFalse(div_row["instances"][0]["is_discrepant"])

        # Ungroup All cleanly reverts all 6 wildcard-merged instances in one call
        ungroup_resp = self.test_client.post(
            "/api/grouping/ungroup_all",
            json={"device_sn": self.bat_sn, "concept_key": "module_*_state_of_charge"},
        )
        self.assertEqual(ungroup_resp.status_code, 200)
        groups_after = group_device_fields(self.bat, custom_groupings=load_custom_groupings())
        self.assertFalse(any(g.concept_template == "module_*_state_of_charge" for g in groups_after))


class TestDefaultConfigsAndExporters(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_dir.name)
        self.ha_config_path = tmp / "ha_config.yaml"
        self.default_cfg_path = tmp / "ha_default_config.yaml"
        self.groupings_path = tmp / "groupings.yaml"
        self.custom_groupings_path = tmp / "custom_groupings.yaml"
        pkg_groupings = Path(mapping_module.__file__).resolve().parent / "data" / "groupings.yaml"
        shutil.copy(pkg_groupings, self.groupings_path)

        self._patches = [
            mock.patch("pwrcell.ha.get_default_ha_config_path", return_value=self.ha_config_path),
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

    def tearDown(self):
        self.client.stop()
        for p in reversed(self._patches):
            p.stop()
        clear_ha_config_cache()
        clear_custom_groupings_cache()
        mapping_module.MappingRegistry._instance = None
        self._tmp_dir.cleanup()

    def test_repo_default_configs_are_clean_and_exporters_preserve_portability(self):
        import yaml

        # 1. Verify shipped ha_default_config.yaml uses portable compounds, valid overrides, and wildcards
        default_doc = yaml.safe_load(Path("config/ha_default_config.yaml").read_text(encoding="utf-8"))
        sel = default_doc["selected_fields"]
        reg = mapping_module.MappingRegistry.get_instance()
        self.assertIn("battery.compound.battery_soc", sel)
        self.assertIn("inverter.compound.grid_power", sel)
        self.assertIn("pv_link.compound.rebus_power", sel)
        self.assertIn("battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC", sel)
        self.assertIn("battery.DCB105_warranty.DCB105_module.*.PackV", sel)
        self.assertNotIn("battery.compound.st_64207", sel)
        self.assertNotIn("inverter.compound.st_64207", sel)
        self.assertNotIn("inverter.compound.whin_64208", sel)
        for k in sel:
            self.assertNotIn(":", k)
            self.assertNotIn(".standalone.", k)
            self.assertNotIn(".concept.", k)
            if ".compound." in k:
                self.assertIsNotNone(reg.get_by_id(k.split(".")[-1]), f"Unknown compound in default config: {k}")
        default_ov = default_doc.get("category_overrides") or {}
        for ov_k in default_ov.keys():
            self.assertNotIn(".standalone.", ov_k)
            self.assertIn(".", ov_k)
        for pv_k in ("pv_link.REbus_status.I", "pv_link.REbus_status.St", "pv_link.REbus_status.V"):
            self.assertEqual(default_ov.get(pv_k), "primary")
        pvl_dev = self.client.state.get_devices_by_type("pv_link")[0]
        for pv_k in ("pv_link.REbus_status.I", "pv_link.REbus_status.St", "pv_link.REbus_status.V"):
            self.assertIsNone(get_effective_ha_category(pvl_dev.fields[pv_k], pvl_dev, default_ov))

        # Verify DC WhIn/WhOut remain in battery_imported/exported_energy and battery_ac_* are MQTT-only
        raw_to_comp = reg.get_raw_to_compound_map()
        self.assertEqual(raw_to_comp.get("battery.DCB105_warranty.WhIn"), "battery.compound.battery_imported_energy")
        self.assertEqual(raw_to_comp.get("battery.battery_status.WhIn"), "battery.compound.battery_imported_energy")
        self.assertEqual(raw_to_comp.get("battery.DCB105_warranty.WhOut"), "battery.compound.battery_exported_energy")
        self.assertEqual(raw_to_comp.get("battery.battery_status.WhOut"), "battery.compound.battery_exported_energy")
        ac_charged = reg.get_by_id("battery_ac_charged_energy")
        ac_discharged = reg.get_by_id("battery_ac_discharged_energy")
        self.assertIsNotNone(ac_charged)
        self.assertEqual(ac_charged.mqtt_fields, ["battery.live.storage_ac_charged_energy_wh"])
        self.assertEqual(ac_charged.modbus_fields, [])
        self.assertIsNotNone(ac_discharged)
        self.assertEqual(ac_discharged.mqtt_fields, ["battery.live.storage_ac_discharged_energy_wh"])
        self.assertEqual(ac_discharged.modbus_fields, [])

        # 2. export_repo_groupings omits ungrouped single-source & sub-group slots and keeps transforms/units
        export_target = Path(self._tmp_dir.name) / "exported_groupings.yaml"
        export_repo_groupings(self.client.state, target_path=export_target)
        exported_doc = yaml.safe_load(export_target.read_text(encoding="utf-8"))
        exported_ids = {g["id"] for g in exported_doc.get("groups", [])}
        self.assertIn("solar_power", exported_ids)
        self.assertIn("battery_soc", exported_ids)
        self.assertFalse(any(gid.startswith("m64200_devices_") for gid in exported_ids))
        grid_pwr = next(g for g in exported_doc["groups"] if g["id"] == "grid_power")
        self.assertIn({"path": "inverter.inverter_status.CTPow", "transform": "negate"}, grid_pwr["fields"])

        # 3. generate_ha_default_config canonicalizes .live. -> .compound., keeps wildcards,
        # repairs unambiguous bare <pt>_<model> slugs, and drops unknown/.standalone./ambiguous slugs
        save_ha_config(
            [
                "000100080009:battery.live.state_of_charge",
                "000100080009:battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC",
                "000100080009:battery.lithium_ion_string.lithium_ion_string_module.2.ModSoC",
                "000100070008:inverter.compound.local_custom_only",
                "000100080009:battery.standalone.socmin_802",
            ],
            config_path=self.ha_config_path,
            category_overrides={
                "000100080009:battery.standalone.does_not_exist": "primary",
                "000100080009:battery.REbus_status.V": "primary",
                "tmpot_102": "primary",
                "v_64207": "primary",
            },
        )
        res = generate_ha_default_config(source_path=self.ha_config_path, target_path=self.default_cfg_path)
        gen_sel = res["selected_fields"]
        self.assertIn("battery.compound.battery_soc", gen_sel)
        self.assertIn("battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC", gen_sel)
        self.assertIn("battery.battery.SoCMin", gen_sel)
        self.assertNotIn("battery.lithium_ion_string.lithium_ion_string_module.2.ModSoC", gen_sel)
        self.assertNotIn("inverter.compound.local_custom_only", gen_sel)
        gen_ov = res["data"].get("category_overrides", {})
        self.assertEqual(gen_ov, {"battery.REbus_status.V": "primary", "inverter.inverter.TmpOt": "primary"})

    def test_persisted_legacy_groupings_reload_and_reset_defaults(self):
        import yaml

        # Write a persisted 3.1.14-style groupings.yaml missing newer members and still
        # overlapping battery_ac_* with DC WhIn/WhOut registers
        legacy_doc = {
            "version": "2.0",
            "auto_group_heuristics": False,
            "groups": [
                {
                    "id": "inverter_state",
                    "name": "Inverter Operational State",
                    "device_type": "inverter",
                    "fields": [
                        "inverter.live.inverter_state_name",
                        "inverter.model_64207.St",
                        "inverter.model_102.St",
                        "inverter.inverter.StVnd",
                    ],
                },
                {
                    "id": "battery_imported_energy",
                    "name": "Battery Stored / Charged Energy",
                    "device_type": "battery",
                    "fields": [
                        "battery.live.battery_imported_energy_wh",
                        "battery.REbus_status.E",
                        "battery.DCB105_warranty.WhIn",
                    ],
                },
                {
                    "id": "battery_exported_energy",
                    "name": "Battery Discharged Energy",
                    "device_type": "battery",
                    "fields": [
                        "battery.live.battery_exported_energy_wh",
                        "battery.model_64252.WhOut",
                    ],
                },
                {
                    "id": "battery_ac_charged_energy",
                    "name": "Battery AC Charged Energy",
                    "device_type": "battery",
                    "fields": [
                        "battery.live.storage_ac_charged_energy_wh",
                        "battery.DCB105_warranty.WhIn",
                        "battery.model_64252.WhIn",
                    ],
                },
                {
                    "id": "battery_ac_discharged_energy",
                    "name": "Battery AC Discharged Energy",
                    "device_type": "battery",
                    "fields": [
                        "battery.live.storage_ac_discharged_energy_wh",
                        "battery.DCB105_warranty.WhOut",
                        "battery.model_64252.WhOut",
                    ],
                },
            ],
            "ungrouped_fields": ["battery.model_64252.V"],
        }
        self.groupings_path.write_text(yaml.safe_dump(legacy_doc, sort_keys=False), encoding="utf-8")

        reg = mapping_module.MappingRegistry.get_instance()
        reg.reload()

        # Reload backfills missing built-in members and strips stale DC WhIn/WhOut from battery_ac_*
        inv_state = reg.get_by_id("inverter_state")
        self.assertIn("inverter.DERMeasureAC.InvSt", inv_state.modbus_fields)
        bat_imp = reg.get_by_id("battery_imported_energy")
        self.assertIn("battery.battery_status.WhIn", bat_imp.modbus_fields)
        bat_exp = reg.get_by_id("battery_exported_energy")
        self.assertIn("battery.DCB105_warranty.WhOut", bat_exp.modbus_fields)
        ac_charged = reg.get_by_id("battery_ac_charged_energy")
        self.assertEqual(ac_charged.modbus_fields, [])
        ac_discharged = reg.get_by_id("battery_ac_discharged_energy")
        self.assertEqual(ac_discharged.modbus_fields, [])
        self.assertEqual(
            reg.get_raw_to_compound_map().get("battery.DCB105_warranty.WhIn"),
            "battery.compound.battery_imported_energy",
        )

        # POST /api/grouping/reset_defaults refreshes groupings.yaml on disk from packaged defaults
        app = create_app(self.client)
        test_client = app.test_client()
        resp = test_client.post("/api/grouping/reset_defaults")
        self.assertEqual(resp.status_code, 200)
        refreshed_doc = yaml.safe_load(self.groupings_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(refreshed_doc.get("groups", [])), 30)
        refreshed_ac = next(g for g in refreshed_doc["groups"] if g["id"] == "battery_ac_charged_energy")
        self.assertEqual(refreshed_ac["fields"], ["battery.live.storage_ac_charged_energy_wh"])


if __name__ == "__main__":
    unittest.main()
