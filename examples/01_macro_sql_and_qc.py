"""Macro regimes and asset returns: ingest, grade, then answer the question in SQL.

    python examples/01_macro_sql_and_qc.py            # synthetic data, no network
    python examples/01_macro_sql_and_qc.py --live     # FRED DGS10 + Yahoo SPY/TLT/GLD (needs [equities])

1. Ingest a 10-year yield series and three daily asset series.
2. Grade the raw files BEFORE loading them: the synthetic run plants a duplicate row,
   an empty close and a rate shock so every class of finding appears.
3. Load into the lake and ask one cross-dataset question in DuckDB SQL: how did each
   asset do in months when the 10-year yield rose versus fell? Plus each asset's worst
   drawdown, from a window function.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from _common import section, table, workspace

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true", help="use FRED and Yahoo instead of synthetic data")
args = ap.parse_args()
root = workspace("macro")

from quantlab.data import quality  # noqa: E402  (after the workspace is set)
from quantlab.data.lake import Lake  # noqa: E402
from quantlab.data.sources.extra import fred_to_bars  # noqa: E402

# ── 1. ingest ────────────────────────────────────────────────────────────────
if args.live:
    from quantlab.data.sources import yahoo
    from quantlab.data.sources.extra import fred_series
    rates = fred_to_bars(fred_series("DGS10", "2010-01-01"))
    assets = yahoo.fetch_daily(["SPY", "TLT", "GLD"], "2010-01-01")
else:
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2016-01-01", periods=2000, tz="UTC")
    level = 2.0 + np.cumsum(rng.normal(0, 0.04, len(days)))
    level[1200:] += 0.6                                   # a one-day shock the grader should surface
    rates = fred_to_bars(pd.DataFrame({"timestamp": days, "symbol": "DGS10_SYN", "value": level}))
    frames = []
    for sym, beta, vol in [("EQUITY_SYN", -2.0, 0.011), ("BOND_SYN", -7.0, 0.006), ("GOLD_SYN", -1.0, 0.009)]:
        # each asset loads on the rate change, so the regime question has a real answer here
        r = beta * np.r_[0, np.diff(level)] / 100 + rng.normal(0.0003, vol, len(days))
        close = 100 * np.exp(np.cumsum(r))
        frames.append(pd.DataFrame({"timestamp": days, "symbol": sym, "open": close, "high": close * 1.004,
                                    "low": close * 0.996, "close": close, "volume": 1e6}))
    assets = pd.concat(frames, ignore_index=True)
    assets = pd.concat([assets, assets.iloc[[100]]], ignore_index=True)    # a duplicated row
    assets.loc[assets.index[500], "close"] = np.nan                          # an empty close

# ── 2. grade before loading ──────────────────────────────────────────────────
section("Pre-flight QC on the raw files")
for name, df in [("rates", rates), ("assets", assets)]:
    rep = quality.report(df)
    print(f"\n{name}: " + ", ".join(f"{k} {v}" for k, v in rep["schema"].items()))
    table(rep["symbols"])
    if len(rep["findings"]):
        table(rep["findings"].head(6))

# ── 3. load, then ask the question in SQL ────────────────────────────────────
lake = Lake()
lake.write("macro", "rates", rates)
lake.write("market", "daily", assets.dropna(subset=["close"]))   # the upsert also drops the duplicate
section("Lake views")
table(lake.tables())

RATE = "DGS10" if args.live else "DGS10_SYN"
section("Monthly asset return by rate regime (DuckDB SQL)")
if not args.live:
    print("synthetic data: each asset was built with a negative loading on rate changes (bonds the most),\n"
          "so the regimes SHOULD separate. Run with --live to ask the same question of real markets.\n")
table(lake.sql(f"""
    WITH rate AS (
        SELECT date_trunc('month', timestamp) AS month,
               last(close ORDER BY timestamp) - first(close ORDER BY timestamp) AS chg
        FROM macro__rates WHERE symbol = '{RATE}' GROUP BY 1),
    regime AS (
        SELECT month, CASE WHEN chg > 0.10 THEN 'rising' WHEN chg < -0.10 THEN 'falling' ELSE 'flat' END AS regime
        FROM rate),
    ret AS (
        SELECT symbol, date_trunc('month', timestamp) AS month,
               last(close ORDER BY timestamp) / first(close ORDER BY timestamp) - 1 AS r
        FROM market__daily GROUP BY 1, 2)
    SELECT symbol, regime, count(*) AS months,
           round(100 * avg(r), 2) AS avg_return_pct,
           round(100 * avg(CASE WHEN r > 0 THEN 1 ELSE 0 END), 0) AS up_months_pct
    FROM ret JOIN regime USING (month)
    GROUP BY 1, 2 ORDER BY 1, 2"""))

section("Worst drawdown per asset (window function)")
table(lake.sql("""
    SELECT symbol, round(100 * min(dd), 1) AS max_drawdown_pct, arg_min(timestamp, dd)::DATE AS trough
    FROM (SELECT symbol, timestamp,
                 close / max(close) OVER (PARTITION BY symbol ORDER BY timestamp) - 1 AS dd
          FROM market__daily)
    GROUP BY 1 ORDER BY 2"""))

print(f"\nworkspace: {root}")
sys.exit(0)
