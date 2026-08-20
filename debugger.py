"""PCB Interactive Debugger - KGU vs DUT comparison."""
import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, date
from program_config import get_reports_dir, get_ml_model_path, get_selected_program
import board_pack
import daa_fa_engine as daa
import daa_knowledge_base as daa_kb

# ---------------------------------------------------------------------------
# Board data is PER-PROGRAM and comes from that program's board pack on disk
# (programs/<slug>/board/board_pack.json). It is deliberately NOT hardcoded
# here: previously these were module-level Snowbird constants, which meant
# every program (Merci, Jupiter, ...) displayed Snowbird's test points and
# spec limits — a real hazard, since a tech could probe the wrong pads.
#
# These accessors read the *currently selected* program on each call. They must
# stay functions (not module globals) because Streamlit shares module state
# across user sessions, so caching a single program's board data globally would
# leak it into other sessions.
# ---------------------------------------------------------------------------


def _prog(program=None):
    return program or get_selected_program()


def phases_for(program=None):
    """Power-on phases for the selected program ({} when not onboarded)."""
    return board_pack.phases(_prog(program))


def test_points_for(program=None):
    """Test points for the selected program ({} when not onboarded)."""
    return board_pack.test_points(_prog(program))


def schematic_for(program=None):
    return board_pack.schematic(_prog(program))


def fault_trees_for(program=None):
    return board_pack.fault_trees(_prog(program))


def board_graph_for(program=None):
    """Power-tree graph bundle handed to the DAA engine."""
    return board_pack.board_graph(_prog(program))


CSS = """<style>
.ph{background:linear-gradient(135deg,#F4F1FB,#ECE8F8);color:#211B33;padding:12px 18px;border-radius:10px;margin:10px 0 6px;font-size:1.1em;font-weight:600;border-left:4px solid #7C3AED}
.ph-c{border-left:4px solid #C026D3}
.tp-pass{background:#E7F6F0;border-left:4px solid #059669;padding:8px 14px;border-radius:8px;margin:4px 0;color:#065F46;font-family:'DM Mono',monospace}
.tp-fail{background:#FCE7F3;border-left:4px solid #DB2777;padding:8px 14px;border-radius:8px;margin:4px 0;color:#9D174D;font-family:'DM Mono',monospace}
.tp-warn{background:#FEF3C7;border-left:4px solid #D97706;padding:8px 14px;border-radius:8px;margin:4px 0;color:#92400E;font-family:'DM Mono',monospace}
.tp-skip{background:#F1EFF7;border-left:4px solid #E0DBF0;padding:8px 14px;border-radius:8px;margin:4px 0;color:#5B5470;font-family:'DM Mono',monospace}
.tp-monitor{background:#FEF3C7;border-left:4px solid #EA580C;padding:8px 14px;border-radius:8px;margin:4px 0;color:#9A3412;font-family:'DM Mono',monospace}
.led{display:inline-block;width:16px;height:16px;border-radius:50%;margin-right:8px;vertical-align:middle}
.led-off{background:#C9C4D6;box-shadow:0 0 2px #b0aabf}
.led-blue{background:#3498db;box-shadow:0 0 8px #3498db,0 0 16px #3498db55}
.led-green{background:#059669;box-shadow:0 0 8px #059669,0 0 16px #05966955}
.led-red{background:#e74c3c;box-shadow:0 0 8px #e74c3c,0 0 16px #e74c3c55}
.led-orange{background:#e67e22;box-shadow:0 0 8px #e67e22,0 0 16px #e67e2255}
.vb{padding:16px;border-radius:12px;margin:12px 0;font-size:1.05em}
.vb-p{background:linear-gradient(135deg,#E7F6F0,#D7F0E5);border:2px solid #059669;color:#065F46}
.vb-f{background:linear-gradient(135deg,#FCE7F3,#FBD8EA);border:2px solid #DB2777;color:#9D174D}
.st{width:100%;border-collapse:collapse;font-family:'DM Mono',monospace;font-size:.9em}
.st th{background:#ECE8F8;color:#211B33;padding:8px 12px;text-align:left;border-bottom:2px solid #7C3AED}
.st td{padding:6px 12px;border-bottom:1px solid #E0DBF0;color:#211B33}
.st tr.rp td{color:#059669} .st tr.rf td{color:#DB2777;font-weight:bold} .st tr.rw td{color:#B45309} .st tr.rs td{color:#8B84A0} .st tr.rm td{color:#C2410C}
.dd{background:#F4F1FB;border:1px solid #E0DBF0;border-radius:10px;padding:14px;margin:8px 0;color:#3B3550}
.dd ol{margin:6px 0;padding-left:20px} .dd li{margin:4px 0;line-height:1.5}
.phase-bar{display:flex;gap:4px;margin:10px 0 16px;flex-wrap:wrap}
.phase-pill{flex:1;min-width:90px;text-align:center;padding:8px 4px;border-radius:10px;font-size:.75em;font-weight:600;font-family:'DM Mono',monospace;border:2px solid #E0DBF0;transition:all .3s}
.pp-gray{background:#F1EFF7;color:#8B84A0;border-color:#E0DBF0}
.pp-blue{background:#EDE9FB;color:#7C3AED;border-color:#7C3AED}
.pp-green{background:#E7F6F0;color:#059669;border-color:#059669}
.pp-red{background:#FCE7F3;color:#DB2777;border-color:#DB2777}
.pp-orange{background:#FEEAD9;color:#C2410C;border-color:#EA580C}
.vi-box{background:linear-gradient(135deg,#F4F1FB,#ECE8F8);border:2px solid #E0DBF0;border-radius:12px;padding:16px;margin:10px 0}
</style>"""


def evaluate(value, tp):
    if value is None or value == "":
        return "skip", "Not measured"
    try:
        v = float(value)
    except (ValueError, TypeError):
        return "skip", "Invalid"
    is_monitor = tp.get("monitor", False)
    if v < tp["lsl"]:
        if v == 0:
            label = "MONITOR: DEAD (0" + tp["unit"] + ")" if is_monitor else "DEAD (0" + tp["unit"] + ")"
            return ("monitor" if is_monitor else "fail"), label
        pct = ((tp["lsl"] - v) / tp["lsl"]) * 100 if tp["lsl"] != 0 else 0
        label = f"MONITOR: LOW by {pct:.1f}% below LSL" if is_monitor else f"LOW by {pct:.1f}% below LSL"
        return ("monitor" if is_monitor else "fail"), label
    if v > tp["usl"]:
        pct = ((v - tp["usl"]) / tp["usl"]) * 100 if tp["usl"] != 0 else 0
        label = f"MONITOR: HIGH by {pct:.1f}% above USL" if is_monitor else f"HIGH by {pct:.1f}% above USL"
        return ("monitor" if is_monitor else "fail"), label
    rng = tp["usl"] - tp["lsl"]
    if rng > 0:
        if (v - tp["lsl"]) / rng < 0.1 or (tp["usl"] - v) / rng < 0.1:
            return "warn", "MARGINAL (near limit)"
    return "pass", "PASS"


def _tp_row(tp, val, status, msg):
    c = "tp-" + status
    n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
    try:
        d = f"{float(val):.4f}" if val else "---"
    except (ValueError, TypeError):
        d = "---"
    ic = {"pass":"✅","fail":"❌","warn":"⚠️","skip":"⬜","monitor":"🟠"}.get(status,"⬜")
    step = tp.get("step", "")
    loc = tp.get("loc", "")
    step_tag = f'<span style="background:#7C3AED;color:#fff;padding:1px 6px;border-radius:10px;font-size:.8em;margin-right:4px;">#{step}</span>' if step else ""
    loc_tag = f'<br><span style="font-size:.75em;color:#5B5470;">📍 {loc}</span>' if loc else ""
    return (f'<div class="{c}">{step_tag}{ic} <b>{tp["tp"]}</b> {tp["name"]}'
            f' | KGU: {n} {tp["unit"]} | DUT: <b>{d}</b> {tp["unit"]}'
            f' | [{tp["lsl"]} - {tp["usl"]}] &rarr; <b>{msg}</b>{loc_tag}</div>')


def _render_board_map():
    """Render the board map from the selected program's board pack.

    Positions/regions come from the pack (board_map.test_point_positions), so
    each program shows ITS OWN board. Programs without map data get a clear
    note instead of another board's layout.
    """
    bm = board_pack.board_map(_prog())
    positions = bm.get("test_point_positions") or []
    if not positions:
        st.info("No board map has been added for this program yet. "
                "Add `board_map.test_point_positions` to its board pack to enable this view.")
        return

    colors = bm.get("group_colors") or {}
    regions = bm.get("regions") or []
    viewbox = bm.get("viewbox", "0 0 1000 760")
    title = bm.get("title", "PCB — TOP VIEW")

    circles, labels = "", ""
    for p in positions:
        x, y = p.get("x", 0), p.get("y", 0)
        step, tp_name, group = p.get("step", ""), p.get("tp", ""), p.get("group", "")
        col = colors.get(group, "#8B84A0")
        circles += f'<circle cx="{x}" cy="{y}" r="14" fill="{col}" stroke="#fff" stroke-width="2"/>'
        circles += (f'<text x="{x}" y="{y+4}" text-anchor="middle" fill="#fff" font-size="11" '
                    f'font-weight="bold" font-family="DM Mono, monospace">{step}</text>')
        # Label sits beside the node; halo keeps it readable over region lines.
        lx = x + 20 if x < 500 else x - 20
        anchor = "start" if x < 500 else "end"
        labels += (f'<text x="{lx}" y="{y+4}" text-anchor="{anchor}" fill="#3B3550" '
                   f'font-size="10" font-weight="600" font-family="DM Mono, monospace" '
                   f'paint-order="stroke" stroke="#FFFFFF" stroke-width="3" '
                   f'stroke-linejoin="round">{tp_name}</text>')

    region_svg = ""
    for r in regions:
        region_svg += (f'<rect x="{r.get("x",0)}" y="{r.get("y",0)}" width="{r.get("w",0)}" '
                       f'height="{r.get("h",0)}" rx="6" fill="#7C3AED08" stroke="#C9C4D6" '
                       f'stroke-width="0.8" stroke-dasharray="5"/>')
        region_svg += (f'<text x="{r.get("x",0)+8}" y="{r.get("y",0)+16}" text-anchor="start" '
                       f'fill="#8B84A0" font-size="9" font-weight="600" '
                       f'font-family="DM Mono, monospace">{r.get("label","")}</text>')

    svg = f'''<svg viewBox="{viewbox}" style="width:100%;max-width:960px;background:#F4F1FB;border-radius:10px;border:1px solid #E0DBF0;">
    <rect x="30" y="30" width="940" height="700" rx="12" fill="#FBFAFE" stroke="#E0DBF0" stroke-width="1"/>
    <text x="500" y="22" text-anchor="middle" fill="#5B5470" font-size="11" font-weight="600" font-family="DM Mono, monospace">{title}</text>
    {region_svg}
    {circles}
    {labels}
    </svg>'''
    st.markdown(svg, unsafe_allow_html=True)

    # Legend
    if colors:
        legend_items = "".join(
            f'<span style="display:inline-block;margin:2px 8px;">'
            f'<span style="display:inline-block;width:12px;height:12px;background:{c};'
            f'border-radius:50%;margin-right:4px;vertical-align:middle;"></span>'
            f'<span style="color:#5B5470;font-size:.8em;">{g}</span></span>'
            for g, c in colors.items())
        st.markdown(f'<div style="text-align:center;margin:6px 0;">{legend_items}</div>',
                    unsafe_allow_html=True)

    # Numbered reference table
    tps = test_points_for()
    rows = []
    for p in sorted(positions, key=lambda d: d.get("step", 0)):
        step = p.get("step")
        match = [v for v in tps.values() if v.get("step") == step]
        spec = ""
        if match:
            m = match[0]
            nom = m.get("nom")
            spec = f'{m.get("lsl")} – {m.get("usl")} {m.get("unit")}' + (f' (nom {nom})' if nom is not None else "")
        rows.append({"#": step, "Test Point": p.get("tp"), "Signal": p.get("signal"),
                     "Group": p.get("group"), "KGU Spec": spec})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_component_diagnostics(diagnostics):
    """Render the ranked component-suspect diagnostic checklist."""
    if not diagnostics:
        return
    st.markdown("##### 🎯 Suspect Components (probe in order)")
    st.caption("Ranked by likelihood. Stop at the first failing check — that's your faulty component.")
    for i, d in enumerate(diagnostics, 1):
        prio = d.get("priority", "Medium")
        prio_color = {"High": "#DB2777", "Medium": "#D97706", "Low": "#7C3AED"}.get(prio, "#8B84A0")
        ref = d.get("ref", "")
        comp = d.get("component", "")
        loc = d.get("location", "")
        check = d.get("check", "")
        expected = d.get("expected", "")
        if_fail = d.get("if_fail", "")
        tools = d.get("tools", "")

        header = f'<div style="background:#F4F1FB;border:1px solid #E0DBF0;border-left:4px solid {prio_color};border-radius:8px;padding:10px 14px;margin:8px 0;">'
        header += f'<div style="font-weight:700;color:#211B33;font-size:1.05em;">#{i} &nbsp; {ref} — {comp} '
        header += f'<span style="float:right;font-size:.8em;color:{prio_color};font-weight:600;">{prio.upper()} PRIORITY</span></div>'
        if loc:
            header += f'<div style="color:#5B5470;font-size:.85em;margin:4px 0 8px 0;">📍 {loc}</div>'
        st.markdown(header, unsafe_allow_html=True)

        cols = st.columns([2, 2, 1])
        with cols[0]:
            st.markdown(f"**Probe / Check**")
            st.markdown(f"<span style='color:#3B3550;font-size:.9em'>{check}</span>", unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f"**Expected (KGU)**")
            st.markdown(f"<span style='color:#059669;font-size:.9em;font-family:\"DM Mono\",monospace'>{expected}</span>", unsafe_allow_html=True)
        with cols[2]:
            if tools:
                st.markdown(f"**Tool**")
                st.markdown(f"<span style='color:#5B5470;font-size:.85em'>{tools}</span>", unsafe_allow_html=True)
        if if_fail:
            st.markdown(f'<div style="background:#FCE7F3;border-left:3px solid #DB2777;padding:6px 10px;margin:6px 0;border-radius:6px;font-size:.85em;color:#9D174D;"><b>❌ If this fails:</b> {if_fail}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_schematic_lookup(tp_name):
    """Render schematic circuit details for a given test point."""
    info = schematic_for().get(tp_name)
    if not info:
        # Try matching by group name
        for key, val in schematic_for().items():
            if tp_name in str(val.get("related_tps", [])):
                info = val
                break
    if not info:
        return
    with st.expander(f"🔍 Schematic: {info['circuit_name']}", expanded=True):
        st.markdown(f"**Circuit:** {info['circuit_name']}")
        st.markdown(f"**IC:** `{info['ic']}`")
        st.markdown(f"**Signal Path:**\n```\n{info['schematic_path']}\n```")
        st.markdown(f"**Description:** {info['description']}")
        if info.get("key_components"):
            comps = " → ".join(info["key_components"])
            st.markdown(f"**Key Components:** {comps}")
        if info.get("failure_modes"):
            st.markdown("**Failure Mode Analysis:**")
            for mode, action in info["failure_modes"].items():
                st.markdown(f"- **{mode}**: {action}")

        # NEW: Component-level diagnostic checklist
        if info.get("component_diagnostics"):
            st.markdown("---")
            _render_component_diagnostics(info["component_diagnostics"])

        if info.get("related_tps"):
            st.markdown(f"**Related Test Points:** {', '.join(info['related_tps'])}")


def _phase_results(phase_tps, readings, pnum):
    fails, warns, passes, monitors = [], [], [], []
    st.markdown("##### KGU Spec vs DUT Comparison")
    for k, tp in phase_tps.items():
        val = readings.get(k)
        s, m = evaluate(val, tp)
        st.markdown(_tp_row(tp, val, s, m), unsafe_allow_html=True)
        if s == "fail": fails.append((k, tp, m))
        elif s == "monitor": monitors.append((k, tp, m))
        elif s == "warn": warns.append((k, tp, m))
        elif s == "pass": passes.append((k, tp, m))
    st.markdown("---")

    # LED status indicator
    if fails:
        led = "led-red"
    elif monitors or warns:
        led = "led-orange"
    elif passes and not fails:
        led = "led-green"
    else:
        led = "led-blue"

    if fails:
        grp = list(phase_tps.values())[0]["group"]
        st.markdown(f'<div class="vb vb-f"><span class="led {led}"></span>❌ Phase {pnum} VERDICT: <b>FAIL</b> — {len(fails)} rail(s) out of spec</div>', unsafe_allow_html=True)
        st.markdown("##### Recommended Actions")
        for _fkey, tp, m in fails:
            st.error(f"**{tp['tp']} ({tp['name']})** - {m}\n\n**Subsystem:** {tp['subsystem']}\n\n**Action:** {tp['fail_action']}")
            _render_schematic_lookup(tp["tp"])
        st.caption("� For the schematic side-by-side with these measurements, switch to the "
                   "**🔬 Debug Workspace** view.")
        for tk, td in fault_trees_for().items():
            if tk in grp or grp.startswith(tk.split(" ")[0]):
                st.markdown(f'<div class="vb vb-f" style="border-color:#e67e22;">🔍 Errors detected. Deep dive in <b>"{td["title"]}"</b> to isolate the fault.</div>', unsafe_allow_html=True)
                sh = "".join(f"<li>{s[3:]}</li>" for s in td["steps"])
                st.markdown(f'<div class="dd"><ol>{sh}</ol></div>', unsafe_allow_html=True)
                break
    elif monitors:
        st.markdown(f'<div class="vb vb-p" style="border-color:#e67e22;"><span class="led {led}"></span>🟠 Phase {pnum}: <b>MONITOR</b> — {len(monitors)} monitor-only rail(s) out of spec, {len(passes)} OK. These do not indicate board failure.</div>', unsafe_allow_html=True)
        for _, tp, m in monitors:
            st.info(f"**{tp['tp']} ({tp['name']})** — {m}\n\n📋 {tp['fail_action']}")
    elif warns:
        st.markdown(f'<div class="vb vb-p" style="border-color:#f39c12;"><span class="led {led}"></span>⚠️ Phase {pnum}: <b>MARGINAL</b> — {len(warns)} near limit, {len(passes)} OK</div>', unsafe_allow_html=True)
        st.info("Within spec but marginal. Proceed but flag for monitoring.")
    else:
        st.markdown(f'<div class="vb vb-p"><span class="led {led}"></span>✅ Phase {pnum}: <b>PASS</b> — {len(passes)}/{len(phase_tps)} within spec. Proceed to Phase {min(pnum+1,8)}.</div>', unsafe_allow_html=True)


def _full_summary(readings):
    results = []
    tf = tw = tp_ = ts = tm = 0
    fg = set()
    for k, tp in test_points_for().items():
        val = readings.get(k)
        s, m = evaluate(val, tp)
        n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
        try:
            d = f"{float(val):.4f}" if val else "---"
        except (ValueError, TypeError):
            d = "---"
        results.append({"Phase": tp["phase"], "TP": tp["tp"], "Rail": tp["name"],
                        "LSL": tp["lsl"], "Nom": n, "USL": tp["usl"],
                        "DUT": d, "Unit": tp["unit"], "Status": s.upper(),
                        "Detail": m, "Group": tp["group"],
                        "Subsystem": tp["subsystem"],
                        "Action": tp["fail_action"] if s == "fail" else ""})
        if s == "fail": tf += 1; fg.add(tp["group"])
        elif s == "monitor": tm += 1
        elif s == "warn": tw += 1
        elif s == "pass": tp_ += 1
        else: ts += 1

    st.markdown("##### Overall DUT Health")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("PASS", tp_); c2.metric("FAIL", tf); c3.metric("MONITOR", tm); c4.metric("MARGINAL", tw); c5.metric("NOT TESTED", ts)

    # LED indicator
    if tf > 0:
        led = "led-red"
    elif tm > 0 or tw > 0:
        led = "led-orange"
    elif tp_ > 0:
        led = "led-green"
    else:
        led = "led-blue"

    if tf > 0:
        st.markdown(f'<div class="vb vb-f"><span class="led {led}"></span>❌ DUT: <b>FAIL</b> — {tf} rail(s) out of spec in: {", ".join(sorted(fg))}</div>', unsafe_allow_html=True)
    elif tm > 0:
        st.markdown(f'<div class="vb vb-p" style="border-color:#e67e22;"><span class="led {led}"></span>🟠 DUT: <b>PASS (with monitors)</b> — all decision rails OK, {tm} monitor-only out of spec</div>', unsafe_allow_html=True)
    elif tw > 0:
        st.markdown(f'<div class="vb vb-p" style="border-color:#f39c12;"><span class="led {led}"></span>⚠️ DUT: <b>MARGINAL</b> — all in spec but {tw} marginal</div>', unsafe_allow_html=True)
    elif tp_ > 0:
        st.markdown(f'<div class="vb vb-p"><span class="led {led}"></span>✅ DUT: <b>PASS</b> — all {tp_} rails within spec</div>', unsafe_allow_html=True)

    st.markdown("##### Full KGU vs DUT Comparison")
    rh = ""
    cp = 0
    for r in results:
        if r["Phase"] != cp:
            cp = r["Phase"]
            pi = phases_for()[cp]
            rh += f'<tr><td colspan="8" style="background:#ECE8F8;color:#211B33;font-weight:bold;padding:8px;border-left:3px solid #7C3AED;">{pi["icon"]} Phase {cp}: {pi["name"]}</td></tr>'
        rc = "r" + r["Status"][0].lower()
        ic = {"PASS":"✅","FAIL":"❌","WARN":"⚠️","SKIP":"⬜","MONITOR":"🟠"}.get(r["Status"],"⬜")
        rh += f'<tr class="{rc}"><td>{r["TP"]}</td><td>{r["Rail"]}</td><td>{r["LSL"]}</td><td>{r["Nom"]}</td><td>{r["USL"]}</td><td><b>{r["DUT"]}</b></td><td>{r["Unit"]}</td><td>{ic} {r["Detail"]}</td></tr>'
    st.markdown(f'<table class="st"><thead><tr><th>Test Point</th><th>Rail</th><th>LSL</th><th>KGU Nom</th><th>USL</th><th>DUT</th><th>Unit</th><th>Verdict</th></tr></thead><tbody>{rh}</tbody></table>', unsafe_allow_html=True)

    if tf > 0:
        st.markdown("---")
        st.markdown("##### Failed Rail Actions")
        for r in results:
            if r["Status"] == "FAIL":
                st.error(f"**{r['TP']} ({r['Rail']})** - {r['Detail']}\n\n**Subsystem:** {r['Subsystem']}\n\n**Action:** {r['Action']}")
                _render_schematic_lookup(r["TP"])
        st.markdown("##### Deep Dive for Failed Subsystems")
        for g in sorted(fg):
            for tk, td in fault_trees_for().items():
                if tk in g or g.startswith(tk.split(" ")[0]):
                    st.markdown(f"**{td['title']}**")
                    sh = "".join(f"<li>{s[3:]}</li>" for s in td["steps"])
                    st.markdown(f'<div class="dd"><ol>{sh}</ol></div>', unsafe_allow_html=True)
                    break

    st.markdown("---")
    df = pd.DataFrame(results)
    did = st.session_state.get("debugger_dut_id", "unknown")
    prog_slug = (get_selected_program() or "debug").lower().replace(" ", "_")
    st.download_button("Download Debug Report (CSV)", data=df.to_csv(index=False),
                       file_name=f"{prog_slug}_debug_{did}.csv", mime="text/csv", use_container_width=True)
    if st.button("Clear All Readings", use_container_width=True):
        st.session_state.debugger_readings = {}
        st.rerun()


def _get_reports_dir():
    prog = get_selected_program()
    if prog:
        return get_reports_dir(prog)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_reports")


def _get_ml_model_path():
    prog = get_selected_program()
    if prog:
        return get_ml_model_path(prog)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "debugger_ml_model.json")


def _get_phase_status(phase_num, readings):
    """Evaluate all TPs in a phase and return status: gray/blue/green/red/orange."""
    ptps = {k: v for k, v in test_points_for().items() if v["phase"] == phase_num}
    if not ptps:
        return "gray"
    has_data = False
    has_fail = False
    has_monitor = False
    has_warn = False
    all_pass = True
    for k, tp in ptps.items():
        val = readings.get(k)
        if val is not None and val != "":
            has_data = True
            s, _ = evaluate(val, tp)
            if s == "fail":
                has_fail = True
                all_pass = False
            elif s == "monitor":
                has_monitor = True
            elif s == "warn":
                has_warn = True
            elif s != "pass":
                all_pass = False
        else:
            all_pass = False
    if has_fail:
        return "red"
    if has_data and all_pass:
        return "green" if not has_monitor and not has_warn else "orange" if has_monitor else "orange"
    if has_data:
        return "blue"
    return "gray"


def _render_phase_status_bar(readings):
    """Render horizontal phase status indicator bar."""
    pills = ""
    for pn in sorted(phases_for()):
        ph = phases_for()[pn]
        status = _get_phase_status(pn, readings)
        cls = f"pp-{status}"
        icon_map = {"gray": "⬜", "blue": "🔵", "green": "🟢", "red": "🔴", "orange": "🟠"}
        ic = icon_map.get(status, "⬜")
        pills += f'<div class="phase-pill {cls}">{ic}<br>P{pn}: {ph["name"][:12]}</div>'
    st.markdown(f'<div class="phase-bar">{pills}</div>', unsafe_allow_html=True)


VI_OPTIONS = ["No Damage", "Crack / Physical Damage", "Liquid Ingress", "Burn Marks / Discoloration",
              "Bent Pins / Connector Damage", "Corrosion", "Missing Components", "Other"]


def _render_visual_inspection():
    """Render visual inspection step before Phase 1. Returns True only for info, never blocks."""
    st.markdown('<div class="vi-box">', unsafe_allow_html=True)
    st.markdown("##### 👁️ Step 0: Visual Inspection (Required)")
    st.markdown('<span style="color:#aaa;font-size:.9em;">Inspect the PCB before powering on. Select all that apply.</span>', unsafe_allow_html=True)
    if "vi_findings" not in st.session_state:
        st.session_state.vi_findings = []
    if "vi_notes" not in st.session_state:
        st.session_state.vi_notes = ""
    findings = st.multiselect("Visual Inspection Findings", VI_OPTIONS, default=st.session_state.vi_findings, key="vi_select")
    st.session_state.vi_findings = findings
    notes = st.text_area("Additional VI Notes", value=st.session_state.vi_notes, key="vi_notes_input",
                         placeholder="Describe location/severity of any damage found...", height=68)
    st.session_state.vi_notes = notes
    st.markdown('</div>', unsafe_allow_html=True)

    if "Liquid Ingress" in findings:
        st.markdown(
            '<div class="vb vb-f" style="border-color:#e67e22;">'
            '<span class="led led-orange"></span>⚠️ <b>PROCEED WITH CAUTION — Liquid Ingress Detected</b><br>'
            'Failure Symptom: <b>Potential dead board due to Liquid Ingress</b>. '
            'Follow the precautionary steps below before powering on.</div>', unsafe_allow_html=True)
        with st.expander("🧪 Liquid Ingress — Precautionary Steps Before Testing", expanded=True):
            # Critical rails to ohm-check are pulled from THIS program's board
            # pack, so the guidance never names another board's components.
            _tps = test_points_for()
            _graph = board_graph_for()
            _rail_lines = []
            for _k in (_graph.get("boot_critical") or [])[:6]:
                _tp = _tps.get(_k, {})
                if _tp:
                    _rail_lines.append(
                        f"   - {_tp.get('name', _k)} ({_tp.get('tp', '?')}) to GND: "
                        f"expect >5Ω (if <1Ω, suspect a corrosion short)")
            _rail_block = ("\n".join(_rail_lines) if _rail_lines else
                           "   - (No power tree defined for this program — check each major rail to GND)")
            _bga = ", ".join(sorted({
                str(t.get("subsystem", "")).split("->")[-1].strip()
                for t in _tps.values() if t.get("subsystem")
            } - {""}))[:200] or "the large BGA/QFN packages"

            st.markdown(f"""
**Pre-Power-On Cleaning & Drying Protocol:**

1. **Remove all visible liquid** — Tilt the board and blot with lint-free wipes. Do NOT shake vigorously (can spread liquid under BGA/QFN packages).
2. **Clean with 90%+ Isopropyl Alcohol (IPA)** — Use high-purity IPA (≥90%, ideally 99%) to displace water and dissolved minerals. Apply with a soft brush or lint-free swab around connectors, under shields, and near fine-pitch components. ([source](https://www.wonderfulpcb.com/blog/cleaning-printed-circuit-boards-without-causing-damage/))
3. **Pay special attention to BGA areas** — liquid becomes trapped under large BGA packages (on this board: {_bga}). Use compressed air at low pressure to help displace moisture from beneath them.
4. **Dry in a controlled environment** — Allow minimum 24-48 hours drying time in a warm, ventilated area (40-50°C). Use desiccant packs or a low-temperature oven if available. Do NOT use a heat gun directly on components. ([source](https://www.elektroda.com/qa,water-damage-electronics-solutions.html))
5. **Inspect for corrosion** — Look for white/green residue on copper traces, connector pins, and solder joints. Corrosion on fine-pitch pads (0.4mm BGA) can cause intermittent failures days after exposure. ([source](https://remedics.com/water-damaged-electronics-drying))
6. **Check resistance to ground on critical rails before powering** — Use a multimeter to measure resistance from each major rail to GND:
{_rail_block}
7. **Use a current-limited power supply** — Set current limit to 500mA initially. If the board draws excessive current immediately, power off and re-inspect for shorts.
8. **Document corrosion locations** — Photograph any corrosion areas for the FA report. Note which subsystems are affected.
9. **Monitor temperature during first power-on** — Use a thermal camera or touch-test for hot spots that indicate shorted components.

*Content was rephrased for compliance with licensing restrictions.*
""")
    if "Burn Marks / Discoloration" in findings:
        st.markdown('<div class="vb vb-f" style="border-color:#e67e22;"><span class="led led-orange"></span>⚠️ <b>Burn Marks Detected</b><br>'
                    'Inspect for shorted components near burn area. Identify affected subsystem before powering on. '
                    'Risk of further damage if powered with existing short.</div>', unsafe_allow_html=True)
    if "Crack / Physical Damage" in findings:
        st.info("📋 Physical damage noted. Proceed with caution — check affected area TPs carefully.")
    return False


def _generate_dfmea_report(readings, dut_id, test_date, test_stage, vi_findings, vi_notes):
    """Generate failure analysis report and store for ML training."""
    report = {
        "report_id": f"FA-{dut_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "dut_id": dut_id,
        "test_date": str(test_date),
        "test_stage": test_stage,
        "generated_at": datetime.now().isoformat(),
        "visual_inspection": {"findings": vi_findings, "notes": vi_notes},
        "phases": {},
        "overall_verdict": "PASS",
        "failed_subsystems": [],
        "root_causes": [],
        "dfmea_entries": [],
    }

    all_fail = False
    for pn in sorted(phases_for()):
        ph = phases_for()[pn]
        ptps = {k: v for k, v in test_points_for().items() if v["phase"] == pn}
        phase_data = {"name": ph["name"], "verdict": "PASS", "test_points": [], "failures": []}
        for k, tp in ptps.items():
            val = readings.get(k)
            s, m = evaluate(val, tp)
            n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
            try:
                d = f"{float(val):.4f}" if val else "N/T"
            except (ValueError, TypeError):
                d = "N/T"
            tp_entry = {"tp": tp["tp"], "rail": tp["name"], "lsl": tp["lsl"], "nom": n,
                        "usl": tp["usl"], "dut_value": d, "unit": tp["unit"],
                        "status": s, "detail": m, "subsystem": tp["subsystem"],
                        "is_monitor": tp.get("monitor", False)}
            phase_data["test_points"].append(tp_entry)
            if s == "fail":
                phase_data["verdict"] = "FAIL"
                all_fail = True
                phase_data["failures"].append(tp_entry)
                # DFMEA entry
                report["dfmea_entries"].append({
                    "item": tp["tp"],
                    "function": tp["name"],
                    "potential_failure_mode": m,
                    "potential_effect": tp["fail_action"],
                    "severity": 8 if ph["critical"] else 5,
                    "potential_cause": f"{tp['subsystem']} failure",
                    "occurrence": 4,
                    "detection_method": f"Measurement at {tp['tp']}",
                    "detection": 3,
                    "rpn": (8 if ph["critical"] else 5) * 4 * 3,
                    "recommended_action": tp["fail_action"],
                    "subsystem": tp["subsystem"],
                    "phase": pn,
                })
                if tp["subsystem"] not in report["failed_subsystems"]:
                    report["failed_subsystems"].append(tp["subsystem"])
                    report["root_causes"].append(f"{tp['subsystem']}: {m}")
        report["phases"][str(pn)] = phase_data

    if "Liquid Ingress" in vi_findings:
        report["overall_verdict"] = "FAIL — Liquid Ingress"
        report["root_causes"].insert(0, "Liquid Ingress detected during Visual Inspection")
    elif all_fail:
        report["overall_verdict"] = "FAIL"
    else:
        report["overall_verdict"] = "PASS"

    # Store report for ML training
    os.makedirs(_get_reports_dir(), exist_ok=True)
    report_path = os.path.join(_get_reports_dir(), f"{report['report_id']}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Update ML training data
    _update_ml_model(report)

    return report


def _update_ml_model(report):
    """Incrementally update ML pattern database from new report."""
    model = {"patterns": {}, "failure_counts": {}, "subsystem_correlations": {}, "total_reports": 0}
    ml_path = _get_ml_model_path()
    if os.path.exists(ml_path):
        try:
            with open(ml_path) as f:
                model = json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass

    model["total_reports"] = model.get("total_reports", 0) + 1

    # Track failure patterns: which TPs fail together
    failed_tps = []
    for pdata in report["phases"].values():
        for tp in pdata.get("failures", []):
            tp_name = tp["tp"]
            failed_tps.append(tp_name)
            model["failure_counts"][tp_name] = model["failure_counts"].get(tp_name, 0) + 1

    # Track co-failure patterns (which TPs fail together)
    if len(failed_tps) > 1:
        pattern_key = "+".join(sorted(failed_tps))
        if "patterns" not in model:
            model["patterns"] = {}
        model["patterns"][pattern_key] = model["patterns"].get(pattern_key, 0) + 1

    # Track subsystem correlations
    for sub in report.get("failed_subsystems", []):
        model["subsystem_correlations"][sub] = model["subsystem_correlations"].get(sub, 0) + 1

    # Track VI findings
    for vi in report.get("visual_inspection", {}).get("findings", []):
        if vi != "No Damage":
            vi_key = f"VI:{vi}"
            model["failure_counts"][vi_key] = model["failure_counts"].get(vi_key, 0) + 1

    with open(_get_ml_model_path(), "w") as f:
        json.dump(model, f, indent=2)


def _get_ml_insights():
    """Get ML-derived insights from accumulated reports."""
    ml_path = _get_ml_model_path()
    if not os.path.exists(ml_path):
        return None
    try:
        with open(ml_path) as f:
            model = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return None
    if model.get("total_reports", 0) < 2:
        return None
    return model


def _render_report_ui(report):
    """Render the Failure Analysis report in the UI."""
    st.markdown("---")
    st.markdown(f'<div style="text-align:center;font-size:1.3em;font-weight:700;color:#211B33;margin:10px 0;">📋 Failure Analysis Report</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="text-align:center;color:#5B5470;margin-bottom:12px;">Report ID: {report["report_id"]}</div>', unsafe_allow_html=True)

    # Header info
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("DUT S/N", report["dut_id"] or "N/A")
    c2.metric("Date", report["test_date"])
    c3.metric("Stage", report["test_stage"])
    c4.metric("Verdict", report["overall_verdict"])

    # Visual Inspection
    vi = report["visual_inspection"]
    vi_text = ", ".join(vi["findings"]) if vi["findings"] else "No Damage"
    st.markdown(f"**Visual Inspection:** {vi_text}")
    if vi["notes"]:
        st.markdown(f"**VI Notes:** {vi['notes']}")

    # Phase-by-phase summary
    st.markdown("##### Phase Summary")
    for pn_str, pdata in report["phases"].items():
        pn = int(pn_str)
        ph = phases_for()[pn]
        v = pdata["verdict"]
        ic = "✅" if v == "PASS" else "❌"
        fail_info = ""
        if pdata["failures"]:
            circuits = [f["subsystem"] for f in pdata["failures"]]
            fail_info = f' — Investigate: **{", ".join(circuits)}**'
        st.markdown(f"{ic} **Phase {pn}: {ph['name']}** → {v}{fail_info}")

    # Risk Analysis Table
    if report["dfmea_entries"]:
        st.markdown("##### Risk Analysis")
        dfmea_rows = ""
        for e in report["dfmea_entries"]:
            dfmea_rows += (f'<tr><td>{e["item"]}</td><td>{e["function"]}</td>'
                           f'<td>{e["potential_failure_mode"]}</td><td>{e["potential_cause"]}</td>'
                           f'<td style="text-align:center">{e["severity"]}</td>'
                           f'<td style="text-align:center">{e["occurrence"]}</td>'
                           f'<td style="text-align:center">{e["detection"]}</td>'
                           f'<td style="text-align:center;font-weight:bold;color:#e74c3c">{e["rpn"]}</td>'
                           f'<td>{e["recommended_action"][:60]}...</td></tr>')
        st.markdown(f'<table class="st"><thead><tr><th>TP</th><th>Function</th><th>Failure Mode</th>'
                    f'<th>Potential Cause</th><th>S</th><th>O</th><th>D</th><th>RPN</th>'
                    f'<th>Action</th></tr></thead><tbody>{dfmea_rows}</tbody></table>', unsafe_allow_html=True)

    # Root causes
    if report["root_causes"]:
        st.markdown("##### Root Cause Summary")
        for rc in report["root_causes"]:
            st.error(f"🔍 {rc}")

    # ML Insights
    ml = _get_ml_insights()
    if ml:
        st.markdown("##### 🤖 ML Pattern Insights")
        st.markdown(f'<span style="color:#888;">Based on {ml["total_reports"]} historical reports</span>', unsafe_allow_html=True)
        # Top failing TPs
        if ml.get("failure_counts"):
            sorted_fails = sorted(ml["failure_counts"].items(), key=lambda x: x[1], reverse=True)[:5]
            for tp_name, count in sorted_fails:
                pct = (count / ml["total_reports"]) * 100
                st.markdown(f"- **{tp_name}**: failed in {count}/{ml['total_reports']} reports ({pct:.0f}%)")
        # Co-failure patterns
        if ml.get("patterns"):
            sorted_patterns = sorted(ml["patterns"].items(), key=lambda x: x[1], reverse=True)[:3]
            if sorted_patterns:
                st.markdown("**Common co-failure patterns:**")
                for pattern, count in sorted_patterns:
                    st.markdown(f"- {pattern.replace('+', ' + ')} → {count} occurrences")

    # Download
    report_json = json.dumps(report, indent=2)
    st.download_button("📥 Download FA Report (JSON)", data=report_json,
                       file_name=f"{report['report_id']}.json", mime="application/json", use_container_width=True)
    # CSV version
    if report["dfmea_entries"]:
        df = pd.DataFrame(report["dfmea_entries"])
        st.download_button("📥 Download FA Table (CSV)", data=df.to_csv(index=False),
                           file_name=f"{report['report_id']}_dfmea.csv", mime="text/csv", use_container_width=True)


def _render_daa_mechanism(mech, rank):
    """Render one ranked failure-mechanism hypothesis with tests and citations."""
    score = mech.get("likelihood_score", 0)
    badge = "🔴 Most likely" if rank == 0 else ("🟠 Likely" if score >= 4 else "🟡 Possible")
    with st.expander(f"{rank+1}. {mech['name']}  ·  {badge}", expanded=(rank == 0)):
        st.markdown(f"<span style='color:#5B5470;'>{mech['description']}</span>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Likely root causes**")
            for c in mech.get("root_causes", []):
                st.markdown(f"- {c}")
        with col2:
            st.markdown("**Confirm nondestructively (do these first)**")
            for t in mech.get("nondestructive_tests", []):
                st.markdown(f"- {t}")
        if mech.get("destructive_tests"):
            st.markdown("**Destructive confirmation (last resort):** "
                        + "; ".join(mech["destructive_tests"]))
        refs = mech.get("references", [])
        if refs:
            links = "  ·  ".join(f"[{r['title']}]({r['url']})" for r in refs)
            st.markdown(f"<span style='font-size:.82em;color:#8B84A0;'>Sources: {links}</span>",
                        unsafe_allow_html=True)


def _render_daa_deduction(ded, resistances):
    """Render the full deduction: verdict, root faults, mechanisms, consequences."""
    verdict = ded["verdict"]
    vtext = ded["verdict_text"]
    if verdict == "power_fault_localized":
        st.markdown(f'<div class="vb vb-f"><b>🎯 {vtext}</b></div>', unsafe_allow_html=True)
    elif verdict == "power_ok_escalate":
        st.markdown(f'<div class="vb vb-p"><b>✅ {vtext}</b></div>', unsafe_allow_html=True)
    else:
        st.info(vtext)

    for i, h in enumerate(ded["hypotheses"]):
        st.markdown(f'<div class="ph ph-c">Root fault {i+1}: {h["rail"]}</div>', unsafe_allow_html=True)
        if h.get("location"):
            st.caption(f"📍 {h['location']}")
        st.markdown(f"**Electrical signature:** {h['signature_label']}")

        # Resolve open-vs-short if a dead rail still needs the R-to-GND probe
        if h.get("needs_resistance_probe"):
            st.warning("This rail reads dead. Measure resistance from the rail to GND "
                       "(board OFF) to tell a regulator-open from a load-short.")
            rv = st.text_input(f"Resistance to GND at {h['rail'].split(' — ')[0]} (Ω)",
                               key=f"daa_r_{h['node']}", placeholder="e.g. 0.4 or 12")
            rf = _to_float_safe(rv)
            if rf is not None:
                resistances[h["node"]] = rf
                verdict_rs = daa.open_or_short(rf)
                icon = "🔻 SHORT" if verdict_rs["signature"] == daa_kb.SIG_DEAD_SHORT else "⭕ OPEN"
                st.markdown(f"**{icon} — {verdict_rs['verdict']}.** {verdict_rs['meaning']}")
                st.caption(verdict_rs["first_action"])
                if verdict_rs["ambiguous"]:
                    st.caption("⚠️ Resistance is in the ambiguous 1–5 Ω band — treat as a loaded "
                               "regulator and confirm by scoping the switching node.")

        if h.get("board_fail_action"):
            st.markdown(f"**Board-specific guidance:** {h['board_fail_action']}")
        if h.get("schematic_path"):
            st.markdown(f"**Signal path:** `{h['schematic_path']}`")

        # Point at the workspace for the side-by-side schematic rather than
        # nesting another viewer inside this report.
        _node = h.get("node")
        if _node:
            try:
                import schematic_index as _si
                _hits = _si.search_index(get_selected_program(),
                                         str(h["rail"].split(" — ")[0]).strip())
                if _hits:
                    st.caption("📐 This rail appears on: "
                               + ", ".join(dict.fromkeys(x["filename"] for x in _hits[:3]))
                               + " — open the **🔬 Debug Workspace** to see it beside the readings.")
            except Exception:
                pass

        st.markdown("##### Ranked failure mechanisms (knowledge base)")
        for rank, mech in enumerate(h.get("mechanisms", [])):
            _render_daa_mechanism(mech, rank)

        # Board component-level checklist (reuse existing renderer)
        if h.get("component_diagnostics"):
            st.markdown("##### Board component checklist for this rail")
            _render_component_diagnostics(h["component_diagnostics"])

    if ded["consequences"]:
        names = ", ".join(c["node"].replace("V_", "").replace("_", " ") for c in ded["consequences"])
        st.markdown(f'<div class="dd"><b>Downstream rails explained by the root fault (not separate faults):</b> {names}</div>', unsafe_allow_html=True)
    if ded["marginal"]:
        st.caption("Marginal (near-limit) rails to keep an eye on: "
                   + ", ".join(m.replace("V_", "").replace("_", " ") for m in ded["marginal"]))


def _to_float_safe(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _daa_report_text(summary, did, td, prog):
    """Human-readable DAA localization report (markdown)."""
    lines = [f"# DAA Failure-Analysis Report — {prog}",
             f"DUT: {did or 'N/A'}    Date: {td}",
             f"Complaint: {summary['complaint']}", "",
             f"## Verdict\n{summary['verdict_text']}", ""]
    if summary.get("primary_fault_rail"):
        lines += [f"Primary fault rail: {summary['primary_fault_rail']}",
                  f"Signature: {summary['primary_signature']}",
                  f"Most likely mechanism: {summary['top_mechanism']}", ""]
    for i, h in enumerate(summary["hypotheses"]):
        lines.append(f"## Root fault {i+1}: {h['rail']}")
        lines.append(f"- Signature: {h['signature_label']}")
        if h.get("board_fail_action"):
            lines.append(f"- Board guidance: {h['board_fail_action']}")
        lines.append("- Ranked mechanisms:")
        for m in h.get("mechanisms", []):
            refs = "; ".join(r["url"] for r in m.get("references", []))
            lines.append(f"  - {m['name']} (score {m.get('likelihood_score',0)}) — sources: {refs}")
    if summary.get("consequences_suppressed"):
        lines.append("\n## Downstream consequences (explained by root fault)")
        lines.append(", ".join(summary["consequences_suppressed"]))
    return "\n".join(lines)


def render_daa_ui(did, td, ts):
    """DAA Fault Localizer — guided, schematic-aware, knowledge-base-backed."""
    prog = get_selected_program() or "PCB"
    st.markdown(
        '<div style="text-align:center;font-size:1.4em;font-weight:700;margin:4px 0 2px;'
        'background:linear-gradient(100deg,#5B21B6 0%,#7C3AED 100%);'
        '-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">'
        '🎯 DAA Fault Localizer</div>', unsafe_allow_html=True)
    st.caption("Deterministic power-tree fault isolation fused with a cited PCB failure-analysis "
               "knowledge base. Works with no training data.")

    if "daa_resistances" not in st.session_state:
        st.session_state.daa_resistances = {}
    readings = st.session_state.debugger_readings

    c1, c2 = st.columns([2, 3])
    with c1:
        complaint = st.selectbox("Reported complaint", list(daa.COMPLAINTS.keys()),
                                 format_func=lambda k: daa.COMPLAINTS[k])
    with c2:
        obs = st.text_area("Visual / environmental observations (optional)",
                           key="daa_observations", height=68,
                           placeholder="e.g. burnt smell near SoC, corrosion at connector, cracked cap, bulging")

    approach = st.radio("Approach", ["Guided probe (recommended)", "Analyze what I've measured"],
                        horizontal=True)

    st.markdown("---")

    graph = board_graph_for()

    if approach == "Guided probe (recommended)":
        branch = graph["complaint_branches"].get(complaint) or graph["boot_critical"]
        measured = [k for k in branch if k in readings]
        st.caption(f"Measured {len(measured)} of {len(branch)} rail(s) on this branch so far.")
        nxt = daa.next_probe(readings, complaint, test_points_for(), evaluate, graph)
        if nxt:
            tp = test_points_for()[nxt["node"]]
            sp = nxt["spec"]
            nom = sp["nom"] if sp["nom"] is not None else "N/A"
            st.markdown(f'<div class="ph"><span class="led led-blue"></span>'
                        f'Next probe → <b>{nxt["tp"]} — {nxt["name"]}</b></div>', unsafe_allow_html=True)
            st.caption(f"📍 {nxt['loc']}")
            st.markdown(f"_{nxt['rationale']}_")
            st.markdown(f"Expected (KGU): **{sp['lsl']} – {sp['usl']} {sp['unit']}** (nom {nom})")
            val = st.text_input(f"Measured value at {nxt['tp']} ({sp['unit']})",
                                key=f"daa_val_{nxt['node']}")
            if val:
                readings[nxt["node"]] = val
                s, m = evaluate(val, tp)
                icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "monitor": "🟠"}.get(s, "")
                st.markdown(f"{icon} **{s.upper()}** — {m}")
                st.button("Record & recommend next probe →")  # any click reruns and advances
        else:
            st.success("Guided sequence complete for this branch — see the analysis below.")

    # Deduction / analysis
    st.markdown("---")
    show = st.button("🔬 Analyze & Localize Fault", type="primary", use_container_width=True) \
        or approach == "Analyze what I've measured"
    if show:
        if not readings:
            st.warning("No measurements yet. Use the guided probe to enter at least the PoE input and 5V bus.")
            return
        ded = daa.deduce(readings, test_points_for(), evaluate, schematic_for(),
                         observations=st.session_state.get("daa_observations", ""),
                         resistances=st.session_state.daa_resistances, graph=graph)
        _render_daa_deduction(ded, st.session_state.daa_resistances)

        # Downloadable DAA report
        summary = daa.daa_summary(readings, test_points_for(), evaluate, schematic_for(),
                                  observations=st.session_state.get("daa_observations", ""),
                                  resistances=st.session_state.daa_resistances,
                                  complaint=complaint, graph=graph)
        st.download_button("📥 Download DAA Localization Report (Markdown)",
                           data=_daa_report_text(summary, did, td, prog),
                           file_name=f"DAA_{did or 'DUT'}_{td}.md", mime="text/markdown",
                           use_container_width=True)

    # Methodology + graph-integrity caveat
    with st.expander("📚 Failure-analysis methodology (nondestructive → destructive)", expanded=False):
        for stage in daa_kb.FA_METHODOLOGY:
            tag = "🟢 nondestructive" if stage["nondestructive"] else "🔴 destructive"
            st.markdown(f"**{stage['stage']}**  ·  _{tag}_")
            for s in stage["steps"]:
                st.markdown(f"- {s}")

    with st.expander("🧭 Power-tree model & edges to verify", expanded=False):
        v = daa.validate_tree(test_points_for(), graph)
        if v["issues"]:
            st.error("Graph issues: " + "; ".join(v["issues"]))
        else:
            st.success("Power-tree integrity OK — every voltage rail is modeled with a valid source path.")
        if v["unverified_edges"]:
            st.caption("These parent edges were inferred from schematic descriptions and should be "
                       "engineer-verified against the schematic:")
            for n in v["unverified_edges"]:
                tp = test_points_for().get(n, {})
                parent = str(graph["tree"].get(n, {}).get("parent", "?")).replace("V_", "").replace("_", " ")
                st.markdown(f"- **{tp.get('tp', n)}** ({tp.get('name','')}) ← assumed fed by *{parent}*")


def _render_pack_unavailable(program, cap):
    """Explain that hardware debug isn't available for this program yet, and how
    to onboard it. Deliberately shows NO board data from any other program."""
    name = program or "this program"
    st.info(f"🚧 **PCB Debugger is not available for {name} yet — design data hasn't been integrated.**")

    st.markdown(f"""
The debugger needs {name}'s **board pack**: its test points, spec limits (KGU),
schematic circuits, and power tree. Until that's added, this view stays disabled
rather than showing another program's board — probing the wrong pads or trusting
the wrong spec limits would be worse than no data.
""")

    st.markdown("##### Current status")
    rows = [
        ("Board pack", "✅ Found" if cap["has_pack"] else "❌ Not created"),
        ("Test points", f"✅ {cap['n_test_points']}" if cap["has_test_points"] else "❌ None"),
        ("Schematic circuits", f"✅ {cap['n_schematic']}" if cap["has_schematic"] else "❌ None"),
        ("Power tree (DAA)", "✅ Defined" if cap["has_power_tree"] else "❌ Not defined"),
        ("Debug bible", "✅ Found" if cap["has_bible"] else "❌ Not added"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Asset", "Status"]),
                 use_container_width=True, hide_index=True)

    if cap["issues"]:
        st.markdown("##### Validation issues to fix")
        for i in cap["issues"][:10]:
            st.markdown(f"- {i}")

    with st.expander("📋 How to onboard this program (repeatable process)", expanded=True):
        st.markdown(f"""
1. **Create the starter pack**
   ```
   python board_pack.py init {name}
   ```
   This scaffolds `programs/{(program or 'program').lower().replace(' ', '_')}/board/board_pack.json`
   plus a `schematics/` folder.

2. **Add the source design documents** (reference material) to
   `programs/.../board/schematics/` — schematic PDFs, PCB top/bottom images,
   power-tree diagrams.

3. **Fill in the pack** — phases, test points (with LSL/nominal/USL from the
   KGU spec), schematic circuits, fault trees, and the power tree.

4. **Add the debug bible** as `programs/.../<program>_debug_bible.md`.

5. **Validate**
   ```
   python board_pack.py validate {name}
   ```
   Fix anything it reports, then reload this page — the debugger and the DAA
   Fault Localizer light up automatically.

See **ONBOARDING.md** for the full field-by-field guide.
""")
    st.caption(f"Expected pack location: `{cap['pack_path']}`")


def render_debugger_ui():
    st.markdown(CSS, unsafe_allow_html=True)
    prog = get_selected_program() or "PCB"
    st.markdown(
        f'<div style="text-align:center;font-size:1.7em;font-weight:700;margin-bottom:4px;'
        f'background:linear-gradient(100deg,#5B21B6 0%,#7C3AED 100%);'
        f'-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">'
        f'{prog} PCB Interactive Debugger</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div style="text-align:center;color:#888;margin-bottom:16px;">Step-by-step fault isolation — KGU spec vs DUT measurement</div>', unsafe_allow_html=True)

    # ---- Capability gate -------------------------------------------------
    # Never fall back to another program's board data. If this program has no
    # board pack, say so and show how to onboard it.
    selected = get_selected_program()
    cap = board_pack.capabilities(selected)
    if not cap["has_test_points"]:
        _render_pack_unavailable(selected, cap)
        return
    if cap["issues"]:
        st.warning(f"⚠️ {selected}'s board pack has {len(cap['issues'])} validation issue(s). "
                   "Measurements may be unreliable until fixed:")
        for i in cap["issues"][:8]:
            st.markdown(f"- {i}")

    if "debugger_dut_id" not in st.session_state:
        st.session_state.debugger_dut_id = ""
    if "debugger_readings" not in st.session_state:
        st.session_state.debugger_readings = {}
    if "debugger_test_date" not in st.session_state:
        st.session_state.debugger_test_date = date.today()
    if "debugger_test_stage" not in st.session_state:
        st.session_state.debugger_test_stage = "U-Boot (Power-On)"

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        did = st.text_input("DUT Serial / ID", value=st.session_state.debugger_dut_id, placeholder="e.g. SNB-2026-00142")
        st.session_state.debugger_dut_id = did
    with c2:
        td = st.date_input("Test Date", value=st.session_state.debugger_test_date)
        st.session_state.debugger_test_date = td
    with c3:
        ts = st.selectbox("Test Stage", ["U-Boot (Power-On)", "QSDK (Full OS)", "Custom"])
        st.session_state.debugger_test_stage = ts

    # Phase status bar — always visible at top
    _render_phase_status_bar(st.session_state.debugger_readings)

    # Board reference map toggle
    with st.expander("📍 PCB Test Point Reference Map (click to expand)", expanded=False):
        _render_board_map()

    st.markdown("---")

    # Visual Inspection — always shown before phases
    _render_visual_inspection()

    st.markdown("---")
    mode = st.radio("Debug Mode", ["Guided (Phase-by-Phase)", "Quick Scan (All Rails)",
                                   "Deep Dive (Single Group)", "🎯 DAA Fault Localizer"], horizontal=True)

    if mode == "🎯 DAA Fault Localizer":
        render_daa_ui(did, td, ts)
        return

    if mode == "Guided (Phase-by-Phase)":
        _ph = phases_for()
        opts = [f"{_ph[k]['icon']} Phase {k}: {_ph[k]['name']}" for k in sorted(_ph)]
        si = st.selectbox("Select Phase (work top to bottom)", range(len(opts)), format_func=lambda i: opts[i])
        pn = si + 1
        ph = phases_for()[pn]
        cc = " ph-c" if ph["critical"] else ""
        ct = " ⚠️ CRITICAL" if ph["critical"] else ""
        # LED: blue while entering data (pre-analysis)
        st.markdown(f'<div class="ph{cc}"><span class="led led-blue"></span>{ph["icon"]} Phase {pn}: {ph["name"]}{ct}<br><span style="font-size:.85em;font-weight:400;color:#aaa;">{ph["desc"]}</span></div>', unsafe_allow_html=True)
        ptps = {k: v for k, v in test_points_for().items() if v["phase"] == pn}
        if not ptps:
            st.info("No test points for this phase.")
            return
        rd = {}
        st.markdown("##### Enter DUT Measurements")
        for k, tp in ptps.items():
            n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
            lb = f'Step {tp["step"]}  ➜  {tp["tp"]} — {tp["name"]}  |  LSL: {tp["lsl"]}  |  Nom: {n}  |  USL: {tp["usl"]} {tp["unit"]}'
            sv = st.session_state.debugger_readings.get(k, "")
            val = st.text_input(lb, value=sv, key=f"g_{k}", placeholder=f'📍 {tp["loc"]}', help=f'Board location: {tp["loc"]}')
            if val:
                rd[k] = val
                st.session_state.debugger_readings[k] = val
        if st.button("Analyze Phase", type="primary", use_container_width=True):
            _phase_results(ptps, rd, pn)

        # Report generation button (available after any data entry)
        st.markdown("---")
        if st.button("📋 Generate Full FA Report", use_container_width=True):
            report = _generate_dfmea_report(
                st.session_state.debugger_readings, did, td, ts,
                st.session_state.get("vi_findings", []),
                st.session_state.get("vi_notes", ""))
            _render_report_ui(report)

    elif mode == "Quick Scan (All Rails)":
        st.markdown("##### Enter all DUT measurements (leave blank to skip)")
        rd = {}
        for pn in sorted(phases_for()):
            ph = phases_for()[pn]
            ptps = {k: v for k, v in test_points_for().items() if v["phase"] == pn}
            if not ptps: continue
            cc = " ph-c" if ph["critical"] else ""
            st.markdown(f'<div class="ph{cc}">{ph["icon"]} Phase {pn}: {ph["name"]}</div>', unsafe_allow_html=True)
            cols = st.columns(min(len(ptps), 3))
            for i, (k, tp) in enumerate(ptps.items()):
                with cols[i % len(cols)]:
                    n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
                    sv = st.session_state.debugger_readings.get(k, "")
                    val = st.text_input(f'#{tp["step"]} {tp["tp"]}: {tp["name"]}', value=sv, key=f"q_{k}",
                                        placeholder=f'{tp["lsl"]}-{tp["usl"]} {tp["unit"]} (nom {n})',
                                        help=f'📍 {tp["loc"]} | LSL={tp["lsl"]} | Nom={n} | USL={tp["usl"]} {tp["unit"]}')
                    if val:
                        rd[k] = val
                        st.session_state.debugger_readings[k] = val
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Analyze All Rails", type="primary", use_container_width=True):
                _full_summary(rd)
        with col2:
            if st.button("📋 Generate Full FA Report", use_container_width=True):
                report = _generate_dfmea_report(
                    st.session_state.debugger_readings, did, td, ts,
                    st.session_state.get("vi_findings", []),
                    st.session_state.get("vi_notes", ""))
                _render_report_ui(report)

    else:  # Deep Dive
        groups = list(fault_trees_for().keys())
        sg = st.selectbox("Select Subsystem to Deep Dive", groups)
        tree = fault_trees_for()[sg]
        st.markdown(f'<div class="ph">{tree["title"]}</div>', unsafe_allow_html=True)
        gtps = {k: v for k, v in test_points_for().items() if v["group"] == sg or v["group"].startswith(sg.split(" ")[0])}
        if gtps:
            st.markdown("##### Relevant Test Points")
            rd = {}
            cols = st.columns(min(len(gtps), 3))
            for i, (k, tp) in enumerate(gtps.items()):
                with cols[i % len(cols)]:
                    sv = st.session_state.debugger_readings.get(k, "")
                    val = st.text_input(f'#{tp["step"]} {tp["tp"]}: {tp["name"]}', value=sv, key=f"d_{k}",
                                        placeholder=f'{tp["lsl"]}-{tp["usl"]} {tp["unit"]}',
                                        help=f'📍 {tp["loc"]}')
                    if val:
                        rd[k] = val
                        st.session_state.debugger_readings[k] = val
            if st.button("Analyze", type="primary", use_container_width=True):
                for k, tp in gtps.items():
                    val = rd.get(k)
                    s, m = evaluate(val, tp)
                    st.markdown(_tp_row(tp, val, s, m), unsafe_allow_html=True)
                    if s == "fail":
                        st.error(f"**{tp['tp']} FAIL:** {tp['fail_action']}")
                        _render_schematic_lookup(tp["tp"])
        st.markdown("##### Fault Isolation Steps")
        sh = "".join(f"<li>{s[3:]}</li>" for s in tree["steps"])
        st.markdown(f'<div class="dd"><ol>{sh}</ol></div>', unsafe_allow_html=True)
