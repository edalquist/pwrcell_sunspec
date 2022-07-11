import pwrcell
import paho.mqtt.client as mqtt
import json
import sunspec2.modbus.client as ss2_client


class PwrCellHA():
  def __init__(self, pwrcell: pwrcell.GeneracPwrCell, mqttc: mqtt.Client):
    self.__ha_topic = "TEST/homeassistant"
    self.__pwrcell = pwrcell
    self.__mqttc = mqttc

  def init(self):
    self.__generate_discovery(
        self.__pwrcell.grid_export_watt_hours,
        state_topic='pwrcell/grid/export_watt_hours',
        device_id='pwrcell_inverter',
        sensor_id='grid_export_watt_hours')
    self.__generate_discovery(
        self.__pwrcell.grid_import_watt_hours,
        state_topic='pwrcell/grid/import_watt_hours',
        device_id='pwrcell_inverter',
        sensor_id='grid_import_watt_hours')
    # grid_export_watt_hours
    # self.__mqttc.publish("{}/sensor/pwrcell_inverter/grid_import_watt_hours/config".format(self.__ha_topic),
    #                      )

    # Grid Consumption - pwrcell/grid/import_watt_hours
    # Grid Return - pwrcell/grid/export_watt_hours
    # Solar Production - pwrcell/pv_link/output_watt_hours
    # Battery In - pwrcell/battery/input_watt_hours
    # Battery Out - pwrcell/battery/output_watt_hours

  def __generate_discovery(self, point: ss2_client.SunSpecModbusClientPoint, state_topic: str, device_id: str, sensor_id: str, device_name: str = None):
    device = point.model.device
    print(point.pdef)
    device_name = device_name or device.common[0].Md.value
    print("{}/sensor/{}/{}/config".format(self.__ha_topic, device_id, sensor_id))
    print(json.dumps({
          "device": self.__create_device(device, device_name),
          "name": "{}: {}".format(device_name, point.pdef['label']),
          "unique_id": "{}_{}".format(device_id, sensor_id),
          "device_class": "energy",  # How to set this?
          "state_class": "total_increasing",  # auto-set based on type == acc32
          "unit_of_measurement": point.pdef['units'],
          "state_topic": state_topic,
          "expire_after": 14400
          }, indent=2))

  def __create_device(self, device: ss2_client.SunSpecModbusClientDevice, device_name: str):
    return {
        "name": device_name,
        "model": device.common[0].Md.value,
        "manufacturer": device.common[0].Mn.value,
        "identifiers": [
            device.common[0].SN.value
        ]
    }

  def loop(self):
    pass
