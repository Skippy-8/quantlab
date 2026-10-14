"""quantlab dashboard.

    streamlit run dashboard/app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="quantlab", page_icon=":material/query_stats:", layout="wide",
                   initial_sidebar_state="expanded")

V = "views/"   # st.Page paths resolve relative to this file
nav = st.navigation({
    "": [st.Page(V + "home.py", title="Overview", icon=":material/space_dashboard:", default=True)],
    "Build": [st.Page(V + "builder.py", title="Strategy Builder", icon=":material/tune:"),
              st.Page(V + "backtest.py", title="Backtest Lab", icon=":material/science:")],
    "Validate": [st.Page(V + "optimize.py", title="Parameter Search", icon=":material/grid_on:"),
                 st.Page(V + "walkforward.py", title="Walk-Forward", icon=":material/fast_forward:"),
                 st.Page(V + "robustness.py", title="Robustness", icon=":material/shield:"),
                 st.Page(V + "compare.py", title="Compare Runs", icon=":material/compare_arrows:")],
    "Markets": [st.Page(V + "options.py", title="Options Lab", icon=":material/stacked_line_chart:"),
                st.Page(V + "events.py", title="Event Studies", icon=":material/event:"),
                st.Page(V + "insiders.py", title="Insider Filings", icon=":material/gavel:")],
    "Data": [st.Page(V + "data.py", title="Data Manager", icon=":material/database:")],
    "Governance": [st.Page(V + "registry.py", title="Research Registry", icon=":material/fact_check:"),
                   st.Page(V + "monitor.py", title="Monitoring", icon=":material/monitor_heart:")],
}, position="sidebar", expanded=True)

with st.sidebar:
    st.html("""<div style="display:flex;align-items:center;gap:.5rem;margin:-.4rem 0 .2rem 0">
      <span style="font:650 1.15rem 'IBM Plex Sans',sans-serif;letter-spacing:-.01em">quantlab</span>
      <span style="font:500 .7rem 'IBM Plex Mono',monospace;opacity:.6">honest backtests</span></div>""")
nav.run()
