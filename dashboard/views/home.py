from __future__ import annotations

import streamlit as st
from ui import empty, ensure_demo_data, fmt, header, kpis, pal

from quantlab import monitor
from quantlab.data.lake import Lake
from quantlab.research import runs
from quantlab.research.registry import Registry

header("Overview", "Backtests you can defend",
       "quantlab runs every strategy through one execution model, rejects any that peek at the future, "
       "counts every variant you try, and keeps a sealed out-of-sample set you can open only once per idea.")

lake, reg = Lake(), Registry()
studies = reg.studies()
saved = runs.list_runs()
hb = monitor.heartbeats()
kpis([("Datasets", fmt(len(lake.datasets()), "int"), "Parquet datasets in the lake"),
      ("Studies", fmt(len(studies), "int"), "Research questions with their own trial count"),
      ("Trials counted", fmt(sum(reg.k(s) for s in studies), "int"), "Distinct strategy/parameter/data combinations"),
      ("Saved runs", fmt(len(saved), "int"), "Reproducible runs you can compare"),
      ("Jobs logged", fmt(int((hb["status"] == "ok").sum()) if len(hb) else 0, "int"), "Successful scheduled-job runs")])

if not lake.datasets():
    st.space("small")
    c1, c2 = st.columns([3, 2])
    c1.markdown("#### Start in one click")
    c1.markdown("Load four synthetic markets (random walks with a quoted spread and funding) to try every page "
                "without downloading anything. Real data comes from the **Data Manager**.")
    if c1.button("Load demo data", type="primary", icon=":material/rocket_launch:"):
        ensure_demo_data()
        st.rerun()

st.space("small")
st.markdown("#### What each step guards against")
p = pal()
steps = [
    (":material/tune:", "Strategy Builder", "Write rules as sentences: `rsi(14) < 30 and close > sma(200)`. "
     "Parsed safely; never executed as code."),
    (":material/science:", "Backtest Lab", "Fills must trade through the limit. Lookahead and cross-symbol leaks are "
     "rejected before any P&L is shown."),
    (":material/grid_on:", "Parameter Search", "Every cell is counted. The best cell is compared with the best cell "
     "of the same search on shuffled signals."),
    (":material/fast_forward:", "Walk-Forward", "Re-optimise on the past, trade the next unseen window, stitch only "
     "the unseen windows together."),
    (":material/shield:", "Robustness", "Monte Carlo drawdown ranges, PBO, and White's Reality Check for the whole "
     "set of strategies you tried."),
    (":material/fact_check:", "Research Registry", "The pass bar rises with the number of trials: "
     "|t| ≥ max(2, √(2 ln K)), plus a deflated Sharpe that counts them."),
]
cols = st.columns(3)
for i, (icon, title, text) in enumerate(steps):
    with cols[i % 3].container(border=True, height="stretch"):
        st.markdown(f"**{icon} {title}**")
        st.caption(text)

if studies:
    st.space("small")
    st.markdown("#### Studies")
    rows = []
    for s in studies:
        t = reg.trials(s)
        best = t["day_t"].max() if len(t) else None
        rows.append({"Study": s, "K": reg.k(s), "Bar |t|": round(reg.bar(s), 2), "Best day t": best,
                     "Clears bar": bool(best is not None and best >= reg.bar(s)), "Pre-registered": bool(reg.prereg_for(s))})
    st.dataframe(rows, hide_index=True, width="stretch",
                 column_config={"Best day t": st.column_config.NumberColumn(format="%.2f"),
                                "Clears bar": st.column_config.CheckboxColumn(),
                                "Pre-registered": st.column_config.CheckboxColumn()})
elif lake.datasets():
    empty("No studies yet. Run a backtest in the **Backtest Lab**; it is counted in its study automatically.")
_ = p
