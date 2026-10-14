# Examples

Three runnable scripts. Each creates a throwaway workspace (its own home, lake and SEC
store under the system temp directory) and never touches your data. All three run offline
on synthetic data; the first two also accept `--live` to run the same pipeline on public data.

| Script | Shows | Live mode |
|---|---|---|
| [`01_macro_sql_and_qc.py`](01_macro_sql_and_qc.py) | Pre-flight QC on raw files (a planted duplicate, empty close and rate shock are each flagged), loading into the lake, then a cross-dataset DuckDB query: monthly asset returns by 10-year-yield regime, and drawdowns from a window function | FRED `DGS10` + Yahoo SPY, TLT, GLD (needs `[equities]`) |
| [`02_sec_event_study.py`](02_sec_event_study.py) | The point-in-time insider store (a filing is invisible one minute before its acceptance time), SQL across the attached store, and a market-model event study with date-clustered t, next to a placebo on random dates | Form 4s from EDGAR (needs `SEC_USER_AGENT`) + Yahoo prices |
| [`03_governance_and_vault.py`](03_governance_and_vault.py) | A rule strategy evaluated and recorded; two strategies refused with `LookaheadError` (one by truncation replay, one by symbol-reorder replay); a 60-cell search with the bar rising to 2.86; a holdout sealed, read once, refused a second time, and caught after tampering | — |

```bash
python examples/01_macro_sql_and_qc.py
python examples/01_macro_sql_and_qc.py --live
python examples/02_sec_event_study.py
python examples/03_governance_and_vault.py
```

On the live run of the first script, the grader flags the market closure for Hurricane Sandy
(29-30 October 2012) as a five-bar gap in every ETF and the March 2020 crash days as outliers,
and the regime table shows TLT up in 98% of falling-rate months and 3% of rising-rate months.

The synthetic event study plants a +15 bp/day drift for ten days after each purchase, so the
study has something to find; the placebo shows what the same machinery reports when there
is nothing. `tests/test_examples.py` runs all three offline on every CI build.
