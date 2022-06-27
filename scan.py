#!/usr/bin/env python3

from operator import invert
import sys
import time
import datetime
import sunspec2.modbus.client as client
import sunspec2.device as device
import sunspec2

GENERAC_SUNSPEC_MODELS = '/Users/edalquist/personal/pwrcell/pika/sunspec-models'
BEACON_IP = '127.0.0.1'
BEACON_PORT = 5020

# Ensure PwrCell models are used
device.set_model_defs_path([GENERAC_SUNSPEC_MODELS] + device.get_model_defs_path())
print(device.get_model_defs_path())

found_devices = {}

# Does a deep scan to find devices
for slid in range(1, 100):
  d = client.SunSpecModbusClientDeviceTCP(slave_id=slid, ipaddr=BEACON_IP, ipport=BEACON_PORT, timeout=60)
  # Try up to 3 rimes
  for t in range(3):
    try:
      d.scan()
      print('{}: Scanned {}'.format(datetime.datetime.now(), d.common[0].Md.get_value()))
      found_devices[slid] = d.common[0].Md.get_value()
      for model in d.model_list:
        print(model)
      break
    except Exception as e:
      pass
  d.close()

for slid, name in found_devices.items():
  print('ID: {} -> {}'.format(slid, name))
