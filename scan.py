#!/usr/bin/env python3

from absl import app
from absl import flags
from contextlib import contextmanager
from dataclasses import asdict
from operator import invert
from pathlib import Path
from sshtunnel import open_tunnel
import copy
import datetime
import json
import logging
import os
import re
import sunspec2
import sunspec2.device as device
import sunspec2.modbus.client as client
import sys
import tempfile
import time
import yaml
import zipfile

FLAGS = flags.FLAGS
flags.DEFINE_string("model_dir", None, "directory")

from config import PwrcellDeviceIds, RootConfig

CONFIG: RootConfig = RootConfig()



@contextmanager
def _open_tunnel():
  logging.info("opening pwrcell tunnel to %s:%s",
               CONFIG.pwrcell.ssh_tunnel.host, CONFIG.pwrcell.ssh_tunnel.port)
  with open_tunnel(
      (CONFIG.pwrcell.ssh_tunnel.host, CONFIG.pwrcell.ssh_tunnel.port),
      ssh_username=CONFIG.pwrcell.ssh_tunnel.username,
      ssh_pkey=CONFIG.pwrcell.ssh_tunnel.identity_file,
      local_bind_address=('127.0.0.1', ),
      remote_bind_address=('127.0.0.1', 502),
      set_keepalive=4.0,
  ) as server:
    logging.info("pwrcell tunnel listening on %s:%s",
                 server.local_bind_address[0], server.local_bind_port)
    yield server


@contextmanager
def _sunspec_models():
  with tempfile.TemporaryDirectory() as tempdir:
    logging.info("Extracting sunspec models to %s", tempdir)
    zf = zipfile.ZipFile(os.path.join(sys.path[0], "sunspec-models.zip"))
    zf.extractall(tempdir)
    yield os.path.join(tempdir, "sunspec-models")


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  CONFIG.load(os.path.join(sys.path[0], "config.yaml"))

  log_level = logging.getLevelName(CONFIG.log_level) or logging.INFO
  logging.basicConfig(format=FORMAT, level=log_level)
  logging.info("Setting Log Level to %s", log_level)

  with _open_tunnel() as server, \
      _sunspec_models() as temp_models:

    # Configure additional model def locations
    device.set_model_defs_path([temp_models] + device.get_model_defs_path())

    found_devices = {}
    config_fragment: PwrcellDeviceIds = PwrcellDeviceIds()

  #   # Does a deep scan to find devices
    for slid in range(1, 100):
      d = client.SunSpecModbusClientDeviceTCP(
          slave_id=slid,
          ipaddr=server.local_bind_address[0],
          ipport=server.local_bind_port,
          timeout=60)
      # Try up to 3 times
      scan_count = 0
      success = False
      while not success and scan_count < 3:
        try:
          scan_count += 1
          d.scan()
          success = True
        except Exception:
          pass

        if success:
          # Track IDs by Serial > Version > Model > Make > ID tree to detect duplicate devices
          ids = found_devices.setdefault(d.common[0].SN.value,
            {}).setdefault(d.common[0].Vr.value,
            {}).setdefault(d.common[0].Md.value,
            {}).setdefault(d.common[0].Mn.value,
            [])
          ids.append(slid)

          if len(ids) > 1:
            logging.info('Duplicate Device ID %s / %s', slid, ids)
          else:
            logging.info('Found ID %s is %s: %s (v: %s / sn: %s)',
              slid,
              # d.common[0].DA.value, # this is always None
              d.common[0].Mn.value,
              d.common[0].Md.value,
              d.common[0].Vr.value,
              d.common[0].SN.value
            )

            if "REbus Beacon" == d.common[0].Md.value:
              config_fragment.rebus_beacon = slid
            elif re.match(r"PWRcell .* Inverter", d.common[0].Md.value):
              config_fragment.inverter.append(slid)
            elif "PV Link" == d.common[0].Md.value:
              config_fragment.pv_links.append(slid)
            elif "PWRcell Battery" == d.common[0].Md.value:
              config_fragment.battery.append(slid)
            elif "ICM" == d.common[0].Md.value:
              config_fragment.icm = slid

      d.close()

    updated_config = copy.deepcopy(CONFIG)
    updated_config.pwrcell.device_ids = config_fragment
    print("********** updated config.yaml **********")
    yaml.dump(asdict(updated_config), sys.stdout, default_flow_style=False)
    print("*****************************************")


if __name__ == '__main__':
  app.run(main)

# common:
#   ID:  1
#   L:  66
#   Mn:  Generac
#   Md:  REbus Beacon
#   Opt:  None
#   Vr:  CES-1.1.2.B66
#   SN:  0001001206E8
#   DA:  None
#   Pad:  32768
