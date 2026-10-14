from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ui import chart, empty, fmt, header, is_dark, kpis, pal

from quantlab.report.charts import style
from quantlab.sec.store import InsiderStore, default_path

header("Markets", "Insider Filings",
       "SEC Form 3/4/5 transactions keyed on the EDGAR acceptance time, the moment the market could first have "
       "known. Transaction dates are shown but never used for timing; pre-planned 10b5-1 trades are separated out.")

if not default_path().exists():
    empty("No insider database yet. Set `SEC_USER_AGENT='Your Name you@email'` and run "
          "`quantlab sec sync AAPL MSFT NVDA --since 2023-01-01`.")
    st.stop()

store = InsiderStore(read_only=True)
s = store.summary()
kpis([("Transactions", fmt(s["rows"], "int"), None), ("Filings", fmt(s["filings"], "int"), None),
      ("Companies", fmt(s["tickers"], "int"), None), ("Public through", str(s["last"])[:10] if s["last"] else "—", None)])

with st.sidebar:
    excl = st.toggle("Exclude 10b5-1 pre-planned trades", value=True)
    roles = st.pills("Role", ["Officer", "Director", "10% owner"], selection_mode="multi",
                     default=["Officer", "Director", "10% owner"])
    min_usd = st.number_input("Minimum purchase ($)", value=0, step=50_000)

p = store.purchases(exclude_plans=excl)
if len(p):
    mask = pd.Series(False, index=p.index)
    mask |= p["officer"] & ("Officer" in roles)
    mask |= p["director"] & ("Director" in roles)
    mask |= p["ten_pct"] & ("10% owner" in roles)
    p = p[mask & (p["value_usd"].fillna(0) >= min_usd)]

tab1, tab2, tab3 = st.tabs(["Purchases", "Cluster buys", "Point-in-time view"])
with tab1:
    if len(p):
        pp, dark = pal(), is_dark()
        m = p.assign(month=pd.to_datetime(p["public_at"], utc=True).dt.tz_convert(None).dt.to_period("M").dt.to_timestamp())
        agg = m.groupby("month").agg(dollars=("value_usd", "sum"), n=("ticker", "size")).reset_index()
        fig = go.Figure(go.Bar(x=agg["month"], y=agg["dollars"], marker_color=pp["accent"],
                               customdata=agg["n"], hovertemplate="%{x|%b %Y}: $%{y:,.0f} (%{customdata} buys)<extra></extra>"))
        fig.update_yaxes(tickprefix="$")
        chart(style(fig, 280, "Open-market purchase dollars by the month they became public", dark), "ins_m")
        st.dataframe(p.sort_values("public_at", ascending=False), hide_index=True, width="stretch", height=380,
                     column_config={"value_usd": st.column_config.NumberColumn("Value", format="dollar")})
    else:
        empty("No purchases match the filters.")
with tab2:
    q = store.query("""
        WITH e AS (SELECT ticker, owner_cik, min(acceptance_datetime_utc) AS t FROM insider_transactions
                   WHERE transaction_code='P' AND acquired_disposed='A' GROUP BY ticker, owner_cik, accession_number)
        SELECT a.ticker, a.t::DATE AS window_start, count(DISTINCT b.owner_cik) AS insiders
        FROM e a JOIN e b ON a.ticker=b.ticker AND b.t BETWEEN a.t AND a.t + INTERVAL 30 DAY
        GROUP BY ALL HAVING count(DISTINCT b.owner_cik) >= 3 ORDER BY window_start DESC LIMIT 200""")
    st.caption("Three or more distinct insiders buying the same stock within 30 days.")
    if len(q):
        st.dataframe(q, hide_index=True, width="stretch")
    else:
        empty("No clusters in the data.")
with tab3:
    a, b = st.columns(2)
    tk = a.text_input("Ticker")
    when = b.date_input("As of (end of day, UTC)")
    if tk:
        st.dataframe(store.as_of(pd.Timestamp(when) + pd.Timedelta(days=1), tk), hide_index=True, width="stretch")
