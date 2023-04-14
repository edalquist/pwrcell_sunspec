import dataclasses
from typing import Optional

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
  inverter: int | None = None
  pv_links: list[int] | None = None
  battery: int | None = None


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
