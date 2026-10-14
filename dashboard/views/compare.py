from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from ui import chart, empty, header, is_dark, pal

from quantlab.report import metrics as M
from quantlab.report.charts import style
from quantlab.research import runs

header("Validate", "Compare Runs",
       "Saved runs carry their full configuration, data fingerprint and code version, so any two can be compared "
       "like for like, or reproduced later.")

saved = runs.list_runs()
if saved.empty:
    empty("No saved runs yet. Use **Save run** on the Export tab of the Backtest Lab.")
    st.stop()

names = saved.set_index("id")["name"]
pick = st.multiselect("Runs", list(saved["id"]), default=list(saved["id"][:4]), format_func=lambda i: f"{names[i]}  ({i})")
if not pick:
    st.stop()
table = runs.compare(pick).drop(columns=["id"])
st.dataframe(table, width="stretch", column_config={
    "trades": st.column_config.NumberColumn("Trades", format="%d"),
    "total_return": st.column_config.NumberColumn("Total return", format="percent"),
    "cagr": st.column_config.NumberColumn("CAGR", format="percent"),
    "max_drawdown": st.column_config.NumberColumn("Max DD", format="percent"),
    "volatility": st.column_config.NumberColumn("Vol", format="percent"),
    "win_rate": st.column_config.NumberColumn("Win rate", format="percent"),
    **{c: st.column_config.NumberColumn(lbl, format="%.2f") for c, lbl in
       (("sharpe", "Sharpe"), ("sortino", "Sortino"), ("calmar", "Calmar"), ("day_t", "Day t"),
        ("expectancy_bp", "Expectancy (bp)"))}})
p, dark = pal(), is_dark()
fig, dd = go.Figure(), go.Figure()
for i, rid in enumerate(pick):
    d = runs.load(rid)
    if "daily_returns" not in d:
        continue
    eq = M.equity_curve(d["daily_returns"])
    color = p["series"][i % len(p["series"])]
    fig.add_scatter(x=eq.index, y=eq.values, name=names[rid], line=dict(color=color, width=2))
    dw = M.drawdown(d["daily_returns"])
    dd.add_scatter(x=dw.index, y=dw.values, name=names[rid], line=dict(color=color, width=1.3))
chart(style(fig, 360, "Growth of $1", dark), "cmp_eq")
dd.update_yaxes(tickformat=".0%")
chart(style(dd, 260, "Drawdowns", dark), "cmp_dd")
with st.expander("Manifests"):
    for rid in pick:
        st.json(runs.load(rid)["manifest"], expanded=False)
if st.button("Delete selected runs", icon=":material/delete:"):
    for rid in pick:
        runs.delete(rid)
    st.rerun()
