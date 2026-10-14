from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from ui import fig_layout, page

from quantlab.sec.store import InsiderStore, default_path

page("Insider Explorer", "🗂️", "SEC Form 3/4/5 insider transactions, keyed on the EDGAR acceptance time: "
     "the moment the market could first have known. Transaction dates are shown, never used for timing.")

if not default_path().exists():
    st.info("No insider data yet. Set `SEC_USER_AGENT='Your Name you@email'` and run "
            "`quantlab sec sync AAPL MSFT NVDA --since 2023-01-01`.")
    st.stop()

store = InsiderStore(read_only=True)
s = store.summary()
c = st.columns(4)
c[0].metric("Transactions", f"{s['rows']:,}")
c[1].metric("Filings", f"{s['filings']:,}")
c[2].metric("Tickers", s["tickers"])
c[3].metric("Public through", str(s["last"])[:10] if s["last"] else "—")

with st.sidebar:
    excl = st.checkbox("Exclude 10b5-1 pre-planned trades", value=True)
    role = st.multiselect("Role", ["officer", "director", "10% owner"], default=["officer", "director", "10% owner"])
    min_usd = st.number_input("Minimum purchase ($)", value=0, step=50_000)

p = store.purchases(exclude_plans=excl)
if len(p):
    mask = pd.Series(False, index=p.index)
    mask |= p["officer"] & ("officer" in role)
    mask |= p["director"] & ("director" in role)
    mask |= p["ten_pct"] & ("10% owner" in role)
    p = p[mask & (p["value_usd"].fillna(0) >= min_usd)]
st.subheader(f"Open-market purchases ({len(p):,})")
if len(p):
    p["month"] = pd.to_datetime(p["public_at"], utc=True).dt.tz_convert(None).dt.to_period("M").dt.to_timestamp()
    fig = px.bar(p.groupby("month").agg(dollars=("value_usd", "sum")).reset_index(), x="month", y="dollars")
    st.plotly_chart(fig_layout(fig, 280, "Purchase dollars by month made public"), width="stretch")
    st.markdown("**Cluster buys**: three or more distinct insiders buying the same stock within 30 days")
    q = store.query("""
        WITH e AS (SELECT ticker, owner_cik, min(acceptance_datetime_utc) AS t FROM insider_transactions
                   WHERE transaction_code='P' AND acquired_disposed='A' GROUP BY ticker, owner_cik, accession_number)
        SELECT a.ticker, a.t::DATE AS window_start, count(DISTINCT b.owner_cik) AS insiders
        FROM e a JOIN e b ON a.ticker=b.ticker AND b.t BETWEEN a.t AND a.t + INTERVAL 30 DAY
        GROUP BY ALL HAVING count(DISTINCT b.owner_cik) >= 3 ORDER BY window_start DESC LIMIT 200""")
    st.dataframe(q, width="stretch", hide_index=True)
    st.dataframe(p.drop(columns=["month"]).sort_values("public_at", ascending=False), width="stretch",
                 hide_index=True)

tk = st.text_input("Point-in-time view: what was public about one ticker at a date")
when = st.date_input("As of")
if tk:
    st.dataframe(store.as_of(pd.Timestamp(when) + pd.Timedelta(days=1), tk), width="stretch",
                 hide_index=True)
