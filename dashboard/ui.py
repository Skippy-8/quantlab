"""Shared look and helpers for the dashboard pages."""
from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ACCENT = "#2F6FDE"
GOOD, BAD, MUTED = "#1F9D6B", "#D1495B", "#8A94A6"


def page(title: str, icon: str = "📈", caption: str = "") -> None:
    st.set_page_config(page_title=f"{title} · quantlab", page_icon=icon, layout="wide")
    st.markdown("""
        <style>
          .block-container {padding-top: 2rem; max-width: 1400px;}
          div[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
          .ql-pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.8rem;
                    font-weight:600; letter-spacing:.02em;}
          .ql-pass {background:rgba(31,157,107,.15); color:#1F9D6B;}
          .ql-fail {background:rgba(209,73,91,.15); color:#D1495B;}
          .ql-warn {background:rgba(232,163,23,.18); color:#B7791F;}
        </style>""", unsafe_allow_html=True)
    st.title(title)
    if caption:
        st.caption(caption)


def pill(text: str, kind: str = "pass") -> str:
    return f'<span class="ql-pill ql-{kind}">{text}</span>'


def fmt(v, digits: int = 2, suffix: str = "") -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def fig_layout(fig: go.Figure, height: int = 340, title: str = "") -> go.Figure:
    fig.update_layout(height=height, title=title, margin=dict(l=10, r=10, t=40 if title else 10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
    fig.update_xaxes(showgrid=True, gridcolor="rgba(138,148,166,.18)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(138,148,166,.18)", zeroline=True,
                     zerolinecolor="rgba(138,148,166,.45)")
    return fig


def datasets():
    from quantlab.data.lake import Lake
    lake = Lake()
    return lake, [f"{s}/{d}" for s, d in lake.datasets()]
