from __future__ import annotations

import itertools

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from ui import chart, data_picker, empty, fmt, header, is_dark, kpis, pal

from quantlab import fast, validation
from quantlab.report.charts import style
from quantlab.research.registry import Registry, fingerprint
from quantlab.stats.deflated import noise_bar
from quantlab.stats.permutation import search_null
from quantlab.strategies import REGISTRY

header("Validate", "Parameter Search",
       "Sweep a grid in fast vectorized mode, then ask the two questions a sweep needs: does the best cell beat "
       "the best cell of the SAME search on shuffled signals, and how often does the in-sample winner lose out "
       "of sample (PBO)?")

with st.sidebar:
    df, lbl = data_picker("op")
    sname = st.selectbox("Template", sorted(REGISTRY), format_func=lambda k: REGISTRY[k].description)
    spec = REGISTRY[sname]
    grid = {}
    for k, vals in spec.grid.items():
        txt = st.text_input(k, ", ".join(str(v) for v in vals), key=f"op_{sname}_{k}")
        try:
            grid[k] = [type(vals[0])(x.strip()) for x in txt.split(",") if x.strip()]
        except ValueError:
            st.error(f"{k}: numbers only")
    cost = st.number_input("Cost per side (bp)", value=5.0, step=0.5, help="Fees plus half the spread, fast mode")
    n_perm = st.slider("Shuffled searches", 20, 400, 100, step=20)
    study = st.text_input("Study", value=f"search_{sname}")
    go_ = st.button("Run search", type="primary", width="stretch", icon=":material/play_arrow:")

combos = [dict(spec.defaults, **dict(zip(grid, v, strict=True))) for v in itertools.product(*grid.values())]
st.caption(f"{len(combos)} cells. Pure noise alone takes the best of {len(combos)} to |t| ≈ "
           f"{noise_bar(len(combos)):.2f}.")
if not go_ or df is None:
    empty("Set the grid in the sidebar and **Run search**." if df is not None else "Load data first.")
    st.stop()

keys = list(grid)
cells = {", ".join(f"{k}={c[k]}" for k in keys): spec.make(**c) for c in combos}
box = st.empty()
with box.status("Sweeping in fast mode", expanded=False) as status:
    stats, daily = fast.sweep(cells, df, cost_bp=cost)
    reg, fp = Registry(), fingerprint(df)
    for c, (_, row) in zip(combos, stats.iterrows(), strict=True):
        reg.record(study, sname, c, {"day_t": row["day_t"], "calendar_sharpe": row["calendar_sharpe"],
                                     "trades": None, "calendar_days": len(daily)}, fp, note="fast")
    status.update(label="Shuffled searches (whole-search null)")
    bar = st.progress(0.0)
    null = search_null(cells, df, n_perm=n_perm, progress=lambda i, n: bar.progress(i / n))
    status.update(label="Probability of backtest overfitting")
    pbo = validation.pbo(daily) if daily.shape[1] >= 2 else {}
    status.update(label="Done", state="complete")
box.empty()

best = stats["calendar_sharpe"].idxmax()
st.caption(f"Best cell: **{best}**")
kpis([("Best cell Sharpe", fmt(stats.loc[best, "calendar_sharpe"]), "Fast mode, annualised over calendar days"),
      ("Permutation p", fmt(null.p_value, digits=3), "Share of shuffled searches whose best cell did as well"),
      ("PBO", fmt(pbo.get("pbo"), "pct0"), "Probability the in-sample winner is below median out of sample"),
      (f"Study bar (K = {reg.k(study)})", fmt(reg.bar(study)), None)])
verdict = null.p_value < 0.05 and pbo.get("pbo", 1) < 0.5
st.markdown(("**The search found something luck does not explain.** " if verdict else
             "**This is what a search of this size finds by luck.** ")
            + f"The best real cell (t {null.best_real:.2f}) vs the best shuffled cell: p = {null.p_value:.3f}; "
              f"PBO {fmt(pbo.get('pbo'), 'pct0')}.")

p, dark = pal(), is_dark()
a, b = st.columns(2)
with a:
    fig = go.Figure(go.Histogram(x=null.null_best, nbinsx=40, marker_color=p["accent"], opacity=0.8,
                                 name="best shuffled cell"))
    fig.add_vline(x=null.best_real, line=dict(color=p["neg"], width=3), annotation_text="best real cell")
    chart(style(fig, 320, "Null distribution of the best cell (day t)", dark), "null")
with b:
    if pbo:
        fig = go.Figure(go.Histogram(x=pbo["logits"], nbinsx=30, marker_color=p["bench"], opacity=0.85))
        fig.add_vline(x=0, line=dict(color=p["muted"], width=2), annotation_text="median")
        chart(style(fig, 320, "Out-of-sample rank of each in-sample winner (logit)", dark), "pbo")
if len(keys) == 2:
    piv = stats["calendar_sharpe"].copy()
    piv.index = [tuple(x.split(", ")) for x in piv.index]
    xs = sorted({c[keys[0]] for c in combos})
    ys = sorted({c[keys[1]] for c in combos})
    z = np.array([[stats.loc[f"{keys[0]}={x}, {keys[1]}={y}", "calendar_sharpe"] for x in xs] for y in ys])
    fig = go.Figure(go.Heatmap(z=z, x=[str(x) for x in xs], y=[str(y) for y in ys], zmid=0, texttemplate="%{z:.2f}",
                               colorscale=[[0, p["neg"]], [0.5, p["surface"]], [1, p["pos"]]], showscale=False))
    fig.update_xaxes(title=keys[0], type="category")
    fig.update_yaxes(title=keys[1], type="category")
    chart(style(fig, 360, "Sharpe by cell: a real edge is a plateau, not a lone peak", dark), "hm")
st.dataframe(stats.sort_values("calendar_sharpe", ascending=False).round(3), width="stretch")
