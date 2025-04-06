import logging
import os
import sys
import time
from pathlib import Path

import yaml
from absl import app, flags

import pwrcell
import pwrcell.models
from pwrcell.config import AppConfig
from pwrcell.mqtt import MqttClient as PwrCellMqttClient
from pwrcell.sunspec import SunspecClient as PwrCellSunspecClient
from pwrcell.tunnel import pwrcell_tunnel

FLAGS = flags.FLAGS
flags.DEFINE_enum("mode", "watch", ["watch", "scan", "mqtt", "ha"], "Mode to run CLI")

CONFIG: AppConfig = AppConfig.read()


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'

  log_level = logging.getLevelName(CONFIG.log_level) or logging.INFO
  logging.basicConfig(format=FORMAT, level=log_level)
  logging.getLogger("pwrcell").setLevel(log_level)
  logging.info("Setting Log Level to %s", log_level)

  with \
      pwrcell_tunnel(CONFIG) as tunnel_config, \
      PwrCellMqttClient(tunnel_config) as pwrcell_mqtt, \
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
