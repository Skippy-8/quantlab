<h1 align="center">quantlab</h1>

<p align="center"><b>Backtests that can't lie to you.</b></p>

<p align="center">
An end-to-end quant research platform: a realistic execution engine, overfitting controls that count
every attempt, a 13-page research dashboard, and a real-time Node.js console. Python, TypeScript and SQL.
</p>

<p align="center">
  <a href="https://github.com/Skippy-8/quantlab/actions/workflows/ci.yml"><img src="https://github.com/Skippy-8/quantlab/actions/workflows/ci.yml/badge.svg" alt="ci"/></a>
  <a href="https://skippy-8.github.io/quantlab/"><img src="https://img.shields.io/badge/docs-live-3550c8" alt="docs"/></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-3550c8" alt="python"/>
  <img src="https://img.shields.io/badge/node-22-3550c8" alt="node"/>
  <img src="https://img.shields.io/badge/typescript-strict-3550c8" alt="typescript"/>
  <img src="https://img.shields.io/badge/tests-220%2B-14805e" alt="tests"/>
  <img src="https://img.shields.io/badge/license-MIT-6b7280" alt="MIT"/>
</p>

<p align="center">
  <a href="https://skippy-8.github.io/quantlab/"><b>Documentation</b></a> ·
  <a href="https://skippy-8.github.io/quantlab/getting-started/">Five-minute start</a> ·
  <a href="https://skippy-8.github.io/quantlab/concepts/methodology/">Methodology</a> ·
  <a href="console/">Live console</a>
</p>

![The Backtest Lab](docs/images/backtest-light.png)

## The problem

Almost every backtest you have seen is too good, and for the same three reasons:

- **It reads the future.** One centred rolling window, one full-sample mean, one `shift(-1)`, and the
  equity curve goes vertical.
- **It fills at prices nobody would have given it.** The close touched your limit, so it filled.
  Fees, funding, borrow and rolls are a rounding error, apparently.
- **It forgets what it tried.** The winner of 200 parameter sets is presented as if it were the only
  idea anyone ever had.

quantlab is built so that none of these can happen quietly. A strategy that peeks is **refused,
with the row that proves it**. Fills come from **one execution model** that every strategy shares.
And every variant you run is **counted**: the bar a result has to clear rises with the number of
things you tried.

## Highlights

- **A strategy that cheats is caught before it is scored.** Every run is replayed on truncated data
  and on reordered symbols. If any past signal changes, the run is rejected.
- **Honest fills.** Limit orders fill only when price trades *through* them, inside a time-to-live,
  with a taker fallback. Fees, funding, short borrow and futures rolls are charged. Stops,
  profit-target ladders, breakeven and trailing exits are modelled with partial fills, and a gap
  through a stop fills at the open.
- **The best cell has to beat luck, not zero.** Parameter searches are re-run on shuffled signals,
  and the best real cell is compared with the best shuffled one. Deflated Sharpe, PBO, White's
  Reality Check, Hansen's SPA, Holm/BHY, walk-forward testing, and a sealed one-shot holdout vault.
- **One platform, every asset class.** Crypto perpetuals with funding, equities, continuous futures,
  multi-leg options priced at mid, quarter and natural, event studies, and a point-in-time SEC
  insider-filings pipeline.
- **No-code or full code.** Write `rsi(14) < 30 and close > sma(200)` in the Strategy Builder (35
  indicators, parsed safely, saved as YAML), or hand the engine any Python function.
- **Live and observable.** A Node.js console streams every trial, run and job heartbeat to the
  browser as it happens. It can launch backtests and stream their output too.

## See it

<table>
<tr>
<td width="50%"><img src="docs/images/console-live-light.png" alt="Live console"/><br/><sub><b>Live console (Node.js).</b> Every trial, run and heartbeat on the platform, pushed over a WebSocket.</sub></td>
<td width="50%"><img src="docs/images/console-run-dark.png" alt="A saved run in the console"/><br/><sub><b>Run detail.</b> Equity and drawdown read straight from Parquet by DuckDB inside Node.</sub></td>
</tr>
<tr>
<td><img src="docs/images/optimize-light.png" alt="Parameter Search"/><br/><sub><b>Parameter Search.</b> Every cell counted, and the best one tested against the best of the same search on shuffled signals.</sub></td>
<td><img src="docs/images/walkforward-light.png" alt="Walk-Forward"/><br/><sub><b>Walk-Forward.</b> Parameters chosen on the past only, then stitched across windows nobody optimised on.</sub></td>
</tr>
<tr>
<td><img src="docs/images/options-light.png" alt="Options Lab"/><br/><sub><b>Options Lab.</b> Thirteen structures, legs chosen by delta, moneyness or offset, priced three ways.</sub></td>
<td><img src="docs/images/console-launch-light.png" alt="Launch a backtest"/><br/><sub><b>Launch from the browser.</b> Validated, spawned without a shell, streamed line by line, verdict parsed.</sub></td>
</tr>
</table>

## How it differs from a typical backtest

| | Typical backtest | quantlab |
|---|---|---|
| Limit-order fills | the bar touched the price | price traded through it, within a time-to-live |
| Lookahead | reviewed by eye, if at all | replayed on truncated data and refused if any past signal changes |
| Parameter search | report the best cell | the best cell must beat the best cell of the same search on shuffled signals |
| Significance bar | t > 2 | `max(2, √(2 ln K))` for K distinct trials, plus a deflated Sharpe over all of them |
| Out-of-sample | a final holdout, often reused | walk-forward, and a sealed vault that opens once per pre-registered spec |
| Options P&L | marked at the mid | the same trades at mid, quarter and natural, to show how much of the edge is the spread |

## A real result

A Donchian breakout grid on six Binance perpetuals, hourly bars, all of 2024:

```
$ quantlab search donchian_breakout --data binance/klines_1h --study trend --perm 200
best cell window=100,exit_window=20: day_t 1.33
whole-search permutation p = 0.488 over 200 shuffles (null best median 1.29)
study 'trend': K = 6, bar 2.00
```

The best of six cells shows t 1.33, and most tools would stop there. quantlab re-runs the *same
six-cell search* 200 times on shuffled signals, and that does at least as well about half the time.
So t 1.33 is what a search that size finds by luck. This is the check quantlab runs by default.

## Three ways in

**The dashboard**: 13 pages for building, validating and comparing strategies.

```bash
pip install -e ".[dashboard]"
quantlab fetch synthetic          # demo data, no network needed
streamlit run dashboard/app.py
```

**The live console**: Node.js and TypeScript, watching the platform in real time.

```bash
cd console && npm install && npm run build
QUANTLAB_HOME=../.quantlab QUANTLAB_LAKE=../data/lake QUANTLAB_CLI=../.venv/bin/quantlab npm start
```

**Python and the CLI**, for anything scripted:

```python
from quantlab import evaluate
from quantlab.data import Lake
from quantlab.engine import EngineConfig, ExitRules
from quantlab.portfolio import Sizing, simulate
from quantlab.report.tearsheet import Tearsheet
from quantlab.rules import RuleStrategy

df = Lake().read("binance", "klines_1h")
rule = RuleStrategy("RSI dip", long_entry="rsi(14) < 30 and close > sma(200)", long_exit="rsi(14) > 55")
cfg = EngineConfig(exits=ExitRules(unit="atr", stop_loss=2.5,
                                   take_profits=((2, 0.5), (4, 0.5)), breakeven_after=1))

res = evaluate(rule.signal_fn(), df, cfg)       # raises LookaheadError if the rule peeks
pf = simulate(res, Sizing(method="vol_target", target_vol=0.15, max_leverage=2))
Tearsheet.from_results(res, pf, title="RSI dip").save("rsi_dip.html")
```

```bash
quantlab fetch binance BTCUSDT ETHUSDT SOLUSDT --start 2024-01 --end 2024-12 --funding
quantlab quality binance/klines_1h                      # grade the data before trusting it
quantlab backtest donchian_breakout --data binance/klines_1h --study trend --tearsheet report.html
quantlab walkforward donchian_breakout --data binance/klines_1h --train 120 --test 30
quantlab import my_prices.csv --source broker --dataset daily     # your own files, columns detected
```

## Tech stack

| Layer | Built with |
|---|---|
| **Research core** | Python 3.11+, pandas, NumPy; a vectorized fast mode for large sweeps |
| **Data** | Parquet lake (PyArrow) queried in place with DuckDB SQL; Binance, Yahoo, CCXT, FRED and SEC EDGAR sources; CSV/Parquet import with column detection and quality grading |
| **Research UI** | Streamlit (13 pages), Plotly, standalone HTML tearsheets |
| **Live console** | Node.js 22, TypeScript (strict), Fastify, WebSockets, DuckDB embedded in Node, React 19 + Vite, hand-drawn SVG charts |
| **Quality** | 220+ tests (pytest and Vitest), ruff, strict `tsc`; every dashboard page rendered headlessly in CI; a cross-language contract test holding Python and Node to the same numbers |
| **Ops** | GitHub Actions (Python matrix, Node, contract, docs), MkDocs Material site on GitHub Pages, job heartbeats with freshness alerts, example systemd units |

## Architecture

```mermaid
flowchart LR
    subgraph Data
      SRC[Binance · Yahoo · CCXT<br/>FRED · CSV import]
      SEC[SEC EDGAR<br/>Forms 3/4/5]
      LAKE[(Parquet lake<br/>+ DuckDB views)]
      INS[(Insider store<br/>point in time)]
      VAULT[(Sealed vault)]
    end
    subgraph Strategy
      RULES[Rule language<br/>+ 35 indicators]
      PY[Python functions]
    end
    subgraph Engine
      CHK[Lookahead +<br/>symbol-leak checks]
      ENG[Execution model<br/>fills · costs · exits]
      PF[Portfolio sizing]
    end
    subgraph Validation
      REG[Trial registry<br/>K · rising bar · DSR]
      WF[Walk-forward · PBO<br/>permutation · SPA]
    end
    subgraph Console[Node.js console]
      WATCH[Watcher + WebSocket]
      JOBS[Job runner]
    end
    SRC --> LAKE
    SEC --> INS
    RULES & PY --> CHK
    LAKE --> CHK --> ENG --> PF --> REP[Tearsheets<br/>saved runs]
    ENG --> REG & WF
    VAULT -. registered run only .-> ENG
    REP & REG & WF & INS --> UI[Streamlit dashboard · CLI]
    REG & REP --> WATCH --> BROWSER[Browser]
    BROWSER --> JOBS -- spawns --> ENG
```

## Project layout

```
quantlab/
  engine.py         execution model, exits, integrity checks, summary statistics
  portfolio.py      dollar equity, sizing methods, leverage and margin limits, contract specs
  rules.py          the no-code rule language (safe AST evaluation, YAML round trip)
  indicators.py     35 causal indicators
  fast.py           a vectorized mode for large sweeps
  validation.py     walk-forward, PBO, Monte Carlo, Reality Check / SPA
  futures.py        continuous contracts and roll schedules
  options/          Black-Scholes and IV, chains (synthetic or ThetaData), multi-leg backtests
  events.py         event studies (market-model CARs, date-clustered t) and event strategies
  stats/            deflated Sharpe, PSR, Holm/BHY, Harvey-Liu, MinBTL, bootstrap, permutation nulls
  research/         trial registry, pre-registration, sealed vault, splits, saved runs
  report/           metrics, Plotly charts, HTML tearsheets
  data/             the lake, importers, quality reports, public sources
  sec/              EDGAR client (rate limited), Form 3/4/5 parser, point-in-time store
  monitor/          heartbeats and health checks
dashboard/          the Streamlit app (13 pages)
console/            the live console: Node.js + TypeScript server, React front end, Vitest suite
docs/               the documentation site (MkDocs Material)
deploy/             example systemd units for scheduled fetches and health checks
tests/              pytest: fill rules, lookahead detection, statistics against published values,
                    exits, sizing, options pricing, rules, every dashboard page
```

## Methodology

The [methodology page](https://skippy-8.github.io/quantlab/concepts/methodology/) explains each
control and what it protects against. Key references:

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*
- Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*
- Harvey & Liu (2015), *Backtesting*
- White (2000), *A Reality Check for Data Snooping*, and Hansen (2005), *A Test for Superior Predictive Ability*
- Cohen, Malloy & Pomorski (2012), *Decoding Inside Information*

## Scope

quantlab contains no proprietary strategies or data. The included strategies are textbook
examples, and all data is fetched from public sources or generated.

## License

MIT
