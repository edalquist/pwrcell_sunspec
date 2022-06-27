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

# PwrCell modbus device IDs
# TODO this would need to be discovered in the future
DEVICES = {
  'REbus Beacon': [1, 10],
  'ICM': [2],
  'PV Link 000100034AC7': [3, 30],
  'PV Link 000100034E68': [4, 31],
  'PV Link 000100034FAC': [5, 32],
  'PV Link 0001000361C7': [6, 33],
  'PV Link 0001000361F4': [7, 34],
  'PWRcell X7602 Inverter': [8, 70],
  'PWRcell Battery': [9, 80]
}

devices = []
try:
  # Configure devices
  inverter = client.SunSpecModbusClientDeviceTCP(slave_id=8, ipaddr='127.0.0.1', ipport=5020, timeout=60)
  devices.append(inverter)

  battery = client.SunSpecModbusClientDeviceTCP(slave_id=9, ipaddr='127.0.0.1', ipport=5020, timeout=60)
  devices.append(battery)

  pv_links = [
    client.SunSpecModbusClientDeviceTCP(slave_id=3, ipaddr='127.0.0.1', ipport=5020, timeout=60),
    client.SunSpecModbusClientDeviceTCP(slave_id=4, ipaddr='127.0.0.1', ipport=5020, timeout=60),
    client.SunSpecModbusClientDeviceTCP(slave_id=5, ipaddr='127.0.0.1', ipport=5020, timeout=60),
    client.SunSpecModbusClientDeviceTCP(slave_id=6, ipaddr='127.0.0.1', ipport=5020, timeout=60),
    client.SunSpecModbusClientDeviceTCP(slave_id=7, ipaddr='127.0.0.1', ipport=5020, timeout=60)
  ]
  devices = devices + pv_links

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


  # Gets JSON Model Data, useful for reading enums?
  # model_def = device.get_model_def(inverter.REbus_status[0].ID.get_value())
  # print(model_def)

  while True:
    print('{}: Updating Data'.format(datetime.datetime.now()))

    # TODO is there any way to do these in parallel?
    # TODO handle sunspec2.modbus.modbus.ModbusClientException from any of these
    inverter.REbus_status[0].read()
    inverter.REbus_exp[0].read()
    battery.REbus_status[0].read()
    for pv_link in pv_links:
      pv_link.REbus_status[0].read()

    inverter_output = inverter.REbus_status[0].P.get_value()
    grid_flow = inverter.REbus_exp[0].Px1.get_value() + inverter.REbus_exp[0].Px2.get_value()
    house_flow = grid_flow - inverter_output
    battery_flow = battery.REbus_status[0].P.get_value()
    pvlink_output = 0
    for pv_link in pv_links:
      pvlink_output += pv_link.REbus_status[0].P.get_value()
    pvlink_output /= 10

    print("\t   Solar Output {:,}KW DC".format(pvlink_output))
    print("\t   Battery Flow {:,}KW DC".format(battery_flow))
    print("\tInverter Output {:,}KW AC".format(inverter_output))
    print("\t      Grid Flow {:,}KW AC".format(grid_flow))
    print("\t     House Flow {:,}KW AC".format(house_flow))
    time.sleep(3)
  
except KeyboardInterrupt as e:
  print(e)
finally:
  print('{}: Closing'.format(datetime.datetime.now()))
  for d in devices:
    d.close()

# battery.SoCRsvMin
# battery.SoC
