"""Smart Schematic Viewer — study a program's actual schematic sheets.

Four capabilities, all per-program:
  * Browse    — page through the uploaded sheets (native PDF view or rendered image).
  * Search    — find any designator/net across every sheet, jump straight to it.
  * Deep dive — high-DPI crop around a hit so a dense A3 sheet is readable.
  * Cross-probe — tie a designator back to its board-pack rail, KGU spec, phase,
                  board location, and (if measured) its DUT reading.

Everything is gated on what the program actually has: no schematics uploaded
means a clear empty state with instructions, never another program's documents.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

import board_pack
import schematic_index as si
import theme
from program_config import get_selected_program
from theme import BORDER


def _sanitize_filename(name: str) -> str:
    """Keep uploads to a safe basename inside the program's folder."""
    base = os.path.basename(name or "").strip().replace("\\", "_").replace("/", "_")
    return "".join(c for c in base if c.isalnum() or c in "._- ()")[:120] or "upload"


def _render_upload(program: str):
    """Upload schematic documents into the program's board/schematics folder."""
    with st.expander("📤 Upload schematic documents", expanded=False):
        st.caption(
            "Accepted: PDF (vector export strongly preferred — it enables search), "
            "PNG/JPG, SVG. Files are stored with the program, not in the browser session."
        )
        ups = st.file_uploader(
            "Schematic sheets / PCB images",
            type=["pdf", "png", "jpg", "jpeg", "webp", "svg"],
            accept_multiple_files=True, key=f"schem_up_{program}",
        )
        if ups:
            d = si.schematics_dir(program)
            os.makedirs(d, exist_ok=True)
            saved = []
            for u in ups:
                fn = _sanitize_filename(u.name)
                try:
                    with open(os.path.join(d, fn), "wb") as f:
                        f.write(u.getvalue())
                    saved.append(fn)
                except Exception as e:
                    st.error(f"Could not save {fn}: {e}")
            if saved:
                si.build_index(program, force=True)
                st.success(f"Saved and indexed: {', '.join(saved)}")
                st.caption("Switch documents below to view them.")

        st.markdown(
            f"Storage location: `{si.schematics_dir(program)}`  \n"
            "⚠️ Schematics are confidential — keep this directory in "
            "access-controlled storage and out of any public repo or container image."
        )


def _render_empty_state(program: str):
    st.info(f"📐 **No schematic documents have been uploaded for {program} yet.**")
    st.markdown(f"""
The Schematic Viewer reads the documents stored in that program's board folder.
Add them one of two ways:

1. **Use the uploader below** (writes straight into the program folder), or
2. **Copy files in directly:**
   ```
   {si.schematics_dir(program)}
   ```

**Export tips for the best experience**
- Export the schematic as a **vector PDF** from your EDA tool (Allegro / Altium /
  KiCad). A vector PDF keeps a text layer, which is what powers designator
  search, deep-dive crops, and cross-probing.
- A scanned or flattened image PDF will still display, but cannot be searched —
  the viewer will tell you when that's the case.
- Include the **power-tree / block-diagram** sheets; they map directly onto the
  board pack's power tree.
""")
    if not si.PDF_AVAILABLE:
        st.warning("PyMuPDF isn't available in this environment, so PDF rendering and "
                   "search are disabled. `pip install pymupdf` to enable them.")


def _render_summary(program: str, index: dict):
    s = si.index_summary(index)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Documents", s["n_documents"])
    c2.metric("Sheets", s["n_sheets"])
    c3.metric("Designators", s["n_designators"])
    c4.metric("Nets", s["n_nets"])
    c5.metric("Searchable", f"{s['searchable_docs']}/{s['n_documents']}")
    if s["scanned_docs"]:
        st.warning(f"{s['scanned_docs']} document(s) have no text layer (scanned or "
                   "flattened). They display fine, but can't be searched or cross-probed. "
                   "Re-export as a vector PDF to unlock those features.")
    return s


def _crossprobe_card(token: str, xp: dict, readings: dict):
    """Show board-pack context for a designator, plus any live measurement."""
    info = xp.get(token.upper())
    if not info:
        return
    st.markdown(f'<div class="ph ph-c">🔗 Cross-probe: {token.upper()}</div>',
                unsafe_allow_html=True)
    cols = st.columns(3)
    with cols[0]:
        if info.get("name"):
            st.markdown(f"**Rail:** {info['name']}")
        if info.get("group"):
            st.markdown(f"**Subsystem group:** {info['group']}")
        if info.get("phase") is not None:
            st.markdown(f"**Debug phase:** {info['phase']}")
    with cols[1]:
        if info.get("lsl") is not None:
            nom = info.get("nom")
            st.markdown(f"**KGU spec:** {info['lsl']} – {info['usl']} {info.get('unit','')}"
                        + (f" (nom {nom})" if nom is not None else ""))
        if info.get("subsystem"):
            st.markdown(f"**Source:** {info['subsystem']}")
        if info.get("loc"):
            st.markdown(f"**Board location:** {info['loc']}")
    with cols[2]:
        key = info.get("test_point_key")
        if key and key in (readings or {}):
            st.metric("Measured (DUT)", f"{readings[key]} {info.get('unit','')}")
        elif key:
            st.caption("Not measured in the current debug session.")
        if info.get("component"):
            st.markdown(f"**Component:** {info['component']}")
        if info.get("priority"):
            st.markdown(f"**Priority:** {info['priority']}")

    if info.get("check") or info.get("expected") or info.get("if_fail"):
        with st.expander("Component diagnostic detail", expanded=False):
            if info.get("check"):
                st.markdown(f"**Check:** {info['check']}")
            if info.get("expected"):
                st.markdown(f"**Expected:** {info['expected']}")
            if info.get("if_fail"):
                st.markdown(f"**If it fails:** {info['if_fail']}")


def _tab_browse(program: str, index: dict):
    docs = index.get("documents", [])
    names = [d["filename"] for d in docs]
    fn = st.selectbox("Document", names, key="schem_browse_doc")
    doc = next(d for d in docs if d["filename"] == fn)
    path = os.path.join(si.schematics_dir(program), fn)

    st.caption(f"{doc['kind'].upper()} · {doc['size_human']} · "
               f"{doc.get('page_count', 1)} sheet(s) · "
               + ("searchable text layer ✅" if doc.get("has_text_layer") else "no text layer ⚠️"))

    if doc["kind"] == "image":
        st.image(path, use_container_width=True)
        return
    if doc["kind"] == "svg":
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                st.markdown(f'<div style="background:#fff;border:1px solid {BORDER};'
                            f'border-radius:10px;padding:8px;overflow:auto;">{f.read()}</div>',
                            unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Could not render SVG: {e}")
        return

    # PDF
    sheets = doc.get("sheets", [])
    mode = st.radio("View", ["Rendered sheet (zoomable image)", "Native PDF viewer"],
                    horizontal=True, key="schem_view_mode")

    if mode == "Native PDF viewer":
        try:
            with open(path, "rb") as f:
                st.pdf(f.read(), height=760)
        except AttributeError:
            st.info("This Streamlit version has no native PDF element — using the "
                    "rendered-sheet view instead.")
            mode = "Rendered sheet (zoomable image)"
        except Exception as e:
            st.error(f"Could not display PDF: {e}")
        if mode == "Native PDF viewer":
            return

    if not sheets:
        st.warning("No sheets found in this document.")
        return

    labels = [f"Sheet {s['page']}" + (f" — {s['title']}" if s.get("title") else "")
              for s in sheets]
    pick = st.selectbox("Sheet", range(len(sheets)), format_func=lambda i: labels[i],
                        key="schem_browse_sheet")
    sheet = sheets[pick]
    dpi = st.select_slider("Render quality (DPI)", options=[100, 150, 200, 300, 400],
                           value=150, key="schem_browse_dpi",
                           help="Higher DPI = sharper zoom, slower render.")

    with st.spinner("Rendering sheet…"):
        png = si.render_page(path, sheet["page"], dpi=dpi)
    if png:
        st.image(png, use_container_width=True)
        st.download_button("📥 Download this sheet as PNG", data=png,
                           file_name=f"{os.path.splitext(fn)[0]}_sheet{sheet['page']}.png",
                           mime="image/png")
    else:
        st.error("Could not render this sheet.")

    if sheet.get("designators"):
        with st.expander(f"Designators on this sheet ({len(sheet['designators'])})",
                         expanded=False):
            st.write(", ".join(sheet["designators"]))
    if sheet.get("nets"):
        with st.expander(f"Nets on this sheet ({len(sheet['nets'])})", expanded=False):
            st.write(", ".join(sheet["nets"]))


def _tab_search(program: str, index: dict, xp: dict, readings: dict):
    st.markdown("Find a component or net across **every** sheet, then zoom into it.")
    summary = si.index_summary(index)

    col1, col2 = st.columns([3, 2])
    with col1:
        term = st.text_input("Designator or net", key="schem_search_term",
                             placeholder="e.g. C448, TP579, U12, VDD_CX").strip()
    with col2:
        known = summary["designators"] + summary["nets"]
        if known:
            picked = st.selectbox("…or pick from the index", [""] + known,
                                  key="schem_search_pick")
            if picked and not term:
                term = picked

    if not term:
        if summary["designators"]:
            st.caption("Indexed designators: " + ", ".join(summary["designators"][:60])
                       + (" …" if len(summary["designators"]) > 60 else ""))
        return

    hits = si.search_index(program, term, index)
    if not hits:
        st.warning(f"'{term}' wasn't found in any indexed sheet. "
                   "It may be on a document without a text layer, or spelled differently.")
        return

    st.success(f"Found '{term.upper()}' in {len(hits)} sheet(s).")
    st.dataframe(pd.DataFrame([{"Document": h["filename"], "Sheet": h["page"],
                                "Sheet title": h["title"], "Matched as": h["match_type"]}
                               for h in hits]),
                 use_container_width=True, hide_index=True)

    # Cross-probe context from the board pack
    _crossprobe_card(term, xp, readings)

    # Deep dive on a chosen hit
    st.markdown("##### 🔍 Deep dive")
    opts = [f"{h['filename']} · sheet {h['page']}" for h in hits]
    idx = st.selectbox("Location", range(len(hits)), format_func=lambda i: opts[i],
                       key="schem_search_hit")
    hit = hits[idx]
    path = os.path.join(si.schematics_dir(program), hit["filename"])

    if hit["kind"] != "pdf":
        st.image(path, use_container_width=True)
        return

    coords = si.locate_in_pdf(path, term, page=hit["page"])
    if not coords:
        st.info("Found on this sheet via the index, but exact coordinates couldn't be "
                "resolved. Showing the full sheet instead.")
        png = si.render_page(path, hit["page"], dpi=150)
        if png:
            st.image(png, use_container_width=True)
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        occ = st.selectbox("Occurrence", range(len(coords)),
                           format_func=lambda i: f"#{i+1} at {coords[i]['rect'][:2]}",
                           key="schem_occ")
    with c2:
        zoom_dpi = st.select_slider("Crop DPI", options=[200, 300, 400, 600], value=300,
                                    key="schem_crop_dpi")
    with c3:
        pad = st.select_slider("Context around it (pt)", options=[60, 110, 200, 350, 600],
                               value=110, key="schem_crop_pad",
                               help="How much surrounding circuit to include.")

    rect = coords[occ]["rect"]
    with st.spinner("Rendering zoomed crop…"):
        crop = si.render_crop(path, hit["page"], rect, dpi=zoom_dpi, pad=float(pad))
    if crop:
        st.image(crop, use_container_width=True,
                 caption=f"{term.upper()} — {hit['filename']} sheet {hit['page']} at {rect[:2]}")
        st.download_button("📥 Download this crop (for the FA report)", data=crop,
                           file_name=f"{term.upper()}_{hit['filename']}_p{hit['page']}.png",
                           mime="image/png")
    else:
        st.error("Could not render the crop.")

    with st.expander("Show the whole sheet with this designator highlighted", expanded=False):
        with st.spinner("Rendering highlighted sheet…"):
            hl = si.render_page_highlighted(path, hit["page"], term, dpi=150)
        if hl:
            st.image(hl, use_container_width=True)


def _tab_component_index(program: str, index: dict, xp: dict):
    """A cross-reference table: designator -> sheets -> board-pack meaning."""
    summary = si.index_summary(index)
    if not summary["designators"]:
        st.info("No designators indexed yet. Upload a vector PDF (with a text layer) "
                "to build the cross-reference.")
        return

    st.markdown("Every designator found in the schematics, cross-referenced with the "
                "board pack. Useful for answering *'where does C448 live and what does it do?'*")

    # Map designator -> sheets
    where = {}
    for d in index.get("documents", []):
        for s in d.get("sheets", []):
            for tok in s.get("designators", []):
                where.setdefault(tok.upper(), []).append(f"{d['filename']} p{s['page']}")

    rows = []
    for tok in summary["designators"]:
        info = xp.get(tok.upper(), {})
        rows.append({
            "Designator": tok,
            "Found on": "; ".join(where.get(tok.upper(), [])[:3]),
            "Board pack rail": info.get("name") or "",
            "Group": info.get("group") or info.get("circuit") or "",
            "Component": info.get("component") or "",
            "In pack": "✅" if info else "—",
        })
    df = pd.DataFrame(rows)

    only_unmatched = st.checkbox("Show only designators NOT in the board pack", value=False,
                                 help="These are components on the schematic that the pack "
                                      "doesn't describe yet — candidates to add.")
    if only_unmatched:
        df = df[df["In pack"] == "—"]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("📥 Download cross-reference (CSV)", data=df.to_csv(index=False),
                       file_name=f"{program}_schematic_xref.csv", mime="text/csv")


def render_schematic_viewer():
    """Entry point for the Schematic Viewer view."""
    program = get_selected_program()
    theme.render_app_header(f"{program or 'Program'} · Schematic Viewer")

    if not program:
        st.warning("Select a program first.")
        return

    st.caption("Study the actual schematic sheets, search any designator across them, "
               "and cross-probe back to test points and measurements.")

    _render_upload(program)

    docs = si.list_documents(program)
    if not docs:
        _render_empty_state(program)
        return

    with st.spinner("Indexing schematics…"):
        index = si.build_index(program)

    _render_summary(program, index)

    if st.button("🔄 Re-index documents", help="Re-scan all sheets (after replacing a file)"):
        si.build_index(program, force=True)
        st.success("Re-indexed.")

    # Board-pack context for cross-probing + any live measurements
    xp = si.crossprobe_targets(program, board_pack.test_points(program),
                               board_pack.schematic(program))
    readings = st.session_state.get("debugger_readings", {}) or {}

    st.markdown("---")
    t1, t2, t3 = st.tabs(["🔎 Search & Deep Dive", "📖 Browse Sheets", "📇 Component Index"])
    with t1:
        _tab_search(program, index, xp, readings)
    with t2:
        _tab_browse(program, index)
    with t3:
        _tab_component_index(program, index, xp)
