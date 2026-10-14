# Futures

```python
from quantlab.futures import SPECS, continuous
from quantlab.portfolio import Sizing, simulate

es = continuous(contracts_df, "ES", rule="calendar", roll_days=5, adjust="ratio")
res = evaluate(strategy, es, EngineConfig(roll_cost_bp=1.5, days_per_year=252))
pf = simulate(res, Sizing(method="fixed_notional", notional=250_000, contracts={"ES": SPECS["ES"]}))
```

* **Input**: one row per contract per bar: `timestamp, contract, expiry, open, high, low, close, volume`.
* **Roll**: `calendar` switches `roll_days` before expiry; `volume` switches on the first bar the next
  contract trades more than the current one.
* **Back-adjustment**: `ratio` keeps percentage returns and never goes negative; `difference` keeps
  point P&L. Either way the continuous series has no artificial jump at the roll.
* **Roll costs**: every roll bar is flagged `roll=True`, and the engine charges `roll_cost_bp` for each
  roll a position is held through.
* **Sizing**: with a `ContractSpec`, notional rounds down to whole contracts and initial margin is
  checked against free equity. `SPECS` covers ES/MES, NQ/MNQ, RTY/M2K, YM/MYM, CL/MCL, GC/MGC, ZN, 6E
  (margins are indicative; check the exchange).

The dashboard's **Data Manager → Continuous futures** tab does the same from an uploaded file.
