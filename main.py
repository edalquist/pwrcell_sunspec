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

# import homeassistant
import pwrcell
from config import RootConfig

FLAGS = flags.FLAGS
flags.DEFINE_enum("mode", "watch", ["watch", "scan", "ha"], "Mode to run CLI")

CONFIG: RootConfig = RootConfig()\



@contextmanager
def _open_tunnel():
  logging.info("opening pwrcell tunnel to %s:%s",
               CONFIG.pwrcell.ssh_tunnel.host, CONFIG.pwrcell.ssh_tunnel.port)
  with open_tunnel(
      (CONFIG.pwrcell.ssh_tunnel.host, CONFIG.pwrcell.ssh_tunnel.port),
      ssh_username=CONFIG.pwrcell.ssh_tunnel.username,
      ssh_pkey=CONFIG.pwrcell.ssh_tunnel.identity_file,
      local_bind_address=('127.0.0.1', ),
      remote_bind_address=('127.0.0.1', 502),
      set_keepalive=4.0,
  ) as server:
    logging.info("pwrcell tunnel listening on %s:%s",
                 server.local_bind_address[0], server.local_bind_port)
    yield server


@contextmanager
def _sunspec_models():
  with tempfile.TemporaryDirectory() as tempdir:
    logging.info("Extracting sunspec models to %s", tempdir)
    zf = zipfile.ZipFile(os.path.join(sys.path[0], "sunspec-models.zip"))
    zf.extractall(tempdir)
    yield os.path.join(tempdir, "sunspec-models")


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  CONFIG.load(os.path.join(sys.path[0], "config.yaml"))

  log_level = logging.getLevelName(CONFIG.log_level) or logging.INFO
  logging.basicConfig(format=FORMAT, level=log_level)
  logging.info("Setting Log Level to %s", log_level)

  with _open_tunnel() as server, \
      _sunspec_models() as temp_models, \
      pwrcell.GeneracPwrCell(
          CONFIG.pwrcell.device_ids,
          ipaddr=server.local_bind_address[0],
          ipport=server.local_bind_port, timeout=60,
          extra_model_defs=[temp_models]) as gpc:
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
