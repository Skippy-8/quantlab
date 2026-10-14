"""Heartbeats and health checks for scheduled jobs.

Silence is ambiguous: a stalled pipeline and a quiet market look the same. So
every scheduled job writes a heartbeat (start, ok / error, a few counters), and
:func:`check` turns heartbeats plus lake freshness into a status table:

* a job is STALE if its last OK heartbeat is older than its expected interval
  times a grace factor, and FAILING if its last run errored;
* a dataset is STALE if its newest bar is older than its allowed age.

``quantlab monitor`` prints the table and exits non-zero when anything is not
OK, so cron / systemd / CI can alert on the exit code alone.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quantlab.research.registry import home


def _path() -> Path:
    return home() / "heartbeats.jsonl"


def beat(job: str, status: str = "ok", **info) -> dict:
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "job": job, "status": status, **info}
    with open(_path(), "a") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return row


@contextmanager
def job(name: str, **info):
    """Wrap a scheduled job: a 'start' beat, then 'ok' or 'error' with the exception."""
    beat(name, "start", **info)
    t0 = datetime.now(timezone.utc)
    try:
        yield
    except Exception as exc:
        beat(name, "error", error=f"{type(exc).__name__}: {exc}"[:300])
        raise
    beat(name, "ok", seconds=round((datetime.now(timezone.utc) - t0).total_seconds(), 1))


def heartbeats() -> pd.DataFrame:
    p = _path()
    if not p.exists():
        return pd.DataFrame(columns=["ts", "job", "status"])
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def check(expected_jobs: dict[str, float] | None = None, max_age_h: dict[str, float] | None = None,
          lake=None, grace: float = 1.5, now: datetime | None = None) -> pd.DataFrame:
    """``expected_jobs``: job -> interval in hours. ``max_age_h``: 'source/dataset' -> allowed bar age."""
    now = now or datetime.now(timezone.utc)
    rows = []
    hb = heartbeats()
    for name, every_h in (expected_jobs or {}).items():
        mine = hb[hb["job"] == name] if len(hb) else hb
        last = mine.iloc[-1] if len(mine) else None
        ok = mine[mine["status"] == "ok"] if len(mine) else mine
        last_ok = ok["ts"].max() if len(ok) else None
        if last is not None and last["status"] == "error":
            status, detail = "FAILING", str(last.get("error", ""))[:120]
        elif last_ok is None:
            status, detail = "NEVER_RAN", "no successful heartbeat"
        elif now - last_ok.to_pydatetime() > timedelta(hours=every_h * grace):
            status, detail = "STALE", f"last ok {last_ok:%Y-%m-%d %H:%M}Z"
        else:
            status, detail = "OK", f"last ok {last_ok:%Y-%m-%d %H:%M}Z"
        rows.append({"kind": "job", "name": name, "status": status, "detail": detail})
    if lake is not None and max_age_h:
        cat = lake.catalog()
        for key, age_h in max_age_h.items():
            src, ds = key.split("/", 1)
            hit = cat[(cat["source"] == src) & (cat["dataset"] == ds)] if len(cat) else cat
            if not len(hit):
                rows.append({"kind": "data", "name": key, "status": "MISSING", "detail": "not in the lake"})
                continue
            last = hit.iloc[0]["last"]
            lag = (now - last.to_pydatetime()).total_seconds() / 3600
            rows.append({"kind": "data", "name": key, "status": "OK" if lag <= age_h else "STALE",
                         "detail": f"newest bar {last:%Y-%m-%d %H:%M}Z ({lag:.0f}h old, allowed {age_h:.0f}h)"})
    return pd.DataFrame(rows, columns=["kind", "name", "status", "detail"])
