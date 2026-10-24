#!/usr/bin/env bash
set -e

OPTIONS_FILE="/data/options.json"
CONFIG_FILE="/data/pwrcell.yaml"

echo "[INFO] Starting Generac PWRcell Home Assistant Add-on..."

if [ -f "$OPTIONS_FILE" ]; then
    echo "[INFO] Reading configuration from $OPTIONS_FILE..."

    LOG_LEVEL=$(jq -r '.log_level // "INFO"' "$OPTIONS_FILE")
    MOCK_MODE=$(jq -r '.mock_mode // false' "$OPTIONS_FILE")
    ENABLE_UI=$(jq -r '.enable_web_explorer // true' "$OPTIONS_FILE")

    # Safely extract SSH key and generate /data/pwrcell.yaml (mode 0600) via Python yaml.safe_dump
    python3 -m pwrcell.setup_key "$OPTIONS_FILE" "$CONFIG_FILE"
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
