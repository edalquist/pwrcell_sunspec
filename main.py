import logging
import os
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager

import paho.mqtt.client as mqtt
import sunspec2.modbus.client as ss2_client
import yaml
from absl import app
from absl import flags
from sshtunnel import open_tunnel

import pwrcell
from config import RootConfig
from paramiko import SSHClient
from scp import SCPClient
from pathlib import Path
import filecmp


FLAGS = flags.FLAGS
flags.DEFINE_enum("mode", "watch", ["watch", "scan", "ha"], "Mode to run CLI")

CONFIG: RootConfig = RootConfig()
APP_PATH = Path(os.path.realpath(__file__)).parent


@contextmanager
def _open_tunnel():
  logging.info("opening pwrcell tunnel to %s:%s",
               CONFIG.pwrcell.ssh_tunnel.host, CONFIG.pwrcell.ssh_tunnel.port)
  with open_tunnel(
      (CONFIG.pwrcell.ssh_tunnel.host, CONFIG.pwrcell.ssh_tunnel.port),
      ssh_username=CONFIG.pwrcell.ssh_tunnel.username,
      ssh_pkey=CONFIG.pwrcell.ssh_tunnel.identity_file,
      local_bind_addresses=[
          ('127.0.0.1', ),
          ('127.0.0.1', ),
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


@contextmanager
def _sunspec_models():
  sunspec_cache_dir = Path(CONFIG.sunspec_cache_dir) if CONFIG.sunspec_cache_dir else APP_PATH
  with SSHClient() as ssh:
    ssh.load_system_host_keys()

    ssh.connect(CONFIG.pwrcell.ssh_tunnel.host,
                port=CONFIG.pwrcell.ssh_tunnel.port,
                username=CONFIG.pwrcell.ssh_tunnel.username,
                key_filename=CONFIG.pwrcell.ssh_tunnel.identity_file)
    logging.info("Checking for new sunspec models on %s", CONFIG.pwrcell.ssh_tunnel.host)

    with SCPClient(ssh.get_transport()) as scp:
      remote_version_file = sunspec_cache_dir / 'sunspec-models' / 'version.chk'
      scp.get('/opt/pika/sunspec-models/version',
              remote_version_file,
              preserve_times=True)
      cached_version_file = sunspec_cache_dir / 'sunspec-models' / 'version'
      if cached_version_file.exists() and filecmp.cmp(cached_version_file, remote_version_file):
        logging.info('Cached sunspec-models are up to date.')
        logging.info('Version: %s', cached_version_file.read_text())
      else:
        logging.info('New sunspec-models found, downloading...')
        logging.info('Cached Version: %s', cached_version_file.read_text() if cached_version_file.exists() else 'n/a')
        logging.info('Remote Version: %s', remote_version_file.read_text())

        # Recursively download all sunspec model files
        scp.get('/opt/pika/sunspec-models', sunspec_cache_dir, recursive=True, preserve_times=True)

  yield sunspec_cache_dir


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  CONFIG.load(os.path.join(sys.path[0], "config.yaml"))

  log_level = logging.getLevelName(CONFIG.log_level) or logging.INFO
  logging.basicConfig(format=FORMAT, level=log_level)
  logging.info("Setting Log Level to %s", log_level)

  with \
      _sunspec_models() as temp_models, \
      _open_tunnel() as server, \
      pwrcell.GeneracPwrCell(
          CONFIG.pwrcell.device_ids,
          ipaddr=server.local_bind_addresses[0][0],
          ipport=server.local_bind_ports[0], timeout=60,
          extra_model_defs=[str(temp_models)]) as gpc:
    if FLAGS.mode == "scan":
      gpc.scan()
    else:
      try:
        while True:
          start = time.time()
          gpc.read()
          # pwrcell_ha.loop()
          sleep_time = max(0, CONFIG.poll_rate - (time.time() - start))
          logging.debug("Sleep for {}s".format(sleep_time))
          time.sleep(sleep_time)
      except KeyboardInterrupt as e:
        logging.info("Closing: %s", e)


if __name__ == '__main__':
  app.run(main)
