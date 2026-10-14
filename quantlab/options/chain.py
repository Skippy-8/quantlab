"""Option-chain data: the standard frame, a synthetic generator, and a ThetaData loader.

Standard chain frame (one row per contract per date)::

    date (UTC midnight) | underlying | expiry | strike | right ('C'/'P') | bid | ask [| iv]

``underlying`` is the spot on that date. When a source lacks it, :func:`implied_spot`
recovers it from put-call parity on the nearest expiry, which also sidesteps split-
and dividend-adjusted stock histories that no longer match as-traded strikes.
"""
from __future__ import annotations

import io
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from quantlab.options import pricing as P

COLUMNS = ["date", "underlying", "expiry", "strike", "right", "bid", "ask"]


def synthetic(spot0: float = 100.0, days: int = 260, vol: float = 0.25, seed: int = 7, start: str = "2024-01-02",
              skew: float = 0.6, term: float = 0.04, event_days: tuple[int, ...] = (), event_iv: float = 0.35,
              n_expiries: int = 8, strike_range: float = 0.35, strike_step: float = 0.025) -> pd.DataFrame:
    """A business-day chain over a GBM underlying with a volatility smile, a term
    structure, weekly Friday expiries and realistic spreads. ``event_days`` (indices)
    add an implied-vol bump before them and a jump on the day, for event studies."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days, tz="UTC")
    r = rng.normal(0, vol / np.sqrt(252), days)
    for d in event_days:
        if 0 < d < days:
            r[d] += rng.choice([-1, 1]) * rng.uniform(0.03, 0.08)
    spot = spot0 * np.exp(np.cumsum(r))
    fridays = pd.date_range(dates[0], dates[-1] + pd.Timedelta(days=120), freq="W-FRI")
    rows = []
    for i, (d, s) in enumerate(zip(dates, spot, strict=True)):
        exps = [e for e in fridays if e > d][:n_expiries]
        strikes = np.round(np.arange(s * (1 - strike_range), s * (1 + strike_range), s * strike_step), 0)
        strikes = np.unique(strikes[strikes > 0])
        bump = 0.0
        nxt = [e for e in event_days if e >= i]
        for e in exps:
            t = max((e - d).days, 1) / 365
            for k in strikes:
                m = np.log(k / s)
                iv = vol * (1 + skew * max(-m, 0) * 2 + 0.3 * m * m * 10) + term * np.sqrt(t)
                if nxt and dates[min(nxt[0], days - 1)] <= e:
                    bump = event_iv * np.sqrt(1 / 365 / t) * 0.6
                rows.append((d, s, e, k, iv + bump, t))
    df = pd.DataFrame(rows, columns=["date", "underlying", "expiry", "strike", "iv", "t"])
    out = []
    for right in ("C", "P"):
        px = P.price(df["underlying"], df["strike"], df["t"], df["iv"], right == "C")
        half = np.maximum(0.025, 0.04 * px)
        out.append(df.assign(right=right, bid=np.maximum(np.round(px - half, 2), 0.0), ask=np.round(px + half, 2),
                             mid_theory=px))
    chain = pd.concat(out, ignore_index=True).drop(columns=["t"])
    return chain[chain["ask"] > 0.01].sort_values(["date", "expiry", "strike", "right"]).reset_index(drop=True)


def implied_spot(day: pd.DataFrame) -> float:
    """Spot from put-call parity at the strike where |C_mid - P_mid| is smallest, nearest expiry."""
    e = day[day["expiry"] == day["expiry"].min()]
    c = e[e["right"] == "C"].set_index("strike")
    p = e[e["right"] == "P"].set_index("strike")
    k = c.index.intersection(p.index)
    if not len(k):
        return float("nan")
    d = ((c.loc[k, "bid"] + c.loc[k, "ask"]) / 2) - ((p.loc[k, "bid"] + p.loc[k, "ask"]) / 2)
    ks = float(d.abs().idxmin())
    return ks + float(d.loc[ks])


def standardize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.floor("D")
    out["expiry"] = pd.to_datetime(out["expiry"], utc=True).dt.floor("D")
    out["right"] = out["right"].astype(str).str.upper().str[0]
    if "underlying" not in out:
        spot = {d: implied_spot(g) for d, g in out.groupby("date")}
        out["underlying"] = out["date"].map(spot)
    return out


def thetadata_eod(symbol: str, start: str, end: str, host: str = "http://127.0.0.1:25503",
                  max_dte: int = 75) -> pd.DataFrame:
    """End-of-day quotes for every strike and expiry from a running Theta Terminal (free tier:
    history from 2023-06, closing NBBO). Requires a ThetaData account and the local terminal."""
    q = urllib.parse.urlencode({"symbol": symbol, "expiration": "*", "start_date": pd.Timestamp(start).strftime("%Y%m%d"),
                                "end_date": pd.Timestamp(end).strftime("%Y%m%d"), "max_dte": max_dte, "format": "csv"})
    with urllib.request.urlopen(f"{host}/v3/option/history/eod?{q}", timeout=300) as r:
        raw = pd.read_csv(io.StringIO(r.read().decode()))
    df = pd.DataFrame({"date": raw["created"].astype(str).str[:10], "expiry": raw["expiration"],
                       "strike": raw["strike"].astype(float), "right": raw["right"], "bid": raw["bid"].astype(float),
                       "ask": raw["ask"].astype(float)})
    df = df[(df["ask"] > 0) & (df["ask"] >= df["bid"])]
    return standardize(df)
