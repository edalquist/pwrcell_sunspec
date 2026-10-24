"""Poller status/trigger and field write REST routes."""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, Response, jsonify, request

from ...client import PwrcellClient
from ...ha import (
    generate_discovery_payload,
    get_recommended_field_keys,
    is_field_selected,
    load_ha_config,
    qualify_legacy_ha_config,
    save_ha_config,
)

logger = logging.getLogger(__name__)


def create_blueprint(client: PwrcellClient) -> Blueprint:
    bp = Blueprint("control", __name__)

    @bp.route("/api/poller/status")
    def get_poller_status():
        status = client.poller.to_dict()
        status["initial_poll_running"] = getattr(client, "is_initial_poll_running", False)
        return jsonify(status)

    @bp.route("/api/poller/trigger", methods=["POST"])
    def trigger_poller():
        body = request.get_json() or {}
        tier = body.get("tier", "config")
        try:
            client.poller.trigger_sync(tier)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        return jsonify({
            "success": True,
            "tier": tier,
            "status": client.poller.to_dict(),
        })

    @bp.route("/api/fields/write", methods=["POST"])
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

    return bp
