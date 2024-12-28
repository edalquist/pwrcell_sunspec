import logging
from typing import Any

import paho.mqtt.client as mqtt
from google.protobuf import text_format
from google.protobuf.unknown_fields import UnknownFieldSet
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from .protos import energy_record_set_pb2
from .tunnel import TunnelConfig


class MqttClient():
  def __init__(self, tunnel_config: TunnelConfig):
    self.__tunnel_ip = tunnel_config.host
    self.__tunnel_port = tunnel_config.mqtt_port

  def __enter__(self):
    self.__mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    self.__mqttc.on_connect = self.__mqtt_on_connect
    self.__mqttc.on_message = self.__mqtt_on_message
    self.__mqttc.on_disconnect = self.__mqtt_disconnect

    self.__mqttc.loop_start()
    self.__mqttc.connect(self.__tunnel_ip, self.__tunnel_port)

    return self

  def __exit__(self, *exc):
    self.__mqttc.loop_stop()
    self.__mqttc.disconnect()
    return False

  def __mqtt_on_connect(self, client: mqtt.Client, userdata: Any, flags: mqtt.ConnectFlags, reason_code: ReasonCode, properties: Properties):
      logging.info("MQTT Connected with result code %s", reason_code)
      # Subscribe to ALL topics
      client.subscribe("#")

  def __mqtt_disconnect(self, client: mqtt.Client, userdata: Any, flags: mqtt.DisconnectFlags, reason_code: ReasonCode, properties: Properties):
      logging.info("MQTT Disconnected with result code %s", reason_code)
      # Subscribe to ALL topics
      client.subscribe("#")

  # The callback for when a PUBLISH message is received from the server.
  def __mqtt_on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
      logging.debug("mqtt: %s", msg.topic)

      if msg.topic.endswith("/energy_recordset_live"):
        erl = energy_record_set_pb2.EnergyRecordSet()
        erl.ParseFromString(msg.payload)

        unknown_field_set = UnknownFieldSet(erl)
        if unknown_field_set:
           logging.warning("Found unknown fields: %s", unknown_field_set)

        text = text_format.MessageToString(erl, print_unknown_fields=True)
        logging.info("%s\n%s", msg.topic, text)
      else:
         logging.warning("Unknown Topic: %s", msg.topic)
