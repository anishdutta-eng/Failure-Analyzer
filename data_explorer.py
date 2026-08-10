"""Generic, schema-agnostic CSV data explorer.

Built for the Jupiter program (and reusable by any program) as a starting point
for uploading arbitrary CSV files and getting immediate, auto-generated
visualizations without assuming a specific column layout.

Entry point: render_data_explorer(df, program_name)
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import theme
from theme import PURPLE, GREEN, MAGENTA, TEXT, TEXT_MUTED, CHART_SEQUENCE, CONTINUOUS_SCALE


_NA_TOKENS = {"n/a", "na", "n.a.", "none", "null", "-", "--", "", "tbd", "?"}


def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy where object columns that are *mostly* numeric (after
    dropping n/a-style tokens) are converted to numeric, so files like the
    Jupiter tracker (with 'n/a' in numeric columns) chart correctly."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype != object:
            continue
        s = out[c].astype(str).str.strip()
        cleaned = s.mask(s.str.lower().isin(_NA_TOKENS))
        num = pd.to_numeric(cleaned, errors="coerce")
        non_null = cleaned.notna().sum()
        if non_null > 0 and (num.notna().sum() / non_null) >= 0.8:
            out[c] = num
    return out


def _detect_datetime_columns(df: pd.DataFrame, sample: int = 200) -> list:
    """Return columns that are datetime dtype or whose object values mostly
    parse as dates (>=80% of a sample)."""
    cols = []
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            cols.append(c)
            continue
        if df[c].dtype == object:
            s = df[c].dropna().head(sample)
            if len(s) == 0:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                parsed = pd.to_datetime(s, errors="coerce")
            if parsed.notna().mean() >= 0.8:
                cols.append(c)
    return cols


def _column_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        col = df[c]
        non_null = int(col.notna().sum())
        nulls = int(col.isna().sum())
        example = col.dropna().iloc[0] if non_null else ""
        rows.append({
            "Column": c,
            "Type": str(col.dtype),
            "Non-null": non_null,
            "Nulls": nulls,
            "% Null": f"{(nulls / len(df) * 100):.1f}%" if len(df) else "0%",
            "Unique": int(col.nunique(dropna=True)),
            "Example": str(example)[:40],
        })
    return pd.DataFrame(rows)


def render_data_explorer(df: pd.DataFrame, program_name: str):
    """Render an interactive, schema-agnostic explorer with starter charts."""
    theme.render_app_header(f"{program_name} · Data Explorer")

    if df is None or df.empty:
        st.warning("The uploaded file has no rows to explore.")
        return

    df = _coerce_types(df)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    datetime_cols = _detect_datetime_columns(df)
    categorical_cols = [c for c in df.columns
                        if c not in numeric_cols and c not in datetime_cols
                        and df[c].nunique(dropna=True) <= max(50, int(len(df) * 0.5))]

    # ---- Overview metrics ----
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{len(df):,}")
    c2.metric("Columns", len(df.columns))
    c3.metric("Numeric", len(numeric_cols))
    c4.metric("Categorical", len(categorical_cols))
    total_cells = len(df) * max(len(df.columns), 1)
    miss = df.isna().sum().sum()
    c5.metric("Missing", f"{(miss / total_cells * 100):.1f}%" if total_cells else "0%")

    tab_preview, tab_cols, tab_viz, tab_stats = st.tabs(
        ["👁 Preview", "🧬 Columns", "📊 Visualizations", "📈 Summary Stats"])

    with tab_preview:
        n = st.slider("Rows to preview", 5, min(200, max(5, len(df))),
                      min(25, len(df)), key="de_preview_n")
        st.dataframe(df.head(n), use_container_width=True)

    with tab_cols:
        st.dataframe(_column_summary(df), use_container_width=True, hide_index=True)

    with tab_stats:
        try:
            st.dataframe(df.describe(include="all").T, use_container_width=True)
        except Exception:
            st.dataframe(df.describe().T, use_container_width=True)

    with tab_viz:
        if not numeric_cols and not categorical_cols and not datetime_cols:
            st.info("No chartable columns detected.")
            return

        # 1) Numeric distribution
        if numeric_cols:
            st.markdown("##### Distribution of a numeric column")
            col = st.selectbox("Numeric column", numeric_cols, key="de_hist_col")
            try:
                fig = px.histogram(df, x=col, nbins=40, color_discrete_sequence=[PURPLE])
                fig.update_layout(bargap=0.05)
                st.plotly_chart(theme.style_fig(fig, height=340), use_container_width=True)
            except Exception as e:
                st.caption(f"Could not plot histogram: {e}")

        # 2) Categorical counts
        if categorical_cols:
            st.markdown("##### Counts by category")
            col = st.selectbox("Categorical column", categorical_cols, key="de_cat_col")
            try:
                vc = df[col].value_counts(dropna=False).head(20).reset_index()
                vc.columns = [col, "count"]
                fig = px.bar(vc, x=col, y="count", color="count",
                             color_continuous_scale=CONTINUOUS_SCALE)
                fig.update_layout(xaxis_tickangle=-40, coloraxis_showscale=False)
                st.plotly_chart(theme.style_fig(fig, height=360), use_container_width=True)
            except Exception as e:
                st.caption(f"Could not plot counts: {e}")

        # 3) Time series
        if datetime_cols:
            st.markdown("##### Trend over time")
            dcol = st.selectbox("Date/time column", datetime_cols, key="de_date_col")
            freq_label = st.selectbox("Group by", ["Day", "Week", "Month"], index=1, key="de_freq")
            freq = {"Day": "D", "Week": "W", "Month": "M"}[freq_label]
            ycol = st.selectbox("Value (or record count)", ["(count of records)"] + numeric_cols,
                                key="de_ts_y")
            try:
                tmp = df.copy()
                tmp[dcol] = pd.to_datetime(tmp[dcol], errors="coerce")
                tmp = tmp.dropna(subset=[dcol]).set_index(dcol)
                if ycol == "(count of records)":
                    series = tmp.resample(freq).size().reset_index(name="count")
                    fig = px.area(series, x=dcol, y="count")
                else:
                    series = tmp[ycol].resample(freq).mean().reset_index()
                    fig = px.line(series, x=dcol, y=ycol, markers=True)
                fig.update_traces(line_color=PURPLE)
                st.plotly_chart(theme.style_fig(fig, height=340), use_container_width=True)
            except Exception as e:
                st.caption(f"Could not plot time series: {e}")

        # 4) Correlation heatmap
        if len(numeric_cols) >= 2:
            st.markdown("##### Correlation between numeric columns")
            try:
                corr = df[numeric_cols].corr(numeric_only=True)
                fig = px.imshow(corr, text_auto=".2f", aspect="auto",
                                color_continuous_scale=[[0.0, GREEN], [0.5, "#F4F1FB"], [1.0, MAGENTA]],
                                zmin=-1, zmax=1)
                st.plotly_chart(theme.style_fig(fig, height=420), use_container_width=True)
            except Exception as e:
                st.caption(f"Could not plot correlation: {e}")

        # 5) Scatter (relationship between two numerics)
        if len(numeric_cols) >= 2:
            st.markdown("##### Relationship between two numeric columns")
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                xcol = st.selectbox("X axis", numeric_cols, key="de_sc_x")
            with sc2:
                ycol2 = st.selectbox("Y axis", numeric_cols,
                                     index=min(1, len(numeric_cols) - 1), key="de_sc_y")
            with sc3:
                color_opt = st.selectbox("Color by (optional)", ["(none)"] + categorical_cols,
                                         key="de_sc_color")
            try:
                kwargs = {"color_discrete_sequence": CHART_SEQUENCE}
                if color_opt != "(none)":
                    kwargs["color"] = color_opt
                else:
                    kwargs["color_discrete_sequence"] = [PURPLE]
                fig = px.scatter(df, x=xcol, y=ycol2, **kwargs)
                st.plotly_chart(theme.style_fig(fig, height=420), use_container_width=True)
            except Exception as e:
                st.caption(f"Could not plot scatter: {e}")
