#!/usr/bin/env python3

from contextlib import contextmanager
from absl import app
from absl import flags
from operator import invert
from pathlib import Path
import datetime
import json
import logging
import os
import sunspec2
import sunspec2.device as device
import sunspec2.modbus.client as client
import sys
import tempfile
import time
import yaml
import zipfile
from sshtunnel import open_tunnel

FLAGS = flags.FLAGS
flags.DEFINE_string("model_dir", None, "directory")

from config import RootConfig

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

  #   model_dir_path = None
  #   if FLAGS.model_dir is not None:
  #     model_dir_path = Path(FLAGS.model_dir).expanduser().resolve()
  #     model_dir_path.mkdir(parents=True, exist_ok=True)
  #     logging.info("Saving Models to %s", model_dir_path)

  #   # Does a deep scan to find devices
    for slid in range(1, 100):
      d = client.SunSpecModbusClientDeviceTCP(
          slave_id=slid,
          ipaddr=server.local_bind_address[0],
          ipport=server.local_bind_port,
          timeout=60)
      # Try up to 3 times
      for t in range(3):
        try:
          d.scan()

          # Track IDs by Serial > Version > Model > Make > ID tree to detect duplicate devices
          ids = found_devices.setdefault(d.common[0].SN.value,
            {}).setdefault(d.common[0].Vr.value,
            {}).setdefault(d.common[0].Md.value,
            {}).setdefault(d.common[0].Mn.value,
            [])
          ids.append(slid)

          if len(ids) > 1:
            logging.info('Duplicate ID %s is %s %s (%s / %s)',
              ids,
              d.common[0].Mn.value,
              d.common[0].Md.value,
              d.common[0].Vr.value,
              d.common[0].SN.value
            )
          else:
            logging.info('Found ID %s is %s %s (%s / %s)',
              slid,
              d.common[0].Mn.value,
              d.common[0].Md.value,
              d.common[0].Vr.value,
              d.common[0].SN.value
            )

            # if model_dir_path:
            #   model_file = model_dir_path / ('%s.json' % slid)
            #   with model_file.open('w') as f:
            #     f.write(json.dumps(json.loads(d.get_json()), indent=2))

          break
        except Exception as e:
          pass

      d.close()

      # TODO update config.yaml?

    print(found_devices)


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
