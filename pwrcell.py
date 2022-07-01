import concurrent.futures
import datetime
import sunspec2.modbus.client as ss2_client
import sunspec2.modbus.modbus as mb
import logging


class GeneracPwrCell():
  def __init__(self, device_config: dict[str, int], ipaddr='127.0.0.1', ipport=502, timeout=None):
    self.__devices = {}
    self.__ipaddr = ipaddr
    self.__ipport = ipport
    self.__iptimeout = timeout

    self.__rebus_beacon = self.__init_device(
        'rebus_beacon', device_config.rebus_beacon)
    self.__inverter = self.__init_device('inverter', device_config.inverter)

    if device_config.pv_links is None:
      raise ValueError("pv_links id must be set")
    self.__pv_links = {}
    for pv_link_id in device_config.pv_links:
      pv_link_name = 'pv_link_{}'.format(pv_link_id)
      self.__pv_links[pv_link_name] = self.__init_device(
          pv_link_name, pv_link_id)

    if device_config.battery is not None:
      self.__battery = self.__init_device('battery', device_config.battery)

  def __init_device(self, name: str, device_id: int):
    if name in self.__devices:
      raise ValueError("Device {} is already configured".format(name))
    if device_id is None:
      raise ValueError("{} id must be set".format(name))

    device = ss2_client.SunSpecModbusClientDeviceTCP(
        slave_id=device_id, ipaddr=self.__ipaddr, ipport=self.__ipport, timeout=self.__iptimeout)
    device.name = name
    logging.info("Configured {} at {}:{} on id {}".format(name,
                                                          self.__ipaddr, self.__ipport, device_id))
    self.__devices[name] = device
    return device

  def __scan_device(self, name: str, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3):
    for t in range(tries):
      try:
        device.scan()
        logging.info("Scanned {} as {}".format(
            name, device.common[0].Md.get_value()))
        break
      except mb.ModbusClientException as e:
        logging.warning("Error scanning {} on try {}: {}".format(name, t, e))

  def scan(self):
    for name, device in self.__devices.items():
      self.__scan_device(name, device)
      # TODO make parallel https://docs.python.org/3/library/concurrent.futures.html

  def close(self):
    logging.debug("Closing all devices")
    for name, device in self.__devices.items():
      device.close()
      logging.debug('Closed {}'.format(name))


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
