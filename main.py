import json
import logging
import os
import paho.mqtt.client as mqtt
import pwrcell
import homeassistant
import sys
import tempfile
import time
import zipfile
import sunspec2.modbus.client as ss2_client


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


def main():
  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  logging.basicConfig(format=FORMAT, level=logging.INFO)

  config = {}
  with open(os.path.join(sys.path[0], "config.json")) as config_file:
    config = json.load(config_file)

  mqtt_client = mqtt.Client(client_id='pwrcell')
  mqtt_client.enable_logger()
  mqtt_client.on_connect = on_connect
  mqtt_client.on_message = on_message

  mqtt_client.username_pw_set(
      config['mqtt']['username'], config['mqtt']['password'])
  # mqtt_client.connect_async(config['mqtt']['host'], config['mqtt']['port'], 60)

  with tempfile.TemporaryDirectory() as tempdir:
    logging.debug("Extracting sunspec models to %s", tempdir)
    zf = zipfile.ZipFile(os.path.join(sys.path[0], "sunspec-models.zip"))
    zf.extractall(tempdir)

    device_config = pwrcell.Config(
        rebus_beacon=1,
        inverter=8,
        battery=9,
        # pv_links=[3, 4, 5, 6, 7],
        pv_links=[3, 4],
    )
    gpc = pwrcell.GeneracPwrCell(
        device_config, ipaddr=config['pwrcell']['host'], ipport=config['pwrcell']['port'], timeout=60, extra_model_defs=[os.path.join(tempdir, "sunspec-models")])
    try:
      # mqtt_client.loop_start()
      gpc.init()

      pwrcell_ha = homeassistant.PwrCellHA(gpc, mqtt_client)
      pwrcell_ha.init()

      # while True:
      #   start = time.time()
      #   gpc.read()
      #   pwrcell_ha.loop()
      #   time.sleep(max(0, 3 - (time.time() - start)))
    except KeyboardInterrupt as e:
      logging.info("Closing: %s", e)
    finally:
      gpc.close()
      mqtt_client.loop_stop()


if __name__ == '__main__':
  sys.exit(main())

# DEVICES = {
#     'REbus Beacon': [1, 10],
#     'ICM': [2],
#     'PV Link 000100034AC7': [3, 30],
#     'PV Link 000100034E68': [4, 31],
#     'PV Link 000100034FAC': [5, 32],
#     'PV Link 0001000361C7': [6, 33],
#     'PV Link 0001000361F4': [7, 34],
#     'PWRcell X7602 Inverter': [8, 70],
#     'PWRcell Battery': [9, 80]
# }
