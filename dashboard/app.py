"""quantlab dashboard: home.

    streamlit run dashboard/app.py
"""
from __future__ import annotations

import streamlit as st
from ui import fmt, page

from quantlab import monitor
from quantlab.research.registry import Registry

page("quantlab", "🧪", "A research platform for honest backtests: every trial is counted, every result is "
     "checked for lookahead, and the out-of-sample set can only be opened once per hypothesis.")

from ui import datasets  # noqa: E402

lake, names = datasets()
reg = Registry()
studies = reg.studies()
hb = monitor.heartbeats()

c = st.columns(4)
c[0].metric("Datasets in the lake", len(names))
c[1].metric("Studies", len(studies))
c[2].metric("Trials recorded", sum(reg.k(s) for s in studies))
c[3].metric("Job runs logged", int((hb["status"] == "ok").sum()) if len(hb) else 0)

if not names:
    st.info("The lake is empty. Load demo data with `quantlab fetch synthetic`, or public market data with "
            "`quantlab fetch binance BTCUSDT ETHUSDT --start 2024-01 --end 2024-06 --funding`.")

st.subheader("Workflow")
st.markdown("""
| Step | Page | What it enforces |
|---|---|---|
| 1. Load data | **Data & Monitoring** | Parquet lake, DuckDB catalog, freshness checks |
| 2. Test an idea | **Backtest Lab** | One execution model for every strategy; lookahead and symbol-leak checks run first |
| 3. Search parameters | **Parameter Search** | Every cell is recorded; a whole-search permutation null says whether the best cell beats luck |
| 4. Judge it | **Research Registry** | The pass bar rises with the number of trials (K); deflated Sharpe uses every trial in the study |
| 5. Confirm it | `quantlab vault` | A sealed out-of-sample set, opened once per pre-registered spec |
| Data side-lane | **Insider Explorer** | Point-in-time SEC Form 3/4/5 transactions |
""")

if studies:
    st.subheader("Studies")
    rows = []
    for s in studies:
        t = reg.trials(s)
        best = t["day_t"].max() if len(t) else None
        rows.append({"study": s, "K (distinct trials)": reg.k(s), "pass bar |t|": round(reg.bar(s), 2),
                     "best day t": fmt(best), "best clears the bar": bool(best is not None and best >= reg.bar(s)),
                     "pre-registered": bool(reg.prereg_for(s))})
    st.dataframe(rows, width="stretch", hide_index=True)
