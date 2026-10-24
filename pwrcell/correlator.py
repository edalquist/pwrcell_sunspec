"""Telemetry Correlation and Modbus-to-MQTT Mapping Engine (Forwarding Shim)."""

from .concept import ConceptView as ComparisonResultRow, ConceptView
from .tools.correlator import (
    KNOWN_TELEMETRY_MAPPINGS,
    ModbusCandidate,
    TelemetryMappingDef,
    _build_comparison_row,
    evaluate_comparisons,
    find_heuristic_matches,
    format_comparison_table,
    get_known_telemetry_mappings,
    log_unrecognized_proto_fields,
)

__all__ = [
    "ComparisonResultRow",
    "ConceptView",
    "KNOWN_TELEMETRY_MAPPINGS",
    "ModbusCandidate",
    "TelemetryMappingDef",
    "_build_comparison_row",
    "evaluate_comparisons",
    "find_heuristic_matches",
    "format_comparison_table",
    "get_known_telemetry_mappings",
    "log_unrecognized_proto_fields",
]
