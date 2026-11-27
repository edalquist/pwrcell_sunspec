"""Tests for separate public config_dir() and private data_dir() storage & legacy HA migration (Issue #36)."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import yaml

from pwrcell import mapping as mapping_module
from pwrcell.bridge import get_default_published_topics_path
from pwrcell.config import (
    MIGRATION_MARKER_FILE,
    AppConfig,
    DeviceConfig,
    _getConfigPath,
    _is_usable_addon_config_dir,
    config_dir,
    data_dir,
    migrate_legacy_addon_configs,
)
from pwrcell.grouping import clear_custom_groupings_cache, get_default_grouping_config_path, save_custom_groupings
from pwrcell.ha import clear_ha_config_cache, get_default_ha_config_path, save_ha_config
from pwrcell.model_sync import load_models_dir
from pwrcell.safety import clear_blocked_fields_cache, get_blocked_fields_path
from pwrcell.setup_key import generate_config_from_options
from pwrcell.state import StateStore


class TestConfigAndDataDirs(unittest.TestCase):
    """Verify user-facing configuration separation, backwards compatibility, and startup migration."""

    def setUp(self):
        clear_ha_config_cache()
        clear_custom_groupings_cache()
        clear_blocked_fields_cache()
        mapping_module.MappingRegistry._instance = None

    def tearDown(self):
        clear_ha_config_cache()
        clear_custom_groupings_cache()
        clear_blocked_fields_cache()
        mapping_module.MappingRegistry._instance = None

    def test_split_config_dir_and_data_dir_routes_files_correctly(self):
        """User configs resolve under PWRCELL_CONFIG_DIR; runtime state/caches stay under PWRCELL_DATA_DIR."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg_path = tmp_path / "public_config"
            dat_path = tmp_path / "private_data"
            cfg_path.mkdir()
            dat_path.mkdir()
            pwrcell_yaml = dat_path / "pwrcell.yaml"
            pwrcell_yaml.write_text("testing: false\n", encoding="utf-8")

            env = {
                "PWRCELL_CONFIG_DIR": str(cfg_path),
                "PWRCELL_DATA_DIR": str(dat_path),
                "PWRCELL_CONFIG": str(pwrcell_yaml),
            }
            with patch.dict(os.environ, env):
                self.assertEqual(config_dir(), cfg_path)
                self.assertEqual(data_dir(), dat_path)

                # User-accessible files -> config_dir()
                self.assertEqual(get_default_ha_config_path(), cfg_path / "ha_config.yaml")
                self.assertEqual(get_default_grouping_config_path(), cfg_path / "custom_groupings.yaml")
                self.assertEqual(Path(_getConfigPath("devices.yaml", for_write=True)), cfg_path / "devices.yaml")
                self.assertEqual(mapping_module._resolve_mappings_path(for_write=True), cfg_path / "groupings.yaml")

                # Fresh install reads bundled groupings.yaml without creating an unmodified copy in config_dir()
                bundled_path = Path(mapping_module.__file__).resolve().parent / "data" / "groupings.yaml"
                self.assertEqual(mapping_module._resolve_mappings_path(), bundled_path)
                mapping_module.load_mappings()
                self.assertFalse((cfg_path / "groupings.yaml").exists())

                # Saving mappings writes to config_dir() / groupings.yaml; reset removes the override cleanly
                mapping_module.save_mappings(mapping_module.get_default_mappings())
                self.assertTrue((cfg_path / "groupings.yaml").exists())
                self.assertEqual(mapping_module._resolve_mappings_path(), cfg_path / "groupings.yaml")
                reset_dst = mapping_module.reset_mappings_to_defaults()
                self.assertEqual(reset_dst, bundled_path)
                self.assertFalse((cfg_path / "groupings.yaml").exists())

                # Write ha_config, custom_groupings, devices.yaml -> all land in config_dir()
                save_ha_config(["000100070008:inverter.live.grid_power_w"])
                self.assertTrue((cfg_path / "ha_config.yaml").exists())
                self.assertFalse((dat_path / "ha_config.yaml").exists())

                save_custom_groupings({"field_overrides": {"000100070008:inverter.inverter.W": "inverter_output_power"}})
                self.assertTrue((cfg_path / "custom_groupings.yaml").exists())
                self.assertFalse((dat_path / "custom_groupings.yaml").exists())

                DeviceConfig(inverter={"000100070008": 8}).write()
                self.assertTrue((cfg_path / "devices.yaml").exists())
                self.assertFalse((dat_path / "devices.yaml").exists())
                self.assertEqual(DeviceConfig.read().inverter.get("000100070008"), 8)

                # Optional blocked_fields.yaml override in config_dir() takes precedence over data_dir() and repo default
                user_blocked = cfg_path / "blocked_fields.yaml"
                user_blocked.write_text("blocked_fields:\n  - '*.TestPattern'\n", encoding="utf-8")
                self.assertEqual(get_blocked_fields_path(), user_blocked)

                # Private/runtime files -> data_dir()
                self.assertEqual(get_default_published_topics_path(), dat_path / ".ha_published_topics.json")
                self.assertEqual(Path(_getConfigPath("pwrcell.yaml")), pwrcell_yaml)
                self.assertEqual(load_models_dir(AppConfig(pwrcell=None)), dat_path / "sunspec-models")
                store = StateStore()
                self.assertEqual(store._get_offset_file(), dat_path / ".monotonic_offsets.json")

    def test_only_config_dir_set_keeps_caches_in_config_dir(self):
        """Setting only PWRCELL_CONFIG_DIR routes both config_dir() and data_dir() there."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "standalone_cfg"
            cfg_path.mkdir()
            clean_env = {k: v for k, v in os.environ.items() if k not in ("PWRCELL_DATA_DIR", "PWRCELL_CONFIG_DIR")}
            clean_env["PWRCELL_CONFIG_DIR"] = str(cfg_path)
            with patch.dict(os.environ, clean_env, clear=True):
                self.assertEqual(config_dir(), cfg_path)
                self.assertEqual(data_dir(), cfg_path)

    def test_standalone_defaults_to_repo_config(self):
        """Without env overrides or /data/options.json, config_dir() and data_dir() point to repo/config."""
        clean_env = {k: v for k, v in os.environ.items() if k not in ("PWRCELL_DATA_DIR", "PWRCELL_CONFIG_DIR")}
        repo_config = Path(__file__).resolve().parent.parent / "config"
        with patch.dict(os.environ, clean_env, clear=True), patch("pwrcell.config._is_ha_addon_env", return_value=False):
            self.assertEqual(config_dir(), repo_config)
            self.assertEqual(data_dir(), repo_config)

    def test_ha_core_config_guard_rejects_configuration_yaml_dir(self):
        """A directory containing configuration.yaml (HA Core /config) must not be treated as addon_config."""
        with tempfile.TemporaryDirectory() as tmp:
            ha_core_dir = Path(tmp) / "ha_core_config"
            ha_core_dir.mkdir()
            (ha_core_dir / "configuration.yaml").write_text("homeassistant:\n", encoding="utf-8")
            self.assertFalse(_is_usable_addon_config_dir(ha_core_dir))

            src_dir = Path(tmp) / "data"
            src_dir.mkdir()
            (src_dir / "ha_config.yaml").write_text("selected_fields:\n  - test\n", encoding="utf-8")
            res = migrate_legacy_addon_configs(src_dir=src_dir, dst_dir=ha_core_dir)
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(res["reason"], "dst_unusable")
            self.assertFalse((ha_core_dir / "ha_config.yaml").exists())
            self.assertFalse((src_dir / MIGRATION_MARKER_FILE).exists())

    def test_migrate_legacy_addon_configs_copies_non_destructively_and_respects_marker(self):
        """Migration copies user configs, skips identical groupings, preserves existing dst & src backups, and respects marker."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "data"
            dst = tmp_path / "config"
            src.mkdir()
            dst.mkdir()

            bundled_groupings = tmp_path / "bundled_groupings.yaml"
            bundled_groupings.write_text("version: '2.0'\ngroups: []\n", encoding="utf-8")

            # Legacy /data files
            (src / "ha_config.yaml").write_text("selected_fields:\n  - 000100070008:inverter.live.grid_power_w\n", encoding="utf-8")
            (src / "custom_groupings.yaml").write_text("field_overrides:\n  a: b\n", encoding="utf-8")
            (src / "devices.yaml").write_text("inverter:\n  '000100070008': 8\n", encoding="utf-8")
            (src / "blocked_fields.yaml").write_text("blocked_fields:\n  - '*.Foo'\n", encoding="utf-8")
            # Unmodified groupings.yaml identical to bundled defaults should NOT be copied
            (src / "groupings.yaml").write_bytes(bundled_groupings.read_bytes())
            # Private files should NOT be migrated
            (src / "pwrcell.yaml").write_text("testing: false\n", encoding="utf-8")
            (src / ".ha_published_topics.json").write_text("[]\n", encoding="utf-8")

            # Pre-existing file in dst must NEVER be overwritten
            (dst / "custom_groupings.yaml").write_text("field_overrides:\n  keep: me\n", encoding="utf-8")

            res = migrate_legacy_addon_configs(src_dir=src, dst_dir=dst, bundled_groupings_path=bundled_groupings)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(set(res["migrated"]), {"ha_config.yaml", "devices.yaml", "blocked_fields.yaml"})
            self.assertEqual(res["skipped_existing"], ["custom_groupings.yaml"])
            self.assertEqual(res["skipped_identical"], ["groupings.yaml"])

            # Verify migrated files + preserved pre-existing dst file + untouched private files
            self.assertTrue((dst / "ha_config.yaml").exists())
            self.assertTrue((dst / "devices.yaml").exists())
            self.assertTrue((dst / "blocked_fields.yaml").exists())
            self.assertIn("keep: me", (dst / "custom_groupings.yaml").read_text(encoding="utf-8"))
            self.assertFalse((dst / "groupings.yaml").exists())
            self.assertFalse((dst / "pwrcell.yaml").exists())
            self.assertFalse((dst / ".ha_published_topics.json").exists())

            # Originals in src stay intact for rollback safety
            self.assertTrue((src / "ha_config.yaml").exists())
            self.assertTrue((src / "devices.yaml").exists())

            # Marker written
            marker = src / MIGRATION_MARKER_FILE
            self.assertTrue(marker.exists())
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(marker_data["version"], 1)

            # Deleting devices.yaml in dst (e.g. Force Re-scan) must NOT re-copy from src on next run
            (dst / "devices.yaml").unlink()
            res2 = migrate_legacy_addon_configs(src_dir=src, dst_dir=dst, bundled_groupings_path=bundled_groupings)
            self.assertEqual(res2["status"], "noop")
            self.assertEqual(res2["reason"], "already_migrated")
            self.assertFalse((dst / "devices.yaml").exists())

    def test_migrate_legacy_addon_configs_copies_customized_groupings_and_resumes_partial(self):
        """Customized groupings.yaml is migrated, and interrupted migration resumes without overwriting."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "data"
            dst = tmp_path / "config"
            src.mkdir()
            dst.mkdir()

            bundled_groupings = tmp_path / "bundled_groupings.yaml"
            bundled_groupings.write_text("version: '2.0'\ngroups: []\n", encoding="utf-8")

            (src / "groupings.yaml").write_text("version: '2.0'\ngroups:\n  - id: custom\n", encoding="utf-8")
            (src / "ha_config.yaml").write_text("selected_fields: []\n", encoding="utf-8")
            # Simulate interrupted run where ha_config.yaml was copied before marker was written
            (dst / "ha_config.yaml").write_text("selected_fields:\n  - preserved\n", encoding="utf-8")

            res = migrate_legacy_addon_configs(src_dir=src, dst_dir=dst, bundled_groupings_path=bundled_groupings)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["migrated"], ["groupings.yaml"])
            self.assertEqual(res["skipped_existing"], ["ha_config.yaml"])
            self.assertIn("preserved", (dst / "ha_config.yaml").read_text(encoding="utf-8"))
            self.assertIn("custom", (dst / "groupings.yaml").read_text(encoding="utf-8"))

    def test_device_config_delete_only_deletes_config_dir_not_legacy_data_backup(self):
        """Force re-scan DeviceConfig.delete() removes config_dir()/devices.yaml and leaves /data backup untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg_path = tmp_path / "config"
            dat_path = tmp_path / "data"
            cfg_path.mkdir()
            dat_path.mkdir()
            (cfg_path / "devices.yaml").write_text("inverter:\n  '000100070008': 8\n", encoding="utf-8")
            (dat_path / "devices.yaml").write_text("inverter:\n  'LEGACY': 8\n", encoding="utf-8")

            with patch.dict(os.environ, {"PWRCELL_CONFIG_DIR": str(cfg_path), "PWRCELL_DATA_DIR": str(dat_path)}):
                self.assertTrue(DeviceConfig.delete())
                self.assertFalse((cfg_path / "devices.yaml").exists())
                self.assertTrue((dat_path / "devices.yaml").exists())

    def test_setup_key_warns_when_ssh_key_file_under_missing_config_mount(self):
        """generate_config_from_options warns clearly if ssh_key_file points to a missing /config/... path."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            opts_path = tmp_path / "options.json"
            cfg_out = tmp_path / "pwrcell.yaml"
            target_key = tmp_path / "nonexistent_id_rsa"
            opts_path.write_text(
                json.dumps({"ssh_key_file": "/config/ssh/pwrcell_key", "ssh_key": ""}),
                encoding="utf-8",
            )
            stderr_buf = io.StringIO()
            with redirect_stderr(stderr_buf):
                generate_config_from_options(
                    options_path=str(opts_path),
                    config_path=str(cfg_out),
                    target_key_path=str(target_key),
                )
            msg = stderr_buf.getvalue()
            self.assertIn("/addon_configs/<slug>", msg)
            self.assertIn("/config/ssh/pwrcell_key", msg)

    def test_addon_manifest_uses_addon_config_rw(self):
        """config.yaml maps addon_config:rw and share:rw without legacy HA Core config:rw."""
        addon_cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
        mappings = addon_cfg.get("map", [])
        self.assertIn("addon_config:rw", mappings)
        self.assertIn("share:rw", mappings)
        self.assertNotIn("config:rw", mappings)


if __name__ == "__main__":
    unittest.main()
