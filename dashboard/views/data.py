from __future__ import annotations

import plotly.express as px
import streamlit as st
from ui import chart, empty, ensure_demo_data, header, is_dark, pal

from quantlab import monitor
from quantlab.data import importer, quality
from quantlab.data.lake import Lake
from quantlab.report.charts import style

header("Data", "Data Manager",
       "Everything lands in one Parquet lake that DuckDB queries in place. Bring your own files, pull public "
       "market data, and check quality before a backtest ever sees it.")

lake = Lake()
tabs = st.tabs(["Catalog", "Import a file", "Fetch public data", "Quality", "Continuous futures", "SQL"])

with tabs[0]:
    cat = lake.catalog()
    if cat.empty:
        empty("The lake is empty.")
        if st.button("Load demo data", type="primary"):
            ensure_demo_data()
            st.rerun()
    else:
        st.dataframe(cat, hide_index=True, width="stretch", column_config={
            "source": "Source", "dataset": "Dataset",
            "rows": st.column_config.NumberColumn("Rows", format="localized"),
            "symbols": st.column_config.NumberColumn("Symbols", format="%d"),
            "first": st.column_config.DatetimeColumn("First bar", format="YYYY-MM-DD HH:mm"),
            "last": st.column_config.DatetimeColumn("Last bar", format="YYYY-MM-DD HH:mm"),
            "updated_utc": st.column_config.DatetimeColumn("Updated (UTC)", format="YYYY-MM-DD HH:mm"),
            "size_mb": st.column_config.NumberColumn("Size (MB)", format="%.1f")})
        ds = st.selectbox("Coverage of", [f"{r.source}/{r.dataset}" for r in cat.itertuples()])
        src, dset = ds.split("/", 1)
        counts = lake.duckdb().execute(f"SELECT symbol, date_trunc('day', timestamp) AS day, count(*) AS bars "
                                       f"FROM {src}__{dset} GROUP BY ALL ORDER BY day").df()
        fig = px.line(counts, x="day", y="bars", color="symbol", color_discrete_sequence=pal()["series"])
        fig.update_yaxes(rangemode="tozero")
        chart(style(fig, 300, "Bars per day (gaps show as dips)", is_dark()), "cov")

with tabs[1]:
    st.caption("CSV or Parquet. Column names are detected (Date/time/timestamp, Open/High/Low/Close, Volume, "
               "Ticker/Symbol ...) and times are stored in UTC.")
    up = st.file_uploader("File", type=["csv", "parquet", "txt"])
    if up is not None:
        raw = importer.load_file(up.getvalue(), up.name)
        st.dataframe(raw.head(8), width="stretch")
        guess = importer.guess_mapping(raw.columns)
        cols = ["(none)"] + list(raw.columns)
        c = st.columns(4)
        mapping = {}
        for i, field in enumerate(["timestamp", "symbol", "open", "high", "low", "close", "volume", "quote_volume"]):
            v = c[i % 4].selectbox(field, cols, index=cols.index(guess[field]) if field in guess else 0, key=f"map_{field}")
            if v != "(none)":
                mapping[field] = v
        a, b, d = st.columns(3)
        sym = a.text_input("Symbol (if the file has none)", "ASSET")
        source = b.text_input("Source name", "custom")
        dataset = d.text_input("Dataset name", "bars")
        try:
            clean = importer.standardize(raw, mapping, symbol=sym)
            st.success(f"{len(clean):,} rows, {clean['symbol'].nunique()} symbols, "
                       f"{clean['timestamp'].min()} → {clean['timestamp'].max()}")
            rep = quality.report(clean)
            st.dataframe(rep["symbols"], hide_index=True, width="stretch")
            if st.button("Add to the lake", type="primary", icon=":material/upload:"):
                with monitor.job("import_file", file=up.name):
                    st.write(lake.write(source, dataset, clean))
                st.success(f"Stored as `{source}/{dataset}`.")
        except ValueError as exc:
            st.error(str(exc))

with tabs[2]:
    kind = st.segmented_control("Source", ["Binance archive", "Yahoo daily", "CCXT exchange", "FRED macro"],
                                default="Binance archive")
    if kind == "Binance archive":
        syms = st.text_input("Symbols", "BTCUSDT, ETHUSDT, SOLUSDT")
        a, b, c = st.columns(3)
        start, end = a.text_input("From (YYYY-MM)", "2024-01"), b.text_input("To (YYYY-MM)", "2024-06")
        interval = c.selectbox("Interval", ["1h", "4h", "1d", "15m"])
        funding = st.toggle("Attach funding rates (USD-M futures)", value=True)
        if st.button("Fetch", type="primary"):
            from quantlab.data.sources import binance as B
            sl = [s.strip().upper() for s in syms.split(",") if s.strip()]
            with st.status("Downloading monthly archives") as s, monitor.job("fetch_binance"):
                k = B.fetch_klines(sl, start, end, interval, progress=s.write)
                if funding and len(k):
                    k = B.attach_funding(k, B.fetch_funding(sl, start, end, progress=s.write))
                st.write(lake.write("binance", f"klines_{interval}", k))
    elif kind == "Yahoo daily":
        syms = st.text_input("Tickers", "SPY, QQQ, IWM, TLT, GLD")
        start = st.text_input("From", "2015-01-01")
        if st.button("Fetch", type="primary"):
            from quantlab.data.sources import yahoo
            with st.spinner("Downloading"), monitor.job("fetch_yahoo"):
                st.write(lake.write("yahoo", "daily", yahoo.fetch_daily([s.strip() for s in syms.split(",")], start)))
    elif kind == "CCXT exchange":
        a, b, c = st.columns(3)
        ex = a.text_input("Exchange id", "kraken")
        syms = b.text_input("Pairs", "BTC/USD, ETH/USD")
        tf = c.selectbox("Timeframe", ["1h", "4h", "1d"])
        start = st.text_input("From", "2024-01-01")
        if st.button("Fetch", type="primary"):
            from quantlab.data.sources.extra import ccxt_ohlcv
            with st.status("Downloading") as s, monitor.job("fetch_ccxt"):
                d = ccxt_ohlcv(ex, [x.strip() for x in syms.split(",")], tf, start, progress=s.write)
                st.write(lake.write(ex, f"ohlcv_{tf}", d))
    else:
        sid = st.text_input("Series id", "DGS10", help="e.g. DGS10 (10y Treasury), CPIAUCSL, UNRATE, VIXCLS")
        if st.button("Fetch", type="primary"):
            from quantlab.data.sources.extra import fred_series, fred_to_bars
            d = fred_series(sid)
            fig = px.line(d, x="timestamp", y="value")
            chart(style(fig, 280, sid, is_dark()), "fred")
            st.write(lake.write("fred", "series", fred_to_bars(d)))

with tabs[3]:
    names = [f"{s}/{d}" for s, d in lake.datasets()]
    if names:
        ds = st.selectbox("Dataset", names, key="q_ds")
        src, dset = ds.split("/", 1)
        rep = quality.report(lake.read(src, dset))
        st.dataframe(rep["symbols"], hide_index=True, width="stretch",
                     column_config={"grade": st.column_config.TextColumn("Grade", help="A clean · D needs fixing"),
                                    "complete_pct": st.column_config.NumberColumn(
                                        "Complete OHLC %", format="%.2f",
                                        help="Share of bars with open, high, low and close all present")})
        with st.expander("Schema and column completeness"):
            st.caption(" · ".join(f"{k.replace('_', ' ')} **{v}**" for k, v in rep["schema"].items()))
            st.dataframe(rep["columns"].astype({"min": str, "max": str}), hide_index=True, width="stretch",
                         column_config={"non_null_pct": st.column_config.ProgressColumn(
                             "Non-null %", min_value=0, max_value=100, format="%.1f%%")})
        if len(rep["findings"]):
            st.dataframe(rep["findings"], hide_index=True, width="stretch", height=300)
        else:
            st.success("No issues found.")
    else:
        empty("No datasets.")

with tabs[4]:
    st.caption("Upload individual contracts (timestamp, contract, expiry, open, high, low, close, volume) and build one "
               "back-adjusted continuous series with roll flags the engine charges for.")
    up = st.file_uploader("Contracts file", type=["csv", "parquet"], key="fut_up")
    a, b, c, d = st.columns(4)
    root = a.text_input("Root", "ES")
    rule = b.selectbox("Roll on", ["calendar", "volume"])
    days = c.number_input("Days before expiry", value=5)
    adj = d.selectbox("Adjust by", ["ratio", "difference"])
    if up is not None:
        from quantlab.futures import continuous
        raw = importer.load_file(up.getvalue(), up.name)
        cont = continuous(raw, root, rule, int(days), adj)
        fig = px.line(cont, x="timestamp", y="close", color_discrete_sequence=[pal()["accent"]])
        for t in cont.loc[cont["roll"], "timestamp"]:
            fig.add_vline(x=t, line=dict(color=pal()["bench"], dash="dot"))
        chart(style(fig, 300, f"{root} continuous (dotted = rolls)", is_dark()), "fut")
        if st.button("Add to the lake", type="primary", key="fut_add"):
            st.write(lake.write("futures", "continuous", cont.drop(columns=["contract"])))

with tabs[5]:
    names = [f"{s}__{d}" for s, d in lake.datasets()]
    st.caption("Read-only views, one per dataset: " + ", ".join(f"`{n}`" for n in names))
    default = f"SELECT symbol, count(*) AS bars, min(timestamp), max(timestamp)\nFROM {names[0]} GROUP BY symbol" \
        if names else "SELECT 1"
    sql = st.text_area("Query", default, height=120)
    if st.button("Run SQL", icon=":material/terminal:"):
        try:
            st.dataframe(lake.duckdb().execute(sql).df(), width="stretch")
        except Exception as exc:
            st.error(str(exc))
