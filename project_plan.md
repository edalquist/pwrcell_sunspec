requirements
  * ssh into pwrcell
  * download sunspec files from pwrcell
  * connect to mqtt port to listen for update events
  * connect to modbus for polling
    * poll power data & critical state after each mqtt event (minimize # of modbus calls?)
    * poll general state/config at a lower rate

API
  * App keeps a local copy of state in memory
  * Can print diff on each update
  * Support callback on each state change

pip install paho-mqtt pysunspec2 sshtunnel absl-py yamldataclassconfig pyserial