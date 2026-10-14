from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ui import chart, empty, fmt, header, is_dark, kpis, pal

from quantlab import validation
from quantlab.report.charts import style
from quantlab.research import runs

header("Validate", "Robustness",
       "History is one path. Monte Carlo resampling shows the range of drawdowns and outcomes the same trades "
       "could have produced; the Reality Check asks whether the best of everything you tried beats zero once the "
       "search itself is accounted for.")

saved = runs.list_runs()
if saved.empty and "bt" not in st.session_state:
    empty("Run a backtest in the **Backtest Lab** (and optionally save runs) first.")
    st.stop()

tab_mc, tab_rc = st.tabs(["Monte Carlo", "Reality Check across runs"])
with tab_mc:
    sources = (["Current backtest"] if "bt" in st.session_state else []) + list(saved["id"] + " · " + saved["name"])
    src = st.selectbox("Run", sources)
    if src == "Current backtest":
        r = st.session_state["bt"]["pf"].daily_returns
        trades = st.session_state["bt"]["res"].positions
    else:
        d = runs.load(src.split(" · ")[0])
        r, trades = d.get("daily_returns", pd.Series(dtype=float)), d["positions"]
    a, b, c = st.columns(3)
    method = a.segmented_control("Resample", ["block", "shuffle"], default="block",
                                 format_func=lambda m: "Blocks of days" if m == "block" else "Shuffle trades")
    n = b.select_slider("Paths", [500, 1000, 2000, 5000], value=2000)
    block = c.number_input("Block length (days)", value=10, min_value=2)
    series = (trades["net_bp"] / 1e4 * 0.1) if method == "shuffle" else r
    mc = validation.monte_carlo(series, n=n, method=method or "block", block=int(block))
    if not mc:
        empty("Not enough observations.")
        st.stop()
    kpis([("Actual max drawdown", fmt(mc["actual_max_dd"], "pct", 3), None),
          ("Median path max DD", fmt(mc["max_dd_p50"], "pct", 3), None),
          ("1-in-20 max DD", fmt(mc["max_dd_p95"], "pct", 3), "5th percentile of resampled max drawdowns"),
          ("1-in-100 max DD", fmt(mc["max_dd_p99"], "pct", 3), None),
          ("Chance of a loss", fmt(mc["prob_loss"], "pct0"), None)])
    p, dark = pal(), is_dark()
    x, y = st.columns(2)
    with x:
        fig = go.Figure(go.Histogram(x=mc["max_dds"], nbinsx=50, marker_color=p["neg"], opacity=0.75))
        fig.add_vline(x=mc["actual_max_dd"], line=dict(color=p["ink"], width=2), annotation_text="actual")
        fig.update_xaxes(tickformat=".0%")
        chart(style(fig, 300, "Max drawdown across resampled paths", dark), "mcdd")
    with y:
        fig = go.Figure(go.Histogram(x=mc["finals"], nbinsx=50, marker_color=p["accent"], opacity=0.75))
        fig.add_vline(x=mc["actual_final"], line=dict(color=p["ink"], width=2), annotation_text="actual")
        fig.update_xaxes(tickformat=".0%")
        chart(style(fig, 300, "Final return across resampled paths", dark), "mcf")
    if method == "shuffle":
        st.caption("Trade shuffling sizes each trade at 10% of equity; it shows order risk, not edge.")

with tab_rc:
    if len(saved) < 2:
        empty("Save at least two runs to test the best of them against the search.")
    else:
        pick = st.multiselect("Runs (the whole set you tried, not just the best)", list(saved["id"]),
                              default=list(saved["id"]), format_func=lambda i: saved.set_index("id").at[i, "name"])
        if len(pick) >= 2 and st.button("Run Reality Check", type="primary"):
            mat = pd.DataFrame({saved.set_index("id").at[i, "name"]: runs.load(i).get("daily_returns")
                                for i in pick}).fillna(0.0)
            out = validation.reality_check(mat, n_boot=1000)
            kpis([("Best run", out["best"], None), ("White's Reality Check p", fmt(out["reality_check_p"], digits=3), None),
                  ("Hansen SPA p", fmt(out["spa_p"], digits=3), "More powerful; drops clearly bad strategies")])
            st.markdown("A p-value below 0.05 means the best run beats zero even after accounting for having "
                        f"tried {out['strategies']}. Above it, the best run is what that many attempts produce by luck.")
