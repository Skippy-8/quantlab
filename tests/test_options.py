import numpy as np
import pytest

from quantlab.options import STRUCTURES, Leg, backtest, compare_fills, synthetic
from quantlab.options import pricing as P
from quantlab.options.chain import implied_spot


def test_black_scholes_known_value_and_parity():
    c = float(P.price(100, 100, 1.0, 0.2, True))
    p = float(P.price(100, 100, 1.0, 0.2, False))
    assert c == pytest.approx(7.9656, abs=1e-3) and c - p == pytest.approx(0.0, abs=1e-9)
    assert float(P.delta(100, 100, 1.0, 0.2, True)) == pytest.approx(0.5398, abs=1e-3)


def test_implied_vol_inverts_price():
    px = P.price(100, [90, 100, 110], 0.5, 0.31, True)
    assert np.allclose(P.implied_vol(px, 100, [90, 100, 110], 0.5, True), 0.31, atol=1e-6)
    assert np.isnan(P.implied_vol(0.0001, 100, 50, 0.5, True))            # below intrinsic: no IV


CHAIN = synthetic(days=120, seed=3)


def test_synthetic_chain_has_quotes_and_parity_spot():
    day = CHAIN[CHAIN["date"] == CHAIN["date"].iloc[0]]
    assert (day["ask"] >= day["bid"]).all() and day["expiry"].nunique() >= 6
    assert implied_spot(day) == pytest.approx(day["underlying"].iat[0], rel=0.01)


def test_delta_selection_picks_the_right_wing():
    from quantlab.options.backtest import _pick
    day = CHAIN[CHAIN["date"] == CHAIN["date"].iloc[10]]
    put = _pick(day, Leg("P", -1, delta=0.2))
    call = _pick(day, Leg("C", -1, delta=0.2))
    s = day["underlying"].iat[0]
    assert put["strike"] < s < call["strike"]


@pytest.mark.parametrize("name", sorted(STRUCTURES))
def test_every_structure_backtests(name):
    entries = CHAIN["date"].drop_duplicates().iloc[::10].tolist()[:8]
    res = backtest(CHAIN, STRUCTURES[name], entries, hold_days=10)
    assert len(res.trades) >= 3
    assert res.daily["equity"].iloc[-1] == pytest.approx(res.trades["pnl"].sum(), rel=1e-9, abs=1e-6)


def test_execution_ordering_mid_beats_quarter_beats_natural():
    entries = CHAIN["date"].drop_duplicates().iloc[::7].tolist()
    cmp = compare_fills(CHAIN, STRUCTURES["iron_condor"], entries, hold_days=7)
    assert cmp.loc["mid", "total_pnl"] > cmp.loc["quarter", "total_pnl"] > cmp.loc["natural", "total_pnl"]


def test_take_profit_and_expiry_settlement():
    entries = CHAIN["date"].drop_duplicates().iloc[::5].tolist()
    res = backtest(CHAIN, [Leg("P", -1, dte=7, delta=0.3)], entries, exit_dte=None, take_profit=0.5)
    reasons = set(res.trades["exit_reason"])
    assert reasons <= {"take_profit", "expiry"} and "expiry" in reasons
