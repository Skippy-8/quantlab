"""From per-trade basis points to a dollar equity curve.

The engine scores every position on one unit of notional, which is the right
way to compare strategies. Trading them needs a sizing rule, capital limits and
mark-to-market. This module replays the engine's positions bar by bar:

* each position is sized when it OPENS, from the equity at that moment;
* open positions are marked to market at every bar close;
* each closing slice realises ``notional * size * net_bp`` (the engine's net,
  so fees, funding, borrow and rolls are already in);
* a position is SKIPPED (and counted) if opening it would breach the gross
  leverage cap, the position limit, or the margin available.

Sizing methods
--------------
``fixed_notional``  the same dollar amount every time.
``fixed_fraction``  a fraction of current equity (compounding).
``vol_target``      notional = equity * target_vol / the symbol's trailing
                    annualised volatility, capped at ``max_weight``: equal risk
                    across calm and wild assets.
``risk_per_trade``  notional = equity * risk_fraction / stop distance, so
                    hitting the stop loses about ``risk_fraction`` of equity.
                    Needs a stop in the engine's ``ExitRules``.

Futures: give a :class:`ContractSpec` and notional is rounded DOWN to whole
contracts (``qty * price * multiplier``), with initial margin checked against
free equity.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from quantlab.engine import BacktestResult


@dataclass(frozen=True)
class ContractSpec:
    multiplier: float = 1.0
    initial_margin: float = 0.0          # dollars per contract
    tick_size: float = 0.0


@dataclass(frozen=True)
class Sizing:
    method: str = "fixed_fraction"
    initial_capital: float = 100_000.0
    notional: float = 10_000.0           # fixed_notional
    fraction: float = 0.10               # fixed_fraction
    target_vol: float = 0.15             # vol_target (annualised, per position)
    vol_lookback_bars: int = 48
    max_weight: float = 0.5              # cap on any one position, as a fraction of equity
    risk_fraction: float = 0.01          # risk_per_trade
    max_leverage: float = 1.0            # gross open notional / equity
    max_positions: int | None = None
    contracts: dict = field(default_factory=dict)    # symbol -> ContractSpec

    def to_dict(self) -> dict:
        d = asdict(self)
        d["contracts"] = {k: asdict(v) for k, v in self.contracts.items()}
        return d


@dataclass
class PortfolioResult:
    equity: pd.Series                    # marked at every bar close
    daily_equity: pd.Series              # last mark of each calendar day
    daily_returns: pd.Series
    ledger: pd.DataFrame                 # each position with its dollars
    stats: dict


def _bars_per_year(ts: pd.Series, days_per_year: int) -> float:
    d = pd.Series(ts.unique()).sort_values().diff().dt.total_seconds().median()
    return days_per_year * 86400 / d if d and d > 0 else float(days_per_year)


def simulate(res: BacktestResult, sizing: Sizing = Sizing()) -> PortfolioResult:
    if res.frame is None:
        raise ValueError("the backtest result has no frame (run it through evaluate/run_backtest)")
    frame = res.frame[["symbol", "timestamp", "close"]].copy()
    dpy = res.summary.get("config", {}).get("days_per_year", 365)
    bpy = _bars_per_year(frame["timestamp"], dpy)
    if sizing.method == "vol_target":
        lr = np.log(frame["close"]).groupby(frame["symbol"]).diff()
        frame["vol"] = lr.groupby(frame["symbol"]).transform(
            lambda s: s.rolling(sizing.vol_lookback_bars, min_periods=sizing.vol_lookback_bars).std()) * math.sqrt(bpy)
    closes = frame.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last").sort_index().ffill()
    vols = frame.pivot_table(index="timestamp", columns="symbol", values="vol", aggfunc="last").sort_index() \
        if "vol" in frame else None
    stop_frac = None
    ex = res.summary.get("config", {}).get("exits", {}) or {}
    if sizing.method == "risk_per_trade":
        if not ex.get("stop_loss"):
            raise ValueError("risk_per_trade sizing needs a stop_loss in the engine's ExitRules")
        stop_frac = ex["stop_loss"]

    pos = res.positions.set_index("position_id") if len(res.positions) else pd.DataFrame()
    slices = res.trades
    opens = {t: g.index.tolist() for t, g in pos.groupby("entry_time")} if len(pos) else {}
    closes_at = {t: g for t, g in slices.groupby("exit_time")} if len(slices) else {}

    cash = equity = sizing.initial_capital
    open_: dict[int, dict] = {}
    ledger, marks = [], []
    skipped = {"leverage": 0, "max_positions": 0, "margin": 0, "zero_contracts": 0, "ruined": 0}
    ruined = False
    for ts, row in closes.iterrows():
        # 1. mark open positions at this close
        unreal = sum(p["notional"] * p["remaining"] * p["side"] * (row[p["symbol"]] / p["entry"] - 1)
                     for p in open_.values() if np.isfinite(row.get(p["symbol"], np.nan)))
        equity = cash + unreal
        # 2. positions opening at this bar are sized from current equity (before closes, so a
        #    position that opens and is closed at the same final bar is still booked)
        for pid in opens.get(ts, []):
            if ruined:
                skipped["ruined"] += 1
                continue
            p = pos.loc[pid]
            sym, px = p["symbol"], float(p["entry_price"])
            if sizing.method == "fixed_notional":
                notional = sizing.notional
            elif sizing.method == "fixed_fraction":
                notional = equity * sizing.fraction
            elif sizing.method == "vol_target":
                v = vols.at[ts, sym] if vols is not None and ts in vols.index else np.nan
                w = min(sizing.target_vol / v, sizing.max_weight) if v and np.isfinite(v) and v > 0 else 0.0
                notional = equity * w
            elif sizing.method == "risk_per_trade":
                notional = min(equity * sizing.risk_fraction / stop_frac, equity * sizing.max_weight * sizing.max_leverage)
            else:
                raise ValueError(f"unknown sizing method {sizing.method!r}")
            spec = sizing.contracts.get(sym)
            qty = None
            if spec is not None:
                qty = math.floor(notional / (px * spec.multiplier)) if px > 0 else 0
                if qty <= 0:
                    skipped["zero_contracts"] += 1
                    continue
                notional = qty * px * spec.multiplier
                margin_used = sum(o["margin"] for o in open_.values())
                if spec.initial_margin and margin_used + qty * spec.initial_margin > equity:
                    skipped["margin"] += 1
                    continue
            gross = sum(o["notional"] * o["remaining"] for o in open_.values())
            if sizing.max_positions and len(open_) >= sizing.max_positions:
                skipped["max_positions"] += 1
                continue
            if notional <= 0 or gross + notional > sizing.max_leverage * equity + 1e-9:
                skipped["leverage"] += 1
                continue
            open_[pid] = {"position_id": pid, "symbol": sym, "side": 1 if p["side"] == "LONG" else -1,
                          "entry": px, "entry_time": ts, "notional": notional, "qty": qty, "remaining": 1.0,
                          "pnl": 0.0, "equity_at_entry": equity,
                          "margin": (qty or 0) * (spec.initial_margin if spec else 0.0)}
        # 3. slices closing at this bar realise their engine net
        if ts in closes_at:
            for _, s in closes_at[ts].iterrows():
                p = open_.get(s["position_id"])
                if p is None:
                    continue
                pnl = p["notional"] * s["size"] * s["net_bp"] / 1e4
                cash += pnl
                p["pnl"] += pnl
                p["remaining"] = round(p["remaining"] - s["size"], 12)
                if p["remaining"] <= 1e-12:
                    ledger.append({**{k: p[k] for k in ("position_id", "symbol", "side", "entry_time", "notional",
                                                        "qty")}, "exit_time": ts, "pnl": p["pnl"],
                                   "return_on_equity_at_entry": p["pnl"] / p["equity_at_entry"]})
                    del open_[s["position_id"]]
            unreal = sum(p["notional"] * p["remaining"] * p["side"] * (row[p["symbol"]] / p["entry"] - 1)
                         for p in open_.values() if np.isfinite(row.get(p["symbol"], np.nan)))
            equity = cash + unreal
        if equity <= 0 and not ruined:
            ruined = True
        marks.append((ts, equity))

    eq = pd.Series(dict(marks)).sort_index()
    daily = eq.groupby(eq.index.floor("D")).last()
    rets = daily.pct_change().fillna(daily.iloc[0] / sizing.initial_capital - 1 if len(daily) else 0.0)
    led = pd.DataFrame(ledger)
    stats = {"initial_capital": sizing.initial_capital, "final_equity": float(eq.iloc[-1]) if len(eq) else None,
             "total_return": float(eq.iloc[-1] / sizing.initial_capital - 1) if len(eq) else None,
             "positions_taken": int(len(led)), "positions_skipped": skipped, "ruined": ruined,
             "sizing": sizing.to_dict()}
    return PortfolioResult(eq, daily, rets, led, stats)
