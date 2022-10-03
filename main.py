from absl import app
from absl import flags
import homeassistant
import logging
import os
import paho.mqtt.client as mqtt
import pwrcell
import sunspec2.modbus.client as ss2_client
import sys
import tempfile
import time
import yaml
import zipfile


def on_connect(client, userdata, flags, rc):
  # The callback for when the client receives a CONNACK response from the server.
  print("Connected with result code "+str(rc))

  # Subscribing in on_connect() means that if we lose the connection and
  # reconnect then subscriptions will be renewed.
  # client.subscribe("$SYS/#")


def on_message(client, userdata, msg):
  # The callback for when a PUBLISH message is received from the server.
  print(msg.topic+" "+str(msg.payload))


def on_read(point: ss2_client.SunSpecModbusClientPoint):
  logging.debug("Callback: %s.%s.%s to %s",
                point.model.device.name, point.model.gname, point.pdef['name'], point.value)


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  logging.basicConfig(format=FORMAT, level=logging.INFO)

  config = {}
  with open(os.path.join(sys.path[0], "config.yaml")) as config_file:
    config = yaml.safe_load(config_file)

  log_level = logging.getLevelName(config['log_level']) or logging.INFO
  logging.info("Setting Log Level to %s", logging.getLevelName(log_level))
  logging.basicConfig(format=FORMAT, level=log_level)

  mqtt_client = mqtt.Client(
      client_id=config['mqtt']['client_name'] + ('_test' if config.get('testing', False) else ''))
  mqtt_client.enable_logger()
  mqtt_client.on_connect = on_connect
  mqtt_client.on_message = on_message

  mqtt_client.username_pw_set(
      config['mqtt']['username'], config['mqtt']['password'])
  mqtt_client.connect_async(config['mqtt']['host'], config['mqtt']['port'], 60)

  with tempfile.TemporaryDirectory() as tempdir:
    logging.debug("Extracting sunspec models to %s", tempdir)
    zf = zipfile.ZipFile(os.path.join(sys.path[0], "sunspec-models.zip"))
    zf.extractall(tempdir)

    device_config = pwrcell.Config(
        rebus_beacon=config['pwrcell']['device_ids']['rebus_beacon'],
        inverter=config['pwrcell']['device_ids']['inverter'],
        battery=config['pwrcell']['device_ids']['battery'],
        pv_links=config['pwrcell']['device_ids']['pv_links'],
    )

    gpc = pwrcell.GeneracPwrCell(
        device_config, ipaddr=config['pwrcell']['host'], ipport=config['pwrcell']['port'], timeout=60,
        extra_model_defs=[os.path.join(tempdir, "sunspec-models")])
    try:
      mqtt_client.loop_start()
      gpc.init()

      pwrcell_ha = homeassistant.PwrCellHA(
          gpc, mqtt_client, testing=config.get('testing', False))
      pwrcell_ha.init()

      while True:
        start = time.time()
        gpc.read()
        pwrcell_ha.loop()
        sleep_time = max(0, config['poll_rate'] - (time.time() - start))
        logging.debug("Sleep for {}s".format(sleep_time))
        time.sleep(sleep_time)
    except KeyboardInterrupt as e:
      logging.info("Closing: %s", e)
    finally:
      gpc.close()
      mqtt_client.loop_stop()


if __name__ == '__main__':
  app.run(main)
