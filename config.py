import dataclasses
from dataclasses import field
from typing import Optional, Set

from yamldataclassconfig.config import YamlDataClassConfig


@dataclasses.dataclass
class SshTunnel(YamlDataClassConfig):
  host: str | None = None
  port: int = 22
  username: str = "root"
  identity_file: str | None = None


@dataclasses.dataclass
class PwrcellDeviceIds(YamlDataClassConfig):
  rebus_beacon: int | None = None
  inverter: list[int] = field(default_factory=list)
  pv_links: list[int] = field(default_factory=list)
  battery: list[int] = field(default_factory=list)
  icm: int | None = None


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
