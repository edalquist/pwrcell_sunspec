import json
import logging
import paho.mqtt.client as mqtt
import pwrcell
import sunspec2.modbus.client as ss2_client


class PwrCellHA():
  def __init__(self, pwrcell: pwrcell.GeneracPwrCell, mqttc: mqtt.Client, testing: bool = False):
    self.__ha_topic = "homeassistant"
    if testing:
      self.__ha_topic = "TEST/{}".format(self.__ha_topic)

    self.__pwrcell = pwrcell
    self.__mqttc = mqttc

  def init(self):
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

    self.__define_sensor(
        self.__pwrcell.battery.battery[0].W,
        device_id='battery',
        sensor_id='watts')
    self.__define_sensor(
        self.__pwrcell.battery.battery[0].SoC,
        device_id='battery',
        sensor_id='state_of_charge')
    self.__define_number(
        self.__pwrcell.battery.battery[0].SoCMax,
        device_id='battery',
        sensor_id='state_of_charge_max')
    self.__define_number(
        self.__pwrcell.battery.battery[0].SoCMin,
        device_id='battery',
        sensor_id='state_of_charge_min')
    self.__define_number(
        self.__pwrcell.battery.battery[0].SoCRsvMax,
        device_id='battery',
        sensor_id='state_of_charge_reserve_max')
    self.__define_number(
        self.__pwrcell.battery.battery[0].SoCRsvMin,
        device_id='battery',
        sensor_id='state_of_charge_reserve_min')
    self.__define_sensor(
        self.__pwrcell.battery.battery_status[0].WhIn,
        device_id='battery',
        sensor_id='in_watt_hours')
    self.__define_sensor(
        self.__pwrcell.battery.battery_status[0].WhOut,
        device_id='battery',
        sensor_id='out_watt_hours')

    for pv_link_id, pv_link in self.__pwrcell.pv_links.items():
      device_id = 'pv_link_{}'.format(pv_link_id)
      self.__define_sensor(
          pv_link.string_combiner[0].DCW,
          device_id=device_id,
          sensor_id='watts',
          device_name_suffix=" {}".format(pv_link_id))
      self.__define_sensor(
          pv_link.string_combiner[0].DCWh,
          device_id=device_id,
          sensor_id='watt_hours',
          device_name_suffix=" {}".format(pv_link_id))

  def __point_to_ha(self, point: ss2_client.SunSpecModbusClientPoint):
    p_type = point.pdef['type']
    if p_type in ['enum16']:
      symbols = point.pdef.get('symbols')
      return next(x for x in symbols if x['value'] == point.cvalue)['name']

    return point.cvalue

  def __ha_to_point(self, point: ss2_client.SunSpecModbusClientPoint, payload):
    p_type = point.pdef['type']

    # For enum types look up the value for the symbol
    if p_type in ['enum16']:
      symbols = point.pdef['symbols']
      return next(x for x in symbols if x['name'] == payload)['value']

    return payload

  def __update_state(self, point: ss2_client.SunSpecModbusClientPoint, state_topic: str):
    p_value = self.__point_to_ha(point)
    logging.info("Publish {}: {}".format(state_topic, p_value))
    self.__mqttc.publish(state_topic, p_value)

  def __handle_command(self, point: ss2_client.SunSpecModbusClientPoint, command_topic: str, client, userdata, msg):
    try:
      payload = msg.payload.decode('utf-8')
      new_value = self.__ha_to_point(point, payload)
      logging.info("Changing {} from {} to {}".format(
          pwrcell.point_to_str(point), point.value, new_value))
      point.cvalue = new_value
      point.write()
      # Immediately re-read the value
      self.__pwrcell.read_point(point)
    except Exception:
      logging.exception("Failed to handle command %s on %s for %s",
                        msg.payload, command_topic, pwrcell.point_to_str(point))

  def __publish_discovery(self, topic, payload):
    logging.info("Publishing HA entity on: %s", topic)
    logging.debug(payload)
    self.__mqttc.publish(topic, payload)  # TODO, retain=True)

  def __define_sensor(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None, device_name_suffix: str = None):
    device = point.model.device
    device_name = device_name or device.common[0].Md.value
    if device_name_suffix is not None:
      device_name += device_name_suffix
    state_topic = "{}/sensor/{}/{}/state".format(
        self.__ha_topic, device_id, sensor_id)
    config_topic = "{}/sensor/{}/{}/config".format(
        self.__ha_topic, device_id, sensor_id)
    self.__publish_discovery(config_topic, json.dumps({
        "device": self.__create_device(device, device_name),
        "name": "{}: {}".format(device_name, point.pdef['label']),
        "unique_id": "{}_{}".format(device_id, sensor_id),
        "device_class": self.__device_class(point),
        "state_class": self.__state_class(point),
        "unit_of_measurement": self.__unit_of_measurement(point),
        "state_topic": state_topic,
        "expire_after": 14400
    }, indent=2, sort_keys=True))
    self.__pwrcell.watch_point(
        point, (lambda p: self.__update_state(p, state_topic)))

  def __define_number(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None, min: float = 1, max: float = 100):
    if point.pdef.get('access') != 'RW':
      raise ValueError(
          "Point must have 'access' set to 'RW' to be mutable: {}".format(point.pdef))

    device = point.model.device
    device_name = device_name or device.common[0].Md.value
    state_topic = "{}/number/{}/{}/state".format(
        self.__ha_topic, device_id, sensor_id)
    config_topic = "{}/number/{}/{}/config".format(
        self.__ha_topic, device_id, sensor_id)
    command_topic = "{}/number/{}/{}/command".format(
        self.__ha_topic, device_id, sensor_id)
    self.__publish_discovery(config_topic, json.dumps({
        "device": self.__create_device(device, device_name),
        "name": "{}: {}".format(device_name, point.pdef['label']),
        "unique_id": "{}_{}".format(device_id, sensor_id),
        "device_class": self.__device_class(point),
        "unit_of_measurement": self.__unit_of_measurement(point),
        "state_topic": state_topic,
        "command_topic": command_topic,
        "expire_after": 14400,
        "min": min,
        "max": max
    }, indent=2, sort_keys=True))
    self.__pwrcell.watch_point(
        point, (lambda p: self.__update_state(p, state_topic)))
    self.__mqttc.subscribe(command_topic)
    self.__mqttc.message_callback_add(
        command_topic, lambda client, userdata, msg: self.__handle_command(point, command_topic, client, userdata, msg))

  def __define_select(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None):
    if point.pdef.get('access') != 'RW':
      raise ValueError(
          "Point must have 'access' set to 'RW' to be mutable: {}".format(point.pdef))

    device = point.model.device
    device_name = device_name or device.common[0].Md.value
    config_topic = "{}/select/{}/{}/config".format(
        self.__ha_topic, device_id, sensor_id)
    state_topic = "{}/select/{}/{}/state".format(
        self.__ha_topic, device_id, sensor_id)
    command_topic = "{}/select/{}/{}/command".format(
        self.__ha_topic, device_id, sensor_id)
    self.__publish_discovery(config_topic, json.dumps({
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

  def __device_class(self, point: ss2_client.SunSpecModbusClientPoint):
    p_type = point.pdef.get('type')
    if p_type in ['acc16', 'acc32']:
      return 'total_increasing'
    elif p_type in ['int16', 'int32', 'uint16', 'uint32']:
      return 'measurement'
    else:
      logging.error("DC UNKNOWN Type(%s)\n\t%s", p_type, point.pdef)

  def __state_class(self, point: ss2_client.SunSpecModbusClientPoint):
    p_type = point.pdef.get('type')
    if p_type in ['int16', 'int32', 'uint16', 'uint32', 'acc16', 'acc32']:
      p_units = point.pdef.get('units')
      if p_units in ['W', 'Wh']:
        return 'energy'
      if p_units in ['%WHRtg']:
        return 'battery'
      else:
        logging.error("SC UNKNOWN Units(%s) for Type(%s)\n\t%s",
                      p_units, p_type, point.pdef)
    else:
      logging.error("SC UNKNOWN Type(%s)\n\t%s", p_type, point.pdef)

  def __unit_of_measurement(self, point: ss2_client.SunSpecModbusClientPoint):
    p_units = point.pdef.get('units')
    if p_units in ['%WHRtg']:
      return '%'
    else:
      return p_units

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
