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
from pwrcell.protos import energy_record_set_pb2
from pwrcell.sunspec import SunspecClient as PwrCellSunspecClient
from pwrcell.tunnel import pwrcell_tunnel

FLAGS = flags.FLAGS
flags.DEFINE_enum("mode", "watch", ["watch", "scan", "mqtt", "ha"], "Mode to run CLI")

CONFIG: AppConfig = AppConfig.read()

def __on_mqtt_update(pwrcell_sunspec: PwrCellSunspecClient, erl: energy_record_set_pb2.EnergyRecordSet):
  logging.info("CALLBACK")
  for inverter in pwrcell_sunspec.get_devices().inverter.values():
    # Code to print out all the data from all models
    # for name, models in inverter.models.items():
    #   for model in models:
    #     model.read()
    #     logging.info("%s: %s", name, model.get_json())

    inverter.inverter_status[0].read()
    # channelType=NET && deviceType=INVERTER
    # realPower_W
    logging.info("inverter_status.CTPow: %s", inverter.inverter_status[0].CTPow.cvalue * -1)
    # exportedEnergy_Ws
    logging.info("inverter_status.WhOut: %s", inverter.inverter_status[0].WhOut.cvalue * 60 * 60)
    logging.info("REbus_exp.Whx: %s", inverter.REbus_exp[0].Whx.cvalue * 60 * 60)
    # importedEnergy_Ws
    logging.info("inverter_status.WhIn: %s", inverter.inverter_status[0].WhIn.cvalue * 60 * 60)

    inverter.inverter[0].read()
    # channelType=INVERTER_OUTPUT && deviceType=INVERTER
    # realPower_W
    logging.info("inverter.W: %s", inverter.inverter[0].W.cvalue)
    # exportedEnergy_Ws
    logging.info("REbus_status.E: %s", inverter.REbus_status[0].E.cvalue)
    # importedEnergy_Ws
    logging.info("REbus_status.Whin: %s", inverter.REbus_exp[0].Whin.cvalue)
    # realPowerSourceMax_W -- ???
    # realPowerSinkMax_W -- ???

    # channelType=INVERTER_OUTPUT && deviceType=INVERTER
    # importedEnergy_Ws -- ???
    # realPower_W -- ???


    inverter.inverter[0].read()
    logging.info("W: %s", inverter.inverter[0].W.cvalue)
    # inverter.inverter_status[0].CTPow.read()

def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'

  log_level = logging.getLevelName(CONFIG.log_level) or logging.INFO
  logging.basicConfig(format=FORMAT, level=log_level)
  logging.getLogger("pwrcell").setLevel(log_level)
  logging.info("Setting Log Level to %s", log_level)

  with \
      pwrcell_tunnel(CONFIG) as tunnel_config, \
      PwrCellSunspecClient(CONFIG, tunnel_config) as pwrcell_sunspec, \
      PwrCellMqttClient(tunnel_config) as pwrcell_mqtt:
      # PwrCellSunspecClient(CONFIG, tunnel_config) as pwrcell_sunspec:
    try:
      pwrcell_mqtt.register_callback(lambda erl: __on_mqtt_update(pwrcell_sunspec, erl))

      while True:
        start = time.time()

        # for inverter in pwrcell_sunspec.get_devices().inverter.values():
        #   inverter.inverter_status[0].read()
        #   # inverter.inverter_status[0].CTPow.read()
        #   value = inverter.inverter_status[0].CTPow.cvalue
        #   logging.info("CTPow: %s", value)

        sleep_time = max(0, CONFIG.poll_rate - (time.time() - start))
        logging.debug("Sleep for {}s".format(sleep_time))
        time.sleep(sleep_time)

    except KeyboardInterrupt as e:
      logging.info("Closing: %s", e)


if __name__ == '__main__':
  app.run(main)
