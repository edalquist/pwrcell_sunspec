"""Telemetry mapping, comparison and field-grouping REST routes."""

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
    bp = Blueprint("grouping", __name__)

    @bp.route("/api/mappings", methods=["GET", "POST"])
    def handle_mappings():
        from ...mapping import MappingRegistry, TelemetryMappingDef, save_mappings
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

    @bp.route("/api/compare")
    def get_compare():
        from ...tools.correlator import evaluate_comparisons, log_unrecognized_proto_fields
        results = evaluate_comparisons(client.state)
        unrecognized = client.get_unrecognized_proto_fields()
        log_unrecognized_proto_fields(unrecognized)

        discrepant_count = sum(
            1 for r in results
            if r.is_explicitly_grouped and (
                getattr(r, "is_discrepant", False)
                or r.status in ("DIVERGENT", "UNIT_MISMATCH", "POLARITY_MISMATCH", "SCALE_MISMATCH")
            )
        )
        exact_count = sum(1 for r in results if r.status == "EXACT")
        close_count = sum(1 for r in results if r.status == "CLOSE")
        multi_count = sum(1 for r in results if r.is_explicitly_grouped)
        single_count = sum(1 for r in results if not r.is_explicitly_grouped)
        stats = {
            "total_groups": len(results),
            "multi_source_groups": multi_count,
            "discrepancies_count": discrepant_count,
            "exact_match_count": exact_count,
            "close_match_count": close_count,
            "single_source_count": single_count,
        }

        return jsonify({
            "comparisons": [r.to_dict() for r in results],
            "stats": stats,
            "unrecognized_proto_fields": unrecognized,
        })

    @bp.route("/api/grouping/overrides")
    def get_grouping_overrides():
        from ...grouping import load_custom_groupings
        return jsonify(load_custom_groupings())

    def _resolve_device_sn(device_sn: str, field_key: str = "", concept_key: str = "") -> str:
        clean_sn = (device_sn or "").strip().upper()
        if clean_sn and clean_sn in client.state.devices:
            return clean_sn

        # 1. Match by field_key in device fields
        if field_key:
            clean_fk = field_key.strip()
            for dev in client.state.devices.values():
                if clean_fk in dev.fields:
                    return dev.serial_number

            # Check prefix match (e.g. 'inverter.model_64208.CTPow' -> device_type == 'inverter')
            if "." in clean_fk:
                prefix = clean_fk.split(".")[0].lower()
                matching = [d for d in client.state.devices.values() if d.device_type.lower() == prefix]
                if len(matching) == 1:
                    return matching[0].serial_number

        # 2. Match by concept_key
        if concept_key:
            from ...optimizer import group_device_fields
            clean_ck = concept_key.strip()
            for dev in client.state.devices.values():
                groups = group_device_fields(dev)
                if any(g.concept_key == clean_ck or g.id == clean_ck for g in groups):
                    return dev.serial_number

        # 3. Fallback if single device
        if len(client.state.devices) == 1:
            return next(iter(client.state.devices.values())).serial_number

        # 4. Fallback if inverter exists and field starts with inverter or system
        if field_key and field_key.startswith(("inverter.", "system.")):
            inv = next((d for d in client.state.devices.values() if d.device_type == "inverter"), None)
            if inv:
                return inv.serial_number

        return clean_sn

    @bp.route("/api/grouping/override", methods=["POST"])
    def set_grouping_override():
        from ...grouping import set_field_grouping_override
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        field_key = data.get("field_key", "")
        target_concept = data.get("target_concept")
        custom_label = data.get("custom_label")
        transform = data.get("transform")

        device_sn = _resolve_device_sn(device_sn, field_key=field_key)
        if not device_sn or not field_key:
            return jsonify({"error": "device_sn and field_key are required"}), 400
        
        if target_concept and str(target_concept).strip().lower() not in ("", "null", "none", "standalone", "ungrouped"):
            clean_tc = str(target_concept).strip()
            dev = client.state.devices.get(device_sn)
            if dev:
                from ...optimizer import group_device_fields
                from ...tools.recommender import are_from_same_model
                incoming_f = dev.fields.get(field_key)
                if incoming_f:
                    existing_groups = group_device_fields(dev)
                    target_grp = next(
                        (g for g in existing_groups if g.concept_key == clean_tc or g.id.endswith(f".concept.{clean_tc}")),
                        None,
                    )
                    if target_grp:
                        for s in target_grp.sources:
                            if s.field_key != field_key and are_from_same_model(s, incoming_f):
                                m_id = getattr(incoming_f, "model_id", None)
                                m_name = f"Model {m_id}" if m_id else getattr(incoming_f, "model_name", "the same model")
                                return jsonify({
                                    "error": f"Cannot merge across fields from the same model ({m_name}). Grouping is strictly for merging corresponding telemetry across different models or protocols."
                                }), 400

        result = set_field_grouping_override(
            device_sn=device_sn,
            field_key=field_key,
            target_concept=target_concept,
            custom_label=custom_label,
            transform=transform,
        )
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/reset", methods=["POST"])
    def reset_grouping_override():
        from ...grouping import reset_field_grouping_override
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        field_key = data.get("field_key", "")

        device_sn = _resolve_device_sn(device_sn, field_key=field_key)
        if not device_sn or not field_key:
            return jsonify({"error": "device_sn and field_key are required"}), 400
        
        result = reset_field_grouping_override(
            device_sn=device_sn,
            field_key=field_key,
        )
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/ungroup_all", methods=["POST"])
    def ungroup_all():
        from ...grouping import ungroup_entire_concept
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        concept_key = data.get("concept_key", "")

        device_sn = _resolve_device_sn(device_sn, concept_key=concept_key)
        if not device_sn or not concept_key:
            return jsonify({"error": "device_sn and concept_key are required"}), 400
        
        dev = client.state.devices.get(device_sn) or next((d for d in client.state.devices.values() if d.serial_number.strip().upper() == device_sn.strip().upper()), None)
        if not dev:
            return jsonify({"error": f"Device {device_sn} not found"}), 404
        
        from ...optimizer import group_device_fields
        groups = group_device_fields(dev)
        grp = next((g for g in groups if g.concept_key == concept_key or g.id == concept_key), None)
        if not grp:
            return jsonify({"error": f"Concept {concept_key} not found"}), 404
        
        device_fields = {s.field_key: None for s in grp.sources}
        result = ungroup_entire_concept(
            device_sn=device_sn,
            concept_key=concept_key,
            device_fields=device_fields,
        )
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/suggestions")
    def get_grouping_suggestions():
        from ...tools.recommender import find_suggested_groupings
        suggestions = find_suggested_groupings(client.state)
        return jsonify({
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
        })

    @bp.route("/api/grouping/suggestions/approve", methods=["POST"])
    def approve_grouping_suggestion():
        from ...grouping import approve_suggestion
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        field_keys = data.get("field_keys", [])
        target_concept = data.get("target_concept", "")
        custom_label = data.get("label") or data.get("custom_label")
        suggestion_id = data.get("suggestion_id")
        transform = data.get("transform")

        if not device_sn or not field_keys or not target_concept:
            return jsonify({"error": "device_sn, field_keys, and target_concept are required"}), 400

        dev = client.state.devices.get(device_sn)
        if dev and len(field_keys) > 1:
            from ...tools.recommender import are_from_same_model
            f_objs = [dev.fields.get(fk) for fk in field_keys if dev.fields.get(fk)]
            for i in range(len(f_objs)):
                for j in range(i + 1, len(f_objs)):
                    if are_from_same_model(f_objs[i], f_objs[j]):
                        return jsonify({
                            "error": "Cannot merge across fields from the same model."
                        }), 400

        result = approve_suggestion(
            device_sn=device_sn,
            field_keys=field_keys,
            target_concept=target_concept,
            custom_label=custom_label,
            suggestion_id=suggestion_id,
            transform=transform,
        )
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/suggestions/batch-approve", methods=["POST"])
    def batch_approve_grouping_suggestions():
        from ...grouping import approve_suggestions
        data = request.get_json() or {}
        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            return jsonify({"error": "suggestions array is required"}), 400

        result = approve_suggestions(suggestions)
        return jsonify({"status": "ok", "count": len(suggestions), "overrides": result})

    @bp.route("/api/grouping/suggestions/dismiss", methods=["POST"])
    def dismiss_grouping_suggestion():
        from ...grouping import dismiss_suggestion
        data = request.get_json() or {}
        suggestion_id = data.get("suggestion_id", "")
        if not suggestion_id:
            return jsonify({"error": "suggestion_id is required"}), 400

        result = dismiss_suggestion(suggestion_id=suggestion_id)
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/suggestions/batch-dismiss", methods=["POST"])
    def batch_dismiss_grouping_suggestions():
        from ...grouping import dismiss_suggestions
        data = request.get_json() or {}
        suggestion_ids = data.get("suggestion_ids", [])
        if not isinstance(suggestion_ids, list):
            return jsonify({"error": "suggestion_ids array is required"}), 400

        result = dismiss_suggestions(suggestion_ids)
        return jsonify({"status": "ok", "count": len(suggestion_ids), "overrides": result})

    @bp.route("/api/grouping/export")
    def export_grouping_mappings():
        from flask import Response
        from ...grouping import export_generalized_groupings, export_as_telemetry_mappings
        fmt = request.args.get("format", "generalized").lower()
        as_download = request.args.get("download", "").lower() in ("true", "1", "yes")
        full = request.args.get("full", "true").lower() in ("true", "1", "yes")

        if fmt in ("telemetry", "telemetry_mappings", "builtin"):
            res = export_as_telemetry_mappings(client.state, only_custom=not full)
            filename = "telemetry_mappings.yaml"
        else:
            res = export_generalized_groupings()
            filename = "custom_groupings.yaml"

        if as_download:
            return Response(
                res["yaml"],
                mimetype="text/yaml",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        return jsonify({
            "status": "ok",
            "format": fmt,
            "filename": filename,
            "yaml": res["yaml"],
            "data": res.get("data") or res.get("mappings"),
            "ungrouped_fields": res.get("ungrouped_fields", []),
        })

    @bp.route("/api/grouping/save-to-mappings", methods=["POST"])
    def save_to_telemetry_mappings():
        from ...grouping import save_current_as_telemetry_mappings
        data = request.get_json() or {}
        clear_custom = data.get("clear_custom_overrides", True)
        only_custom = data.get("only_custom", False)
        res = save_current_as_telemetry_mappings(
            state_store=client.state,
            only_custom=only_custom,
            clear_custom_overrides=clear_custom,
        )
        return jsonify(res)

    return bp
