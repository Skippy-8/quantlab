"""Plotly figures for a backtest: equity, drawdown, monthly heatmap, rolling Sharpe,
return distribution, trade map. Each takes a palette so the same figure works in
the dashboard (either theme) and in an exported report."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from quantlab.report import metrics as M
from quantlab.report.theme import FONT_MONO, FONT_SANS, palette


def style(fig: go.Figure, height: int = 320, title: str = "", dark: bool = False, transparent: bool = True,
          pct_y: bool = False) -> go.Figure:
    p = palette(dark)
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=44 if title else 12, b=8),
        title=dict(text=title, x=0, xanchor="left", font=dict(family=FONT_SANS, size=14, color=p["ink"])),
        font=dict(family=FONT_SANS, size=12, color=p["muted"]),
        paper_bgcolor="rgba(0,0,0,0)" if transparent else p["surface"],
        plot_bgcolor="rgba(0,0,0,0)" if transparent else p["surface"],
        legend=dict(orientation="h", y=1.0, yanchor="bottom", x=1, xanchor="right", bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified", hoverlabel=dict(font=dict(family=FONT_MONO, size=12)),
        colorway=p["series"])
    fig.update_xaxes(showgrid=False, automargin=True, linecolor=p["line"], ticks="outside", tickcolor=p["line"],
                     tickfont=dict(family=FONT_MONO, size=11))
    fig.update_yaxes(gridcolor=p["line"], zerolinecolor=p["line"], automargin=True, tickfont=dict(family=FONT_MONO, size=11))
    if pct_y:
        fig.update_yaxes(tickformat=".0%")
    return fig


def equity(eq: pd.Series, bench: pd.Series | None = None, dark: bool = False, log: bool = False) -> go.Figure:
    p = palette(dark)
    fig = go.Figure()
    if bench is not None and len(bench):
        b = bench.reindex(eq.index).ffill()
        b = b / b.dropna().iloc[0] * eq.iloc[0]
        fig.add_scatter(x=b.index, y=b.values, name="Benchmark", line=dict(color=p["bench"], width=1.5))
    fig.add_scatter(x=eq.index, y=eq.values, name="Strategy", line=dict(color=p["accent"], width=2.2),
                    fill="tozeroy" if not log else None, fillcolor=p["accent_soft"] if not dark else "rgba(139,163,255,.08)")
    fig.update_yaxes(type="log" if log else "linear", tickformat="$,.0f")
    rng = (eq.min(), eq.max())
    if not log:
        pad = (rng[1] - rng[0]) * 0.08 or rng[1] * 0.02
        fig.update_yaxes(range=[rng[0] - pad, rng[1] + pad])
    return style(fig, 340, "Equity", dark)


def underwater(r: pd.Series, dark: bool = False) -> go.Figure:
    p = palette(dark)
    dd = M.drawdown(r)
    fig = go.Figure(go.Scatter(x=dd.index, y=dd.values, name="Drawdown", fill="tozeroy",
                               line=dict(color=p["neg"], width=1.2), fillcolor="rgba(194,59,54,.18)"))
    return style(fig, 220, "Drawdown from peak", dark, pct_y=True)


def monthly_heatmap(r: pd.Series, dark: bool = False) -> go.Figure:
    p = palette(dark)
    t = M.monthly_table(r).drop(columns="Year")
    z = t.to_numpy(float)
    lim = np.nanmax(np.abs(z)) if np.isfinite(z).any() else 0.01
    text = [[("" if np.isnan(v) else f"{v * 100:+.1f}") for v in row] for row in z]
    fig = go.Figure(go.Heatmap(z=z, x=list(t.columns), y=[str(y) for y in t.index], zmid=0, zmin=-lim, zmax=lim,
                               colorscale=[[0, p["neg"]], [0.5, p["surface"]], [1, p["pos"]]], text=text,
                               texttemplate="%{text}", textfont=dict(family=FONT_MONO, size=11), showscale=False,
                               hovertemplate="%{y} %{x}: %{z:.2%}<extra></extra>", xgap=2, ygap=2))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return style(fig, 60 + 34 * len(t), "Monthly returns (%)", dark)


def rolling_sharpe(r: pd.Series, window: int = 90, periods: int = 365, dark: bool = False) -> go.Figure:
    p = palette(dark)
    rs = M.rolling_sharpe(r, window, periods)
    fig = go.Figure(go.Scatter(x=rs.index, y=rs.values, name=f"{window}-day Sharpe", line=dict(color=p["accent"])))
    fig.add_hline(y=0, line=dict(color=p["muted"], width=1))
    return style(fig, 220, f"Rolling {window}-day Sharpe", dark)


def distribution(r: pd.Series, dark: bool = False) -> go.Figure:
    p = palette(dark)
    x = r[r != 0]
    fig = go.Figure(go.Histogram(x=x, nbinsx=60, marker_color=p["accent"], opacity=0.85, name="Daily return"))
    if len(x) > 2 and x.std() > 0:
        grid = np.linspace(x.min(), x.max(), 200)
        dens = np.exp(-0.5 * ((grid - x.mean()) / x.std()) ** 2) / (x.std() * np.sqrt(2 * np.pi))
        width = (x.max() - x.min()) / 60
        fig.add_scatter(x=grid, y=dens * len(x) * width, name="Normal", line=dict(color=p["bench"], dash="dot"))
    fig.update_xaxes(tickformat=".1%")
    return style(fig, 240, "Distribution of active daily returns", dark)


def trade_map(positions: pd.DataFrame, dark: bool = False) -> go.Figure:
    p = palette(dark)
    if positions.empty:
        return style(go.Figure(), 240, "Trades", dark)
    c = np.where(positions["net_bp"] > 0, p["pos"], p["neg"])
    fig = go.Figure(go.Scatter(
        x=pd.to_datetime(positions["exit_time"]), y=positions["net_bp"], mode="markers",
        marker=dict(color=c, size=np.clip(np.sqrt(positions["bars_held"].clip(lower=1)) * 2.2, 4, 16), opacity=0.7,
                    line=dict(width=0)),
        customdata=np.stack([positions["symbol"], positions["side"], positions["exit"]], axis=1),
        hovertemplate="%{customdata[0]} %{customdata[1]} (%{customdata[2]})<br>%{y:.1f} bp<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=p["muted"], width=1))
    fig.update_layout(hovermode="closest")
    return style(fig, 260, "Every trade: net bp at exit (size = time held)", dark)
