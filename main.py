import pwrcell
import sys
import logging


def main():
  FORMAT = '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
  logging.basicConfig(format=FORMAT, level=logging.DEBUG)

  device_config = {
      'rebus_beacon': 1,
      'inverter': 8,
      'pv_links': [3, 4, 5, 6, 7],
      'battery': 9
  }
  gpc = pwrcell.GeneracPwrCell(device_config, ipport=5020, timeout=60)
  try:
    gpc.init()
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
