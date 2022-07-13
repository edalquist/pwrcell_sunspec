import json
import logging
import paho.mqtt.client as mqtt
import pwrcell
import sunspec2.modbus.client as ss2_client


class PwrCellHA():
  def __init__(self, pwrcell: pwrcell.GeneracPwrCell, mqttc: mqtt.Client):
    self.__ha_topic = "TEST/homeassistant"
    self.__pwrcell = pwrcell
    self.__mqttc = mqttc

  def init(self):
    # if self.__battery:
    #   self.__watch_points({
    #       self.__battery.battery[0].W: 'battery_watts',
    #       self.__battery.battery[0].SoC: 'battery_state_of_charge',
    #       self.__battery.battery[0].SoCMax: 'battery_state_of_charge_max',
    #       self.__battery.battery[0].SoCMin: 'battery_state_of_charge_min',
    #       self.__battery.battery[0].SoCRsvMax: 'battery_state_of_charge_reserve_max',
    #       self.__battery.battery[0].SoCRsvMin: 'battery_state_of_charge_reserve_min',
    #       self.__battery.battery_status[0].WhIn: 'battery_in_watt_hours',
    #       self.__battery.battery_status[0].WhOut: 'battery_out_watt_hours',
    #   })
    # for pv_link in self.__pv_links.values():
    #   self.__watch_points({pv_link.string_combiner[0].DCW: '%s_watts' % pv_link.name,
    #                       pv_link.string_combiner[0].DCWh: '%s_watt_hours' % pv_link.name})

    self.__define_select(
        self.__pwrcell.rebus_beacon.REbus_dir[0].SysMd,
        device_id='rebus_beacon',
        sensor_id='system_mode')
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Whx,
        device_id='pwrcell_inverter',
        sensor_id='grid_export_watt_hours')
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Whin,
        device_id='pwrcell_inverter',
        sensor_id='grid_import_watt_hours')
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Px1,
        device_id='pwrcell_inverter',
        sensor_id='grid_export_phase_a')
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Px2,
        device_id='pwrcell_inverter',
        sensor_id='grid_export_phase_b')
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Whx,
        device_id='pwrcell_inverter',
        sensor_id='grid_export_watt_hours')
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Whin,
        device_id='pwrcell_inverter',
        sensor_id='grid_import_watt_hours')

    # Grid Consumption - pwrcell/grid/import_watt_hours
    # Grid Return - pwrcell/grid/export_watt_hours
    # Solar Production - pwrcell/pv_link/output_watt_hours
    # Battery In - pwrcell/battery/input_watt_hours
    # Battery Out - pwrcell/battery/output_watt_hours
  def __update_state(self, point: ss2_client.SunSpecModbusClientPoint, state_topic: str):
    print("UPDATE:\t{}: {}".format(state_topic, point.value))

  def __handle_command(self, point: ss2_client.SunSpecModbusClientPoint, command_topic: str, client, userdata, msg):
    print("COMMAND:\t{}: {} -> {}".format(command_topic, point.value, msg))

  def __define_sensor(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None):
    device = point.model.device
    device_name = device_name or device.common[0].Md.value
    state_topic = "{}/sensor/{}/{}/state".format(
        self.__ha_topic, device_id, sensor_id)
    config_topic = "{}/sensor/{}/{}/config".format(
        self.__ha_topic, device_id, sensor_id)
    print(config_topic)
    print(json.dumps({
          "device": self.__create_device(device, device_name),
          "name": "{}: {}".format(device_name, point.pdef['label']),
          "unique_id": "{}_{}".format(device_id, sensor_id),
          "device_class": self.__device_class(point),
          "state_class": self.__state_class(point),
          "unit_of_measurement": point.pdef['units'],
          "state_topic": state_topic,
          "expire_after": 14400
          }, indent=2, sort_keys=True))
    self.__pwrcell.watch_point(
        point, (lambda p: self.__update_state(p, state_topic)))

  def __device_class(self, point: ss2_client.SunSpecModbusClientPoint):
    p_type = point.pdef.get('type')
    if p_type in ['acc16', 'acc32']:
      return 'total_increasing'
    elif p_type in ['int16', 'int32`']:
      return 'measurement'
    else:
      logging.error("DC UNKNOWN Type(%s)\n\t%s", p_type, point.pdef)

  def __state_class(self, point: ss2_client.SunSpecModbusClientPoint):
    p_type = point.pdef.get('type')
    if p_type in ['int16', 'int32', 'acc16', 'acc32']:
      p_units = point.pdef.get('units')
      if p_units in ['W', 'Wh']:
        return 'energy'
      else:
        logging.error("UNKNOWN Units(%s) for Type(%s)\n\t%s",
                      p_units, p_type, point.pdef)
    else:
      logging.error("SC UNKNOWN Type(%s)\n\t%s", p_type, point.pdef)

  def __define_select(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None):
    device = point.model.device
    device_name = device_name or device.common[0].Md.value
    config_topic = "{}/select/{}/{}/config".format(
        self.__ha_topic, device_id, sensor_id)
    state_topic = "{}/select/{}/{}/state".format(
        self.__ha_topic, device_id, sensor_id)
    command_topic = "{}/select/{}/{}/command".format(
        self.__ha_topic, device_id, sensor_id)
    print(config_topic)
    print(json.dumps({
          "device": self.__create_device(device, device_name),
          "name": "{}: {}".format(device_name, point.pdef['label']),
          "unique_id": "{}_{}".format(device_id, sensor_id),
          "options": self.__select_options(point),
          "state_topic": state_topic,
          "command_topic": command_topic,
          "entity_category": 'config',
          "expire_after": 14400
          }, indent=2, sort_keys=True))
    self.__pwrcell.watch_point(
        point, (lambda p: self.__update_state(p, state_topic)))
    # Subscribe to command_topic & register callback
    self.__mqttc.subscribe(command_topic)
    self.__mqttc.message_callback_add(
        command_topic, lambda client, userdata, msg: self.__handle_command(point, command_topic, client, userdata, msg))

  def __select_options(self, point: ss2_client.SunSpecModbusClientPoint):
    symbols = point.pdef.get('symbols')
    symbols = sorted(symbols, key=lambda s: s['value'])
    return list(map(lambda s: s['name'], symbols))

  def __create_device(self, device: ss2_client.SunSpecModbusClientDevice, device_name: str):
    return {
        "name": device_name,
        "model": device.common[0].Md.value,
        "manufacturer": device.common[0].Mn.value,
        "sw_version": device.common[0].Vr.value,
        "identifiers": [
            device.common[0].SN.value
        ]
    }

  def loop(self):
    pass
