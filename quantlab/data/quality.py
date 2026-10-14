"""Data-quality checks run before any backtest is trusted.

Each check returns rows of findings; :func:`report` runs them all and grades
each symbol. The classic silent killers:

* **gaps**: missing bars bigger than the series' usual step (a feed outage
  looks like a quiet market to a strategy);
* **duplicates**: two rows for one (symbol, timestamp);
* **bad bars**: high < low, close outside [low, high], non-positive prices;
* **outliers**: one-bar returns beyond ``k`` robust standard deviations (MAD),
  usually bad prints;
* **suspected splits**: a one-bar move close to a common split ratio (1/2, 1/3,
  1/4, 1/10 or their inverses) that does not revert. Unadjusted splits turn
  into fake crashes and fake rallies in a backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SPLIT_RATIOS = (2, 3, 4, 5, 10, 20, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1 / 20)


def gaps(df: pd.DataFrame, tolerance: float = 1.5) -> pd.DataFrame:
    rows = []
    for sym, g in df.groupby("symbol"):
        ts = pd.to_datetime(g["timestamp"], utc=True).sort_values()
        d = ts.diff()
        step = d.median()
        if pd.isna(step) or step <= pd.Timedelta(0):
            continue
        # daily equity bars skip weekends: only flag gaps longer than 4 steps there
        limit = step * (4 if step >= pd.Timedelta("1D") else tolerance)
        for i in np.flatnonzero((d > limit).to_numpy()):
            rows.append({"symbol": sym, "check": "gap", "at": ts.iloc[i - 1],
                         "detail": f"{d.iloc[i] / step:.0f} steps missing until {ts.iloc[i]}"})
    return pd.DataFrame(rows)


def duplicates(df: pd.DataFrame) -> pd.DataFrame:
    dup = df[df.duplicated(["symbol", "timestamp"], keep=False)]
    return pd.DataFrame([{"symbol": s, "check": "duplicate", "at": t, "detail": "repeated timestamp"}
                         for s, t in dup[["symbol", "timestamp"]].drop_duplicates().itertuples(index=False)])


def bad_bars(df: pd.DataFrame) -> pd.DataFrame:
    bad = (df["high"] < df["low"]) | (df["close"] > df["high"] * 1.000001) | (df["close"] < df["low"] * 0.999999) \
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    return pd.DataFrame([{"symbol": r.symbol, "check": "bad_bar", "at": r.timestamp,
                          "detail": f"O {r.open} H {r.high} L {r.low} C {r.close}"} for r in df[bad].itertuples()])


def outliers(df: pd.DataFrame, k: float = 12.0) -> pd.DataFrame:
    rows = []
    for sym, g in df.groupby("symbol"):
        r = np.log(g["close"]).diff()
        mad = (r - r.median()).abs().median() * 1.4826
        if not mad or not np.isfinite(mad):
            continue
        for i in np.flatnonzero((r.abs() > k * mad).to_numpy()):
            rows.append({"symbol": sym, "check": "outlier", "at": g["timestamp"].iloc[i],
                         "detail": f"{np.expm1(r.iloc[i]) * 100:+.1f}% in one bar ({abs(r.iloc[i]) / mad:.0f} robust sd)"})
    return pd.DataFrame(rows)


def suspected_splits(df: pd.DataFrame, tol: float = 0.03) -> pd.DataFrame:
    rows = []
    for sym, g in df.groupby("symbol"):
        c = g["close"].to_numpy(float)
        if len(c) < 3:
            continue
        ratio = c[1:] / c[:-1]
        for i, x in enumerate(ratio):
            hit = next((s for s in SPLIT_RATIOS if abs(x / s - 1) < tol), None)
            if hit is None:
                continue
            after = c[i + 1:i + 6]
            if len(after) and abs(after.mean() / c[i + 1] - 1) < 0.15:     # it stayed there: not a bad print
                rows.append({"symbol": sym, "check": "split?", "at": g["timestamp"].iloc[i + 1],
                             "detail": f"price x{x:.3f} in one bar (looks like a {'1:' + str(round(1 / hit)) if hit < 1 else str(round(hit)) + ':1'} split)"})
    return pd.DataFrame(rows)


def report(df: pd.DataFrame) -> dict:
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    found = [f for f in (gaps(df), duplicates(df), bad_bars(df), outliers(df), suspected_splits(df)) if len(f)] \
        if len(df) else []
    findings = pd.concat(found, ignore_index=True) if found else \
        pd.DataFrame(columns=["symbol", "check", "at", "detail"])
    per = []
    for sym, g in df.groupby("symbol"):
        f = findings[findings["symbol"] == sym] if len(findings) else findings
        counts = f["check"].value_counts().to_dict() if len(f) else {}
        severe = counts.get("bad_bar", 0) + counts.get("duplicate", 0) + counts.get("split?", 0)
        grade = "A" if not counts else "B" if not severe and sum(counts.values()) <= 3 else "C" if not severe else "D"
        per.append({"symbol": sym, "bars": len(g), "first": g["timestamp"].min(), "last": g["timestamp"].max(),
                    "grade": grade, **counts})
    return {"symbols": pd.DataFrame(per), "findings": findings}
