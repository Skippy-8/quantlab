"""Vectorized fast mode: thousands of parameter cells in seconds.

The fill simulator is exact but walks bar by bar. For SEARCHING (sweeps,
walk-forward optimisation, cross-validation) an approximation is enough as
long as it is conservative and consistent:

* the position held over bar t is the signal at the close of bar t-1
  (it trades at the next close: no same-bar execution);
* P&L per bar = position * close-to-close return - |change in position| * cost,
  where ``cost_bp`` per side should cover fees plus half the spread;
* funding is charged when the frame carries ``funding_rate``.

The result is a per-bar, per-symbol P&L matrix in bp of one unit, so it is on
the same scale as the full engine. Use fast mode to choose; confirm the choice
with :func:`quantlab.engine.evaluate`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab.engine import prepare, signals


@dataclass
class FastResult:
    bars: pd.DataFrame          # timestamp x symbol, bp per bar
    daily: pd.Series            # calendar-day sum across symbols (bp)
    stats: dict


def _stats(daily: pd.Series, days_per_year: int, turnover: float) -> dict:
    traded = daily[daily != 0]
    sd_t, sd = traded.std(ddof=1), daily.std(ddof=1)
    return {"day_t": float(traded.mean() / (sd_t / math.sqrt(len(traded)))) if len(traded) > 2 and sd_t > 0 else float("nan"),
            "calendar_sharpe": float(daily.mean() / sd * math.sqrt(days_per_year)) if sd > 0 else float("nan"),
            "sum_bp": float(daily.sum()), "mean_day_bp": float(daily.mean()), "turnover": turnover}


def run(fn, df: pd.DataFrame, cost_bp: float = 5.0, days_per_year: int = 365, prepared: bool = False,
        sig: np.ndarray | None = None) -> FastResult:
    d = df if prepared else prepare(df)
    s = signals(fn, d) if sig is None else sig
    sym = d["symbol"].to_numpy()
    close = d["close"].to_numpy(float)
    new = np.r_[True, sym[1:] != sym[:-1]]                      # first row of each symbol
    ret = np.where(new, 0.0, close / np.r_[close[0], close[:-1]] - 1)
    held = np.where(new, 0, np.r_[0, s[:-1]])                   # position over this bar = previous signal
    prev_held = np.where(new, 0, np.r_[0, held[:-1]])
    trade = np.abs(held - prev_held)
    pnl = held * ret * 1e4 - trade * cost_bp
    if "funding_rate" in d.columns:
        pnl -= held * d["funding_rate"].fillna(0).to_numpy(float) * 1e4
    frame = pd.DataFrame({"timestamp": d["timestamp"], "symbol": sym, "pnl": pnl})
    bars = frame.pivot_table(index="timestamp", columns="symbol", values="pnl", aggfunc="sum").fillna(0.0)
    tot = bars.sum(axis=1)
    days = pd.date_range(tot.index.min().floor("D"), tot.index.max().floor("D"), freq="D")
    daily = tot.groupby(tot.index.floor("D")).sum().reindex(days, fill_value=0.0)
    return FastResult(bars, daily, _stats(daily, days_per_year, float(trade.sum())))


def sweep(cells: dict, df: pd.DataFrame, cost_bp: float = 5.0, days_per_year: int = 365) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every cell. Returns (stats per cell, daily bp matrix: day x cell)."""
    d = prepare(df)
    stats, daily = {}, {}
    for label, fn in cells.items():
        r = run(fn, d, cost_bp, days_per_year, prepared=True)
        stats[label], daily[label] = r.stats, r.daily
    return pd.DataFrame(stats).T, pd.DataFrame(daily).fillna(0.0)
