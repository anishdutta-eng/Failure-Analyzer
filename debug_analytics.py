"""Debug Statistical Analytics — Weibull, Pareto, Correlation, Trend Analysis."""
import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from program_config import get_reports_dir, get_ml_model_path, get_selected_program


def _get_reports_dir():
    prog = get_selected_program()
    if prog:
        return get_reports_dir(prog)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_reports")


def _reports_signature(rdir):
    """Return a (filename, mtime) tuple for every report JSON — used as a cache
    key so the loader re-reads only when files are added/changed."""
    if not os.path.isdir(rdir):
        return ()
    sig = []
    for fname in sorted(os.listdir(rdir)):
        if fname.endswith(".json"):
            try:
                sig.append((fname, os.path.getmtime(os.path.join(rdir, fname))))
            except OSError:
                pass
    return tuple(sig)


@st.cache_data(show_spinner=False)
def _load_reports_cached(rdir, signature):
    """Load reports from disk. Cached on (rdir, signature); the signature busts
    the cache whenever the set of reports or their mtimes change."""
    reports = []
    for fname, _ in signature:
        try:
            with open(os.path.join(rdir, fname)) as f:
                reports.append(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return reports


def _load_all_reports():
    """Load all stored FA reports into a list (cached on dir + file mtimes)."""
    rdir = _get_reports_dir()
    return _load_reports_cached(rdir, _reports_signature(rdir))


def _reports_to_dataframe(reports):
    """Flatten reports into a DataFrame for analysis."""
    rows = []
    for r in reports:
        base = {"report_id": r.get("report_id", ""), "dut_id": r.get("dut_id", ""),
                "test_date": r.get("test_date", ""), "test_stage": r.get("test_stage", ""),
                "overall_verdict": r.get("overall_verdict", ""),
                "vi_findings": ", ".join(r.get("visual_inspection", {}).get("findings", [])),
                "num_failures": len(r.get("dfmea_entries", [])),
                "failed_subsystems": ", ".join(r.get("failed_subsystems", []))}
        # Add per-TP data
        for pn_str, pdata in r.get("phases", {}).items():
            for tp in pdata.get("test_points", []):
                row = {**base, "phase": int(pn_str), "phase_name": pdata.get("name", ""),
                       "tp": tp["tp"], "rail": tp["rail"], "status": tp["status"],
                       "dut_value": tp["dut_value"], "lsl": tp["lsl"], "usl": tp["usl"],
                       "subsystem": tp["subsystem"], "is_monitor": tp.get("is_monitor", False)}
                rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _weibull_analysis(df_reports):
    """Weibull analysis on failure data — models failure distribution over report sequence."""
    st.markdown("##### 📊 Weibull Failure Distribution Analysis")
    st.markdown('<span style="color:#aaa;font-size:.9em;">Models how failures distribute across the test population. '
                'β < 1 = infant mortality, β ≈ 1 = random, β > 1 = wear-out.</span>', unsafe_allow_html=True)

    # Get failure counts per report
    fail_counts = df_reports.groupby("report_id").agg(
        failures=("status", lambda x: (x == "fail").sum()),
        total_tps=("status", "count")
    ).reset_index()
    fail_counts["fail_rate"] = fail_counts["failures"] / fail_counts["total_tps"]

    # We need at least some failure data
    fail_rates = fail_counts["fail_rate"].values
    fail_rates = fail_rates[fail_rates > 0]

    if len(fail_rates) < 3:
        st.info("Need at least 3 reports with failures for Weibull analysis. Keep generating reports.")
        return

    try:
        from scipy.stats import weibull_min
        # Fit Weibull to failure rate data
        shape, loc, scale = weibull_min.fit(fail_rates, floc=0)

        # Interpretation
        if shape < 1:
            interpretation = "**Infant Mortality (β < 1)**: Failure rate is decreasing. Early-life defects dominate — likely manufacturing or assembly issues."
        elif shape < 1.5:
            interpretation = "**Random Failures (β ≈ 1)**: Failure rate is roughly constant. Failures are random — no dominant wear mechanism."
        else:
            interpretation = "**Wear-Out (β > 1)**: Failure rate is increasing. Components are degrading over time — check thermal, mechanical stress."

        c1, c2, c3 = st.columns(3)
        c1.metric("β (Shape)", f"{shape:.3f}")
        c2.metric("η (Scale)", f"{scale:.4f}")
        c3.metric("Reports Analyzed", len(fail_counts))
        st.markdown(interpretation)

        # Plot Weibull PDF and CDF
        x = np.linspace(0.001, max(fail_rates) * 1.5, 200)
        pdf = weibull_min.pdf(x, shape, loc=0, scale=scale)
        cdf = weibull_min.cdf(x, shape, loc=0, scale=scale)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=pdf, mode="lines", name="PDF (Probability Density)",
                                 line=dict(color="#3498db", width=2)))
        fig.add_trace(go.Scatter(x=x, y=cdf, mode="lines", name="CDF (Cumulative Failure)",
                                 line=dict(color="#e74c3c", width=2), yaxis="y2"))
        fig.add_trace(go.Histogram(x=fail_rates, nbinsx=15, name="Observed Fail Rates",
                                   opacity=0.3, marker_color="#2ecc71", yaxis="y"))
        fig.update_layout(
            title=f"Weibull Distribution (β={shape:.2f}, η={scale:.4f})",
            xaxis_title="Failure Rate per Report",
            yaxis_title="Density / Count",
            yaxis2=dict(title="Cumulative Probability", overlaying="y", side="right", range=[0, 1]),
            template="plotly_dark", height=400,
            legend=dict(x=0.6, y=0.95))
        st.plotly_chart(fig, use_container_width=True)

        # Reliability prediction
        st.markdown("**Reliability Predictions:**")
        for pct in [0.10, 0.50, 0.90]:
            b_life = weibull_min.ppf(pct, shape, loc=0, scale=scale)
            st.markdown(f"- B{int(pct*100)} Life: {pct*100:.0f}% of units expected to have fail rate ≤ {b_life:.4f}")

    except Exception as e:
        st.warning(f"Weibull fit failed: {e}. Need more diverse failure data.")


def _pareto_analysis(df_reports):
    """Pareto analysis — identify the vital few failure modes."""
    st.markdown("##### 📊 Pareto Analysis (80/20 Rule)")
    st.markdown('<span style="color:#aaa;font-size:.9em;">Identifies the vital few test points and subsystems causing the majority of failures.</span>', unsafe_allow_html=True)

    fails = df_reports[df_reports["status"] == "fail"]
    if len(fails) < 1:
        st.info("No failures recorded yet. Generate reports with failure data.")
        return

    # By Test Point
    tp_counts = fails.groupby("tp").size().sort_values(ascending=False).reset_index(name="count")
    tp_counts["cumulative_pct"] = (tp_counts["count"].cumsum() / tp_counts["count"].sum() * 100)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=tp_counts["tp"], y=tp_counts["count"], name="Failure Count",
                         marker_color="#e74c3c", opacity=0.8))
    fig.add_trace(go.Scatter(x=tp_counts["tp"], y=tp_counts["cumulative_pct"], name="Cumulative %",
                             mode="lines+markers", line=dict(color="#f39c12", width=2), yaxis="y2"))
    fig.add_shape(type="line", x0=0, x1=1, y0=80, y1=80, xref="paper", yref="y2",
                  line=dict(color="#888", width=1, dash="dash"))
    fig.add_annotation(x=1, y=80, text="80%", showarrow=False, xref="paper", yref="y2",
                       font=dict(color="#888", size=10), xanchor="left")
    fig.update_layout(title="Pareto: Failures by Test Point", xaxis_title="Test Point",
                      yaxis_title="Failure Count",
                      yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105]),
                      template="plotly_dark", height=400)
    st.plotly_chart(fig, use_container_width=True)

    # 80/20 insight
    vital_few = tp_counts[tp_counts["cumulative_pct"] <= 80]
    if len(vital_few) > 0:
        st.markdown(f"🎯 **{len(vital_few)} test point(s)** account for 80% of all failures: "
                    f"**{', '.join(vital_few['tp'].tolist())}**")

    # By Subsystem
    sub_counts = fails.groupby("subsystem").size().sort_values(ascending=False).reset_index(name="count")
    sub_counts["cumulative_pct"] = (sub_counts["count"].cumsum() / sub_counts["count"].sum() * 100)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=sub_counts["subsystem"], y=sub_counts["count"], name="Failure Count",
                          marker_color="#9b59b6", opacity=0.8))
    fig2.add_trace(go.Scatter(x=sub_counts["subsystem"], y=sub_counts["cumulative_pct"], name="Cumulative %",
                              mode="lines+markers", line=dict(color="#f39c12", width=2), yaxis="y2"))
    fig2.update_layout(title="Pareto: Failures by Subsystem", xaxis_title="Subsystem",
                       yaxis_title="Failure Count",
                       yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105]),
                       template="plotly_dark", height=400)
    st.plotly_chart(fig2, use_container_width=True)


def _correlation_heatmap(df_reports):
    """Correlation heatmap — which TPs tend to fail together."""
    st.markdown("##### 🔥 Failure Correlation Heatmap")
    st.markdown('<span style="color:#aaa;font-size:.9em;">Shows which test points tend to fail together, revealing shared root causes or cascading failures.</span>', unsafe_allow_html=True)

    # Build a binary matrix: report x TP (1=fail, 0=not fail)
    fails = df_reports[df_reports["status"] == "fail"]
    if len(fails) < 2:
        st.info("Need more failure data for correlation analysis.")
        return

    pivot = df_reports.pivot_table(index="report_id", columns="tp",
                                   values="status", aggfunc=lambda x: 1 if "fail" in x.values else 0,
                                   fill_value=0)
    # Only keep TPs that have failed at least once
    fail_tps = [c for c in pivot.columns if pivot[c].sum() > 0]
    if len(fail_tps) < 2:
        st.info("Need failures in at least 2 different test points for correlation.")
        return

    corr = pivot[fail_tps].corr()

    fig = px.imshow(corr, text_auto=".2f", color_continuous_scale="RdYlGn_r",
                    title="TP Failure Co-occurrence Correlation",
                    labels=dict(color="Correlation"))
    fig.update_layout(template="plotly_dark", height=500)
    st.plotly_chart(fig, use_container_width=True)

    # Highlight strong correlations
    strong = []
    for i in range(len(fail_tps)):
        for j in range(i + 1, len(fail_tps)):
            val = corr.iloc[i, j]
            if val > 0.5:
                strong.append((fail_tps[i], fail_tps[j], val))
    if strong:
        st.markdown("**Strong co-failure patterns (correlation > 0.5):**")
        for tp1, tp2, val in sorted(strong, key=lambda x: -x[2]):
            st.markdown(f"- **{tp1}** ↔ **{tp2}**: r = {val:.2f} — likely shared root cause or cascading failure")


def _phase_failure_distribution(df_reports):
    """Which phases fail most often — sunburst and bar chart."""
    st.markdown("##### 📈 Phase Failure Distribution")

    fails = df_reports[df_reports["status"] == "fail"]
    if len(fails) < 1:
        st.info("No failures recorded yet.")
        return

    phase_counts = fails.groupby(["phase", "phase_name"]).size().reset_index(name="count")
    phase_counts["label"] = phase_counts.apply(lambda r: f"P{int(r['phase'])}: {r['phase_name']}", axis=1)

    fig = px.bar(phase_counts, x="label", y="count", color="count",
                 color_continuous_scale="Reds", title="Failures by Phase")
    fig.update_layout(template="plotly_dark", height=350, xaxis_title="Phase", yaxis_title="Failure Count")
    st.plotly_chart(fig, use_container_width=True)

    # Subsystem sunburst
    sub_data = fails.groupby(["phase_name", "subsystem", "tp"]).size().reset_index(name="count")
    if len(sub_data) > 1:
        fig2 = px.sunburst(sub_data, path=["phase_name", "subsystem", "tp"], values="count",
                           title="Failure Hierarchy: Phase → Subsystem → Test Point",
                           color="count", color_continuous_scale="Reds")
        fig2.update_layout(template="plotly_dark", height=500)
        st.plotly_chart(fig2, use_container_width=True)


def _trend_analysis(df_reports, reports):
    """Failure rate trend over time."""
    st.markdown("##### 📉 Failure Rate Trend Over Time")

    report_summary = []
    for r in reports:
        total = 0
        fails = 0
        for pdata in r.get("phases", {}).values():
            for tp in pdata.get("test_points", []):
                if tp["status"] != "skip":
                    total += 1
                    if tp["status"] == "fail":
                        fails += 1
        if total > 0:
            report_summary.append({
                "date": r.get("test_date", ""),
                "report_id": r.get("report_id", ""),
                "fail_rate": fails / total,
                "failures": fails,
                "total": total,
                "verdict": r.get("overall_verdict", "")
            })

    if len(report_summary) < 2:
        st.info("Need at least 2 reports for trend analysis.")
        return

    df_trend = pd.DataFrame(report_summary)
    df_trend["date"] = pd.to_datetime(df_trend["date"], errors="coerce")
    df_trend = df_trend.sort_values("date")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_trend["date"], y=df_trend["fail_rate"],
                             mode="lines+markers", name="Fail Rate",
                             line=dict(color="#e74c3c", width=2),
                             marker=dict(size=8)))
    # Rolling average if enough data
    if len(df_trend) >= 5:
        df_trend["rolling_avg"] = df_trend["fail_rate"].rolling(window=3, min_periods=1).mean()
        fig.add_trace(go.Scatter(x=df_trend["date"], y=df_trend["rolling_avg"],
                                 mode="lines", name="3-Report Moving Avg",
                                 line=dict(color="#f39c12", width=2, dash="dash")))
    fig.update_layout(title="Failure Rate Trend", xaxis_title="Test Date",
                      yaxis_title="Failure Rate", template="plotly_dark", height=350,
                      yaxis=dict(range=[0, max(df_trend["fail_rate"].max() * 1.2, 0.1)]))
    st.plotly_chart(fig, use_container_width=True)

    # Verdict distribution
    verdict_counts = df_trend["verdict"].value_counts()
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Total Reports", len(df_trend))
        st.metric("Avg Fail Rate", f"{df_trend['fail_rate'].mean():.1%}")
    with c2:
        st.metric("PASS", verdict_counts.get("PASS", 0))
        st.metric("FAIL", sum(v for k, v in verdict_counts.items() if "FAIL" in str(k)))


def _dfmea_rpn_analysis(reports):
    """Aggregate DFMEA RPN analysis across all reports."""
    st.markdown("##### ⚠️ Risk Priority Number (RPN) Analysis")

    all_dfmea = []
    for r in reports:
        for entry in r.get("dfmea_entries", []):
            all_dfmea.append(entry)

    if not all_dfmea:
        st.info("No failure analysis entries yet. Generate reports with failure data.")
        return

    df = pd.DataFrame(all_dfmea)

    # Aggregate by subsystem — average RPN and count
    agg = df.groupby("subsystem").agg(
        avg_rpn=("rpn", "mean"),
        max_rpn=("rpn", "max"),
        occurrences=("rpn", "count"),
        avg_severity=("severity", "mean")
    ).sort_values("avg_rpn", ascending=False).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Bar(x=agg["subsystem"], y=agg["avg_rpn"], name="Avg RPN",
                         marker_color="#e74c3c", opacity=0.8))
    fig.add_trace(go.Bar(x=agg["subsystem"], y=agg["max_rpn"], name="Max RPN",
                         marker_color="#e67e22", opacity=0.5))
    fig.update_layout(title="RPN by Subsystem", xaxis_title="Subsystem",
                      yaxis_title="RPN", template="plotly_dark", height=400, barmode="overlay")
    st.plotly_chart(fig, use_container_width=True)

    # RPN table
    st.markdown("**Subsystem Risk Ranking:**")
    for _, row in agg.iterrows():
        risk = "🔴 HIGH" if row["avg_rpn"] >= 80 else "🟠 MEDIUM" if row["avg_rpn"] >= 40 else "🟢 LOW"
        st.markdown(f"- {risk} **{row['subsystem']}**: Avg RPN={row['avg_rpn']:.0f}, "
                    f"Max RPN={row['max_rpn']:.0f}, Occurrences={row['occurrences']}, "
                    f"Avg Severity={row['avg_severity']:.1f}")


def _vi_analysis(reports):
    """Visual inspection findings analysis."""
    st.markdown("##### 👁️ Visual Inspection Findings Distribution")

    vi_data = []
    for r in reports:
        vi = r.get("visual_inspection", {})
        for finding in vi.get("findings", []):
            if finding != "No Damage":
                vi_data.append({"finding": finding, "verdict": r.get("overall_verdict", ""),
                                "dut_id": r.get("dut_id", "")})

    if not vi_data:
        st.info("No visual inspection findings (other than 'No Damage') recorded yet.")
        return

    df_vi = pd.DataFrame(vi_data)
    counts = df_vi["finding"].value_counts().reset_index()
    counts.columns = ["Finding", "Count"]

    fig = px.pie(counts, values="Count", names="Finding", title="VI Findings Distribution",
                 color_discrete_sequence=px.colors.qualitative.Set2)
    fig.update_layout(template="plotly_dark", height=350)
    st.plotly_chart(fig, use_container_width=True)

    # Correlation: VI finding vs verdict
    if len(df_vi) > 1:
        cross = pd.crosstab(df_vi["finding"], df_vi["verdict"].apply(lambda x: "FAIL" if "FAIL" in str(x) else "PASS"))
        st.markdown("**VI Finding vs Verdict:**")
        st.dataframe(cross, use_container_width=True)


def render_analytics_ui():
    """Main entry point for the analytics dashboard."""
    st.markdown('<div style="text-align:center;font-size:1.6em;font-weight:700;color:#e0e0e0;margin-bottom:4px;">'
                '📊 Failure Analysis Statistical Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div style="text-align:center;color:#888;margin-bottom:16px;">'
                'Weibull, Pareto, Correlation, Trend & RPN analysis from accumulated debug reports</div>',
                unsafe_allow_html=True)

    reports = _load_all_reports()
    if not reports:
        st.warning("No debug reports found. Use the PCB Debugger to generate FA reports first.")
        st.info("Reports are stored in the program's `debug_reports/` folder as JSON files when you click "
                "'Generate Full FA Report' in the debugger.")
        return

    df = _reports_to_dataframe(reports)
    if df.empty:
        st.warning("Reports found but no test point data could be extracted.")
        return

    # Summary metrics
    n_reports = len(reports)
    n_fails = len(df[df["status"] == "fail"])
    n_total = len(df[df["status"] != "skip"])
    fail_rate = n_fails / n_total if n_total > 0 else 0
    n_pass = sum(1 for r in reports if r.get("overall_verdict") == "PASS")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Reports", n_reports)
    c2.metric("Total Measurements", n_total)
    c3.metric("Total Failures", n_fails)
    c4.metric("Overall Fail Rate", f"{fail_rate:.1%}")
    c5.metric("Pass Rate", f"{n_pass}/{n_reports}")

    st.markdown("---")

    # Analysis selector
    analyses = ["All Analyses", "Weibull Distribution", "Pareto (80/20)",
                "Correlation Heatmap", "Phase Distribution", "Trend Over Time",
                "RPN Analysis", "Visual Inspection"]
    selected = st.multiselect("Select Analyses to Display", analyses, default=["All Analyses"])

    show_all = "All Analyses" in selected

    if show_all or "Pareto (80/20)" in selected:
        st.markdown("---")
        _pareto_analysis(df)

    if show_all or "Weibull Distribution" in selected:
        st.markdown("---")
        _weibull_analysis(df)

    if show_all or "Correlation Heatmap" in selected:
        st.markdown("---")
        _correlation_heatmap(df)

    if show_all or "Phase Distribution" in selected:
        st.markdown("---")
        _phase_failure_distribution(df)

    if show_all or "Trend Over Time" in selected:
        st.markdown("---")
        _trend_analysis(df, reports)

    if show_all or "RPN Analysis" in selected:
        st.markdown("---")
        _dfmea_rpn_analysis(reports)

    if show_all or "Visual Inspection" in selected:
        st.markdown("---")
        _vi_analysis(reports)

    # Export all data
    st.markdown("---")
    st.markdown("##### 📥 Export")
    c1, c2 = st.columns(2)
    prog_slug = (get_selected_program() or "debug").lower().replace(" ", "_")
    with c1:
        st.download_button("Download All Report Data (CSV)", data=df.to_csv(index=False),
                           file_name=f"{prog_slug}_all_debug_data.csv", mime="text/csv", use_container_width=True)
    with c2:
        all_json = json.dumps(reports, indent=2)
        st.download_button("Download All Reports (JSON)", data=all_json,
                           file_name=f"{prog_slug}_all_reports.json", mime="application/json", use_container_width=True)
