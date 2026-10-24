import dataclasses
import logging
import sys
from dataclasses import field
from pathlib import Path
from typing import Any, Dict, Optional

import dataconf

import os

logger = logging.getLogger(__name__)

_CONFIG_FILE = "pwrcell.yaml"
_DEVICE_FILE = "devices.yaml"


def is_addon_data_env() -> bool:
    """Return True if running inside an explicit PWRCELL_DATA_DIR or HA Add-on /data directory."""
    if os.environ.get("PWRCELL_DATA_DIR"):
        return True
    return Path("/data").is_dir() and Path("/data/options.json").exists()


def data_dir() -> Path:
    """Return the canonical persistent data directory for runtime configurations and caches."""
    env_dir = os.environ.get("PWRCELL_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    if Path("/data").is_dir() and Path("/data/options.json").exists():
        return Path("/data")
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "config").is_dir():
        return repo_root / "config"
    return repo_root


def _getConfigPath(file: str, for_write: bool = False) -> str:
    # 1. Environment variable override
    if file in (_CONFIG_FILE, "config.yaml", "pwrcell.yaml") and "PWRCELL_CONFIG" in os.environ:
        return os.environ["PWRCELL_CONFIG"]

    # 2. In Home Assistant add-on container or explicit PWRCELL_DATA_DIR
    if is_addon_data_env():
        data_f = data_dir() / file
        if for_write or data_f.exists() or file == _DEVICE_FILE:
            return str(data_f)

    # 3. Standard paths: check config/pwrcell.yaml, pwrcell.yaml, local_config.yaml, then config.yaml
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

  def get_device_map(self, device_type: str) -> Dict[str, int]:
    """Retrieve or initialize the slave map for any device type."""
    if not hasattr(self, device_type):
      setattr(self, device_type, {})
    return getattr(self, device_type)

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
      return dataconf.load(path, DeviceConfig)
    except FileNotFoundError as e:
      return None

  def write(self):
    target = _getConfigPath(_DEVICE_FILE, for_write=True)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    dataconf.dump(target, self, out='yaml')
