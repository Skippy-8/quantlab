from __future__ import annotations

import itertools

import plotly.graph_objects as go
import streamlit as st
from ui import chart, data_picker, empty, fmt, header, is_dark, kpis, pal

from quantlab import validation
from quantlab.report.charts import style
from quantlab.strategies import REGISTRY

header("Validate", "Walk-Forward",
       "Choose parameters on the past only, trade them on the next window nobody optimised on, and roll forward. "
       "The stitched unseen windows are the closest a backtest gets to live trading.")

with st.sidebar:
    df, lbl = data_picker("wf")
    sname = st.selectbox("Template", sorted(REGISTRY), format_func=lambda k: REGISTRY[k].description)
    spec = REGISTRY[sname]
    grid = {}
    for k, vals in spec.grid.items():
        txt = st.text_input(k, ", ".join(str(v) for v in vals), key=f"wf_{sname}_{k}")
        grid[k] = [type(vals[0])(x.strip()) for x in txt.split(",") if x.strip()]
    train = st.number_input("Training window (days)", value=60, step=10)
    test = st.number_input("Trading window (days)", value=20, step=5)
    anchored = st.toggle("Anchored (expanding) training window")
    objective = st.selectbox("Choose by", ["calendar_sharpe", "day_t", "sum_bp"])
    go_ = st.button("Run walk-forward", type="primary", width="stretch", icon=":material/play_arrow:")

if not go_ or df is None:
    empty("Set the windows in the sidebar and **Run walk-forward**." if df is not None else "Load data first.")
    st.stop()

combos = [dict(spec.defaults, **dict(zip(grid, v, strict=True))) for v in itertools.product(*grid.values())]
bar = st.progress(0.0, "Folds")
wf = validation.walk_forward(spec.make, combos, df, int(train), int(test), objective=objective, anchored=anchored,
                             progress=lambda i, n: bar.progress(i / n, f"fold {i}/{n}"))
bar.empty()
if not wf.stats["folds"]:
    st.warning("Not enough data for one training plus one trading window.")
    st.stop()
st_ = wf.stats
kpis([("Folds", fmt(st_["folds"], "int"), None), ("Out-of-sample Sharpe", fmt(st_["oos_sharpe"]), None),
      ("Out-of-sample day t", fmt(st_["oos_day_t"]), None),
      ("Profitable folds", fmt(st_["positive_folds"], "pct0"), None),
      ("Distinct choices", fmt(st_["distinct_choices"], "int"), "Parameter sets chosen across folds: many = unstable")])
p, dark = pal(), is_dark()
eq = wf.oos_daily.cumsum()
fig = go.Figure(go.Scatter(x=eq.index, y=eq.values, line=dict(color=p["accent"], width=2), name="OOS cumulative bp"))
for t in wf.folds["test_start"]:
    fig.add_vline(x=str(t), line=dict(color=p["line"], width=1))
chart(style(fig, 340, "Stitched out-of-sample P&L (bp per unit); lines mark each new fold", dark), "wf")
folds = wf.folds.copy()
folds["chosen"] = folds["chosen"].map(lambda d: ", ".join(f"{k}={d[k]}" for k in grid))
st.dataframe(folds, hide_index=True, width="stretch", column_config={
    "fold": "Fold", "train_start": "Train from", "test_start": "Trade from", "test_end": "Trade to",
    "chosen": "Chosen on the past", f"is_{objective}": st.column_config.NumberColumn("In-sample score", format="%.2f"),
    "oos_sum_bp": st.column_config.NumberColumn("Out-of-sample bp", format="%.0f"),
    "oos_trades": st.column_config.NumberColumn("Trades", format="%d")})
