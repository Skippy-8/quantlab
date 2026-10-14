"""Synthetic bars for tests, demos and smoke runs.

Random walks with a quoted spread (the close prints at the bid, the mid or the
ask), lognormal volume and an 8-hourly funding rate. Optionally a weak, known
edge can be planted (``drift_after_drop``) so the pipeline can be shown to FIND
a real effect, and the overfitting controls to REJECT the noise around it.
Its P&L means nothing about real markets.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def panel(n_bars: int = 3000, symbols=("AAA", "BBB", "CCC", "DDD"), freq: str = "h", seed: int = 7,
          vol: float = 0.006, drift_after_drop: float = 0.0, start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for k, sym in enumerate(symbols):
        r = rng.normal(0, vol, n_bars)
        if drift_after_drop:
            # a planted mean-reversion edge: after a 2-sigma down bar, the next bar drifts up
            drop = np.r_[False, r[:-1] < -2 * vol]
            r[drop] += drift_after_drop * vol
        mid = 100.0 * (1 + k) * np.exp(np.cumsum(r))
        half = mid * rng.uniform(0.5e-4, 3e-4, n_bars)
        close = mid + half * rng.choice([-1.0, 0.0, 1.0], n_bars)
        opn = np.r_[close[0], close[:-1]]
        wick = np.abs(rng.normal(0, vol / 2, (2, n_bars)))
        ts = pd.date_range(start, periods=n_bars, freq=freq, tz="UTC")
        volume = rng.lognormal(13, 1, n_bars)
        frames.append(pd.DataFrame({
            "symbol": sym, "timestamp": ts, "open": opn,
            "high": np.maximum.reduce([opn, close, mid + half]) * (1 + wick[0]),
            "low": np.minimum.reduce([opn, close, mid - half]) * (1 - wick[1]),
            "close": close, "volume": volume, "quote_volume": volume * close,
            "bbo_bid": mid - half, "bbo_ask": mid + half,
            "funding_rate": np.where(ts.hour % 8 == 0, rng.normal(1e-4, 2e-4, n_bars), 0.0)}))
    return pd.concat(frames, ignore_index=True)
