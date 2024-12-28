requirements
* X ssh into pwrcell
* X download sunspec files from pwrcell
* X connect to mqtt port to listen for update events
* On init
  * if no devices, scan and save config
  * if devices, verify serial numbers match, if not re-scan
* Create data model sort of like the sunspec model?
  * TODO map MQTT protos back to corresponding Modbus values!!!
  * Root of tree is list of devices, support 0..N of each (only 1 rebus?)
  * How should the API under each device look?
    * Sunspec model is easy but very hard to understand naming
    * Could generate real names from the sunspec model labels?
* Data API access
  * Callback registration for all MQTT driven fields
  * Callback registration for all sunspec fields
    * requires poll rate on registration
    * support any number of registrations
  * Pull style API for all fields
    * MQTT fields should cache
    * ModBus fields should trigger a read

API
* App keeps a local copy of state in memory
* Can print diff on each update
* Support callback on each state change





pip install paho-mqtt pysunspec2 sshtunnel absl-py yamldataclassconfig pyserial


