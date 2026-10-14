"""Standard post-run splits, reported for every backtest.

A single headline number hides where the result comes from. These splits are
descriptive (they are not used to pick anything) but each is an extra cell, so
reading a t inside a split should account for the extra looks.

* by year;
* weekday vs weekend entry (UTC) - crypto trades 24/7, and weekend liquidity is
  different enough that a strategy living only on weekends is a different strategy;
* long vs short;
* by symbol category, when a ``symbol -> category`` mapping is supplied;
* exit type (maker / taker / eod), which shows how much of the result paid the spread.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.stats.inference import t_stat


def _row(x: pd.Series) -> dict:
    return {"trades": int(len(x)), "mean_bp": float(x.mean()) if len(x) else float("nan"),
            "median_bp": float(x.median()) if len(x) else float("nan"),
            "win_rate": float((x > 0).mean()) if len(x) else float("nan"),
            "sum_bp": float(x.sum()), "t": t_stat(x)}


def table(trades: pd.DataFrame, by: pd.Series) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = {k: _row(g) for k, g in trades["net_bp"].groupby(by.values)}
    return pd.DataFrame(rows).T


def report(trades: pd.DataFrame, categories: dict | None = None) -> dict[str, pd.DataFrame]:
    if trades.empty:
        return {}
    entry = pd.to_datetime(trades["entry_time"], utc=True)
    out = {
        "year": table(trades, entry.dt.year),
        "weekday_vs_weekend": table(trades, pd.Series(np.where(entry.dt.dayofweek >= 5, "weekend", "weekday"))),
        "side": table(trades, trades["side"]),
        "exit": table(trades, trades["exit"]),
        "symbol": table(trades, trades["symbol"]).sort_values("sum_bp", ascending=False),
    }
    if categories:
        out["category"] = table(trades, trades["symbol"].map(lambda s: categories.get(s, "unknown")))
    return out
