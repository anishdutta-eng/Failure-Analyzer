"""Fault scoping — turn a failed test point into a ranked, visual root-cause
hypothesis on the actual schematic sheet.

THE PROBLEM
-----------
The debugger tells you *a rail is out of spec*. The schematic viewer shows you
*a picture*. Neither answers the question a technician actually has: **which
component do I check, and where is it on the sheet?**

WHAT THIS ADDS
--------------
Given a failing test point, this module assembles a "sub-circuit scope":

  1. Topology     — the failed rail plus its power-tree parent and children,
                    from the board pack (so context is electrical, not visual).
  2. Suspects     — ranked candidate components, fused from four sources:
                      a) the pack's key_components / failure_modes / diagnostics
                      b) the DAA knowledge base, selected by electrical
                         signature (open vs short vs droop behave differently)
                      c) historical priors learned from past debug reports
                      d) proximity association (below)
  3. Proximity    — components whose OCR'd designators sit physically NEAR the
                    failed test point on the schematic sheet. Without a netlist
                    this is the best available evidence of sub-circuit
                    membership, and on real sheets it works well because a
                    regulator's parts are drawn together.
  4. Annotation   — the sheet re-rendered with the failed net boxed in red, its
                    topological neighbours in purple, and nearby suspect
                    components in amber, then cropped to the sub-circuit.

Honest limitation: proximity is a heuristic, not connectivity. Anything derived
that way is labelled as such in the UI so nobody mistakes it for a netlist
trace. Exact component-to-rail mapping needs a netlist import (future work).
"""

from __future__ import annotations

import io
import json
import os
import re

import daa_knowledge_base as kb
import schematic_index as si

try:  # Pillow is a hard dependency of the app, but stay defensive.
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = ImageDraw = None

# Highlight roles -> RGB
COLOR_PRIMARY = (220, 38, 99)      # the failed net itself
COLOR_UPSTREAM = (124, 58, 237)    # its power source
COLOR_DOWNSTREAM = (37, 99, 235)   # what it feeds
COLOR_SUSPECT = (217, 119, 6)      # nearby candidate components
COLOR_RELATED = (5, 150, 105)      # related test points

ROLE_COLORS = {
    "primary": COLOR_PRIMARY,
    "upstream": COLOR_UPSTREAM,
    "downstream": COLOR_DOWNSTREAM,
    "suspect": COLOR_SUSPECT,
    "related": COLOR_RELATED,
}

# Component-class keywords -> the designator prefixes they'd carry on a sheet.
# Used to turn the pack's prose ("Power inductor (0.47uH)") into something we
# can actually look for among OCR'd designators.
_CLASS_PREFIXES = {
    "inductor": ("L", "FB"),
    "ferrite": ("FB", "L"),
    "bead": ("FB", "L"),
    "cap": ("C",),
    "capacitor": ("C",),
    "caps": ("C",),
    "resistor": ("R",),
    "divider": ("R",),
    "feedback": ("R",),
    "diode": ("D",),
    "rectifier": ("D",),
    "converter": ("U",),
    "regulator": ("U",),
    "ldo": ("U",),
    "controller": ("U",),
    "ic": ("U",),
    "soc": ("U",),
    "connector": ("J",),
    "rj45": ("J",),
    "jack": ("J",),
    "magnetics": ("T", "J"),
    "transformer": ("T",),
    "fuse": ("F",),
    "crystal": ("Y", "X"),
    "oscillator": ("Y", "X"),
    "led": ("LED", "D"),
    "transistor": ("Q",),
    "fet": ("Q",),
    "mosfet": ("Q",),
}


# --------------------------------------------------------------------------- #
# Historical priors
# --------------------------------------------------------------------------- #
def history_priors(program: str) -> dict:
    """Load learned failure frequencies from past debug reports.

    Returns {"test_points": {TP: count}, "subsystems": {name: count},
             "total_reports": int}. Empty when nothing has been recorded yet.
    """
    from program_config import get_ml_model_path
    try:
        path = get_ml_model_path(program)
    except Exception:
        return {"test_points": {}, "subsystems": {}, "total_reports": 0}
    if not path or not os.path.isfile(path):
        return {"test_points": {}, "subsystems": {}, "total_reports": 0}
    try:
        with open(path, encoding="utf-8") as f:
            model = json.load(f) or {}
    except Exception:
        return {"test_points": {}, "subsystems": {}, "total_reports": 0}

    counts = model.get("failure_counts") or {}
    tps = {k: v for k, v in counts.items() if re.fullmatch(r"TP\d+", str(k).strip(), re.I)}
    return {
        "test_points": tps,
        "subsystems": model.get("subsystem_correlations") or {},
        "total_reports": int(model.get("total_reports") or 0),
        "all_counts": counts,
    }


# --------------------------------------------------------------------------- #
# Topology scope
# --------------------------------------------------------------------------- #
def subcircuit(tp_key: str, test_points: dict, graph: dict, schematic_db: dict) -> dict:
    """Describe the electrical neighbourhood of a failing rail."""
    tp = (test_points or {}).get(tp_key, {}) or {}
    tree = (graph or {}).get("tree") or {}
    root = (graph or {}).get("root") or "__SOURCE__"

    parent = (tree.get(tp_key) or {}).get("parent")
    children = [k for k, v in tree.items() if v.get("parent") == tp_key]
    circuit = (schematic_db or {}).get(tp.get("tp"), {}) or {}

    def _label(key):
        t = (test_points or {}).get(key, {}) or {}
        return {"key": key, "tp": t.get("tp"), "name": t.get("name"),
                "unit": t.get("unit"), "lsl": t.get("lsl"), "usl": t.get("usl")}

    return {
        "tp_key": tp_key,
        "tp": tp.get("tp"),
        "name": tp.get("name"),
        "group": tp.get("group"),
        "phase": tp.get("phase"),
        "subsystem": tp.get("subsystem"),
        "loc": tp.get("loc"),
        "spec": {"lsl": tp.get("lsl"), "nom": tp.get("nom"), "usl": tp.get("usl"),
                 "unit": tp.get("unit")},
        "fail_action": tp.get("fail_action"),
        "upstream": None if not parent or parent == root else _label(parent),
        "source_is_external": parent == root,
        "downstream": [_label(c) for c in children],
        "circuit_name": circuit.get("circuit_name"),
        "schematic_path": circuit.get("schematic_path"),
        "ic": circuit.get("ic"),
        "description": circuit.get("description"),
        "key_components": circuit.get("key_components") or [],
        "failure_modes": circuit.get("failure_modes") or {},
        "component_diagnostics": circuit.get("component_diagnostics") or [],
        "related_tps": circuit.get("related_tps") or [],
    }


# --------------------------------------------------------------------------- #
# Proximity association on the sheet
# --------------------------------------------------------------------------- #
def _box_center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _distance(b1, b2):
    (x1, y1), (x2, y2) = _box_center(b1), _box_center(b2)
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def net_name_for(tp_key: str, tp: dict | None = None) -> str | None:
    """Derive the schematic net label for a rail.

    Test-point keys follow `V_TP<num>_<NET>` (e.g. V_TP579_VDD_CX -> VDD_CX).
    The net label is a far better anchor than the TPxxx label, because on real
    schematics the rail name is printed inside the circuit that generates it,
    while TPxxx often only appears on test-point summary sheets.
    """
    m = re.fullmatch(r"V_TP\d+_(.+)", (tp_key or "").upper())
    if m:
        return m.group(1)
    m = re.fullmatch(r"V_(.+)", (tp_key or "").upper())
    if m:
        return m.group(1)
    if tp:
        m = re.match(r"([A-Z0-9_.]{3,})", str(tp.get("name", "")).upper())
        if m:
            return m.group(1)
    return None


def neighbors_on_sheet(program: str, anchors, radius_px: int = 900,
                       index: dict | None = None, limit: int = 40,
                       components_only: bool = False) -> list:
    """Find designators drawn near any of `anchors` on each sheet.

    `anchors` may be a single token or a list (e.g. ['TP579', 'VDD_CX']).
    Returns [{filename, sheet_title, anchor, anchor_box, token, box,
    distance_px, sheet_component_count}], nearest first.
    """
    if isinstance(anchors, str):
        anchors = [anchors]
    anchors = [a.upper() for a in anchors if a]
    index = index or si.build_index(program)
    out = []
    for d in index.get("documents", []):
        for s in d.get("sheets", []):
            boxes = s.get("ocr_boxes") or {}
            comp_count = len([t for t in (s.get("designators") or [])
                              if not t.upper().startswith("TP")])
            for anchor in anchors:
                abox_list = boxes.get(anchor) or []
                if not abox_list:
                    continue
                abox = abox_list[0]
                for token, tboxes in boxes.items():
                    if token in anchors:
                        continue
                    if components_only and token.upper().startswith("TP"):
                        continue
                    # Only designator-like tokens are candidate components
                    if not re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]?", token):
                        continue
                    for tb in tboxes:
                        dist = _distance(abox, tb)
                        if dist <= radius_px:
                            out.append({
                                "filename": d["filename"],
                                "sheet_title": d.get("title") or s.get("title") or "",
                                "anchor": anchor,
                                "anchor_box": abox,
                                "token": token,
                                "box": tb,
                                "distance_px": round(dist, 1),
                                "sheet_component_count": comp_count,
                            })
    # Prefer real circuit sheets (those with components) and closer tokens
    out.sort(key=lambda r: (-min(r["sheet_component_count"], 1), r["distance_px"]))
    seen, dedup = set(), []
    for r in out:
        k = (r["filename"], r["token"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    return dedup[:limit]


# --------------------------------------------------------------------------- #
# Suspect ranking
# --------------------------------------------------------------------------- #
def _prefixes_for(text: str) -> tuple:
    t = (text or "").lower()
    pres = set()
    for kw, prefixes in _CLASS_PREFIXES.items():
        if kw in t:
            pres.update(prefixes)
    return tuple(pres)


def _token_prefix(token: str) -> str:
    m = re.match(r"^([A-Z]+)", token.upper())
    return m.group(1) if m else ""


def suspects(program: str, tp_key: str, test_points: dict, graph: dict,
             schematic_db: dict, signature: str | None = None,
             index: dict | None = None, radius_px: int = 900) -> dict:
    """Rank likely-faulty components for a failing rail.

    Fuses: the pack's own knowledge, the DAA knowledge base (selected by
    electrical signature), historical failure frequency, and sheet proximity.
    Every suspect carries `sources` so the UI can show *why* it is suspected.
    """
    scope = subcircuit(tp_key, test_points, graph, schematic_db)
    priors = history_priors(program)

    # --- 1. Mechanism candidates from the knowledge base, by signature ------
    mech_ids = []
    if signature and signature in kb.ELECTRICAL_SIGNATURES:
        mech_ids = kb.ELECTRICAL_SIGNATURES[signature]["candidates"]
    mechanisms = [kb.mechanism(m) for m in mech_ids]
    mechanisms = [m for m in mechanisms if m]

    # Which component classes does the signature implicate?
    implicated_prefixes = set()
    for m in mechanisms[:3]:  # top mechanisms carry the most weight
        implicated_prefixes.update(_prefixes_for(m.get("name", "")))
        for cause in m.get("root_causes", [])[:4]:
            implicated_prefixes.update(_prefixes_for(cause))

    # --- 2. Component classes named by the pack for THIS rail ---------------
    class_entries = []
    for comp in scope["key_components"]:
        class_entries.append({
            "component": comp,
            "prefixes": _prefixes_for(comp),
            "source": "board pack key_components",
        })
    for cd in scope["component_diagnostics"]:
        class_entries.append({
            "component": cd.get("component") or cd.get("ref"),
            "ref": cd.get("ref"),
            "prefixes": _prefixes_for(f"{cd.get('ref','')} {cd.get('component','')}"),
            "priority": cd.get("priority"),
            "check": cd.get("check"),
            "expected": cd.get("expected"),
            "if_fail": cd.get("if_fail"),
            "location": cd.get("location"),
            "tools": cd.get("tools"),
            "source": "board pack component_diagnostics",
        })

    # --- 3. Proximity evidence from the sheet -------------------------------
    # Anchor on BOTH the TP label and the net name; the net name is what
    # actually appears inside the generating circuit on real schematics.
    net = net_name_for(tp_key, (test_points or {}).get(tp_key))
    anchors = [a for a in (scope.get("tp"), net) if a]
    near = neighbors_on_sheet(program, anchors, radius_px=radius_px, index=index,
                              components_only=True) if anchors else []

    # --- 4. Score designators found near the net ---------------------------
    ranked = []
    for n in near:
        token = n["token"]
        pfx = _token_prefix(token)
        score = 0.0
        reasons = []

        # Closer on the sheet = more likely in the same sub-circuit
        prox = max(0.0, 1.0 - (n["distance_px"] / float(radius_px)))
        score += prox * 3.0
        reasons.append(f"drawn {int(n['distance_px'])}px from {n['anchor']} on "
                       f"{n['sheet_title'] or n['filename']}")

        # Signature implicates this component class
        if pfx and pfx in implicated_prefixes:
            score += 3.0
            reasons.append("component class matches the electrical signature")

        # The pack names this class for this rail
        for ce in class_entries:
            if pfx and pfx in (ce.get("prefixes") or ()):
                score += 2.0
                reasons.append(f"pack lists “{ce['component']}” for this rail")
                break

        # Another test point is context, not a suspect
        if pfx == "TP":
            score -= 2.5
            reasons.append("this is a test point, not a component")

        # Historical prior
        hist = priors.get("all_counts", {}).get(token)
        if hist:
            score += min(3.0, 1.0 + float(hist))
            reasons.append(f"seen failing in {hist} past report(s)")

        ranked.append({
            "designator": token,
            "score": round(score, 2),
            "prefix": pfx,
            "distance_px": n["distance_px"],
            "filename": n["filename"],
            "sheet_title": n["sheet_title"],
            "box": n["box"],
            "anchor_box": n["anchor_box"],
            "reasons": reasons,
            "evidence": "proximity-derived (heuristic, not a netlist trace)",
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)

    return {
        "scope": scope,
        "net_name": net,
        "anchors": anchors,
        "signature": signature,
        "signature_label": (kb.ELECTRICAL_SIGNATURES.get(signature, {}) or {}).get("label"),
        "first_action": (kb.ELECTRICAL_SIGNATURES.get(signature, {}) or {}).get("first_action"),
        "mechanisms": mechanisms,
        "component_classes": class_entries,
        "ranked_designators": ranked,
        "history": priors,
        "implicated_prefixes": sorted(implicated_prefixes),
    }


# --------------------------------------------------------------------------- #
# Highlight planning + annotation
# --------------------------------------------------------------------------- #
def highlight_plan(program: str, analysis: dict, index: dict | None = None,
                   max_suspects: int = 8) -> dict:
    """Decide what to box on which sheet.

    Returns {filename: [{token, box, role, label}]} — chooses the sheet with the
    richest evidence for the failing net.
    """
    index = index or si.build_index(program)
    scope = analysis["scope"]
    anchors = [a.upper() for a in (analysis.get("anchors") or []) if a]
    if not anchors:
        return {}

    # Collect the tokens we care about, with their role
    roles = {a: "primary" for a in anchors}
    if scope.get("upstream") and scope["upstream"].get("tp"):
        roles[str(scope["upstream"]["tp"]).upper()] = "upstream"
    for d in scope.get("downstream", []):
        if d.get("tp"):
            roles.setdefault(str(d["tp"]).upper(), "downstream")
    for rt in scope.get("related_tps", []):
        m = re.search(r"\bTP\d+\b", str(rt), re.I)
        if m:
            roles.setdefault(m.group(0).upper(), "related")
    for s in analysis.get("ranked_designators", [])[:max_suspects]:
        if s["prefix"] != "TP" and s["score"] > 0:
            roles.setdefault(s["designator"], "suspect")

    # Score each sheet: prefer real circuit sheets (with components) that
    # contain one of our anchors, then by how much of the scope they show.
    best, best_score, per_sheet = None, -1.0, {}
    for d in index.get("documents", []):
        for s in d.get("sheets", []):
            boxes = s.get("ocr_boxes") or {}
            if not any(a in boxes for a in anchors):
                continue
            comp_count = len([t for t in (s.get("designators") or [])
                              if not t.upper().startswith("TP")])
            hits = []
            for token, role in roles.items():
                for b in (boxes.get(token) or [])[:2]:
                    hits.append({"token": token, "box": b, "role": role, "label": token})
            if not hits:
                continue
            per_sheet[d["filename"]] = hits
            # A sheet showing actual components is far more useful than a
            # test-point summary sheet, so weight that heavily.
            score = len(hits) + (25.0 if comp_count else 0.0) + min(comp_count, 40) * 0.1
            if score > best_score:
                best, best_score = d["filename"], score

    if not best:
        return {}
    return {best: per_sheet[best]}


def annotate_sheet(path: str, highlights: list, crop: bool = True,
                   pad: int = 420, scale: float = 1.6,
                   max_px: int = 2600) -> bytes | None:
    """Draw the highlight boxes on a raster sheet and crop to the sub-circuit."""
    if Image is None or not highlights:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            draw = ImageDraw.Draw(im)

            for h in highlights:
                x0, y0, x1, y1 = h["box"]
                color = ROLE_COLORS.get(h.get("role", "suspect"), COLOR_SUSPECT)
                w = 5 if h.get("role") == "primary" else 3
                # Box the token with a little breathing room
                draw.rectangle([x0 - 8, y0 - 8, x1 + 8, y1 + 8], outline=color, width=w)
                # Role tick above the box
                if h.get("role") == "primary":
                    draw.rectangle([x0 - 8, y0 - 30, x0 + 78, y0 - 10], fill=color)

            if crop:
                xs0 = min(h["box"][0] for h in highlights)
                ys0 = min(h["box"][1] for h in highlights)
                xs1 = max(h["box"][2] for h in highlights)
                ys1 = max(h["box"][3] for h in highlights)
                box = (max(0, int(xs0) - pad), max(0, int(ys0) - pad),
                       min(im.width, int(xs1) + pad), min(im.height, int(ys1) + pad))
                im = im.crop(box)

            if scale and scale != 1.0:
                im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
            if max(im.size) > max_px:  # keep payloads sane
                ratio = max_px / float(max(im.size))
                im = im.resize((int(im.width * ratio), int(im.height * ratio)), Image.LANCZOS)

            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


def analyze_failure(program: str, tp_key: str, test_points: dict, graph: dict,
                    schematic_db: dict, signature: str | None = None,
                    index: dict | None = None) -> dict:
    """One-call convenience: scope + suspects + highlight plan + annotated image."""
    index = index or si.build_index(program)
    analysis = suspects(program, tp_key, test_points, graph, schematic_db,
                        signature=signature, index=index)
    plan = highlight_plan(program, analysis, index=index)
    image = None
    used_file = None
    if plan:
        used_file = next(iter(plan))
        image = annotate_sheet(os.path.join(si.schematics_dir(program), used_file),
                               plan[used_file])
    analysis["highlight_plan"] = plan
    analysis["annotated_file"] = used_file
    analysis["annotated_png"] = image
    return analysis
