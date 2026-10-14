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

from quantlab.research.vault import guard


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

    def duckdb(self) -> duckdb.DuckDBPyConnection:
        """An in-memory DuckDB with one view per dataset, named ``<source>__<dataset>``."""
        con = duckdb.connect()
        con.execute("SET TimeZone='UTC'")
        for source, dataset in self.datasets():
            glob = (self._dir(source, dataset) / "symbol=*" / "data.parquet").as_posix()
            con.execute(f"CREATE VIEW {source}__{dataset} AS "
                        f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
        return con

    def catalog(self) -> pd.DataFrame:
        rows = []
        con = self.duckdb()
        for source, dataset in self.datasets():
            v = f"{source}__{dataset}"
            n, syms, lo, hi = con.execute(
                f"SELECT count(*), count(DISTINCT symbol), min(timestamp), max(timestamp) FROM {v}").fetchone()
            files = list(self._dir(source, dataset).glob("symbol=*/data.parquet"))
            updated = max(f.stat().st_mtime for f in files)
            rows.append({"source": source, "dataset": dataset, "rows": n, "symbols": syms,
                         "first": pd.Timestamp(lo), "last": pd.Timestamp(hi),
                         "updated_utc": datetime.fromtimestamp(updated, timezone.utc),
                         "size_mb": round(sum(f.stat().st_size for f in files) / 1e6, 2)})
        return pd.DataFrame(rows)
