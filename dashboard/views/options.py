from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ui import chart, empty, fmt, header, is_dark, kpis, pal

from quantlab.options import STRUCTURES, backtest, compare_fills, synthetic
from quantlab.options.chain import thetadata_eod
from quantlab.report.charts import style

header("Markets", "Options Lab",
       "Multi-leg structures on real bid/ask chains: legs chosen by delta, moneyness or days to expiry, priced at "
       "mid, a quarter of the spread, or the natural side. Seeing all three is how you learn whether a result "
       "survives execution.")

with st.sidebar:
    st.markdown("### Chain")
    source = st.segmented_control("Source", ["Synthetic", "ThetaData"], default="Synthetic")
    if source == "ThetaData":
        sym = st.text_input("Underlying", "SPY")
        a, b = st.columns(2)
        start = a.date_input("From", pd.Timestamp("2024-01-02"))
        end = b.date_input("To", pd.Timestamp("2024-06-28"))
        st.caption("Needs a running Theta Terminal (free account: EOD quotes from 2023-06).")
    else:
        days = st.slider("Trading days", 60, 500, 250, step=10)
        vol = st.slider("Underlying vol", 0.10, 0.80, 0.25, step=0.05)
        seed = st.number_input("Seed", value=7)
    st.markdown("### Structure")
    sname = st.selectbox("Structure", sorted(STRUCTURES), index=sorted(STRUCTURES).index("iron_condor"),
                         format_func=lambda s: s.replace("_", " ").title())
    every = st.number_input("Enter every N trading days", value=5, min_value=1)
    max_open = st.number_input("Max open structures", value=3, min_value=1)
    st.markdown("### Exits")
    hold = st.number_input("Hold (calendar days, 0 = off)", value=14, min_value=0)
    exit_dte = st.number_input("Exit at DTE (0 = hold to expiry)", value=1, min_value=0)
    tp = st.number_input("Take profit (% of basis, 0 = off)", value=50, min_value=0)
    sl = st.number_input("Stop loss (% of basis, 0 = off)", value=0, min_value=0)
    fill = st.segmented_control("Fills", ["mid", "quarter", "natural"], default="mid")
    fee = st.number_input("Fee per contract ($)", value=0.65, step=0.05)
    go_ = st.button("Run options backtest", type="primary", width="stretch", icon=":material/play_arrow:")

legs = STRUCTURES[sname]
st.markdown("**Legs**  " + "  ·  ".join(
    f"`{'+' if lg.side > 0 else '−'}{lg.qty} {lg.right} "
    + (f"Δ{lg.delta:g}" if lg.delta is not None else f"m{lg.moneyness:+g}" if lg.moneyness is not None
       else f"ATM{lg.atm_offset:+d}") + f" ~{lg.dte}d`" for lg in legs))
if not go_:
    empty("Configure the chain and structure in the sidebar, then **Run options backtest**.")
    st.stop()

box = st.empty()
with box.status("Loading chain", expanded=False) as status:
    try:
        chain = (thetadata_eod(sym, str(start), str(end)) if source == "ThetaData"
                 else synthetic(days=days, vol=vol, seed=int(seed)))
    except Exception as exc:
        status.update(label="Could not load the chain", state="error")
        st.error(f"{type(exc).__name__}: {exc}")
        st.stop()
    dates = sorted(chain["date"].unique())
    entries = dates[::int(every)]
    kw = dict(hold_days=int(hold) or None, exit_dte=int(exit_dte) or None, take_profit=(tp / 100) or None,
              stop_loss=(sl / 100) or None, fee_per_contract=fee, max_open=int(max_open))
    status.update(label="Backtesting")
    res = backtest(chain, legs, entries, fill=fill or "mid", **kw)
    status.update(label="Comparing fill assumptions")
    fills = compare_fills(chain, legs, entries, **kw)
    status.update(label="Done", state="complete")
box.empty()

t = res.trades
if t.empty:
    empty(f"No trades: {res.skipped}")
    st.stop()
kpis([("Trades", fmt(len(t), "int"), None), ("Total P&L", fmt(t["pnl"].sum(), "usd"), "Per 1 structure, ×100 multiplier"),
      ("Avg P&L", fmt(t["pnl"].mean(), "usd"), None), ("Win rate", fmt((t["pnl"] > 0).mean(), "pct0"), None),
      ("Worst trade", fmt(t["pnl"].min(), "usd"), None)])
p, dark = pal(), is_dark()
a, b = st.columns([3, 2])
with a:
    fig = go.Figure(go.Scatter(x=res.daily.index, y=res.daily["equity"], line=dict(color=p["accent"], width=2),
                               fill="tozeroy", name="P&L"))
    fig.update_yaxes(tickprefix="$")
    chart(style(fig, 320, f"Cumulative P&L, {fill} fills (marked daily at mid)", dark), "opt_eq")
with b:
    fig = go.Figure(go.Bar(x=fills.index, y=fills["total_pnl"],
                           marker_color=[p["pos"] if v > 0 else p["neg"] for v in fills["total_pnl"]],
                           text=[fmt(v, "usd") for v in fills["total_pnl"]], textposition="outside", cliponaxis=False))
    fig.update_yaxes(tickprefix="$")
    chart(style(fig, 320, "Same trades, three execution assumptions", dark), "opt_fill")
spot = chain.groupby("date")["underlying"].first()
fig = go.Figure(go.Scatter(x=spot.index, y=spot.values, line=dict(color=p["muted"], width=1.2), name="Underlying"))
fig.add_scatter(x=t["entry_date"], y=t["spot_entry"], mode="markers", name="Entry",
                marker=dict(color=[p["pos"] if v > 0 else p["neg"] for v in t["pnl"]], size=9))
chart(style(fig, 260, "Entries on the underlying (green = winner)", dark), "opt_spot")
st.dataframe(t, hide_index=True, width="stretch", column_config={
    "pnl": st.column_config.NumberColumn("P&L", format="dollar"),
    "return_on_basis": st.column_config.NumberColumn("Return on basis", format="percent")})
st.caption(f"Exit reasons: {t['exit_reason'].value_counts().to_dict()}. Skipped entries: {res.skipped}.")
