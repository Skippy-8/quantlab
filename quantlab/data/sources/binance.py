"""Binance public market-data archive (https://data.binance.vision).

Monthly zip files of klines (spot or USD-M futures) and of futures funding
rates. No API key, no account: the archive is public. Files are downloaded,
parsed and returned as tidy frames; nothing is redistributed by this repo.

Survivorship: the archive keeps DELISTED symbols, so a universe assembled from
it point in time includes the coins that went to zero, which a "current
listings" universe silently drops.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import requests

BASE = "https://data.binance.vision/data"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "trades", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
UA = {"User-Agent": "quantlab-research/0.1"}


def months(start: str, end: str) -> list[str]:
    """'2023-01'..'2023-03' -> ['2023-01', '2023-02', '2023-03'] (inclusive)."""
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def _get_zip(url: str, session: requests.Session | None = None) -> bytes | None:
    s = session or requests
    r = s.get(url, headers=UA, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def parse_klines_zip(blob: bytes, symbol: str) -> pd.DataFrame:
    """One monthly kline zip -> frame. Newer files carry a header row, older ones do not."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode()
    first = raw.split("\n", 1)[0]
    header = 0 if first and not first[0].isdigit() else None
    df = pd.read_csv(io.StringIO(raw), header=header, names=None if header == 0 else KLINE_COLS)
    df.columns = KLINE_COLS[:len(df.columns)]
    t = pd.to_numeric(df["open_time"])
    unit = "us" if t.max() > 1e14 else "ms"           # spot switched to microseconds in 2025
    out = pd.DataFrame({"symbol": symbol, "timestamp": pd.to_datetime(t, unit=unit, utc=True)})
    for c in ("open", "high", "low", "close", "volume", "quote_volume"):
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    return out


def parse_funding_zip(blob: bytes, symbol: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode()
    df = pd.read_csv(io.StringIO(raw))
    tcol = next(c for c in df.columns if "time" in c.lower())
    rcol = next(c for c in df.columns if "rate" in c.lower())
    return pd.DataFrame({"symbol": symbol,
                         "timestamp": pd.to_datetime(pd.to_numeric(df[tcol]), unit="ms", utc=True).dt.floor("h"),
                         "funding_rate": pd.to_numeric(df[rcol], errors="coerce")})


def fetch_klines(symbols: list[str], start: str, end: str, interval: str = "1h", market: str = "futures/um",
                 progress=print) -> pd.DataFrame:
    """Klines for each symbol and month. Missing months (not yet listed, delisted) are skipped."""
    sess, frames = requests.Session(), []
    for sym in symbols:
        for m in months(start, end):
            url = f"{BASE}/{market}/monthly/klines/{sym}/{interval}/{sym}-{interval}-{m}.zip"
            blob = _get_zip(url, sess)
            if blob is None:
                continue
            frames.append(parse_klines_zip(blob, sym))
        if progress:
            progress(f"  {sym}: {sum(len(f) for f in frames if f['symbol'].iat[0] == sym)} bars")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_funding(symbols: list[str], start: str, end: str, progress=print) -> pd.DataFrame:
    sess, frames = requests.Session(), []
    for sym in symbols:
        for m in months(start, end):
            url = f"{BASE}/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip"
            blob = _get_zip(url, sess)
            if blob is not None:
                frames.append(parse_funding_zip(blob, sym))
        if progress:
            progress(f"  {sym}: funding fetched")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def attach_funding(klines: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """Add a ``funding_rate`` column: the rate settled at each bar's open (0 elsewhere)."""
    if funding.empty:
        return klines.assign(funding_rate=0.0)
    f = funding.groupby(["symbol", "timestamp"], as_index=False)["funding_rate"].sum()
    out = klines.drop(columns=["funding_rate"], errors="ignore").merge(f, on=["symbol", "timestamp"], how="left")
    out["funding_rate"] = out["funding_rate"].fillna(0.0)
    return out


def this_month() -> str:
    return date.today().strftime("%Y-%m")
