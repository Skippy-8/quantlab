"""Insider purchases as events: a point-in-time store, then a market-model event study.

    python examples/02_sec_event_study.py                 # synthetic filings and prices, no network
    SEC_USER_AGENT="Your Name you@example.com" \\
      python examples/02_sec_event_study.py --live        # real Form 4s + Yahoo prices (needs [equities])

1. Load Form 4 purchases into the insider store, keyed on EDGAR acceptance time.
2. Show point-in-time discipline: a filing accepted at 21:15 UTC is invisible one minute before.
3. Join filings to prices in SQL (the store is attached read-only as schema `sec`).
4. Run a market-model event study with t-statistics clustered by event date, and the same
   study on placebo dates drawn from the same tickers, which should find nothing.

The synthetic run plants a small post-purchase drift so there is something to detect; the
placebo shows what the same machinery reports when there is not.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from _common import section, table, workspace

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true")
ap.add_argument("--tickers", default="AAPL,MSFT,NVDA,AMZN,META,JPM,XOM,UNH,HD,PG")
ap.add_argument("--seed", type=int, default=0, help="synthetic data seed")
args = ap.parse_args()
root = workspace("sec")

from quantlab import events  # noqa: E402
from quantlab.data.lake import Lake  # noqa: E402
from quantlab.sec.store import InsiderStore, default_path  # noqa: E402

lake = Lake()
store = InsiderStore(default_path())

# ── 1. filings and prices ────────────────────────────────────────────────────
if args.live:
    if not os.environ.get("SEC_USER_AGENT"):
        raise SystemExit("--live needs SEC_USER_AGENT='Your Name you@example.com' (SEC fair-access policy)")
    from quantlab.data.sources import yahoo
    from quantlab.sec.sync import sync
    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    sync(tickers, "2021-01-01", store=store)
    prices = yahoo.fetch_daily(tickers + ["SPY"], "2020-06-01")
else:
    # 40 tickers x 5 purchases = 200 events. Seed 0 is typical, not chosen: over seeds 0-11 the
    # study's median t is 3.9 (range 1.7 to 5.2) and the placebo's |t| stays below 1.2.
    rng = np.random.default_rng(args.seed)
    days = pd.bdate_range("2021-01-04", periods=750, tz="UTC")
    tickers = [f"T{i:02d}" for i in range(40)]
    market = rng.normal(0.0004, 0.010, len(days))
    rets = {t: rng.uniform(0.6, 1.4) * market + rng.normal(0, 0.015, len(days)) for t in tickers}
    rows, n = [], 0
    for t in tickers:
        for k in rng.choice(np.arange(150, len(days) - 30), size=5, replace=False):
            accepted = days[k] + pd.Timedelta(hours=21, minutes=15)        # after the US close
            rets[t][k + 1:k + 11] += 0.0015                                 # planted: +15 bp/day for 10 days
            n += 1
            rows.append({"accession_number": f"0000000000-21-{n:06d}", "line": 1, "cik": f"{1000 + n}",
                         "ticker": t, "form_type": "4", "acceptance_datetime_utc": accepted,
                         "filing_date": accepted.date(), "transaction_date": days[k].date(),
                         "owner_cik": f"9{n:06d}", "owner_name": f"Insider {n}", "officer_title": "CEO",
                         "is_director": False, "is_officer": True, "is_ten_percent_owner": False,
                         "aff10b5one": False, "in_10b5_1_footnote": False, "transaction_code": "P",
                         "acquired_disposed": "A", "shares": 1000.0, "price": 50.0, "value_usd": 50_000.0})
    for r in rows:
        store.write([r], r["accession_number"], r["ticker"], "4")
    prices = pd.concat([pd.DataFrame({"timestamp": days, "symbol": t, "close": 50 * np.exp(np.cumsum(r))})
                        .assign(open=lambda d: d["close"], high=lambda d: d["close"], low=lambda d: d["close"],
                                volume=1e6) for t, r in rets.items()], ignore_index=True)
lake.write("market", "daily", prices)
print(f"store: {store.summary()}")

# ── 2. point in time ─────────────────────────────────────────────────────────
section("Point-in-time reads")
first = store.purchases().iloc[0]
before = store.as_of(first["public_at"] - pd.Timedelta(minutes=1), first["ticker"])
after = store.as_of(first["public_at"], first["ticker"])
print(f"{first['ticker']} purchase accepted {first['public_at']}: "
      f"{len(before)} rows visible one minute before, {len(after)} at acceptance")

# ── 3. SQL across the store and the lake ─────────────────────────────────────
store.close()                                      # release the write lock; SQL attaches it read-only
section("Insider purchases per quarter (SQL over the attached store)")
table(lake.sql("""
    SELECT date_trunc('quarter', t.acceptance_datetime_utc)::DATE AS quarter,
           count(DISTINCT t.accession_number) AS filings,
           round(sum(t.value_usd) / 1e6, 2) AS value_musd,
           count(DISTINCT t.ticker) AS tickers
    FROM sec.insider_transactions t
    WHERE t.transaction_code = 'P' AND t.acquired_disposed = 'A'
    GROUP BY 1 ORDER BY 1""", sec_db=default_path()).tail(8))

# ── 4. the event study, and a placebo ────────────────────────────────────────
store = InsiderStore(default_path(), read_only=True)
ev = events.insider_purchases(store)
ev = ev[ev["symbol"].isin(prices["symbol"].unique())].sort_values(["timestamp", "symbol"], ignore_index=True)
px = lake.read("market", "daily")
real = events.event_study(px, ev, pre=5, post=10, model="market_model")
rng = np.random.default_rng(1)
placebo_ev = ev.assign(timestamp=pd.to_datetime(rng.choice(px["timestamp"].unique(), len(ev)), utc=True))
placebo = events.event_study(px, placebo_ev, pre=5, post=10, model="market_model")

section("Market-model event study, CAR over the 10 days after the filing became public")
table(pd.DataFrame([{"events": s["events"], "event dates": s["event_dates"],
                     "mean CAR %": 100 * s["mean_car_post"], "median CAR %": 100 * s["median_car_post"],
                     "positive %": 100 * s["positive_share"], "t (date-clustered)": s["t_date_clustered"]}
                    for s in (real, placebo)]).assign(sample=["insider purchases", "placebo dates"]))
print(f"\nworkspace: {root}")
