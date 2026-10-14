# Event studies

An event is a symbol and the time the information became **public**. For SEC filings that is the EDGAR
acceptance time, not the transaction date.

```python
from quantlab.events import event_strategy, event_study, earnings_dates, insider_purchases

events = earnings_dates(["AAPL", "MSFT", "NVDA"])                 # or a CSV, or insider purchases
out = event_study(prices, events, pre=5, post=20, model="market_model")
out["path"]                 # mean cumulative abnormal return by bar, with a 95% band
out["t_date_clustered"]     # events on the same day count once

res = evaluate(event_strategy(events, side=1, hold=10, delay=1), prices)   # trade it through the engine
```

* **Models**: `raw`; `market` (minus the equal-weighted market of the loaded symbols, or a benchmark
  you pass); `market_model` (alpha and beta fitted on an estimation window before each event).
* **Inference** is clustered by calendar date. Twenty companies reporting on the same morning share
  one market shock and are not twenty independent observations.
* **Trading**: `event_strategy` enters `delay` bars after the first bar that opens at or after the event
  and holds `hold` bars. It is causal by construction, so it passes the engine's lookahead check.
