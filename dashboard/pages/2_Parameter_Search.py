from __future__ import annotations

import itertools

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from ui import ACCENT, BAD, datasets, fig_layout, fmt, page

from quantlab.engine import EngineConfig, evaluate
from quantlab.research.registry import Registry, fingerprint
from quantlab.stats.deflated import noise_bar
from quantlab.stats.permutation import search_null
from quantlab.strategies import REGISTRY

page("Parameter Search", "🎲", "Sweeping parameters and keeping the best cell is how most backtests overfit. "
     "Here every cell is recorded, and the best one is compared with the best cell of the SAME search "
     "run on shuffled signals.")

lake, names = datasets()
if not names:
    st.warning("No data yet: run `quantlab fetch synthetic`.")
    st.stop()

with st.sidebar:
    ds = st.selectbox("Dataset", names)
    src, dset = ds.split("/", 1)
    syms = lake.symbols(src, dset)
    pick = st.multiselect("Symbols", syms, default=syms[: min(6, len(syms))])
    sname = st.selectbox("Strategy", sorted(REGISTRY), format_func=lambda k: REGISTRY[k].description)
    spec = REGISTRY[sname]
    grid = {}
    for k, vals in spec.grid.items():
        grid[k] = st.multiselect(k, vals, default=vals)
    n_perm = st.slider("Shuffled searches", 20, 500, 100, step=20)
    study = st.text_input("Study", value=f"search_{sname}")
    run = st.button("Run search", type="primary", width="stretch")

combos = [dict(spec.defaults, **dict(zip(grid, v, strict=True))) for v in itertools.product(*grid.values())]
st.caption(f"{len(combos)} cells. Noise alone takes the best of {len(combos)} to |t| ≈ "
           f"{noise_bar(len(combos)):.2f}.")
if not run:
    st.stop()

df = lake.read(src, dset, pick)
cfg, reg, fp = EngineConfig(), Registry(), fingerprint(df)
cells = {}
for c in combos:
    label = ", ".join(f"{k}={c[k]}" for k in grid)
    cells[label] = spec.make(**c)
    reg.record(study, sname, c, evaluate(spec.make(**c), df, cfg, check=False).summary, fp)

bar = st.progress(0.0, "Running shuffled searches...")
res = search_null(cells, df, cfg, n_perm=n_perm, progress=lambda i, n: bar.progress(i / n, f"shuffle {i}/{n}"))
bar.empty()

k = st.columns(4)
k[0].metric("Best cell", res.best_label)
k[1].metric("Its day t", fmt(res.best_real))
k[2].metric("Permutation p (whole search)", fmt(res.p_value, 3))
k[3].metric(f"Study bar (K = {reg.k(study)})", fmt(reg.bar(study)))
verdict = ("beats" if res.p_value < 0.05 else "does NOT beat")
st.markdown(f"The best real cell **{verdict}** the best cell found on shuffled signals "
            f"(p = {res.p_value:.3f}). A p above 0.05 means the sweep found what any sweep of this size finds by luck.")

fig = go.Figure()
fig.add_histogram(x=res.null_best, nbinsx=40, name="best cell, shuffled", marker_color=ACCENT, opacity=0.75)
fig.add_vline(x=res.best_real, line=dict(color=BAD, width=3), annotation_text="best real cell")
st.plotly_chart(fig_layout(fig, 340, "Null distribution of the BEST cell"), width="stretch")

cells_sorted = sorted(res.real_by_cell.items(), key=lambda kv: kv[1])
f2 = go.Figure(go.Bar(x=[v if np.isfinite(v) else 0 for _, v in cells_sorted], y=[k for k, _ in cells_sorted],
                      orientation="h", marker_color=ACCENT))
f2.add_vline(x=noise_bar(len(combos)), line=dict(dash="dash", color=BAD), annotation_text="noise bar")
st.plotly_chart(fig_layout(f2, 60 + 28 * len(cells_sorted), "Day t by cell"), width="stretch")
