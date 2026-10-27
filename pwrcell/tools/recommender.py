"""Automated Grouping Recommendation Engine for Generac PWRcell.

Analyzes telemetry across SunSpec Modbus registers and live MQTT push fields to identify
high-confidence candidate groupings based on:
1. Live telemetry classification (excluding configuration, settings, trip thresholds, and address fields)
2. Phase, sensor location, and flow-direction compatibility (preventing Phase A vs Phase B or Import vs Export mismatches)
3. Physical measurement units and semantic concept alignment
4. Quiescent zero-matching gates to prevent idle false positives
5. Paired SunSpec standard vs. Generac vendor model topologies

Surfaces scored suggestions for one-click user review, batch approval, or dismissal in the UI.
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
        "tokens": {"a", "amp", "amps", "current", "dca", "iin", "i", "apha", "aphb", "aphc"},
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
        "tokens": {"temp", "tmp", "temperature", "tmpsnk", "tmpcab", "tmpamb", "tmptrns"},
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
]

# Exclusion sets for non-telemetry points
SETTING_PREFIXES = (
    "reconn",
    "wmaxlim",
    "outpf",
    "varpct",
    "pqset",
    "varmod",
    "wmod",
    "trip",
    "prot",
    "conn",
    "autostart",
    "pcmd",
)
SETTING_SUFFIXES = (
    "_ena",
    "ena",
    "lim",
    "rtg",
    "crv",
    "tms",
    "time",
    "dly",
    "set",
    "cfg",
    "offset",
    "slope",
    "bias",
    "latchtms",
    "trip",
)
ADDRESS_POINTS = {
    "adr1",
    "adr2",
    "cty",
    "st",
    "zp",
    "cntr",
    "phn",
    "fnm",
    "lnm",
    "em",
    "ico",
    "iem",
    "ifnm",
    "ilnm",
    "iphn",
    "dns1",
    "dns2",
    "gw",
    "ip",
    "mac",
    "port",
    "mask",
    "sn",
    "vn",
    "vm",
    "vr",
    "cert",
    "ver",
}
NON_TELEMETRY_MODELS = {16, 64203, 64250, 120, 121, 122, 123, 124, 126}


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
    last_updated: Optional[float] = None

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
    suggested_transform: Optional[str] = None
    inverted_pair: bool = False
    positive_field_key: Optional[str] = None
    negative_field_key: Optional[str] = None

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


def is_telemetry_candidate(source: Any, group: Any) -> bool:
    """Filter out non-telemetry points (configuration, setpoints, network settings, addresses, scale factors)."""
    name = (source.name or "").lower()
    # 1. Scale factors
    if getattr(group, "is_scale_factor", False) or is_scale_factor_point(
        name=source.name,
        point_type=getattr(source, "point_type", None),
        label=source.label,
        explicit=bool(getattr(group, "is_scale_factor", False)),
    ):
        return False

    # 2. Writable registers (setpoints, control registers)
    if getattr(source, "is_writable", False):
        return False

    # 3. Models known to be purely network config, curve definitions, or protection trips
    if source.model_id in NON_TELEMETRY_MODELS:
        return False

    # 4. Network and address points
    if name in ADDRESS_POINTS:
        return False

    # 5. Empty or blank strings
    val = source.value
    if isinstance(val, str) and not val.strip():
        return False

    # 6. Setting / limit / trip / curve prefixes and suffixes
    if any(name.startswith(p) for p in SETTING_PREFIXES):
        return False
    if any(name.endswith(s) for s in SETTING_SUFFIXES):
        return False

    # 7. Must possess a valid physical measurement unit
    u = clean_unit(source.units or getattr(group, "units", None))
    if not u:
        return False

    return True


def extract_phase(name: str, label: str) -> str:
    """Extract electrical phase (A, B, C) if explicitly specified in name or label."""
    cleaned = re.sub(r"[_\W]+", " ", f"{name} {label}").lower()
    m = re.search(r"\b(?:phase|line)\s*([abc])\b", cleaned)
    if m:
        return m.group(1).upper()
    m2 = re.search(r"\b(?:phv|a|w|v)?ph([abc])\b", cleaned)
    if m2:
        return m2.group(1).upper()
    return ""


def extract_temp_sensor(name: str, label: str) -> str:
    """Extract physical temperature sensor location."""
    cleaned = re.sub(r"[_\W]+", " ", f"{name} {label}").lower()
    if re.search(r"\b(?:snk|heatsink)\b|tmpsnk", cleaned):
        return "heatsink"
    if re.search(r"\b(?:cab|cabinet)\b|tmpcab", cleaned):
        return "cabinet"
    if re.search(r"\b(?:trns|transformer)\b|tmptrns", cleaned):
        return "transformer"
    if re.search(r"\b(?:amb|ambient)\b|tmpamb", cleaned):
        return "ambient"
    if re.search(r"\bcell\b", cleaned):
        return "cell"
    return ""


def extract_direction(name: str, label: str) -> str:
    """Extract power or energy flow direction (export, import, charge, discharge)."""
    cleaned = re.sub(r"[_\W]+", " ", f"{name} {label}").lower()
    if re.search(r"\b(?:exp|export(?:ed)?|out|whout|whexp)\b", cleaned):
        return "export"
    if re.search(r"\b(?:imp|import(?:ed)?|whimp|whin)\b", cleaned) or re.search(r"\bin\b", cleaned):
        return "import"
    if re.search(r"\b(?:discha|discharge|discharging)\b", cleaned):
        return "discharge"
    if re.search(r"\b(?:cha|charge|charging)\b", cleaned):
        return "charge"
    return ""


def extract_count_type(name: str, label: str) -> str:
    """Distinguish detected vs installed device counts."""
    cleaned = re.sub(r"[_\W]+", " ", f"{name} {label}").lower()
    if re.search(r"\bdetected\b", cleaned):
        return "detected"
    if re.search(r"\binstalled\b", cleaned):
        return "installed"
    return ""


def extract_extremum(name: str, label: str) -> Optional[str]:
    """Distinguish minimum vs maximum extremum points (e.g. CellVMax vs CellVMin, SoCMax vs SoCMin)."""
    cleaned = re.sub(r"[_\W]+", " ", f"{name} {label}").lower()
    is_max = bool(re.search(r"\b(?:max|maximum)\b", cleaned) or re.search(r"cellvmax|socmax|tmpmax|vmax", cleaned))
    is_min = bool(re.search(r"\b(?:min|minimum)\b", cleaned) or re.search(r"cellvmin|socmin|tmpmin|vmin", cleaned))
    if is_max and not is_min:
        return "MAX"
    if is_min and not is_max:
        return "MIN"
    return None


def get_source_model_key(s: Any) -> str:
    """Return a normalized model/stream key identifying the source model.
    
    Fields from the same model key must never be merged or suggested together.
    """
    m_id = getattr(s, "model_id", None)
    if m_id is not None:
        return f"model_{m_id}"
    
    src_id = (getattr(s, "source_id", "") or "").strip().upper()
    if src_id.startswith("M") and src_id[1:].isdigit():
        return f"model_{src_id[1:]}"
    if src_id == "MQTT":
        return "mqtt"
        
    src_type = (getattr(s, "source_type", "") or "").strip().upper()
    if src_type == "MQTT":
        return "mqtt"

    f_key = (getattr(s, "field_key", "") or "").strip()
    if f_key:
        parts = f_key.split(".")
        if len(parts) >= 2:
            middle = parts[1].lower()
            if middle == "live":
                return "mqtt"
            if middle.startswith("model_"):
                return middle
            m_name = (getattr(s, "model_name", "") or "").strip().lower()
            if m_name:
                return f"model_{m_name}"
            return f"model_{middle}"
            
    m_name = (getattr(s, "model_name", "") or "").strip().lower()
    if m_name:
        return f"model_{m_name}"

    return ""


def are_from_same_model(s_a: Any, s_b: Any) -> bool:
    """Return True if two fields belong to the same SunSpec model or telemetry stream.
    
    Merging should NEVER happen across fields from the same model.
    """
    # 1. Both SunSpec with same model_id
    if getattr(s_a, "model_id", None) is not None and getattr(s_b, "model_id", None) is not None:
        if s_a.model_id == s_b.model_id:
            return True
            
    # 2. Both MQTT push streams on the same device
    src_type_a = getattr(s_a, "source_type", "")
    src_type_b = getattr(s_b, "source_type", "")
    if src_type_a == "MQTT" and src_type_b == "MQTT":
        return True

    # 3. Source IDs match (e.g. both 'M802' or both 'M102')
    sid_a = getattr(s_a, "source_id", "")
    sid_b = getattr(s_b, "source_id", "")
    if sid_a and sid_b and sid_a.upper() == sid_b.upper():
        return True

    # 4. Normalized model keys
    m_a = get_source_model_key(s_a)
    m_b = get_source_model_key(s_b)
    if m_a and m_b and m_a == m_b:
        return True

    return False


GENERIC_CLUSTER_CONCEPTS = {
    "energy", "power", "voltage", "current", "frequency", "temperature",
    "state", "status", "standalone", "null", "none"
}
STOP_TOKENS = {
    "wh", "w", "v", "a", "hz", "c", "f", "pct", "percent", "inverter", "battery",
    "rebus", "live", "raw", "model", "push", "status", "dir", "exp", "tot",
    "meter", "phase", "ph", "device"
}


def clean_label(label: str) -> str:
    cleaned = re.sub(r"\(.*?\)", "", label).strip()
    return cleaned if cleaned else label.strip()


def synthesize_concept_for_pair(
    s_a: Any,
    s_b: Any,
    g_a: Any,
    g_b: Any,
    tok_a: Set[str],
    tok_b: Set[str],
    unit: Optional[str] = None,
) -> Tuple[str, str]:
    """Synthesize a unique, specific concept key and human label for a suggested pair.

    Ensures each distinct telemetry pair forms its own concept group rather than
    collapsing into generic domain categories like 'energy', 'power', or 'voltage'.
    """
    from ..mapping import MappingRegistry
    reg = MappingRegistry.get_instance()

    # 1. Check if either field matches a specific non-generic mapping in the registry
    for s in (s_a, s_b):
        m = reg.get_by_mqtt(s.field_key) or reg.find_mapping_for_modbus(s.field_key)
        if m and m.id and m.id.lower() not in GENERIC_CLUSTER_CONCEPTS:
            return m.id, m.label

    cl_a = clean_label(s_a.label)
    cl_b = clean_label(s_b.label)

    # 2. Extract meaningful shared descriptors (excluding generic unit words)
    shared = (tok_a & tok_b) - STOP_TOKENS
    primary_descriptors = [t for t in shared if t not in GENERIC_CLUSTER_CONCEPTS]

    if primary_descriptors:
        shared_lower = {t.lower() for t in primary_descriptors}
        words_a = [w for w in re.split(r"[\W_]+", cl_a) if w]
        words_b = [w for w in re.split(r"[\W_]+", cl_b) if w]

        # Prefer a clean existing label that contains the specific descriptor
        if any(w.lower() in shared_lower for w in words_b) and cl_b.lower() not in GENERIC_CLUSTER_CONCEPTS:
            key = re.sub(r"[\W_]+", "_", cl_b).lower().strip("_")
            return key, cl_b
        if any(w.lower() in shared_lower for w in words_a) and cl_a.lower() not in GENERIC_CLUSTER_CONCEPTS:
            key = re.sub(r"[\W_]+", "_", cl_a).lower().strip("_")
            return key, cl_a

        unit_suffix = [u for u in ("energy", "power", "voltage", "current") if u in tok_a | tok_b]
        ordered = sorted(primary_descriptors) + (unit_suffix[:1] if unit_suffix and unit_suffix[0] not in primary_descriptors else [])
        key = "_".join(ordered)
        label = " ".join(t.capitalize() for t in ordered)
        return key, label

    # 3. Use the most descriptive clean label between s_a and s_b
    candidates = [c for c in (cl_a, cl_b) if c.lower() not in GENERIC_CLUSTER_CONCEPTS]
    if candidates:
        best_label = max(candidates, key=len)
        key = re.sub(r"[\W_]+", "_", best_label).lower().strip("_")
        return key, best_label

    # 4. Fallback to point names
    key = f"{s_a.name.lower()}_{s_b.name.lower()}"
    return key, f"{cl_a or s_a.name} ({s_a.name}/{s_b.name})"


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

        # Collect candidate sources that sit in single-source groups and qualify as telemetry
        single_source_candidates: List[Tuple[Any, Any]] = []
        for g in groups:
            if len(g.sources) == 1:
                s = g.sources[0]
                if s.value is not None and is_telemetry_candidate(s, g):
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

                # 0. NEVER merge across fields from the same model or telemetry stream
                if are_from_same_model(s_a, s_b):
                    continue

                # 1. Extremum isolation: Min != Max (e.g. CellVMin != CellVMax)
                ext_a = extract_extremum(s_a.name, s_a.label)
                ext_b = extract_extremum(s_b.name, s_b.label)
                if ext_a and ext_b and ext_a != ext_b:
                    continue

                # 2. Units must be non-empty and compatible
                u_a = clean_unit(s_a.units or g_a.units)
                u_b = clean_unit(s_b.units or g_b.units)
                if not u_a or not u_b or u_a != u_b:
                    continue

                # 3. Phase isolation: Phase A != Phase B, and single phase != aggregate phase
                ph_a = extract_phase(s_a.name, s_a.label)
                ph_b = extract_phase(s_b.name, s_b.label)
                if (ph_a or ph_b) and ph_a != ph_b:
                    continue

                # 3. Temp sensor location isolation: Heatsink != Cabinet != Transformer
                ts_a = extract_temp_sensor(s_a.name, s_a.label)
                ts_b = extract_temp_sensor(s_b.name, s_b.label)
                if ts_a and ts_b and ts_a != ts_b:
                    continue

                # 4. Flow direction isolation: Import != Export, Charge != Discharge (except signed power/current)
                dir_a = extract_direction(s_a.name, s_a.label)
                dir_b = extract_direction(s_b.name, s_b.label)
                if dir_a and dir_b and dir_a != dir_b and u_a not in ("W", "kW", "VA", "VAr", "A"):
                    continue

                # 5. Count type isolation: Detected != Installed
                ct_a = extract_count_type(s_a.name, s_a.label)
                ct_b = extract_count_type(s_b.name, s_b.label)
                if ct_a and ct_b and ct_a != ct_b:
                    continue

                # 6. Semantic token and naming proximity
                tok_a = tokenize_name(f"{s_a.name} {s_a.label} {g_a.concept_key}")
                tok_b = tokenize_name(f"{s_b.name} {s_b.label} {g_b.concept_key}")
                cluster_a = find_semantic_cluster(tok_a, u_a)
                cluster_b = find_semantic_cluster(tok_b, u_b)

                same_concept = bool(cluster_a and cluster_b and cluster_a["concept"] == cluster_b["concept"])
                shared_tokens = tok_a & tok_b

                # Hard gate: Must share semantic concept or at least 2 distinct naming tokens
                if not same_concept and len(shared_tokens) < 2:
                    continue

                # 7. Topology / Paired Model correlation
                is_standard = s_a.model_id in (101, 102, 103, 120, 121, 122, 123, 404, 802, 804) or s_b.model_id in (101, 102, 103, 120, 121, 122, 123, 404, 802, 804)
                is_vendor_or_mqtt = (
                    s_a.source_type == "MQTT"
                    or s_b.source_type == "MQTT"
                    or (s_a.model_id and s_a.model_id >= 64200)
                    or (s_b.model_id and s_b.model_id >= 64200)
                )
                is_topo_match = is_standard and is_vendor_or_mqtt

                # 8. Score heuristics
                score = 0
                reasons: List[str] = []

                val_a = s_a.value
                val_b = s_b.value
                is_numeric = (
                    isinstance(val_a, (int, float))
                    and isinstance(val_b, (int, float))
                    and not isinstance(val_a, bool)
                    and not isinstance(val_b, bool)
                )

                is_inverted = False
                suggested_transform = None
                pos_key = None
                neg_key = None

                if is_numeric:
                    f_a = float(val_a)
                    f_b = float(val_b)
                    both_zero = abs(f_a) < 0.05 and abs(f_b) < 0.05
                    delta = abs(f_a - f_b)
                    denom = max(abs(f_a), abs(f_b), 1.0)
                    pct_diff = (delta / denom) * 100.0

                    abs_delta = abs(abs(f_a) - abs(f_b))
                    abs_pct_diff = (abs_delta / denom) * 100.0

                    # Check for opposite polarity match (e.g. +2800 vs -2800)
                    if not both_zero and (f_a * f_b < -0.25) and (abs_delta <= 0.05 or (abs_pct_diff <= 25.0 and denom >= 5.0) or (same_concept and abs_pct_diff <= 35.0)):
                        is_inverted = True
                        suggested_transform = "negate"
                        pos_key = s_a.field_key if f_a > 0 else s_b.field_key
                        neg_key = s_b.field_key if f_a > 0 else s_a.field_key
                        score += 55
                        reasons.append(f"Inverted polarity live match (|{f_a:.1f}| ≈ |{f_b:.1f}| {u_a}) — suggests grouping with negation")
                    elif both_zero:
                        # Zero matching requires high semantic concept agreement and topology match
                        if not (same_concept and (shared_tokens or is_topo_match)):
                            continue
                        score += 40
                        reasons.append(f"Quiescent zero value agreement (0.00 {u_a})")
                    elif delta <= 0.05:
                        score += 50
                        reasons.append(f"Exact live value match ({f_a:.2f} {u_a})")
                    elif pct_diff <= 1.0 and denom >= 10.0:
                        score += 45
                        reasons.append(f"Near-exact live values agree within {pct_diff:.2f}% (Δ {delta:.2f})")
                    elif pct_diff <= 5.0 or delta <= 5.0:
                        score += 35
                        reasons.append(f"Live values agree within sensor noise ({pct_diff:.1f}% difference)")
                    elif pct_diff <= 25.0 or delta <= 50.0:
                        score += 20
                        reasons.append(f"Live values correlate with polling skew ({pct_diff:.1f}% difference, Δ {delta:.1f} {u_a})")
                    elif same_concept:
                        score += 15
                        reasons.append(f"Transient telemetry divergence during polling (Δ {delta:.1f} {u_a})")
                    else:
                        continue
                else:
                    raw_a = s_a.raw_value
                    raw_b = s_b.raw_value
                    if raw_a is not None and raw_b is not None and raw_a == raw_b:
                        score += 50
                        reasons.append(f"Identical raw state code ({raw_a})")
                    elif str(val_a).strip().upper() == str(val_b).strip().upper():
                        score += 50
                        reasons.append(f"Identical state value ({val_a})")
                    else:
                        continue

                # Concept bonus
                if same_concept and cluster_a:
                    score += 35
                    reasons.append(f"Shared semantic concept: {cluster_a['label']}")
                elif shared_tokens:
                    score += 20
                    reasons.append(f"Matching naming tokens: {', '.join(sorted(shared_tokens))}")

                # Topology bonus
                if is_topo_match:
                    score += 15
                    reasons.append("Complementary SunSpec standard and Generac REbus vendor registers")

                # Filter threshold: score >= 65
                if score >= 65:
                    confidence = min(0.99, round(score / 100.0, 2))
                    conf_label = "HIGH" if confidence >= 0.85 else "MEDIUM"

                    # Synthesize distinct concept key and display label per pair
                    suggested_key, suggested_label = synthesize_concept_for_pair(
                        s_a=s_a,
                        s_b=s_b,
                        g_a=g_a,
                        g_b=g_b,
                        tok_a=tok_a,
                        tok_b=tok_b,
                        unit=u_a,
                    )

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
                            last_updated=getattr(s_a, "last_updated", None),
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
                            last_updated=getattr(s_b, "last_updated", None),
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
                            suggested_transform=suggested_transform,
                            inverted_pair=is_inverted,
                            positive_field_key=pos_key,
                            negative_field_key=neg_key,
                        )
                    )

    # Sort suggestions by confidence descending
    suggestions.sort(key=lambda s: -s.confidence)
    return suggestions
