import dataclasses
import logging
from contextlib import contextmanager
from dataclasses import field
from enum import Enum
from typing import Any, Generator, TypeVar

import sunspec2.device as ss2_device
import sunspec2.modbus.client as ss2_client

from .config import AppConfig, DeviceConfig
from .logging import time_fn
from .models import load_models_dir
from .tunnel import TunnelConfig

CDT = TypeVar("CDT", bound=ss2_client.SunSpecModbusClientDeviceTCP)

logger = logging.getLogger(__name__)

@contextmanager
def _client_device(client_device: CDT) -> Generator[CDT, None, None]:
  try:
    client_device.connect()
    yield client_device
  finally:
    client_device.disconnect()
class DeviceType(Enum):
  REBUS_BECON = 1
  INVERTER = 2
  PV_LINK = 3
  BATTERY = 4
  ICM = 5

  @staticmethod
  def resolveType(model: str) -> 'DeviceType|None':
    if not model:
      return None
    if model == "REbus Beacon":
      return DeviceType.REBUS_BECON
    if model == "ICM":
      return DeviceType.ICM
    if model == "PV Link":
      return DeviceType.PV_LINK
    if "Inverter" in model:
      return DeviceType.INVERTER
    if "Battery" in model:
      return DeviceType.BATTERY

    return None

@dataclasses.dataclass
class Devices:
  rebus_beacon: dict[str: ss2_client.SunSpecModbusClientDeviceTCP] = field(default_factory=dict)
  inverter: dict[str: ss2_client.SunSpecModbusClientDeviceTCP] = field(default_factory=dict)
  pv_link: dict[str: ss2_client.SunSpecModbusClientDeviceTCP] = field(default_factory=dict)
  battery: dict[str: ss2_client.SunSpecModbusClientDeviceTCP] = field(default_factory=dict)
  icm: dict[str: ss2_client.SunSpecModbusClientDeviceTCP] = field(default_factory=dict)

  def get_config(self) -> DeviceConfig:
    config = DeviceConfig()
    config.rebus_beacon = {sn: d.slave_id for sn, d in self.rebus_beacon.items()}
    config.inverter = {sn: d.slave_id for sn, d in self.inverter.items()}
    config.pv_link = {sn: d.slave_id for sn, d in self.pv_link.items()}
    config.battery = {sn: d.slave_id for sn, d in self.battery.items()}
    config.icm = {sn: d.slave_id for sn, d in self.icm.items()}
    return config


class SunspecClient():
  # __energy_recordset_live: energy_record_set_pb2.EnergyRecordSet
  __devices: Devices

  def __init__(self, config: AppConfig, tunnel_config: TunnelConfig):
    self.__config = config
    self.__tunnel_ip = tunnel_config.host
    self.__tunnel_port = tunnel_config.modbus_port

  def __enter__(self):
    sunspec_models_dir = load_models_dir(self.__config)
    ss2_device.set_model_defs_path([str(sunspec_models_dir)] + ss2_device.get_model_defs_path())

    if not self._load_devices():
      device_config = self.scan()
      logger.info("Saving config post-scan")
      device_config.write()


    return self

  def __exit__(self, *exc):
    return False

  def _scan_with_retries(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries = 3, full_model_read = True) -> bool:
    for _ in range(tries):
      with _client_device(device) as d:
        try:
          d.scan(full_model_read=full_model_read)
          return True
        except Exception as e:
          if 'Modbus exception 11:' in str(e):
            logger.info('Retrying %s', d.slave_id)
            continue
          elif "Error scanning SunSpec base addresses." in str(e):
            logger.debug('ID %s - No Device', d.slave_id)
            return False
          raise e

  def _create_device(self, id: int, full_model_read = True) -> ss2_client.SunSpecModbusClientDeviceTCP|None:
    d = ss2_client.SunSpecModbusClientDeviceTCP(
          slave_id=id, ipaddr=self.__tunnel_ip, ipport=self.__tunnel_port, timeout=60)
    if self._scan_with_retries(d, full_model_read = full_model_read):
      return d
    return None

  def scan(self, start: int = 1, end: int = 100, stop_at_first_duplicate = True) -> DeviceConfig:
    logger.info("Scanning %s:%s from ID %s to %s",
                 self.__tunnel_ip, self.__tunnel_port, start, end)
    devices = Devices()

    found_devices: dict[str, int] = {}

    for slid in range(start, end):
      d = self._create_device(slid)
      if not d:
        continue

      if 'common' not in d.models:
        logger.debug('ID %s - No Device', slid)
        continue

      # Md: Model
      model = d.common[0].Md.value
      if not model:
        logger.debug('No model field found for device %s', slid)
        continue

      # SN: Serial Number
      serial_number = d.common[0].SN.value
      # Vr: Version
      version = d.common[0].Vr.value
      # Mn: Manufacturer
      manufacturer = d.common[0].Mn.value

      device_type = DeviceType.resolveType(model)
      if not device_type:
        logger.warning('Unknown device discovered @ ID %s is "%s" "%s" (v: %s / sn: %s)',
          slid,
          manufacturer,
          model,
          version,
          serial_number
        )
        continue

      ids = found_devices.setdefault(serial_number, [])
      ids.append(slid)

      if len(ids) > 1:
        if stop_at_first_duplicate:
          logging.info('Found duplicate devices at %s, stopping scan.', ids)
          self.__devices = devices
          return devices.get_config()

        logger.info('Duplicate IDs %s is "%s" "%s" (v: %s / sn: %s)',
          ids,
          manufacturer,
          model,
          version,
          serial_number
        )
      else:
        logger.info('Found @ ID %s is "%s" "%s" (v: %s / sn: %s)',
          slid,
          manufacturer,
          model,
          version,
          serial_number
        )

        match device_type:
          case DeviceType.REBUS_BECON:
            devices.rebus_beacon[serial_number] = d
          case DeviceType.ICM:
            devices.icm[serial_number] = d
          case DeviceType.PV_LINK:
            devices.pv_link[serial_number] = d
          case DeviceType.INVERTER:
            devices.inverter[serial_number] = d
          case DeviceType.BATTERY:
            devices.battery[serial_number] = d
          case _:
            logger.warning('Unknown device discovered @ ID %s is "%s" "%s" (v: %s / sn: %s)',
              slid,
              manufacturer,
              model,
              version,
              serial_number
            )

    self.__devices = devices
    return devices.get_config()

  def _load_devices(self) -> bool:
    device_config = DeviceConfig.read()

    if not device_config or device_config == DeviceConfig():
      return False

    devices = Devices()
    if not self._load_devices_into_dict(DeviceType.REBUS_BECON, device_config.rebus_beacon, devices.rebus_beacon):
      return False

    if not self._load_devices_into_dict(DeviceType.INVERTER, device_config.inverter, devices.inverter):
      return False

    if not self._load_devices_into_dict(DeviceType.PV_LINK, device_config.pv_link, devices.pv_link):
      return False

    if not self._load_devices_into_dict(DeviceType.BATTERY, device_config.battery, devices.battery):
      return False

    if not self._load_devices_into_dict(DeviceType.ICM, device_config.icm, devices.icm):
      return False

    self.__devices = devices
    return True

  def _load_devices_into_dict(self, expected_type: DeviceType, ids: dict[str, id], dest: dict[str, ss2_client.SunSpecModbusClientDeviceTCP]) -> bool:
    for serial_number, id in  ids.items():
      d = self._create_device(id, full_model_read=False)
      if not d:
        logger.warning('Device %s with serial %s, failed to load, triggering full re-scan', id, serial_number)
        return False

      d.common[0].read()
      if serial_number != d.common[0].SN.value:
        logger.warning('Device %s has serial %s but expected %s, triggering full re-scan', id, d.common[0].SN.value, serial_number)
        return False

      resolved_type = DeviceType.resolveType(d.common[0].Md.value)
      if resolved_type != expected_type:
        logger.warning('Device %s has is type %s but expected %s, triggering full re-scan', id, resolved_type, expected_type)
        return False

      dest[serial_number] = d

    return True