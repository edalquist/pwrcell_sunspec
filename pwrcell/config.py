import dataclasses
from datetime import datetime, timezone
import json
import logging
import os
import shutil
import sys
from dataclasses import field
from pathlib import Path
from typing import Any, Dict, List, Optional

import dataconf
from dataconf.exceptions import MalformedConfigException
import yaml

logger = logging.getLogger(__name__)

_CONFIG_FILE = "pwrcell.yaml"
_DEVICE_FILE = "devices.yaml"
_BLOCKED_FIELDS_FILE = "blocked_fields.yaml"
MIGRATION_MARKER_FILE = ".config_migrated.json"
MIGRATABLE_CONFIG_FILES = (
    "ha_config.yaml",
    "custom_groupings.yaml",
    "devices.yaml",
    "groupings.yaml",
    "telemetry_mappings.yaml",
    "blocked_fields.yaml",
)


def _is_ha_addon_env() -> bool:
    """Return True when running inside a Home Assistant Add-on container (/data/options.json present)."""
    return Path("/data").is_dir() and Path("/data/options.json").exists()


def is_addon_data_env() -> bool:
    """Return True if running inside an explicit PWRCELL_DATA_DIR or HA Add-on /data directory."""
    if os.environ.get("PWRCELL_DATA_DIR"):
        return True
    return _is_ha_addon_env()


def is_custom_config_env() -> bool:
    """Return True if running with PWRCELL_CONFIG_DIR, PWRCELL_DATA_DIR, or inside an HA Add-on."""
    if os.environ.get("PWRCELL_CONFIG_DIR"):
        return True
    return is_addon_data_env()


def _is_usable_addon_config_dir(path: Path = Path("/config")) -> bool:
    """Return True if path is a writable HA app_config/addon_config mount (not HA Core /config)."""
    try:
        if not path.is_dir():
            return False
        if (path / "configuration.yaml").exists():
            return False
        return os.access(path, os.W_OK)
    except OSError:
        return False


def data_dir() -> Path:
    """Return the canonical persistent data directory for private configs, runtime state, and caches."""
    env_dir = os.environ.get("PWRCELL_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    if _is_ha_addon_env():
        return Path("/data")
    cfg_env_dir = os.environ.get("PWRCELL_CONFIG_DIR")
    if cfg_env_dir:
        return Path(cfg_env_dir)
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config").is_dir():
        return repo_root / "config"
    return repo_root


def config_dir() -> Path:
    """Return the canonical user-accessible configuration directory."""
    env_dir = os.environ.get("PWRCELL_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    data_env_dir = os.environ.get("PWRCELL_DATA_DIR")
    if data_env_dir:
        return Path(data_env_dir)
    if _is_ha_addon_env():
        addon_cfg = Path("/config")
        if _is_usable_addon_config_dir(addon_cfg):
            return addon_cfg
        return Path("/data")
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config").is_dir():
        return repo_root / "config"
    return repo_root


def _getConfigPath(file: str, for_write: bool = False) -> str:
    # 1. Environment variable override for main pwrcell.yaml
    if file in (_CONFIG_FILE, "config.yaml", "pwrcell.yaml") and "PWRCELL_CONFIG" in os.environ:
        return os.environ["PWRCELL_CONFIG"]

    # 2. User-accessible config files in custom config env (HA Add-on /config or PWRCELL_CONFIG_DIR / PWRCELL_DATA_DIR)
    if is_custom_config_env():
        if file == _DEVICE_FILE:
            return str(config_dir() / _DEVICE_FILE)
        if file == _BLOCKED_FIELDS_FILE:
            cfg_f = config_dir() / _BLOCKED_FIELDS_FILE
            if for_write or cfg_f.exists():
                return str(cfg_f)
            legacy_f = data_dir() / _BLOCKED_FIELDS_FILE
            if legacy_f.exists():
                return str(legacy_f)
        if file in (_CONFIG_FILE, "config.yaml", "pwrcell.yaml") and os.environ.get("PWRCELL_CONFIG_DIR"):
            cfg_f = config_dir() / _CONFIG_FILE
            if for_write or cfg_f.exists():
                return str(cfg_f)

    # 3. In Home Assistant add-on container or explicit PWRCELL_DATA_DIR
    if is_addon_data_env():
        data_f = data_dir() / file
        if for_write or data_f.exists():
            return str(data_f)

    # 4. Standard paths: check config/pwrcell.yaml, pwrcell.yaml, local_config.yaml, then config.yaml
    repo_root = Path(__file__).resolve().parent.parent
    bases = [Path.cwd(), repo_root]
    if sys.path and sys.path[0]:
        bases.append(Path(sys.path[0]))

    if file in (_CONFIG_FILE, "config.yaml", "pwrcell.yaml"):
        for base in bases:
            for candidate in (
                "config/pwrcell.yaml",
                "config/local_config.yaml",
                "config/config.yaml",
                "pwrcell.yaml",
                "local_config.yaml",
            ):
                p = base / candidate
                if p.exists():
                    return str(p)

    for base in bases:
        for p in (base / "config" / file, base / file):
            if p.exists():
                return str(p)

    return str(data_dir() / file)


def _atomic_copy_file(src: Path, dst: Path) -> None:
    """Copy src to dst atomically using a temporary file in dst.parent and os.replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.migrate.tmp"
    try:
        data = src.read_bytes()
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            shutil.copystat(src, tmp)
        except OSError:
            pass
        os.replace(tmp, dst)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _atomic_write_json(target: Path, payload: Dict[str, Any]) -> None:
    """Write JSON atomically using temp file + fsync + os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def migrate_legacy_addon_configs(
    src_dir: Optional[Path | str] = None,
    dst_dir: Optional[Path | str] = None,
    bundled_groupings_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """One-time, non-destructive copy of user-facing config files from /data to /config.

    Leaves original files in src_dir intact as a rollback safety net, never overwrites
    existing files in dst_dir, and writes a marker file so subsequent deletions in dst_dir
    do not resurrect stale copies from src_dir.
    """
    src = Path(src_dir) if src_dir is not None else data_dir()
    dst = Path(dst_dir) if dst_dir is not None else config_dir()

    empty_res: Dict[str, Any] = {
        "migrated": [],
        "skipped_existing": [],
        "skipped_identical": [],
        "source_dir": str(src),
        "target_dir": str(dst),
    }

    try:
        if src.resolve() == dst.resolve():
            return {"status": "noop", "reason": "same_dir", **empty_res}
    except OSError:
        if src == dst:
            return {"status": "noop", "reason": "same_dir", **empty_res}

    marker = src / MIGRATION_MARKER_FILE
    if marker.exists():
        return {"status": "noop", "reason": "already_migrated", **empty_res}

    if not _is_usable_addon_config_dir(dst):
        logger.warning(
            "Skipping legacy config migration: destination %s is missing, read-only, or contains configuration.yaml",
            dst,
        )
        return {"status": "skipped", "reason": "dst_unusable", **empty_res}

    bundled = (
        Path(bundled_groupings_path)
        if bundled_groupings_path is not None
        else (Path(__file__).resolve().parent / "data" / "groupings.yaml")
    )
    bundled_bytes: Optional[bytes] = None
    if bundled.is_file():
        try:
            bundled_bytes = bundled.read_bytes()
        except OSError:
            bundled_bytes = None

    migrated: List[str] = []
    skipped_existing: List[str] = []
    skipped_identical: List[str] = []

    for fname in MIGRATABLE_CONFIG_FILES:
        if fname == "telemetry_mappings.yaml" and (
            (dst / "groupings.yaml").exists() or (src / "groupings.yaml").exists()
        ):
            continue

        src_file = src / fname
        if not src_file.is_file():
            continue

        dst_file = dst / fname
        if dst_file.exists():
            skipped_existing.append(fname)
            logger.info("Migration preserved existing %s (skipped copying %s)", dst_file, src_file)
            continue

        if fname == "groupings.yaml" and bundled_bytes is not None:
            try:
                if src_file.read_bytes() == bundled_bytes:
                    skipped_identical.append(fname)
                    logger.info(
                        "Skipping migration of unmodified %s (identical to bundled defaults)",
                        src_file,
                    )
                    continue
            except OSError:
                pass

        _atomic_copy_file(src_file, dst_file)
        migrated.append(fname)
        logger.info("Migrated user config %s -> %s (kept original as backup)", src_file, dst_file)

    marker_payload = {
        "version": 1,
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(src),
        "target_dir": str(dst),
        "migrated": migrated,
        "skipped_existing": skipped_existing,
        "skipped_identical": skipped_identical,
    }
    _atomic_write_json(marker, marker_payload)

    return {
        "status": "ok",
        "migrated": migrated,
        "skipped_existing": skipped_existing,
        "skipped_identical": skipped_identical,
        "source_dir": str(src),
        "target_dir": str(dst),
    }


@dataclasses.dataclass
class SshTunnel:
  host: str | None = None
  port: int = 22
  username: str = "root"
  identity_file: str | None = None
  password: str | None = None
  key_passphrase: str | None = None


@dataclasses.dataclass
class PwrcellConfig:
  ssh_tunnel: SshTunnel | None = None
  # device_ids: PwrcellDeviceIds | None = None


@dataclasses.dataclass
class MqttConfig:
  client_name: str | None = None
  host: str | None = None
  port: int = 1883
  username: str | None = None
  password: str | None = None


@dataclasses.dataclass
class AppConfig:
  """Root config for App"""
  testing: bool = True
  poll_rate: int = 12  # Fast telemetry poll interval in seconds
  config_poll_interval: int = 45  # Config & keypad sync interval in seconds
  slow_poll_interval: int = 300  # Slow accumulators & diagnostics interval in seconds
  enable_polling: bool = True  # Enable background Modbus polling
  log_level: str = "INFO"
  pwrcell: PwrcellConfig | None = None
  mqtt: MqttConfig | None = None
  sunspec_cache_dir: str | None = None
  telemetry_mappings_file: str = "telemetry_mappings.yaml"
  polling_tiers: Dict[str, Any] | None = None  # Path-based tier configuration (fast, config, slow)
  include_bulk_table_groups: bool = False  # Opt-in to expose large repeating curve/schedule table groups
  blocked_fields: List[str] = field(default_factory=list)
  unblocked_fields: List[str] = field(default_factory=list)

  @classmethod
  def read(cls) -> 'AppConfig':
    config_path = _getConfigPath(_CONFIG_FILE)
    try:
      return dataconf.load(config_path, AppConfig)
    except FileNotFoundError:
      logger.info("Config file %s not found, using defaults", config_path)
      return cls()
    except Exception as e:
      logger.error("Failed to load config from %s: %s", config_path, e)
      raise

  def write(self):
    target = _getConfigPath(_CONFIG_FILE, for_write=True)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    dataconf.dump(target, self, out='yaml')


@dataclasses.dataclass
class DeviceConfig:
  rebus_beacon: Dict[str, int] = field(default_factory=dict)
  inverter: Dict[str, int] = field(default_factory=dict)
  pv_link: Dict[str, int] = field(default_factory=dict)
  battery: Dict[str, int] = field(default_factory=dict)
  icm: Dict[str, int] = field(default_factory=dict)

  def __post_init__(self):
    for f in dataclasses.fields(self):
      if getattr(self, f.name) is None:
        setattr(self, f.name, {})

  def get_device_map(self, device_type: str) -> Dict[str, int]:
    """Retrieve or initialize the slave map for any device type."""
    current = getattr(self, device_type, None)
    if not isinstance(current, dict):
      current = {}
      setattr(self, device_type, current)
    return current

  def to_dict(self) -> Dict[str, Dict[str, int]]:
    """Return all configured device categories as a dictionary."""
    return {
      k: v for k, v in self.__dict__.items()
      if not k.startswith("_") and isinstance(v, dict)
    }

  @classmethod
  def read(cls) -> Optional['DeviceConfig']:
    path = _getConfigPath(_DEVICE_FILE)
    try:
      with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    except FileNotFoundError:
      return None

    if raw is None:
      return cls()

    if not isinstance(raw, dict):
      raise MalformedConfigException(
        f"expected mapping in {path}, got {type(raw).__name__}"
      )

    normalized: Dict[str, Any] = {}
    for k, v in raw.items():
      key = str(k)
      if v is None:
        normalized[key] = {}
      elif isinstance(v, dict):
        normalized[key] = {str(sn): slave_id for sn, slave_id in v.items()}
      else:
        normalized[key] = v

    return dataconf.dict(normalized, cls)

  @classmethod
  def delete(cls) -> bool:
    """Delete the cached devices.yaml configuration file if it exists."""
    deleted = False
    candidates = {
      Path(_getConfigPath(_DEVICE_FILE, for_write=True)),
      Path(_getConfigPath(_DEVICE_FILE, for_write=False)),
      config_dir() / _DEVICE_FILE,
      Path("config") / _DEVICE_FILE,
      Path(_DEVICE_FILE),
    }
    for p in candidates:
      if p.exists() and p.is_file():
        try:
          p.unlink()
          deleted = True
          logger.info("Deleted device cache at %s", p)
        except Exception as e:
          logger.warning("Could not delete device cache at %s: %s", p, e)
    return deleted

  def write(self):
    target = Path(_getConfigPath(_DEVICE_FILE, for_write=True))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Dict[str, int]] = {}
    for f in dataclasses.fields(self):
      val = getattr(self, f.name, None)
      payload[f.name] = val if isinstance(val, dict) else {}

    tmp_target = target.with_suffix(target.suffix + ".tmp")
    try:
      with open(tmp_target, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)
      os.replace(tmp_target, target)
    except Exception:
      if tmp_target.exists():
        try:
          tmp_target.unlink()
        except OSError:
          pass
      raise


if __name__ == "__main__":
  logging.basicConfig(format="[%(levelname)s] %(message)s", level=logging.INFO)
  if len(sys.argv) > 1 and sys.argv[1] == "migrate":
    migrate_legacy_addon_configs()
