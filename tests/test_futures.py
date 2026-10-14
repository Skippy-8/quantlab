import pandas as pd
import pytest

from quantlab.engine import EngineConfig, run_backtest
from quantlab.futures import SPECS, continuous


def contracts():
    """Two contracts: H expires day 10 trading at 100, M trades at 105 (contango); flat prices."""
    days = pd.date_range("2024-03-01", periods=20, freq="D", tz="UTC")
    h = pd.DataFrame({"timestamp": days[:10], "contract": "H", "expiry": days[9], "open": 100.0, "high": 101.0,
                      "low": 99.0, "close": 100.0, "volume": [1000] * 6 + [400] * 4})
    m = pd.DataFrame({"timestamp": days, "contract": "M", "expiry": days[19], "open": 105.0, "high": 106.0,
                      "low": 104.0, "close": 105.0, "volume": [100] * 6 + [900] * 14})
    return pd.concat([h, m], ignore_index=True)


def test_calendar_roll_and_ratio_adjustment_remove_the_jump():
    c = continuous(contracts(), "ES", rule="calendar", roll_days=3)
    assert c["roll"].sum() == 1
    roll_day = c.index[c["roll"]][0]
    assert c.loc[roll_day, "timestamp"] == pd.Timestamp("2024-03-07", tz="UTC")       # expiry minus 3 days
    assert c["close"].pct_change().abs().max() == pytest.approx(0.0)                # no artificial jump


def test_volume_roll_switches_on_the_first_crossover():
    c = continuous(contracts(), "ES", rule="volume", adjust="difference")
    assert c.loc[c["roll"], "timestamp"].iloc[0] == pd.Timestamp("2024-03-07", tz="UTC")
    assert c["close"].diff().abs().max() == pytest.approx(0.0)


def test_roll_cost_is_charged_for_positions_held_through_a_roll():
    c = continuous(contracts(), "ES", roll_days=3)
    df = c.assign(signal=1)
    t = run_backtest(df, EngineConfig(roll_cost_bp=4, maker_fee_bp=0, taker_fee_bp=0)).trades.iloc[0]
    assert t["roll_bp"] == 4


def test_contract_specs():
    assert SPECS["MES"].multiplier == 5 and SPECS["ES"].multiplier == 50
