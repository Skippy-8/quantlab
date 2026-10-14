from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ui import BAD, GOOD, datasets, fig_layout, fmt, page, pill

from quantlab.engine import EngineConfig, LookaheadError, evaluate
from quantlab.research import splits
from quantlab.research.registry import Registry, fingerprint
from quantlab.stats.inference import concentration_check, split_halves
from quantlab.strategies import REGISTRY

page("Backtest Lab", "🧪", "Every strategy runs through the same execution model. Integrity checks run before "
     "any P&L is computed, and every run is counted in its study.")

lake, names = datasets()
if not names:
    st.warning("No data yet: run `quantlab fetch synthetic` (or fetch Binance / Yahoo data).")
    st.stop()

with st.sidebar:
    st.header("Data")
    ds = st.selectbox("Dataset", names)
    src, dset = ds.split("/", 1)
    syms = lake.symbols(src, dset)
    pick = st.multiselect("Symbols", syms, default=syms[: min(6, len(syms))])
    st.header("Strategy")
    sname = st.selectbox("Strategy", sorted(REGISTRY), format_func=lambda k: REGISTRY[k].description)
    spec = REGISTRY[sname]
    params = {}
    for k, v in spec.defaults.items():
        if isinstance(v, bool):
            params[k] = st.checkbox(k, value=v)
        elif isinstance(v, int):
            params[k] = st.number_input(k, value=v, step=1)
        else:
            params[k] = st.number_input(k, value=float(v), step=0.1, format="%.2f")
    st.header("Execution")
    maker = st.number_input("Maker fee (bp)", value=2.0, step=0.5)
    taker = st.number_input("Taker fee (bp)", value=5.0, step=0.5)
    spread = st.number_input("Assumed half-spread if no quotes (bp)", value=2.0, step=0.5)
    dpy = st.radio("Calendar", [365, 252], format_func=lambda d: "Crypto (365 d)" if d == 365 else "Equities (252 d)")
    st.header("Research")
    study = st.text_input("Study (trial counter)", value="default")
    record = st.checkbox("Record this run in the registry", value=True)
    run = st.button("Run backtest", type="primary", width="stretch")

if not run:
    st.info("Pick data and a strategy in the sidebar, then **Run backtest**.")
    st.stop()

df = lake.read(src, dset, pick)
cfg = EngineConfig(maker_fee_bp=maker, taker_fee_bp=taker, assumed_half_spread_bp=spread, days_per_year=dpy)
with st.spinner("Checking for lookahead, then simulating fills..."):
    try:
        res = evaluate(spec.make(**params), df, cfg)
    except LookaheadError as exc:
        st.error(f"**Rejected: the strategy reads the future.** {exc}")
        st.stop()

s, reg = res.summary, Registry()
if record:
    reg.record(study, sname, params, s, fingerprint(df))
v = reg.verdict(study, s)

st.markdown(pill("PASS", "pass") if v.passed else pill("FAIL", "fail"), unsafe_allow_html=True)
st.caption(f"Study **{study}**: K = {v.k} distinct trials, so the bar is |t| ≥ {v.bar:.2f}. "
           + ("Clears every check." if v.passed else "Not yet: " + "; ".join(v.reasons) + "."))
if s.get("quotes", {}).get("note"):
    st.warning(f"Quotes: {s['quotes']['note']}.")

k = st.columns(6)
k[0].metric("Trades", s["trades"])
k[1].metric("Net / trade", fmt(s.get("mean_net_bp_per_trade"), 1, " bp"))
k[2].metric("Win rate", fmt((s.get("win_rate") or 0) * 100, 1, "%"))
k[3].metric("Day t", fmt(s.get("day_t")))
k[4].metric("Sharpe (calendar)", fmt(s.get("calendar_sharpe")))
k[5].metric("Deflated Sharpe", fmt(v.dsr, 3))

if res.trades.empty:
    st.stop()

eq = res.daily.cumsum()
dd = eq - eq.cummax()
fig = go.Figure()
fig.add_scatter(x=eq.index, y=eq.values, name="Cumulative net (bp)", line=dict(color=GOOD, width=2))
fig.add_scatter(x=dd.index, y=dd.values, name="Drawdown (bp)", fill="tozeroy", line=dict(color=BAD, width=1),
                opacity=0.5)
st.plotly_chart(fig_layout(fig, 380, "Equity and drawdown, net of fees and funding"), width="stretch")

c1, c2 = st.columns(2)
h = go.Figure(go.Histogram(x=res.trades["net_bp"], nbinsx=60, marker_color="#2F6FDE"))
c1.plotly_chart(fig_layout(h, 300, "Net P&L per trade (bp)"), width="stretch")
halves = split_halves(res.daily)
conc = concentration_check(res.trades["symbol"], res.trades["net_bp"])
with c2:
    st.markdown("**Robustness**")
    st.markdown(f"- First half {fmt(halves['half1_mean'])} bp/day, second half {fmt(halves['half2_mean'])} bp/day "
                f"→ {'same sign' if halves['same_sign'] else '**sign flips (a regime, not an edge)**'}")
    st.markdown(f"- Symbol-clustered bootstrap: P(mean > 0) = {fmt(conc.get('p_mean_positive'), 3)}; "
                f"median trade {fmt(conc.get('median'), 1)} bp; mean without the 5 best symbols "
                f"{fmt(conc.get('mean_ex_top5'), 1)} bp → {'robust' if conc.get('ok') else '**concentrated or weak**'}")
    st.markdown(f"- Entry fill rate {fmt((s.get('entry_fill_rate') or 0) * 100, 1, '%')}; "
                f"exits {s.get('exits')}; time in market {fmt(s.get('time_in_market', 0) * 100, 1, '%')}")
    st.markdown(f"- Integrity checks: **{s.get('integrity_checks')}** (no lookahead, no cross-symbol leak)")

st.subheader("Standard splits")
tabs = splits.report(res.trades)
for tab, t in zip(st.tabs([n.replace("_", " ") for n in tabs]), tabs.values(), strict=True):
    tab.dataframe(t.round(2), width="stretch")

with st.expander("Trades"):
    st.dataframe(res.trades, width="stretch", hide_index=True)
    st.download_button("Download trades (CSV)", res.trades.to_csv(index=False), f"{sname}_trades.csv")
with st.expander("Full summary"):
    st.json({k: v for k, v in s.items() if not isinstance(v, pd.DataFrame)})
