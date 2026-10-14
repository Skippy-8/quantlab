# Data and quality

## The lake

```
data/lake/<source>/<dataset>/symbol=<SYMBOL>/data.parquet
```

One file per symbol, rewritten on update and de-duplicated on `(symbol, timestamp)`, so re-running a
fetch is idempotent.

## SQL

DuckDB reads the lake in place, with one view per dataset named `<source>__<dataset>`. The insider
store, when present, is attached read-only as schema `sec`.

```bash
quantlab sql --tables
quantlab sql "SELECT symbol, round(100 * min(close / peak - 1), 1) AS max_dd_pct
              FROM (SELECT symbol, close, max(close) OVER (PARTITION BY symbol ORDER BY timestamp) AS peak
                    FROM yahoo__daily) GROUP BY 1" --format table
quantlab sql "SELECT * FROM fred__series WHERE symbol = 'DGS10'" --export dgs10.parquet
```

```python
from quantlab.data import Lake
Lake().sql("SELECT symbol, count(*) FROM yahoo__daily GROUP BY 1")      # a DataFrame
```

Queries are read-only by construction: `Lake.sql` parses the text first and accepts exactly one
`SELECT` (or `WITH ... SELECT`). `COPY`, `CREATE`, `INSERT`, `ATTACH`, `PRAGMA` and multi-statement
input are refused before anything runs.

Every read goes through the vault guard. `Lake.read` raises on a sealed directory, and a sealed
dataset gets no SQL view (and is left out of the catalog) unless a registered vault run is open, so
SQL cannot be used to look at the holdout either.

## Sources

| Command | Data |
|---|---|
| `quantlab fetch binance SYMS --start YYYY-MM --end YYYY-MM [--funding]` | Binance public archive (spot or USD-M futures), including delisted symbols |
| `quantlab fetch yahoo TICKERS --start DATE` | Daily US equities (split/dividend adjusted) |
| `quantlab fetch fred SERIES --start YYYY-MM` | FRED macro series (DGS10, CPIAUCSL, UNRATE, ...), stored as bars so quality checks and SQL treat them like prices |
| `quantlab fetch ccxt PAIRS --exchange ID --interval 1h` | OHLCV from any exchange the ccxt library supports |
| `ccxt_ohlcv(exchange, pairs, ...)` | Any of 100+ exchanges via CCXT |
| `fred_series("DGS10")` | FRED macro series |
| `quantlab import FILE` | Your CSV/Parquet: `Date`/`time`/`timestamp`, `Open`/`High`/`Low`/`Close`, `Volume`, `Ticker`/`Symbol` and other aliases are detected; epoch seconds/ms/µs and zoned or naive dates are parsed to UTC |

## Quality checks

```bash
quantlab quality binance/klines_1h      # exits non-zero if any symbol grades C or D
```

| Check | Catches |
|---|---|
| Gaps | missing bars longer than the usual step (a feed outage looks like a quiet market) |
| Duplicates | two rows for one `(symbol, timestamp)` |
| Bad bars | high < low, close outside the range, non-positive prices |
| Outliers | one-bar returns beyond 12 robust (MAD) standard deviations |
| Suspected splits | a one-bar jump close to a split ratio that does not revert: unadjusted splits look like crashes |
| Missing | a bar with an empty open, high, low or close (NaN passes every comparison, so the checks above miss it) |

Grades: **A** no findings; **B** up to three non-severe findings; **C** more; **D** any bad bar,
duplicate or suspected split. Each symbol also reports `complete_pct`, its share of bars with all four
prices present.

### Schema and completeness, for any table

`quality.profile(df)` needs no particular columns. It reports the row and column counts, symbols,
time range and median step, and per column the type, non-null share, null count, distinct values
and range. The CLI applies it to any query result, which makes it a check for filings and macro
tables as much as for prices:

```bash
quantlab quality --sql "SELECT * FROM sec.insider_transactions"
```
