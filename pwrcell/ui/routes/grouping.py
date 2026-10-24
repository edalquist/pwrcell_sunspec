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
        if not client.is_mock:
            client.poll_telemetry_models_live()
        results = evaluate_comparisons(client.state)
        unrecognized = client.get_unrecognized_proto_fields()
        log_unrecognized_proto_fields(unrecognized)

        discrepant_count = sum(1 for r in results if getattr(r, "is_discrepant", False) or r.status in ("DIVERGENT", "UNIT_MISMATCH", "POLARITY_MISMATCH", "SCALE_MISMATCH"))
        exact_count = sum(1 for r in results if r.status == "EXACT")
        close_count = sum(1 for r in results if r.status == "CLOSE")
        multi_count = sum(1 for r in results if (getattr(r, "source_count", 0) > 1 or len(getattr(r, "sources", [])) > 1))
        single_count = sum(1 for r in results if r.status == "SINGLE_SOURCE")
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

    @bp.route("/api/grouping/override", methods=["POST"])
    def set_grouping_override():
        from ...grouping import set_field_grouping_override
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        field_key = data.get("field_key", "")
        target_concept = data.get("target_concept")
        custom_label = data.get("custom_label")
        if not device_sn or not field_key:
            return jsonify({"error": "device_sn and field_key are required"}), 400
        
        result = set_field_grouping_override(
            device_sn=device_sn,
            field_key=field_key,
            target_concept=target_concept,
            custom_label=custom_label,
        )
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/reset", methods=["POST"])
    def reset_grouping_override():
        from ...grouping import reset_field_grouping_override
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        field_key = data.get("field_key", "")
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
        if not device_sn or not concept_key:
            return jsonify({"error": "device_sn and concept_key are required"}), 400
        
        dev = client.state.devices.get(device_sn)
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

        if not device_sn or not field_keys or not target_concept:
            return jsonify({"error": "device_sn, field_keys, and target_concept are required"}), 400

        result = approve_suggestion(
            device_sn=device_sn,
            field_keys=field_keys,
            target_concept=target_concept,
            custom_label=custom_label,
            suggestion_id=suggestion_id,
        )
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/suggestions/dismiss", methods=["POST"])
    def dismiss_grouping_suggestion():
        from ...grouping import dismiss_suggestion
        data = request.get_json() or {}
        suggestion_id = data.get("suggestion_id", "")
        if not suggestion_id:
            return jsonify({"error": "suggestion_id is required"}), 400

        result = dismiss_suggestion(suggestion_id=suggestion_id)
        return jsonify({"status": "ok", "overrides": result})

    @bp.route("/api/grouping/export")
    def export_grouping_mappings():
        from flask import Response
        from ...grouping import export_generalized_groupings, export_as_telemetry_mappings
        fmt = request.args.get("format", "generalized").lower()
        as_download = request.args.get("download", "").lower() in ("true", "1", "yes")

        if fmt in ("telemetry", "telemetry_mappings", "builtin"):
            res = export_as_telemetry_mappings(client.state)
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
        })

    return bp
