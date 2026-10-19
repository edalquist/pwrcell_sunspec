"""Web Explorer API Server for Generac PWRcell (v3).

Provides REST APIs and Server-Sent Events (SSE) for the companion Web Explorer,
enabling real-time device inspection, field exploration, and Home Assistant entity configuration.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from ..client import PwrcellClient, create_client
from ..ha import (
    generate_discovery_payload,
    get_recommended_field_keys,
    load_ha_config,
    save_ha_config,
)
from ..state import StateField

logger = logging.getLogger(__name__)


def create_app(client: PwrcellClient) -> Flask:
    """Create and configure the Flask Web Explorer application."""
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="")

    # Event subscribers queue list for Server-Sent Events
    sse_queues: list[queue.Queue] = []
    sse_lock = threading.Lock()
    app.sse_queues = sse_queues  # type: ignore[attr-defined]
    app.sse_lock = sse_lock      # type: ignore[attr-defined]

    def on_field_change(field: StateField):
        event_data = {
            "type": "field_update",
            "field": field.to_dict(),
        }
        with sse_lock:
            for q in list(sse_queues):
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    pass

    def on_compound_change(c_view):
        event_data = {
            "type": "compound_update",
            "field": c_view.to_dict(),
        }
        with sse_lock:
            for q in list(sse_queues):
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    pass

    # Subscribe to state store changes and compound view updates
    client.state.subscribe(on_field_change)
    client.state.subscribe_compound(on_compound_change)

    @app.route("/")
    def index():
        return send_from_directory(str(static_dir), "index.html")

    @app.route("/api/overview")
    def get_overview():
        inv = client.state.get_inverter()
        bat = client.state.get_battery()

        # Prefer latest values from compound views
        grid_view = client.state.get_compound_view("grid_power")
        solar_view = client.state.get_compound_view("solar_power")
        bat_view = client.state.get_compound_view("battery_power")
        soc_view = client.state.get_compound_view("battery_soc")
        soh_view = client.state.get_compound_view("battery_soh")
        mode_view = client.state.get_compound_view("system_mode")

        grid_w = grid_view.latest_value if (grid_view and grid_view.latest_value is not None) else (
            inv.fields.get("inverter.live.grid_power_w").value if (inv and "inverter.live.grid_power_w" in inv.fields) else 0.0
        )
        solar_w = solar_view.latest_value if (solar_view and solar_view.latest_value is not None) else (
            inv.fields.get("inverter.live.solar_power_w").value if (inv and "inverter.live.solar_power_w" in inv.fields) else 0.0
        )
        load_w = inv.fields.get("inverter.live.load_power_w").value if (inv and "inverter.live.load_power_w" in inv.fields) else 0.0
        mode = mode_view.latest_value if (mode_view and mode_view.latest_value is not None) else (
            inv.fields.get("inverter.live.system_mode").value if (inv and "inverter.live.system_mode" in inv.fields) else "UNKNOWN"
        )
        if isinstance(mode, int):
            from ..controls import OPERATING_MODES
            inv_modes = {v: k for k, v in OPERATING_MODES.items()}
            mode = inv_modes.get(mode, f"MODE_{mode}")

        bat_w = bat_view.latest_value if (bat_view and bat_view.latest_value is not None) else (
            bat.fields.get("battery.live.battery_power_w").value if (bat and "battery.live.battery_power_w" in bat.fields) else 0.0
        )
        soc = soc_view.latest_value if (soc_view and soc_view.latest_value is not None) else (
            bat.fields.get("battery.live.state_of_charge").value if (bat and "battery.live.state_of_charge" in bat.fields) else None
        )
        soh = soh_view.latest_value if (soh_view and soh_view.latest_value is not None) else (
            bat.fields.get("battery.live.state_of_health").value if (bat and "battery.live.state_of_health" in bat.fields) else None
        )

        ha_selected = load_ha_config()

        return jsonify({
            "is_mock": client.is_mock,
            "device_count": len(client.state.devices),
            "ha_selected_count": len(ha_selected),
            "grid_power_w": grid_w,
            "solar_power_w": solar_w,
            "load_power_w": load_w,
            "battery_power_w": bat_w,
            "battery_soc": soc,
            "battery_soh": soh,
            "system_mode": mode,
        })

    @app.route("/api/devices")
    def get_devices():
        devices_list = [dev.to_dict(catalog=client.catalog) for dev in client.state.devices.values()]
        # Sort so beacon, inverter, battery come first, then pv_links, icm
        sort_order = {"rebus_beacon": 1, "inverter": 2, "battery": 3, "pv_link": 4, "icm": 5}
        devices_list.sort(key=lambda d: (sort_order.get(d["device_type"], 99), d["serial_number"]))
        return jsonify(devices_list)

    @app.route("/api/devices/<serial_number>")
    def get_device_details(serial_number: str):
        dev = client.state.devices.get(serial_number)
        if not dev:
            return jsonify({"error": "Device not found"}), 404

        refresh_arg = request.args.get("refresh", "").lower()
        if refresh_arg in ("1", "true", "config", "all", "models") and client.modbus and dev.slave_id is not None:
            if refresh_arg in ("all", "models"):
                client.poller.poll_device_all_models(dev.slave_id, dev.serial_number)
            else:
                target_models = set(client.poller.config_models.get(dev.device_type, []))
                if refresh_arg in ("1", "true"):
                    target_models.update(client.poller.fast_models.get(dev.device_type, []))
                for mid in target_models:
                    client.poller.poll_device_model(dev.slave_id, dev.serial_number, mid)

        fields_dict = {f_key: f.to_dict() for f_key, f in dev.fields.items()}
        compound_views = [c.to_dict() for c in client.state.get_compound_views(serial_number)]

        return jsonify({
            **dev.to_dict(catalog=client.catalog),
            "fields": fields_dict,
            "compound_fields": compound_views,
        })

    @app.route("/api/devices/<serial_number>/poll_all", methods=["POST"])
    def poll_all_device_models(serial_number: str):
        dev = client.state.devices.get(serial_number)
        if not dev:
            return jsonify({"error": "Device not found"}), 404
        if not client.modbus or dev.slave_id is None:
            return jsonify({"success": True, "count": 0, "message": "No Modbus connection or slave ID"})

        count = client.poller.poll_device_all_models(dev.slave_id, dev.serial_number)
        return jsonify({"success": True, "count": count, "field_count": len(dev.fields)})

    @app.route("/api/fields")
    def get_all_fields():
        all_fields = []
        for dev in client.state.devices.values():
            for f in dev.fields.values():
                all_fields.append(f.to_dict())
            for c in client.state.get_compound_views(dev.serial_number):
                all_fields.append(c.to_dict())
        return jsonify(all_fields)

    @app.route("/api/mappings", methods=["GET", "POST"])
    def handle_mappings():
        from ..mapping import MappingRegistry, TelemetryMappingDef, save_mappings
        reg = MappingRegistry.get_instance()
        if request.method == "POST":
            body = request.get_json() or {}
            mappings_raw = body.get("mappings", [])
            mappings = [TelemetryMappingDef.from_dict(d) for d in mappings_raw]
            save_mappings(mappings)
            reg.reload()
            return jsonify({"success": True, "count": len(mappings)})
        else:
            return jsonify({"mappings": [m.to_dict() for m in reg.get_all()]})

    @app.route("/api/compare")
    def get_compare():
        from ..correlator import evaluate_comparisons, log_unrecognized_proto_fields
        if not client.is_mock:
            client.poll_telemetry_models_live()
        results = evaluate_comparisons(client.state)
        unrecognized = client.get_unrecognized_proto_fields()
        log_unrecognized_proto_fields(unrecognized)
        return jsonify({
            "comparisons": [r.to_dict() for r in results],
            "unrecognized_proto_fields": unrecognized,
        })

    @app.route("/api/poller/status")
    def get_poller_status():
        return jsonify(client.poller.to_dict())

    @app.route("/api/poller/trigger", methods=["POST"])
    def trigger_poller():
        body = request.get_json() or {}
        tier = body.get("tier", "config")
        client.poller.trigger_sync(tier)
        return jsonify({
            "success": True,
            "tier": tier,
            "status": client.poller.to_dict(),
        })

    @app.route("/api/fields/write", methods=["POST"])
    def write_field():
        body = request.get_json() or {}
        field_key = body.get("field_key")
        value = body.get("value")

        if not field_key:
            return jsonify({"error": "field_key is required"}), 400

        try:
            confirmed_val = client.controls.write_field(field_key, value)
            return jsonify({"success": True, "field_key": field_key, "value": confirmed_val})
        except Exception as e:
            logger.error("Failed writing field %s: %s", field_key, e)
            return jsonify({"error": str(e)}), 400

    @app.route("/api/ha/config", methods=["GET", "POST"])
    def handle_ha_config():
        if request.method == "POST":
            body = request.get_json() or {}
            selected = body.get("selected_fields", [])
            save_ha_config(selected)
            if hasattr(client, "bridge") and client.bridge:
                try:
                    client.bridge.reload_config_and_republish()
                except Exception as e:
                    logger.warning("Failed dynamically updating HA bridge discovery: %s", e)
            return jsonify({"success": True, "count": len(selected)})
        else:
            selected = load_ha_config()
            return jsonify({"selected_fields": selected})

    @app.route("/api/ha/recommended")
    def get_ha_recommended():
        recommended = get_recommended_field_keys(client.state)
        return jsonify({"recommended_fields": recommended})

    @app.route("/api/ha/preview")
    def get_ha_preview():
        selected = load_ha_config()
        preview_list = []
        gateway = client.state.get_beacon() or client.state.get_inverter()

        for dev in client.state.devices.values():
            for f_key, f in dev.fields.items():
                if f_key in selected:
                    payload_info = generate_discovery_payload(f, dev, gateway_device=gateway)
                    preview_list.append({
                        "field_key": f_key,
                        "device_name": dev.model_name,
                        "field_label": f.label,
                        "config_topic": payload_info["config_topic"],
                        "state_topic": payload_info["state_topic"],
                        "command_topic": payload_info["command_topic"],
                        "platform": payload_info["platform"],
                        "payload": payload_info["payload"],
                    })

        return jsonify(preview_list)

    @app.route("/api/stream")
    def sse_stream():
        """Server-Sent Events endpoint streaming live state updates to the browser."""
        client_queue: queue.Queue = queue.Queue(maxsize=100)
        with sse_lock:
            sse_queues.append(client_queue)

        def event_generator():
            try:
                # Initial connect ping
                yield f"data: {json.dumps({'type': 'connected'})}\n\n"
                while True:
                    try:
                        event_data = client_queue.get(timeout=15.0)
                        yield f"data: {json.dumps(event_data)}\n\n"
                    except queue.Empty:
                        # Keepalive ping
                        yield ": keepalive\n\n"
            finally:
                with sse_lock:
                    if client_queue in sse_queues:
                        sse_queues.remove(client_queue)

        return Response(
            event_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


def run_explorer(
    client: PwrcellClient,
    host: str = "0.0.0.0",
    port: int = 5555,
    debug: bool = False,
):
    """Run the Web Explorer HTTP server."""
    app = create_app(client)
    logger.info("Starting PWRcell Web Explorer at http://%s:%d", "localhost" if host == "0.0.0.0" else host, port)
    app.run(host=host, port=port, debug=debug, use_reloader=False)
