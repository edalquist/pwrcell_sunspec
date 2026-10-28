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

    @bp.route("/api/compare/sync_sample", methods=["POST"])
    @bp.route("/api/grouping/sync_sample", methods=["POST"])
    def sync_sample_endpoint():
        body = request.get_json() or {}
        field_keys = body.get("field_keys", [])
        device_sn = body.get("device_sn")
        concept_key = body.get("concept_key")

        # If field_keys is empty but concept_key is provided, resolve field_keys from concept
        if not field_keys and concept_key:
            from ...tools.correlator import evaluate_comparisons
            all_comps = evaluate_comparisons(client.state)
            matching_row = next(
                (r for r in all_comps if (r.concept_key == concept_key or r.mapping_id == concept_key) and (not device_sn or r.device_sn == device_sn)),
                None
            )
            if matching_row and matching_row.sources:
                field_keys = [s.get("field_key") for s in matching_row.sources if s.get("field_key")]
                if not device_sn:
                    device_sn = matching_row.device_sn

        if not field_keys:
            return jsonify({"status": "error", "error": "No field keys or concept provided"}), 400

        res = client.sync_sample_fields(field_keys=field_keys, device_sn=device_sn)

        # Also return refreshed comparison row if applicable
        comp_dict = None
        if concept_key or field_keys:
            from ...tools.correlator import evaluate_comparisons
            all_comps = evaluate_comparisons(client.state)
            matching_row = None
            if concept_key:
                matching_row = next(
                    (r for r in all_comps if (r.concept_key == concept_key or r.mapping_id == concept_key) and (not device_sn or r.device_sn == device_sn)),
                    None
                )
            if not matching_row and field_keys:
                matching_row = next(
                    (r for r in all_comps if any(s.get("field_key") in field_keys for s in r.sources)),
                    None
                )
            if matching_row:
                comp_dict = matching_row.to_dict()

        res["comparison"] = comp_dict
        return jsonify(res)

    @bp.route("/api/grouping/bounds", methods=["GET", "POST", "DELETE"])
    def handle_grouping_bounds():
        from ...bounds import load_custom_bounds, save_custom_bound
        if request.method == "GET":
            return jsonify(load_custom_bounds())

        body = request.get_json(silent=True) or {}
        field_key = (
            body.get("field_key")
            or body.get("key")
            or request.args.get("field_key")
            or request.args.get("key")
        )
        if not field_key:
            return jsonify({"error": "field_key is required"}), 400

        device_sn = body.get("device_sn") or request.args.get("device_sn")
        apply_all = body.get("apply_all", False)
        if apply_all:
            device_sn = None

        if request.method == "DELETE":
            save_custom_bound(field_key, None, device_sn=device_sn)
            return jsonify({"success": True, "bounds": load_custom_bounds()})

        bounds_val = body.get("bounds", body)
        save_custom_bound(field_key, bounds_val, device_sn=device_sn)
        return jsonify({"success": True, "bounds": load_custom_bounds()})

    @bp.route("/api/grouping/overrides")
    def get_grouping_overrides():
        from ...grouping import load_custom_groupings
        return jsonify(load_custom_groupings())

    @bp.route("/api/grouping/reset_defaults", methods=["POST"])
    def reset_grouping_defaults():
        try:
            from ...grouping import get_default_grouping_config_path, save_custom_groupings
            p = get_default_grouping_config_path()
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    save_custom_groupings({})
            else:
                save_custom_groupings({})
            return jsonify({"success": True, "message": "Grouping overrides reset to default"})
        except Exception as e:
            logger.error("Failed resetting grouping overrides: %s", e)
            return jsonify({"error": str(e)}), 500

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
        
        member_field_keys = data.get("member_field_keys") or []
        if isinstance(member_field_keys, str):
            member_field_keys = [member_field_keys]
        member_field_keys = [k for k in member_field_keys if k and isinstance(k, str)]
        if field_key not in member_field_keys:
            member_field_keys.insert(0, field_key)

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
                        (
                            g for g in existing_groups
                            if g.concept_key == clean_tc
                            or g.id.endswith(f".concept.{clean_tc}")
                            or g.id.endswith(f".standalone.{clean_tc}")
                        ),
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
                            if s.field_key and s.field_key not in member_field_keys:
                                member_field_keys.append(s.field_key)

        result = None
        for fk in member_field_keys:
            result = set_field_grouping_override(
                device_sn=device_sn,
                field_key=fk,
                target_concept=target_concept,
                custom_label=custom_label,
                transform=transform if fk == field_key else None,
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

    @bp.route("/api/grouping/invert", methods=["POST"])
    def invert_field_transform():
        from ...grouping import load_custom_groupings, save_custom_groupings
        data = request.get_json() or {}
        device_sn = data.get("device_sn", "")
        field_key = data.get("field_key", "")
        device_sn = _resolve_device_sn(device_sn, field_key=field_key)
        if not device_sn or not field_key:
            return jsonify({"error": "device_sn and field_key are required"}), 400

        custom_data = load_custom_groupings()
        transforms = custom_data.setdefault("field_transforms", {})
        clean_sn = device_sn.strip().upper()
        qual_key = f"{clean_sn}:{field_key.strip()}"

        current_tf = transforms.get(qual_key) or transforms.get(field_key.strip())
        new_tf = "none" if current_tf == "negate" else "negate"
        transforms[qual_key] = new_tf

        save_custom_groupings(custom_data)
        return jsonify({"status": "ok", "field_key": field_key, "transform": new_tf})

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
        negate_field_key = data.get("negate_field_key")
        positive_field_key = data.get("positive_field_key")
        negative_field_key = data.get("negative_field_key")
        polarity_convention = data.get("polarity_convention")

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
            negate_field_key=negate_field_key,
            positive_field_key=positive_field_key,
            negative_field_key=negative_field_key,
            polarity_convention=polarity_convention,
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

        if fmt in ("telemetry", "telemetry_mappings", "builtin", "groupings"):
            res = export_as_telemetry_mappings(client.state, only_custom=not full)
            filename = "groupings.yaml"
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

    @bp.route("/api/grouping/export_repo_groupings", methods=["POST"])
    def export_groupings_to_repo():
        from ...grouping import export_repo_groupings
        try:
            body = request.get_json() or {}
            target_path = body.get("target_path")
            res = export_repo_groupings(client.state, target_path=target_path)
            return jsonify({
                "status": "ok",
                "groups_count": len(res.get("groups", [])),
                "ungrouped_count": len(res.get("ungrouped_fields", [])),
                "target_path": res.get("target_path"),
                "message": f"Successfully exported {len(res.get('groups', []))} groupings to {res.get('target_path')}",
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

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
