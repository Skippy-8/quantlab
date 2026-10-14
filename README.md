<h1 align="center">quantlab</h1>

<p align="center"><b>Backtests that can't lie to you.</b></p>

<p align="center">
An end-to-end financial data platform and quantitative research engine:<br/>
Hive-partitioned DuckDB/Parquet data lake · Automated data-quality &amp; schema profiling · Deterministic execution · Multiple-testing governance · 13-page analytics suite &amp; live Node.js console.
</p>

<p align="center">
  <a href="https://github.com/Skippy-8/quantlab/actions/workflows/ci.yml"><img src="https://github.com/Skippy-8/quantlab/actions/workflows/ci.yml/badge.svg" alt="ci"/></a>
  <a href="https://skippy-8.github.io/quantlab/"><img src="https://img.shields.io/badge/docs-live-3550c8" alt="docs"/></a>
  <img src="https://img.shields.io/badge/tests-239-14805e" alt="239 tests"/>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-3550c8" alt="python 3.11 | 3.12"/>
  <img src="https://img.shields.io/badge/node-22-3550c8" alt="node 22"/>
  <img src="https://img.shields.io/badge/typescript-strict-3550c8" alt="typescript strict"/>
  <img src="https://img.shields.io/badge/license-MIT-6b7280" alt="MIT"/>
</p>

<p align="center">
  <a href="https://skippy-8.github.io/quantlab/"><b>Documentation</b></a> ·
  <a href="#why-quantlab-exists">Why It Exists</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#verification-in-practice">Data QC &amp; Validation</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#cli-reference">CLI Reference</a> ·
  <a href="console/">Live Console</a>
</p>

![The Backtest Lab](docs/images/backtest-light.png)

## Why quantlab exists

A financial analysis or backtest is only as credible as the weakest step that produced it. Standard
research pipelines fail silently in four places: they ingest unverified feeds, leak future data across
timestamps, assume unrealistic fills, and report the winner of hundreds of parameter trials as if it
were the only idea tested.

**quantlab** turns each failure mode into an enforced invariant: a pipeline or strategy run that
violates one is refused rather than reported.

| Pillar | Standard pipeline | quantlab invariant |
|---|---|---|
| **1. Data integrity and point-in-time isolation** | Raw feeds ingested as delivered; tables trusted without schema or null audits. | `quantlab quality` grades every symbol for gaps, duplicate timestamps, impossible bars (`high < low`, non-positive prices), empty values, robust-SD outliers and unadjusted splits, plus a schema and per-column completeness profile for any table or SQL query. SEC Form 3/4/5 filings are keyed on acceptance time, so a historical query returns only what was public then. |
| **2. Temporal and cross-sectional causality** | Lookahead reviewed by eye, if at all. | Every strategy is replayed on truncated histories and on a reversed symbol order before any P&L is scored. If a single past signal changes, `evaluate()` raises `LookaheadError` naming the symbol and timestamp. |
| **3. Microstructure-aware execution** | Limit orders fill whenever a bar touches the price; flat or zero costs. | One deterministic execution model (it draws no random numbers): limit orders fill only when price trades *through* them within a time-to-live, with a taker fallback on expiry; fills are against the bid and ask (an assumed half-spread, flagged in the summary, when the data has no quotes). Maker/taker fees, perpetual funding, short borrow and futures rolls are charged; target ladders fill partially, stops gap to the open, and options are marked at mid, quarter and natural. |
| **4. Multiple-testing governance and vault sealing** | The best parameter cell is reported against a static t > 2; holdouts are reused. | A central registry counts every distinct variant (K) per study and scales the significance bar as `max(2, √(2 ln K))`. Grid searches face a whole-search permutation null, backed by DSR, PBO (CSCV), White's Reality Check, Hansen's SPA and walk-forward stitching; the final holdout is sealed by a SHA-256 manifest and opens once per pre-registered spec. |

## Platform highlights

- **Read-only DuckDB SQL lake and multi-source ingestion.** FRED macro series, rate-limited SEC
  EDGAR Form 3/4/5 filings, equities and ETFs (Yahoo), crypto perpetuals (Binance, CCXT) and
  schema-detected CSV/Parquet files land in Hive-partitioned Parquet. It is queried through DuckDB
  views (`quantlab sql`, `Lake.sql()`) that accept one `SELECT` at a time, refuse every write
  statement, and give sealed vault datasets no view at all.
- **Self-service YAML rules and reproducible tearsheets.** Strategy rules read as expressions
  (`rsi(14) < 30 and close > sma(200)`), are validated against an `ast` node allow-list, and are
  versioned as YAML, so someone who does not write Python can author and review them. Any run exports
  as a standalone HTML tearsheet, and every saved run records its code version and data fingerprint.
- **Observability and operations.** A strict TypeScript / Node.js 22 / React 19 console streams
  trials, runs and job heartbeats over WebSockets and reads run artefacts through DuckDB embedded in
  Node. Freshness checks (`OK` / `RUNNING` / `FAILING` / `STALE`) exit non-zero for cron and systemd
  alerting.

## Architecture

```mermaid
flowchart LR
    subgraph ING["Ingestion"]
      SRC["FRED · SEC EDGAR · Yahoo<br/>Binance · CCXT · CSV/Parquet"]
      QC["Quality grading<br/>gaps · bad bars · outliers · splits"]
    end
    subgraph STORE["Storage"]
      LAKE[("Parquet lake<br/>DuckDB SQL views")]
      INS[("Insider store<br/>point in time")]
      VAULT[("Sealed vault<br/>SHA-256 manifest")]
    end
    subgraph EXEC["Execution"]
      RULES["Rule language<br/>35 causal indicators"]
      CHK["Causality checks<br/>truncation · symbol order"]
      ENG["Execution engine<br/>fills · costs · exits"]
      PF["Portfolio sizing<br/>leverage · margin · contracts"]
    end
    subgraph GOV["Governance"]
      REG["Trial registry<br/>K · bar · DSR"]
      VAL["Walk-forward · PBO<br/>permutation · RC/SPA"]
    end
    subgraph SURF["Surfaces"]
      DASH["Streamlit dashboard<br/>13 pages"]
      REP["HTML tearsheets<br/>saved runs"]
      CON["Node.js console<br/>WebSocket stream"]
    end
    SRC --> QC --> LAKE
    SRC --> INS
    LAKE --> CHK
    RULES --> CHK --> ENG --> PF --> REP
    ENG --> REG & VAL
    VAULT -. registered run only .-> ENG
    LAKE & INS & REG & VAL & REP --> DASH
    REG & REP --> CON
    CON -- launches --> ENG
```

| Layer | Core modules | Capabilities and invariants |
|---|---|---|
| **Ingestion and columnar lake** | `quantlab/data`, `quantlab/sec` | **Lake and SQL:** Hive-partitioned Parquet with one read-only DuckDB view per dataset (a single `SELECT` per call; sealed vault datasets get no view) and atomic, idempotent per-symbol upserts.<br/>**QC and regulatory ingestion:** per-symbol bar grading plus a schema and completeness profile for any table. The EDGAR client runs under a shared 8 req/s token bucket with `Retry-After` backoff; filings are keyed on `(accession, owner, line)` and queried by acceptance time. |
| **Execution and portfolio** | `engine.py`, `portfolio.py`, `futures.py`, `options/`, `events.py` | **Execution:** through-the-limit fills with TTL and taker fallback; fee, funding, borrow and roll accounting; stop, target-ladder, breakeven, trailing and time exits with partial fills.<br/>**Sizing and asset classes:** fixed notional, fixed fraction, volatility target or risk per trade, under leverage, position and margin limits. Continuous futures, 13 option structures (Black-Scholes or ThetaData chains), and market-model event studies with date-clustered t. |
| **Declarative rule engine** | `rules.py`, `indicators.py` | **AST allow-list:** expressions parsed with Python's `ast` against a fixed set of node types and serialised to YAML, over 35 indicators computed per symbol from past data only. |
| **Statistical governance and vault** | `stats/`, `validation.py`, `research/` | **Overfitting controls:** distinct-trial registry (K) with a rising bar; PSR, DSR, Holm, BHY, Harvey-Liu haircut and MinBTL; whole-search permutation nulls; PBO by CSCV; White's Reality Check and Hansen's SPA on a stationary bootstrap; block Monte Carlo; walk-forward; spec-hash pre-registration and the one-shot SHA-256 vault. |
| **Analytics UI and reporting** | `dashboard/`, `report/` | **Decision surfaces:** 13 Streamlit pages in light and dark themes, interactive Plotly charts, standalone HTML tearsheets, and saved runs stamped with code version and data fingerprint. |
| **Real-time console and operations** | `console/`, `monitor/`, `deploy/` | **Live monitoring:** Fastify and WebSocket server in strict TypeScript, DuckDB embedded in Node, React 19 front end. Job heartbeats (`OK` / `RUNNING` / `FAILING` / `STALE`), health checks that exit non-zero for cron and systemd alerting, and example systemd timers. |

## Verification in practice

Two runs against public data, from the CLI. The quality report's two tables are condensed into one,
with timestamps shortened to dates.

### Pre-flight data QC

Ten years of the 10-year Treasury yield (`DGS10`) and the civilian unemployment rate (`UNRATE`), from
FRED:

```text
$ quantlab fetch fred DGS10 UNRATE --start 2015-01
$ quantlab quality fred/series
symbol  bars       first        last  grade  outlier
 DGS10  2946  2015-01-02  2026-10-13      C        4
UNRATE   140  2015-01-01  2026-09-01      B        1
 DGS10  outlier  2020-03-09   -27.0% in one bar (17 robust sd)
 DGS10  outlier  2020-03-10   +40.7% in one bar (18 robust sd)
UNRATE  outlier  2020-04-01  +236.4% in one bar (34 robust sd)
```

Every flag falls in March or April 2020, at 17 to 34 robust standard deviations. These are genuine
macro shocks, not bad prints. The grader reports them with their dates and magnitudes and removes
nothing, so whether a study includes the COVID-19 regime remains an explicit analyst decision rather
than a silent side effect of ingestion.

### Whole-search permutation null

A six-cell Donchian breakout grid on six Binance perpetuals, hourly bars, calendar year 2024:

```text
$ quantlab search donchian_breakout --data binance/klines_1h --study trend --perm 200
best cell window=100,exit_window=20: day_t 1.33
whole-search permutation p = 0.488 over 200 shuffles (null best median 1.29)
study 'trend': K = 6, bar 2.00
```

The winning cell reaches t = 1.33. The null re-runs the entire six-cell search 200 times with each
symbol's signal circularly shifted against its prices, which breaks any real timing while preserving
the signal's autocorrelation. The best null cell matches or beats 1.33 in **48.8%** of runs (median
1.29), so the result is what a search of this size produces by chance. It is logged in the registry as
one of K = 6 trials against a bar of 2.00.

## Interface and observability

<table>
<tr>
<td width="50%"><img src="docs/images/console-live-light.png" alt="Live console"/><br/><sub><b>Live console.</b> A Node watcher tails the registry and heartbeat logs by byte offset, consuming whole lines only, and pushes each new trial, run and job state over a WebSocket.</sub></td>
<td width="50%"><img src="docs/images/console-run-dark.png" alt="Run detail"/><br/><sub><b>Run detail.</b> Daily equity, drawdown, exits and per-symbol P&amp;L, aggregated in SQL by DuckDB embedded in the Node process, reading the run's Parquet files in place.</sub></td>
</tr>
<tr>
<td><img src="docs/images/optimize-light.png" alt="Parameter Search"/><br/><sub><b>Parameter Search.</b> Every cell is recorded as a trial; the Sharpe surface is shown with the whole-search null and PBO, because a real edge is a plateau, not a peak.</sub></td>
<td><img src="docs/images/walkforward-light.png" alt="Walk-Forward"/><br/><sub><b>Walk-Forward.</b> Parameters selected on each training window with the vectorized engine, confirmed by the full engine on the next unseen window, and stitched out of sample.</sub></td>
</tr>
<tr>
<td><img src="docs/images/options-light.png" alt="Options Lab"/><br/><sub><b>Options Lab.</b> Thirteen structures with legs chosen by delta, moneyness or strike offset; the same trades priced at mid, quarter and natural.</sub></td>
<td><img src="docs/images/console-launch-light.png" alt="Launch"/><br/><sub><b>Launch.</b> Requests are schema-validated with unknown fields rejected and every argument allow-listed, then the CLI is spawned from an argv array with no shell; output streams line by line and the verdict is parsed.</sub></td>
</tr>
</table>

## Quickstart

**1. Install and load demo data** (Python 3.11+):

```bash
git clone https://github.com/Skippy-8/quantlab && cd quantlab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dashboard,equities,dev]"     # or: make install (adds the docs extra and the console)
quantlab fetch synthetic                        # demo data into the lake, no network needed
```

**2. Run the end-to-end examples.** Three scripts in [`examples/`](examples/), offline by default:
macro regimes in SQL with pre-flight QC, a point-in-time SEC insider event study against a placebo,
and the governance path from `LookaheadError` to a sealed holdout vault.

```bash
python examples/01_macro_sql_and_qc.py --live  # FRED + Yahoo; omit --live for synthetic data
make help                                      # test, lint, contract, docs, dashboard, console ...
```

**3. Launch the analytics dashboard or the live console:**

```bash
streamlit run dashboard/app.py                  # the 13-page Streamlit dashboard

cd console && npm install && npm run build      # the Node.js 22 + React 19 console
QUANTLAB_HOME=../.quantlab QUANTLAB_LAKE=../data/lake QUANTLAB_CLI=../.venv/bin/quantlab npm start
# → http://127.0.0.1:8787
```

**4. Query with SQL and evaluate a strategy in Python:**

```python
from quantlab import evaluate
from quantlab.data import Lake
from quantlab.engine import EngineConfig, ExitRules
from quantlab.portfolio import Sizing, simulate
from quantlab.report.tearsheet import Tearsheet
from quantlab.rules import RuleStrategy

lake = Lake()                                   # after: quantlab fetch yahoo SPY TLT GLD --start 2015-01-01
vol = lake.sql("""
    SELECT symbol, round(100 * stddev(r) * sqrt(252), 1) AS ann_vol_pct
    FROM (SELECT symbol, close / lag(close) OVER (PARTITION BY symbol ORDER BY timestamp) - 1 AS r
          FROM yahoo__daily)
    GROUP BY symbol ORDER BY ann_vol_pct DESC""")

rule = RuleStrategy("RSI dip", long_entry="rsi(14) < 30 and close > sma(200)", long_exit="rsi(14) > 55")
cfg = EngineConfig(days_per_year=252, exits=ExitRules(unit="atr", stop_loss=2.5,
                                                      take_profits=((2, 0.5), (4, 0.5)), breakeven_after=1))
res = evaluate(rule.signal_fn(), lake.read("yahoo", "daily"), cfg)   # raises LookaheadError if the rule peeks
pf = simulate(res, Sizing(method="vol_target", target_vol=0.10, max_leverage=1))
Tearsheet.from_results(res, pf, title="RSI dip on ETFs").save("rsi_dip.html")
```

## CLI reference

| Command | Example | Purpose |
|---|---|---|
| `fetch` | `quantlab fetch fred DGS10 CPIAUCSL UNRATE --start 2010-01` | Ingest from `synthetic`, `binance` (with `--funding`), `yahoo`, `fred` or `ccxt` (`--exchange`) |
| `sec sync` | `quantlab sec sync AAPL MSFT NVDA --since 2022-01-01` | Backfill Forms 3/4/5 into the point-in-time store (needs `SEC_USER_AGENT`) |
| `import` | `quantlab import prices.csv --source broker --dataset daily` | Load any CSV/Parquet; columns detected, times stored in UTC |
| `sql` | `quantlab sql "SELECT symbol, avg(close) FROM yahoo__daily GROUP BY 1" --format csv` | One read-only query over the lake views and the `sec.*` insider tables; `--export` to CSV, Parquet or JSON; `--tables` lists what can be queried |
| `quality` | `quantlab quality yahoo/daily` | Grade each symbol, list every finding, and profile the schema and column completeness; `--sql` profiles any query result, such as `sec.insider_transactions` |
| `catalog` | `quantlab catalog` | Datasets, row counts, symbols and date ranges in the lake |
| `backtest` | `quantlab backtest donchian_breakout --data yahoo/daily --study etf --tearsheet report.html` | One leak-checked run, recorded in the study and judged against its bar; `--rules file.yaml` for a rule strategy, `--save` to keep it |
| `search` | `quantlab search bollinger_reversion --data yahoo/daily --study etf --perm 200` | Sweep a template's grid, record every cell, and run the whole-search permutation null |
| `walkforward` | `quantlab walkforward donchian_breakout --data yahoo/daily --train 750 --test 250` | Rolling out-of-sample parameter selection and stitched evaluation |
| `options` | `quantlab options iron_condor --days 250 --every 5 --hold 14` | Backtest a multi-leg option structure, priced at mid, quarter and natural |
| `registry` | `quantlab registry --study etf --json` | Recorded trials, distinct K and the current bar per study |
| `prereg` | `quantlab prereg etf prereg/etf-trend.md` | Register a written spec by its SHA-256 hash before running it |
| `vault` | `quantlab vault seal data/vault` | Seal, verify or audit the one-shot out-of-sample vault |
| `monitor` | `quantlab monitor --job fetch_fred=24 --data yahoo/daily=36` | Job heartbeats and data freshness; exits non-zero on anything not OK |
| `strategies` | `quantlab strategies --json` | Built-in templates, their defaults and parameter grids |

## Deep dives

<details>
<summary><b>The 13-page analytics dashboard</b></summary>

<br/>

| Group | Page | Decision it supports |
|---|---|---|
| | **Overview** | Platform state (datasets, studies, distinct trials, saved runs, completed jobs) and what each step guards against |
| Build | **Strategy Builder** | Author rules, validate them against data for causality, save as YAML |
| | **Backtest Lab** | Configure data, strategy, exits, costs and sizing. The verdict against the study's bar, with equity, drawdown, rolling Sharpe, monthly returns, trade map, robustness and splits. Export a tearsheet or save the run |
| Validate | **Parameter Search** | Whether the best cell beats the best cell of the same search on shifted signals; the probability of backtest overfitting; the Sharpe surface |
| | **Walk-Forward** | Whether parameters chosen on the past hold on the next window |
| | **Robustness** | Monte Carlo drawdown and outcome ranges; Reality Check and SPA across saved runs |
| | **Compare Runs** | Saved runs side by side, with their manifests |
| Markets | **Options Lab** | Structure P&L on synthetic or ThetaData chains, and how much of it the spread consumes |
| | **Event Studies** | Cumulative abnormal returns around uploaded, earnings or insider events; trade them through the engine |
| | **Insider Filings** | Open-market purchases by role, cluster buys, a point-in-time view |
| Data | **Data Manager** | Catalog and coverage, file import, public fetchers, quality grades and completeness, continuous futures, SQL console |
| Governance | **Research Registry** | Each trial against the bar it faces as K grows; pre-registration |
| | **Monitoring** | Job heartbeats and data freshness |

Every page is rendered headlessly in CI, and its main action is executed.
</details>

<details>
<summary><b>The declarative rule language and its 35 indicators</b></summary>

<br/>

A strategy can be written by someone who does not write Python, reviewed in a pull request, and
reproduced exactly:

```yaml
name: RSI dip in an uptrend
long_entry:  rsi(14) < 30 and close > sma(200)
long_exit:   rsi(14) > 55
exits: {unit: atr, stop_loss: 2, take_profits: [[2, 0.5], [4, 0.5]], breakeven_after: 1}
```

- **Grammar:** price and volume columns, indicator calls, `crosses_above` / `crosses_below`,
  arithmetic, comparisons, and `and` / `or` / `not`.
- **Safety:** expressions are parsed with Python's `ast`, and only those node types are admitted.
  Attribute access, subscripts, lambdas, imports and unknown names are rejected, so a rule file
  cannot execute arbitrary code.
- **Causality:** every indicator is computed per symbol from past data only, and every rule still
  passes through the engine's truncation and symbol-order replay.

Indicators: `adx` `atr` `bb_lower` `bb_pct` `bb_upper` `cci` `donchian_high` `donchian_low` `ema`
`highest` `hma` `keltner_lower` `keltner_upper` `lag` `lowest` `macd` `macd_hist` `macd_signal` `mfi`
`momentum` `natr` `obv` `realized_vol` `roc` `rsi` `sma` `stoch_d` `stoch_k` `supertrend_dir`
`true_range` `volume_z` `vwap` `williams_r` `wma` `zscore`.
</details>

<details>
<summary><b>Testing, the cross-language contract and CI</b></summary>

<br/>

239 tests: 193 in pytest and 46 in Vitest.

- **Execution:** fill rules (through-the-limit, TTL expiry, taker fallback), exits with partial fills
  and gap-through-stop handling, stop-before-target ordering within a bar, borrow and roll costs;
  sizing methods, leverage and position limits, whole-contract rounding.
- **Statistics:** checked against published values, including DSR, PSR, Holm, BHY and the noise
  bar; the Reality Check rejection rate under a true null across seeds.
- **Integrity:** lookahead and symbol-leak detection on deliberately leaking strategies; vault
  sealing and one-shot runs; idempotent lake upserts; the SEC parser on raw ownership XML.
- **SQL and QC:** cross-dataset joins and window functions checked against pandas; every write path
  (`COPY`, `CREATE`, `INSERT`, `DROP`, `ATTACH`, multiple statements) refused; sealed datasets
  unreachable from SQL; the SEC store attached read-only; completeness and schema profiling on
  non-price tables.
- **Dashboard:** every Streamlit page rendered headlessly with its main action executed.
- **Examples:** all three scripts run offline and their key claims are asserted.
- **Console:** byte-offset tailing (partial lines, multi-byte characters split across reads, file
  rotation), the registry and heartbeat state, argument allow-listing against injection attempts,
  the job lifecycle (timeouts, crashes, queueing), and the HTTP and WebSocket API against a fixture
  home built with DuckDB.
- **Cross-language contract:** CI has the Python CLI write a real research home, then requires the
  Node service to match `quantlab registry --json` on every study's runs, K and bar, and to read
  every saved run.

GitHub Actions runs four jobs on every push: Python 3.11 and 3.12 (ruff, pytest, an end-to-end CLI
smoke test), Node (strict `tsc`, Vitest, production build), and the contract. A fifth workflow builds
the documentation with `mkdocs --strict` and publishes it to GitHub Pages.
</details>

## Repository layout

```text
quantlab/
  engine.py         execution model, exits, causality checks, summary statistics
  portfolio.py      dollar equity, sizing methods, leverage and margin limits, contract specs
  rules.py          the rule language: allow-listed AST evaluation, YAML round trip
  indicators.py     35 causal indicators
  fast.py           a vectorized engine for large sweeps
  validation.py     walk-forward, PBO, Monte Carlo, Reality Check / SPA
  futures.py        continuous contracts and roll schedules
  options/          Black-Scholes and implied volatility, chains, multi-leg backtests
  events.py         market-model event studies and event-driven strategies
  stats/            DSR, PSR, Holm/BHY, Harvey-Liu, MinBTL, bootstrap, permutation nulls
  research/         trial registry, pre-registration, sealed vault, splits, saved runs
  report/           metrics, Plotly charts, HTML tearsheets
  data/             the lake and its read-only SQL, importers, quality grading and profiling, sources
  sec/              EDGAR client, Form 3/4/5 parser, point-in-time store
  monitor/          heartbeats and health checks
examples/           three runnable end-to-end scripts (macro SQL + QC, SEC event study, governance)
dashboard/          Streamlit application, 13 pages
console/            Node.js + TypeScript service, React front end, Vitest suite
docs/               MkDocs Material documentation site
deploy/             example systemd services and timers
tests/              pytest suite
Makefile            install, test, lint, contract, docs, dashboard and console targets
```

## References

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality*
- Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*
- Harvey & Liu (2015), *Backtesting*
- White (2000), *A Reality Check for Data Snooping*
- Hansen (2005), *A Test for Superior Predictive Ability*
- Cohen, Malloy & Pomorski (2012), *Decoding Inside Information*

The [methodology page](https://skippy-8.github.io/quantlab/concepts/methodology/) maps each control
to the failure it prevents.

## Scope and license

quantlab contains no proprietary strategies or data. The bundled strategies are textbook templates,
and all data is fetched from public sources or generated. MIT licensed.
