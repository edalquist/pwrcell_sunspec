import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, TypeVar

import sunspec2.device as ss2_device
import sunspec2.modbus.client as ss2_client

from .config import RootConfig
from .logging import time_fn
from .models import load_models_dir
from .tunnel import TunnelConfig

CDT = TypeVar("CDT", bound=ss2_client.SunSpecModbusClientDeviceTCP)

logger = logging.getLogger(__name__)

@contextmanager
def _client_device(client_device: CDT) -> Generator[CDT, None, None]:
  try:
    with time_fn(logger, "ID %s connect took %sms", client_device.slave_id):
      client_device.connect()
    yield client_device
  finally:
    with time_fn(logger, "ID %s disconn took %sms", client_device.slave_id):
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
      # TODO save config?

    # TODO can we maintain multiple TCP connections concurrently?

    return self

  def __exit__(self, *exc):
    return False


  def scan(self, start: int = 1, end: int = 100, stop_at_first_duplicate = True):
    logger.info("Scanning %s:%s from ID %s to %s",
                 self.__tunnel_ip, self.__tunnel_port, start, end)
    found_devices = {}

    for slid in range(start, end):
      d = ss2_client.SunSpecModbusClientDeviceTCP(
          slave_id=slid, ipaddr=self.__tunnel_ip, ipport=self.__tunnel_port, timeout=60)
      for _ in range(3):
        with _client_device(d) as d:
          try:
            with time_fn(logger, "ID %s scan    took %sms", d.slave_id):
              d.scan()
            break
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

        # REbus Beacon
        # ICM
        # PV Link
        # PWRcell X7602 Inverter
        # PWRcell Battery

        # SN: Serial Number
        # Vr: Version
        # Md: Model
        # Mn: Manufacturer
        ids = found_devices.setdefault(d.common[0].SN.value, [])
        ids.append(slid)

        if len(ids) > 1:
          if stop_at_first_duplicate:
            return

          logger.info('Duplicate @ ID %s is "%s" "%s" (v: %s / sn: %s)',
            ids,
            d.common[0].Mn.value,
            d.common[0].Md.value,
            d.common[0].Vr.value,
            d.common[0].SN.value
          )
        else:
          logger.info('Found @ ID %s is "%s" "%s" (v: %s / sn: %s)',
            slid,
            d.common[0].Mn.value,
            d.common[0].Md.value,
            d.common[0].Vr.value,
            d.common[0].SN.value
          )