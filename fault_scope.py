"""Fault scoping — technically accurate root-cause analysis for a failing rail.

DESIGN PRINCIPLE: EVERY CLAIM MUST BE TRACEABLE
-----------------------------------------------
An earlier version of this module ranked "suspect components" by how close their
OCR'd designators were drawn to a net on the schematic image. That was removed:
proximity on a drawing is not connectivity, so those rankings (C606, C613, ...)
asserted a relationship that no data in this tool could support.

Everything below is derived from one of three traceable sources, and each result
is tagged with which one:

  AUTHORITATIVE  - human-authored, schematic-derived content in the board pack:
                   schematic_path, ic, key_components, failure_modes,
                   component_diagnostics, related_tps, and the power-tree edges.
                   100% coverage on Snowbird for the first five.
  MEASURED       - the technician's own readings, evaluated against KGU limits.
  REFERENCE      - general physics-of-failure knowledge from the cited
                   knowledge base, selected by electrical signature.

OCR'd schematic text is used ONLY for navigation (finding the right sheet and
locating a label to zoom to). It never becomes a diagnosis.
"""

from __future__ import annotations

import io
import json
import os
import re

import daa_knowledge_base as kb
import schematic_index as si

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = ImageDraw = None

SRC_AUTHORITATIVE = "authoritative"   # from the board pack / schematic
SRC_MEASURED = "measured"             # from this session's readings
SRC_REFERENCE = "reference"           # from the FA knowledge base

# Highlight roles for schematic annotation (authoritative nets only)
COLOR_PRIMARY = (220, 38, 99)
COLOR_UPSTREAM = (124, 58, 237)
COLOR_DOWNSTREAM = (37, 99, 235)
COLOR_RELATED = (5, 150, 105)
ROLE_COLORS = {
    "primary": COLOR_PRIMARY,
    "upstream": COLOR_UPSTREAM,
    "downstream": COLOR_DOWNSTREAM,
    "related": COLOR_RELATED,
}


# --------------------------------------------------------------------------- #
# Measurement helpers
# --------------------------------------------------------------------------- #
def to_float(val):
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Failure-mode matching — the core accurate diagnosis
# --------------------------------------------------------------------------- #
# The pack's failure_modes are keyed by measurement condition, e.g.
#   "0V", "<0.88V", ">0.99V", "Low (<1.9V)", "High (>2.05V)",
#   "Ripple >30mV", "Differs from TP579", "Present but no WiFi"
# Numeric conditions can be evaluated directly against the reading. The rest
# require additional observation, so we present them as conditional rather than
# pretending they matched.
_NUM = r"([-+]?\d+(?:\.\d+)?)"
_COND_PATTERNS = [
    ("zero",    re.compile(r"^\s*0\s*[VWA]?\s*$", re.I)),
    ("both_zero", re.compile(r"^\s*both\s+0\s*[VWA]?\s*$", re.I)),
    ("lt",      re.compile(rf"<\s*{_NUM}\s*([mkM]?[VWAΩ])?", re.I)),
    ("gt",      re.compile(rf">\s*{_NUM}\s*([mkM]?[VWAΩ])?", re.I)),
]


def classify_condition(cond: str) -> dict:
    """Turn a failure_modes key into something evaluable.

    Returns {"kind": "zero"|"lt"|"gt"|"low"|"high"|"ripple"|"contextual",
             "threshold": float|None, "raw": cond}
    """
    c = (cond or "").strip()
    low = c.lower()

    if _COND_PATTERNS[0][1].match(c) or _COND_PATTERNS[1][1].match(c):
        return {"kind": "zero", "threshold": 0.0, "raw": c}

    # Ripple conditions are AC measurements — a DC reading can't confirm them.
    if "ripple" in low or "oscillat" in low:
        return {"kind": "ripple", "threshold": None, "raw": c}

    m = _COND_PATTERNS[2][1].search(c)
    if m:
        return {"kind": "lt", "threshold": float(m.group(1)), "raw": c}
    m = _COND_PATTERNS[3][1].search(c)
    if m:
        return {"kind": "gt", "threshold": float(m.group(1)), "raw": c}

    if low in ("low", "low output", "low voltage", "out of spec"):
        return {"kind": "low", "threshold": None, "raw": c}
    if low.startswith("high"):
        return {"kind": "high", "threshold": None, "raw": c}

    return {"kind": "contextual", "threshold": None, "raw": c}


def match_failure_modes(tp: dict, value, failure_modes: dict) -> dict:
    """Evaluate the pack's failure modes against an actual measurement.

    Returns {"matched": [...], "conditional": [...], "value": float|None}.
    `matched` entries are AUTHORITATIVE diagnoses whose condition the reading
    provably satisfies. `conditional` entries need further observation, and are
    labelled as such instead of being presented as conclusions.
    """
    v = to_float(value)
    lsl, usl = tp.get("lsl"), tp.get("usl")
    matched, conditional = [], []

    for cond, guidance in (failure_modes or {}).items():
        info = classify_condition(cond)
        kind, thr = info["kind"], info["threshold"]
        hit = False
        why = ""

        if v is not None:
            if kind == "zero":
                # Treat "dead" generously: at/near zero relative to the spec floor
                floor = float(lsl) if isinstance(lsl, (int, float)) else 0.0
                hit = v == 0 or (floor and v <= floor * 0.25)
                why = f"measured {v} ≈ 0"
            elif kind == "lt" and thr is not None:
                hit = v < thr
                why = f"measured {v} < {thr}"
            elif kind == "gt" and thr is not None:
                hit = v > thr
                why = f"measured {v} > {thr}"
            elif kind == "low" and isinstance(lsl, (int, float)):
                hit = v < float(lsl)
                why = f"measured {v} below LSL {lsl}"
            elif kind == "high" and isinstance(usl, (int, float)):
                hit = v > float(usl)
                why = f"measured {v} above USL {usl}"

        entry = {"condition": cond, "guidance": guidance, "kind": kind,
                 "threshold": thr, "why": why, "source": SRC_AUTHORITATIVE}
        if hit:
            matched.append(entry)
        else:
            conditional.append(entry)

    # Most specific first: explicit numeric thresholds before generic low/high
    order = {"zero": 0, "lt": 1, "gt": 1, "low": 2, "high": 2, "ripple": 3, "contextual": 4}
    matched.sort(key=lambda e: order.get(e["kind"], 9))
    conditional.sort(key=lambda e: order.get(e["kind"], 9))
    return {"matched": matched, "conditional": conditional, "value": v}


# --------------------------------------------------------------------------- #
# Authoritative topology scope
# --------------------------------------------------------------------------- #
def net_name_for(tp_key: str, tp: dict | None = None) -> str | None:
    """Schematic net label for a rail: V_TP579_VDD_CX -> VDD_CX.

    Used to locate the rail on a sheet, because TPxxx labels frequently appear
    only on test-point summary sheets while the net label is printed inside the
    circuit that generates it.
    """
    m = re.fullmatch(r"V_TP\d+_(.+)", (tp_key or "").upper())
    if m:
        return m.group(1)
    m = re.fullmatch(r"V_(.+)", (tp_key or "").upper())
    if m:
        return m.group(1)
    return None


def subcircuit(tp_key: str, test_points: dict, graph: dict, schematic_db: dict) -> dict:
    """The rail's electrical neighbourhood — entirely from the board pack."""
    tp = (test_points or {}).get(tp_key, {}) or {}
    tree = (graph or {}).get("tree") or {}
    root = (graph or {}).get("root") or "__SOURCE__"
    parent = (tree.get(tp_key) or {}).get("parent")
    children = [k for k, v in tree.items() if v.get("parent") == tp_key]
    circuit = (schematic_db or {}).get(tp.get("tp"), {}) or {}

    def _lab(key):
        t = (test_points or {}).get(key, {}) or {}
        return {"key": key, "tp": t.get("tp"), "name": t.get("name"),
                "unit": t.get("unit"), "lsl": t.get("lsl"), "nom": t.get("nom"),
                "usl": t.get("usl"), "subsystem": t.get("subsystem")}

    return {
        "tp_key": tp_key,
        "tp": tp.get("tp"),
        "name": tp.get("name"),
        "group": tp.get("group"),
        "phase": tp.get("phase"),
        "subsystem": tp.get("subsystem"),
        "loc": tp.get("loc"),
        "step": tp.get("step"),
        "spec": {"lsl": tp.get("lsl"), "nom": tp.get("nom"), "usl": tp.get("usl"),
                 "unit": tp.get("unit")},
        "fail_action": tp.get("fail_action"),
        "net": net_name_for(tp_key, tp),
        "upstream": None if not parent or parent == root else _lab(parent),
        "source_is_external": parent == root,
        "downstream": [_lab(c) for c in children],
        "circuit_name": circuit.get("circuit_name"),
        "schematic_path": circuit.get("schematic_path"),
        "ic": circuit.get("ic"),
        "description": circuit.get("description"),
        "key_components": circuit.get("key_components") or [],
        "failure_modes": circuit.get("failure_modes") or {},
        "component_diagnostics": circuit.get("component_diagnostics") or [],
        "related_tps": circuit.get("related_tps") or [],
        "source": SRC_AUTHORITATIVE,
    }


def history_for(program: str, tp_label: str | None) -> dict:
    """How often this rail has failed in past debug reports (MEASURED history)."""
    from program_config import get_ml_model_path
    out = {"count": 0, "total_reports": 0, "subsystems": {}}
    try:
        path = get_ml_model_path(program)
        if not path or not os.path.isfile(path):
            return out
        with open(path, encoding="utf-8") as f:
            model = json.load(f) or {}
    except Exception:
        return out
    counts = model.get("failure_counts") or {}
    out["total_reports"] = int(model.get("total_reports") or 0)
    out["count"] = int(counts.get(tp_label, 0) or 0) if tp_label else 0
    out["subsystems"] = model.get("subsystem_correlations") or {}
    return out


# --------------------------------------------------------------------------- #
# Schematic navigation (OCR — navigation only, never diagnosis)
# --------------------------------------------------------------------------- #
def locate_net(program: str, scope: dict, index: dict | None = None) -> list:
    """Find sheets where this rail can be seen, best first.

    Returns [{filename, title, anchor, box, component_count, is_circuit_sheet}].
    Prefers sheets that actually draw components (a real circuit page) over
    test-point summary tables.
    """
    index = index or si.build_index(program)
    anchors = [a for a in (scope.get("net"), scope.get("tp")) if a]
    if not anchors:
        return []
    out = []
    for d in index.get("documents", []):
        for s in d.get("sheets", []):
            boxes = s.get("ocr_boxes") or {}
            comp_count = len([t for t in (s.get("designators") or [])
                              if not str(t).upper().startswith("TP")])
            for a in anchors:
                bl = boxes.get(a.upper())
                if not bl:
                    continue
                out.append({
                    "filename": d["filename"],
                    "title": d.get("title") or s.get("title") or d["filename"],
                    "page": s.get("page", 1),
                    "kind": d.get("kind", "image"),
                    "anchor": a.upper(),
                    "box": bl[0],
                    "all_boxes": bl,
                    "component_count": comp_count,
                    "is_circuit_sheet": comp_count > 0,
                })
                break  # one entry per sheet, best anchor first
    # Circuit sheets first, then richer sheets
    out.sort(key=lambda r: (not r["is_circuit_sheet"], -r["component_count"]))
    return out


def designators_near(program: str, sheet_filename: str, box, radius_px: int = 700,
                     index: dict | None = None, limit: int = 25) -> list:
    """Reference designators printed near a point on a sheet.

    NAVIGATION AID ONLY. Being drawn nearby does not mean a part is on the net;
    callers must present this as "visible in this area", never as a diagnosis.
    """
    index = index or si.build_index(program)
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    found = []
    for d in index.get("documents", []):
        if d["filename"] != sheet_filename:
            continue
        for s in d.get("sheets", []):
            for token, boxes in (s.get("ocr_boxes") or {}).items():
                if not re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]?", token):
                    continue
                if token.upper().startswith("TP"):
                    continue
                for b in boxes:
                    bx, by = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
                    dist = ((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5
                    if dist <= radius_px:
                        found.append({"designator": token, "box": b,
                                      "distance_px": round(dist, 1)})
                        break
    found.sort(key=lambda r: r["distance_px"])
    seen, out = set(), []
    for f in found:
        if f["designator"] in seen:
            continue
        seen.add(f["designator"])
        out.append(f)
    return out[:limit]


# --------------------------------------------------------------------------- #
# Schematic rendering
# --------------------------------------------------------------------------- #
def render_net_view(program: str, sheet: dict, scope: dict, zoom: float = 1.0,
                    pad: int = 700, index: dict | None = None,
                    mark_related: bool = True) -> bytes | None:
    """Render the sheet region around the rail, marking only AUTHORITATIVE items:
    the rail's own label(s) plus topological neighbours from the power tree."""
    if Image is None:
        return None
    path = os.path.join(si.schematics_dir(program), sheet["filename"])
    index = index or si.build_index(program)

    # Which tokens may we legitimately mark?
    roles = {}
    for b in sheet.get("all_boxes", [sheet["box"]]):
        roles.setdefault("primary", []).append(b)
    if mark_related:
        boxes_on_sheet = {}
        for d in index.get("documents", []):
            if d["filename"] != sheet["filename"]:
                continue
            for s in d.get("sheets", []):
                boxes_on_sheet = s.get("ocr_boxes") or {}
        def _add(role, label):
            if not label:
                return
            for b in (boxes_on_sheet.get(str(label).upper()) or [])[:2]:
                roles.setdefault(role, []).append(b)
        up = scope.get("upstream") or {}
        _add("upstream", up.get("tp"))
        _add("upstream", net_name_for(up.get("key", ""), None))
        for dn in scope.get("downstream", []):
            _add("downstream", dn.get("tp"))
        for rt in scope.get("related_tps", []):
            m = re.search(r"\bTP\d+\b", str(rt), re.I)
            if m:
                _add("related", m.group(0))

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            draw = ImageDraw.Draw(im)
            for role, boxes in roles.items():
                color = ROLE_COLORS.get(role, COLOR_PRIMARY)
                width = 6 if role == "primary" else 3
                for b in boxes:
                    draw.rectangle([b[0] - 10, b[1] - 10, b[2] + 10, b[3] + 10],
                                   outline=color, width=width)

            # Crop around the primary label
            pb = roles["primary"][0]
            eff_pad = int(pad / max(zoom, 0.05))
            box = (max(0, pb[0] - eff_pad), max(0, pb[1] - int(eff_pad * 0.7)),
                   min(im.width, pb[2] + eff_pad), min(im.height, pb[3] + int(eff_pad * 0.7)))
            im = im.crop(box)

            # Scale for legibility, capped to keep payload reasonable
            target = 1700
            if im.width < target:
                r = target / float(im.width)
                im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
            if max(im.size) > 2600:
                r = 2600 / float(max(im.size))
                im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)

            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# One-call analysis
# --------------------------------------------------------------------------- #
def analyze(program: str, tp_key: str, value, test_points: dict, graph: dict,
            schematic_db: dict, signature: str | None = None,
            index: dict | None = None) -> dict:
    """Assemble a fully traceable analysis for one rail."""
    index = index or si.build_index(program)
    tp = (test_points or {}).get(tp_key, {}) or {}
    scope = subcircuit(tp_key, test_points, graph, schematic_db)
    fm = match_failure_modes(tp, value, scope["failure_modes"])

    mechanisms = []
    if signature and signature in kb.ELECTRICAL_SIGNATURES:
        mechanisms = [m for m in
                      (kb.mechanism(x) for x in kb.ELECTRICAL_SIGNATURES[signature]["candidates"])
                      if m]

    sheets = locate_net(program, scope, index=index)
    return {
        "scope": scope,
        "measurement": {"value": fm["value"], "raw": value,
                        "spec": scope["spec"], "source": SRC_MEASURED},
        "diagnosis": fm["matched"],            # AUTHORITATIVE, condition proven
        "other_modes": fm["conditional"],     # AUTHORITATIVE, needs observation
        "mechanisms": mechanisms,             # REFERENCE
        "signature": signature,
        "signature_label": (kb.ELECTRICAL_SIGNATURES.get(signature, {}) or {}).get("label"),
        "first_action": (kb.ELECTRICAL_SIGNATURES.get(signature, {}) or {}).get("first_action"),
        "sheets": sheets,
        "history": history_for(program, scope.get("tp")),
    }
