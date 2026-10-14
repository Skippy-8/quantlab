"""The trial registry: every backtest is counted, so the pass bar can rise with the count.

The single biggest source of false discoveries in backtesting is the trials
nobody reports. Run 50 parameter sets, keep the best, and a t of 2.5 means
nothing. This module makes the count unavoidable:

* every run is appended to an append-only JSONL file, keyed by a STUDY;
* K is the number of DISTINCT trials in the study (same strategy, params and
  data fingerprint run twice counts once);
* the pass bar is ``max(floor, sqrt(2 ln K))``: the |t| the best of K pure-noise
  trials is expected to reach (the MinBTL bound), never below a floor;
* the deflated Sharpe of any trial uses the Sharpes of ALL trials in its study.

Pre-registration: :func:`preregister` records a written spec's hash BEFORE any
result exists. A trial run against a registered spec is tagged with it, so a
reader can check the spec predates the result.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quantlab.stats.deflated import dsr, noise_bar

DEFAULT_FLOOR = 2.0


def home() -> Path:
    p = Path(os.environ.get("QUANTLAB_HOME", ".quantlab"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(df: pd.DataFrame) -> str:
    """A short, stable hash of the data a trial ran on (symbols, span, rows, a close checksum)."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    key = "|".join([",".join(sorted(map(str, df["symbol"].unique()))) if "symbol" in df else "",
                    str(ts.min()), str(ts.max()), str(len(df)),
                    f"{float(pd.to_numeric(df['close'], errors='coerce').sum()):.6f}"])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def trial_key(strategy: str, params: dict, data_fp: str, window: str = "") -> str:
    blob = json.dumps({"s": strategy, "p": params, "d": data_fp, "w": window}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass
class Verdict:
    study: str
    k: int
    bar: float
    day_t: float | None
    dsr: float | None
    halves_same_sign: bool
    passed: bool
    reasons: list[str]


class Registry:
    def __init__(self, path: str | Path | None = None, floor: float = DEFAULT_FLOOR):
        self.path = Path(path) if path else home() / "registry.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.floor = floor

    # ── storage ─────────────────────────────────────────────────────────────
    def _append(self, row: dict) -> dict:
        with open(self.path, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return row

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def trials(self, study: str | None = None) -> pd.DataFrame:
        rows = [e for e in self.events() if e.get("event") == "trial" and (study is None or e["study"] == study)]
        return pd.DataFrame(rows)

    def studies(self) -> list[str]:
        return sorted({e["study"] for e in self.events() if e.get("event") == "trial"})

    # ── pre-registration ────────────────────────────────────────────────────
    def preregister(self, study: str, spec_path: str | Path, note: str = "") -> dict:
        spec = Path(spec_path)
        sha = hashlib.sha256(spec.read_bytes()).hexdigest()
        return self._append({"event": "prereg", "ts": _now(), "study": study, "spec": str(spec),
                             "spec_sha256": sha, "note": note})

    def prereg_for(self, study: str) -> dict | None:
        regs = [e for e in self.events() if e.get("event") == "prereg" and e["study"] == study]
        return regs[-1] if regs else None

    # ── trials ──────────────────────────────────────────────────────────────
    def record(self, study: str, strategy: str, params: dict, summary: dict, data_fp: str,
               window: str = "", note: str = "") -> dict:
        reg = self.prereg_for(study)
        return self._append({
            "event": "trial", "ts": _now(), "study": study, "strategy": strategy, "params": params,
            "data": data_fp, "window": window, "key": trial_key(strategy, params, data_fp, window),
            "prereg_sha256": reg["spec_sha256"] if reg else None, "note": note,
            "trades": summary.get("trades"), "day_t": summary.get("day_t"),
            "calendar_sharpe": summary.get("calendar_sharpe"),
            "mean_net_bp_per_trade": summary.get("mean_net_bp_per_trade"),
            "half1_mean_day_bp": summary.get("half1_mean_day_bp"),
            "half2_mean_day_bp": summary.get("half2_mean_day_bp"),
            "calendar_days": summary.get("calendar_days")})

    def k(self, study: str) -> int:
        t = self.trials(study)
        return int(t["key"].nunique()) if len(t) else 0

    def bar(self, study: str) -> float:
        return noise_bar(max(self.k(study), 1), self.floor)

    def verdict(self, study: str, summary: dict, k: int | None = None) -> Verdict:
        """Judge one result against the study's CURRENT bar."""
        k = k if k is not None else max(self.k(study), 1)
        bar = noise_bar(k, self.floor)
        t = summary.get("day_t")
        h1, h2 = summary.get("half1_mean_day_bp"), summary.get("half2_mean_day_bp")
        same = h1 is not None and h2 is not None and h1 > 0 and h2 > 0
        d = self.deflated(study, summary)
        reasons = []
        if t is None or t < bar:
            reasons.append(f"day t {t} below the bar {bar:.2f} (K = {k})")
        if not same:
            reasons.append("not positive in both calendar halves")
        if d is not None and d < 0.95:
            reasons.append(f"deflated Sharpe {d:.2f} < 0.95")
        return Verdict(study, k, bar, t, d, same, not reasons, reasons)

    def deflated(self, study: str, summary: dict) -> float | None:
        """DSR of ``summary`` given every trial Sharpe in the study (annualised SR, n in years)."""
        sr, days = summary.get("calendar_sharpe"), summary.get("calendar_days")
        if sr is None or not days:
            return None
        # per-observation (daily) Sharpe with n = days: valid for samples under a year,
        # where "annualised SR over n years" leaves PSR undefined
        root = math.sqrt(summary.get("config", {}).get("days_per_year", 365))
        t = self.trials(study)
        srs = [x / root for x in t["calendar_sharpe"].dropna().tolist()] if len(t) else []
        res = dsr(sr=sr / root, n=days, n_trials=max(len(srs), 1), trial_srs=srs if len(srs) > 1 else None)
        return None if math.isnan(res["dsr"]) else res["dsr"]
