import logging
import pwrcell
import sys
import time


def main():
  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  logging.basicConfig(format=FORMAT, level=logging.DEBUG)

  device_config = pwrcell.Config(
      rebus_beacon=1, inverter=8, battery=9, pv_links=[3, 4, 5, 6, 7])
  gpc = pwrcell.GeneracPwrCell(device_config, ipport=5020, timeout=60)
  try:
    gpc.init()
    while True:
      gpc.read()
      time.sleep(3)
  except KeyboardInterrupt as e:
    logging.info("Closing: %s", e)
  finally:
    gpc.close()


if __name__ == '__main__':
  sys.exit(main())

# DEVICES = {
#     'REbus Beacon': [1, 10],
#     'ICM': [2],
#     'PV Link 000100034AC7': [3, 30],
#     'PV Link 000100034E68': [4, 31],
#     'PV Link 000100034FAC': [5, 32],
#     'PV Link 0001000361C7': [6, 33],
#     'PV Link 0001000361F4': [7, 34],
#     'PWRcell X7602 Inverter': [8, 70],
#     'PWRcell Battery': [9, 80]
# }
