from __future__ import annotations

import streamlit as st
from ui import (
    chart,
    costs_form,
    data_picker,
    empty,
    exits_form,
    fmt,
    header,
    is_dark,
    kpis,
    sizing_form,
    strategy_picker,
)

from quantlab.engine import LookaheadError, evaluate
from quantlab.portfolio import simulate
from quantlab.report import charts as C
from quantlab.report import metrics as M
from quantlab.report.tearsheet import Tearsheet
from quantlab.research import runs, splits
from quantlab.research.registry import Registry, fingerprint
from quantlab.stats.inference import concentration_check, split_halves

header("Build", "Backtest Lab",
       "One execution model for every strategy: limit orders that must trade through, expiry with a taker "
       "fallback, fees, funding and borrow. Integrity checks run before any result is shown.")

with st.sidebar:
    st.markdown("### Data")
    df, data_label = data_picker("bt")
    st.markdown("### Strategy")
    label, fn, params, rule_exits, spec_id = strategy_picker("bt")
    exits = exits_form("bt", rule_exits)
    cfg = costs_form("bt", exits)
    sizing = sizing_form("bt")
    st.markdown("### Research")
    study = st.text_input("Study", value="default", help="Every run is counted in its study's trial total (K)")
    run = st.button("Run backtest", type="primary", width="stretch", icon=":material/play_arrow:")

if run and df is not None:
    box = st.empty()
    with box.status("Running", expanded=False) as status:
        status.update(label="Checking for lookahead and cross-symbol leaks")
        try:
            res = evaluate(fn, df, cfg)
        except LookaheadError as exc:
            status.update(label="Rejected", state="error")
            st.error(f"**Rejected: the strategy reads the future.** {exc}", icon=":material/block:")
            st.stop()
        except Exception as exc:
            status.update(label="Failed", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
            st.stop()
        status.update(label="Sizing the portfolio")
        pf = simulate(res, sizing)
        reg = Registry()
        reg.record(study, spec_id, params, res.summary, fingerprint(df))
        st.session_state["bt"] = {"res": res, "pf": pf, "label": label, "params": params, "spec": spec_id,
                                  "study": study, "data": data_label, "verdict": reg.verdict(study, res.summary)}
        status.update(label="Done", state="complete")
    box.empty()

if "bt" not in st.session_state:
    empty("Choose data and a strategy in the sidebar, then **Run backtest**." if df is not None else
          "Load data first (sidebar), or open the **Data Manager**.")
    st.stop()

S = st.session_state["bt"]
res, pf, v = S["res"], S["pf"], S["verdict"]
s, dark = res.summary, is_dark()
r = pf.daily_returns
m = M.summary(r, cfg.days_per_year) if len(r) > 1 else {}
t = M.trade_stats(res.positions)

top = st.columns([5, 2])
with top[0]:
    st.markdown(f"#### {S['label']}")
    st.caption(f"{S['data']} · study **{S['study']}**")
with top[1]:
    st.badge("Passes the study bar" if v.passed else "Does not pass", icon=":material/verified:" if v.passed
             else ":material/cancel:", color="green" if v.passed else "red")
    st.caption(f"K = {v.k} trials → bar |t| ≥ {v.bar:.2f}. " + ("" if v.passed else "; ".join(v.reasons)))

kpis([("Total return", fmt(m.get("total_return"), "pct", 3), "Compounded, net of all modelled costs"),
      ("CAGR", fmt(m.get("cagr"), "pct", 3), None),
      ("Sharpe", fmt(m.get("sharpe")), "Annualised over every calendar day"),
      ("Max drawdown", fmt(m.get("max_drawdown"), "pct", 3), None),
      ("Trades", fmt(t.get("trades"), "int"), None),
      ("Day t", fmt(s.get("day_t")), "t-statistic of the daily P&L series; compare with the study bar"),
      ("DSR", fmt(v.dsr, digits=3), "Deflated Sharpe ratio: the probability the Sharpe is real after counting every trial in the study")])
if s.get("quotes", {}).get("note"):
    st.caption(f":material/info: Quotes: {s['quotes']['note']}.")

tabs = st.tabs(["Performance", "Trades", "Risk & robustness", "Splits", "Export"])
with tabs[0]:
    chart(C.equity(pf.equity, dark=dark), "eq")
    a, b = st.columns(2)
    with a:
        chart(C.underwater(r, dark=dark), "dd")
    with b:
        chart(C.rolling_sharpe(r, 60, cfg.days_per_year, dark=dark), "rs")
    if len(r) > 31:
        chart(C.monthly_heatmap(r, dark=dark), "mh")
with tabs[1]:
    chart(C.trade_map(res.positions, dark=dark), "tm")
    a, b, c, d = st.columns(4)
    a.metric("Win rate", fmt(t.get("win_rate"), "pct0"), border=True)
    b.metric("Expectancy", fmt(t.get("expectancy_bp"), "bp"), border=True)
    c.metric("Payoff ratio", fmt(t.get("payoff_ratio")), border=True)
    d.metric("Profit factor", fmt(t.get("profit_factor")), border=True)
    st.dataframe(res.positions, hide_index=True, width="stretch", height=320)
with tabs[2]:
    halves = split_halves(res.daily)
    conc = concentration_check(res.positions["symbol"], res.positions["net_bp"]) if len(res.positions) > 2 else {}
    a, b = st.columns(2)
    with a.container(border=True):
        st.markdown("**Stability**")
        st.markdown(f"First half **{fmt(halves['half1_mean'], 'bp')}/day**, second half "
                    f"**{fmt(halves['half2_mean'], 'bp')}/day**: "
                    + ("same sign." if halves["same_sign"] else ":red[the sign flips: a regime, not an edge.]"))
        st.markdown(f"Symbol-clustered bootstrap: P(mean > 0) = **{fmt(conc.get('p_mean_positive'), digits=3)}**; "
                    f"median trade **{fmt(conc.get('median'), 'bp')}**; mean without the top 5 symbols "
                    f"**{fmt(conc.get('mean_ex_top5'), 'bp')}** → "
                    + ("robust across symbols." if conc.get("ok") else ":red[concentrated or weak.]"))
        st.markdown(f"Entry fill rate **{fmt(s.get('entry_fill_rate'), 'pct0')}**, time in market "
                    f"**{fmt(s.get('time_in_market'), 'pct0')}**, exits {s.get('exits')}.")
    with b.container(border=True):
        st.markdown("**Risk**")
        st.dataframe({"Metric": ["Volatility", "Sortino", "Calmar", "Daily VaR 95%", "Daily CVaR 95%", "Skew",
                                 "Kurtosis", "Longest drawdown (days)"],
                      "Value": [fmt(m.get("volatility"), "pct0"), fmt(m.get("sortino")), fmt(m.get("calmar")),
                                fmt(m.get("var_95"), "pct", 3), fmt(m.get("cvar_95"), "pct", 3), fmt(m.get("skew")),
                                fmt(m.get("kurtosis")), fmt(m.get("longest_drawdown_days"), "int")]},
                     hide_index=True, width="stretch")
    chart(C.distribution(r, dark=dark), "dist")
    sk = pf.stats["positions_skipped"]
    if any(sk.values()):
        st.caption(f"Positions skipped by the sizing limits: {sk}")
with tabs[3]:
    rep = splits.report(res.positions)
    for tab, tbl in zip(st.tabs([n.replace("_", " ").title() for n in rep]), rep.values(), strict=True):
        tab.dataframe(tbl.round(2), width="stretch")
with tabs[4]:
    ts = Tearsheet.from_results(res, pf, S["label"], verdict={"passed": v.passed,
                                                               "text": f"K = {v.k}, bar {v.bar:.2f}, day t {s.get('day_t')}"})
    st.download_button("Download HTML tearsheet", ts.to_html(), file_name="tearsheet.html", mime="text/html",
                       type="primary", icon=":material/description:")
    st.download_button("Download trades (CSV)", res.trades.to_csv(index=False), file_name="trades.csv",
                       icon=":material/table:")
    name = st.text_input("Save as run", value=S["label"])
    if st.button("Save run", icon=":material/bookmark_add:"):
        rid = runs.save(name, S["spec"], S["params"], res, pf, data_fp=fingerprint(res.frame), study=S["study"])
        st.success(f"Saved as `{rid}`. Compare it in **Compare Runs**.")
