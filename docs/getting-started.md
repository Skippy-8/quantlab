# Getting started

## Install

```bash
git clone https://github.com/Skippy-8/quantlab && cd quantlab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dashboard,dev]"          # add [equities] for Yahoo data
```

Python 3.11+. Everything lives under two directories you can move with environment variables:
`QUANTLAB_LAKE` (the Parquet lake, default `data/lake`) and `QUANTLAB_HOME` (registry, saved runs,
heartbeats, default `.quantlab`).

## Five minutes, no downloads

```bash
quantlab fetch synthetic                                   # four synthetic markets into the lake
quantlab backtest sma_crossover --study demo --splits      # one run, counted in study "demo"
quantlab search bollinger_reversion --study demo --perm 200
quantlab registry --study demo
streamlit run dashboard/app.py                             # the dashboard
```

`search` sweeps a parameter grid, records every cell as a trial, and compares the best cell with
the best cell of the same search run 200 times on shuffled signals. On random data the answer
should be, and is, "this is what luck produces".

## Real data

```bash
quantlab fetch binance BTCUSDT ETHUSDT SOLUSDT --start 2023-01 --end 2024-12 --funding
quantlab quality binance/klines_1h
quantlab backtest donchian_breakout --data binance/klines_1h --study trend \
    --tearsheet report.html --save "Donchian 55/20"
quantlab walkforward donchian_breakout --data binance/klines_1h --train 120 --test 30
```

Your own files:

```bash
quantlab import my_prices.csv --source broker --dataset daily     # columns are detected
```

## In Python

```python
from quantlab import evaluate
from quantlab.data import Lake
from quantlab.engine import EngineConfig, ExitRules
from quantlab.portfolio import Sizing, simulate
from quantlab.rules import RuleStrategy

df = Lake().read("binance", "klines_1h")
rule = RuleStrategy("RSI dip", long_entry="rsi(14) < 30 and close > sma(200)", long_exit="rsi(14) > 55")
cfg = EngineConfig(exits=ExitRules(unit="atr", stop_loss=2.5, take_profits=((2, 0.5), (4, 0.5)),
                                   breakeven_after=1))
res = evaluate(rule.signal_fn(), df, cfg)          # raises LookaheadError if the rule peeks
pf = simulate(res, Sizing(method="vol_target", target_vol=0.15, max_leverage=2))
print(res.summary["day_t"], pf.stats["final_equity"])
```
