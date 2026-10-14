from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from ui import chart, empty, fmt, header, is_dark, kpis, pal

from quantlab.report.charts import style
from quantlab.research.registry import Registry
from quantlab.stats.deflated import noise_bar

header("Governance", "Research Registry",
       "Every run is counted in its study. The pass bar is the |t| the best of K pure-noise trials is expected to "
       "reach, so trying more things raises the bar for all of them.")

reg = Registry()
studies = reg.studies()
if not studies:
    empty("No trials yet. Every run in the Backtest Lab or Parameter Search is recorded here.")
    st.stop()

study = st.selectbox("Study", studies)
t = reg.trials(study)
k, bar = reg.k(study), reg.bar(study)
pre = reg.prereg_for(study)
best = t["day_t"].max() if len(t) else None
kpis([("Runs", fmt(len(t), "int"), None), ("Distinct trials (K)", fmt(k, "int"), None),
      ("Pass bar |t|", fmt(bar), "max(2, √(2 ln K))"), ("Best day t", fmt(best), None),
      ("Pre-registered", "Yes" if pre else "No", "A written spec registered before any result")])
if pre:
    st.caption(f"Spec `{pre['spec']}` registered {pre['ts']} · sha256 {pre['spec_sha256'][:16]}…")
else:
    with st.expander("Pre-register this study"):
        st.markdown("Write the hypothesis, the exact rule, the statistic and the pass threshold **before** running, "
                    "then register the file. Its hash is recorded, so anyone can check it predates the results.")
        path = st.text_input("Spec file path")
        if path and st.button("Register spec"):
            st.write(reg.preregister(study, path))

p, dark = pal(), is_dark()
ks = np.arange(1, max(k * 3, 20))
fig = go.Figure()
fig.add_scatter(x=ks, y=[noise_bar(int(x), reg.floor) for x in ks], name="Pass bar", line=dict(color=p["neg"], width=2))
tt = t.dropna(subset=["day_t"]).reset_index(drop=True)
fig.add_scatter(x=np.arange(1, len(tt) + 1), y=tt["day_t"], mode="markers", name="Trial day t",
                marker=dict(color=[p["pos"] if v >= bar else p["accent"] for v in tt["day_t"]], size=9))
fig.update_xaxes(title="trial number (K)")
chart(style(fig, 340, "Each trial against the bar it faces", dark), "reg")
cols = ["ts", "strategy", "params", "trades", "day_t", "calendar_sharpe", "mean_net_bp_per_trade",
        "half1_mean_day_bp", "half2_mean_day_bp", "note", "data", "key"]
st.dataframe(t[[c for c in cols if c in t]].sort_values("ts", ascending=False), hide_index=True, width="stretch",
             column_config={"ts": st.column_config.TextColumn("Recorded (UTC)"), "strategy": "Strategy",
                            "params": "Parameters", "trades": "Trades", "note": "Note", "data": "Data fingerprint",
                            "key": "Trial key", "day_t": st.column_config.NumberColumn("Day t", format="%.2f"),
                            "calendar_sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
                            "mean_net_bp_per_trade": st.column_config.NumberColumn("Net bp / trade", format="%.1f"),
                            "half1_mean_day_bp": st.column_config.NumberColumn("1st half bp/day", format="%.1f"),
                            "half2_mean_day_bp": st.column_config.NumberColumn("2nd half bp/day", format="%.1f")})
