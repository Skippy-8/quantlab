"""Example strategies: textbook rules that show the interface, not edges.

A strategy is a factory: ``make(**params)`` returns a function that takes the
panel (all symbols, sorted by symbol then timestamp) and returns it with a
``signal`` column in {-1, 0, 1}: the position wanted after each bar's close.

Rules for writing one (the engine checks the first two and rejects violations):
* only use rows at or before each timestamp (no ``shift(-1)``, no centred
  windows, no full-sample statistics);
* group by ``symbol`` for every rolling / shift / diff, or one symbol's rows
  leak into the next;
* return every row, unchanged in order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategySpec:
    name: str
    description: str
    make: Callable[..., Callable[[pd.DataFrame], pd.DataFrame]]
    defaults: dict = field(default_factory=dict)
    grid: dict = field(default_factory=dict)        # a small search grid for the permutation demo


def _g(df: pd.DataFrame, col: str = "close"):
    return df.groupby("symbol", sort=False)[col]


def sma_crossover(fast: int = 20, slow: int = 100, allow_short: bool = True):
    """Long when the fast moving average is above the slow one, short (or flat) below."""
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        f = _g(df).transform(lambda s: s.rolling(fast, min_periods=fast).mean())
        s = _g(df).transform(lambda s: s.rolling(slow, min_periods=slow).mean())
        sig = np.where(f > s, 1, np.where(f < s, -1 if allow_short else 0, 0))
        return df.assign(signal=np.where(s.isna(), 0, sig))
    return fn


def bollinger_reversion(window: int = 48, k: float = 2.0, exit_z: float = 0.0):
    """Fade closes beyond k standard deviations of a rolling mean; flat once back past exit_z."""
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        m = _g(df).transform(lambda s: s.rolling(window, min_periods=window).mean())
        sd = _g(df).transform(lambda s: s.rolling(window, min_periods=window).std())
        z = (df["close"] - m) / sd
        out = np.zeros(len(df), dtype=int)
        for _, idx in df.groupby("symbol", sort=False).indices.items():
            pos, zz = 0, z.to_numpy()[idx]
            for j, i in enumerate(idx):
                v = zz[j]
                if not np.isfinite(v):
                    pos = 0
                elif pos == 0 and v <= -k:
                    pos = 1
                elif pos == 0 and v >= k:
                    pos = -1
                elif (pos == 1 and v >= -exit_z) or (pos == -1 and v <= exit_z):
                    pos = 0
                out[i] = pos
        return df.assign(signal=out)
    return fn


def donchian_breakout(window: int = 55, exit_window: int = 20):
    """Turtle-style channel breakout: enter on a close beyond the prior N-bar extreme,
    exit on a close beyond the prior exit-window extreme the other way."""
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        hi = _g(df, "high").transform(lambda s: s.rolling(window, min_periods=window).max().shift(1))
        lo = _g(df, "low").transform(lambda s: s.rolling(window, min_periods=window).min().shift(1))
        xhi = _g(df, "high").transform(lambda s: s.rolling(exit_window, min_periods=exit_window).max().shift(1))
        xlo = _g(df, "low").transform(lambda s: s.rolling(exit_window, min_periods=exit_window).min().shift(1))
        c = df["close"].to_numpy()
        out = np.zeros(len(df), dtype=int)
        for _, idx in df.groupby("symbol", sort=False).indices.items():
            pos = 0
            for i in idx:
                if pos == 0:
                    pos = 1 if c[i] > hi.iat[i] else (-1 if c[i] < lo.iat[i] else 0)
                elif pos == 1 and c[i] < xlo.iat[i]:
                    pos = 0
                elif pos == -1 and c[i] > xhi.iat[i]:
                    pos = 0
                out[i] = pos
        return df.assign(signal=out)
    return fn


def xs_momentum(lookback: int = 168, top_n: int = 1, rebalance: int = 24):
    """Cross-sectional momentum: at each rebalance bar, long the top-N trailing
    performers and short the bottom-N; hold until the next rebalance."""
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        ret = _g(df).transform(lambda s: s / s.shift(lookback) - 1)
        wide = pd.DataFrame({"timestamp": df["timestamp"], "symbol": df["symbol"], "r": ret})
        piv = wide.pivot(index="timestamp", columns="symbol", values="r")
        sig = pd.DataFrame(0, index=piv.index, columns=piv.columns)
        stamp = piv.index[(np.arange(len(piv)) % rebalance) == 0]
        held = pd.Series(0, index=piv.columns)
        for t in piv.index:
            if t in stamp:
                row = piv.loc[t].dropna()
                held = pd.Series(0, index=piv.columns)
                if len(row) >= 2 * top_n:
                    order = row.sort_values()
                    held[order.index[-top_n:]] = 1
                    held[order.index[:top_n]] = -1
            sig.loc[t] = held
        long = sig.stack().rename("signal").reset_index()
        out = df.merge(long, on=["timestamp", "symbol"], how="left")
        return df.assign(signal=out["signal"].fillna(0).astype(int).to_numpy())
    return fn


REGISTRY: dict[str, StrategySpec] = {
    "sma_crossover": StrategySpec("sma_crossover", "Moving-average crossover (trend)", sma_crossover,
                                  {"fast": 20, "slow": 100, "allow_short": True},
                                  {"fast": [10, 20, 50], "slow": [100, 200]}),
    "bollinger_reversion": StrategySpec("bollinger_reversion", "Bollinger-band fade (mean reversion)",
                                        bollinger_reversion, {"window": 48, "k": 2.0, "exit_z": 0.0},
                                        {"window": [24, 48, 96], "k": [1.5, 2.0, 2.5]}),
    "donchian_breakout": StrategySpec("donchian_breakout", "Donchian channel breakout (trend)",
                                      donchian_breakout, {"window": 55, "exit_window": 20},
                                      {"window": [20, 55, 100], "exit_window": [10, 20]}),
    "xs_momentum": StrategySpec("xs_momentum", "Cross-sectional momentum (long winners, short losers)",
                                xs_momentum, {"lookback": 168, "top_n": 1, "rebalance": 24},
                                {"lookback": [72, 168, 336], "rebalance": [24, 72]}),
}
