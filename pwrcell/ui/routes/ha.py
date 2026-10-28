"""Home Assistant entity configuration REST routes."""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, Response, jsonify, request

from ...client import PwrcellClient
from ...ha import (
    generate_discovery_payload,
    generate_gateway_discovery_payload,
    get_recommended_field_keys,
    is_field_selected,
    load_ha_category_overrides,
    load_ha_config,
    qualify_legacy_ha_config,
    reset_ha_config_to_defaults,
    save_ha_category_override,
    save_ha_config,
)

logger = logging.getLogger(__name__)


def create_blueprint(client: PwrcellClient) -> Blueprint:
    bp = Blueprint("ha", __name__)

    @bp.route("/api/ha/config", methods=["GET", "POST"])
    def handle_ha_config():
        if request.method == "POST":
            body = request.get_json() or {}
            incoming = body.get("selected_fields", [])
            dev_sn = body.get("device_serial")
            dev_sns = body.get("device_serials")
            merge = body.get("merge", False)

            target_serials: set[str] = set()
            if dev_sns and isinstance(dev_sns, list):
                target_serials.update(str(s).strip().upper() for s in dev_sns if s)
            if dev_sn:
                target_serials.add(str(dev_sn).strip().upper())

            if merge and target_serials:
                existing = load_ha_config()
                existing = qualify_legacy_ha_config(existing, client.state)

                # Keep all fields from devices not in target_serials
                merged = set()
                target_dev_types = set()
                for tsn in target_serials:
                    for d in client.state.devices.values():
                        if d.serial_number.strip().upper() == tsn:
                            target_dev_types.add(d.device_type)
                            break

                for k in existing:
                    if ":" in k:
                        sn_part, _ = k.split(":", 1)
                        if sn_part.strip().upper() not in target_serials:
                            merged.add(k)
                    else:
                        dot_idx = k.find(".")
                        k_dev_type = k[:dot_idx] if dot_idx != -1 else ""
                        if k_dev_type not in target_dev_types:
                            merged.add(k)

                # Add incoming fields
                qualified_incoming = qualify_legacy_ha_config(incoming, client.state)
                for k in qualified_incoming:
                    merged.add(k)

                final_selected = sorted(list(merged))
            else:
                final_selected = sorted(list(set(qualify_legacy_ha_config(incoming, client.state))))

            cat_overrides = body.get("category_overrides")
            save_ha_config(final_selected, category_overrides=cat_overrides)
            if hasattr(client, "bridge") and client.bridge:
                try:
                    client.bridge.reload_config_and_republish()
                except Exception as e:
                    logger.warning("Failed dynamically updating HA bridge discovery: %s", e)
            return jsonify({
                "success": True,
                "count": len(final_selected),
                "selected_fields": final_selected,
                "category_overrides": load_ha_category_overrides(),
            })
        else:
            selected = load_ha_config()
            qualified = qualify_legacy_ha_config(selected, client.state)
            if set(qualified) != set(selected):
                save_ha_config(qualified)
            return jsonify({
                "selected_fields": qualified,
                "category_overrides": load_ha_category_overrides(),
            })

    @bp.route("/api/ha/category_override", methods=["POST"])
    def set_ha_category_override():
        try:
            body = request.get_json() or {}
            dev_sn = body.get("device_serial")
            field_key = body.get("field_key")
            category = body.get("category")
            if not field_key:
                return jsonify({"error": "field_key is required"}), 400

            overrides = save_ha_category_override(dev_sn, field_key, category)
            if hasattr(client, "bridge") and client.bridge:
                try:
                    client.bridge.reload_config_and_republish()
                except Exception as e:
                    logger.warning("Failed dynamically updating HA bridge discovery: %s", e)

            return jsonify({
                "success": True,
                "device_serial": dev_sn,
                "field_key": field_key,
                "category": category,
                "category_overrides": overrides,
            })
        except Exception as e:
            logger.error("Failed saving HA category override: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/ha/reset_defaults", methods=["POST"])
    def reset_ha_defaults():
        try:
            from ...bridge import get_default_published_topics_path

            body = request.get_json(silent=True) or {}
            purge_mqtt = body.get("purge_mqtt", True)

            qualified = reset_ha_config_to_defaults(client.state)

            cache_path = get_default_published_topics_path()
            if cache_path.exists():
                try:
                    cache_path.unlink()
                except Exception as e:
                    logger.warning("Could not delete cache file %s: %s", cache_path, e)

            purged_topics = []
            if purge_mqtt:
                try:
                    from ...tools.clean_discovery import purge_pwrcell_discovery_topics
                    m_cfg = getattr(getattr(client, "config", None), "mqtt", None)
                    pfx = getattr(getattr(client, "bridge", None), "discovery_prefix", "homeassistant") or "homeassistant"
                    purged_topics = purge_pwrcell_discovery_topics(
                        broker_host=getattr(m_cfg, "host", None) or "127.0.0.1",
                        broker_port=getattr(m_cfg, "port", None) or 1883,
                        username=getattr(m_cfg, "username", None),
                        password=getattr(m_cfg, "password", None),
                        discovery_prefix=pfx,
                        clear_cache=True,
                    )
                except Exception as e:
                    logger.warning("Failed purging MQTT discovery during reset: %s", e)

            if hasattr(client, "bridge") and client.bridge:
                try:
                    client.bridge._published_discovery_topics.clear()
                    client.bridge.reload_config_and_republish()
                except Exception as e:
                    logger.warning("Failed republishing HA discovery during reset: %s", e)

            return jsonify({
                "success": True,
                "count": len(qualified),
                "selected_fields": qualified,
                "purged_count": len(purged_topics),
            })
        except Exception as e:
            logger.error("Failed resetting HA config to defaults: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/ha/clean_discovery", methods=["POST"])
    def clean_ha_discovery():
        try:
            from ...tools.clean_discovery import purge_pwrcell_discovery_topics
            from ...bridge import get_default_published_topics_path

            m_cfg = getattr(getattr(client, "config", None), "mqtt", None)
            pfx = getattr(getattr(client, "bridge", None), "discovery_prefix", "homeassistant") or "homeassistant"
            purged_topics = purge_pwrcell_discovery_topics(
                broker_host=getattr(m_cfg, "host", None) or "127.0.0.1",
                broker_port=getattr(m_cfg, "port", None) or 1883,
                username=getattr(m_cfg, "username", None),
                password=getattr(m_cfg, "password", None),
                discovery_prefix=pfx,
                clear_cache=True,
            )

            # Republish currently selected active fields
            if hasattr(client, "bridge") and client.bridge:
                try:
                    client.bridge._published_discovery_topics.clear()
                    client.bridge.publish_discovery()
                except Exception as e:
                    logger.warning("Failed republishing active discovery: %s", e)

            return jsonify({
                "success": True,
                "purged_count": len(purged_topics),
                "purged_topics": purged_topics,
            })
        except Exception as e:
            logger.error("Failed cleaning MQTT discovery: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/ha/recommended")
    def get_ha_recommended():
        sn = request.args.get("serial_number")
        recommended = get_recommended_field_keys(client.state, device_sn=sn)
        return jsonify({"recommended_fields": recommended})

    @bp.route("/api/ha/copy_device_selections", methods=["POST"])
    def copy_device_selections():
        body = request.get_json() or {}
        source_sn = body.get("source_serial")
        if not source_sn:
            return jsonify({"error": "source_serial is required"}), 400

        source_dev = client.state.devices.get(source_sn)
        if not source_dev:
            clean_s = source_sn.strip().upper()
            for d in client.state.devices.values():
                if d.serial_number.strip().upper() == clean_s:
                    source_dev = d
                    break
        if not source_dev:
            return jsonify({"error": f"Device {source_sn} not found"}), 404

        clean_src_sn = source_dev.serial_number.strip().upper()
        target_type = body.get("target_device_type") or source_dev.device_type

        # Use in-flight selected_fields if provided, otherwise load from file
        selected = body.get("selected_fields")
        if selected is None:
            selected = load_ha_config()

        # Find all fields selected for source_dev
        src_field_keys = []
        for k in selected:
            if ":" in k:
                sn_part, field_part = k.split(":", 1)
                if sn_part.strip().upper() == clean_src_sn:
                    src_field_keys.append(field_part)
            else:
                if k.startswith(f"{source_dev.device_type}."):
                    src_field_keys.append(k)

        peer_devices = [d for d in client.state.devices.values() if d.device_type == target_type]
        peer_serials = {d.serial_number.strip().upper() for d in peer_devices}

        updated_selected = set()
        for k in selected:
            if ":" in k:
                sn_part, _ = k.split(":", 1)
                if sn_part.strip().upper() not in peer_serials:
                    updated_selected.add(k)
            else:
                if not k.startswith(f"{target_type}."):
                    updated_selected.add(k)

        # Apply src_field_keys to all peer devices
        for peer in peer_devices:
            peer_sn = peer.serial_number.strip().upper()
            for f_key in src_field_keys:
                updated_selected.add(f"{peer_sn}:{f_key}")

        new_list = sorted(list(updated_selected))
        if body.get("save", False):
            save_ha_config(new_list)
            if hasattr(client, "bridge") and client.bridge:
                try:
                    client.bridge.reload_config_and_republish()
                except Exception as e:
                    logger.warning("Failed dynamically updating HA bridge discovery: %s", e)

        return jsonify({
            "success": True,
            "source_serial": clean_src_sn,
            "target_device_type": target_type,
            "peer_count": len(peer_devices),
            "copied_fields_count": len(src_field_keys),
            "selected_fields": new_list,
        })

    @bp.route("/api/ha/export_defaults", methods=["GET", "POST"])
    def export_ha_defaults():
        from flask import Response
        from ...ha import export_default_config, generate_ha_default_config
        as_download = request.args.get("download", "").lower() in ("true", "1", "yes")

        if request.method == "POST":
            try:
                body = request.get_json(silent=True) or {}
                target_path = body.get("target_path")
                keys = export_default_config(target_path=target_path)
                return jsonify({
                    "success": True,
                    "count": len(keys),
                    "default_fields": keys,
                    "message": f"Successfully exported {len(keys)} generic field IDs to ha_default_config.yaml",
                })
            except Exception as e:
                logger.error("Failed exporting default HA config: %s", e)
                return jsonify({"error": str(e)}), 500

        try:
            res = generate_ha_default_config()
            if as_download:
                return Response(
                    res["yaml"],
                    mimetype="text/yaml",
                    headers={"Content-Disposition": "attachment; filename=ha_default_config.yaml"},
                )
            return jsonify({
                "status": "ok",
                "filename": "ha_default_config.yaml",
                "yaml": res["yaml"],
                "count": len(res.get("selected_fields", [])),
                "data": res.get("data"),
            })
        except Exception as e:
            logger.error("Failed generating default HA config: %s", e)
            return jsonify({"status": "error", "error": str(e)}), 500

    @bp.route("/api/ha/preview")
    def get_ha_preview():
        selected = load_ha_config()
        cat_overrides = load_ha_category_overrides()
        preview_list = []
        gateway = client.state.get_beacon() or client.state.get_inverter()

        # Include parent gateway device node so via_device is never orphaned
        if gateway:
            gw_payload_info = generate_gateway_discovery_payload(gateway)
            preview_list.append({
                "field_key": f"{gateway.device_type}.status",
                "device_serial": gateway.serial_number,
                "device_name": gateway.model_name,
                "field_label": "Gateway Status",
                "config_topic": gw_payload_info["config_topic"],
                "state_topic": gw_payload_info["state_topic"],
                "command_topic": gw_payload_info["command_topic"],
                "platform": gw_payload_info["platform"],
                "payload": gw_payload_info["payload"],
            })

        for dev in client.state.get_devices_snapshot():
            # Include compound fields
            for c_view in client.state.get_compound_views(dev.serial_number):
                if is_field_selected(c_view.key, dev.serial_number, selected, c_view.mqtt_key):
                    payload_info = generate_discovery_payload(c_view, dev, gateway_device=gateway, category_overrides=cat_overrides)
                    preview_list.append({
                        "field_key": c_view.key,
                        "device_serial": dev.serial_number,
                        "device_name": dev.model_name,
                        "field_label": c_view.label,
                        "config_topic": payload_info["config_topic"],
                        "state_topic": payload_info["state_topic"],
                        "command_topic": payload_info["command_topic"],
                        "platform": payload_info["platform"],
                        "payload": payload_info["payload"],
                    })

            # Include raw fields
            for f_key, f in list(dev.fields.items()):
                if is_field_selected(f_key, dev.serial_number, selected):
                    payload_info = generate_discovery_payload(f, dev, gateway_device=gateway, category_overrides=cat_overrides)
                    preview_list.append({
                        "field_key": f_key,
                        "device_serial": dev.serial_number,
                        "device_name": dev.model_name,
                        "field_label": f.label,
                        "config_topic": payload_info["config_topic"],
                        "state_topic": payload_info["state_topic"],
                        "command_topic": payload_info["command_topic"],
                        "platform": payload_info["platform"],
                        "payload": payload_info["payload"],
                    })

        return jsonify(preview_list)

    return bp
