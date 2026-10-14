"""Governance: causality checks, a counted search, and a one-shot holdout.

    python examples/03_governance_and_vault.py

1. A rule strategy written as a sentence, evaluated by the engine and recorded as a trial.
2. Two deliberately broken strategies the engine refuses before scoring: one reads the
   next bar (caught by truncation replay), one depends on which symbol comes first in the
   file (caught by symbol-reorder replay).
3. A 60-cell parameter search recorded in a study, showing the significance bar rising
   with the number of distinct trials, max(2, sqrt(2 ln K)).
4. A holdout sealed with a SHA-256 manifest: unreadable outside a registered run, opened
   once for a pre-registered spec, refused a second time, and tamper-evident.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np

from _common import section, table, workspace

root = workspace("governance")

import pandas as pd  # noqa: E402

from quantlab import LookaheadError, evaluate  # noqa: E402
from quantlab.data.lake import Lake  # noqa: E402
from quantlab.data.synthetic import panel  # noqa: E402
from quantlab.fast import sweep  # noqa: E402
from quantlab.research import vault  # noqa: E402
from quantlab.research.registry import Registry, fingerprint  # noqa: E402
from quantlab.rules import RuleStrategy  # noqa: E402
from quantlab.stats.deflated import noise_bar  # noqa: E402
from quantlab.strategies import REGISTRY  # noqa: E402

data = panel(n_bars=3000, seed=3)                         # four synthetic hourly markets
research, holdout = data[data["timestamp"] < "2024-03-20"], data[data["timestamp"] >= "2024-03-20"]
reg = Registry()

# ── 1. a rule strategy ───────────────────────────────────────────────────────
section("1. A rule strategy, evaluated and recorded")
rule = RuleStrategy("RSI dip in an uptrend", long_entry="rsi(14) < 30 and close > sma(200)",
                    long_exit="rsi(14) > 55")
res = evaluate(rule.signal_fn(), research)                # lookahead and symbol-order checks run first
reg.record("rsi-dip", "rules:rsi-dip", {}, res.summary, fingerprint(research))
v = reg.verdict("rsi-dip", res.summary)
s = res.summary
print(f"{s['trades']} trades, day t {s['day_t']:.2f}, entry fill rate {s['entry_fill_rate']:.0%}")
print(f"verdict: {'PASS' if v.passed else 'FAIL'} (K = {v.k}, bar {v.bar:.2f}): {'; '.join(v.reasons) or 'clears every test'}")

# ── 2. strategies the engine refuses ─────────────────────────────────────────
section("2. Strategies that cheat are refused before scoring")


def peeks_at_the_next_bar(df):
    nxt = df.groupby("symbol")["close"].shift(-1)          # tomorrow's close: future data
    return df.assign(signal=np.where(nxt > df["close"], 1, 0))


def benchmarks_against_the_first_row(df):
    # causal in time, but "the benchmark" is whichever symbol happens to come first in the file,
    # so the result depends on row order: caught by the symbol-reorder replay, not by truncation
    first = df.groupby("timestamp")["close"].transform("first")
    ret = df.groupby("symbol")["close"].pct_change(24)
    bench = first.groupby(df["symbol"]).pct_change(24)
    return df.assign(signal=np.where(ret > bench, 1, -1))


for fn in (peeks_at_the_next_bar, benchmarks_against_the_first_row):
    try:
        evaluate(fn, research)
        print(f"{fn.__name__}: accepted (unexpected)")
    except LookaheadError as exc:
        print(f"{fn.__name__}: LookaheadError\n    {exc}")

# ── 3. the bar rises with K ──────────────────────────────────────────────────
section("3. A 60-cell search: every cell counted, the bar rises with K")
spec = REGISTRY["sma_crossover"]
grid = [{"fast": f, "slow": s, "allow_short": True} for f in (5, 8, 10, 12, 15, 20, 25, 30, 40, 50)
        for s in (60, 80, 100, 150, 200, 300)]
stats, _ = sweep({str(i): spec.make(**p) for i, p in enumerate(grid)}, research)
fp = fingerprint(research)
rows = []
for i, p in enumerate(grid):
    reg.record("sma-search", "sma_crossover", p, stats.loc[str(i)].to_dict(), fp)
    k = i + 1
    if k in (1, 5, 10, 20, 40, 60):
        best = stats["day_t"].iloc[:k].max()
        rows.append({"K": reg.k("sma-search"), "bar": round(reg.bar("sma-search"), 2),
                     "sqrt(2 ln K)": round(math.sqrt(2 * math.log(k)), 2), "best day t so far": round(best, 2),
                     "best clears bar": bool(best >= reg.bar("sma-search"))})
table(pd.DataFrame(rows))
assert reg.bar("sma-search") == noise_bar(60, 2.0)
print("the best of 60 cells is what a search that size finds by chance unless it clears the last row's bar")

# ── 4. the vault ─────────────────────────────────────────────────────────────
section("4. A sealed holdout, opened once")
lake = Lake()
lake.write("holdout", "hourly", holdout)
vdir = Path(lake.root) / "holdout" / "hourly"
info = vault.seal(vdir, register=root / "vault_register.jsonl", description="last 25% of the synthetic sample")
print(f"sealed {info['files']} files, manifest sha256 {info['manifest_sha256'][:16]}...")
print(f"verify: {vault.verify(vdir)}")

try:
    lake.read("holdout", "hourly")
except vault.VaultError as exc:
    print(f"reading outside a run: VaultError: {exc}")
print(f"SQL views exclude it: {('holdout', 'hourly') not in lake.readable()}")

spec_file = root / "prereg_rsi_dip.md"
spec_file.write_text("Hypothesis: the RSI dip rule has positive day t on the holdout.\n"
                     "Rule: rsi(14) < 30 and close > sma(200); exit rsi(14) > 55. Pass: day t >= 2.\n")
with vault.open_run(vdir, spec=spec_file, hypothesis="RSI dip on the holdout") as run:
    out = evaluate(rule.signal_fn(), lake.read("holdout", "hourly"))
    run.result(out.summary)
    print(f"registered run {run.run_id}: {out.summary['trades']} trades, day t {out.summary['day_t']:.2f}")

try:
    with vault.open_run(vdir, spec=spec_file, hypothesis="the same idea again"):
        pass
except vault.VaultError as exc:
    print(f"second run of the same spec: VaultError: {exc}")

victim = next(vdir.rglob("data.parquet"))
os.chmod(victim, 0o644)
victim.write_bytes(victim.read_bytes() + b"\0")            # an edit after sealing
print(f"after tampering, verify: {vault.verify(vdir)}")
print(f"\nworkspace: {root}")
