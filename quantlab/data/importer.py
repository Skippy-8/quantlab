"""Bring your own data: CSV / Parquet files with whatever column names they came with.

``load_file`` reads the file and ``standardize`` maps its columns onto the lake
schema (symbol, timestamp, open, high, low, close, volume, ...). Common aliases
are recognised (``Date``, ``datetime``, ``time``, ``Adj Close``, ``vol`` ...);
anything else can be mapped explicitly. Epoch seconds / milliseconds and naive
or zoned date strings are all handled; times are stored in UTC.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

ALIASES = {
    "timestamp": ["timestamp", "time", "date", "datetime", "date_time", "open_time", "ts", "ts_ms", "t"],
    "symbol": ["symbol", "ticker", "asset", "instrument", "pair", "coin", "sym"],
    "open": ["open", "o", "open_price"],
    "high": ["high", "h", "high_price"],
    "low": ["low", "l", "low_price"],
    "close": ["close", "c", "close_price", "last", "price", "adj_close", "adj close", "adjclose"],
    "volume": ["volume", "vol", "v", "base_volume", "qty"],
    "quote_volume": ["quote_volume", "quote_asset_volume", "turnover", "notional", "dollar_volume"],
    "bbo_bid": ["bid", "bbo_bid", "best_bid"],
    "bbo_ask": ["ask", "bbo_ask", "best_ask"],
    "funding_rate": ["funding_rate", "funding", "fundingrate"],
}


def load_file(path_or_buffer, name: str | None = None) -> pd.DataFrame:
    name = name or (str(path_or_buffer) if isinstance(path_or_buffer, (str, Path)) else "upload.csv")
    if name.lower().endswith((".parquet", ".pq")):
        return pd.read_parquet(path_or_buffer)
    if isinstance(path_or_buffer, (bytes, bytearray)):
        path_or_buffer = io.BytesIO(path_or_buffer)
    return pd.read_csv(path_or_buffer, sep=None, engine="python")


def guess_mapping(columns) -> dict[str, str]:
    norm = {str(c).strip().lower().replace("-", "_"): c for c in columns}
    out = {}
    for target, names in ALIASES.items():
        for n in names:
            if n in norm and norm[n] not in out.values():
                out[target] = norm[n]
                break
    if "close" in out and str(out["close"]).lower().replace(" ", "") in ("adjclose", "adj_close"):
        pass                                              # adjusted closes preferred when present
    return out


def _to_utc(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        v = pd.to_numeric(s)
        unit = "us" if v.max() > 1e14 else "ms" if v.max() > 1e11 else "s"
        return pd.to_datetime(v, unit=unit, utc=True)
    t = pd.to_datetime(s, utc=False, format="mixed")
    return t.dt.tz_localize("UTC") if t.dt.tz is None else t.dt.tz_convert("UTC")


def standardize(df: pd.DataFrame, mapping: dict | None = None, symbol: str | None = None) -> pd.DataFrame:
    """Rename to the lake schema, parse times to UTC, coerce numbers, fill OHLC from close if absent."""
    m = {**guess_mapping(df.columns), **(mapping or {})}
    if "timestamp" not in m or "close" not in m:
        raise ValueError(f"could not find a time and a close/price column in {list(df.columns)}; "
                         "pass mapping={'timestamp': ..., 'close': ...}")
    out = pd.DataFrame({k: df[v] for k, v in m.items() if v in df.columns})
    out["timestamp"] = _to_utc(out["timestamp"])
    if "symbol" not in out:
        out["symbol"] = symbol or "ASSET"
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    for c in [c for c in out.columns if c not in ("timestamp", "symbol")]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ("open", "high", "low"):
        if c not in out:
            out[c] = out["close"]
    if "volume" not in out:
        out["volume"] = 0.0
    out = out.dropna(subset=["close"]).sort_values(["symbol", "timestamp"])
    return out.drop_duplicates(["symbol", "timestamp"], keep="last").reset_index(drop=True)
