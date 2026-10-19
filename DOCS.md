# Generac PWRcell Home Assistant Add-on

Integrates your Generac PWRcell system (Inverter, Battery, PV Links, REbus Beacon) directly into Home Assistant via SunSpec Modbus TCP and MQTT, with an integrated **Web Explorer** accessible via Home Assistant Ingress.

---

## Features

- **Automatic MQTT Discovery**: Automatically registers your PWRcell Inverter, Battery, PV Links, and REbus Beacon in Home Assistant's native Device & Entity Registry.
- **Embedded Web Explorer (Ingress)**: View live power flow, compare Modbus registers with push telemetry, inspect raw SunSpec points, and trigger manual syncs directly from the Home Assistant sidebar.
- **Control System Modes**: Select and switch system operating modes (`SELF_SUPPLY`, `CLEAN_BACKUP`, `PRIORITY_BACKUP`, etc.) directly from Home Assistant dashboards or the Web Explorer with full enum validation.
- **Automatic SSH Tunneling**: Automatically opens and maintains an SSH tunnel to your Generac Beacon to access the internal Modbus TCP and telemetry streams.
- **Persistent Configuration**: Selected entities and discovered Modbus devices are preserved in Home Assistant's `/data` partition across add-on updates.

---

## Installation

### Option 1: Via Home Assistant Add-on Store (Recommended)

1. In Home Assistant, navigate to **Settings** > **Add-ons** > **Add-on Store**.
2. Click the three dots (menu) in the top right corner and select **Repositories**.
3. Add your repository URL:
   ```text
   https://github.com/edalquist/pwrcell_sunspec
   ```
4. Refresh or reload the Add-on Store.
5. Search for **Generac PWRcell** and click **Install**.

### Option 2: Local Add-on (For Development)

1. Copy or clone this repository into `/addons/pwrcell` on your Home Assistant OS host (using the Samba or SSH & Web Terminal add-on).
2. Go to **Settings** > **Add-ons** > **Add-on Store** > **Check for updates**.
3. Under the **Local add-ons** section, click **Generac PWRcell** and click **Install**.

---

## Configuration

In the Add-on **Configuration** tab, customize the following settings:

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `beacon_host` | string | `192.168.0.73` | IP address or hostname of your Generac Beacon on the local network. |
| `beacon_port` | integer | `22` | SSH port on the Generac Beacon (default: `22`). |
| `beacon_user` | string | `root` | SSH user for connecting to the Beacon. |
| `ssh_key` | password | `""` | *(Recommended)* Paste your SSH private key (PEM/OpenSSH format) directly here. |
| `ssh_key_file` | string | `"/share/pwrcell_ssh_key"` | Alternative path to an SSH private key file stored in `/share`. |
| `mqtt_host` | string | `"core-mosquitto"` | Hostname of your Home Assistant MQTT broker (default `core-mosquitto` for the official Mosquitto add-on). |
| `mqtt_port` | integer | `1883` | MQTT port (default: `1883`). |
| `mqtt_username` | string | `""` | MQTT username (leave blank if anonymous or using local broker integration). |
| `mqtt_password` | password | `""` | MQTT password. |
| `poll_rate` | integer | `12` | Interval in seconds for fast telemetry Modbus polling. |
| `config_poll_interval`| integer | `45` | Interval in seconds to sync physical front-panel keypad changes. |
| `slow_poll_interval` | integer | `300` | Interval in seconds for diagnostic accumulators. |
| `enable_web_explorer` | boolean | `true` | Launch the Web Explorer UI via Home Assistant Ingress. |
| `log_level` | string | `"INFO"` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `mock_mode` | boolean | `false` | Set to `true` to run against the built-in simulator for testing without live hardware. |

---

## Web Explorer (Ingress)

When `enable_web_explorer` is enabled, click **Open Web UI** or toggle **Show in sidebar** in the add-on info panel.

The Web Explorer allows you to:
- Monitor live power gauges (Solar, Grid, Load, Battery).
- View all SunSpec register points across every device with enum symbol lookups.
- Select/deselect which metrics publish to Home Assistant MQTT Discovery using the **Select Recommended** or entity checkboxes.
- Issue real-time control commands (system mode changes, battery charge limits) with field validation.
- Inspect the live correlation comparison table between MQTT protobuf pushes and SunSpec Modbus registers.

---

## Home Assistant Entities

Once the add-on connects to the MQTT broker, the following entities are automatically created in Home Assistant under **Settings** > **Devices & Services** > **MQTT**:

- **PWRcell Inverter**:
  - `sensor.pwrcell_inverter_grid_power` (W)
  - `sensor.pwrcell_inverter_solar_power` (W)
  - `sensor.pwrcell_inverter_load_power` (W)
  - `sensor.pwrcell_inverter_system_mode`
- **PWRcell Battery**:
  - `sensor.pwrcell_battery_state_of_charge` (%)
  - `sensor.pwrcell_battery_state_of_health` (%)
  - `sensor.pwrcell_battery_battery_power` (W)
- **PWRcell Controls**:
  - `select.rebus_beacon_rebus_dir_system_operating_mode` (Interactive dropdown with `SELF_SUPPLY`, `CLEAN_BACKUP`, `PRIORITY_BACKUP`, etc.)
- **PWRcell PV Links**:
  - String power (W) and accumulated energy (kWh) per string.
