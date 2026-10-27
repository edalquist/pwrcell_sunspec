"""Device, field and overview REST routes."""

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


def _filter_ha_selected_for_device(ha_selected, serial_number: str) -> set:
    clean_sn = (serial_number or "").strip().upper()
    dev_keys = set()
    for k in (ha_selected or []):
        if not k:
            continue
        k_str = str(k).strip()
        if ":" in k_str:
            sn_part, field_part = k_str.split(":", 1)
            if sn_part.strip().upper() == clean_sn:
                dev_keys.add(field_part.strip())
                dev_keys.add(k_str)
        else:
            dev_keys.add(k_str)
    return dev_keys


def create_blueprint(client: PwrcellClient) -> Blueprint:
    bp = Blueprint("devices", __name__)

    @bp.route("/api/overview")
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
            from ...controls import SUNSPEC_SYS_MD_NAMES
            mode = SUNSPEC_SYS_MD_NAMES.get(mode, f"MODE_{mode}")

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
            "initial_poll_running": getattr(client, "is_initial_poll_running", False),
            "ha_selected_count": len(ha_selected),
            "grid_power_w": grid_w,
            "solar_power_w": solar_w,
            "load_power_w": load_w,
            "battery_power_w": bat_w,
            "battery_soc": soc,
            "battery_soh": soh,
            "system_mode": mode,
        })

    @bp.route("/api/devices")
    def get_devices():
        devices_list = [dev.to_dict(catalog=client.catalog) for dev in client.state.get_devices_snapshot()]
        # Sort so beacon, inverter, battery come first, then pv_links, icm
        sort_order = {"rebus_beacon": 1, "inverter": 2, "battery": 3, "pv_link": 4, "icm": 5}
        devices_list.sort(key=lambda d: (sort_order.get(d["device_type"], 99), d["serial_number"]))
        return jsonify(devices_list)

    @bp.route("/api/devices/rescan", methods=["POST"])
    def rescan_devices():
        body = request.get_json(silent=True) or {}
        start = int(body.get("start", 1))
        end = int(body.get("end", 100))
        count = client.rescan_devices(start=start, end=end)
        devices_list = [dev.to_dict(catalog=client.catalog) for dev in client.state.get_devices_snapshot()]
        return jsonify({"success": True, "discovered_count": count, "devices": devices_list})

    @bp.route("/api/devices/<serial_number>")
    def get_device_details(serial_number: str):
        dev = client.state.get_device(serial_number)
        if not dev:
            return jsonify({"error": "Device not found"}), 404

        refresh_arg = request.args.get("refresh", "").lower()
        if refresh_arg in ("1", "true", "config", "all", "models") and client.modbus and dev.slave_id is not None:
            if refresh_arg in ("all", "models"):
                client.poller.poll_device_all_models(dev.slave_id, dev.serial_number)
            else:
                with client.poller._cond:
                    target_models = set(client.poller.config_models.get(dev.device_type, []))
                    if refresh_arg in ("1", "true"):
                        target_models.update(client.poller.fast_models.get(dev.device_type, []))
                for mid in target_models:
                    client.poller.poll_device_model(dev.slave_id, dev.serial_number, mid)

        fields_dict = dev.serialize_fields()
        compound_views = [c.to_dict() for c in client.state.get_compound_views(serial_number)]
        ha_selected = set(load_ha_config())
        clean_sn = (serial_number or "").strip().upper()
        dev_ha_selected = _filter_ha_selected_for_device(ha_selected, clean_sn)
        unified_groups = [g.to_dict() for g in client.state.get_unified_fields(serial_number, ha_selected_keys=dev_ha_selected)]

        return jsonify({
            **dev.to_dict(catalog=client.catalog),
            "fields": fields_dict,
            "compound_fields": compound_views,
            "unified_fields": unified_groups,
        })

    @bp.route("/api/devices/<serial_number>/unified_fields")
    def get_device_unified_fields(serial_number: str):
        dev = client.state.get_device(serial_number)
        if not dev:
            return jsonify({"error": "Device not found"}), 404
        ha_selected = set(load_ha_config())
        clean_sn = (serial_number or "").strip().upper()
        dev_ha_selected = _filter_ha_selected_for_device(ha_selected, clean_sn)
        groups = client.state.get_unified_fields(serial_number, ha_selected_keys=dev_ha_selected)
        return jsonify({
            "device_sn": serial_number,
            "device_type": dev.device_type,
            "unified_fields": [g.to_dict() for g in groups],
            "total_count": len(groups),
        })

    @bp.route("/api/devices/<serial_number>/optimize_polling", methods=["POST"])
    def optimize_polling_for_device(serial_number: str):
        from ...optimizer import solve_minimal_model_set
        dev = client.state.get_device(serial_number)
        if not dev:
            return jsonify({"error": "Device not found"}), 404

        body = request.get_json() or {}
        incoming_selected = body.get("selected_keys")
        preferred_sources = body.get("preferred_sources", {})

        clean_sn = (serial_number or "").strip().upper()
        raw_selected = set(incoming_selected) if incoming_selected is not None else set(load_ha_config())
        dev_ha_selected = _filter_ha_selected_for_device(raw_selected, clean_sn)

        groups = client.state.get_unified_fields(
            serial_number,
            preferred_sources=preferred_sources,
            ha_selected_keys=dev_ha_selected,
        )

        selected_items = {}
        for g in groups:
            qual_id = f"{clean_sn}:{g.id}"
            if g.is_selected or g.id in dev_ha_selected or qual_id in dev_ha_selected:
                cand_sources = set()
                for s in g.sources:
                    if s.source_type == "MQTT":
                        cand_sources.add("MQTT")
                    elif s.model_id is not None:
                        cand_sources.add(s.model_id)
                selected_items[g.id] = cand_sources

        # Determine all source field keys already covered by selected unified groups
        covered_field_keys = {
            s.field_key
            for g_id in selected_items
            for g in groups if g.id == g_id
            for s in g.sources
        }

        # Also capture any specific raw field keys selected for this device that are not part of an already selected group
        for k in dev_ha_selected:
            clean_k = k.split(":", 1)[-1] if ":" in k else k
            if clean_k in dev.fields and clean_k not in covered_field_keys and clean_k not in selected_items:
                f = dev.fields[clean_k]
                if f.model_id:
                    selected_items.setdefault(clean_k, set()).add(f.model_id)

        pinned_models = {}
        for g_id, pref_key in preferred_sources.items():
            for g in groups:
                if g.id == g_id or g.concept_key == g_id:
                    for s in g.sources:
                        is_match = (
                            s.field_key == pref_key
                            or pref_key in (s.source_id, f"M{s.model_id}", str(s.model_id))
                            or (s.model_id and f"model_{s.model_id}" in pref_key)
                            or (s.name.lower() == pref_key.split(".")[-1].lower() and s.model_id and str(s.model_id) in pref_key)
                        )
                        if is_match:
                            pinned_models[g.id] = "MQTT" if s.source_type == "MQTT" else (s.model_id or pref_key)
                            break

        opt_res = solve_minimal_model_set(
            items=selected_items,
            pinned_sources=pinned_models,
            allow_mqtt=True,
        )

        all_models = set(dev.supported_models)
        for f in dev.fields.values():
            if f.model_id:
                all_models.add(f.model_id)

        models_avoided = sorted(list(all_models - set(opt_res.minimal_models)))

        # Synchronize groups with opt_res.assignments and opt_res.minimal_models
        polled_models = set(opt_res.minimal_models)
        for g in groups:
            for s in g.sources:
                s.is_optimal = False
                s.is_pinned = False

            if g.preferred_source_key:
                for s in g.sources:
                    if s.field_key == g.preferred_source_key:
                        s.is_pinned = True
                        s.is_optimal = True
                        g.active_source_key = s.field_key
                        g.latest_value = s.value
                        g.raw_value = s.raw_value
                        g.latest_source = s.source_id
                        break
                continue

            chosen = opt_res.assignments.get(g.id)
            matched_src = None
            if chosen is not None:
                for s in g.sources:
                    if (chosen == "MQTT" and s.source_type == "MQTT") or (s.model_id == chosen):
                        matched_src = s
                        break
            elif polled_models:
                for s in g.sources:
                    if (s.source_type == "MQTT" and "MQTT" in polled_models) or (s.model_id in polled_models):
                        matched_src = s
                        break

            if not matched_src and g.sources:
                matched_src = g.sources[0]

            if matched_src:
                matched_src.is_optimal = True
                matched_src.is_primary = True
                g.active_source_key = matched_src.field_key
                g.primary_source_key = matched_src.field_key
                g.latest_value = matched_src.value
                g.raw_value = matched_src.raw_value
                g.latest_source = matched_src.source_id

            # Also identify the optimal SunSpec candidate among Modbus sources for comparison/fallback
            mb_sources = [s for s in g.sources if s.source_type != "MQTT"]
            if mb_sources and not any(s.is_optimal for s in mb_sources):
                from ...optimizer import get_default_favored_models
                favored = get_default_favored_models()
                best_mb = min(
                    mb_sources,
                    key=lambda s: (0 if s.model_id in polled_models else 1, favored.get(s.model_id or 0, 1.0))
                )
                best_mb.is_optimal = True

        return jsonify({
            "device_sn": serial_number,
            "minimal_models": opt_res.minimal_models,
            "assignments": opt_res.assignments,
            "models_avoided": models_avoided,
            "unified_fields": [g.to_dict() for g in groups],
            "stats": {
                **opt_res.stats,
                "all_device_models_count": len(all_models),
                "models_avoided_count": len(models_avoided),
            },
        })

    @bp.route("/api/devices/<serial_number>/field_details")
    @bp.route("/api/devices/<serial_number>/fields/<path:field_key>/modbus_details")
    def get_field_modbus_details(serial_number: str, field_key: Optional[str] = None):
        target_key = field_key or request.args.get("field_key")
        if not target_key or target_key == "undefined":
            return jsonify({"error": "A valid field_key parameter is required"}), 400
        details = client.state.get_field_modbus_details(serial_number, target_key)
        if not details:
            return jsonify({"error": f"Field '{target_key}' not found on device '{serial_number}'"}), 404
        return jsonify(details)

    @bp.route("/api/devices/<serial_number>/poll_all", methods=["POST"])
    def poll_all_device_models(serial_number: str):
        dev = client.state.get_device(serial_number)
        if not dev:
            return jsonify({"error": "Device not found"}), 404
        if not client.modbus or dev.slave_id is not None:
            pass
        if not client.modbus or dev.slave_id is None:
            return jsonify({"success": True, "count": 0, "message": "No Modbus connection or slave ID"})

        count = client.poller.poll_device_all_models(dev.slave_id, dev.serial_number)
        return jsonify({"success": True, "count": count, "field_count": len(dev.fields)})

    @bp.route("/api/fields")
    def get_all_fields():
        all_fields = []
        for dev in client.state.get_devices_snapshot():
            all_fields.extend(dev.serialize_fields().values())
            for c in client.state.get_compound_views(dev.serial_number):
                all_fields.append(c.to_dict())
        return jsonify(all_fields)

    return bp
