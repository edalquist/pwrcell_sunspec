import dataclasses
import logging
import sys
from dataclasses import field
from pathlib import Path
from typing import Any, Dict

import dataconf

import os

logger = logging.getLogger(__name__)

_CONFIG_FILE = "pwrcell.yaml"
_DEVICE_FILE = "devices.yaml"

def _getConfigPath(file: str) -> str:
    # 1. Environment variable override
    if file in (_CONFIG_FILE, "config.yaml", "pwrcell.yaml") and "PWRCELL_CONFIG" in os.environ:
        return os.environ["PWRCELL_CONFIG"]

    # 2. In Home Assistant add-on container (/data/options.json exists)
    if Path("/data").is_dir() and Path("/data/options.json").exists():
        data_f = Path("/data") / file
        if data_f.exists():
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
                "config.yaml",
            ):
                p = base / candidate
                if p.exists():
                    return str(p)

    for base in bases:
        for p in (base / "config" / file, base / file):
            if p.exists():
                return str(p)

    if (repo_root / "config").is_dir():
        return str(repo_root / "config" / file)
    return str(repo_root / file)


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
    except Exception as e:
      logger.warning("Could not load config from %s (%s), returning defaults", config_path, e)
      return cls()

  def write(self):
    target = "/data/pwrcell.yaml" if Path("/data").is_dir() and Path("/data/options.json").exists() else _getConfigPath(_CONFIG_FILE)
    dataconf.dump(target, self, out='yaml')


@dataclasses.dataclass
class DeviceConfig:
  rebus_beacon: Dict[str, int] = field(default_factory=dict)
  inverter: Dict[str, int] = field(default_factory=dict)
  pv_link: Dict[str, int] = field(default_factory=dict)
  battery: Dict[str, int] = field(default_factory=dict)
  icm: Dict[str, int] = field(default_factory=dict)

  @classmethod
  def read(cls) -> 'DeviceConfig':
    path = _getConfigPath(_DEVICE_FILE)
    try:
      return dataconf.load(path, DeviceConfig)
    except FileNotFoundError as e:
      return None

  def write(self):
    dataconf.dump(_getConfigPath(_DEVICE_FILE), self, out='yaml')
