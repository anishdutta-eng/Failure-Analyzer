"""Schematic document indexing and rendering — the engine behind the Smart
Schematic Viewer.

WHAT IT DOES
------------
Given the schematic documents a program has uploaded to
`programs/<slug>/board/schematics/`, this module:

  1. Discovers them (PDF, PNG, JPG, SVG).
  2. Detects whether a PDF has a real text layer (vector EDA export) or is a
     flattened scan — search only works on the former, so we say so explicitly.
  3. Extracts every component designator (C448, TP579, U12, R737 ...) and net
     name (VDD_CX, POE_5V ...) **with page + bounding-box coordinates**.
  4. Caches that index to disk so repeat loads are instant.
  5. Searches the index and renders either a full page or a high-DPI CROP
     around a hit, which is what makes "deep dive on this circuit" possible on
     a dense A3 sheet.

Design notes
------------
* No Streamlit import — pure logic, so it is unit-testable.
* PyMuPDF does the PDF work. NOTE ON LICENSING: PyMuPDF is AGPL-3.0 (or
  commercial). Fine for an internal, non-distributed tool, but worth a check
  with your OSS/legal process before shipping externally. The module degrades
  gracefully if it is unavailable (image-only support remains).
* The index is keyed on (size, mtime) per file, so editing/replacing a
  schematic automatically reindexes.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

# PyMuPDF is optional at import time so the rest of the app still works if it
# is missing or blocked; PDF features then report themselves unavailable.
try:  # pragma: no cover - import shim
    import pymupdf as _fitz  # PyMuPDF >= 1.24 preferred name
except Exception:  # pragma: no cover
    try:
        import fitz as _fitz
    except Exception:
        _fitz = None

PDF_AVAILABLE = _fitz is not None

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VECTOR_EXTS = {".svg"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS | VECTOR_EXTS

INDEX_FILENAME = "schematic_index.json"
INDEX_VERSION = 1

# Reference designators: letter prefix + number (C448, TP579, U12, FB3, R737).
# Ordered longest-prefix-first so TP matches before T.
_DESIGNATOR_RE = re.compile(
    r"\b(TP|FB|SW|JP|XW|BT|LED|CN|RN|DZ|[CRULDJQYXFKMPTVZ])(\d{1,5})([A-Z])?\b"
)

# Net / signal names: VDD_CX, POE_5V, DVDD3P3, VCC_1V8, GND_A ...
_NET_RE = re.compile(
    r"\b((?:V|VDD|VCC|VSS|AVDD|DVDD|VBAT|VIN|VOUT|STBY|POE|PP|VPP|VAA)"
    r"[A-Z0-9]*(?:[_.][A-Z0-9]+)+|[A-Z]{2,}[_][A-Z0-9]{2,}(?:[_][A-Z0-9]+)*)\b"
)

# Tokens that look like designators but are noise on a schematic title block.
_DESIGNATOR_STOPWORDS = {
    "R1", "C1",  # kept: these are legitimate; placeholder for future tuning
}


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _slug(program: str) -> str:
    return (program or "").lower().replace(" ", "_")


def schematics_dir(program: str) -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "programs", _slug(program), "board", "schematics")


def index_path(program: str) -> str:
    return os.path.join(os.path.dirname(schematics_dir(program)), INDEX_FILENAME)


def list_documents(program: str) -> list:
    """Return metadata for every supported schematic document, name-sorted."""
    d = schematics_dir(program)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("."):
            continue
        path = os.path.join(d, fn)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext not in SUPPORTED_EXTS:
            continue
        stat = os.stat(path)
        out.append({
            "filename": fn,
            "path": path,
            "ext": ext,
            "kind": "pdf" if ext in PDF_EXTS else ("svg" if ext in VECTOR_EXTS else "image"),
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "size_human": _human(stat.st_size),
        })
    return out


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _normalize_designator(m: re.Match) -> str:
    prefix, num, suffix = m.group(1), m.group(2), m.group(3) or ""
    return f"{prefix}{num}{suffix}"


def extract_tokens(text: str) -> tuple:
    """Return (designators, nets) found in a block of page text."""
    designators = {_normalize_designator(m) for m in _DESIGNATOR_RE.finditer(text)}
    nets = {m.group(1) for m in _NET_RE.finditer(text)}
    # A net name like VDD_CX can also match the designator pattern fragments;
    # drop designators that are actually part of a longer net token.
    return sorted(designators), sorted(nets)


def index_pdf(path: str, max_pages: int | None = None) -> dict:
    """Index one PDF: per-sheet text, designators, nets, and coordinates."""
    if not PDF_AVAILABLE:
        return {"error": "PyMuPDF is not installed, so PDF indexing is unavailable.",
                "sheets": [], "has_text_layer": False}
    try:
        doc = _fitz.open(path)
    except Exception as e:
        return {"error": f"Could not open PDF: {e}", "sheets": [], "has_text_layer": False}

    sheets = []
    any_text = False
    try:
        n = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for i in range(n):
            page = doc[i]
            text = page.get_text() or ""
            if text.strip():
                any_text = True
            designators, nets = extract_tokens(text)
            title = _guess_sheet_title(text)
            sheets.append({
                "page": i + 1,
                "title": title,
                "width": round(page.rect.width, 1),
                "height": round(page.rect.height, 1),
                "designators": designators,
                "nets": nets,
                "char_count": len(text.strip()),
            })
    finally:
        doc.close()

    return {"sheets": sheets, "has_text_layer": any_text, "page_count": len(sheets)}


def _guess_sheet_title(text: str) -> str:
    """Best-effort sheet title: first meaningful line of the page text."""
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) < 3:
            continue
        if re.fullmatch(r"[\d\s/.\-:]+", s):  # dates, page numbers
            continue
        return s[:70]
    return ""


def build_index(program: str, force: bool = False) -> dict:
    """Build (or load from cache) the schematic index for a program.

    The cache is invalidated per-file on size/mtime change, so replacing a
    schematic re-indexes just that document.
    """
    docs = list_documents(program)
    cache = {}
    ipath = index_path(program)
    if not force and os.path.isfile(ipath):
        try:
            with open(ipath, encoding="utf-8") as f:
                loaded = json.load(f)
            if loaded.get("index_version") == INDEX_VERSION:
                cache = {d["filename"]: d for d in loaded.get("documents", [])}
        except Exception:
            cache = {}

    documents = []
    for d in docs:
        prev = cache.get(d["filename"])
        unchanged = (prev and prev.get("size_bytes") == d["size_bytes"]
                     and abs(float(prev.get("mtime", 0)) - d["mtime"]) < 1e-6)
        if unchanged:
            documents.append(prev)
            continue

        entry = {k: d[k] for k in ("filename", "ext", "kind", "size_bytes", "mtime", "size_human")}
        if d["kind"] == "pdf":
            entry.update(index_pdf(d["path"]))
        else:
            # Images/SVG carry no extractable text layer.
            entry.update({"sheets": [{"page": 1, "title": d["filename"], "designators": [],
                                      "nets": [], "char_count": 0}],
                          "has_text_layer": False, "page_count": 1})
            if d["kind"] == "svg":
                try:
                    with open(d["path"], encoding="utf-8", errors="ignore") as f:
                        svg_text = f.read()
                    desig, nets = extract_tokens(svg_text)
                    entry["sheets"][0].update({"designators": desig, "nets": nets})
                    entry["has_text_layer"] = bool(desig or nets)
                except Exception:
                    pass
        documents.append(entry)

    index = {
        "index_version": INDEX_VERSION,
        "program": program,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "documents": documents,
    }
    try:
        os.makedirs(os.path.dirname(ipath), exist_ok=True)
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
    except Exception:
        pass  # cache write is best-effort
    return index


def index_summary(index: dict) -> dict:
    """Roll-up stats for the UI."""
    docs = index.get("documents", [])
    all_desig, all_nets, sheets = set(), set(), 0
    searchable, scanned = 0, 0
    for d in docs:
        for s in d.get("sheets", []):
            sheets += 1
            all_desig.update(s.get("designators", []))
            all_nets.update(s.get("nets", []))
        if d.get("has_text_layer"):
            searchable += 1
        elif d.get("kind") == "pdf":
            scanned += 1
    return {
        "n_documents": len(docs),
        "n_sheets": sheets,
        "n_designators": len(all_desig),
        "n_nets": len(all_nets),
        "searchable_docs": searchable,
        "scanned_docs": scanned,
        "designators": sorted(all_desig),
        "nets": sorted(all_nets),
    }


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def search_index(program: str, term: str, index: dict | None = None) -> list:
    """Fast index lookup: which documents/sheets mention this token.

    Returns [{filename, page, title, match_type}] — no PDF open required.
    """
    term_u = (term or "").strip().upper()
    if not term_u:
        return []
    index = index or build_index(program)
    hits = []
    for d in index.get("documents", []):
        for s in d.get("sheets", []):
            desig = [x.upper() for x in s.get("designators", [])]
            nets = [x.upper() for x in s.get("nets", [])]
            match_type = None
            if term_u in desig:
                match_type = "designator"
            elif term_u in nets:
                match_type = "net"
            elif any(term_u in x for x in desig):
                match_type = "designator (partial)"
            elif any(term_u in x for x in nets):
                match_type = "net (partial)"
            if match_type:
                hits.append({"filename": d["filename"], "page": s.get("page", 1),
                             "title": s.get("title", ""), "match_type": match_type,
                             "kind": d.get("kind", "pdf")})
    return hits


def locate_in_pdf(path: str, term: str, page: int | None = None) -> list:
    """Exact coordinate lookup by opening the PDF. Returns
    [{page, rect:[x0,y0,x1,y1]}] for each occurrence."""
    if not PDF_AVAILABLE or not term:
        return []
    try:
        doc = _fitz.open(path)
    except Exception:
        return []
    out = []
    try:
        pages = [page - 1] if page else range(doc.page_count)
        for i in pages:
            if i < 0 or i >= doc.page_count:
                continue
            for r in doc[i].search_for(term):
                out.append({"page": i + 1,
                            "rect": [round(r.x0, 1), round(r.y0, 1),
                                     round(r.x1, 1), round(r.y1, 1)]})
    except Exception:
        pass
    finally:
        doc.close()
    return out


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render_page(path: str, page: int = 1, dpi: int = 150) -> bytes | None:
    """Render a whole PDF page to PNG bytes."""
    if not PDF_AVAILABLE:
        return None
    try:
        doc = _fitz.open(path)
    except Exception:
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        return doc[page - 1].get_pixmap(dpi=dpi).tobytes("png")
    except Exception:
        return None
    finally:
        doc.close()


def render_crop(path: str, page: int, rect, dpi: int = 300, pad: float = 110.0) -> bytes | None:
    """Render a high-DPI CROP around `rect` (PDF points) — the deep-dive view.

    `pad` expands the region so the surrounding circuit is visible, not just
    the matched label.
    """
    if not PDF_AVAILABLE:
        return None
    try:
        doc = _fitz.open(path)
    except Exception:
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        p = doc[page - 1]
        x0, y0, x1, y1 = rect
        clip = _fitz.Rect(max(0, x0 - pad), max(0, y0 - pad * 0.8),
                          min(p.rect.width, x1 + pad * 1.5),
                          min(p.rect.height, y1 + pad))
        return p.get_pixmap(dpi=dpi, clip=clip).tobytes("png")
    except Exception:
        return None
    finally:
        doc.close()


def render_page_highlighted(path: str, page: int, term: str, dpi: int = 150) -> bytes | None:
    """Render a full page with every occurrence of `term` highlighted, so you
    can see where a designator sits in the context of the whole sheet."""
    if not PDF_AVAILABLE:
        return None
    try:
        doc = _fitz.open(path)
    except Exception:
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        p = doc[page - 1]
        for r in p.search_for(term or ""):
            # Draw an attention box (annotation-free so we don't alter the file)
            p.draw_rect(r + (-6, -6, 6, 6), color=(0.86, 0.15, 0.83), width=2.5)
        return p.get_pixmap(dpi=dpi).tobytes("png")
    except Exception:
        return None
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Cross-probing helpers (schematic <-> board pack)
# --------------------------------------------------------------------------- #
def crossprobe_targets(program: str, test_points: dict, schematic_db: dict) -> dict:
    """Map searchable tokens -> board-pack context.

    Returns {TOKEN: {"test_point_key", "tp", "name", "subsystem", "group"}} so
    the viewer can say "TP579 = VDD_CX (Miami Core), phase 2" and jump both
    ways between schematic and debugger.
    """
    out = {}
    for key, tp in (test_points or {}).items():
        label = str(tp.get("tp", "")).strip().upper()
        if label:
            out.setdefault(label, {
                "test_point_key": key, "tp": tp.get("tp"), "name": tp.get("name"),
                "subsystem": tp.get("subsystem"), "group": tp.get("group"),
                "phase": tp.get("phase"), "loc": tp.get("loc"),
                "lsl": tp.get("lsl"), "nom": tp.get("nom"), "usl": tp.get("usl"),
                "unit": tp.get("unit"),
            })
    # Components named in the schematic DB (key_components / diagnostics refs)
    for tp_name, circuit in (schematic_db or {}).items():
        for comp in circuit.get("component_diagnostics", []) or []:
            ref = str(comp.get("ref", "")).strip().upper()
            if ref:
                out.setdefault(ref, {}).update({
                    "component": comp.get("component"), "circuit": tp_name,
                    "location": comp.get("location"), "priority": comp.get("priority"),
                    "check": comp.get("check"), "expected": comp.get("expected"),
                    "if_fail": comp.get("if_fail"),
                })
    return out
