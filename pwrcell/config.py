import dataclasses
import logging
import sys
from dataclasses import field
from pathlib import Path
from typing import Dict

import dataconf

logger = logging.getLogger(__name__)

_CONFIG_FILE = "config.yaml"
_DEVICE_FILE = "devices.yaml"

def _getConfigPath(file: str) -> str:
  return str(Path(sys.path[0]) / file)


@dataclasses.dataclass
class SshTunnel:
  host: str | None = None
  port: int = 22
  username: str = "root"
  identity_file: str | None = None


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
  poll_rate: int = 12  # TODO poll_rate_sec
  log_level: str = "INFO"
  pwrcell: PwrcellConfig | None = None
  mqtt: MqttConfig | None = None
  sunspec_cache_dir: str | None = None

  @classmethod
  def read(cls) -> 'AppConfig':
    return dataconf.load(_getConfigPath(_CONFIG_FILE), AppConfig)

  def write(self):
    dataconf.dump(_getConfigPath(_CONFIG_FILE), self, out='yaml')


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
