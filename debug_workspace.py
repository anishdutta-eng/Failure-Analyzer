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
import schematic_index as si
import theme
from program_config import get_selected_program
from theme import BORDER, GREEN, MAGENTA, PURPLE, TEXT, TEXT_MUTED

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
def _schematic_pane(program: str, analysis: dict, index: dict, deep: bool = False):
    scope = analysis["scope"]
    sheets = analysis["sheets"]

    st.markdown("##### 2 · Schematic")

    if not sheets:
        st.info(f"No sheet on file shows **{scope.get('net') or scope.get('tp')}**.")
        st.caption("The circuit sheet for this rail hasn't been uploaded, or its label "
                   "wasn't machine-readable. Add it under the program's "
                   "`board/schematics/` folder to enable this pane.")
        return

    circuit_sheets = [s for s in sheets if s["is_circuit_sheet"]]
    if not circuit_sheets:
        st.warning("This net only appears on test-point summary sheets, not on a circuit "
                   "page — so the drawing below shows the reference table, not the circuit.")

    def _slab(i):
        s = sheets[i]
        tag = f"{s['component_count']} components" if s["is_circuit_sheet"] else "reference table"
        return f"{s['title']}  ·  {tag}"

    c1, c2 = st.columns([3, 2])
    with c1:
        idx = st.selectbox("Sheet", range(len(sheets)), format_func=_slab, key="ws_sheet")
    with c2:
        zoom = st.select_slider("Zoom", options=[0.5, 0.75, 1.0, 1.5, 2.5, 4.0],
                                value=1.5 if deep else 1.0, key="ws_zoom",
                                help="Higher zoom = tighter crop around the net label.")

    sheet = sheets[idx]
    with st.spinner("Rendering schematic…"):
        png = fs.render_net_view(program, sheet, scope, zoom=float(zoom), index=index)

    if png:
        legend = "  ".join(
            f'<span style="margin-right:14px;"><span style="display:inline-block;width:11px;'
            f'height:11px;background:{c};border-radius:2px;margin-right:5px;'
            f'vertical-align:middle;"></span><span style="font-size:.78em;color:{TEXT_MUTED};">'
            f'{lab}</span></span>'
            for lab, c in (("this rail", "#DC2663"), ("its source", "#7C3AED"),
                           ("what it feeds", "#2563EB"), ("related TP", "#059669")))
        st.markdown(f'<div style="margin:2px 0 6px;">{legend}</div>', unsafe_allow_html=True)
        st.image(png, use_container_width=True)
        b1, b2 = st.columns(2)
        with b1:
            st.download_button("📥 Save this view", data=png, mime="image/png",
                               file_name=f"{scope.get('tp')}_{sheet['filename']}",
                               use_container_width=True, key="ws_dl_view")
        with b2:
            full = os.path.join(si.schematics_dir(program), sheet["filename"])
            try:
                with open(full, "rb") as f:
                    st.download_button("📥 Full sheet", data=f.read(), mime="image/png",
                                       file_name=sheet["filename"],
                                       use_container_width=True, key="ws_dl_full")
            except Exception:
                pass
        st.caption(f"Anchored on `{sheet['anchor']}` in {sheet['filename']}")
    else:
        st.error("Could not render this sheet.")

    # Navigation aid — explicitly NOT a diagnosis
    if sheet["is_circuit_sheet"]:
        with st.expander("🔤 Reference designators printed in this area (navigation aid)",
                         expanded=False):
            near = fs.designators_near(program, sheet["filename"], sheet["box"], index=index)
            if near:
                st.caption("These are simply the designators OCR found near the net label on "
                           "this sheet. **Proximity on a drawing does not prove a part is on "
                           "this net** — use this to navigate, then read the schematic to "
                           "confirm which parts actually belong to the circuit.")
                st.write("  ".join(f"`{n['designator']}`" for n in near))
            else:
                st.caption("No designators resolved near this label.")


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
        focus = st.session_state.get("ws_focus")
        if focus not in tps:
            focus = failing[0] if failing else next(iter(tps))
        analysis = fs.analyze(program, focus, readings.get(focus), tps, graph, sch,
                              signature=_signature_for(focus, readings, tps),
                              index=index)
        _schematic_pane(program, analysis, index, deep=True)
        with st.expander("📏 Measurements", expanded=False):
            _measure_pane(program, tps, phases, readings)
    else:
        left, right = st.columns([1, 1], gap="large")
        with left:
            focus = _measure_pane(program, tps, phases, readings)
        if not focus:
            return
        analysis = fs.analyze(program, focus, readings.get(focus), tps, graph, sch,
                              signature=_signature_for(focus, readings, tps),
                              index=index)
        with right:
            _schematic_pane(program, analysis, index)

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
