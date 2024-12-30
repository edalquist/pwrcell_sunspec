import dataclasses
import logging
import sys
from dataclasses import field
from pathlib import Path

import yaml
from yamldataclassconfig.config import YamlDataClassConfig

logger = logging.getLogger(__name__)

@dataclasses.dataclass
class SshTunnel(YamlDataClassConfig):
  host: str | None = None
  port: int = 22
  username: str = "root"
  identity_file: str | None = None


@dataclasses.dataclass
class PwrcellDeviceIds(YamlDataClassConfig):
  rebus_beacon: dict[str: int] = field(default_factory=dict)
  inverter: dict[str: int] = field(default_factory=dict)
  pv_link: dict[str: int] = field(default_factory=dict)
  battery: dict[str: int] = field(default_factory=dict)
  icm: dict[str: int] = field(default_factory=dict)


@dataclasses.dataclass
class PwrcellConfig(YamlDataClassConfig):
  ssh_tunnel: SshTunnel | None = None
  device_ids: PwrcellDeviceIds | None = None


@dataclasses.dataclass
class MqttConfig(YamlDataClassConfig):
  client_name: str | None = None
  host: str | None = None
  port: int = 1883
  username: str | None = None
  password: str | None = None


@dataclasses.dataclass
class RootConfig(YamlDataClassConfig):
  """Root config for App"""
  testing: bool = True
  poll_rate: int = 12  # TODO poll_rate_sec
  log_level: str = "INFO"
  pwrcell: PwrcellConfig | None = None
  mqtt: MqttConfig | None = None
  sunspec_cache_dir: str | None = None


def _getConfigPath() -> Path:
  return Path(sys.path[0]) / "config.yaml"

def loadConfig() -> RootConfig:
  config: RootConfig = RootConfig()
  config.load(_getConfigPath())
  return config

def saveConfig(config: RootConfig):
  with open(str(_getConfigPath()) + ".tmp", "w") as f:
    yaml.dump(config, f)