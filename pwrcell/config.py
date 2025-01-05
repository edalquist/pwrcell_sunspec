import dataclasses
import logging
import sys
from dataclasses import asdict, field
from pathlib import Path

import yaml
from yamldataclassconfig.config import YamlDataClassConfig

logger = logging.getLogger(__name__)

_CONFIG_FILE = "config.yaml"
_DEVICE_FILE = "devices.yaml"

def _getConfigPath(file: str) -> Path:
  return Path(sys.path[0]) / file


@dataclasses.dataclass
class SshTunnel(YamlDataClassConfig):
  host: str | None = None
  port: int = 22
  username: str = "root"
  identity_file: str | None = None


@dataclasses.dataclass
class PwrcellConfig(YamlDataClassConfig):
  ssh_tunnel: SshTunnel | None = None
  # device_ids: PwrcellDeviceIds | None = None


@dataclasses.dataclass
class MqttConfig(YamlDataClassConfig):
  client_name: str | None = None
  host: str | None = None
  port: int = 1883
  username: str | None = None
  password: str | None = None


@dataclasses.dataclass
class AppConfig(YamlDataClassConfig):
  """Root config for App"""
  testing: bool = True
  poll_rate: int = 12  # TODO poll_rate_sec
  log_level: str = "INFO"
  pwrcell: PwrcellConfig | None = None
  mqtt: MqttConfig | None = None
  sunspec_cache_dir: str | None = None

  @classmethod
  def read(cls) -> 'AppConfig':
    config = cls()
    config.load(_getConfigPath(_CONFIG_FILE))
    return config

  def write(self):
    with open(str(_getConfigPath(_CONFIG_FILE)), "w") as f:
      yaml.safe_dump(asdict(self), f)



@dataclasses.dataclass
class DeviceConfig(YamlDataClassConfig):
  rebus_beacon: dict[str: int] = field(default_factory=dict)
  inverter: dict[str: int] = field(default_factory=dict)
  pv_link: dict[str: int] = field(default_factory=dict)
  battery: dict[str: int] = field(default_factory=dict)
  icm: dict[str: int] = field(default_factory=dict)

  @classmethod
  def read(cls) -> 'DeviceConfig|None':
    path = _getConfigPath(_DEVICE_FILE)
    config = cls()
    try:
      config.load(path)
    except FileNotFoundError as e:
      return None
    except Exception as e:
      logger.warning('Failed to load device config from %s: %s', path, e)
      return None
    return config

  def write(self):
    with open(str(_getConfigPath(_DEVICE_FILE)), "w") as f:
      yaml.dump(self.to_dict(), f)

