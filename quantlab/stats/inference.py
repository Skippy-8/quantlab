"""Intervals, t-statistics and robustness checks for backtest results.

Everything is deterministic (fixed seeds), so identical data always yields
identical claims.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SEED = 7


def t_stat(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.size < 3:
        return float("nan")
    sd = x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(x.size))) if sd > 0 else float("nan")


def wilson_ci(wins: int, n: int, z: float = 1.96):
    """(point, lo, hi): Wilson interval for a win rate."""
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - half), min(1.0, center + half)


def bootstrap_mean_ci(values, n_boot: int = 10_000, alpha: float = 0.05, seed: int = SEED):
    """(mean, lo, hi): percentile bootstrap on the mean."""
    v = np.asarray(list(values), float)
    if v.size == 0:
        return None
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, v.size, size=(n_boot, v.size))].mean(axis=1)
    return float(v.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def cluster_diff_t(values, flag, clusters) -> float:
    """t of mean(values | flag) - mean(values | ~flag) with observations clustered
    (e.g. by date): each cluster contributes one difference, so many trades on one
    day count once. Used to ask whether a filter's kept trades beat its dropped ones."""
    d = pd.DataFrame({"v": np.asarray(values, float), "f": np.asarray(flag, bool), "c": np.asarray(clusters)})
    g = d.groupby(["c", "f"]).v.mean().unstack()
    if True not in g.columns or False not in g.columns:
        return float("nan")
    return t_stat((g[True] - g[False]).dropna())


def split_halves(daily: pd.Series) -> dict:
    """The first and second calendar halves. A result whose sign flips between them
    is a regime, not an edge."""
    h = len(daily) // 2
    a, b = daily.iloc[:h], daily.iloc[h:]
    return {"half1_mean": float(a.mean()) if len(a) else float("nan"),
            "half2_mean": float(b.mean()) if len(b) else float("nan"),
            "half1_t": t_stat(a), "half2_t": t_stat(b),
            "same_sign": bool(np.sign(a.mean()) == np.sign(b.mean())) if len(a) and len(b) else False}


def concentration_check(symbols, x, n_boot: int = 5000, drop_top: int = 5, p_min: float = 0.95,
                        seed: int = SEED) -> dict:
    """Is a result more than a handful of symbols?

    Valid under fat tails and for symbols with many trades:
    1. symbol-clustered bootstrap (resample SYMBOLS, each with all its trades):
       P(mean > 0) >= ``p_min``;
    2. the median trade > 0 (the typical trade wins);
    3. the mean with the ``drop_top`` best symbols removed is still > 0.
    """
    d = pd.DataFrame({"symbol": list(symbols), "x": np.asarray(x, float)})
    if len(d) < 3:
        return {"n": len(d), "ok": False}
    by = {s: g.x.to_numpy() for s, g in d.groupby("symbol")}
    names = list(by)
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(names), len(names))
        means[i] = np.concatenate([by[names[j]] for j in pick]).mean()
    sums = d.groupby("symbol").x.sum().sort_values(ascending=False)
    ex = d[~d.symbol.isin(sums.head(drop_top).index)].x
    out = {"n": len(d), "symbols": len(names),
           "p_mean_positive": float((means > 0).mean()),
           "boot_p5_mean": float(np.percentile(means, 5)),
           "median": float(d.x.median()),
           f"mean_ex_top{drop_top}": float(ex.mean()) if len(ex) else None}
    out["ok"] = bool(out["p_mean_positive"] >= p_min and out["median"] > 0
                     and ex.size > 0 and ex.mean() > 0)
    return out
