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
POWER_TREE = {
    "V_POE_POWER_RAIL":        {"parent": ROOT,                 "verified": True},
    "V_TP1205_POE_5V":         {"parent": "V_POE_POWER_RAIL",   "verified": True},
    "V_TP55_STBY":             {"parent": "V_POE_POWER_RAIL",   "verified": True},
    # Miami core domain (Buck 1 from 5V bus)
    "V_TP579_VDD_CX":          {"parent": "V_TP1205_POE_5V",    "verified": True},
    "V_TP27_VDD_SOC_CX":       {"parent": "V_TP579_VDD_CX",     "verified": True},
    "V_TP29_VDD_SOC_MX":       {"parent": "V_TP579_VDD_CX",     "verified": True},
    "V_TP578_VDD1V95_PMU":     {"parent": "V_TP1205_POE_5V",    "verified": True},
    # DDR4 (Buck 3 from 5V; VPP sequenced after VDD_DDR)
    "V_TP574_VDD_DDR":         {"parent": "V_TP1205_POE_5V",    "verified": True},
    "V_TP576_VDD_LDO_2P5_VPP": {"parent": "V_TP1205_POE_5V",    "verified": True,
                                "seq_after": "V_TP574_VDD_DDR"},
    # Shared 1.8V (Buck 2) and analog LDOs
    "V_TP503_VDD1P8_NAPA":     {"parent": "V_TP1205_POE_5V",    "verified": True},
    "V_TP28_VAA_0P8":          {"parent": "V_TP503_VDD1P8_NAPA", "verified": False},
    "V_TP36_VAA_1P2":          {"parent": "V_TP503_VDD1P8_NAPA", "verified": False},
    # Ethernet PHY (Buck 5 from 5V; also needs shared 1.8V)
    "V_TP504_VDD1P05_NAPA":    {"parent": "V_TP1205_POE_5V",    "verified": True,
                                "co_requires": ["V_TP503_VDD1P8_NAPA"]},
    # Waikiki WiFi (Buck 6 from 5V) + PCIe rails
    "V_TP573_DVDD3P3":         {"parent": "V_TP1205_POE_5V",    "verified": True},
    "V_TP535_DVDD5":           {"parent": "V_TP1205_POE_5V",    "verified": True},
    "V_TP589_DVDD3P3_BZT":     {"parent": "V_TP573_DVDD3P3",    "verified": True},
    "V_TP34_VDD_PCIE_0P925":   {"parent": "V_TP573_DVDD3P3",    "verified": False},
    "V_TP30_VDD_PCIE_1P8":     {"parent": "V_TP573_DVDD3P3",    "verified": False},
    "V_TP31_VDD_1V8_PX3":      {"parent": "V_TP503_VDD1P8_NAPA", "verified": False},
    # RF power amps (Buck 8 / Buck 7 from 5V)
    "V_TP569_VDD_XPA":         {"parent": "V_TP1205_POE_5V",    "verified": True},
    "V_TP577_AVDD3P3_2G":      {"parent": "V_TP1205_POE_5V",    "verified": True},
    # LED (from a 3.3V bus — parentage inferred, review)
    "V_TP590_LED":             {"parent": "V_TP573_DVDD3P3",    "verified": False},
}

# Boot-critical chain: if any of these fail, the unit is dead / won't boot.
# Ordered top-down = the guided minimal-probe sequence for a "dead" complaint.
BOOT_CRITICAL = [
    "V_POE_POWER_RAIL",
    "V_TP1205_POE_5V",
    "V_TP579_VDD_CX",
    "V_TP27_VDD_SOC_CX",
    "V_TP29_VDD_SOC_MX",
    "V_TP578_VDD1V95_PMU",
    "V_TP574_VDD_DDR",
    "V_TP576_VDD_LDO_2P5_VPP",
    "V_TP503_VDD1P8_NAPA",
]

# Complaint -> prioritized probe branch (top-down).
COMPLAINT_BRANCHES = {
    "DEAD": BOOT_CRITICAL,
    "DOA": BOOT_CRITICAL,
    "REBOOTS": ["V_POE_POWER_RAIL", "V_TP1205_POE_5V", "V_TP579_VDD_CX", "V_TP574_VDD_DDR"],
    "NO_WIFI": ["V_TP1205_POE_5V", "V_TP573_DVDD3P3", "V_TP535_DVDD5",
                "V_TP589_DVDD3P3_BZT", "V_TP30_VDD_PCIE_1P8", "V_TP503_VDD1P8_NAPA"],
    "NO_ETHERNET": ["V_TP1205_POE_5V", "V_TP503_VDD1P8_NAPA", "V_TP504_VDD1P05_NAPA"],
    "NO_RF": ["V_TP1205_POE_5V", "V_TP569_VDD_XPA", "V_TP577_AVDD3P3_2G"],
}

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
def ancestors(node: str):
    """Yield power-tree ancestors of `node`, nearest first, up to (not incl.) ROOT."""
    seen = set()
    cur = POWER_TREE.get(node, {}).get("parent")
    while cur and cur != ROOT and cur not in seen:
        seen.add(cur)
        yield cur
        cur = POWER_TREE.get(cur, {}).get("parent")


def children_of(node: str):
    return [k for k, v in POWER_TREE.items() if v.get("parent") == node]


def validate_tree(test_points: dict) -> dict:
    """Integrity check: every voltage test point should be in the tree, parents
    must exist, and there must be no cycles. Returns issues + unverified edges."""
    issues = []
    unverified = []
    # Cycle / missing-parent check
    for node, meta in POWER_TREE.items():
        parent = meta.get("parent")
        if parent != ROOT and parent not in POWER_TREE:
            issues.append(f"{node}: parent '{parent}' not in tree")
        if not meta.get("verified", False):
            unverified.append(node)
        # walk to root to detect cycles
        seen, cur = set(), node
        while cur and cur != ROOT:
            if cur in seen:
                issues.append(f"cycle detected at {cur}")
                break
            seen.add(cur)
            cur = POWER_TREE.get(cur, {}).get("parent")
    # Coverage: voltage TPs not modeled
    for key, tp in test_points.items():
        if key in NON_NODE_KEYS:
            continue
        if str(tp.get("unit", "")).upper() != "V":
            continue
        if tp.get("monitor"):
            continue  # monitor-only pins (e.g. USB-C orientation) are not power rails
        if key not in POWER_TREE:
            issues.append(f"{key}: voltage test point not modeled in POWER_TREE")
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
def localize_fault(readings: dict, test_points: dict, evaluate_fn) -> dict:
    """Find the topmost root fault(s) and suppress downstream consequences.

    A failed node is a ROOT fault if none of its measured power-tree ancestors
    also failed; otherwise it is a CONSEQUENCE of the highest failing ancestor.
    """
    statuses = classify(readings, test_points, evaluate_fn)
    failed = {k for k, s in statuses.items() if s == "fail" and k in POWER_TREE}
    warned = {k for k, s in statuses.items() if s == "warn" and k in POWER_TREE}

    root_faults, consequences = [], []
    for node in failed:
        failing_ancestor = None
        for anc in ancestors(node):
            if anc in failed:
                failing_ancestor = anc  # keep walking; last one = highest failing
        if failing_ancestor is None:
            root_faults.append(node)
        else:
            consequences.append({"node": node, "explained_by": failing_ancestor})

    # Rank root faults: closest to ROOT first (fewest ancestors), critical first
    def depth(n):
        return sum(1 for _ in ancestors(n))
    root_faults.sort(key=lambda n: (depth(n), n not in BOOT_CRITICAL))

    # Verdict
    measured_critical = [k for k in BOOT_CRITICAL if k in statuses]
    critical_failed = [k for k in BOOT_CRITICAL if statuses.get(k) == "fail"]
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


def next_probe(readings: dict, complaint: str, test_points: dict, evaluate_fn) -> dict | None:
    """Guided minimal-probe: the single best next node to measure.

    Walk the complaint's branch top-down and return the first UNMEASURED node
    whose parent is either ROOT or already measured PASS/WARN. If a measured
    parent already FAILED, we've localized — return None (stop probing)."""
    branch = COMPLAINT_BRANCHES.get(complaint, BOOT_CRITICAL)
    statuses = classify(readings, test_points, evaluate_fn)

    for node in branch:
        if node in readings:
            continue  # already measured
        parent = POWER_TREE.get(node, {}).get("parent")
        parent_status = statuses.get(parent) if parent != ROOT else "pass"
        if parent == ROOT or parent is None or parent_status in ("pass", "warn", None):
            tp = test_points.get(node, {})
            return {
                "node": node,
                "tp": tp.get("tp"),
                "name": tp.get("name"),
                "loc": tp.get("loc"),
                "spec": {"lsl": tp.get("lsl"), "nom": tp.get("nom"),
                         "usl": tp.get("usl"), "unit": tp.get("unit")},
                "rationale": _probe_rationale(node, parent, parent_status),
            }
    return None


def _probe_rationale(node, parent, parent_status):
    if parent == ROOT:
        return "Start at the board's power input — confirm power is actually reaching the board."
    pname = POWER_TREE.get(parent, {})
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
           observations: str = "", resistances: dict | None = None) -> dict:
    """Produce ranked, cited failure hypotheses for the localized fault(s).

    `resistances` optionally maps node_key -> R-to-ground (Ohms) so dead rails
    can be resolved to open vs short. `observations` is free-text visual/
    environmental notes that bias mechanism ranking.
    """
    resistances = resistances or {}
    loc = localize_fault(readings, test_points, evaluate_fn)
    hypotheses = []

    targets = loc["root_faults"] or [k for k, s in loc["statuses"].items()
                                      if s in ("fail", "warn") and k in POWER_TREE]

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
                complaint: str = "DEAD") -> dict:
    """Structured DAA localization block for inclusion in the FA report."""
    d = deduce(readings, test_points, evaluate_fn, schematic_db, observations, resistances)
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
