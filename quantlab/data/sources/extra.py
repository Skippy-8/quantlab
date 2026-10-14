"""More public data sources.

* :func:`ccxt_ohlcv` - bars from any of the 100+ exchanges CCXT supports, paged
  back to ``start`` (``pip install ccxt``; public endpoints need no key).
* :func:`fred_series` - a FRED macro series (rates, inflation, unemployment...)
  from FRED's public CSV endpoint, no key needed; daily values as a frame that
  can be merged onto bars or used as a regime filter.
"""
from __future__ import annotations

import io
import time

import pandas as pd
import requests


def ccxt_ohlcv(exchange: str, symbols: list[str], timeframe: str = "1h", start: str = "2024-01-01",
               end: str | None = None, limit: int = 1000, progress=print) -> pd.DataFrame:
    try:
        import ccxt
    except ImportError as exc:
        raise SystemExit("ccxt is not installed: pip install ccxt") from exc
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    since0 = ex.parse8601(pd.Timestamp(start, tz="UTC").isoformat())
    stop = ex.parse8601(pd.Timestamp(end, tz="UTC").isoformat()) if end else None
    frames = []
    for sym in symbols:
        since, rows = since0, []
        while True:
            batch = ex.fetch_ohlcv(sym, timeframe, since=since, limit=limit)
            if not batch:
                break
            rows += batch
            since = batch[-1][0] + 1
            if len(batch) < limit or (stop and since >= stop):
                break
            time.sleep(ex.rateLimit / 1000)
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
        df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        if stop:
            df = df[df["ts"] < stop]
        df["symbol"] = sym.replace("/", "").replace(":USDT", "")
        df["quote_volume"] = df["volume"] * df["close"]
        frames.append(df.drop(columns=["ts"]))
        if progress:
            progress(f"  {sym}: {len(df)} bars")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fred_series(series_id: str, start: str | None = None) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}" + (f"&cosd={start}" if start else "")
    # FRED stalls some custom User-Agents indefinitely; the library default is served normally
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["timestamp", "value"]
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["symbol"] = series_id
    if start:
        df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
    return df.dropna(subset=["value"]).reset_index(drop=True)
