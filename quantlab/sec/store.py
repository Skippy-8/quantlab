"""DuckDB storage for insider transactions, point in time and idempotent.

* ``insider_transactions`` keys each row on (accession, owner, line), so
  re-ingesting a filing changes nothing.
* ``ingested_filings`` records every accession processed (including ones that
  yielded no rows), which makes a long backfill resumable.
* Every read helper filters on ``acceptance_datetime_utc``: the time the
  filing became public. ``as_of`` makes that explicit for backtests.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

COLUMNS = {
    "accession_number": "VARCHAR", "line": "INTEGER", "cik": "VARCHAR", "ticker": "VARCHAR",
    "form_type": "VARCHAR", "acceptance_datetime_utc": "TIMESTAMPTZ", "market_session": "VARCHAR",
    "filing_date": "DATE", "period_of_report": "DATE", "owner_cik": "VARCHAR", "owner_name": "VARCHAR",
    "officer_title": "VARCHAR", "is_director": "BOOLEAN", "is_officer": "BOOLEAN",
    "is_ten_percent_owner": "BOOLEAN", "aff10b5one": "BOOLEAN", "security_title": "VARCHAR",
    "transaction_date": "DATE", "transaction_code": "VARCHAR", "acquired_disposed": "VARCHAR",
    "shares": "DOUBLE", "price": "DOUBLE", "value_usd": "DOUBLE", "shares_owned_after": "DOUBLE",
    "direct_or_indirect": "VARCHAR", "in_10b5_1_footnote": "BOOLEAN", "plan_adoption_date": "DATE",
}


def default_path() -> Path:
    return Path(os.environ.get("QUANTLAB_SEC_DB", "data/sec/insider.duckdb"))


class InsiderStore:
    def __init__(self, path: str | Path | None = None, read_only: bool = False):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path), read_only=read_only)
        self.con.execute("SET TimeZone='UTC'")
        if not read_only:
            cols = ", ".join(f"{k} {v}" for k, v in COLUMNS.items())
            self.con.execute(f"CREATE TABLE IF NOT EXISTS insider_transactions ({cols}, "
                             "PRIMARY KEY (accession_number, owner_cik, line))")
            self.con.execute("CREATE TABLE IF NOT EXISTS ingested_filings (accession_number VARCHAR PRIMARY KEY, "
                             "ticker VARCHAR, form_type VARCHAR, rows INTEGER, ingested_utc TIMESTAMPTZ)")
            self.con.execute("CREATE INDEX IF NOT EXISTS ix_ins_ticker_acc ON insider_transactions "
                             "(ticker, acceptance_datetime_utc)")

    def known(self) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT accession_number FROM ingested_filings").fetchall()}

    def write(self, rows: list[dict], accession: str, ticker: str, form_type: str) -> int:
        if rows:
            df = pd.DataFrame(rows).reindex(columns=list(COLUMNS))
            self.con.register("incoming", df)
            self.con.execute("INSERT INTO insider_transactions SELECT * FROM incoming ON CONFLICT DO NOTHING")
            self.con.unregister("incoming")
        self.con.execute("INSERT INTO ingested_filings VALUES (?, ?, ?, ?, now()) ON CONFLICT DO NOTHING",
                         [accession, ticker, form_type, len(rows)])
        return len(rows)

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def as_of(self, ts, ticker: str | None = None) -> pd.DataFrame:
        """Every transaction PUBLIC at ``ts`` (acceptance <= ts)."""
        q = "SELECT * FROM insider_transactions WHERE acceptance_datetime_utc <= ?"
        p: list = [pd.Timestamp(ts, tz="UTC") if pd.Timestamp(ts).tzinfo is None else pd.Timestamp(ts)]
        if ticker:
            q += " AND ticker = ?"
            p.append(ticker.upper())
        return self.query(q + " ORDER BY acceptance_datetime_utc", p)

    def purchases(self, exclude_plans: bool = True) -> pd.DataFrame:
        """Open-market purchases, one row per insider per filing (split fills summed)."""
        plan = "AND NOT coalesce(aff10b5one, false) AND NOT coalesce(in_10b5_1_footnote, false)" if exclude_plans else ""
        return self.query(f"""
            SELECT ticker, owner_cik, any_value(owner_name) AS owner_name, accession_number,
                   min(acceptance_datetime_utc) AS public_at, min(transaction_date) AS first_trade,
                   bool_or(is_officer) AS officer, bool_or(is_director) AS director,
                   bool_or(is_ten_percent_owner) AS ten_pct, any_value(officer_title) AS title,
                   sum(shares) AS shares, sum(value_usd) AS value_usd, max(shares_owned_after) AS owned_after
            FROM insider_transactions
            WHERE transaction_code = 'P' AND acquired_disposed = 'A' {plan}
            GROUP BY ticker, owner_cik, accession_number
            ORDER BY public_at""")

    def summary(self) -> dict:
        n, f, t, lo, hi = self.con.execute(
            "SELECT count(*), count(DISTINCT accession_number), count(DISTINCT ticker), "
            "min(acceptance_datetime_utc), max(acceptance_datetime_utc) FROM insider_transactions").fetchone()
        return {"rows": n, "filings": f, "tickers": t, "first": lo, "last": hi,
                "ingested": self.con.execute("SELECT count(*) FROM ingested_filings").fetchone()[0]}

    def close(self) -> None:
        self.con.close()
