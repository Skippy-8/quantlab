# quantlab

**A research platform for honest backtests.**

Most backtests overstate their results for three reasons: the strategy quietly uses future data,
the fills are better than the market would have given, and nobody counts how many variants were
tried before the winner. quantlab makes each of those mechanically hard to get wrong, and then
covers the rest of the workflow: data, strategy authoring, validation, reporting and monitoring.

![The Backtest Lab](images/backtest-light.png){ .shot }

## What it does

| Area | What you get |
|---|---|
| **Execution** | One engine for every strategy: limit orders that must trade through, expiry with a taker fallback, fees, funding, short borrow, futures roll costs; stops, profit-target ladders, breakeven and trailing exits with partial fills |
| **Integrity** | Every strategy is re-run on truncated data and reordered symbols before scoring. One that reads the future, or leaks one symbol's rows into another's, is rejected with the row that proves it |
| **Multiple testing** | A trial registry counts every variant; the pass bar rises with the count. Deflated Sharpe, Holm/BHY, Harvey-Liu haircut, whole-search permutation nulls, PBO, White's Reality Check and Hansen's SPA |
| **Out-of-sample** | Walk-forward optimisation; a sealed, hashed vault that opens once per pre-registered hypothesis |
| **Portfolio** | Dollar equity under fixed-fraction, volatility-target or risk-per-trade sizing with leverage, position and margin limits; whole futures contracts |
| **Strategies** | 35 causal indicators and a no-code rule language (`rsi(14) < 30 and close > sma(200)`), parsed safely and stored as YAML; Python for anything else |
| **Asset classes** | Crypto perps with funding, equities, continuous futures, multi-leg options on bid/ask chains, event studies |
| **Data** | A Parquet lake with a DuckDB catalog; Binance, Yahoo, CCXT, FRED and SEC EDGAR sources; CSV/Parquet import with column detection; quality checks |
| **Reporting** | Metrics, benchmark statistics, a standalone HTML tearsheet, saved runs with code version and data fingerprint |
| **Operations** | A Streamlit dashboard, a CLI, heartbeats and freshness checks that exit non-zero for alerting, example systemd units, CI |

## Where to start

- [Getting started](getting-started.md): install, load data, run your first backtest in five minutes.
- [Methodology](concepts/methodology.md): why each control exists and what it protects against.
- [No-code strategies](guides/rules.md): write strategies as sentences.
