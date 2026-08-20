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
import daa_fa_engine as daa
import daa_knowledge_base as daa_kb
import debugger
import fault_scope
import schematic_index as si
import theme
from program_config import get_selected_program
from theme import BORDER, TEXT_MUTED


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
        st.warning(f"{s['scanned_docs']} document(s) have no searchable text. "
                   "They display fine but can't be searched or cross-probed.")
    n_ocr = sum(1 for d in index.get("documents", []) if d.get("ocr") and d.get("has_text_layer"))
    if n_ocr:
        st.caption(f"🔤 {n_ocr} image-based sheet(s) were made searchable with OCR. "
                   "OCR is very good on schematics but not perfect — if a designator "
                   "isn't found, try a partial search (e.g. `579` instead of `TP579`).")
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

    # Group by category (from manifest) so the list reads logically.
    cats = []
    for d in docs:
        c = d.get("category") or "Uncategorized"
        if c not in cats:
            cats.append(c)
    cat = st.selectbox("Category", ["All"] + cats, key="schem_browse_cat")
    pool = [d for d in docs if cat == "All" or (d.get("category") or "Uncategorized") == cat]
    if not pool:
        st.info("No documents in this category.")
        return

    def _label(d):
        return f"{d.get('title') or d['filename']}"

    fn = st.selectbox("Document", [d["filename"] for d in pool],
                      format_func=lambda f: _label(next(x for x in pool if x["filename"] == f)),
                      key="schem_browse_doc")
    doc = next(d for d in docs if d["filename"] == fn)
    path = os.path.join(si.schematics_dir(program), fn)

    layer = ("searchable text layer ✅" if doc.get("has_text_layer") and not doc.get("ocr")
             else ("searchable via OCR ✅" if doc.get("has_text_layer") else "not searchable ⚠️"))
    st.caption(f"**{doc.get('title') or fn}** · {doc['kind'].upper()} · {doc['size_human']} · "
               f"{doc.get('page_count', 1)} sheet(s) · {layer}  \n`{fn}`")

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
        # Raster schematic: use the OCR boxes to crop-zoom on the match.
        boxes = si.locate_in_image(program, hit["filename"], term, index)
        if boxes:
            c1, c2, c3 = st.columns(3)
            with c1:
                occ = st.selectbox("Occurrence", range(len(boxes)),
                                   format_func=lambda i: f"#{i+1} at {boxes[i]['box'][:2]}",
                                   key="schem_img_occ")
            with c2:
                pad = st.select_slider("Context around it (px)",
                                       options=[120, 260, 450, 700, 1100], value=260,
                                       key="schem_img_pad")
            with c3:
                scale = st.select_slider("Upscale", options=[1.0, 1.5, 2.0, 3.0], value=2.0,
                                         key="schem_img_scale")
            crop = si.render_image_crop(path, boxes[occ]["box"], pad=int(pad), scale=float(scale))
            if crop:
                st.image(crop, use_container_width=True,
                         caption=f"{term.upper()} — {hit['filename']} (OCR-located)")
                st.download_button("📥 Download this crop (for the FA report)", data=crop,
                                   file_name=f"{term.upper()}_{hit['filename']}",
                                   mime="image/png")
            with st.expander("Show the full sheet", expanded=False):
                st.image(path, use_container_width=True)
        else:
            st.info("Matched via the OCR token list, but no reliable coordinates for this "
                    "term (low OCR confidence). Showing the full sheet.")
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


HIGHLIGHT_LEGEND = [
    ("primary", "Failed net / test point", "#DC2663"),
    ("upstream", "Its power source", "#7C3AED"),
    ("downstream", "What it feeds", "#2563EB"),
    ("suspect", "Nearby suspect component", "#D97706"),
    ("related", "Related test point", "#059669"),
]


def render_suspect_analysis(program: str, tp_key: str, signature: str | None,
                            index: dict | None = None, compact: bool = False,
                            key_prefix: str = "fv"):
    """Shared renderer: sub-circuit scope, ranked suspects and the annotated
    schematic for one failing rail. Used by the Fault View tab AND inline in
    the PCB Debugger so both views stay consistent."""
    tps = board_pack.test_points(program)
    graph = board_pack.board_graph(program)
    sch = board_pack.schematic(program)

    analysis = fault_scope.analyze_failure(program, tp_key, tps, graph, sch,
                                           signature=signature, index=index)
    scope = analysis["scope"]

    # --- Sub-circuit summary ---
    head = f"{scope.get('tp')} — {scope.get('name')}"
    st.markdown(f"#### 🔧 Sub-circuit: {head}")
    if analysis.get("signature_label"):
        st.markdown(f"**Electrical signature:** {analysis['signature_label']}")
    if analysis.get("first_action"):
        st.caption(f"First action: {analysis['first_action']}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if scope.get("circuit_name"):
            st.markdown(f"**Circuit:** {scope['circuit_name']}")
        if scope.get("ic"):
            st.markdown(f"**Source IC:** {scope['ic']}")
        if analysis.get("net_name"):
            st.markdown(f"**Net label:** `{analysis['net_name']}`")
    with c2:
        up = scope.get("upstream")
        st.markdown(f"**Fed from:** {up['tp'] + ' — ' + str(up['name']) if up else 'external source'}")
        dn = scope.get("downstream") or []
        st.markdown(f"**Feeds:** {', '.join(d['tp'] for d in dn) if dn else '—'}")
    with c3:
        sp = scope.get("spec") or {}
        if sp.get("lsl") is not None:
            st.markdown(f"**KGU spec:** {sp['lsl']} – {sp['usl']} {sp.get('unit','')}")
        if scope.get("loc"):
            st.markdown(f"**Board location:** {scope['loc']}")

    if scope.get("schematic_path"):
        st.markdown(f"**Signal path:** `{scope['schematic_path']}`")
    if scope.get("fail_action"):
        st.info(f"**Board guidance:** {scope['fail_action']}")

    # --- Annotated schematic ---
    png = analysis.get("annotated_png")
    if png:
        st.markdown("##### 📐 Sub-circuit highlighted on the schematic")
        legend = "  ".join(
            f'<span style="display:inline-block;margin-right:14px;">'
            f'<span style="display:inline-block;width:11px;height:11px;background:{c};'
            f'border-radius:2px;margin-right:5px;vertical-align:middle;"></span>'
            f'<span style="font-size:.8em;color:{TEXT_MUTED};">{label}</span></span>'
            for _role, label, c in HIGHLIGHT_LEGEND)
        st.markdown(f'<div style="margin:4px 0 8px;">{legend}</div>', unsafe_allow_html=True)
        st.image(png, use_container_width=True,
                 caption=f"{analysis.get('annotated_file')} — highlighted sub-circuit")
        st.download_button("📥 Download annotated sub-circuit (for the FA report)",
                           data=png, mime="image/png",
                           file_name=f"{scope.get('tp')}_subcircuit.png",
                           key=f"{key_prefix}_dl_{tp_key}")
    else:
        st.caption("No sheet in this program's schematics contains this net with "
                   "locatable coordinates, so there's nothing to highlight. "
                   "(Add the circuit sheet for this rail to enable it.)")

    # --- Ranked suspects ---
    ranked = analysis.get("ranked_designators") or []
    st.markdown("##### 🎯 Suspect components (ranked)")
    if not ranked:
        st.warning(
            "No candidate components could be associated with this rail from the "
            "schematics on file. This happens when the net label doesn't appear on "
            "a sheet that also shows components — the rail's own circuit sheet is "
            "probably missing. Fall back to the mechanism checklist below."
        )
    else:
        rows = []
        for r in ranked[:12]:
            rows.append({
                "Component": r["designator"],
                "Confidence": round(r["score"], 2),
                "Distance": f"{int(r['distance_px'])} px",
                "Sheet": r["sheet_title"] or r["filename"],
                "Why": "; ".join(r["reasons"][1:])[:110] or r["reasons"][0][:110],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("⚠️ Ranking blends the board pack's component list, the electrical "
                   "signature, past failure history, and **how close each part is drawn "
                   "to this net on the sheet**. Proximity is a strong heuristic but is "
                   "NOT a netlist trace — confirm against the schematic before rework.")

    # --- Mechanism checklist from the knowledge base ---
    mechs = analysis.get("mechanisms") or []
    if mechs and not compact:
        st.markdown("##### 🔬 What to check, by failure mechanism")
        for i, m in enumerate(mechs[:4]):
            with st.expander(f"{i+1}. {m['name']}", expanded=(i == 0)):
                st.markdown(m.get("description", ""))
                cols = st.columns(2)
                with cols[0]:
                    st.markdown("**Likely causes**")
                    for c in m.get("root_causes", [])[:5]:
                        st.markdown(f"- {c}")
                with cols[1]:
                    st.markdown("**Confirm (nondestructive first)**")
                    for t in m.get("nondestructive_tests", [])[:5]:
                        st.markdown(f"- {t}")
                refs = m.get("references", [])
                if refs:
                    st.caption("Sources: " + " · ".join(f"[{r['title']}]({r['url']})" for r in refs))

    # --- Component-level checklist straight from the pack ---
    cds = scope.get("component_diagnostics") or []
    if cds and not compact:
        with st.expander(f"📋 Board component checklist for this rail ({len(cds)})",
                         expanded=False):
            for cd in cds:
                st.markdown(f"**{cd.get('ref','?')} — {cd.get('component','')}** "
                            f"({cd.get('priority','')})")
                if cd.get("check"):
                    st.markdown(f"- Check: {cd['check']}")
                if cd.get("expected"):
                    st.markdown(f"- Expected: {cd['expected']}")
                if cd.get("if_fail"):
                    st.markdown(f"- If it fails: {cd['if_fail']}")
                st.markdown("---")

    # --- History ---
    hist = analysis.get("history") or {}
    if hist.get("total_reports"):
        tp_label = scope.get("tp")
        seen = (hist.get("all_counts") or {}).get(tp_label)
        st.caption(f"📊 Learned from {hist['total_reports']} past debug report(s)"
                   + (f" — {tp_label} has failed {seen} time(s) before." if seen else "."))
    return analysis


def render_fault_view(program: str, index: dict, readings: dict):
    """Fault View: drive the schematic from the debugger's live measurements."""
    st.markdown("Turn a failed measurement into a highlighted sub-circuit and a ranked "
                "list of components to check.")

    tps = board_pack.test_points(program)
    graph = board_pack.board_graph(program)
    if not tps:
        st.info(f"{program} has no board pack test points yet, so faults can't be scoped. "
                "See ONBOARDING.md.")
        return

    # Which rails are currently failing, per the debugger session?
    failing, marginal = [], []
    for key, val in (readings or {}).items():
        tp = tps.get(key)
        if not tp:
            continue
        status, _msg = debugger.evaluate(val, tp)
        if status == "fail":
            failing.append(key)
        elif status == "warn":
            marginal.append(key)

    if readings:
        st.caption(f"Live debug session: {len(readings)} measurement(s), "
                   f"{len(failing)} failing, {len(marginal)} marginal.")
    else:
        st.caption("No live measurements yet — enter readings in the **PCB Debugger** and "
                   "they'll appear here automatically, or pick a rail manually below.")

    # Root-cause ordering from the DAA engine (suppresses downstream noise)
    root_first = list(failing)
    if failing:
        loc = daa.localize_fault(readings, tps, debugger.evaluate, graph)
        roots = loc.get("root_faults") or []
        consequences = {c["node"] for c in loc.get("consequences", [])}
        root_first = roots + [f for f in failing if f not in roots]
        if roots:
            st.success(f"🎯 DAA localization: root fault(s) **"
                       + ", ".join(tps[r].get("tp", r) for r in roots if r in tps)
                       + "**" + (f" · {len(consequences)} downstream failure(s) explained by them"
                                 if consequences else ""))

    # Rail selector — defaults to the localized root fault
    options = root_first + [k for k in tps if k not in root_first]
    if not options:
        return

    def _fmt(k):
        tp = tps.get(k, {})
        mark = "❌ " if k in failing else ("⚠️ " if k in marginal else "")
        return f"{mark}{tp.get('tp','?')} — {tp.get('name','')}"

    c1, c2 = st.columns([3, 2])
    with c1:
        tp_key = st.selectbox("Rail to root-cause", options, format_func=_fmt,
                              key="fv_rail")
    with c2:
        # Signature drives which mechanisms/components are implicated
        sig_opts = {
            "Auto (from the measurement)": None,
            "Dead — short to ground (<1 Ω)": daa_kb.SIG_DEAD_SHORT,
            "Dead — open / not switching (>5 Ω)": daa_kb.SIG_DEAD_OPEN,
            "Low / drooping": daa_kb.SIG_LOW,
            "High / over-voltage": daa_kb.SIG_HIGH,
            "Excessive ripple": daa_kb.SIG_RIPPLE,
            "Intermittent": daa_kb.SIG_INTERMITTENT,
        }
        choice = st.selectbox("Electrical signature", list(sig_opts), key="fv_sig",
                              help="Open vs short implicate completely different parts, "
                                   "so this materially changes the ranking.")
        signature = sig_opts[choice]

    if signature is None:
        signature = daa.signature_for(tp_key, readings, tps, debugger.evaluate)
        if signature == "dead_unknown":
            st.warning("This rail reads dead, but open vs short can't be told apart from "
                       "voltage alone. Measure resistance to GND (board OFF) and pick the "
                       "matching signature above — it changes which components are suspected.")
            signature = None

    st.markdown("---")
    render_suspect_analysis(program, tp_key, signature, index=index, key_prefix="fv")


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
    t0, t1, t2, t3 = st.tabs(["🎯 Fault View", "🔎 Search & Deep Dive",
                              "📖 Browse Sheets", "📇 Component Index"])
    with t0:
        render_fault_view(program, index, readings)
    with t1:
        _tab_search(program, index, xp, readings)
    with t2:
        _tab_browse(program, index)
    with t3:
        _tab_component_index(program, index, xp)
