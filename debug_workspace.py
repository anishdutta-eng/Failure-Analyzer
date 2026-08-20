"""Debug Workspace — the PCB Debugger and the schematic, side by side.

One screen, two panes:

    LEFT   measure the rails for the current phase (KGU spec vs DUT)
    RIGHT  the schematic, automatically following whichever rail is selected

Selecting or failing a rail on the left immediately re-centres the schematic on
the right, with a "deep dive" toggle that hands the full width to the drawing.

Everything shown is traceable. Diagnoses come from the board pack's
measurement-conditional `failure_modes` (authored from the schematic) evaluated
against the actual reading. Reference-designator text picked up by OCR is
offered only as a navigation aid and is labelled as such — it is never presented
as a root cause, because proximity on a drawing is not connectivity.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

import board_pack
import daa_fa_engine as daa
import daa_knowledge_base as daa_kb
import debugger
import fault_scope as fs
import schematic_canvas
import schematic_index as si
import theme
from program_config import get_selected_program
from theme import TEXT_MUTED

STATUS_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "monitor": "🟠", "skip": "⬜"}

SIGNATURE_CHOICES = {
    "Auto (from the reading)": None,
    "Dead — short to GND (<1 Ω)": daa_kb.SIG_DEAD_SHORT,
    "Dead — open / not switching (>5 Ω)": daa_kb.SIG_DEAD_OPEN,
    "Low / drooping": daa_kb.SIG_LOW,
    "High / over-voltage": daa_kb.SIG_HIGH,
    "Excessive ripple (AC)": daa_kb.SIG_RIPPLE,
    "Intermittent": daa_kb.SIG_INTERMITTENT,
}


# --------------------------------------------------------------------------- #
# Left pane — measurement
# --------------------------------------------------------------------------- #
def _measure_pane(program: str, tps: dict, phases: dict, readings: dict):
    """Rail entry for one phase. Returns the key of the rail to show at right."""
    st.markdown("##### 1 · Measure")

    scope_mode = st.radio("Scope", ["By phase", "All rails", "Failing only"],
                          horizontal=True, key="ws_scope", label_visibility="collapsed")

    if scope_mode == "By phase":
        pnums = sorted(phases)
        labels = {p: f"{phases[p].get('icon','')} P{p}: {phases[p].get('name','')}" for p in pnums}
        pnum = st.selectbox("Phase", pnums, format_func=lambda p: labels[p], key="ws_phase")
        ph = phases[pnum]
        if ph.get("desc"):
            st.caption(ph["desc"] + ("  ·  **boot-critical**" if ph.get("critical") else ""))
        subset = {k: v for k, v in tps.items() if v.get("phase") == pnum}
    elif scope_mode == "Failing only":
        subset = {}
        for k, v in tps.items():
            if k in readings and debugger.evaluate(readings[k], v)[0] == "fail":
                subset[k] = v
        if not subset:
            st.success("No failing rails in this session.")
    else:
        subset = dict(tps)

    subset = dict(sorted(subset.items(), key=lambda kv: kv[1].get("step", 999)))

    # Rail rows: spec on the left, entry box, live verdict
    for key, tp in subset.items():
        c1, c2, c3 = st.columns([3, 2, 3])
        with c1:
            st.markdown(f"**{tp.get('tp')}** · {tp.get('name')}")
            nom = tp.get("nom")
            st.caption(f"KGU {tp.get('lsl')} – {tp.get('usl')} {tp.get('unit')}"
                       + (f" (nom {nom})" if nom is not None else ""))
        with c2:
            val = st.text_input(f"{tp.get('tp')} ({tp.get('unit')})", key=f"ws_in_{key}",
                                value=str(readings.get(key, "")), label_visibility="collapsed",
                                placeholder=f"{tp.get('unit')}")
            if val.strip():
                readings[key] = val.strip()
            elif key in readings:
                del readings[key]
        with c3:
            if key in readings:
                status, msg = debugger.evaluate(readings[key], tp)
                st.markdown(f"{STATUS_ICON.get(status,'')} **{status.upper()}** — {msg}")
            else:
                st.caption("not measured")

    # Which rail is the schematic following?
    measured_fails = [k for k in tps if k in readings
                      and debugger.evaluate(readings[k], tps[k])[0] == "fail"]
    focus_options = (measured_fails + [k for k in subset if k not in measured_fails]
                     + [k for k in tps if k not in subset and k not in measured_fails])
    if not focus_options:
        return None

    st.markdown("---")
    default_idx = 0
    prev = st.session_state.get("ws_focus")
    if prev in focus_options:
        default_idx = focus_options.index(prev)

    def _fmt(k):
        tp = tps.get(k, {})
        mark = ""
        if k in readings:
            s = debugger.evaluate(readings[k], tp)[0]
            mark = STATUS_ICON.get(s, "") + " "
        return f"{mark}{tp.get('tp')} — {tp.get('name')}"

    focus = st.selectbox("🔎 Schematic follows this rail", focus_options,
                         index=default_idx, format_func=_fmt, key="ws_focus")
    return focus


# --------------------------------------------------------------------------- #
# Right pane — schematic
# --------------------------------------------------------------------------- #
def _schematic_pane(program: str, analysis: dict, index: dict, deep: bool = False,
                    height: int = 620):
    """Right pane: the full sheet, interactive. Pan/zoom happens in the browser."""
    scope = analysis["scope"]
    sheets = analysis["sheets"]
    all_docs = si.list_documents(program)

    st.markdown("##### 2 · Schematic")

    if not all_docs:
        st.info("No schematic documents uploaded for this program yet.")
        st.caption(f"Add sheets to `{si.schematics_dir(program)}` or use the uploader in the "
                   "**📐 Schematic Viewer** view.")
        return

    # Sheet choice: prefer sheets where this net was actually found, but always
    # allow browsing every sheet so the pane is never a dead end.
    found = [s["filename"] for s in sheets]
    options = found + [d["filename"] for d in all_docs if d["filename"] not in found]
    titles = {d["filename"]: (d.get("title") or d["filename"]) for d in all_docs}
    by_name = {s["filename"]: s for s in sheets}

    def _label(fn):
        s = by_name.get(fn)
        if s:
            tag = f"{s['component_count']} components" if s["is_circuit_sheet"] else "reference table"
            return f"✓ {titles.get(fn, fn)} · {tag}"
        return f"   {titles.get(fn, fn)}"

    if found:
        st.caption(f"`{scope.get('net') or scope.get('tp')}` found on {len(found)} sheet(s) — "
                   "marked with ✓ and highlighted in the drawing.")
    else:
        st.warning(f"`{scope.get('net') or scope.get('tp')}` wasn't located on any sheet, so "
                   "nothing is highlighted. Pick a sheet to read manually.")

    fn = st.selectbox("Sheet", options, format_func=_label, key="ws_sheet")
    sheet = by_name.get(fn)

    markers = fs.sheet_markers(program, sheet, scope, index=index) if sheet else []
    if markers:
        st.markdown(schematic_canvas.legend_html(), unsafe_allow_html=True)

    path = os.path.join(si.schematics_dir(program), fn)
    ok = schematic_canvas.render_canvas(
        path, markers=markers, height=height,
        initial="marker" if (markers and not deep) else "fit",
        key=f"ws_canvas_{fn}")
    if not ok:
        st.error("Could not load this sheet image.")
        return

    c1, c2 = st.columns(2)
    with c1:
        try:
            with open(path, "rb") as f:
                st.download_button("📥 Download full sheet", data=f.read(), mime="image/png",
                                   file_name=fn, use_container_width=True, key="ws_dl_full")
        except Exception:
            pass
    with c2:
        if sheet:
            st.caption(f"Highlighted anchor: `{sheet['anchor']}`")

    # Navigation aid — explicitly NOT a diagnosis
    if sheet and sheet.get("is_circuit_sheet"):
        with st.expander("🔤 Designators printed near this net (navigation aid, not a diagnosis)",
                         expanded=False):
            near = fs.designators_near(program, fn, sheet["box"], index=index)
            if near:
                st.caption("Simply the reference designators OCR found near the net label. "
                           "**Being drawn nearby does not prove a part is on this net** — "
                           "use these to orient yourself, then read the drawing to confirm.")
                st.write("  ".join(f"`{n['designator']}`" for n in near))
            else:
                st.caption("None resolved near this label.")


# --------------------------------------------------------------------------- #
# Analysis (full width, under the two panes)
# --------------------------------------------------------------------------- #
def _analysis_pane(program: str, analysis: dict, tps: dict, readings: dict, graph: dict):
    scope = analysis["scope"]
    meas = analysis["measurement"]
    st.markdown(f"##### 3 · Analysis — {scope.get('tp')} {scope.get('name')}")

    # Measurement vs spec
    sp = scope["spec"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Measured (DUT)", f"{meas['raw']} {sp.get('unit','')}" if meas["raw"] is not None else "—")
    c2.metric("KGU window", f"{sp.get('lsl')} – {sp.get('usl')} {sp.get('unit','')}")
    c3.metric("Nominal", f"{sp.get('nom')} {sp.get('unit','')}" if sp.get("nom") is not None else "—")
    if meas["raw"] is not None:
        status, _ = debugger.evaluate(meas["raw"], tps.get(scope["tp_key"], {}))
        c4.metric("Verdict", f"{STATUS_ICON.get(status,'')} {status.upper()}")

    # --- Authoritative diagnosis ---
    diag = analysis["diagnosis"]
    if diag:
        st.markdown("**Diagnosis — from the schematic's documented failure modes**")
        for d in diag:
            st.error(f"**Condition `{d['condition']}` is met** ({d['why']})\n\n{d['guidance']}")
    elif meas["raw"] is not None:
        st.success("This reading satisfies the KGU window — no documented failure mode applies.")
    else:
        st.info("Enter a measurement to get a diagnosis for this rail.")

    # --- The circuit itself (all authoritative) ---
    left, right = st.columns(2)
    with left:
        st.markdown("**Circuit**")
        if scope.get("circuit_name"):
            st.markdown(f"- {scope['circuit_name']}")
        if scope.get("ic"):
            st.markdown(f"- Source: **{scope['ic']}**")
        if scope.get("schematic_path"):
            st.markdown(f"- Path: `{scope['schematic_path']}`")
        if scope.get("loc"):
            st.markdown(f"- Probe at: {scope['loc']}")
        up = scope.get("upstream")
        st.markdown(f"- Fed from: **{up['tp']} ({up['name']})**" if up
                    else "- Fed from: external source")
        dn = scope.get("downstream") or []
        if dn:
            st.markdown("- Feeds: " + ", ".join(f"**{d['tp']}**" for d in dn))
    with right:
        st.markdown("**Components in this circuit** (from the schematic)")
        for kc in scope.get("key_components", []):
            st.markdown(f"- {kc}")
        if not scope.get("key_components"):
            st.caption("None documented for this rail yet.")

    if scope.get("description"):
        st.caption(scope["description"])

    # --- Component-level checklist, when the pack has one ---
    cds = scope.get("component_diagnostics") or []
    if cds:
        with st.expander(f"📋 Component checklist for this circuit ({len(cds)})", expanded=False):
            st.dataframe(pd.DataFrame([{
                "Ref": c.get("ref"), "Component": c.get("component"),
                "Priority": c.get("priority"), "Check": c.get("check"),
                "Expected": c.get("expected"), "If it fails": c.get("if_fail"),
                "Tools": c.get("tools"),
            } for c in cds]), use_container_width=True, hide_index=True)

    # --- Other documented modes that need more observation ---
    others = [o for o in analysis["other_modes"] if o["kind"] in ("contextual", "ripple")]
    if others:
        with st.expander(f"Other documented failure modes for this rail ({len(others)})",
                         expanded=False):
            st.caption("These can't be confirmed from a DC reading alone — check them if the "
                       "symptom matches.")
            for o in others:
                st.markdown(f"- **{o['condition']}** — {o['guidance']}")

    # --- Reference mechanisms ---
    mechs = analysis.get("mechanisms") or []
    if mechs:
        with st.expander(f"🔬 General failure mechanisms for this signature ({len(mechs)})",
                         expanded=False):
            st.caption("Physics-of-failure reference, selected by the electrical signature. "
                       "Not specific to this board.")
            for m in mechs[:4]:
                st.markdown(f"**{m['name']}** — {m.get('description','')}")
                if m.get("nondestructive_tests"):
                    st.markdown("Confirm: " + "; ".join(m["nondestructive_tests"][:3]))
                refs = m.get("references", [])
                if refs:
                    st.caption("Sources: " + " · ".join(f"[{r['title']}]({r['url']})" for r in refs))
                st.markdown("---")

    # --- History ---
    h = analysis.get("history") or {}
    if h.get("total_reports"):
        msg = f"📊 {h['total_reports']} past debug report(s) on file"
        if h.get("count"):
            msg += f" — **{scope.get('tp')} has failed {h['count']} time(s) before**"
        st.caption(msg + ".")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def render_debug_workspace():
    program = get_selected_program()
    theme.render_app_header(f"{program or 'Program'} · Debug Workspace")

    cap = board_pack.capabilities(program)
    if not cap["has_test_points"]:
        st.info(f"🚧 **No board pack for {program} yet**, so there are no test points to "
                "measure. See `ONBOARDING.md`, or run "
                f"`python board_pack.py init {program}`.")
        return

    tps = board_pack.test_points(program)
    phases = board_pack.phases(program)
    graph = board_pack.board_graph(program)
    sch = board_pack.schematic(program)

    if "debugger_readings" not in st.session_state:
        st.session_state.debugger_readings = {}
    readings = st.session_state.debugger_readings

    # --- Session header ---
    h1, h2, h3, h4 = st.columns([2, 2, 2, 2])
    with h1:
        st.text_input("DUT serial", key="debugger_dut_id", placeholder="unit serial")
    with h2:
        st.date_input("Test date", key="debugger_test_date")
    with h3:
        st.selectbox("Stage", ["Field Return", "Factory", "Bench", "Other"], key="ws_stage")
    with h4:
        deep = st.toggle("🔍 Deep dive schematic", value=False, key="ws_deep",
                         help="Give the schematic the full width for close reading.")

    debugger._render_phase_status_bar(readings)

    # --- Session-level DAA localization: which failure is the ROOT one? ---
    failing = [k for k in tps if k in readings
               and debugger.evaluate(readings[k], tps[k])[0] == "fail"]
    if failing:
        loc = daa.localize_fault(readings, tps, debugger.evaluate, graph)
        roots = loc.get("root_faults") or []
        cons = [c for c in loc.get("consequences", [])]
        if roots:
            root_labels = ", ".join(tps[r].get("tp", r) for r in roots if r in tps)
            msg = f"🎯 **Root fault: {root_labels}**"
            if cons:
                msg += (f" — {len(cons)} downstream rail(s) are failing *because of it* "
                        f"({', '.join(tps[c['node']].get('tp', c['node']) for c in cons if c['node'] in tps)}), "
                        "so fix the root first.")
            st.warning(msg)

    index = si.build_index(program) if si.list_documents(program) else {"documents": []}

    st.markdown("---")

    # --- Two panes ---
    if deep:
        # Full width for the drawing; measurements collapse out of the way.
        with st.expander("📏 Measurements", expanded=False):
            focus = _measure_pane(program, tps, phases, readings)
        if focus not in tps:
            focus = (failing[0] if failing else next(iter(tps)))
        analysis = fs.analyze(program, focus, readings.get(focus), tps, graph, sch,
                              signature=_signature_for(focus, readings, tps),
                              index=index)
        _schematic_pane(program, analysis, index, deep=True, height=820)
    else:
        left, right = st.columns([5, 6], gap="large")
        with left:
            focus = _measure_pane(program, tps, phases, readings)
        if not focus:
            return
        analysis = fs.analyze(program, focus, readings.get(focus), tps, graph, sch,
                              signature=_signature_for(focus, readings, tps),
                              index=index)
        with right:
            _schematic_pane(program, analysis, index, height=620)

    st.markdown("---")

    # Signature override sits with the analysis, since it changes the reference set
    sc1, sc2 = st.columns([2, 3])
    with sc1:
        choice = st.selectbox("Electrical signature", list(SIGNATURE_CHOICES), key="ws_sig",
                              help="Open vs short implicate different parts. Set this after "
                                   "the resistance-to-GND probe for an accurate reference set.")
    if SIGNATURE_CHOICES[choice] is not None:
        analysis = fs.analyze(program, focus, readings.get(focus), tps, graph, sch,
                              signature=SIGNATURE_CHOICES[choice], index=index)
    with sc2:
        if analysis.get("signature_label"):
            st.caption(f"**{analysis['signature_label']}** — {analysis.get('first_action','')}")

    _analysis_pane(program, analysis, tps, readings, graph)


def _signature_for(tp_key: str, readings: dict, tps: dict):
    sig = daa.signature_for(tp_key, readings, tps, debugger.evaluate)
    return None if sig == "dead_unknown" else sig
