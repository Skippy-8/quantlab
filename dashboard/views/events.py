from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ui import chart, data_picker, empty, fmt, header, is_dark, kpis, pal

from quantlab.data.importer import load_file
from quantlab.engine import EngineConfig, evaluate
from quantlab.events import event_strategy, event_study
from quantlab.report.charts import style
from quantlab.sec.store import InsiderStore, default_path

header("Markets", "Event Studies",
       "What happens to prices around an event: earnings, insider purchases, listings, or any dated list you "
       "upload. Abnormal returns are measured against the market, inference is clustered by date, and the same "
       "events can be traded through the standard engine.")

with st.sidebar:
    df, lbl = data_picker("ev", default_symbols=20)
    st.markdown("### Events")
    src = st.selectbox("Event source", ["Upload CSV (symbol, timestamp)", "SEC insider purchases", "Earnings (yfinance)"])
    up = st.file_uploader("Events file", type=["csv", "parquet"]) if src.startswith("Upload") else None
    min_usd = st.number_input("Minimum purchase ($)", value=100_000, step=50_000) if src.startswith("SEC") else 0
    st.markdown("### Window")
    a, b = st.columns(2)
    pre = a.number_input("Bars before", value=5, min_value=1)
    post = b.number_input("Bars after", value=20, min_value=1)
    model = st.selectbox("Abnormal return model", ["market", "market_model", "raw"],
                         format_func=lambda m: {"market": "Minus the market", "market_model": "Market model (α, β)",
                                                "raw": "Raw returns"}[m])
    go_ = st.button("Run event study", type="primary", width="stretch", icon=":material/play_arrow:")

if not go_ or df is None:
    empty("Pick data and an event source, then **Run event study**." if df is not None else "Load price data first.")
    st.stop()

if src.startswith("Upload"):
    if up is None:
        st.warning("Upload a file with `symbol` and `timestamp` columns.")
        st.stop()
    ev = load_file(up.getvalue(), up.name)
    ev.columns = [c.lower() for c in ev.columns]
elif src.startswith("SEC"):
    if not default_path().exists():
        st.warning("No insider database yet: run `quantlab sec sync ...` first.")
        st.stop()
    from quantlab.events import insider_purchases
    ev = insider_purchases(InsiderStore(read_only=True), min_value=min_usd)
else:
    from quantlab.events import earnings_dates
    with st.spinner("Fetching earnings dates"):
        ev = earnings_dates(sorted(df["symbol"].unique()))
if ev.empty or not {"symbol", "timestamp"} <= set(ev.columns):
    st.warning("No usable events (need `symbol` and `timestamp`).")
    st.stop()
ev["timestamp"] = pd.to_datetime(ev["timestamp"], utc=True)
ev = ev[ev["symbol"].isin(df["symbol"].unique())]
out = event_study(df, ev, int(pre), int(post), model=model)
if not out.get("events"):
    empty("None of the events fall inside the loaded data with a full window around them.")
    st.stop()

kpis([("Events", fmt(out["events"], "int"), None), ("Event dates", fmt(out["event_dates"], "int"), None),
      ("Mean CAR after", fmt(out["mean_car_post"], "pct", 3), "Cumulative abnormal return from the event bar on"),
      ("Median CAR after", fmt(out["median_car_post"], "pct", 3), None),
      ("Date-clustered t", fmt(out["t_date_clustered"]), "Events on the same day count once")])
p, dark = pal(), is_dark()
path = out["path"]
fig = go.Figure()
fig.add_scatter(x=path["bar"], y=path["hi"], line=dict(width=0), showlegend=False, hoverinfo="skip")
fig.add_scatter(x=path["bar"], y=path["lo"], fill="tonexty", fillcolor="rgba(53,80,200,.15)", line=dict(width=0),
                name="95% band")
fig.add_scatter(x=path["bar"], y=path["mean_car"], line=dict(color=p["accent"], width=2.5), name="Mean CAR")
fig.add_vline(x=0, line=dict(color=p["muted"], dash="dot"))
fig.update_yaxes(tickformat=".1%")
fig.update_xaxes(title="bars relative to the event")
chart(style(fig, 360, "Cumulative abnormal return around the event", dark), "car")

st.markdown("#### Trade it")
c1, c2, c3 = st.columns(3)
side = c1.segmented_control("Side", [1, -1], default=1, format_func=lambda s: "Long" if s > 0 else "Short")
hold = c2.number_input("Hold (bars)", value=int(post), min_value=1)
delay = c3.number_input("Delay (bars after it is public)", value=0, min_value=0)
res = evaluate(event_strategy(ev, int(side or 1), int(hold), int(delay)), df, EngineConfig())
s = res.summary
kpis([("Trades", fmt(s["trades"], "int"), None), ("Net per trade", fmt(s.get("mean_net_bp_per_trade"), "bp"), None),
      ("Win rate", fmt(s.get("win_rate"), "pct0"), None), ("Day t", fmt(s.get("day_t")), None)])
st.dataframe(out["per_event"].sort_values("car_post"), hide_index=True, width="stretch", height=300)
