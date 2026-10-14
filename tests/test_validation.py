import numpy as np
import pandas as pd
import pytest

from quantlab import fast, validation
from quantlab.data.synthetic import panel
from quantlab.engine import EngineConfig, evaluate
from quantlab.strategies import REGISTRY

SMA = REGISTRY["sma_crossover"].make


def test_fast_mode_trades_on_the_next_bar_and_charges_turnover():
    df = pd.DataFrame({"symbol": "X", "timestamp": pd.date_range("2024", periods=4, freq="D", tz="UTC"),
                       "open": 1.0, "high": 1.0, "low": 1.0, "volume": 1.0, "close": [100.0, 110.0, 121.0, 121.0]})
    r = fast.run(lambda d: d.assign(signal=[1, 1, 0, 0]), df, cost_bp=10)
    # held over bar 1 (+10%) and bar 2 (+10%): 1000 + 1000 bp, minus one entry and one exit at 10 bp
    assert r.daily.sum() == pytest.approx(2000 - 20)


def test_fast_and_full_engine_broadly_agree():
    df = panel(n_bars=1500)
    f = fast.run(SMA(fast=10, slow=50), df, cost_bp=7).daily.sum()
    e = evaluate(SMA(fast=10, slow=50), df, EngineConfig()).daily.sum()
    assert np.sign(f) == np.sign(e) or abs(f - e) < 0.5 * max(abs(f), abs(e))


def test_walk_forward_scores_only_unseen_windows():
    df = panel(n_bars=24 * 200)
    grid = [{"fast": f, "slow": s} for f in (5, 10) for s in (30, 60)]
    wf = validation.walk_forward(SMA, grid, df, train_days=60, test_days=30)
    assert wf.stats["folds"] == len(wf.folds) >= 4
    for row in wf.folds.itertuples():
        assert row.train_start < row.test_start < row.test_end
    assert wf.oos_daily.index.min() >= pd.Timestamp(wf.folds["test_start"].iloc[0], tz="UTC")


def test_pbo_is_high_for_pure_noise_and_low_for_a_real_edge():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024", periods=800, freq="D")
    noise = pd.DataFrame(rng.normal(0, 1, (800, 20)), index=idx)
    assert validation.pbo(noise)["pbo"] > 0.3
    edge = noise.copy()
    edge[0] += 0.4                                            # one config is genuinely better
    assert validation.pbo(edge)["pbo"] < 0.1


def test_monte_carlo_brackets_the_actual_path():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.001, 0.01, 500))
    mc = validation.monte_carlo(r, n=500, method="shuffle")
    assert mc["final_p5"] < mc["final_p50"] < mc["final_p95"]
    assert mc["actual_final"] == pytest.approx(mc["final_p50"], rel=1e-6)    # shuffling preserves the product
    assert mc["max_dd_p95"] <= mc["max_dd_p50"] <= 0


def test_reality_check_rejects_noise_and_detects_an_edge():
    rng = np.random.default_rng(2)
    idx = pd.date_range("2024", periods=600, freq="D")
    noise = pd.DataFrame(rng.normal(0, 1, (600, 30)), index=idx)
    # under the null the p-value is ~uniform: across 20 noise panels, a 5% test rarely rejects
    ps = [validation.reality_check(pd.DataFrame(np.random.default_rng(s).normal(0, 1, (400, 20))), n_boot=200)
          ["reality_check_p"] for s in range(20)]
    assert sum(p < 0.05 for p in ps) <= 3
    edge = noise.copy()
    edge[5] += 0.3
    out = validation.reality_check(edge, n_boot=300)
    assert out["best"] == "5" and out["spa_p"] < 0.05
