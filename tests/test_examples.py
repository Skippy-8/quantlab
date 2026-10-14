"""The examples are documentation: each must keep running, offline, and say what it claims."""
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def run(name: str) -> str:
    out = subprocess.run([sys.executable, str(EXAMPLES / name)], capture_output=True, text=True, timeout=300,
                         cwd=EXAMPLES.parent)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


@pytest.mark.slow
def test_macro_sql_and_qc():
    out = run("01_macro_sql_and_qc.py")
    assert "duplicate" in out and "missing" in out and "outlier" in out
    assert "Monthly asset return by rate regime" in out and "max_drawdown_pct" in out


@pytest.mark.slow
def test_sec_event_study():
    out = run("02_sec_event_study.py")
    assert "0 rows visible one minute before, 1 at acceptance" in out
    assert "insider purchases" in out and "placebo dates" in out


@pytest.mark.slow
def test_governance_and_vault():
    out = run("03_governance_and_vault.py")
    assert out.count("LookaheadError") >= 2 and "changes when the symbols are reordered" in out
    assert "60 2.86" in " ".join(out.split())
    assert "one shot per hypothesis" in out and "'ok': False" in out
