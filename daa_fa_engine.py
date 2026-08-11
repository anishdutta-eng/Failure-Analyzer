"""DAA FA Engine — fuses the failure-analysis knowledge base with a board's
power-tree schematic to localize and explain Dead-After-Arrival faults.

Design goals
------------
- Deterministic and explainable (no training data required to work on day one).
- Pure functions: the engine takes the board's test-point table, its
  `evaluate` function, and its schematic DB as arguments, so it has NO import
  dependency on the Streamlit UI (`debugger.py`) and is fully unit-testable.
- Fuses three sources of truth:
    1. The power-tree graph (who feeds whom) — for fault localization.
    2. Electrical signatures (open/short/low/high/ripple/...) — from measurements.
    3. The knowledge base (`daa_knowledge_base`) — physics-of-failure mechanisms,
       tests, and citations.

Core capabilities
-----------------
- classify(readings)          -> per-rail PASS/WARN/FAIL/MONITOR
- localize_fault(readings)    -> topmost root fault(s), suppressing downstream consequences
- next_probe(readings, ...)   -> the single best next measurement (guided, minimal probes)
- open_or_short(node, r)      -> converter-open vs load-short discrimination + candidates
- deduce(readings, obs, ...)  -> ranked, cited failure hypotheses with recommended tests
- daa_summary(...)            -> a structured block for the FA report
"""

from __future__ import annotations

import daa_knowledge_base as kb

ROOT = "__PSE_INPUT__"  # external power source (PoE injector + cable), upstream of the board

# Resistance-to-ground thresholds (Ohms) for the open-vs-short discriminator.
SHORT_OHMS = 1.0
OPEN_OHMS = 5.0

# Readings that are system-level power figures, not nodes in the voltage tree.
NON_NODE_KEYS = {"POE_POWER_UBOOT", "POE_POWER_QSDK"}


# --------------------------------------------------------------------------- #
# Power-tree graph (derived from the Snowbird schematic paths in SCHEMATIC_DB).
# 'parent' is the power source; 'verified' marks edges confirmed directly from a
# schematic_path string vs. inferred (which the UI flags for engineer review).
# 'seq_after' = must power up after this rail; 'co_requires' = also needs these.
# --------------------------------------------------------------------------- #
# ---------------------------------------------------------------------------
# The power-tree topology is PER-PROGRAM and is supplied by the caller via a
# `graph` bundle loaded from that program's board pack:
#
#   graph = {
#     "root": "<source sentinel>",       # upstream of the board (e.g. PSE input)
#     "tree": {rail: {"parent": ..., "verified": bool,
#                     "seq_after": rail, "co_requires": [rails]}},
#     "boot_critical": [rails...],       # must pass or the unit is dead
#     "complaint_branches": {complaint: [rails...]},
#   }
#
# It is NOT hardcoded here. Previously this module held Snowbird's rails, which
# meant every program was localized against Snowbird's topology.
# ---------------------------------------------------------------------------

EMPTY_GRAPH = {"root": ROOT, "tree": {}, "boot_critical": [], "complaint_branches": {}}


def _g(graph):
    """Normalize a graph bundle, tolerating None/partial input."""
    g = dict(EMPTY_GRAPH)
    if graph:
        g.update({k: v for k, v in graph.items() if v is not None})
    return g


COMPLAINTS = {
    "DEAD": "Dead (no LED, no boot)",
    "DOA": "Dead on arrival (never worked)",
    "REBOOTS": "Reboots / brown-out / unstable power",
    "NO_WIFI": "Boots but WiFi dead",
    "NO_ETHERNET": "Boots but Ethernet dead",
    "NO_RF": "Boots but a radio band dead",
}


# --------------------------------------------------------------------------- #
# Graph helpers
# --------------------------------------------------------------------------- #
def ancestors(node: str, graph=None):
    """Yield power-tree ancestors of `node`, nearest first, up to (not incl.) root."""
    g = _g(graph)
    tree, root = g["tree"], g["root"]
    seen = set()
    cur = tree.get(node, {}).get("parent")
    while cur and cur != root and cur not in seen:
        seen.add(cur)
        yield cur
        cur = tree.get(cur, {}).get("parent")


def children_of(node: str, graph=None):
    return [k for k, v in _g(graph)["tree"].items() if v.get("parent") == node]


def validate_tree(test_points: dict, graph=None) -> dict:
    """Integrity check: every voltage test point should be in the tree, parents
    must exist, and there must be no cycles. Returns issues + unverified edges."""
    g = _g(graph)
    tree, root = g["tree"], g["root"]
    issues = []
    unverified = []
    if not tree:
        return {"issues": ["No power tree defined for this program."], "unverified_edges": []}
    # Cycle / missing-parent check
    for node, meta in tree.items():
        parent = meta.get("parent")
        if parent != root and parent not in tree:
            issues.append(f"{node}: parent '{parent}' not in tree")
        if not meta.get("verified", False):
            unverified.append(node)
        # walk to root to detect cycles
        seen, cur = set(), node
        while cur and cur != root:
            if cur in seen:
                issues.append(f"cycle detected at {cur}")
                break
            seen.add(cur)
            cur = tree.get(cur, {}).get("parent")
    # Coverage: voltage TPs not modeled
    for key, tp in test_points.items():
        if key in NON_NODE_KEYS:
            continue
        if str(tp.get("unit", "")).upper() != "V":
            continue
        if tp.get("monitor"):
            continue  # monitor-only pins (e.g. USB-C orientation) are not power rails
        if key not in tree:
            issues.append(f"{key}: voltage test point not modeled in the power tree")
    return {"issues": issues, "unverified_edges": unverified}


# --------------------------------------------------------------------------- #
# Classification & signatures
# --------------------------------------------------------------------------- #
def _to_float(val):
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return None


def classify(readings: dict, test_points: dict, evaluate_fn) -> dict:
    """Return {node_key: status} for every reading, using the board's evaluate()."""
    out = {}
    for key, val in readings.items():
        tp = test_points.get(key)
        if tp is None:
            continue
        status, _msg = evaluate_fn(val, tp)
        out[key] = status
    return out


def signature_for(key: str, readings: dict, test_points: dict, evaluate_fn,
                  r_to_gnd=None) -> str | None:
    """Derive the electrical signature at a node from its reading (+ optional
    resistance-to-ground). Returns a kb.SIG_* value, or 'dead_unknown' when a
    rail is at ~0 V but we still need the R-to-GND probe to call open vs short."""
    tp = test_points.get(key)
    if tp is None:
        return None
    val = readings.get(key)
    status, _ = evaluate_fn(val, tp)
    fval = _to_float(val)
    if status == "fail":
        # Dead-ish (at/near zero) => need open/short discrimination
        near_zero = fval is not None and fval <= (tp.get("lsl", 0) or 0) * 0.25
        if near_zero or fval == 0:
            if r_to_gnd is None:
                return "dead_unknown"
            return kb.SIG_DEAD_SHORT if r_to_gnd < OPEN_OHMS else kb.SIG_DEAD_OPEN
        if fval is not None and tp.get("usl") is not None and fval > tp["usl"]:
            return kb.SIG_HIGH
        return kb.SIG_LOW
    if status == "warn":
        return kb.SIG_LOW
    return None


def open_or_short(r_to_gnd: float) -> dict:
    """Interpret a resistance-to-ground probe on a dead rail."""
    if r_to_gnd < SHORT_OHMS:
        sig = kb.SIG_DEAD_SHORT
    elif r_to_gnd > OPEN_OHMS:
        sig = kb.SIG_DEAD_OPEN
    else:
        # Ambiguous middle band — lean toward short (loaded regulator) but flag it
        sig = kb.SIG_DEAD_SHORT
    info = kb.ELECTRICAL_SIGNATURES[sig]
    return {
        "resistance_ohms": r_to_gnd,
        "signature": sig,
        "verdict": "Load / die short" if sig == kb.SIG_DEAD_SHORT else "Regulator open / not switching",
        "meaning": info["meaning"],
        "first_action": info["first_action"],
        "candidates": kb.candidates_for_signature(sig),
        "ambiguous": SHORT_OHMS <= r_to_gnd <= OPEN_OHMS,
    }


# --------------------------------------------------------------------------- #
# Fault localization
# --------------------------------------------------------------------------- #
def localize_fault(readings: dict, test_points: dict, evaluate_fn, graph=None) -> dict:
    """Find the topmost root fault(s) and suppress downstream consequences.

    A failed node is a ROOT fault if none of its measured power-tree ancestors
    also failed; otherwise it is a CONSEQUENCE of the highest failing ancestor.
    """
    g = _g(graph)
    tree, boot = g["tree"], g["boot_critical"]
    statuses = classify(readings, test_points, evaluate_fn)
    failed = {k for k, s in statuses.items() if s == "fail" and k in tree}
    warned = {k for k, s in statuses.items() if s == "warn" and k in tree}

    root_faults, consequences = [], []
    for node in failed:
        failing_ancestor = None
        for anc in ancestors(node, graph):
            if anc in failed:
                failing_ancestor = anc  # keep walking; last one = highest failing
        if failing_ancestor is None:
            root_faults.append(node)
        else:
            consequences.append({"node": node, "explained_by": failing_ancestor})

    # Rank root faults: closest to ROOT first (fewest ancestors), critical first
    def depth(n):
        return sum(1 for _ in ancestors(n, graph))
    root_faults.sort(key=lambda n: (depth(n), n not in boot))

    # Verdict
    measured_critical = [k for k in boot if k in statuses]
    critical_failed = [k for k in boot if statuses.get(k) == "fail"]
    if not readings:
        verdict = "no_data"
    elif critical_failed:
        verdict = "power_fault_localized"
    elif len(measured_critical) >= 3 and not critical_failed and not failed:
        # All measured boot-critical rails pass -> not a power DAA
        verdict = "power_ok_escalate"
    elif failed:
        verdict = "non_critical_fault"
    else:
        verdict = "inconclusive"

    return {
        "statuses": statuses,
        "root_faults": root_faults,
        "consequences": consequences,
        "marginal": sorted(warned),
        "verdict": verdict,
        "measured_critical": measured_critical,
        "critical_failed": critical_failed,
    }


def next_probe(readings: dict, complaint: str, test_points: dict, evaluate_fn, graph=None) -> dict | None:
    """Guided minimal-probe: the single best next node to measure.

    Walk the complaint's branch top-down and return the first UNMEASURED node
    whose parent is either ROOT or already measured PASS/WARN. If a measured
    parent already FAILED, we've localized — return None (stop probing)."""
    g = _g(graph)
    tree, root = g["tree"], g["root"]
    branch = g["complaint_branches"].get(complaint) or g["boot_critical"]
    statuses = classify(readings, test_points, evaluate_fn)

    for node in branch:
        if node in readings:
            continue  # already measured
        parent = tree.get(node, {}).get("parent")
        parent_status = statuses.get(parent) if parent != root else "pass"
        if parent == root or parent is None or parent_status in ("pass", "warn", None):
            tp = test_points.get(node, {})
            return {
                "node": node,
                "tp": tp.get("tp"),
                "name": tp.get("name"),
                "loc": tp.get("loc"),
                "spec": {"lsl": tp.get("lsl"), "nom": tp.get("nom"),
                         "usl": tp.get("usl"), "unit": tp.get("unit")},
                "rationale": _probe_rationale(node, parent, parent_status, root),
            }
    return None


def _probe_rationale(node, parent, parent_status, root=ROOT):
    if parent == root:
        return "Start at the board's power input — confirm power is actually reaching the board."
    return (f"Its upstream source measured OK, so probe here next to see if the fault "
            f"is at this stage or further downstream.")


# --------------------------------------------------------------------------- #
# Deduction — fuse localization + signatures + knowledge base + schematic
# --------------------------------------------------------------------------- #
# Observation keywords that bias mechanism ranking (from visual/environmental notes).
_OBS_BOOST = {
    "eos": ["burn", "burnt", "char", "scorch", "smell", "melt", "smoke", "surge", "lightning"],
    "corrosion": ["corros", "rust", "water", "liquid", "moist", "wet", "condens", "oxid"],
    "electrochemical_migration": ["dendrite", "green", "residue", "contamin", "humid"],
    "mlcc_crack": ["crack", "flex", "chip", "ceramic", "cap "],
    "solder_joint_fatigue": ["intermittent", "cold", "reflow", "bga", "reball", "wiggle", "tap"],
    "electrolytic_cap_wearout": ["bulg", "ripple", "reboot", "brown", "leak"],
}


def _mech_score(mech_id, rank, obs_text):
    """Higher = more likely. Base from signature rank, plus observation boosts."""
    score = max(0, 5 - rank)  # earlier in candidate list = higher base
    ot = (obs_text or "").lower()
    for kw in _OBS_BOOST.get(mech_id, []):
        if kw in ot:
            score += 4
            break
    return score


def deduce(readings: dict, test_points: dict, evaluate_fn, schematic_db: dict,
           observations: str = "", resistances: dict | None = None, graph=None) -> dict:
    """Produce ranked, cited failure hypotheses for the localized fault(s).

    `resistances` optionally maps node_key -> R-to-ground (Ohms) so dead rails
    can be resolved to open vs short. `observations` is free-text visual/
    environmental notes that bias mechanism ranking.
    """
    resistances = resistances or {}
    g = _g(graph)
    tree = g["tree"]
    loc = localize_fault(readings, test_points, evaluate_fn, graph)
    hypotheses = []

    targets = loc["root_faults"] or [k for k, s in loc["statuses"].items()
                                      if s in ("fail", "warn") and k in tree]

    for node in targets:
        tp = test_points.get(node, {})
        sig = signature_for(node, readings, test_points, evaluate_fn,
                            r_to_gnd=resistances.get(node))
        needs_resistance = sig == "dead_unknown"
        cand_ids = []
        if sig and sig in kb.ELECTRICAL_SIGNATURES:
            cand_ids = kb.ELECTRICAL_SIGNATURES[sig]["candidates"]
        elif needs_resistance:
            # Both open and short are possible until we probe R-to-GND
            cand_ids = (kb.ELECTRICAL_SIGNATURES[kb.SIG_DEAD_OPEN]["candidates"]
                        + kb.ELECTRICAL_SIGNATURES[kb.SIG_DEAD_SHORT]["candidates"])

        # Score & assemble mechanism list
        mechs = []
        seen = set()
        for rank, mid in enumerate(cand_ids):
            if mid in seen:
                continue
            seen.add(mid)
            rec = kb.mechanism(mid)
            if not rec:
                continue
            rec["likelihood_score"] = _mech_score(mid, rank, observations)
            mechs.append(rec)
        mechs.sort(key=lambda m: m["likelihood_score"], reverse=True)

        # Board-specific context from the schematic DB (keyed by TP short name)
        sch = schematic_db.get(tp.get("tp"), {})

        hypotheses.append({
            "node": node,
            "rail": f"{tp.get('tp')} — {tp.get('name')}",
            "location": tp.get("loc"),
            "signature": sig,
            "signature_label": (kb.ELECTRICAL_SIGNATURES.get(sig, {}).get("label")
                                if sig in kb.ELECTRICAL_SIGNATURES else
                                "Dead rail — measure resistance to ground to call open vs short"),
            "needs_resistance_probe": needs_resistance,
            "board_fail_action": tp.get("fail_action"),
            "schematic_path": sch.get("schematic_path"),
            "ic": sch.get("ic"),
            "component_diagnostics": sch.get("component_diagnostics", []),
            "mechanisms": mechs,
        })

    return {
        "verdict": loc["verdict"],
        "verdict_text": _verdict_text(loc),
        "root_faults": loc["root_faults"],
        "consequences": loc["consequences"],
        "marginal": loc["marginal"],
        "hypotheses": hypotheses,
    }


def _verdict_text(loc: dict) -> str:
    v = loc["verdict"]
    if v == "no_data":
        return "No measurements yet. Start the guided probe at the PoE input."
    if v == "power_fault_localized":
        n = len(loc["root_faults"])
        return (f"Power fault localized to {n} root cause"
                f"{'s' if n != 1 else ''}. Downstream dead rails are explained by it.")
    if v == "power_ok_escalate":
        return ("All measured boot-critical rails are within spec. This is likely NOT a "
                "power DAA — escalate to boot/firmware/eMMC analysis via UART.")
    if v == "non_critical_fault":
        return "Fault found on a non-boot-critical rail — the unit may boot but a function is impaired."
    return "Inconclusive so far — continue the guided probe sequence."


# --------------------------------------------------------------------------- #
# Report block
# --------------------------------------------------------------------------- #
def daa_summary(readings: dict, test_points: dict, evaluate_fn, schematic_db: dict,
                observations: str = "", resistances: dict | None = None,
                complaint: str = "DEAD", graph=None) -> dict:
    """Structured DAA localization block for inclusion in the FA report."""
    d = deduce(readings, test_points, evaluate_fn, schematic_db, observations, resistances, graph)
    top = d["hypotheses"][0] if d["hypotheses"] else None
    return {
        "complaint": COMPLAINTS.get(complaint, complaint),
        "verdict": d["verdict"],
        "verdict_text": d["verdict_text"],
        "primary_fault_rail": top["rail"] if top else None,
        "primary_signature": top["signature_label"] if top else None,
        "top_mechanism": (top["mechanisms"][0]["name"] if top and top["mechanisms"] else None),
        "root_faults": d["root_faults"],
        "consequences_suppressed": [c["node"] for c in d["consequences"]],
        "hypotheses": d["hypotheses"],
    }
