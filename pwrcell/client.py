from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

from .config import AppConfig
from .mqtt import MqttClient as PwrCellMqttClient
from .sunspec import SunspecClient as PwrCellSunspecClient
from .tunnel import pwrcell_tunnel


@dataclass
class PwrcellClient():
  sunspec: PwrCellSunspecClient
  mqtt: PwrCellMqttClient

@contextmanager
def create_client(config: AppConfig) -> Generator[PwrcellClient, None, None]:
  with \
      pwrcell_tunnel(config) as tunnel_config, \
      PwrCellSunspecClient(config, tunnel_config) as pwrcell_sunspec, \
      PwrCellMqttClient(tunnel_config) as pwrcell_mqtt:

    yield PwrcellClient(pwrcell_sunspec, pwrcell_mqtt)

