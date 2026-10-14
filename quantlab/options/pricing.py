"""Black-Scholes(-Merton) prices, greeks and implied volatility (vectorized, numpy only)."""
from __future__ import annotations

import math

import numpy as np

_SQRT2 = math.sqrt(2.0)


def _ncdf(x):
    from math import erf
    return 0.5 * (1.0 + np.vectorize(erf)(np.asarray(x, float) / _SQRT2))


def _npdf(x):
    x = np.asarray(x, float)
    return np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _d1d2(s, k, t, vol, r=0.0, q=0.0):
    s, k, t, vol = (np.asarray(a, float) for a in (s, k, t, vol))
    vt = vol * np.sqrt(np.maximum(t, 1e-12))
    d1 = (np.log(s / k) + (r - q + 0.5 * vol * vol) * t) / np.where(vt > 0, vt, np.nan)
    return d1, d1 - vt


def price(s, k, t, vol, is_call, r=0.0, q=0.0):
    s, k, t, vol, is_call = (np.asarray(a) for a in (s, k, t, vol, is_call))
    intrinsic = np.where(is_call, np.maximum(s - k, 0.0), np.maximum(k - s, 0.0))
    d1, d2 = _d1d2(s, k, t, vol, r, q)
    disc_q, disc_r = np.exp(-q * t), np.exp(-r * t)
    call = s * disc_q * _ncdf(d1) - k * disc_r * _ncdf(d2)
    put = k * disc_r * _ncdf(-d2) - s * disc_q * _ncdf(-d1)
    out = np.where(is_call, call, put)
    return np.where((t <= 0) | (vol <= 0) | ~np.isfinite(out), intrinsic, out)


def delta(s, k, t, vol, is_call, r=0.0, q=0.0):
    d1, _ = _d1d2(s, k, t, vol, r, q)
    dq = np.exp(-q * np.asarray(t, float))
    return np.where(is_call, dq * _ncdf(d1), dq * (_ncdf(d1) - 1))


def gamma(s, k, t, vol, r=0.0, q=0.0):
    d1, _ = _d1d2(s, k, t, vol, r, q)
    return np.exp(-q * np.asarray(t, float)) * _npdf(d1) / (np.asarray(s, float) * np.asarray(vol, float) * np.sqrt(t))


def vega(s, k, t, vol, r=0.0, q=0.0):
    """Price change per 1.00 change in vol (divide by 100 for per vol point)."""
    d1, _ = _d1d2(s, k, t, vol, r, q)
    return np.asarray(s, float) * np.exp(-q * np.asarray(t, float)) * _npdf(d1) * np.sqrt(t)


def theta(s, k, t, vol, is_call, r=0.0, q=0.0):
    """Price change per YEAR of time decay (divide by 365 for per day)."""
    s, k, t, vol = (np.asarray(a, float) for a in (s, k, t, vol))
    d1, d2 = _d1d2(s, k, t, vol, r, q)
    common = -s * np.exp(-q * t) * _npdf(d1) * vol / (2 * np.sqrt(t))
    call = common - r * k * np.exp(-r * t) * _ncdf(d2) + q * s * np.exp(-q * t) * _ncdf(d1)
    put = common + r * k * np.exp(-r * t) * _ncdf(-d2) - q * s * np.exp(-q * t) * _ncdf(-d1)
    return np.where(is_call, call, put)


def implied_vol(px, s, k, t, is_call, r=0.0, q=0.0, lo=1e-4, hi=5.0, iters=60):
    """Vectorized bisection. NaN where the price is outside the no-arbitrage bounds."""
    px, s, k, t, is_call = (np.asarray(a) for a in (px, s, k, t, is_call))
    a, b = np.full(np.shape(px), lo, float), np.full(np.shape(px), hi, float)
    p_lo, p_hi = price(s, k, t, a, is_call, r, q), price(s, k, t, b, is_call, r, q)
    ok = (px > p_lo) & (px < p_hi) & (t > 0)
    for _ in range(iters):
        m = 0.5 * (a + b)
        pm = price(s, k, t, m, is_call, r, q)
        a = np.where(pm < px, m, a)
        b = np.where(pm >= px, m, b)
    return np.where(ok, 0.5 * (a + b), np.nan)
