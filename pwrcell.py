import concurrent.futures
import dataclasses
import datetime
import logging
import time
import traceback
from collections.abc import Callable
from email.policy import default
from typing import overload

import sunspec2.device as device
import sunspec2.mdef as mdef
import sunspec2.modbus.client as ss2_client
import sunspec2.modbus.modbus as mb
from config import PwrcellDeviceIds


# def point_id(point: ss2_client.SunSpecModbusClientPoint):
#   device = point.model.device
#   return "{}.{}.{}".format(device.name, point.model.gname, point.pdef[mdef.NAME])


# def point_sf_info(point: ss2_client.SunSpecModbusClientPoint):
#   if point.sf is not None:
#     sf_point = point.model.points[point.sf]
#     return "scale factor {} ({})".format(sf_point.cvalue, point_id(sf_point))
#   if point.sf_value is not None:
#     return "scale factor {}".format(point.sf_value)
#   return ""


# def is_enum(point: ss2_client.SunSpecModbusClientPoint):
#   p_type = point.pdef[mdef.TYPE]
#   return p_type in [mdef.TYPE_ENUM16, mdef.TYPE_ENUM32]


# def is_acc(point: ss2_client.SunSpecModbusClientPoint):
#   p_type = point.pdef[mdef.TYPE]
#   return p_type in [mdef.TYPE_ACC16, mdef.TYPE_ACC32, mdef.TYPE_ACC64]


# def is_int(point: ss2_client.SunSpecModbusClientPoint):
#   p_type = point.pdef[mdef.TYPE]
#   return p_type in [mdef.TYPE_INT16, mdef.TYPE_INT32, mdef.TYPE_INT64]


# def is_uint(point: ss2_client.SunSpecModbusClientPoint):
#   p_type = point.pdef[mdef.TYPE]
#   return p_type in [mdef.TYPE_UINT16, mdef.TYPE_UINT32, mdef.TYPE_UINT64]


class GeneracPwrCell():
  def __init__(self, device_config: PwrcellDeviceIds, ipaddr='127.0.0.1', ipport=502, timeout=None, extra_model_defs: list[str] = []):
    # Configure additional model def locations
    device.set_model_defs_path(extra_model_defs + device.get_model_defs_path())
    logging.info("Model Defs: %s", str(device.get_model_defs_path()))

    # self.__watched_points_by_device = {}
    # self.__devices = {}
    # self.__ipaddr = ipaddr
    # self.__ipport = ipport
    # self.__iptimeout = timeout

    # self.rebus_beacon = self.__init_device(
    #     'rebus_beacon', device_config.rebus_beacon)
    # self.inverter = self.__init_device('inverter', device_config.inverter)

    # if len(device_config.pv_links) == 0:
    #   raise ValueError("pv_links array must be set and not empty")
    # self.pv_links = {}
    # for pv_link_id in device_config.pv_links:
    #   pv_link_name = 'pv_link_{}'.format(pv_link_id)
    #   self.pv_links[pv_link_id] = self.__init_device(
    #       pv_link_name, pv_link_id)

    # if device_config.battery > 0:
    #   self.battery = self.__init_device('battery', device_config.battery)

    # self.__executor = concurrent.futures.ThreadPoolExecutor(
    #     thread_name_prefix='ModBusPool', max_workers=(len(self.__devices) * 2))

  # def __init_device(self, name: str, device_id: int):
  #   if name in self.__devices:
  #     raise ValueError("Device {} is already configured".format(name))
  #   if device_id is None or device_id <= 0:
  #     raise ValueError("{} id must be set to a positive int".format(name))

  #   device = ss2_client.SunSpecModbusClientDeviceTCP(
  #       slave_id=device_id, ipaddr=self.__ipaddr, ipport=self.__ipport, timeout=self.__iptimeout)
  #   device.name = name
  #   logging.info("Configured %s at %s:%s on id %s", name,
  #                self.__ipaddr, self.__ipport, device_id)
  #   self.__devices[name] = device
  #   return device

  # def __connect_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3, reconnect=False):
  #   if not reconnect and device.is_connected():
  #     return
  #   for t in range(tries):
  #     try:
  #       device.connect()
  #       logging.info("Connected %s", device.name)
  #       break
  #     except mb.ModbusClientException as e:
  #       logging.warning("Error connecting %s on try %s: %s", device.name, t, e)

  # def __scan_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3):
  #   # Ensure device is connected before scanning
  #   self.__connect_device(device, tries=tries)
  #   for t in range(tries):
  #     try:
  #       # Don't read all model data (it is slow)
  #       device.scan(connect=False, full_model_read=False)
  #       device.common[0].read()
  #       logging.info("Scanned %s as %s %s - %s",
  #                    device.name,
  #                    device.common[0].Mn.get_value(),
  #                    device.common[0].Md.get_value(),
  #                    device.common[0].SN.get_value())
  #       self.__fix_device(device)
  #       break
  #     except Exception as e:
  #       logging.warning("Error scanning %s on try %s: %s", device.name, t, e)
  #       self.__connect_device(device, tries=tries, reconnect=True)

  # def __fix_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP):
  #   """
  #   Apply various overrides/fixes to devices after they have been loaded
  #   """
  #   for string_combiner in device.models.get(404, []):
  #     # DCW has a scale factor point of DCW_SF but that is set to zero in the system. Clear the sf point
  #     # reference and manually set the sf_value to -1
  #     if device.common[0].Vr.value == "634_13700":
  #       string_combiner.DCW.sf = None
  #       string_combiner.DCW.sf_value = None
  #     else:
  #       logging.info("Found older pvlink firmware, adjusting scale factor.")
  #       string_combiner.DCW.sf = None
  #       string_combiner.DCW.sf_value = -1

  def init(self):
    logging.info("init")
    # Kick off scans of all devices
    futures_to_devices = {}
  #   for device in self.__devices.values():
  #     scan_future = self.__executor.submit(self.__scan_device, device)
  #     futures_to_devices[scan_future] = device

  #   # Wait for all the scans to complete
  #   for future in concurrent.futures.as_completed(futures_to_devices):
  #     device = futures_to_devices[future]
  #     try:
  #       future.result()
  #     except Exception as exc:
  #       # TODO fail hard here?
  #       logging.error("Failed to scan %s: %s", device.name, exc)

  # def watch_point(self, point: ss2_client.SunSpecModbusClientPoint, callback: Callable[[ss2_client.SunSpecModbusClientPoint], None]):
  #   device = point.model.device
  #   points = self.__watched_points_by_device.setdefault(device, dict())
  #   points[point] = callback
  #   # If the point has a scale-factor point read it's value to ensure it gets used?
  #   if point.sf is not None:
  #     sf_point = point.model.points[point.sf]
  #     if sf_point.value is None:
  #       sf_point.read()  # TODO retries
  #     logging.debug("Bind %s with scale factor %s=%s", point_id(
  #         point), point_id(sf_point), sf_point.cvalue)
  #   else:
  #     logging.debug("Bind %s with no scale factor", point_id(point))

  # def watch_points(self, points: dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint], None]]):
  #   for point, callback in points.items():
  #     self.watch_point(point, callback)

  # def __read_points(self, device: ss2_client.SunSpecModbusClientDeviceTCP, points: dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint]]], tries=3):
  #   self.__connect_device(device, tries=tries)
  #   for point, callback in points.items():
  #     for t in range(tries):
  #       try:
  #         point.read()
  #         logging.debug("Read %s", point_id(point))
  #         break
  #       except Exception as e:
  #         logging.warning("Error reading %s on try %s: %s", device.name, t, e)
  #         self.__connect_device(device, tries=tries, reconnect=True)
  #     # Execute read callback
  #     callback(point)

  # def __do_read_points(self, device: ss2_client.SunSpecModbusClientDeviceTCP, points: dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint]]], tries=3):
  #   return self.__executor.submit(self.__read_points, device, points, tries=tries)

  def read(self):
    logging.info("read")
    # self.__read(self.__watched_points_by_device)

  # def read_point(self, point: ss2_client.SunSpecModbusClientPoint):
  #   device = point.model.device
  #   points = self.__watched_points_by_device[device]
  #   # TODO better error message if being asked to read point with no callback
  #   callback = points[point]
  #   self.__read({device: {point: callback}})

  # def __read(self, points: dict[ss2_client.SunSpecModbusClientDeviceTCP, dict[ss2_client.SunSpecModbusClientPoint, Callable[[ss2_client.SunSpecModbusClientPoint]]]]):
  #   start = time.time()
  #   logging.debug("POLLING POINTS")
  #   futures_to_devices = {}

  #   # Kick off reads for all watched devices/models
  #   for device, points in points.items():
  #     futures_to_devices[self.__do_read_points(device, points)] = device

  #   for future in concurrent.futures.as_completed(futures_to_devices):
  #     device = futures_to_devices[future]
  #     try:
  #       future.result()
  #     except Exception as exc:
  #       logging.error("Failed to read %s: %s", device.name, exc)

  #   logging.debug("POLLED POINTS IN %fms", (time.time() - start) * 1000)

  def close(self):
    logging.info("Closing all devices")
    # for name, device in self.__devices.items():
    #   device.close()
    #   logging.debug('Closed %s', name)
