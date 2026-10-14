# No-code strategies

Write a strategy as rules. In the dashboard's **Strategy Builder** or as a YAML file:

```yaml
name: RSI dip in an uptrend
description: Buy short-term weakness only when the long-term trend is up.
long_entry: rsi(14) < 30 and close > sma(200)
long_exit: rsi(14) > 55
exits: {unit: atr, stop_loss: 2.5, take_profits: [[2, 0.5], [4, 0.5]], breakeven_after: 1, time_stop_bars: 72}
```

```bash
quantlab backtest --rules rsi_dip.yaml --tearsheet rsi_dip.html
```

## The language

| Element | Examples |
|---|---|
| Columns | `open high low close volume quote_volume funding_rate` |
| Indicators | `sma(50)`, `ema(20)`, `rsi(14)`, `macd()`, `macd_signal()`, `adx(14)`, `bb_upper(20, 2)`, `atr(14)`, `donchian_high(55)`, `vwap(24)`, `zscore(20)`, `realized_vol(24)`, … (35 in total) |
| Helpers | `lag(close, 3)`, `highest(high, 20)`, `lowest(low, 20)`, `crosses_above(a, b)`, `crosses_below(a, b)` |
| Operators | `+ - * /`, `< <= > >= == !=`, `and or not`, parentheses |

## Position logic (per symbol)

* flat → long when `long_entry` is true; long → flat when `long_exit` is true; `short_entry` while
  long reverses the position. Shorts mirror this.
* With no `long_exit`, the position is held exactly while `long_entry` is true.
* `exits` adds stops and targets on top, using the engine's [mechanical exits](../concepts/execution.md#mechanical-exits).

## Safety

Rule text is parsed with Python's `ast` and only the node types listed above are allowed. Attribute
access, subscripts, lambdas, imports and every unknown name are rejected, so a rule file shared by
someone else cannot execute code. The test suite tries `__import__('os')`, `close.__class__`,
`exec(...)` and others and checks each is refused.

Every indicator is computed per symbol and is causal; `tests/test_indicators_rules.py` runs the
engine's lookahead and symbol-leak checks on all 35.
