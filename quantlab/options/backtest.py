"""Multi-leg options backtests on real (or synthetic) bid/ask chains.

A structure is a list of :class:`Leg` rules; on each entry date the legs are
resolved against that day's chain, priced, and then marked every day until an
exit rule fires.

Leg selection
-------------
* expiry: ``dte`` (the first expiry at least that many days out) or ``nth`` (0 = nearest);
* strike: ``delta`` (closest absolute delta, computed from the quote's own implied
  vol), ``moneyness`` (strike nearest spot x (1 + m)) or ``atm_offset`` (strikes from ATM).

Fills
-----
``fill="mid"`` (both sides at the midpoint), ``"quarter"`` (a quarter of the
spread worse than mid), or ``"natural"`` (pay the ask, sell the bid). Reporting
all three is the honest way to show how much of a result depends on execution.

Exits (first to trigger)
------------------------
``hold_days``, ``exit_dte`` (days before the nearest leg expires), ``take_profit``
and ``stop_loss`` as fractions of the entry debit (or credit), or expiry (settled
at intrinsic value against the underlying).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quantlab.options import pricing as P

MULT = 100


@dataclass(frozen=True)
class Leg:
    right: str                        # "C" or "P"
    side: int                         # +1 long, -1 short
    qty: int = 1
    dte: int | None = 30
    nth: int | None = None
    delta: float | None = None
    moneyness: float | None = None
    atm_offset: int | None = None


STRUCTURES = {
    "long_call": [Leg("C", 1, delta=0.5)],
    "long_put": [Leg("P", 1, delta=0.5)],
    "short_put": [Leg("P", -1, delta=0.3)],
    "covered_strangle_short": [Leg("P", -1, delta=0.2), Leg("C", -1, delta=0.2)],
    "bull_call_spread": [Leg("C", 1, delta=0.5), Leg("C", -1, delta=0.3)],
    "bear_put_spread": [Leg("P", 1, delta=0.5), Leg("P", -1, delta=0.3)],
    "long_straddle": [Leg("C", 1, atm_offset=0), Leg("P", 1, atm_offset=0)],
    "short_straddle": [Leg("C", -1, atm_offset=0), Leg("P", -1, atm_offset=0)],
    "long_strangle": [Leg("C", 1, delta=0.25), Leg("P", 1, delta=0.25)],
    "iron_condor": [Leg("P", 1, delta=0.1), Leg("P", -1, delta=0.2), Leg("C", -1, delta=0.2), Leg("C", 1, delta=0.1)],
    "iron_butterfly": [Leg("P", 1, delta=0.15), Leg("P", -1, atm_offset=0), Leg("C", -1, atm_offset=0),
                       Leg("C", 1, delta=0.15)],
    "call_calendar": [Leg("C", -1, dte=7, atm_offset=0), Leg("C", 1, dte=35, atm_offset=0)],
    "double_calendar": [Leg("P", -1, dte=7, moneyness=-0.03), Leg("P", 1, dte=35, moneyness=-0.03),
                        Leg("C", -1, dte=7, moneyness=0.03), Leg("C", 1, dte=35, moneyness=0.03)],
}


@dataclass
class OptionsResult:
    trades: pd.DataFrame
    daily: pd.DataFrame
    skipped: dict = field(default_factory=dict)


def _pick_expiry(day: pd.DataFrame, leg: Leg) -> pd.Timestamp | None:
    exps = np.sort(day["expiry"].unique())
    d0 = day["date"].iat[0]
    if leg.nth is not None:
        return pd.Timestamp(exps[leg.nth]) if leg.nth < len(exps) else None
    ok = [e for e in exps if (pd.Timestamp(e) - d0).days >= (leg.dte or 0)]
    return pd.Timestamp(ok[0]) if ok else None


def _pick(day: pd.DataFrame, leg: Leg) -> pd.Series | None:
    e = _pick_expiry(day, leg)
    if e is None:
        return None
    q = day[(day["expiry"] == e) & (day["right"] == leg.right)].copy()
    if q.empty:
        return None
    s = float(q["underlying"].iat[0])
    if leg.delta is not None:
        t = max((e - q["date"].iat[0]).days, 1) / 365
        mid = (q["bid"] + q["ask"]) / 2
        iv = P.implied_vol(mid, s, q["strike"], t, leg.right == "C")
        dl = np.abs(P.delta(s, q["strike"], t, np.nan_to_num(iv, nan=0.3), leg.right == "C"))
        q["score"] = np.abs(dl - leg.delta)
    elif leg.moneyness is not None:
        q["score"] = (q["strike"] - s * (1 + leg.moneyness)).abs()
    else:
        ks = np.sort(q["strike"].unique())
        atm = int(np.argmin(np.abs(ks - s)))
        k = ks[int(np.clip(atm + (leg.atm_offset or 0) * (1 if leg.right == "C" else -1), 0, len(ks) - 1))]
        q["score"] = (q["strike"] - k).abs()
    return q.sort_values("score").iloc[0]


def _px(bid, ask, side, fill: str, opening: bool) -> float:
    mid = (bid + ask) / 2
    paying = (side > 0) == opening                  # buying to open, or buying back a short to close
    worse = (ask - mid) if paying else -(mid - bid)
    return mid + {"mid": 0.0, "quarter": 0.5, "natural": 1.0}[fill] * worse


def backtest(chain: pd.DataFrame, legs: list[Leg], entries: list, fill: str = "mid", hold_days: int | None = None,
             exit_dte: int | None = 1, take_profit: float | None = None, stop_loss: float | None = None,
             fee_per_contract: float = 0.65, max_open: int = 1) -> OptionsResult:
    """Enter ``legs`` on each date in ``entries`` (skipping any that would exceed ``max_open``)."""
    chain = chain.sort_values(["date", "expiry", "strike"])
    by_day = {d: g for d, g in chain.groupby("date")}
    days = sorted(by_day)
    entries = sorted({pd.Timestamp(e).tz_localize("UTC") if pd.Timestamp(e).tzinfo is None else pd.Timestamp(e)
                      for e in entries})
    entries = [e.floor("D") for e in entries]
    open_, trades, marks = [], [], {}
    skipped = {"no_chain": 0, "no_leg": 0, "max_open": 0}
    for d in days:
        day = by_day[d]
        spot = float(day["underlying"].iat[0])
        # manage open structures
        still = []
        for pos in open_:
            quotes, settle = [], False
            for lg, c in zip(pos["legs"], pos["contracts"], strict=True):
                if d >= c["expiry"]:
                    settle = True
                q = day[(day["expiry"] == c["expiry"]) & (day["strike"] == c["strike"]) & (day["right"] == lg.right)]
                quotes.append(None if q.empty else q.iloc[0])
            value_mid = sum(lg.side * lg.qty * ((q["bid"] + q["ask"]) / 2 if q is not None else pos["last"][i])
                            for i, (lg, q) in enumerate(zip(pos["legs"], quotes, strict=True)))
            pos["last"] = [((q["bid"] + q["ask"]) / 2) if q is not None else pos["last"][i] for i, q in enumerate(quotes)]
            pnl_mid = (value_mid - pos["entry_value"]) * MULT
            basis = abs(pos["entry_value"]) * MULT or 1.0
            held = (d - pos["entry_date"]).days
            dte_left = min((c["expiry"] - d).days for c in pos["contracts"])
            why = None
            if settle:
                why = "expiry"
            elif exit_dte is not None and dte_left <= exit_dte:
                why = "exit_dte"
            elif hold_days is not None and held >= hold_days:
                why = "hold_days"
            elif take_profit is not None and pnl_mid >= take_profit * basis:
                why = "take_profit"
            elif stop_loss is not None and pnl_mid <= -stop_loss * basis:
                why = "stop_loss"
            if why:
                if why == "expiry":
                    exit_value = sum(lg.side * lg.qty * max((spot - c["strike"]) if lg.right == "C" else
                                                            (c["strike"] - spot), 0.0)
                                     for lg, c in zip(pos["legs"], pos["contracts"], strict=True))
                else:
                    exit_value = sum(lg.side * lg.qty * (_px(q["bid"], q["ask"], lg.side, fill, opening=False)
                                                         if q is not None else pos["last"][i])
                                     for i, (lg, q) in enumerate(zip(pos["legs"], quotes, strict=True)))
                fees = fee_per_contract * sum(lg.qty for lg in pos["legs"]) * (1 if why == "expiry" else 2)
                pnl = (exit_value - pos["entry_value"]) * MULT - fees
                trades.append({"entry_date": pos["entry_date"], "exit_date": d, "exit_reason": why,
                               "entry_value": pos["entry_value"], "exit_value": exit_value, "pnl": pnl,
                               "return_on_basis": pnl / basis, "days_held": held, "spot_entry": pos["spot"],
                               "spot_exit": spot, "legs": pos["desc"], "fees": fees})
                marks[d] = marks.get(d, 0.0) + pnl - pos["marked"]
            else:
                marks[d] = marks.get(d, 0.0) + pnl_mid - pos["marked"]
                pos["marked"] = pnl_mid
                still.append(pos)
        open_ = still
        # new entries
        if d in entries:
            if len(open_) >= max_open:
                skipped["max_open"] += 1
                continue
            picked = [_pick(day, lg) for lg in legs]
            if any(p is None for p in picked):
                skipped["no_leg"] += 1
                continue
            entry_value = sum(lg.side * lg.qty * _px(p["bid"], p["ask"], lg.side, fill, opening=True)
                              for lg, p in zip(legs, picked, strict=True))
            desc = " / ".join(f"{'+' if lg.side > 0 else '-'}{lg.qty} {p['expiry']:%m-%d} {p['strike']:g}{lg.right}"
                              for lg, p in zip(legs, picked, strict=True))
            open_.append({"legs": legs, "contracts": [{"expiry": p["expiry"], "strike": p["strike"]} for p in picked],
                          "entry_value": entry_value, "entry_date": d, "spot": spot, "desc": desc, "marked": 0.0,
                          "last": [(p["bid"] + p["ask"]) / 2 for p in picked]})
    missing = [e for e in entries if e not in by_day]
    skipped["no_chain"] = len(missing)
    daily = pd.Series(marks).sort_index().rename("pnl").to_frame()
    daily["equity"] = daily["pnl"].cumsum()
    return OptionsResult(pd.DataFrame(trades), daily, skipped)


def compare_fills(chain, legs, entries, **kw) -> pd.DataFrame:
    """The same backtest at mid, quarter and natural fills, side by side."""
    rows = {}
    for f in ("mid", "quarter", "natural"):
        t = backtest(chain, legs, entries, fill=f, **kw).trades
        rows[f] = {"trades": len(t), "total_pnl": float(t["pnl"].sum()) if len(t) else 0.0,
                   "avg_pnl": float(t["pnl"].mean()) if len(t) else 0.0,
                   "win_rate": float((t["pnl"] > 0).mean()) if len(t) else float("nan")}
    return pd.DataFrame(rows).T
