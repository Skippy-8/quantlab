from __future__ import annotations

import plotly.express as px
import streamlit as st
from ui import chart, empty, header, is_dark, kpis, pal

from quantlab import monitor
from quantlab.data.lake import Lake
from quantlab.report.charts import style

header("Governance", "Monitoring",
       "Silence is ambiguous: a stalled pipeline and a quiet market look the same. Every scheduled job writes a "
       "heartbeat, and these checks turn heartbeats and data freshness into a status, the same one "
       "`quantlab monitor` returns as an exit code for alerting.")

lake = Lake()
hb = monitor.heartbeats()
jobs = sorted(hb["job"].unique()) if len(hb) else []
with st.sidebar:
    st.markdown("### Expectations")
    every = {j: st.number_input(f"{j}: runs every (h)", value=24.0, step=1.0, key=f"ev_{j}") for j in jobs}
    max_age = {f"{s}/{d}": st.number_input(f"{s}/{d}: max bar age (h)", value=48.0, step=12.0, key=f"age_{s}{d}")
               for s, d in lake.datasets()}

table = monitor.check(every, max_age, lake)
if table.empty:
    empty("Nothing to check yet: no scheduled jobs have run and the lake is empty.")
    st.stop()
bad = table[table["status"] != "OK"]
kpis([("Checks", str(len(table)), None), ("OK", str(int((table["status"] == "OK").sum())), None),
      ("Need attention", str(len(bad)), None)])
p = pal()
st.dataframe(table, hide_index=True, width="stretch", column_config={"status": st.column_config.TextColumn("Status")})
if len(hb):
    h = hb.copy()
    h["day"] = h["ts"].dt.floor("D")
    agg = h.groupby(["day", "status"]).size().reset_index(name="runs")
    fig = px.bar(agg, x="day", y="runs", color="status",
                 color_discrete_map={"ok": p["pos"], "error": p["neg"], "start": p["muted"], "progress": p["accent"]})
    chart(style(fig, 260, "Heartbeats per day", is_dark()), "hb")
    st.dataframe(hb.sort_values("ts", ascending=False).head(100), hide_index=True, width="stretch")
