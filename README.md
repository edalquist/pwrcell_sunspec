# Generac PWRCell API via SunSpec / ModBus TCP

You will need access to the ModBus TCP port on your Generac Beacon. How to do this is currently left as an exercise for
the reader.

# Installation

This has currently been tested running in a linux container (LXC) but should work on any system
where Python venv's are viable. Instructions below are for systems with systemd

## Setup SSH Tunnel

Follow https://gist.github.com/drmalex07/c0f9304deea566842490 to set up an SSH tunnel as a service.


Service template: `/etc/systemd/system/secure-tunnel@.service`
```
[Unit]
Description=Setup a secure tunnel to %I
After=network.target

[Service]
Environment="LOCAL_ADDR=localhost"
EnvironmentFile=/etc/default/secure-tunnel@%i
ExecStart=/usr/bin/ssh -NT -i ${KEY_PATH} -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes -L ${LOCAL_ADDR}:${LOCAL_PORT}:localhost:${REMOTE_PORT} ${TARGET}

# Restart every >2 seconds to avoid StartLimitInterval failure
RestartSec=5
Restart=always

[Install]
WantedBy=multi-user.target
```

Service Config: `/etc/default/secure-tunnel@pwrcell`
```
TARGET=root@192.168.0.XXX
LOCAL_ADDR=0.0.0.0
LOCAL_PORT=5020
REMOTE_PORT=502
KEY_PATH=/etc/default/secure-tunnel/pwrcell
```

Enable, start, and verify:
```
systemctl enable secure-tunnel@pwrcell
systemctl start secure-tunnel@pwrcell
systemctl status secure-tunnel@pwrcell
```

## Setup pwrcell_sunspec

Clone this repository into your chosen directory:

```
cd /opt
git clone https://github.com/edalquist/pwrcell_sunspec.git
```

Setup python venv:

```
cd pwrcell_sunspec
python3.11 -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

Configure pwrcell_sunspec by cloning the example config `cp config.example.yaml config.yaml` and
editing the `mqtt` block to point to your MQTT server with the correct username/password. The
`pwrcell` config can be left alone if using the ssh service as described above.

Add systemd configuration in `/etc/systemd/system/pwrcell-ha.service`, note that this declares a
dependency on the `secure-tunnel@pwrcell.service` systemd service configured above.

```
[Unit]
Description=Publish PwrCell data to Home Assistant
After=syslog.target network.target secure-tunnel@pwrcell.service

[Service]
Type=simple
WorkingDirectory=/opt/pwrcell_sunspec
ExecStart=/opt/pwrcell_sunspec/venv/bin/python /opt/pwrcell_sunspec/main.py

# Restart every >2 seconds to avoid StartLimitInterval failure
RestartSec=5
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable, start, and verify:
```
systemctl enable pwrcell-ha.service
systemctl start pwrcell-ha.service
systemctl status pwrcell-ha.service
```

# Plans

* https://sshtunnel.readthedocs.io/en/latest/
* https://pypi.org/project/paho-mqtt/
* https://gitlab.com/ttblt-hass/mqtt-hass-base

Have this run and pull data from PwrCell and push into Home Assistant MQTT sensors
