# Exits and portfolio sizing

The engine scores each position on one unit of notional. `quantlab.portfolio.simulate` replays the
positions bar by bar under a sizing rule and capital limits, and returns a dollar equity curve.

```python
from quantlab.portfolio import ContractSpec, Sizing, simulate

pf = simulate(res, Sizing(method="vol_target", target_vol=0.15, max_weight=0.5, max_leverage=2.0,
                          initial_capital=100_000))
pf.equity            # marked to market at every bar close
pf.daily_returns     # feeds the tearsheet
pf.ledger            # each position with its notional and dollar P&L
pf.stats["positions_skipped"]   # how many entries the limits refused, and why
```

| Method | Notional at entry |
|---|---|
| `fixed_notional` | the same dollar amount every time |
| `fixed_fraction` | `equity × fraction` (compounding) |
| `vol_target` | `equity × target_vol / trailing annualised vol`, capped at `max_weight` |
| `risk_per_trade` | `equity × risk_fraction / stop distance`: hitting the stop costs about `risk_fraction` of equity |

Limits: `max_leverage` (gross open notional / equity), `max_positions`, and for futures the initial
margin of `ContractSpec`. Notional is rounded down to whole contracts
(`qty × price × multiplier`); `quantlab.futures.SPECS` holds common CME specifications.

Each closing slice realises `notional × size × net_bp`, the engine's net, so fees, funding, borrow
and rolls are already included. A position opened while equity is at or below zero is skipped and the
account is marked ruined.
