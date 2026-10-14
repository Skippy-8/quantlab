"""Out-of-sample validation and data-snooping tests.

* :func:`walk_forward` - re-optimise on a rolling training window, trade the
  choice on the following unseen window, stitch the unseen windows together.
* :func:`pbo` - the Probability of Backtest Overfitting (Bailey, Borwein, Lopez
  de Prado & Zhu, 2017) by combinatorially symmetric cross-validation (CSCV):
  how often the in-sample winner ranks below the median out of sample.
* :func:`monte_carlo` - resample trades or blocks of days to get the
  distribution of drawdowns, final returns and the chance of losing money,
  instead of the single path history happened to deliver.
* :func:`reality_check` - White's (2000) Reality Check and Hansen's (2005) SPA
  test: is the best of a whole set of strategies better than zero, after
  accounting for having searched the set? Stationary bootstrap (Politis &
  Romano, 1994) keeps the returns' serial dependence.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from quantlab import fast
from quantlab.engine import EngineConfig, evaluate, prepare

# ── walk-forward ───────────────────────────────────────────────────────────

@dataclass
class WalkForwardResult:
    folds: pd.DataFrame
    oos_daily: pd.Series
    stats: dict


def walk_forward(factory: Callable[..., Callable], grid: list[dict], df: pd.DataFrame, train_days: int = 90,
                 test_days: int = 30, objective: str = "calendar_sharpe", cost_bp: float = 5.0,
                 cfg: EngineConfig = EngineConfig(), anchored: bool = False,
                 progress: Callable[[int, int], None] | None = None) -> WalkForwardResult:
    """Rolling (or anchored) walk-forward. Each fold chooses the grid point with the best
    in-sample ``objective`` in FAST mode, then scores it with the FULL engine on the next
    ``test_days``, using the training window as indicator warm-up only."""
    d = prepare(df, cfg)
    t0, t1 = d["timestamp"].min().floor("D"), d["timestamp"].max().floor("D")
    starts = []
    s = t0 + pd.Timedelta(days=train_days)
    while s + pd.Timedelta(days=test_days) <= t1 + pd.Timedelta(days=1):
        starts.append(s)
        s += pd.Timedelta(days=test_days)
    rows, oos = [], []
    for k, test_start in enumerate(starts):
        train_start = t0 if anchored else test_start - pd.Timedelta(days=train_days)
        test_end = test_start + pd.Timedelta(days=test_days)
        train = d[(d["timestamp"] >= train_start) & (d["timestamp"] < test_start)]
        best, best_v = None, -np.inf
        for p in grid:
            v = fast.run(factory(**p), train, cost_bp, cfg.days_per_year, prepared=True).stats.get(objective, np.nan)
            if np.isfinite(v) and v > best_v:
                best, best_v = p, v
        if best is None:
            continue
        window = d[(d["timestamp"] >= train_start) & (d["timestamp"] < test_end)]
        res = evaluate(factory(**best), window, cfg, score_from=test_start, score_to=test_end, check=False)
        day = res.daily[(res.daily.index >= test_start) & (res.daily.index < test_end)]
        oos.append(day)
        rows.append({"fold": k + 1, "train_start": train_start.date(), "test_start": test_start.date(),
                     "test_end": test_end.date(), "chosen": best, f"is_{objective}": best_v,
                     "oos_sum_bp": float(day.sum()), "oos_trades": res.summary["trades"]})
        if progress:
            progress(k + 1, len(starts))
    stitched = pd.concat(oos).groupby(level=0).sum().sort_index() if oos else pd.Series(dtype=float)
    folds = pd.DataFrame(rows)
    sd = stitched.std(ddof=1) if len(stitched) > 1 else float("nan")
    traded = stitched[stitched != 0]
    st = {"folds": int(len(folds)),
          "oos_sharpe": float(stitched.mean() / sd * math.sqrt(cfg.days_per_year)) if sd and sd > 0 else float("nan"),
          "oos_day_t": float(traded.mean() / (traded.std(ddof=1) / math.sqrt(len(traded))))
          if len(traded) > 2 and traded.std(ddof=1) > 0 else float("nan"),
          "oos_sum_bp": float(stitched.sum()),
          "positive_folds": float((folds["oos_sum_bp"] > 0).mean()) if len(folds) else float("nan"),
          "distinct_choices": int(folds["chosen"].astype(str).nunique()) if len(folds) else 0}
    return WalkForwardResult(folds, stitched, st)


# ── probability of backtest overfitting (CSCV) ─────────────────────────────

def pbo(daily: pd.DataFrame, n_blocks: int = 10, periods: int = 365) -> dict:
    """``daily``: day x configuration matrix of returns (e.g. from :func:`quantlab.fast.sweep`).

    Split the days into ``n_blocks`` contiguous blocks; for every way of choosing half
    of them as in-sample, pick the configuration with the best in-sample Sharpe and
    record its out-of-sample rank. PBO = share of splits where that rank is below the
    median, i.e. the in-sample winner is an out-of-sample loser."""
    if daily.shape[1] < 2:
        raise ValueError("PBO needs at least two configurations")
    n_blocks -= n_blocks % 2
    blocks = np.array_split(np.arange(len(daily)), n_blocks)
    X = daily.to_numpy(float)

    def sharpe(rows):
        m, s = X[rows].mean(0), X[rows].std(0, ddof=1)
        return np.where(s > 0, m / s * math.sqrt(periods), -np.inf)

    logits, degr = [], []
    for combo in itertools.combinations(range(n_blocks), n_blocks // 2):
        is_rows = np.concatenate([blocks[i] for i in combo])
        oos_rows = np.concatenate([blocks[i] for i in range(n_blocks) if i not in combo])
        s_is, s_oos = sharpe(is_rows), sharpe(oos_rows)
        best = int(np.argmax(s_is))
        rank = (s_oos < s_oos[best]).sum() + 0.5 * ((s_oos == s_oos[best]).sum() - 1)
        w = (rank + 1) / (X.shape[1] + 1)
        logits.append(math.log(w / (1 - w)))
        degr.append((s_is[best], s_oos[best]))
    lg = np.array(logits)
    d = np.array(degr)
    slope = float(np.polyfit(d[:, 0], d[:, 1], 1)[0]) if len(d) > 2 and np.ptp(d[:, 0]) > 0 else float("nan")
    return {"pbo": float((lg <= 0).mean()), "splits": len(lg), "configs": X.shape[1],
            "median_logit": float(np.median(lg)), "is_vs_oos_slope": slope,
            "mean_is_sharpe_of_winner": float(d[:, 0].mean()), "mean_oos_sharpe_of_winner": float(d[:, 1].mean()),
            "logits": lg.tolist()}


# ── Monte Carlo ────────────────────────────────────────────────────────────

def _max_dd(eq: np.ndarray) -> float:
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min())


def monte_carlo(returns: pd.Series, n: int = 2000, method: str = "block", block: int = 10, seed: int = 7) -> dict:
    """Resample a return series ``n`` times.

    ``method="shuffle"`` reorders the observations (for per-trade returns: same trades, different
    luck in their order); ``"block"`` resamples contiguous blocks (for daily returns, keeping
    short-term serial dependence). Returns percentiles of final return and max drawdown and the
    probability of a loss."""
    r = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(float)
    if r.size < 5:
        return {}
    rng = np.random.default_rng(seed)
    finals, dds = np.empty(n), np.empty(n)
    for i in range(n):
        if method == "shuffle":
            x = rng.permutation(r)
        else:
            starts = rng.integers(0, r.size, int(math.ceil(r.size / block)))
            x = np.concatenate([np.take(r, np.arange(s, s + block), mode="wrap") for s in starts])[:r.size]
        eq = np.cumprod(1 + x)
        finals[i], dds[i] = eq[-1] - 1, _max_dd(np.r_[1.0, eq])
    pct = lambda a, q: float(np.percentile(a, q))  # noqa: E731
    actual = np.cumprod(1 + r)
    return {"n": n, "method": method, "actual_final": float(actual[-1] - 1), "actual_max_dd": _max_dd(np.r_[1.0, actual]),
            "final_p5": pct(finals, 5), "final_p50": pct(finals, 50), "final_p95": pct(finals, 95),
            "max_dd_p50": pct(dds, 50), "max_dd_p95": pct(dds, 5), "max_dd_p99": pct(dds, 1),
            "prob_loss": float((finals < 0).mean()), "finals": finals.tolist(), "max_dds": dds.tolist()}


# ── White's Reality Check and Hansen's SPA ─────────────────────────────────

def stationary_bootstrap_indices(t: int, n: int, mean_block: float, rng) -> np.ndarray:
    """Politis-Romano stationary bootstrap: ``n`` index paths of length ``t``."""
    p = 1.0 / mean_block
    idx = np.empty((n, t), dtype=int)
    idx[:, 0] = rng.integers(0, t, n)
    new = rng.random((n, t)) < p
    jumps = rng.integers(0, t, (n, t))
    for j in range(1, t):
        idx[:, j] = np.where(new[:, j], jumps[:, j], (idx[:, j - 1] + 1) % t)
    return idx


def reality_check(daily: pd.DataFrame, benchmark: pd.Series | None = None, n_boot: int = 1000,
                  mean_block: float = 10.0, seed: int = 7) -> dict:
    """Is the best strategy in ``daily`` (day x strategy) better than the benchmark (default: zero),
    after accounting for the search? Returns White's RC p-value and Hansen's SPA (consistent) p-value."""
    X = daily.to_numpy(float)
    if benchmark is not None:
        X = X - benchmark.reindex(daily.index).fillna(0).to_numpy(float)[:, None]
    t, k = X.shape
    mu = X.mean(0)
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_indices(t, n_boot, mean_block, rng)
    boot_mu = np.stack([X[i].mean(0) for i in idx])                  # n_boot x k
    v_rc = math.sqrt(t) * mu.max()
    v_rc_boot = math.sqrt(t) * (boot_mu - mu).max(axis=1)
    sd = np.sqrt(t) * boot_mu.std(0, ddof=1)
    sd = np.where(sd > 0, sd, np.inf)
    # SPA: studentise, and drop clearly-bad strategies from the null (Hansen's consistent version)
    thresh = -np.sqrt(2 * math.log(math.log(t))) * sd / math.sqrt(t)
    mu_c = np.where(mu >= thresh, 0.0, mu)
    t_spa = max(float((math.sqrt(t) * mu / sd).max()), 0.0)
    t_spa_boot = np.maximum((math.sqrt(t) * (boot_mu - mu + mu_c) / sd).max(axis=1), 0.0)
    best = int(np.argmax(mu))
    return {"strategies": k, "days": t, "best": str(daily.columns[best]), "best_mean": float(mu[best]),
            "reality_check_p": float((v_rc_boot >= v_rc).mean()), "spa_p": float((t_spa_boot >= t_spa).mean())}
