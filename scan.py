#!/usr/bin/env python3

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

FLAGS = flags.FLAGS
flags.DEFINE_string("model_dir", None, "directory")


def main(argv):
  del argv  # Unused.

  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  logging.basicConfig(format=FORMAT, level=logging.INFO)

  config = {}
  with open(os.path.join(sys.path[0], "config.yaml")) as config_file:
    config = yaml.safe_load(config_file)

  with tempfile.TemporaryDirectory() as tempdir:
    logging.debug("Extracting sunspec models to %s", tempdir)
    zf = zipfile.ZipFile(os.path.join(sys.path[0], "sunspec-models.zip"))
    zf.extractall(tempdir)

    # Configure additional model def locations
    device.set_model_defs_path(
        [os.path.join(tempdir, "sunspec-models")] + device.get_model_defs_path())

    found_devices = {}

    model_dir_path = None
    if FLAGS.model_dir is not None:
      model_dir_path = Path(FLAGS.model_dir).expanduser().resolve()
      model_dir_path.mkdir(parents=True, exist_ok=True)
      logging.info("Saving Models to %s", model_dir_path)

    # Does a deep scan to find devices
    for slid in range(1, 100):
      d = client.SunSpecModbusClientDeviceTCP(
          slave_id=slid, ipaddr=config['pwrcell']['host'], ipport=config['pwrcell']['port'], timeout=60)
      # Try up to 3 rimes
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

            if model_dir_path:
              model_file = model_dir_path / ('%s.json' % slid)
              with model_file.open('w') as f:
                f.write(json.dumps(json.loads(d.get_json()), indent=2))
              
          break
        except Exception as e:
          pass

      d.close()

      # TODO update config.yaml?


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
