from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from ui import ACCENT, BAD, fig_layout, page

from quantlab.research.registry import Registry
from quantlab.stats.deflated import noise_bar

page("Research Registry", "📒", "Every recorded trial, by study. The pass bar is the |t| the best of K "
     "noise trials is expected to reach, so it rises as a study tries more things.")

reg = Registry()
studies = reg.studies()
if not studies:
    st.info("No trials recorded yet. Run a backtest from the Backtest Lab or `quantlab backtest`.")
    st.stop()

study = st.selectbox("Study", studies)
t = reg.trials(study)
k, bar = reg.k(study), reg.bar(study)
pre = reg.prereg_for(study)

c = st.columns(4)
c[0].metric("Runs", len(t))
c[1].metric("Distinct trials (K)", k)
c[2].metric("Pass bar |t|", f"{bar:.2f}")
c[3].metric("Pre-registered", "yes" if pre else "no")
if pre:
    st.caption(f"Spec `{pre['spec']}` registered {pre['ts']} (sha256 {pre['spec_sha256'][:12]}...)")

ks = np.arange(1, max(k, 2) * 4)
fig = go.Figure()
fig.add_scatter(x=ks, y=[noise_bar(int(x), reg.floor) for x in ks], name="pass bar", line=dict(color=BAD))
tt = t.dropna(subset=["day_t"]).reset_index(drop=True)
fig.add_scatter(x=np.arange(1, len(tt) + 1), y=tt["day_t"], mode="markers", name="trial day t",
                marker=dict(color=ACCENT, size=8))
st.plotly_chart(fig_layout(fig, 340, "Each trial's t against the bar it faces as K grows"), width="stretch")

cols = ["ts", "strategy", "params", "trades", "day_t", "calendar_sharpe", "mean_net_bp_per_trade",
        "half1_mean_day_bp", "half2_mean_day_bp", "data", "key"]
st.dataframe(t[[c for c in cols if c in t]].sort_values("ts", ascending=False), width="stretch",
             hide_index=True)
