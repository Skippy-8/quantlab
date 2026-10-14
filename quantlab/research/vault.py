"""The sealed out-of-sample vault.

An out-of-sample set stays out of sample only if nobody looks at it. "We held
out 2021-2023" means nothing if the researcher ran twenty variants against it.
The vault enforces the discipline mechanically:

* :func:`seal` writes a manifest (sha256 of every file) and a ``.vault_sealed``
  marker. A sealed directory is never rebuilt in place.
* :func:`guard` refuses to read any file under a sealed directory unless a
  vault RUN is open.
* :func:`open_run` opens a run only for a written, pre-registered spec, and
  refuses a spec whose hash has already been run: one shot per hypothesis.
  Every run is logged start and end in an append-only register, so the number
  of times the vault was used is always known.

Usage::

    with open_run(vault_dir, spec="prereg/momentum.md", hypothesis="12-1 momentum") as run:
        df = run.read("klines_1h.parquet")
        res = evaluate(strategy, df)
        run.result(res.summary)          # recorded in the register
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

MARKER = ".vault_sealed"
ENV_RUN = "QUANTLAB_VAULT_RUN"


class VaultError(PermissionError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _events(register: Path) -> list[dict]:
    if not register.exists():
        return []
    return [json.loads(x) for x in register.read_text().splitlines() if x.strip()]


def _append(register: Path, row: dict) -> None:
    register.parent.mkdir(parents=True, exist_ok=True)
    with open(register, "a") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def seal(vault_dir: str | Path, register: str | Path | None = None, description: str = "") -> dict:
    """Freeze a directory of data files as the out-of-sample vault."""
    v = Path(vault_dir).resolve()
    marker = v / MARKER
    if marker.exists():
        raise VaultError(f"{v} is already sealed; a sealed vault is never rebuilt in place")
    files = sorted(p for p in v.rglob("*") if p.is_file() and p.name not in (MARKER, "MANIFEST.json"))
    if not files:
        raise VaultError(f"nothing to seal in {v}")
    reg = Path(register).resolve() if register else v.parent / f"{v.name}_register.jsonl"
    manifest = {"sealed_utc": _now(), "description": description,
                "files": {str(p.relative_to(v)): sha256(p) for p in files}}
    (v / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    man_sha = sha256(v / "MANIFEST.json")
    marker.write_text(json.dumps({"register": str(reg), "manifest_sha256": man_sha, "sealed_utc": manifest["sealed_utc"]}))
    _append(reg, {"event": "sealed", "ts": manifest["sealed_utc"], "vault": str(v), "files": len(files),
                  "manifest_sha256": man_sha})
    for p in files:                                   # read-only on disk, as a second line of defence
        p.chmod(0o444)
    return {"vault": str(v), "files": len(files), "register": str(reg), "manifest_sha256": man_sha}


def _sealed_root(path: Path) -> Path | None:
    d = path.resolve().parent if path.is_file() or not path.exists() else path.resolve()
    while True:
        if (d / MARKER).exists():
            return d
        if d.parent == d:
            return None
        d = d.parent


def register_of(vault_dir: Path) -> Path:
    return Path(json.loads((vault_dir / MARKER).read_text())["register"])


def guard(path: str | Path) -> None:
    """Raise unless ``path`` is outside every sealed vault, or a run is open for it."""
    p = Path(path)
    root = _sealed_root(p)
    if root is None:
        return
    run_id = os.environ.get(ENV_RUN, "")
    if not run_id:
        raise VaultError(f"{p} is inside the sealed vault {root}; open a registered vault run to read it")
    ev = [e for e in _events(register_of(root)) if e.get("run_id") == run_id]
    started = any(e["event"] == "run_start" for e in ev)
    ended = any(e["event"] == "run_end" for e in ev)
    if not started or ended:
        raise VaultError(f"vault run {run_id!r} is {'already ended' if ended else 'not started'}")


def verify(vault_dir: str | Path) -> dict:
    """Re-hash every file against the manifest (detects edits after sealing)."""
    v = Path(vault_dir).resolve()
    man = json.loads((v / "MANIFEST.json").read_text())
    bad = [f for f, h in man["files"].items() if not (v / f).exists() or sha256(v / f) != h]
    return {"files": len(man["files"]), "modified_or_missing": bad, "ok": not bad}


def runs(vault_dir: str | Path) -> list[dict]:
    v = Path(vault_dir).resolve()
    return [e for e in _events(register_of(v)) if e["event"] in ("run_start", "run_end")]


class VaultRun:
    def __init__(self, vault: Path, run_id: str, register: Path):
        self.vault, self.run_id, self.register = vault, run_id, register
        self._result: dict | None = None

    def read(self, rel: str) -> pd.DataFrame:
        p = self.vault / rel
        guard(p)
        return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)

    def result(self, summary: dict) -> None:
        keep = ("trades", "day_t", "calendar_sharpe", "mean_net_bp_per_trade", "half1_mean_day_bp",
                "half2_mean_day_bp", "max_drawdown_bp")
        self._result = {k: summary.get(k) for k in keep}


@contextmanager
def open_run(vault_dir: str | Path, spec: str | Path, hypothesis: str):
    """Open ONE registered run of the vault for a written spec."""
    v = Path(vault_dir).resolve()
    if not (v / MARKER).exists():
        raise VaultError(f"{v} is not a sealed vault")
    check = verify(v)
    if not check["ok"]:
        raise VaultError(f"vault files changed since sealing: {check['modified_or_missing'][:5]}")
    reg = register_of(v)
    spec_sha = sha256(Path(spec))
    ev = _events(reg)
    if any(e.get("spec_sha256") == spec_sha for e in ev if e["event"] == "run_start"):
        raise VaultError("this spec has already been run against the vault (one shot per hypothesis)")
    run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    n_before = sum(1 for e in ev if e["event"] == "run_start")
    _append(reg, {"event": "run_start", "ts": _now(), "run_id": run_id, "spec": str(spec),
                  "spec_sha256": spec_sha, "hypothesis": hypothesis, "vault_runs_before": n_before})
    prev = os.environ.get(ENV_RUN)
    os.environ[ENV_RUN] = run_id
    run = VaultRun(v, run_id, reg)
    err = None
    try:
        yield run
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        _append(reg, {"event": "run_end", "ts": _now(), "run_id": run_id, "spec_sha256": spec_sha,
                      "result": run._result, "error": err})
        if prev is None:
            os.environ.pop(ENV_RUN, None)
        else:
            os.environ[ENV_RUN] = prev
