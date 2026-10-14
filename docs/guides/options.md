# Options

Multi-leg structures on real (or synthetic) bid/ask chains.

```python
from quantlab.options import STRUCTURES, Leg, backtest, compare_fills, synthetic

chain = synthetic(days=250, vol=0.25)                      # or chain.thetadata_eod("SPY", start, end)
entries = sorted(chain["date"].unique())[::5]              # every 5th trading day
res = backtest(chain, STRUCTURES["iron_condor"], entries, fill="mid", hold_days=14, take_profit=0.5)
compare_fills(chain, STRUCTURES["iron_condor"], entries, hold_days=14)   # mid vs quarter vs natural
```

## Chains

The standard frame has one row per contract per date:
`date | underlying | expiry | strike | right | bid | ask`. Sources:

* `synthetic(...)`: a GBM underlying with a volatility smile, term structure, weekly Friday expiries,
  realistic spreads, and optional event-day IV bumps and jumps; for demos and tests;
* `thetadata_eod(...)`: end-of-day quotes for every strike and expiry from a running Theta Terminal
  (ThetaData's free tier has history from 2023-06);
* your own: anything that `chain.standardize` can map. When a source lacks the underlying, it is
  recovered from put-call parity, which also sidesteps split- and dividend-adjusted stock histories.

## Structures

Thirteen are predefined (`long_call`, `short_put`, verticals, straddles, strangles, `iron_condor`,
`iron_butterfly`, `call_calendar`, `double_calendar`, …). A custom one is a list of legs:

```python
my_structure = [Leg("P", -1, dte=7, delta=0.25), Leg("P", +1, dte=35, delta=0.25)]
```

Legs choose their expiry by `dte` (first expiry at least that far out) or `nth`, and their strike by
`delta` (computed from each quote's own implied vol), `moneyness`, or `atm_offset`.

## Execution and exits

Fills are `mid`, `quarter` (a quarter of the spread worse than mid) or `natural` (pay the ask, sell the
bid). Report all three: the gap between them is usually the most important number in an options
backtest. Exits: `hold_days`, `exit_dte`, `take_profit` / `stop_loss` as fractions of the entry debit or
credit, or expiry (settled at intrinsic value). Per-contract fees are charged on each leg.
