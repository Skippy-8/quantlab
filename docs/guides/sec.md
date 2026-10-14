# SEC insider filings

A point-in-time pipeline for Forms 3, 4 and 5.

```bash
export SEC_USER_AGENT="Your Name you@example.com"     # SEC requires a real contact
quantlab sec sync AAPL MSFT NVDA --since 2020-01-01
```

* **Fetching** respects SEC fair access: a shared token bucket at 8 requests a second and
  `Retry-After`-aware backoff. Each company's `submissions` JSON is paged back to `--since`.
* **Raw XML**: EDGAR's `primaryDocument` for these forms points at an XSL-rendered page; the parser
  strips that prefix and reads the raw `ownershipDocument`.
* **Rows** carry the reporting owner, role (officer, director, 10% owner, title), transaction code,
  shares, price, holdings afterwards, direct/indirect ownership, the Rule 10b5-1 checkbox (from April
  2023), and whether the row cites a 10b5-1 footnote, with the plan's adoption date when given.
* **Storage** is DuckDB keyed on `(accession, owner, line)`, so re-ingesting changes nothing, and
  `ingested_filings` makes a long backfill resumable.
* **Point in time**: every read filters on `acceptance_datetime_utc`. `InsiderStore.as_of(ts)` returns
  exactly what was public at `ts`; `purchases()` returns open-market buys, one per insider per filing,
  with pre-planned trades excluded by default.

Insider purchases can feed [event studies](events.md) directly with `events.insider_purchases(store)`.
