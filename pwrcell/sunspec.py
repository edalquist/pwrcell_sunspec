import logging
from contextlib import contextmanager
from typing import Any, Generator, TypeVar

import sunspec2.device as ss2_device
import sunspec2.modbus.client as ss2_client

from .config import PwrcellDeviceIds, RootConfig, saveConfig
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


class SunspecClient():
  # __energy_recordset_live: energy_record_set_pb2.EnergyRecordSet

  def __init__(self, config: RootConfig, tunnel_config: TunnelConfig):
    self.__config = config
    self.__tunnel_ip = tunnel_config.host
    self.__tunnel_port = tunnel_config.modbus_port

  def __enter__(self):
    sunspec_models_dir = load_models_dir(self.__config)
    ss2_device.set_model_defs_path([str(sunspec_models_dir)] + ss2_device.get_model_defs_path())

    if not self.__config.pwrcell.device_ids:
      self.__config.devices = self.scan()
      logger.info("Save config post-scan")
      saveConfig(self.__config)

    # TODO can we maintain multiple TCP connections concurrently?

    return self

  def __exit__(self, *exc):
    return False


  def scan(self, start: int = 1, end: int = 100, stop_at_first_duplicate = True) -> PwrcellDeviceIds:
    logger.info("Scanning %s:%s from ID %s to %s",
                 self.__tunnel_ip, self.__tunnel_port, start, end)
    devices: PwrcellDeviceIds = PwrcellDeviceIds()
    found_devices: dict[str, int] = {}

    for slid in range(start, end):
      d = ss2_client.SunSpecModbusClientDeviceTCP(
          slave_id=slid, ipaddr=self.__tunnel_ip, ipport=self.__tunnel_port, timeout=60)
      for _ in range(3):
        with _client_device(d) as d:
          try:
            d.scan()
            break # successful scan, break out of retry loop
          except Exception as e:
            if 'Modbus exception 11:' in str(e):
              logger.info('Retrying %s', slid)
              continue
            elif "Error scanning SunSpec base addresses." in str(e):
              logger.debug('ID %s - No Device', slid)
              break
            raise e

      if 'common' not in d.models:
        logger.debug('ID %s - No Device', slid)
        continue

      # SN: Serial Number
      serial_number = d.common[0].SN.value
      # Vr: Version
      version = d.common[0].Vr.value
      # Md: Model
      model = d.common[0].Md.value
      # Mn: Manufacturer
      manufacturer = d.common[0].Mn.value

      ids = found_devices.setdefault(serial_number, [])
      ids.append(slid)

      if len(ids) > 1:
        logger.info('Duplicate @ ID %s is "%s" "%s" (v: %s / sn: %s)',
          ids,
          manufacturer,
          model,
          version,
          serial_number
        )

        if stop_at_first_duplicate:
          return devices
      else:
        logger.info('Found @ ID %s is "%s" "%s" (v: %s / sn: %s)',
          slid,
          manufacturer,
          model,
          version,
          serial_number
        )

        if model == "REbus Beacon":
          devices.rebus_beacon[serial_number] = slid
        elif model == "ICM":
          devices.icm[serial_number] = slid
        elif model == "PV Link":
          devices.pv_link[serial_number] = slid
        elif "Inverter" in model:
          devices.inverter[serial_number] = slid
        elif "Battery" in model:
          devices.battery[serial_number] = slid
        else:
          logger.warning('Unknown device discovered @ ID %s is "%s" "%s" (v: %s / sn: %s)',
            slid,
            manufacturer,
            model,
            version,
            serial_number
          )

    return devices