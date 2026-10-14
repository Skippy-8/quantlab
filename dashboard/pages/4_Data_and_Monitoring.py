from __future__ import annotations

import plotly.express as px
import streamlit as st
from ui import datasets, fig_layout, page

from quantlab import monitor

page("Data & Monitoring", "🛰️", "What is in the lake, how fresh it is, and whether the scheduled jobs that feed "
     "it are running. Silence is ambiguous, so every job writes a heartbeat.")

lake, names = datasets()
cat = lake.catalog()
if len(cat):
    st.subheader("Lake catalog")
    st.dataframe(cat, width="stretch", hide_index=True)
    ds = st.selectbox("Bars per day", names)
    src, dset = ds.split("/", 1)
    con = lake.duckdb()
    counts = con.execute(f"SELECT symbol, date_trunc('day', timestamp) AS day, count(*) AS bars "
                         f"FROM {src}__{dset} GROUP BY ALL ORDER BY day").df()
    fig = px.line(counts, x="day", y="bars", color="symbol")
    st.plotly_chart(fig_layout(fig, 300, "Gaps show up as dips (DuckDB over the Parquet lake)"),
                    width="stretch")
    with st.expander("SQL console (read-only views: <source>__<dataset>)"):
        sql = st.text_area("Query", f"SELECT symbol, count(*) AS bars, min(timestamp), max(timestamp)\n"
                                    f"FROM {src}__{dset} GROUP BY symbol")
        if st.button("Run SQL"):
            try:
                st.dataframe(con.execute(sql).df(), width="stretch")
            except Exception as exc:
                st.error(str(exc))
else:
    st.info("The lake is empty.")

st.subheader("Health checks")
hb = monitor.heartbeats()
jobs = sorted(hb["job"].unique()) if len(hb) else []
every = {j: st.session_state.get(f"every_{j}", 24.0) for j in jobs}
max_age = {n: 48.0 for n in names}
table = monitor.check(every, max_age, lake)
if len(table):
    st.dataframe(table, width="stretch", hide_index=True)
st.caption("Thresholds here are illustrative (24h jobs, 48h data). In production the same check runs as "
           "`quantlab monitor --job ... --data ...`, which exits non-zero for alerting.")
if len(hb):
    st.subheader("Recent heartbeats")
    st.dataframe(hb.sort_values("ts", ascending=False).head(50), width="stretch", hide_index=True)
