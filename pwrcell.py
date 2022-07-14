from collections.abc import Callable
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


def point_to_str(point: ss2_client.SunSpecModbusClientPoint):
  device = point.model.device
  return "{}.{}.{}".format(device.name, point.model.gname, point.pdef['name'])


class GeneracPwrCell():
  def __init__(self, device_config: Config, ipaddr='127.0.0.1', ipport=502, timeout=None, extra_model_defs: list[str] = []):
    # Configure additional model def locations
    device.set_model_defs_path(extra_model_defs + device.get_model_defs_path())

    self.__watched_points_by_device = {}
    self.__devices = {}
    self.__ipaddr = ipaddr
    self.__ipport = ipport
    self.__iptimeout = timeout

    self.rebus_beacon = self.__init_device(
        'rebus_beacon', device_config.rebus_beacon)
    self.inverter = self.__init_device('inverter', device_config.inverter)

    if len(device_config.pv_links) == 0:
      raise ValueError("pv_links array must be set and not empty")
    self.pv_links = {}
    for pv_link_id in device_config.pv_links:
      pv_link_name = 'pv_link_{}'.format(pv_link_id)
      self.pv_links[pv_link_id] = self.__init_device(
          pv_link_name, pv_link_id)

    if device_config.battery > 0:
      self.battery = self.__init_device('battery', device_config.battery)

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

  def watch_point(self, point: ss2_client.SunSpecModbusClientPoint, callback: Callable[[ss2_client.SunSpecModbusClientPoint], None]):
    device = point.model.device
    points = self.__watched_points_by_device.setdefault(device, dict())
    points[point] = callback
    logging.debug("Bind %s to %s", point_to_str(point), callback)

  def watch_points(self, points: dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint], None]]):
    for point, callback in points.items():
      self.watch_point(point, callback)

  def __read_points(self, device: ss2_client.SunSpecModbusClientDeviceTCP, points: dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint]]], tries=3):
    self.__connect_device(device, tries=tries)
    for point, callback in points.items():
      for t in range(tries):
        try:
          point.read()
          logging.debug("Read %s", point_to_str(point))
          break
        except Exception as e:
          logging.warning("Error reading %s on try %s: %s", device.name, t, e)
          self.__connect_device(device, tries=tries, reconnect=True)
      # Execute read callback
      callback(point)

  def __do_read_points(self, device: ss2_client.SunSpecModbusClientDeviceTCP, points: dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint]]], tries=3):
    return self.__executor.submit(self.__read_points, device, points, tries=tries)

  def read(self):
    self.__read(self.__watched_points_by_device)

  def read_point(self, point: ss2_client.SunSpecModbusClientPoint):
    device = point.model.device
    points = self.__watched_points_by_device[device]
    callback = points[point]
    self.__read({device: {point: callback}})

  def __read(self, points: dict[ss2_client.SunSpecModbusClientDeviceTCP, dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint]]]]):
    start = time.time()
    logging.debug("POLLING POINTS")
    futures_to_devices = {}

    # Kick off reads for all watched devices/models
    for device, points in points.items():
      futures_to_devices[self.__do_read_points(device, points)] = device

    for future in concurrent.futures.as_completed(futures_to_devices):
      device = futures_to_devices[future]
      try:
        future.result()
      except Exception as exc:
        logging.error("Failed to read %s: %s", device.name, exc)

    logging.debug("POLLED POINTS IN %fms", (time.time() - start) * 1000)

  def close(self):
    logging.info("Closing all devices")
    for name, device in self.__devices.items():
      device.close()
      logging.debug('Closed %s', name)
