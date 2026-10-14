# Data and quality

## The lake

```
data/lake/<source>/<dataset>/symbol=<SYMBOL>/data.parquet
```

One file per symbol, rewritten on update and de-duplicated on `(symbol, timestamp)`, so re-running a
fetch is idempotent. DuckDB reads it in place:

```python
from quantlab.data import Lake
con = Lake().duckdb()       # one view per dataset: <source>__<dataset>
con.execute("SELECT symbol, avg(quote_volume) FROM binance__klines_1h GROUP BY symbol").df()
```

Every read goes through the vault guard, so a sealed directory cannot be read through the lake by
accident.

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
