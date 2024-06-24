import json
import logging
import paho.mqtt.client as mqtt
import pwrcell
import sunspec2.mdef as mdef
import sunspec2.modbus.client as ss2_client
import time


class TimeMovingAvg():
  def __init__(self, max_age: int = 60):
    self.__max_age = max_age
    self.__points = []

  def accumulate(self, value: float):
    now = time.time()
    self.__points.append({'ts': now, 'v': value})
    average = None
    slice_idx = 0
    for idx, p in enumerate(self.__points):
      if (now - p['ts']) > self.__max_age:
        slice_idx = idx + 1
      elif average is None:
        average = p['v']
      else:
        average += p['v']
    self.__points = self.__points[slice_idx:]
    return average / len(self.__points)


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
        self.__pwrcell.inverter.REbus_exp[0].Px1,
        device_id='pwrcell_inverter',
        sensor_id='grid_watts_phase_a',
        round_digits=1,
        moving_average=True)
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_exp[0].Px2,
        device_id='pwrcell_inverter',
        sensor_id='grid_watts_phase_b',
        round_digits=1,
        moving_average=True)
    self.__define_sensor(
        self.__pwrcell.inverter.inverter_status[0].CTPow,
        device_id='pwrcell_inverter',
        sensor_id='grid_watts',
        round_digits=1,
        moving_average=True,
        negate=True)
    self.__define_sensor(
        self.__pwrcell.inverter.inverter_status[0].WhOut,
        device_id='pwrcell_inverter',
        sensor_id='grid_export_watt_hours',
        state_class='total_increasing')
    self.__define_sensor(
        self.__pwrcell.inverter.inverter_status[0].WhIn,
        device_id='pwrcell_inverter',
        sensor_id='grid_import_watt_hours',
        state_class='total_increasing')
    self.__define_sensor(
        self.__pwrcell.inverter.inverter[0].W,
        device_id='pwrcell_inverter',
        sensor_id='inverter_watts',
        round_digits=1,
        moving_average=True)
    self.__define_sensor(
        self.__pwrcell.inverter.inverter[0].PhVphA,
        device_id='pwrcell_inverter',
        sensor_id='inverter_phase1_volts',
        round_digits=1,
        moving_average=True)
    self.__define_sensor(
        self.__pwrcell.inverter.inverter[0].PhVphB,
        device_id='pwrcell_inverter',
        sensor_id='inverter_phase2_volts',
        round_digits=1,
        moving_average=True)    
    self.__define_sensor(
        self.__pwrcell.inverter.REbus_status[0].St,
        device_id='pwrcell_inverter',
        sensor_id='inverter_state')

    if hasattr(self.__pwrcell,'battery'):
        self.__define_sensor(
            self.__pwrcell.battery.battery[0].W,
            device_id='battery',
            sensor_id='watts',
            round_digits=1,
            moving_average=True,
            negate=True)
        self.__define_sensor(
            self.__pwrcell.battery.battery[0].SoC,
            device_id='battery',
            sensor_id='state_of_charge',
            round_digits=1)
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
            sensor_id='in_watt_hours',
            state_class='total_increasing')
        self.__define_sensor(
            self.__pwrcell.battery.battery_status[0].WhOut,
            device_id='battery',
            sensor_id='out_watt_hours',
            state_class='total_increasing')
        self.__define_sensor(
            self.__pwrcell.battery.REbus_status[0].St,
            device_id='battery',
            sensor_id='battery_state')

    for pv_link_id, pv_link in self.__pwrcell.pv_links.items():
      device_id = 'pv_link_{}'.format(pv_link_id)
      self.__define_sensor(
          pv_link.string_combiner[0].DCW,
          device_id=device_id,
          sensor_id='watts',
          device_name_suffix=" {}".format(pv_link_id),
          round_digits=1,
          moving_average=True)
      self.__define_sensor(
          pv_link.string_combiner[0].DCWh,
          device_id=device_id,
          sensor_id='watt_hours',
          device_name_suffix=" {}".format(pv_link_id))
      self.__define_sensor(
          pv_link.REbus_status[0].St,
          device_id=device_id,
          sensor_id='pvlink_state')

  def __point_to_ha(self, point: ss2_client.SunSpecModbusClientPoint):
    # For enum types find the name for the value
    if pwrcell.is_enum(point):
      symbols = point.pdef[mdef.SYMBOLS]
      return next(symbol for symbol in symbols if symbol[mdef.VALUE] == point.cvalue)[mdef.NAME]

    return point.cvalue

  def __ha_to_point(self, point: ss2_client.SunSpecModbusClientPoint, payload):
    # For enum types look up the value for the name, throws if no match
    if pwrcell.is_enum(point):
      symbols = point.pdef[mdef.SYMBOLS]
      return next(symbol for symbol in symbols if symbol[mdef.NAME] == payload)[mdef.VALUE]

    return payload

  def __update_state(self, point: ss2_client.SunSpecModbusClientPoint, state_topic: str, round_digits: int = -1,
                     tma: TimeMovingAvg = None, negate: bool = False):
    p_value = self.__point_to_ha(point)
    p_value = tma.accumulate(p_value) if tma is not None else p_value
    p_value = round(p_value, round_digits) if round_digits >= 0 else p_value
    p_value = -1 * p_value if negate else p_value
    logging.info("Publish {}: {}".format(state_topic, p_value))
    self.__mqttc.publish(state_topic, p_value)

  def __handle_command(self, point: ss2_client.SunSpecModbusClientPoint, command_topic: str, client, userdata, msg):
    try:
      payload = msg.payload.decode('utf-8')
      new_value = self.__ha_to_point(point, payload)
      logging.info("Changing {} from {} to {}".format(
          pwrcell.point_id(point), point.cvalue, new_value))
      point.cvalue = new_value
      point.write()
      # Immediately re-read the value after writing, will update the state topic
      self.__pwrcell.read_point(point)
    except Exception:
      logging.exception("Failed to handle command %s on %s for %s",
                        msg.payload, command_topic, pwrcell.point_id(point))

  def __define_sensor(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None,
                      device_name_suffix: str = None, state_class: str = None, round_digits: int = -1, negate: bool = False,
                      moving_average: bool = False):
    print(point.pdef)
    sensor_config = {
        "device_class": self.__device_class(point),
        "state_class": self.__state_class(point) if state_class is None else state_class,
        "unit_of_measurement": self.__unit_of_measurement(point),
    }
    self.__publish_entity('sensor', sensor_config, point, device_id, sensor_id, device_name, device_name_suffix,
                          round_digits=round_digits, moving_average=moving_average, negate=negate)

  def __define_number(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None, device_name_suffix: str = None, min: float = 1, max: float = 100):
    sensor_config = {
        "unit_of_measurement": self.__unit_of_measurement(point),
        "min": min,
        "max": max,
    }
    self.__publish_entity('number', sensor_config, point, device_id,
                          sensor_id, device_name, device_name_suffix)

  def __define_select(self, point: ss2_client.SunSpecModbusClientPoint, device_id: str, sensor_id: str, device_name: str = None, device_name_suffix: str = None):
    sensor_config = {
        "options": self.__select_options(point),
        "entity_category": 'config',
    }
    self.__publish_entity('select', sensor_config, point, device_id,
                          sensor_id, device_name, device_name_suffix)

  def __publish_entity(self, entity_type: str, entity_config: dict[str, str], point: ss2_client.SunSpecModbusClientPoint,
                       device_id: str, sensor_id: str, device_name: str = None, device_name_suffix: str = None,
                       round_digits: int = -1, moving_average: bool = False, negate: bool = False):
    device = point.model.device
    device_name_select = device_name or device.common[0].Md.value
    device_id = device.common[0].SN.value
    device_name = "{}:{}".format(device_name_select, device_id)
    if device_name_suffix is not None:
      device_name += device_name_suffix

    config_topic = "{}/{}/{}/{}/config".format(
        self.__ha_topic, entity_type, device_id, sensor_id)
    state_topic = "{}/{}/{}/{}/state".format(
        self.__ha_topic, entity_type, device_id, sensor_id)
    entity_config = {k: v for k, v in entity_config.items() if v is not None} | {
        "device": self.__create_device(device, device_name),
        # TODO what is label is missing?
        "name": "{}: {}".format(device_name, point.pdef[mdef.LABEL]),
        "unique_id": "{}_{}".format(device_id, sensor_id),
        "state_topic": state_topic,
        "expires_after": 14400,
    }

    if point.pdef.get(mdef.ACCESS) == mdef.ACCESS_RW:
      command_topic = "{}/{}/{}/{}/command".format(
          self.__ha_topic, entity_type, device_id, sensor_id)
      entity_config['command_topic'] = command_topic
      # Subscribe to command topic and register callback
      self.__mqttc.subscribe(command_topic)
      self.__mqttc.message_callback_add(
          command_topic, lambda client, userdata, msg: self.__handle_command(point, command_topic, client, userdata, msg))

    # Register watch/callback with pwrcell for point
    tma = TimeMovingAvg() if moving_average else None
    self.__pwrcell.watch_point(
        point, (lambda p: self.__update_state(p, state_topic, round_digits=round_digits, tma=tma, negate=negate)))

    # Publish Discovery
    logging.info("Binding %s to %s %s", config_topic,
                 pwrcell.point_id(point), pwrcell.point_sf_info(point))
    self.__mqttc.publish(config_topic, json.dumps(
        entity_config, indent=2, sort_keys=True), retain=True)

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

  def __state_class(self, point: ss2_client.SunSpecModbusClientPoint):
    if pwrcell.is_acc(point):
      return 'total_increasing'
    elif pwrcell.is_int(point) or pwrcell.is_uint(point):
      return 'measurement'
    elif pwrcell.is_enum(point):
      return None
    else:
      raise ValueError("DC UNKNOWN Type(%s)\n\t%s" %
                       (point.pdef[mdef.TYPE], point.pdef))

  def __device_class(self, point: ss2_client.SunSpecModbusClientPoint):
    if pwrcell.is_enum(point):
        return None
    if pwrcell.is_int(point) or pwrcell.is_uint(point) or pwrcell.is_acc(point):
      p_units = point.pdef.get(mdef.UNITS)
      if p_units in ['W']:
        return 'power'
      if p_units in ['V']:
        return 'voltage'      
      if p_units in ['Wh']:
        return 'energy'
      if p_units in ['%WHRtg']:
        return 'battery'
      else:
        raise ValueError("SC UNKNOWN Units(%s) for Type(%s)\n\t%s" %
                         (p_units, point.pdef[mdef.TYPE], point.pdef))
    else:
      raise ValueError("SC UNKNOWN Type(%s)\n\t%s" %
                       (point.pdef[mdef.TYPE], point.pdef))

  def __unit_of_measurement(self, point: ss2_client.SunSpecModbusClientPoint):
    p_units = point.pdef.get(mdef.UNITS)
    if p_units in ['%WHRtg']:
      return '%'
    else:
      return p_units

  def __select_options(self, point: ss2_client.SunSpecModbusClientPoint):
    symbols = point.pdef.get(mdef.SYMBOLS)
    symbols = sorted(symbols, key=lambda s: s[mdef.VALUE])
    return list(map(lambda symbol: symbol[mdef.NAME], symbols))

  def loop(self):
    """
    No-impl for now, may be used in future
    """
    pass
