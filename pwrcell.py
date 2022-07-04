from email.policy import default
from typing import overload
import concurrent.futures
import dataclasses
import datetime
import logging
import sunspec2.device as device
import sunspec2.modbus.client as ss2_client
import sunspec2.modbus.modbus as mb
import time
import traceback


@dataclasses.dataclass
class Config:
  rebus_beacon: int
  inverter: int
  pv_links: list[int]
  battery: int = -1


class GeneracPwrCell():
  def __init__(self, device_config: Config, ipaddr='127.0.0.1', ipport=502, timeout=None, extra_model_defs: list[str] = []):
    # Configure additional model def locations
    device.set_model_defs_path(extra_model_defs + device.get_model_defs_path())

    self.__devices = {}
    self.__ipaddr = ipaddr
    self.__ipport = ipport
    self.__iptimeout = timeout

    self.__rebus_beacon = self.__init_device(
        'rebus_beacon', device_config.rebus_beacon)
    self.__inverter = self.__init_device('inverter', device_config.inverter)

    if len(device_config.pv_links) == 0:
      raise ValueError("pv_links array must be set and not empty")
    self.__pv_links = {}
    for idx, pv_link_id in enumerate(device_config.pv_links):
      pv_link_name = 'pv_link_{}'.format(idx)
      self.__pv_links[pv_link_name] = self.__init_device(
          pv_link_name, pv_link_id)

    if device_config.battery > 0:
      self.__battery = self.__init_device('battery', device_config.battery)

    self.__executor = concurrent.futures.ThreadPoolExecutor(
        thread_name_prefix='ModBusPool', max_workers=(len(self.__devices) * 2))

  def __init_device(self, name: str, device_id: int):
    if name in self.__devices:
      raise ValueError("Device {} is already configured".format(name))
    if device_id is None or device_id <= 0:
      raise ValueError("{} id must be set to a positive int".format(name))

    device = ss2_client.SunSpecModbusClientDeviceTCP(
        slave_id=device_id, ipaddr=self.__ipaddr, ipport=self.__ipport, timeout=self.__iptimeout)
    device.name = name
    logging.info("Configured %s at %s:%s on id %s", name,
                 self.__ipaddr, self.__ipport, device_id)
    self.__devices[name] = device
    return device

  def __connect_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3, reconnect=False):
    if not reconnect and device.is_connected():
      return
    for t in range(tries):
      try:
        device.connect()
        logging.info("Connected %s", device.name)
        break
      except mb.ModbusClientException as e:
        logging.warning("Error connecting %s on try %s: %s", device.name, t, e)

  def __scan_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3):
    # Ensure device is connected before scanning
    self.__connect_device(device, tries=tries)
    for t in range(tries):
      try:
        # Don't read all model data (it is slow)
        device.scan(connect=False, full_model_read=False)
        device.common[0].read()
        logging.info("Scanned %s as %s %s - %s",
                     device.name,
                     device.common[0].Mn.get_value(),
                     device.common[0].Md.get_value(),
                     device.common[0].SN.get_value())
        break
      except Exception as e:
        logging.warning("Error scanning %s on try %s: %s", device.name, t, e)
        self.__connect_device(device, tries=tries, reconnect=True)

  def init(self):
    # Kick off scans of all devices
    futures_to_devices = {}
    for device in self.__devices.values():
      scan_future = self.__executor.submit(self.__scan_device, device)
      futures_to_devices[scan_future] = device

    # Wait for all the scans to complete
    for future in concurrent.futures.as_completed(futures_to_devices):
      device = futures_to_devices[future]
      try:
        future.result()
      except Exception as exc:
        # TODO fail hard here?
        logging.error("Failed to scan %s: %s", device.name, exc)

    # Configure the points to poll data for and bind them to properties on the GeneracPwrCell class
    self.__watched_points_by_device = {}
    self.__watch_points({
        self.__rebus_beacon.REbus_dir[0].SysMd: 'system_mode',
        self.__inverter.inverter[0].W: 'inverter_output_watts',
        self.__inverter.inverter[0].WH: 'inverter_output_watt_hours',
        self.__inverter.REbus_exp[0].Px1: 'grid_export_phase_a',
        self.__inverter.REbus_exp[0].Px2: 'grid_export_phase_b',
        self.__inverter.REbus_exp[0].Whx: 'grid_export_watt_hours',
        self.__inverter.REbus_exp[0].Whin: 'grid_import_watt_hours',
        self.__battery.battery[0].W: 'battery_watts',
        self.__battery.battery[0].SoC: 'battery_state_of_charge',
        self.__battery.battery[0].SoCMax: 'battery_state_of_charge_max',
        self.__battery.battery[0].SoCMin: 'battery_state_of_charge_min',
        self.__battery.battery[0].SoCRsvMax: 'battery_state_of_charge_reserve_max',
        self.__battery.battery[0].SoCRsvMin: 'battery_state_of_charge_reserve_min',
        self.__battery.battery_status[0].WhIn: 'battery_in_watt_hours',
        self.__battery.battery_status[0].WhOut: 'battery_out_watt_hours',
    })
    for pv_link in self.__pv_links.values():
      self.__watch_points({pv_link.string_combiner[0].DCW: '%s_watts' % pv_link.name,
                          pv_link.string_combiner[0].DCWh: '%s_watt_hours' % pv_link.name})

  def __watch_point(self, point: ss2_client.SunSpecModbusClientPoint, prop_name: str):
    device = point.model.device
    points = self.__watched_points_by_device.setdefault(device, set())
    points.add(point)
    setattr(GeneracPwrCell, prop_name, property(lambda self: point))
    # if point.pdef.get('access') == 'RW':
    #   setattr(GeneracPwrCell, prop_name, property(
    #       lambda self: self.__get_point_value(point),
    #       lambda self, value: self.__set_point_value(point, value)))
    # else:
    #   setattr(GeneracPwrCell, prop_name, property(
    #       lambda self: self.__get_point_value(point)))
    logging.debug("Bind %s.%s.%s to %s",
                  device.name, point.model.gname, point.pdef['name'], prop_name)

  def __watch_points(self, points: dict[ss2_client.SunSpecModbusClientPoint, str]):
    for point, prop_name in points.items():
      self.__watch_point(point, prop_name)

  # def __get_point_value(self, point: ss2_client.SunSpecModbusClientPoint):
  #   if point.pdef.get('type') == 'enum16' and 'symbols' in point.pdef:
  #     symbols = {}
  #     for symbol_dict in point.pdef['symbols']:
  #       symbols[int(symbol_dict['value'])] = symbol_dict['name']
  #     return symbols[point.value]
  #   else:
  #     return point.value

  # # TODO not sure I like this approach, it prevents use of "real" enums and the like
  # def __set_point_value(self, point: ss2_client.SunSpecModbusClientPoint, value):
  #   if point.pdef.get('type') == 'enum16' and 'symbols' in point.pdef:
  #     symbols = {}
  #     for symbol_dict in point.pdef['symbols']:
  #       symbols[symbol_dict['name']] = int(symbol_dict['value'])
  #     value = symbols[value]
  #   print("Write %s to %s" % (value, point.pdef['name']))
  #   # TODO this needs to be in a retry block
  #   # point.value = value
  #   # point.write()
  #   # point.read()

  @ property
  def system_mode(self):
    # TODO this is an enum
    return self.__rebus_beacon.REbus_dir[0].SysMd.value

  def __read_points(self, device: ss2_client.SunSpecModbusClientDeviceTCP, points: set[ss2_client.SunSpecModbusClientPoint], tries=3):
    self.__connect_device(device, tries=tries)
    for point in points:
      for t in range(tries):
        try:
          point.read()
          logging.debug("Read %s on %s: %s",
                        point.pdef['name'], device.name, point.value)
          break
        except Exception as e:
          logging.warning("Error reading %s on try %s: %s", device.name, t, e)
          self.__connect_device(device, tries=tries, reconnect=True)

  def __do_read_points(self, device: ss2_client.SunSpecModbusClientDeviceTCP, points: set[ss2_client.SunSpecModbusClientPoint], tries=3):
    return self.__executor.submit(self.__read_points, device, points, tries=tries)

  def read(self):
    start = time.time()
    logging.info("POLLING POINTS")
    futures_to_devices = {}

    # Kick off reads for all watched devices/models
    for device, points in self.__watched_points_by_device.items():
      futures_to_devices[self.__do_read_points(device, points)] = device

    for future in concurrent.futures.as_completed(futures_to_devices):
      device = futures_to_devices[future]
      try:
        future.result()
      except Exception as exc:
        logging.error("Failed to read %s: %s", device.name, exc)

    logging.info("POLLED POINTS IN %fms", (time.time() - start) * 1000)

  def close(self):
    logging.debug("Closing all devices")
    for name, device in self.__devices.items():
      device.close()
      logging.debug('Closed %s', name)
