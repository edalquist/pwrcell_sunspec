import logging
import filecmp

from contextlib import contextmanager
from sshtunnel import open_tunnel, SSHTunnelForwarder
from pathlib import Path
from typing import Generator

from pwrcell.config import RootConfig

@contextmanager
def pwrcell_tunnel(config: RootConfig) -> Generator[SSHTunnelForwarder, None, None]:
  logging.info("opening pwrcell tunnel to %s:%s",
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
    logging.info("pwrcell tunnel listening. ModBus=%s, MQTT=%s",
                 server.local_bind_ports[0], server.local_bind_ports[1])
    yield server