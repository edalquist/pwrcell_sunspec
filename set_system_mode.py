#!/usr/bin/env python3

from operator import invert
import sys
import time
import datetime
import sunspec2.modbus.client as client
import sunspec2.device as device
import sunspec2

# Ensure PwrCell models are used
device.set_model_defs_path(['/Users/edalquist/personal/pwrcell/pika/sunspec-models'] + device.get_model_defs_path())
print(device.get_model_defs_path())

devices = []
try:
  # Configure devices
  beacon = client.SunSpecModbusClientDeviceTCP(slave_id=1, ipaddr='127.0.0.1', ipport=5020, timeout=60)
  devices.append(beacon)

  # Load device data for all
  print('{}: Initial Model Scan'.format(datetime.datetime.now()))
  for d in devices:
    for t in range(3):
      try:
        d.scan()
        print('{}: Scanned {}'.format(datetime.datetime.now(), d.common[0].Md.get_value()))
        break
      except sunspec2.modbus.modbus.ModbusClientException as e:
        print('retry: {}'.format(e))


  beacon.REbus_dir[0].read()
  sys_mode = beacon.REbus_dir[0].SysMd.value
  print("\t    System Mode\t{:,}".format(sys_mode))

  beacon.REbus_dir[0].SysMd.value = 3
  beacon.REbus_dir[0].write()

  beacon.REbus_dir[0].read()
  sys_mode = beacon.REbus_dir[0].SysMd.value
  print("\t    System Mode\t{:,}".format(sys_mode))

  
except KeyboardInterrupt as e:
  print(e)
finally:
  print('{}: Closing'.format(datetime.datetime.now()))
  for d in devices:
    d.close()

# {
#   "name": "SAFETY_SHUTDOWN",
#   "value": 0
# },
# {
#   "name": "GRID_TIE",
#   "value": 1
# },
# {
#   "name": "SELF_SUPPLY",
#   "value": 2
# },
# {
#   "name": "CLEAN_BACKUP",
#   "value": 3
# },
# {
#   "name": "PRIORITY_BACKUP",
#   "value": 4
# },
# {
#   "name": "REMOTE_ARBITRAGE",
#   "value": 5
# },
# {
#   "name": "SELL",
#   "value": 6
# }
