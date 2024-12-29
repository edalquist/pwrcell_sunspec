import dataclasses
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sshtunnel import open_tunnel

from .config import RootConfig

logger = logging.getLogger(__name__)

@dataclasses.dataclass
class TunnelConfig():
  host: str | None = None
  mqtt_port: int | None = None
  modbus_port: int | None = None

@contextmanager
def pwrcell_tunnel(config: RootConfig) -> Generator[TunnelConfig, None, None]:
  logger.info("opening pwrcell tunnel to %s:%s",
               config.pwrcell.ssh_tunnel.host, config.pwrcell.ssh_tunnel.port)
  with open_tunnel(
      (config.pwrcell.ssh_tunnel.host, config.pwrcell.ssh_tunnel.port),
      ssh_username=config.pwrcell.ssh_tunnel.username,
      ssh_pkey=config.pwrcell.ssh_tunnel.identity_file,
      local_bind_addresses=[
          ('127.0.0.1', ), # ModBus - random free port
          ('127.0.0.1', ), # MQTT - random free port
      ],
      remote_bind_addresses=[
          ('127.0.0.1', 502),   # ModBus
          ('127.0.0.1', 1883),  # MQTT
      ],
      set_keepalive=4.0,
  ) as server:
    config = TunnelConfig(
      host=server.local_bind_hosts[0],
      mqtt_port=server.local_bind_ports[1],
      modbus_port=server.local_bind_ports[0],
    )
    logger.info("pwrcell tunnel listening: %s",
                 config)
    yield config