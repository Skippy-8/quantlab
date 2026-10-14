"""Futures: continuous contracts and contract specifications.

A futures backtest needs one continuous series per market, built from
individual contracts that expire. :func:`continuous` stitches them:

* **roll rule**: switch to the next contract ``roll_days`` before expiry
  (``rule="calendar"``), or on the first day the next contract trades more
  volume than the current one (``rule="volume"``);
* **back-adjustment**: shift all history before each roll so the series has no
  artificial jump at the switch, by the price DIFFERENCE (keeps point P&L,
  right for fixed-multiplier P&L) or the RATIO (keeps percentage returns, and
  never goes negative);
* every roll bar is flagged ``roll=True``. The engine charges
  ``EngineConfig.roll_cost_bp`` for each roll a position is held through, which
  is the cost of crossing out of one contract and into the next.

``SPECS`` lists multipliers, tick sizes and indicative initial margins for common
CME contracts (check current exchange margins before relying on them); pass them
to :class:`quantlab.portfolio.Sizing` via ``contracts=`` to size in whole contracts.
"""
from __future__ import annotations

import pandas as pd

from quantlab.portfolio import ContractSpec

SPECS = {
    "ES": ContractSpec(50, 13_000, 0.25), "MES": ContractSpec(5, 1_300, 0.25),
    "NQ": ContractSpec(20, 19_000, 0.25), "MNQ": ContractSpec(2, 1_900, 0.25),
    "RTY": ContractSpec(50, 7_500, 0.1), "M2K": ContractSpec(5, 750, 0.1),
    "YM": ContractSpec(5, 9_500, 1.0), "MYM": ContractSpec(0.5, 950, 1.0),
    "CL": ContractSpec(1_000, 6_000, 0.01), "MCL": ContractSpec(100, 600, 0.01),
    "GC": ContractSpec(100, 10_000, 0.1), "MGC": ContractSpec(10, 1_000, 0.1),
    "ZN": ContractSpec(1_000, 2_200, 1 / 64), "6E": ContractSpec(125_000, 2_500, 0.00005),
}


def continuous(contracts: pd.DataFrame, root: str, rule: str = "calendar", roll_days: int = 5,
               adjust: str = "ratio") -> pd.DataFrame:
    """``contracts``: rows of (timestamp, contract, expiry, open, high, low, close, volume) for one market.

    Returns one series with ``symbol=root``, the active ``contract`` per bar, and ``roll`` flags."""
    df = contracts.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["expiry"] = pd.to_datetime(df["expiry"], utc=True)
    order = df.groupby("contract")["expiry"].first().sort_values()
    seq = list(order.index)
    by = {c: g.set_index("timestamp").sort_index() for c, g in df.groupby("contract")}
    days = sorted(df["timestamp"].unique())
    active, k = [], 0
    for t in days:
        while k < len(seq) - 1:
            cur, nxt = seq[k], seq[k + 1]
            if rule == "calendar":
                switch = t >= order[cur] - pd.Timedelta(days=roll_days)
            else:
                cv = by[cur]["volume"].get(t, 0.0)
                nv = by[nxt]["volume"].get(t, 0.0)
                switch = (nv > cv) or t >= order[cur] - pd.Timedelta(days=1)
            if switch and t in by[nxt].index:
                k += 1
            else:
                break
        if t in by[seq[k]].index:
            active.append((t, seq[k]))
    rows = pd.DataFrame(active, columns=["timestamp", "contract"])
    rows["roll"] = rows["contract"].ne(rows["contract"].shift()) & rows.index.to_series().gt(0)
    px = pd.concat([by[c].loc[[t]].assign(contract=c) for t, c in active]).reset_index()
    out = rows.merge(px.drop(columns=["contract"]), left_index=True, right_index=True, suffixes=("", "_x"))
    out = out.drop(columns=[c for c in out.columns if c.endswith("_x")] + ["expiry"], errors="ignore")
    cols = [c for c in ("open", "high", "low", "close") if c in out]
    # back-adjust: at each roll, compare the new contract with the old one on the same bar
    for i in reversed(out.index[out["roll"]].tolist()):
        t, old = out.at[i, "timestamp"], out.at[i - 1, "contract"]
        if t not in by[old].index:
            continue
        old_c, new_c = float(by[old].at[t, "close"]), float(out.at[i, "close"])
        if adjust == "ratio" and old_c > 0:
            out.loc[: i - 1, cols] *= new_c / old_c
        elif adjust == "difference":
            out.loc[: i - 1, cols] += new_c - old_c
    out["symbol"] = root
    return out[["symbol", "timestamp", "contract", "roll", *cols, "volume"]]
