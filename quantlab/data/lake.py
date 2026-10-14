"""A Parquet data lake with a DuckDB catalog.

Layout::

    <root>/<source>/<dataset>/symbol=<SYMBOL>/data.parquet

One file per (source, dataset, symbol), rewritten on update with rows de-duplicated
on ``(symbol, timestamp)``, so re-running a fetch is idempotent. DuckDB reads the
whole lake in place through hive-partitioned globs; nothing is copied into a
database file. ``catalog()`` reports rows, span and last update for every
dataset, which is what the freshness monitor checks.

Every read goes through the vault guard, so a sealed directory cannot be read
by accident through the lake either.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from quantlab.research.vault import VaultError, guard


def default_root() -> Path:
    return Path(os.environ.get("QUANTLAB_LAKE", "data/lake"))


class Lake:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else default_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, source: str, dataset: str) -> Path:
        return self.root / source / dataset

    # ── write ───────────────────────────────────────────────────────────────
    def write(self, source: str, dataset: str, df: pd.DataFrame) -> dict:
        """Upsert rows: merge with what is stored, drop duplicate (symbol, timestamp)."""
        if df.empty:
            return {"symbols": 0, "rows": 0}
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        n = 0
        for sym, g in df.groupby("symbol"):
            d = self._dir(source, dataset) / f"symbol={sym}"
            d.mkdir(parents=True, exist_ok=True)
            f = d / "data.parquet"
            g = g.drop(columns=["symbol"])
            if f.exists():
                g = pd.concat([pd.read_parquet(f), g], ignore_index=True)
            g = g.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
            tmp = f.with_suffix(".tmp")
            g.to_parquet(tmp, index=False)
            os.replace(tmp, f)
            n += len(g)
        return {"symbols": int(df["symbol"].nunique()), "rows": int(n)}

    # ── read ────────────────────────────────────────────────────────────────
    def symbols(self, source: str, dataset: str) -> list[str]:
        d = self._dir(source, dataset)
        return sorted(p.name.split("=", 1)[1] for p in d.glob("symbol=*")) if d.exists() else []

    def read(self, source: str, dataset: str, symbols: list[str] | None = None,
             start=None, end=None) -> pd.DataFrame:
        d = self._dir(source, dataset)
        guard(d)
        frames = []
        for sym in symbols or self.symbols(source, dataset):
            f = d / f"symbol={sym}" / "data.parquet"
            if f.exists():
                frames.append(pd.read_parquet(f).assign(symbol=sym))
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        if start is not None:
            df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            df = df[df["timestamp"] < pd.Timestamp(end, tz="UTC")]
        return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    # ── SQL ─────────────────────────────────────────────────────────────────
    def datasets(self) -> list[tuple[str, str]]:
        return sorted((p.parent.name, p.name) for p in self.root.glob("*/*") if p.is_dir()
                      and any(p.glob("symbol=*/data.parquet")))

    def readable(self) -> list[tuple[str, str]]:
        """Datasets that may be read now: everything except a sealed vault outside an open run."""
        out = []
        for source, dataset in self.datasets():
            try:
                guard(self._dir(source, dataset))
            except VaultError:
                continue
            out.append((source, dataset))
        return out

    def duckdb(self, sec_db: str | Path | None = None) -> duckdb.DuckDBPyConnection:
        """An in-memory DuckDB with one view per readable dataset, named ``<source>__<dataset>``.

        Sealed vault datasets get no view, so SQL cannot bypass the vault. With ``sec_db``, the
        point-in-time insider store is attached read-only as schema ``sec``.
        """
        con = duckdb.connect()
        con.execute("SET TimeZone='UTC'")
        for source, dataset in self.readable():
            glob = (self._dir(source, dataset) / "symbol=*" / "data.parquet").as_posix().replace("'", "''")
            con.execute(f'CREATE VIEW "{source}__{dataset}" AS '
                        f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
        if sec_db is not None and Path(sec_db).exists():
            path = Path(sec_db).as_posix().replace("'", "''")
            con.execute(f"ATTACH '{path}' AS sec (READ_ONLY)")
        return con

    def tables(self, sec_db: str | Path | None = None) -> pd.DataFrame:
        """Every relation a query can use: lake views and, when attached, the SEC tables."""
        return self.duckdb(sec_db).execute(
            "SELECT view_name AS name, 'lake view' AS kind FROM duckdb_views() "
            "WHERE NOT internal AND database_name = 'memory' "
            "UNION ALL SELECT 'sec.' || table_name, 'sec table' FROM duckdb_tables() WHERE database_name = 'sec' "
            "ORDER BY kind, name").df()

    def sql(self, query: str, sec_db: str | Path | None = None) -> pd.DataFrame:
        """Run ONE read-only query (SELECT, or WITH ... SELECT) over the lake views.

        Anything else (COPY, CREATE, INSERT, ATTACH, PRAGMA, several statements) is refused
        before it runs, so a query can read the lake but never write to it or to disk.
        """
        con = self.duckdb(sec_db)
        stmts = con.extract_statements(query)
        if len(stmts) != 1:
            raise ValueError(f"expected one SQL statement, got {len(stmts)}")
        if stmts[0].type != duckdb.StatementType.SELECT:
            raise ValueError(f"only read-only SELECT queries are allowed, not {stmts[0].type.name}")
        return con.execute(query).df()

    def catalog(self) -> pd.DataFrame:
        rows = []
        con = self.duckdb()
        for source, dataset in self.readable():
            v = f'"{source}__{dataset}"'
            n, syms, lo, hi = con.execute(
                f"SELECT count(*), count(DISTINCT symbol), min(timestamp), max(timestamp) FROM {v}").fetchone()
            files = list(self._dir(source, dataset).glob("symbol=*/data.parquet"))
            updated = max(f.stat().st_mtime for f in files)
            rows.append({"source": source, "dataset": dataset, "rows": n, "symbols": syms,
                         "first": pd.Timestamp(lo), "last": pd.Timestamp(hi),
                         "updated_utc": datetime.fromtimestamp(updated, timezone.utc),
                         "size_mb": round(sum(f.stat().st_size for f in files) / 1e6, 2)})
        return pd.DataFrame(rows)
