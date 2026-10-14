import math

import numpy as np
import pandas as pd
import pytest

from quantlab.data.synthetic import panel
from quantlab.engine import evaluate
from quantlab.portfolio import simulate
from quantlab.report import metrics as M
from quantlab.report.tearsheet import Tearsheet
from quantlab.strategies import REGISTRY


def series(vals, start="2024-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"))


def test_drawdown_and_recovery():
    r = series([0.1, -0.5, 0.0, 1.0, 0.0])          # 1.1 -> 0.55 -> back to 1.1 on day 4
    assert M.drawdown(r).min() == pytest.approx(-0.5)
    p = M.drawdown_periods(r)
    assert p.iloc[0]["depth"] == pytest.approx(-0.5) and p.iloc[0]["days"] == 2


def test_summary_annualisation_and_ratios():
    rng = np.random.default_rng(0)
    r = series(rng.normal(0.001, 0.01, 730))
    s = M.summary(r, periods=365)
    assert s["volatility"] == pytest.approx(r.std() * math.sqrt(365))
    assert s["sharpe"] == pytest.approx(r.mean() / r.std() * math.sqrt(365))
    assert s["calmar"] == pytest.approx(s["cagr"] / abs(s["max_drawdown"]))
    assert s["cvar_95"] <= s["var_95"]


def test_monthly_table_compounds():
    r = series([0.01] * 31 + [0.0] * 29)             # January +1% a day, February flat
    t = M.monthly_table(r)
    assert t.loc[2024, "Jan"] == pytest.approx(1.01 ** 31 - 1) and t.loc[2024, "Feb"] == 0


def test_benchmark_beta_recovers_a_known_exposure():
    rng = np.random.default_rng(1)
    b = series(rng.normal(0, 0.02, 500))
    s = 0.5 * b + series(rng.normal(0.0005, 0.002, 500))
    st = M.benchmark_stats(s, b)
    assert st["beta"] == pytest.approx(0.5, abs=0.03) and st["correlation"] > 0.9


def test_tearsheet_renders_a_complete_document(tmp_path):
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), panel(n_bars=900))
    pf = simulate(res)
    ts = Tearsheet.from_results(res, pf, "SMA test", verdict={"passed": False, "text": "t 0.4 < 2.0"})
    html = ts.to_html()
    assert html.startswith("<!doctype html>") and "SMA test" in html and html.count("plotly-graph-div") == 6
    assert "Does not pass" in html
    assert (tmp_path / "r.html").exists() is False
    ts.save(str(tmp_path / "r.html"))
    assert (tmp_path / "r.html").stat().st_size > 10_000
