# Generac PWRcell API via SunSpec / ModBus TCP

Integrate and control your Generac PWRcell system (Inverter, Battery, PV Links, REbus Beacon) using SunSpec Modbus TCP and internal MQTT telemetry. Includes a companion **Web Explorer** with live telemetry, SunSpec enum lookups, Modbus register browsing, and full **Home Assistant MQTT Discovery**.

---

## Features

- **Home Assistant MQTT Discovery**: Automatically creates native devices and sensors for Inverters, Batteries, PV Links, and the REbus Beacon in Home Assistant (`sensor.*`, `select.*`).
- **Web Explorer with Ingress**: Browse all raw and compound SunSpec points, monitor live energy flows (Solar, Grid, Load, Battery), and pick which metrics expose to Home Assistant. Runs embedded in the Home Assistant sidebar via Ingress or standalone on port `5555`.
- **System Operating Mode Control**: Change operational modes (`SELF_SUPPLY`, `CLEAN_BACKUP`, `PRIORITY_BACKUP`, etc.) from Home Assistant or the Web Explorer with strict SunSpec enum and bounds validation.
- **Built-in SSH Tunneling**: Includes automatic SSH tunnel management and watchdog reconnection to access the Beacon's internal Modbus TCP (port 502) and telemetry broker.
- **Telemetry Correlation & Comparison**: Live side-by-side comparison between MQTT protobuf pushes and polled SunSpec Modbus registers, plus unrecognized field detection.
- **Simulation / Mock Mode**: Full offline simulation mode (`--mock`) for development and testing without physical hardware.

---

## Installation Options

You can run this project in two primary ways:
1. [**Home Assistant Add-on**](#option-1-home-assistant-add-on-recommended) (Recommended for Home Assistant OS / Supervised).
2. [**Local / Standalone Environment**](#option-2-local--standalone-installation) (Python venv, CLI, or Systemd service).

---

### Option 1: Home Assistant Add-on (Recommended)

If you run **Home Assistant OS** or **Home Assistant Supervised**, running as an Add-on provides automatic lifecycle management, direct Mosquitto broker integration, persistent configuration, and one-click sidebar access via Home Assistant Ingress.

#### Method A: Via Home Assistant Add-on Store (Repository)
1. In Home Assistant, navigate to **Settings** > **Add-ons** > **Add-on Store**.
2. Click the three dots menu (**⋮**) in the upper right corner and select **Repositories**.
3. Add the repository URL:
   ```text
   https://github.com/edalquist/pwrcell_sunspec
   ```
4. Reload the page, locate **Generac PWRcell** in the store, and click **Install**.

#### Method B: Local Add-on (Direct Copy / Development)
1. Using the **Advanced SSH & Web Terminal** or **Samba** add-on on your Home Assistant host, navigate to the `/addons` directory:
   ```bash
   cd /addons
   git clone https://github.com/edalquist/pwrcell_sunspec.git pwrcell
   ```
2. In Home Assistant, go to **Settings** > **Add-ons** > **Add-on Store**.
3. Click the menu (**⋮**) > **Check for updates**.
4. Scroll to the **Local add-ons** section, select **Generac PWRcell**, and click **Install**.

#### Add-on Configuration
In the add-on's **Configuration** tab in Home Assistant, set your parameters:

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `beacon_host` | string | `192.168.0.73` | IP address or hostname of your Generac Beacon on your local LAN. |
| `beacon_port` | integer | `22` | SSH port on the Beacon (default: `22`). |
| `beacon_user` | string | `root` | SSH user for Beacon connection. |
| `ssh_key` | password | `""` | *(Recommended)* Paste your SSH private key text directly into this field. |
| `ssh_key_file` | string | `"/share/pwrcell_ssh_key"` | Alternative path to an SSH private key file in `/share`. |
| `mqtt_host` | string | `"core-mosquitto"` | Hostname of your Home Assistant MQTT broker (`core-mosquitto` for Mosquitto add-on). |
| `mqtt_port` | integer | `1883` | MQTT broker port. |
| `mqtt_username` | string | `""` | MQTT username (optional if using anonymous/local auth). |
| `mqtt_password` | password | `""` | MQTT password. |
| `poll_rate` | integer | `12` | Telemetry Modbus polling interval (seconds). |
| `config_poll_interval` | integer | `45` | Sync interval for physical front-panel keypad changes (seconds). |
| `slow_poll_interval` | integer | `300` | Diagnostics and accumulator polling interval (seconds). |
| `enable_web_explorer` | boolean | `true` | Enable Web Explorer with Home Assistant Ingress sidebar integration. |
| `mock_mode` | boolean | `false` | Set to `true` to test against mock fixtures without connecting to hardware. |

Click **Save**, then on the **Info** tab, toggle **Show in sidebar** and click **Start**.

---

### Option 2: Local / Standalone Installation

For local development, standalone servers, Proxmox LXC containers, or dedicated Linux boxes.

#### 1. Prerequisites
- Python 3.11+
- SSH access to your Generac Beacon with an SSH private key.

#### 2. Clone and Setup Environment
```bash
git clone https://github.com/edalquist/pwrcell_sunspec.git
cd pwrcell_sunspec

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 3. Configuration
Copy the example configuration to `config/pwrcell.yaml`:
```bash
cp config/pwrcell.example.yaml config/pwrcell.yaml
```

Edit `config/pwrcell.yaml` with your parameters:
```yaml
testing: false
poll_rate: 12
config_poll_interval: 45
slow_poll_interval: 300
enable_polling: true
log_level: INFO

pwrcell:
  ssh_tunnel:
    host: 192.168.0.73
    port: 22
    username: root
    identity_file: /path/to/your/ssh_key

mqtt:
  client_name: pwrcell-ha
  host: 192.168.0.72  # Home Assistant IP or MQTT Broker host
  port: 1883
  username: mqtt-user
  password: your-password
```

#### 4. Running the CLI & Services

- **Launch Web Explorer UI**:
  ```bash
  python main.py explore --host 0.0.0.0 --port 5555
  # Or test with the built-in simulator:
  python main.py explore --mock
  ```
  Open `http://localhost:5555` in your browser.

- **Run Combined Service (MQTT Bridge + Web UI)**:
  ```bash
  python main.py service --host 0.0.0.0 --port 5555
  ```

- **Run MQTT Bridge Daemon Only (Headless)**:
  ```bash
  python main.py run
  ```

- **Live Telemetry vs Modbus Comparison**:
  ```bash
  python main.py compare
  ```

- **Change Operating Mode via CLI**:
  ```bash
  python main.py set-mode CLEAN_BACKUP
  python main.py set-mode SELF_SUPPLY
  python main.py set-mode PRIORITY_BACKUP
  ```

- **Show System Status Summary**:
  ```bash
  python main.py status
  ```

- **Scan Modbus Slave IDs**:
  ```bash
  python main.py scan --start 1 --end 50
  ```

---

### Option 3: Systemd Daemon Service (Linux / LXC)

To run as a systemd background service on a standalone Linux host:

Create `/etc/systemd/system/pwrcell.service`:
```ini
[Unit]
Description=Generac PWRcell Home Assistant Gateway & Web Explorer
After=syslog.target network.target

[Service]
Type=simple
WorkingDirectory=/opt/pwrcell_sunspec
ExecStart=/opt/pwrcell_sunspec/.venv/bin/python /opt/pwrcell_sunspec/main.py service --host 0.0.0.0 --port 5555
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable pwrcell.service
sudo systemctl start pwrcell.service
sudo systemctl status pwrcell.service
```

*(Note: If you prefer using an external systemd SSH tunnel instead of the built-in tunnel manager, point `pwrcell.ssh_tunnel.host` in `pwrcell.yaml` to `127.0.0.1` and your local forwarded port).*

---

## Managing Home Assistant Entities in Web Explorer

1. Open the Web Explorer (via the Home Assistant sidebar or at `http://<host>:5555`).
2. Select your device from the left panel.
3. Check or uncheck points under the **HA** column to expose or hide metrics in Home Assistant.
4. Click **Select Recommended** to auto-select standard home energy metrics (Solar Power, Grid Power, Home Load, Battery SOC/Power, System Mode).
5. Click **Preview HA** to view the generated MQTT Discovery payload.
6. Click **Save HA Config**:
   - Selections are saved persistently to `config/ha_config.yaml` (or `/data/ha_config.yaml` inside the add-on).
   - The bridge dynamically updates Home Assistant over MQTT in real time without needing a service restart. Newly selected entities appear immediately in **Settings** > **Devices & Services** > **MQTT**, and deselected entities are automatically removed.

---

## Testing

Run the automated unit test suite:
```bash
./.venv/bin/python -m unittest discover tests
```