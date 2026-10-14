"""Technical indicators, computed per symbol and strictly causal.

Every function takes the panel (sorted by symbol, then timestamp) and returns a
Series aligned to it. Each one only uses rows at or before the current row, and
never mixes symbols, so anything built from them passes the engine's lookahead
and symbol-leak checks. ``tests/test_indicators.py`` runs that check on every one.

The same functions back the no-code rule language (``quantlab.rules``), where
they are called by name: ``rsi(14) < 30 and close > sma(200)``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _by(df: pd.DataFrame, s: pd.Series):
    return s.groupby(df["symbol"], sort=False)


def _col(df: pd.DataFrame, src) -> pd.Series:
    return df[src] if isinstance(src, str) else src


def _roll(df, src, n, fn):
    return _by(df, _col(df, src)).transform(lambda x: getattr(x.rolling(int(n), min_periods=int(n)), fn)())


def _ewm(df, src, span=None, alpha=None):
    s = _col(df, src)
    return _by(df, s).transform(lambda x: x.ewm(span=span, alpha=alpha, adjust=False,
                                                min_periods=int(span or 1 / alpha)).mean())


# ── moving averages and trend ──────────────────────────────────────────────

def sma(df, n=20, src="close"):
    """Simple moving average."""
    return _roll(df, src, n, "mean")


def ema(df, n=20, src="close"):
    """Exponential moving average (span n)."""
    return _ewm(df, src, span=int(n))


def wma(df, n=20, src="close"):
    """Linearly weighted moving average."""
    w = np.arange(1, int(n) + 1, dtype=float)
    return _by(df, _col(df, src)).transform(
        lambda x: x.rolling(int(n), min_periods=int(n)).apply(lambda v: float(np.dot(v, w) / w.sum()), raw=True))


def hma(df, n=20, src="close"):
    """Hull moving average: WMA(2*WMA(n/2) - WMA(n), sqrt(n))."""
    raw = 2 * wma(df, max(int(n) // 2, 1), src) - wma(df, n, src)
    return wma(df, max(int(np.sqrt(n)), 1), raw)


def macd(df, fast=12, slow=26, src="close"):
    """MACD line: EMA(fast) - EMA(slow)."""
    return ema(df, fast, src) - ema(df, slow, src)


def macd_signal(df, fast=12, slow=26, signal=9, src="close"):
    return _ewm(df, macd(df, fast, slow, src), span=int(signal))


def macd_hist(df, fast=12, slow=26, signal=9, src="close"):
    return macd(df, fast, slow, src) - macd_signal(df, fast, slow, signal, src)


def adx(df, n=14):
    """Average Directional Index (Wilder): trend strength, 0-100."""
    up = _by(df, df["high"]).diff()
    dn = -_by(df, df["low"]).diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = true_range(df)
    a = 1.0 / int(n)
    atr_ = _ewm(df, tr, alpha=a)
    pdi = 100 * _ewm(df, plus, alpha=a) / atr_
    mdi = 100 * _ewm(df, minus, alpha=a) / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return _ewm(df, dx, alpha=a)


def supertrend_dir(df, n=10, mult=3.0):
    """Supertrend direction: +1 in an uptrend, -1 in a downtrend."""
    a = atr(df, n)
    mid = (df["high"] + df["low"]) / 2
    up_b, lo_b = (mid + mult * a).to_numpy(), (mid - mult * a).to_numpy()
    c = df["close"].to_numpy()
    out = np.zeros(len(df))
    for _, idx in df.groupby("symbol", sort=False).indices.items():
        d, fu, fl = 1, np.nan, np.nan
        for k, i in enumerate(idx):
            if np.isnan(up_b[i]):
                out[i] = np.nan
                continue
            pc = c[idx[k - 1]] if k else c[i]
            fu = up_b[i] if np.isnan(fu) or up_b[i] < fu or pc > fu else fu
            fl = lo_b[i] if np.isnan(fl) or lo_b[i] > fl or pc < fl else fl
            d = 1 if c[i] > fu else (-1 if c[i] < fl else d)
            out[i] = d
    return pd.Series(out, index=df.index)


# ── oscillators ────────────────────────────────────────────────────────────

def rsi(df, n=14, src="close"):
    """Relative Strength Index (Wilder smoothing), 0-100."""
    d = _by(df, _col(df, src)).diff()
    a = 1.0 / int(n)
    gain = _ewm(df, d.clip(lower=0), alpha=a)
    loss = _ewm(df, (-d).clip(lower=0), alpha=a)
    out = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    out = out.mask(loss.eq(0) & gain.gt(0), 100.0)          # only gains: 100, not undefined
    return out.mask(loss.eq(0) & gain.eq(0), 50.0)          # no movement at all: neutral


def stoch_k(df, n=14):
    """Stochastic %K: where the close sits in the n-bar range, 0-100."""
    lo, hi = _roll(df, "low", n, "min"), _roll(df, "high", n, "max")
    return 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)


def stoch_d(df, n=14, smooth=3):
    return _roll(df, stoch_k(df, n), smooth, "mean")


def williams_r(df, n=14):
    return stoch_k(df, n) - 100


def cci(df, n=20):
    """Commodity Channel Index."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    m = _roll(df, tp, n, "mean")
    mad = _by(df, tp).transform(lambda x: x.rolling(int(n), min_periods=int(n))
                                .apply(lambda v: np.mean(np.abs(v - v.mean())), raw=True))
    return (tp - m) / (0.015 * mad.replace(0, np.nan))


def roc(df, n=10, src="close"):
    """Rate of change over n bars, as a fraction."""
    s = _col(df, src)
    return s / _by(df, s).shift(int(n)) - 1


def momentum(df, n=10, src="close"):
    return roc(df, n, src)


def zscore(df, n=20, src="close"):
    """Distance from the rolling mean in rolling standard deviations."""
    s = _col(df, src)
    return (s - sma(df, n, s)) / _roll(df, s, n, "std")


# ── volatility and bands ───────────────────────────────────────────────────

def true_range(df):
    pc = _by(df, df["close"]).shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df, n=14):
    """Average True Range (Wilder)."""
    return _ewm(df, true_range(df), alpha=1.0 / int(n))


def natr(df, n=14):
    """ATR as a fraction of the close."""
    return atr(df, n) / df["close"]


def bb_upper(df, n=20, k=2.0, src="close"):
    return sma(df, n, src) + k * _roll(df, src, n, "std")


def bb_lower(df, n=20, k=2.0, src="close"):
    return sma(df, n, src) - k * _roll(df, src, n, "std")


def bb_pct(df, n=20, k=2.0, src="close"):
    """%B: 0 at the lower band, 1 at the upper."""
    lo, hi = bb_lower(df, n, k, src), bb_upper(df, n, k, src)
    return (_col(df, src) - lo) / (hi - lo).replace(0, np.nan)


def keltner_upper(df, n=20, mult=2.0):
    return ema(df, n) + mult * atr(df, n)


def keltner_lower(df, n=20, mult=2.0):
    return ema(df, n) - mult * atr(df, n)


def donchian_high(df, n=20):
    """Highest high of the PRIOR n bars (excludes the current bar, so a close above it is a breakout)."""
    return _by(df, df["high"]).transform(lambda x: x.rolling(int(n), min_periods=int(n)).max().shift(1))


def donchian_low(df, n=20):
    return _by(df, df["low"]).transform(lambda x: x.rolling(int(n), min_periods=int(n)).min().shift(1))


def realized_vol(df, n=24, src="close"):
    """Rolling standard deviation of log returns (per bar)."""
    lr = np.log(_col(df, src)).groupby(df["symbol"], sort=False).diff()
    return _roll(df, lr, n, "std")


# ── volume ─────────────────────────────────────────────────────────────────

def obv(df):
    """On-balance volume."""
    sign = np.sign(_by(df, df["close"]).diff().fillna(0))
    return _by(df, sign * df["volume"]).cumsum()


def vwap(df, n=24):
    """Rolling volume-weighted average price over n bars."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return _roll(df, tp * df["volume"], n, "sum") / _roll(df, "volume", n, "sum")


def volume_z(df, n=48):
    """Volume relative to its rolling mean, in rolling standard deviations."""
    return zscore(df, n, "volume")


def mfi(df, n=14):
    """Money Flow Index, 0-100."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    flow = tp * df["volume"]
    up = _by(df, tp).diff() > 0
    pos = _roll(df, flow.where(up, 0.0), n, "sum")
    neg = _roll(df, flow.where(~up, 0.0), n, "sum")
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


# ── helpers for rules ──────────────────────────────────────────────────────

def lag(df, s, n=1):
    """The value n bars ago (per symbol)."""
    return _by(df, _col(df, s)).shift(int(n))


def highest(df, s, n):
    return _roll(df, s, n, "max")


def lowest(df, s, n):
    return _roll(df, s, n, "min")


REGISTRY = {f.__name__: f for f in (
    sma, ema, wma, hma, macd, macd_signal, macd_hist, adx, supertrend_dir, rsi, stoch_k, stoch_d,
    williams_r, cci, roc, momentum, zscore, true_range, atr, natr, bb_upper, bb_lower, bb_pct,
    keltner_upper, keltner_lower, donchian_high, donchian_low, realized_vol, obv, vwap, volume_z, mfi,
    lag, highest, lowest)}
