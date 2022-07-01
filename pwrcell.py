import concurrent.futures
import datetime
import sunspec2.modbus.client as ss2_client
import sunspec2.modbus.modbus as mb
import logging


class GeneracPwrCell():
  def __init__(self, device_config: dict, ipaddr='127.0.0.1', ipport=502, timeout=None):
    self.__devices = {}
    self.__ipaddr = ipaddr
    self.__ipport = ipport
    self.__iptimeout = timeout

    self.__rebus_beacon = self.__init_device(
        'rebus_beacon', device_config['rebus_beacon'])
    self.__inverter = self.__init_device('inverter', device_config['inverter'])

    if 'pv_links' not in device_config or len(device_config['pv_links']) == 0:
      raise ValueError("pv_links array must be set and not empty")
    self.__pv_links = {}
    for idx, pv_link_id in enumerate(device_config['pv_links']):
      pv_link_name = 'pv_link_{}'.format(idx)
      self.__pv_links[pv_link_name] = self.__init_device(
          pv_link_name, pv_link_id)

    if 'battery' in device_config:
      self.__battery = self.__init_device('battery', device_config['battery'])

  def __init_device(self, name: str, device_id: int):
    if name in self.__devices:
      raise ValueError("Device {} is already configured".format(name))
    if device_id is None:
      raise ValueError("{} id must be set".format(name))

    device = ss2_client.SunSpecModbusClientDeviceTCP(
        slave_id=device_id, ipaddr=self.__ipaddr, ipport=self.__ipport, timeout=self.__iptimeout)
    device.name = name
    logging.info("Configured %s at %s:%s on id %s", name,
                 self.__ipaddr, self.__ipport, device_id)
    self.__devices[name] = device
    return device

  def __scan_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3):
    for t in range(tries):
      try:
        device.scan()
        logging.info("Scanned %s as %s %s - %s",
                     device.name,
                     device.common[0].Mn.get_value(),
                     device.common[0].Md.get_value(),
                     device.common[0].SN.get_value())
        break
      except mb.ModbusClientException as e:
        logging.warning("Error scanning %s on try %s: %s", device.name, t, e)

  def scan(self):
    with concurrent.futures.ThreadPoolExecutor(thread_name_prefix='ScanPool', max_workers=len(self.__devices)) as executor:
      future_to_device = {executor.submit(
          self.__scan_device, device): device for device in self.__devices.values()}
      for future in concurrent.futures.as_completed(future_to_device):
        device = future_to_device[future]
        try:
          future.result()
        except Exception as exc:
          logging.error("Failed to scan %s: %s", device.name, exc)

  def close(self):
    logging.debug("Closing all devices")
    for name, device in self.__devices.items():
      device.close()
      logging.debug('Closed %s', name)
