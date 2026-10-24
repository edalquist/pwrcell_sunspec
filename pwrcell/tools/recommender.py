"""Automated Grouping Recommendation Engine for Generac PWRcell.

Analyzes telemetry across SunSpec Modbus registers and live MQTT push fields to identify
candidate groupings based on:
1. Live value agreement and correlation (Delta < 1%)
2. Clean unit and device class compatibility
3. Semantic token and naming proximity (e.g. 'wh' ≈ 'e' ≈ 'energy')
4. Paired SunSpec standard vs. Generac vendor model topologies

Surfaces scored suggestions for one-click user review, approval, or dismissal in the UI.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..catalog import is_scale_factor_point
from ..optimizer import clean_unit, group_device_fields
from ..state import StateStore, UnifiedDevice

logger = logging.getLogger(__name__)

# Canonical semantic synonym groups
SEMANTIC_SYNONYM_CLUSTERS: List[Dict[str, Any]] = [
    {
        "concept": "energy",
        "units": "Wh",
        "label": "Cumulative Energy",
        "tokens": {"wh", "e", "energy", "totwh", "whexp", "whimp", "kwh", "dcwh", "whin", "whout"},
    },
    {
        "concept": "power",
        "units": "W",
        "label": "Active Power",
        "tokens": {"w", "p", "power", "kw", "real_power", "dcw", "watts", "ctpow"},
    },
    {
        "concept": "voltage",
        "units": "V",
        "label": "Voltage",
        "tokens": {"v", "volt", "voltage", "volts", "dcv", "vin", "phv", "phvpha", "phvphb", "phvphc"},
    },
    {
        "concept": "current",
        "units": "A",
        "label": "Current",
        "tokens": {"a", "amp", "amps", "current", "dca", "iin", "apha", "aphb", "aphc"},
    },
    {
        "concept": "frequency",
        "units": "Hz",
        "label": "Frequency",
        "tokens": {"hz", "freq", "frequency"},
    },
    {
        "concept": "temperature",
        "units": "C",
        "label": "Temperature",
        "tokens": {"temp", "tmp", "temperature", "tmpsnk", "tmpcab", "tmpamb"},
    },
    {
        "concept": "state_of_charge",
        "units": "%",
        "label": "State of Charge",
        "tokens": {"soc", "state_of_charge"},
    },
    {
        "concept": "state_of_health",
        "units": "%",
        "label": "State of Health",
        "tokens": {"soh", "state_of_health"},
    },
    {
        "concept": "connection_state",
        "units": "",
        "label": "Connection / Enable State",
        "tokens": {"conn", "connect", "connected", "enabled", "enable", "ena"},
    },
]


@dataclass
class GroupingCandidateSource:
    source_id: str
    source_type: str
    field_key: str
    name: str
    label: str
    model_id: Optional[int]
    value: Any
    raw_value: Any
    units: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GroupingSuggestion:
    id: str
    device_sn: str
    device_type: str
    device_name: str
    suggested_concept_key: str
    suggested_label: str
    units: str
    confidence: float  # 0.0 to 1.0
    confidence_label: str  # HIGH, MEDIUM
    reasons: List[str]
    sources: List[GroupingCandidateSource] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = [s.to_dict() for s in self.sources]
        return d


def tokenize_name(text: str) -> Set[str]:
    """Extract lowercase alphanumeric tokens from point names, keys, and labels."""
    if not text:
        return set()
    cleaned = re.sub(r"[_\W]+", " ", text).lower()
    return {t for t in cleaned.split() if t}


def find_semantic_cluster(tokens: Set[str], unit: Optional[str]) -> Optional[Dict[str, Any]]:
    """Match tokens and unit against known semantic synonym clusters."""
    c_unit = clean_unit(unit)
    for cluster in SEMANTIC_SYNONYM_CLUSTERS:
        if c_unit and cluster["units"] and clean_unit(cluster["units"]) != c_unit:
            continue
        if tokens & cluster["tokens"]:
            return cluster
    return None


def find_suggested_groupings(
    state_store: StateStore,
    dismissed_ids: Optional[Set[str]] = None,
) -> List[GroupingSuggestion]:
    """Scan all devices in state_store and compute high-confidence grouping suggestions."""
    from ..grouping import load_custom_groupings
    overrides_data = load_custom_groupings()
    dismissed = dismissed_ids if dismissed_ids is not None else set(overrides_data.get("dismissed_suggestions", []))

    suggestions: List[GroupingSuggestion] = []

    if not state_store.devices:
        return suggestions

    for dev in state_store.devices.values():
        dev_sn = dev.serial_number
        dev_type = dev.device_type
        dev_name = f"{dev.model_name or dev.device_type} ({dev_sn[-4:] if len(dev_sn) >= 4 else dev_sn})"

        # Evaluate existing unified groups for this device
        groups = group_device_fields(dev)

        # Collect candidate sources that currently sit in single-source groups and have live values.
        # Exclude scale factor registers from merging candidates.
        single_source_candidates: List[Tuple[Any, Any]] = []  # (group, source)
        for g in groups:
            if getattr(g, "is_scale_factor", False):
                continue
            if len(g.sources) == 1:
                s = g.sources[0]
                if is_scale_factor_point(
                    name=s.name,
                    point_type=getattr(s, "point_type", None),
                    label=s.label,
                    explicit=bool(getattr(s, "is_scale_factor", False)),
                ):
                    continue
                if s.value is not None:
                    single_source_candidates.append((g, s))

        # Check pairs of candidates on this device
        evaluated_pairs: Set[Tuple[str, str]] = set()

        for i in range(len(single_source_candidates)):
            for j in range(i + 1, len(single_source_candidates)):
                g_a, s_a = single_source_candidates[i]
                g_b, s_b = single_source_candidates[j]

                # Don't compare same field
                if s_a.field_key == s_b.field_key:
                    continue

                pair_key = tuple(sorted([s_a.field_key, s_b.field_key]))
                if pair_key in evaluated_pairs:
                    continue
                evaluated_pairs.add(pair_key)

                # 1. Units must be compatible
                u_a = clean_unit(s_a.units or g_a.units)
                u_b = clean_unit(s_b.units or g_b.units)
                if u_a != u_b:
                    continue

                # 2. Score heuristics
                score = 0
                reasons: List[str] = []

                # Heuristic A: Value correlation
                val_a = s_a.value
                val_b = s_b.value
                is_numeric = isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)) and not isinstance(val_a, bool) and not isinstance(val_b, bool)

                if is_numeric:
                    f_a = float(val_a)
                    f_b = float(val_b)
                    delta = abs(f_a - f_b)
                    denom = max(abs(f_a), abs(f_b), 1.0)
                    pct_diff = (delta / denom) * 100.0

                    if delta <= 0.05:
                        score += 50
                        reasons.append(f"Exact live value match ({f_a:.2f} {u_a or ''})")
                    elif pct_diff <= 1.0 and denom >= 10.0:
                        score += 45
                        reasons.append(f"Near-exact live values agree within {pct_diff:.2f}% (Δ {delta:.2f})")
                    elif pct_diff <= 5.0 and delta <= 5.0:
                        score += 30
                        reasons.append(f"Live values agree within sensor noise ({pct_diff:.1f}% difference)")
                    else:
                        # Values do not match; cannot recommend grouping with high confidence
                        continue
                else:
                    # String or Enum matching
                    raw_a = s_a.raw_value
                    raw_b = s_b.raw_value
                    if raw_a is not None and raw_b is not None and raw_a == raw_b:
                        score += 50
                        reasons.append(f"Identical raw enum state code ({raw_a})")
                    elif str(val_a).strip().upper() == str(val_b).strip().upper():
                        score += 50
                        reasons.append(f"Identical state value ({val_a})")
                    else:
                        continue

                # Heuristic B: Semantic token and naming proximity
                tok_a = tokenize_name(f"{s_a.name} {s_a.label} {g_a.concept_key}")
                tok_b = tokenize_name(f"{s_b.name} {s_b.label} {g_b.concept_key}")

                cluster_a = find_semantic_cluster(tok_a, u_a)
                cluster_b = find_semantic_cluster(tok_b, u_b)

                common_tokens = tok_a & tok_b
                if cluster_a and cluster_b and cluster_a["concept"] == cluster_b["concept"]:
                    score += 35
                    reasons.append(f"Shared semantic concept: {cluster_a['label']}")
                elif common_tokens:
                    score += 25
                    reasons.append(f"Matching naming tokens: {', '.join(sorted(common_tokens))}")

                # Heuristic C: Topology / Paired Model correlation
                # E.g. Standard model (102, 802, 404) vs. Vendor model (64207, 64251, 64252) or MQTT
                is_standard_a = s_a.model_id in (101, 102, 103, 120, 121, 122, 123, 404, 802, 804)
                is_standard_b = s_b.model_id in (101, 102, 103, 120, 121, 122, 123, 404, 802, 804)
                is_vendor_or_mqtt = (
                    s_a.source_type == "MQTT"
                    or s_b.source_type == "MQTT"
                    or (s_a.model_id and s_a.model_id >= 64200)
                    or (s_b.model_id and s_b.model_id >= 64200)
                )

                if (is_standard_a or is_standard_b) and is_vendor_or_mqtt:
                    score += 15
                    reasons.append("Complementary SunSpec standard and Generac REbus vendor registers")

                # Filter threshold: score >= 70
                if score >= 70:
                    confidence = min(0.99, round(score / 100.0, 2))
                    conf_label = "HIGH" if confidence >= 0.85 else "MEDIUM"

                    # Synthesize clean concept key and display label
                    if cluster_a and cluster_b and cluster_a["concept"] == cluster_b["concept"]:
                        suggested_key = cluster_a["concept"]
                        suggested_label = cluster_a["label"]
                    else:
                        suggested_key = g_a.concept_key if len(g_a.concept_key) <= len(g_b.concept_key) else g_b.concept_key
                        suggested_label = g_a.label if g_a.label else g_b.label

                    sugg_id = f"sugg_{dev_sn}_{pair_key[0]}_{pair_key[1]}".replace(".", "_").replace(":", "_")

                    if sugg_id in dismissed:
                        continue

                    candidate_sources = [
                        GroupingCandidateSource(
                            source_id=s_a.source_id,
                            source_type=s_a.source_type,
                            field_key=s_a.field_key,
                            name=s_a.name,
                            label=s_a.label,
                            model_id=s_a.model_id,
                            value=s_a.value,
                            raw_value=s_a.raw_value,
                            units=s_a.units,
                        ),
                        GroupingCandidateSource(
                            source_id=s_b.source_id,
                            source_type=s_b.source_type,
                            field_key=s_b.field_key,
                            name=s_b.name,
                            label=s_b.label,
                            model_id=s_b.model_id,
                            value=s_b.value,
                            raw_value=s_b.raw_value,
                            units=s_b.units,
                        ),
                    ]

                    suggestions.append(
                        GroupingSuggestion(
                            id=sugg_id,
                            device_sn=dev_sn,
                            device_type=dev_type,
                            device_name=dev_name,
                            suggested_concept_key=suggested_key,
                            suggested_label=suggested_label,
                            units=u_a or "",
                            confidence=confidence,
                            confidence_label=conf_label,
                            reasons=reasons,
                            sources=candidate_sources,
                        )
                    )

    # Sort suggestions by confidence descending
    suggestions.sort(key=lambda s: -s.confidence)
    return suggestions
