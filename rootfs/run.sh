#!/usr/bin/env bash
set -e

OPTIONS_FILE="/data/options.json"
CONFIG_FILE="/data/pwrcell.yaml"

echo "[INFO] Starting Generac PWRcell Home Assistant Add-on..."

if [ -f "$OPTIONS_FILE" ]; then
    echo "[INFO] Reading configuration from $OPTIONS_FILE..."

    BEACON_HOST=$(jq -r '.beacon_host // "192.168.0.73"' "$OPTIONS_FILE")
    BEACON_PORT=$(jq -r '.beacon_port // 22' "$OPTIONS_FILE")
    BEACON_USER=$(jq -r '.beacon_user // "root"' "$OPTIONS_FILE")
    BEACON_PASS=$(jq -r '.beacon_password // ""' "$OPTIONS_FILE")
    SSH_KEY_FILE=$(jq -r '.ssh_key_file // ""' "$OPTIONS_FILE")
    SSH_KEY=$(jq -r '.ssh_key // ""' "$OPTIONS_FILE")
    SSH_PASSPHRASE=$(jq -r '.ssh_key_passphrase // ""' "$OPTIONS_FILE")

    MQTT_HOST=$(jq -r '.mqtt_host // "core-mosquitto"' "$OPTIONS_FILE")
    MQTT_PORT=$(jq -r '.mqtt_port // 1883' "$OPTIONS_FILE")
    MQTT_USER=$(jq -r '.mqtt_username // ""' "$OPTIONS_FILE")
    MQTT_PASS=$(jq -r '.mqtt_password // ""' "$OPTIONS_FILE")
    MQTT_CLIENT_NAME=$(jq -r '.mqtt_client_name // ""' "$OPTIONS_FILE")
    if [ -z "$MQTT_CLIENT_NAME" ] || [ "$MQTT_CLIENT_NAME" = "null" ]; then
        MQTT_CLIENT_NAME="${HOSTNAME:-pwrcell-ha}"
    fi

    POLL_RATE=$(jq -r '.poll_rate // 12' "$OPTIONS_FILE")
    CONFIG_POLL_INTERVAL=$(jq -r '.config_poll_interval // 45' "$OPTIONS_FILE")
    SLOW_POLL_INTERVAL=$(jq -r '.slow_poll_interval // 300' "$OPTIONS_FILE")

    LOG_LEVEL=$(jq -r '.log_level // "INFO"' "$OPTIONS_FILE")
    MOCK_MODE=$(jq -r '.mock_mode // false' "$OPTIONS_FILE")
    ENABLE_UI=$(jq -r '.enable_web_explorer // true' "$OPTIONS_FILE")

    # Set up SSH private key
    ID_FILE=""
    python3 -m pwrcell.setup_key "$OPTIONS_FILE" || true

    if [ -f "/root/.ssh/id_rsa_pwrcell" ] && [ -s "/root/.ssh/id_rsa_pwrcell" ]; then
        ID_FILE="/root/.ssh/id_rsa_pwrcell"
    elif [ -n "$SSH_KEY_FILE" ] && [ "$SSH_KEY_FILE" != "null" ] && [ -f "$SSH_KEY_FILE" ]; then
        echo "[INFO] Using SSH key file at $SSH_KEY_FILE"
        ID_FILE="$SSH_KEY_FILE"
    elif [ -f "/share/pwrcell_ssh_key" ]; then
        echo "[INFO] Found existing key at /share/pwrcell_ssh_key"
        ID_FILE="/share/pwrcell_ssh_key"
    else
        echo "[WARNING] No SSH private key specified! SSH tunnel connection may fail unless passwordless key exists."
    fi

    # Write runtime configuration for PWRcell
    cat <<EOF > "$CONFIG_FILE"
---
testing: false
poll_rate: $POLL_RATE
config_poll_interval: $CONFIG_POLL_INTERVAL
slow_poll_interval: $SLOW_POLL_INTERVAL
enable_polling: true
log_level: "$LOG_LEVEL"
pwrcell:
  ssh_tunnel:
    host: "$BEACON_HOST"
    port: $BEACON_PORT
    username: "$BEACON_USER"
    identity_file: "$ID_FILE"
    password: "$BEACON_PASS"
    key_passphrase: "$SSH_PASSPHRASE"
mqtt:
  client_name: "$MQTT_CLIENT_NAME"
  host: "$MQTT_HOST"
  port: $MQTT_PORT
  username: "$MQTT_USER"
  password: "$MQTT_PASS"
EOF

    echo "[INFO] Successfully generated $CONFIG_FILE"
    export PWRCELL_CONFIG="$CONFIG_FILE"
fi

MOCK_ARG=""
if [ "$MOCK_MODE" = "true" ]; then
    echo "[INFO] Running in mock/simulation mode."
    MOCK_ARG="--mock"
fi

UI_ARG=""
if [ "$ENABLE_UI" = "false" ]; then
    echo "[INFO] Web Explorer disabled by configuration."
    UI_ARG="--no-ui"
fi

echo "[INFO] Launching Generac PWRcell Service (Bridge + Web Explorer Ingress)..."
exec python3 /app/main.py --log-level "${LOG_LEVEL:-INFO}" $MOCK_ARG service $UI_ARG --host 0.0.0.0 --port 5555
