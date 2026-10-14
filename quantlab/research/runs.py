"""Saved runs: every backtest you keep is reproducible and comparable.

A run directory holds the manifest (strategy, parameters, engine and sizing
config, data fingerprint, code version, timestamps), the summary, the daily
returns, the positions and the equity curve. ``compare`` lines runs up side by
side; ``load`` restores one exactly as it was.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quantlab.research.registry import home


def _root() -> Path:
    p = home() / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def code_version() -> str:
    try:
        root = Path(__file__).resolve().parents[2]
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "quantlab"], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return (sha or "unknown") + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def save(name: str, strategy: str, params: dict, res, pf=None, data_fp: str = "", study: str = "",
         extra: dict | None = None) -> str:
    rid = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    d = _root() / rid
    d.mkdir()
    manifest = {"id": rid, "name": name, "strategy": strategy, "params": params, "study": study,
                "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": data_fp,
                "code": code_version(), "engine": res.summary.get("config"),
                "sizing": pf.stats.get("sizing") if pf is not None else None, **(extra or {})}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    (d / "summary.json").write_text(json.dumps({k: v for k, v in res.summary.items() if k != "config"},
                                               indent=1, default=str))
    res.positions.to_parquet(d / "positions.parquet", index=False)
    res.daily.rename("net_bp").to_frame().to_parquet(d / "daily_bp.parquet")
    if pf is not None:
        pf.daily_returns.rename("ret").to_frame().to_parquet(d / "daily_returns.parquet")
        pf.equity.rename("equity").to_frame().to_parquet(d / "equity.parquet")
        (d / "portfolio.json").write_text(json.dumps(pf.stats, indent=1, default=str))
    return rid


def list_runs() -> pd.DataFrame:
    rows = []
    for d in sorted(_root().glob("*/manifest.json"), reverse=True):
        m = json.loads(d.read_text())
        s = json.loads((d.parent / "summary.json").read_text())
        rows.append({"id": m["id"], "name": m["name"], "strategy": m["strategy"], "study": m.get("study"),
                     "created": m["created_utc"], "trades": s.get("trades"), "day_t": s.get("day_t"),
                     "calendar_sharpe": s.get("calendar_sharpe"), "code": m.get("code")})
    return pd.DataFrame(rows)


def load(rid: str) -> dict:
    d = _root() / rid
    out = {"manifest": json.loads((d / "manifest.json").read_text()),
           "summary": json.loads((d / "summary.json").read_text()),
           "positions": pd.read_parquet(d / "positions.parquet"),
           "daily_bp": pd.read_parquet(d / "daily_bp.parquet")["net_bp"]}
    if (d / "daily_returns.parquet").exists():
        out["daily_returns"] = pd.read_parquet(d / "daily_returns.parquet")["ret"]
        out["equity"] = pd.read_parquet(d / "equity.parquet")["equity"]
        out["portfolio"] = json.loads((d / "portfolio.json").read_text())
    return out


def delete(rid: str) -> None:
    d = _root() / rid
    for f in d.glob("*"):
        f.unlink()
    d.rmdir()


def compare(ids: list[str]) -> pd.DataFrame:
    from quantlab.report import metrics as M
    rows = []
    for rid in ids:
        r = load(rid)
        periods = (r["manifest"].get("engine") or {}).get("days_per_year", 365)
        s = M.summary(r["daily_returns"], periods) if "daily_returns" in r else {}
        t = M.trade_stats(r["positions"])
        rows.append({"run": r["manifest"]["name"], "id": rid, **{k: s.get(k) for k in
                     ("total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar", "volatility")},
                     "trades": t.get("trades"), "win_rate": t.get("win_rate"), "expectancy_bp": t.get("expectancy_bp"),
                     "day_t": r["summary"].get("day_t")})
    return pd.DataFrame(rows).set_index("run")
