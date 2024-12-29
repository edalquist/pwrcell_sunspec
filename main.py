import logging
import os
import sys
import time
from pathlib import Path

import yaml
from absl import app, flags

import pwrcell
import pwrcell.models
from pwrcell.config import RootConfig
from pwrcell.mqtt import MqttClient as PwrCellMqttClient
from pwrcell.sunspec import SunspecClient as PwrCellSunspecClient
from pwrcell.tunnel import pwrcell_tunnel

FLAGS = flags.FLAGS
flags.DEFINE_enum("mode", "watch", ["watch", "scan", "mqtt", "ha"], "Mode to run CLI")

CONFIG: RootConfig = RootConfig()
APP_PATH = Path(os.path.realpath(__file__)).parent


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  CONFIG.load(Path(sys.path[0]) / "config.yaml")
  if not CONFIG.sunspec_cache_dir:
    CONFIG.sunspec_cache_dir = APP_PATH

  log_level = logging.getLevelName(CONFIG.log_level) or logging.INFO
  logging.basicConfig(format=FORMAT, level=log_level)
  logging.getLogger("pwrcell").setLevel(log_level)
  logging.info("Setting Log Level to %s", log_level)

      # PwrCellMqttClient(tunnel_config) as pwrcell_mqtt, \
  with \
      pwrcell_tunnel(CONFIG) as tunnel_config, \
      PwrCellSunspecClient(CONFIG, tunnel_config) as pwrcell_sunspec:
    try:
      while True:
        start = time.time()
        sleep_time = max(0, CONFIG.poll_rate - (time.time() - start))
        logging.debug("Sleep for {}s".format(sleep_time))
        time.sleep(sleep_time)
    except KeyboardInterrupt as e:
      logging.info("Closing: %s", e)

    #   pwrcell.GeneracPwrCell(
    #       CONFIG.pwrcell.device_ids,
    #       ipaddr=server.local_bind_addresses[0][0],
    #       modbus_port=server.local_bind_ports[0],
    #       mqtt_port=server.local_bind_ports[1],
    #       timeout=60,
    #       extra_model_defs=[str(temp_models)]) as gpc:
    # if FLAGS.mode == "scan":
    #   gpc.scan()
    # else:
      # try:
      #   while True:
      #     start = time.time()
      #     gpc.read()
      #     # pwrcell_ha.loop()
      #     sleep_time = max(0, CONFIG.poll_rate - (time.time() - start))
      #     logging.debug("Sleep for {}s".format(sleep_time))
      #     time.sleep(sleep_time)
      # except KeyboardInterrupt as e:
      #   logging.info("Closing: %s", e)


if __name__ == '__main__':
  app.run(main)
