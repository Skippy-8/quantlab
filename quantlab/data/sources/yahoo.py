"""Daily US equity bars via yfinance (optional dependency: ``pip install quantlab[equities]``).

Prices are split- and dividend-ADJUSTED. That is right for return studies and
wrong for anything that compares a price with an as-traded level (option
strikes, limit prices); use unadjusted closes for those.
"""
from __future__ import annotations

import pandas as pd


def fetch_daily(symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit("yfinance is not installed: pip install 'quantlab[equities]'") from exc
    frames = []
    for sym in symbols:
        h = yf.Ticker(sym).history(start=start, end=end, auto_adjust=True)
        if h.empty:
            continue
        frames.append(pd.DataFrame({
            "symbol": sym, "timestamp": pd.to_datetime(h.index.date).tz_localize("UTC"),
            "open": h["Open"].values, "high": h["High"].values, "low": h["Low"].values,
            "close": h["Close"].values, "volume": h["Volume"].values,
            "quote_volume": (h["Close"] * h["Volume"]).values}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
