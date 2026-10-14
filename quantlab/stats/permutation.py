"""Whole-search permutation nulls.

Testing the best cell of a parameter sweep against a textbook null is wrong:
the best of N noise strategies beats it routinely. The honest null re-runs the
IDENTICAL search on data where the signal cannot know the future, and compares
the best real statistic with the distribution of the best shuffled one.

Shuffle used here: each symbol's signal series is circularly shifted by a
random offset relative to its prices. That keeps the signal's own
autocorrelation, turnover and long/short balance, and keeps the price path, but
breaks any timing relationship between the two.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from quantlab.engine import EngineConfig, eligibility, prepare, run_backtest, signals


@dataclass
class SearchNullResult:
    stat: str
    best_real: float
    best_label: str
    null_best: list[float]
    p_value: float
    real_by_cell: dict


def _stat(res, stat: str) -> float:
    v = res.summary.get(stat)
    return float(v) if v is not None else float("-inf")


def _shift(sig: np.ndarray, sym: np.ndarray, rng, min_shift: int) -> np.ndarray:
    out = sig.copy()
    for s in np.unique(sym):
        idx = np.flatnonzero(sym == s)
        n = idx.size
        if n <= 2 * min_shift:
            continue
        out[idx] = np.roll(sig[idx], int(rng.integers(min_shift, n - min_shift)))
    return out


def search_null(cells: dict[str, Callable[[pd.DataFrame], pd.DataFrame]], df: pd.DataFrame,
                cfg: EngineConfig = EngineConfig(), stat: str = "day_t", n_perm: int = 200,
                min_shift: int = 24, seed: int = 7,
                progress: Callable[[int, int], None] | None = None) -> SearchNullResult:
    """Run every cell of a search, then the same search ``n_perm`` times on shifted signals.

    ``cells`` maps a label to a strategy function (one entry per parameter set).
    The p-value is the share of shuffled searches whose BEST cell is at least as
    good as the best real cell."""
    base = prepare(df, cfg)
    base["eligible"] = eligibility(base, cfg)
    elig = base["eligible"].to_numpy(bool)
    sym = base["symbol"].to_numpy()
    sigs = {k: np.where(elig, signals(fn, base), 0) for k, fn in cells.items()}
    real = {k: _stat(run_backtest(base.assign(signal=s), cfg), stat) for k, s in sigs.items()}
    best_label = max(real, key=real.get)
    rng = np.random.default_rng(seed)
    null = []
    for i in range(n_perm):
        best = float("-inf")
        for s in sigs.values():
            best = max(best, _stat(run_backtest(base.assign(signal=_shift(s, sym, rng, min_shift)), cfg), stat))
        null.append(best)
        if progress:
            progress(i + 1, n_perm)
    arr = np.asarray(null)
    p = float((1 + (arr >= real[best_label]).sum()) / (1 + arr.size))
    return SearchNullResult(stat, real[best_label], best_label, null, p, real)


def grid(fn_factory: Callable[..., Callable], params: Sequence[dict]) -> dict:
    """Build the ``cells`` mapping for :func:`search_null` from a strategy factory."""
    return {",".join(f"{k}={v}" for k, v in p.items()): fn_factory(**p) for p in params}
