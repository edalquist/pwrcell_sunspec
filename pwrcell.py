import concurrent.futures
import dataclasses
import datetime
import logging
import sunspec2.device as device
import sunspec2.modbus.client as ss2_client
import sunspec2.modbus.modbus as mb


@dataclasses.dataclass
class Config:
  rebus_beacon: int
  inverter: int
  battery: int
  pv_links: list[int]


class GeneracPwrCell():
  def __init__(self, device_config: Config, ipaddr='127.0.0.1', ipport=502, timeout=None):
    # TODO make this configurable
    device.set_model_defs_path(
        ['/Users/edalquist/personal/pwrcell/pika/sunspec-models'] + device.get_model_defs_path())

    self.__devices = {}
    self.__ipaddr = ipaddr
    self.__ipport = ipport
    self.__iptimeout = timeout

    self.__rebus_beacon = self.__init_device(
        'rebus_beacon', device_config.rebus_beacon)
    self.__inverter = self.__init_device('inverter', device_config.inverter)

    if len(device_config.pv_links) == 0:
      raise ValueError("pv_links array must be set and not empty")
    self.__pv_links = {}
    for idx, pv_link_id in enumerate(device_config.pv_links):
      pv_link_name = 'pv_link_{}'.format(idx)
      self.__pv_links[pv_link_name] = self.__init_device(
          pv_link_name, pv_link_id)

    if device_config.battery is not None:
      self.__battery = self.__init_device('battery', device_config.battery)

    self.__executor = concurrent.futures.ThreadPoolExecutor(
        thread_name_prefix='ModBusPool', max_workers=(len(self.__devices) * 2))

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

  def __connect_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3, reconnect=False):
    if not reconnect and device.is_connected():
      return
    for t in range(tries):
      try:
        device.connect()
        logging.info("Connected %s", device.name)
        break
      except mb.ModbusClientException as e:
        logging.warning("Error connecting %s on try %s: %s", device.name, t, e)

  def __scan_device(self, device: ss2_client.SunSpecModbusClientDeviceTCP, tries=3):
    # Ensure device is connected before scanning
    self.__connect_device(device, tries=tries)
    for t in range(tries):
      try:
        # Don't read all model data (it is slow)
        device.scan(connect=False, full_model_read=False)
        device.common[0].read()
        logging.info("Scanned %s as %s %s - %s",
                     device.name,
                     device.common[0].Mn.get_value(),
                     device.common[0].Md.get_value(),
                     device.common[0].SN.get_value())
        break
      except Exception as e:
        logging.warning("Error scanning %s on try %s: %s", device.name, t, e)
        self.__connect_device(device, tries=tries, reconnect=True)

  def init(self):
    futures_to_devices = {}
    for device in self.__devices.values():
      scan_future = self.__executor.submit(self.__scan_device, device)
      futures_to_devices[scan_future] = device

    for future in concurrent.futures.as_completed(futures_to_devices):
      device = futures_to_devices[future]
      try:
        future.result()
      except Exception as exc:
        logging.error("Failed to scan %s: %s", device.name, exc)

  def __read_models(self, device: ss2_client.SunSpecModbusClientDeviceTCP, models: list[list[ss2_client.SunSpecModbusClientModel]], tries=3):
    self.__connect_device(device, tries=tries)
    for model in models:
      for t in range(tries):
        try:
          model[0].read()
          # TODO how to get model group name instead of number?
          logging.debug("Read %s on %s", model[0].model_id, device.name)
          break
        except Exception as e:
          logging.warning("Error reading %s on try %s: %s", device.name, t, e)
          self.__connect_device(device, tries=tries, reconnect=True)

  def __do_read_models(self, device: ss2_client.SunSpecModbusClientDeviceTCP, models: list[list[ss2_client.SunSpecModbusClientModel]], tries=3):
    return self.__executor.submit(self.__read_models, device, models, tries=tries)

  def read(self):
    logging.info("POLLING")
    futures_to_devices = {}

    # Hard coded list of models we care about data from
    futures_to_devices[self.__do_read_models(self.__rebus_beacon, [
        self.__rebus_beacon.REbus_dir])] = self.__rebus_beacon
    futures_to_devices[self.__do_read_models(self.__inverter, [
        self.__inverter.inverter, self.__inverter.REbus_exp])] = self.__inverter
    futures_to_devices[self.__do_read_models(self.__battery, [
        self.__battery.battery])] = self.__battery
    for pv_link in self.__pv_links.values():
      futures_to_devices[self.__do_read_models(pv_link, [
          pv_link.string_combiner])] = pv_link

    for future in concurrent.futures.as_completed(futures_to_devices):
      device = futures_to_devices[future]
      try:
        future.result()
      except Exception as exc:
        logging.error("Failed to read %s: %s", device.name, exc)

  def close(self):
    logging.debug("Closing all devices")
    for name, device in self.__devices.items():
      device.close()
      logging.debug('Closed %s', name)
