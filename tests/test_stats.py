import math

import numpy as np
import pytest

from quantlab.stats.deflated import (
    bhy,
    dsr,
    expected_max_sr,
    haircut_sharpe,
    holm,
    minbtl_years,
    noise_bar,
    norm_ppf,
    psr,
)
from quantlab.stats.inference import concentration_check, split_halves, wilson_ci


def test_norm_ppf_matches_known_quantiles():
    assert norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert norm_ppf(0.5) == pytest.approx(0.0, abs=1e-12)


def test_harvey_liu_worked_example():
    # SR 0.92 over 20 years at 200 trials -> ~0.44 after the BHY haircut (paper: 0.438)
    h = haircut_sharpe(0.92, 20, 200)
    assert h["haircut_sr"] == pytest.approx(0.44, abs=0.015)


def test_haircut_is_monotone_in_sample_length():
    cuts = [haircut_sharpe(2.5, y, 100)["haircut_pct"] for y in (3, 10, 30)]
    assert cuts[0] > cuts[1] > cuts[2]


def test_psr_penalises_negative_skew_and_fat_tails():
    assert psr(0.1, 250, -1.0, 6.0) < psr(0.1, 250, 0.0, 3.0)


def test_dsr_falls_as_trials_rise():
    r = np.random.default_rng(1).normal(0.05, 1, 1000)
    one = dsr(r, n_trials=1)["dsr"]
    many = dsr(r, n_trials=500, var_trial_sr=0.002)["dsr"]
    assert many < one


def test_expected_max_sr_grows_with_n():
    assert expected_max_sr(1000, 0.01) > expected_max_sr(10, 0.01) > 0


def test_holm_and_bhy():
    p = [0.001, 0.01, 0.02, 0.5]
    assert holm(p)["n_reject"] == 3          # adjusted 0.004, 0.03, 0.04, 0.5
    one_small = [0.009, 0.3, 0.5, 0.7, 0.9]           # a lone small p among k = 5
    assert holm(one_small)["n_reject"] == 1          # 0.009 * 5 = 0.045
    assert bhy(one_small)["n_reject"] == 0           # 0.009 * 5 * c(5)=2.28 = 0.10: the dependence price


def test_noise_bar_and_minbtl():
    assert noise_bar(1, floor=2.0) == 2.0
    assert noise_bar(100) == pytest.approx(math.sqrt(2 * math.log(100)))
    assert minbtl_years(45, 1.0) == pytest.approx(2 * math.log(45))


def test_wilson_interval_contains_the_point():
    p, lo, hi = wilson_ci(55, 100)
    assert lo < p < hi


def test_concentration_flags_a_one_symbol_result():
    syms = ["A"] * 5 + [f"S{i}" for i in range(40)]
    x = [500.0] * 5 + [-5.0] * 40
    out = concentration_check(syms, x)
    assert out["ok"] is False and out["median"] < 0


def test_split_halves_detects_a_sign_flip():
    import pandas as pd
    d = pd.Series([1.0] * 50 + [-1.0] * 50)
    assert split_halves(d)["same_sign"] is False
