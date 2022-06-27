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
  battery = client.SunSpecModbusClientDeviceTCP(slave_id=9, ipaddr='127.0.0.1', ipport=5020, timeout=60)
  devices.append(battery)

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


  battery.battery[0].read()
  bat_min_reserve = battery.battery[0].SoCRsvMin.value / 10
  print("\t    Battery Min Reserve\t{:,}%".format(bat_min_reserve))

  battery.battery[0].SoCRsvMin.value = (85 * 10)
  battery.battery[0].write()

  battery.battery[0].read()
  bat_min_reserve = battery.battery[0].SoCRsvMin.value / 10
  print("\t    Battery Min Reserve\t{:,}%".format(bat_min_reserve))

  
except KeyboardInterrupt as e:
  print(e)
finally:
  print('{}: Closing'.format(datetime.datetime.now()))
  for d in devices:
    d.close()
