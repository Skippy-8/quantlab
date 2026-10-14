"""Event studies and event-driven strategies.

An *event* is (symbol, timestamp) plus any payload: an earnings release, an
insider purchase made public, an exchange listing, a macro print. Two tools:

* :func:`event_study` - the abnormal-return path around every event (market-
  adjusted, or against a market model fitted on a pre-event window), averaged
  with a confidence band, and the cumulative abnormal return (CAR) per event.
  Inference clusters by calendar date, because events on the same day share
  the same market shock and are not independent.
* :func:`event_strategy` - turns events into an engine strategy: enter ``delay``
  bars AFTER the event became public, hold ``hold`` bars. It is causal by
  construction, so it passes the engine's lookahead check.

Timing discipline: the event timestamp must be when the information was PUBLIC
(for SEC filings the EDGAR acceptance time, not the transaction date). A bar is
"after" an event only if it OPENS at or after that time.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _returns_wide(df: pd.DataFrame) -> pd.DataFrame:
    px = df.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last").sort_index()
    return px.pct_change()


def event_study(df: pd.DataFrame, events: pd.DataFrame, pre: int = 5, post: int = 20, model: str = "market",
                market: pd.Series | None = None, estimation: int = 120) -> dict:
    """``events``: columns symbol, timestamp. ``model``: 'raw', 'market' (minus the market return)
    or 'market_model' (alpha + beta fitted on the ``estimation`` bars before the window).
    The market defaults to the equal-weighted average of all symbols in ``df``."""
    rets = _returns_wide(df)
    mkt = market.reindex(rets.index) if market is not None else rets.mean(axis=1)
    idx = rets.index
    paths, rows = [], []
    for ev in events.itertuples(index=False):
        sym, ts = ev.symbol, pd.Timestamp(ev.timestamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        if sym not in rets.columns:
            continue
        k = idx.searchsorted(ts)                       # first bar at or after the event
        if k - pre < 1 or k + post >= len(idx):
            continue
        r = rets[sym].iloc[k - pre:k + post + 1].to_numpy()
        m = mkt.iloc[k - pre:k + post + 1].to_numpy()
        if model == "raw":
            ar = r
        elif model == "market":
            ar = r - m
        else:
            lo = max(1, k - pre - estimation)
            er, em = rets[sym].iloc[lo:k - pre].to_numpy(), mkt.iloc[lo:k - pre].to_numpy()
            ok = np.isfinite(er) & np.isfinite(em)
            if ok.sum() < 30:
                continue
            beta, alpha = np.polyfit(em[ok], er[ok], 1)
            ar = r - (alpha + beta * m)
        if not np.isfinite(ar).all():
            continue
        paths.append(ar)
        rows.append({"symbol": sym, "timestamp": ts, "event_bar": idx[k], "car_pre": float(ar[:pre].sum()),
                     "car_post": float(ar[pre:].sum()), "day0": float(ar[pre])})
    if not paths:
        return {"events": 0}
    A = np.vstack(paths)
    car = A.cumsum(axis=1)
    rel = np.arange(-pre, post + 1)
    mean_car = car.mean(axis=0)
    se = car.std(axis=0, ddof=1) / math.sqrt(len(car))
    per = pd.DataFrame(rows)
    by_date = per.groupby(per["event_bar"].dt.floor("D"))["car_post"].mean()
    t_clustered = float(by_date.mean() / (by_date.std(ddof=1) / math.sqrt(len(by_date)))) \
        if len(by_date) > 2 and by_date.std(ddof=1) > 0 else float("nan")
    return {"events": len(per), "event_dates": int(len(by_date)), "model": model,
            "path": pd.DataFrame({"bar": rel, "mean_car": mean_car, "lo": mean_car - 1.96 * se,
                                  "hi": mean_car + 1.96 * se}),
            "per_event": per, "mean_car_post": float(per["car_post"].mean()),
            "median_car_post": float(per["car_post"].median()),
            "positive_share": float((per["car_post"] > 0).mean()), "t_date_clustered": t_clustered}


def event_strategy(events: pd.DataFrame, side: int = 1, hold: int = 5, delay: int = 0):
    """An engine strategy: ``side`` (+1 long / -1 short) starting ``delay`` bars after the first
    bar that opens at or after each event, held for ``hold`` bars. Overlapping events extend the hold."""
    ev = events[["symbol", "timestamp"]].copy()
    ev["timestamp"] = pd.to_datetime(ev["timestamp"], utc=True)
    by_sym = {s: np.sort(g["timestamp"].to_numpy()) for s, g in ev.groupby("symbol")}

    def fn(df: pd.DataFrame) -> pd.DataFrame:
        out = np.zeros(len(df), dtype=int)
        for sym, idx in df.groupby("symbol", sort=False).indices.items():
            times = by_sym.get(sym)
            if times is None:
                continue
            ts = df["timestamp"].to_numpy()[idx]
            start = np.searchsorted(ts, times) + delay
            for s0 in start:
                if s0 < len(idx):
                    out[idx[s0:min(s0 + hold, len(idx))]] = side
        return df.assign(signal=out)
    return fn


def insider_purchases(store, min_value: float = 0.0, officers_only: bool = False) -> pd.DataFrame:
    """Events from the SEC insider store: one row per insider purchase, timed at EDGAR acceptance."""
    p = store.purchases()
    if officers_only:
        p = p[p["officer"]]
    p = p[p["value_usd"].fillna(0) >= min_value]
    return p.rename(columns={"ticker": "symbol", "public_at": "timestamp"})[["symbol", "timestamp", "owner_name",
                                                                              "value_usd", "officer"]]


def earnings_dates(symbols: list[str]) -> pd.DataFrame:
    """Past earnings announcement times from yfinance (needs ``quantlab[equities]``)."""
    import yfinance as yf
    rows = []
    for s in symbols:
        try:
            ed = yf.Ticker(s).get_earnings_dates(limit=60)
        except Exception:
            continue
        if ed is None or ed.empty:
            continue
        for t, r in ed.iterrows():
            rows.append({"symbol": s, "timestamp": pd.Timestamp(t).tz_convert("UTC"),
                         "eps_estimate": r.get("EPS Estimate"), "eps_actual": r.get("Reported EPS")})
    return pd.DataFrame(rows)
