"""Unit tests for generic SunSpec sub-group (groups) support."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from pwrcell.catalog import (
    format_group_field_label,
    format_group_label,
    get_catalog,
    should_ingest_model_groups,
    strip_group_indices,
)
from pwrcell.config import AppConfig
from pwrcell.controls import ControlDispatcher
from pwrcell.fixtures import MockFixtureLoader
from pwrcell.ha import (
    _resolve_standalone_or_orphan_slug,
    generate_discovery_payload,
    get_effective_ha_category,
)
from pwrcell.modbus import SerializedModbusClient
from pwrcell.optimizer import group_device_fields
from pwrcell.poller import DEFAULT_SLOW_PATHS, extract_model_groups
from pwrcell.state import FieldSource, StateStore


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
        bat = store.get_device("000100082128")
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
        details = store.get_field_modbus_details("000100082128", m1_soc.key)
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
        beacon_default = store_default.get_device("0001001206E8")
        pv_default = store_default.get_device("000100034AC7")
        self.assertIsNotNone(beacon_default)
        self.assertIsNotNone(pv_default)

        # Model 64200 devices ingested by default, including subgroup "ID"
        self.assertIn("rebus_beacon.REbus_dir.devices.1.ID", beacon_default.fields)
        self.assertFalse(any(k.startswith("rebus_beacon.schedule.repeating.") for k in beacon_default.fields))
        self.assertFalse(any(k.startswith("pv_link.flash_reader.sector.") for k in pv_default.fields))

        _, store_bulk = self._ingest_fixtures(include_bulk=True)
        beacon_bulk = store_bulk.get_device("0001001206E8")
        pv_bulk = store_bulk.get_device("000100034AC7")
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


if __name__ == "__main__":
    unittest.main()
