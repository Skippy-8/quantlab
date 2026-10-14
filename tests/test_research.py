import math
import os

import pandas as pd
import pytest

from quantlab.data.synthetic import panel
from quantlab.research import vault
from quantlab.research.registry import Registry, fingerprint


def summary(t, h1=1.0, h2=1.0, sr=1.0):
    return {"day_t": t, "half1_mean_day_bp": h1, "half2_mean_day_bp": h2, "calendar_sharpe": sr,
            "calendar_days": 365, "trades": 100, "config": {"days_per_year": 365}}


def test_bar_rises_with_distinct_trials(tmp_path):
    reg = Registry(tmp_path / "r.jsonl", floor=2.0)
    for i in range(30):
        reg.record("s", "strat", {"p": i}, summary(1.0), "fp")
    reg.record("s", "strat", {"p": 0}, summary(1.0), "fp")        # a re-run is not a new trial
    assert reg.k("s") == 30
    assert reg.bar("s") == pytest.approx(math.sqrt(2 * math.log(30)))


def test_verdict_requires_bar_and_both_halves(tmp_path):
    reg = Registry(tmp_path / "r.jsonl")
    reg.record("s", "strat", {}, summary(3.0), "fp")
    assert reg.verdict("s", summary(3.0, sr=3.0)).passed
    v = reg.verdict("s", summary(3.0, h1=-1.0, sr=3.0))
    assert not v.passed and any("halves" in r for r in v.reasons)


def test_preregistration_is_recorded_with_the_spec_hash(tmp_path):
    reg = Registry(tmp_path / "r.jsonl")
    spec = tmp_path / "spec.md"
    spec.write_text("hypothesis: momentum")
    reg.preregister("s", spec)
    row = reg.record("s", "strat", {}, summary(1.0), "fp")
    assert row["prereg_sha256"] == reg.prereg_for("s")["spec_sha256"]


def test_fingerprint_changes_with_the_data():
    a, b = panel(n_bars=100), panel(n_bars=101)
    assert fingerprint(a) != fingerprint(b) and fingerprint(a) == fingerprint(a.copy())


@pytest.fixture
def sealed(tmp_path):
    d = tmp_path / "vault"
    d.mkdir()
    panel(n_bars=50).to_parquet(d / "bars.parquet")
    vault.seal(d)
    return d


def test_sealed_files_cannot_be_read_without_a_run(sealed):
    with pytest.raises(vault.VaultError):
        vault.guard(sealed / "bars.parquet")


def test_one_shot_per_spec(sealed, tmp_path):
    spec = tmp_path / "h1.md"
    spec.write_text("H1")
    with vault.open_run(sealed, spec, "h1") as run:
        df = run.read("bars.parquet")
        run.result({"trades": len(df), "day_t": 0.1})
    assert os.environ.get(vault.ENV_RUN) is None
    with pytest.raises(vault.VaultError):
        with vault.open_run(sealed, spec, "h1 again"):
            pass
    runs = vault.runs(sealed)
    assert [r["event"] for r in runs] == ["run_start", "run_end"] and runs[1]["result"]["trades"] == 200


def test_a_modified_vault_refuses_to_open(sealed, tmp_path):
    f = sealed / "bars.parquet"
    f.chmod(0o644)
    pd.DataFrame({"x": [1]}).to_parquet(f)
    spec = tmp_path / "h2.md"
    spec.write_text("H2")
    with pytest.raises(vault.VaultError):
        with vault.open_run(sealed, spec, "h2"):
            pass


def test_sealing_twice_is_refused(sealed):
    with pytest.raises(vault.VaultError):
        vault.seal(sealed)
