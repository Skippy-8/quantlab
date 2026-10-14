"""Mechanical exits: stops, target ladders, breakeven, trailing, time stops, and the cost add-ons."""
import pandas as pd
import pytest

from quantlab.engine import EngineConfig, ExitRules, run_backtest


def frame(o, h, lo, c, sig=None, **extra):
    n = len(c)
    df = pd.DataFrame({"symbol": "X", "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
                       "open": o, "high": h, "low": lo, "close": c, "volume": 1.0,
                       "bbo_bid": [x - 0.5 for x in c], "bbo_ask": [x + 0.5 for x in c],
                       "signal": sig if sig is not None else [1] * n})
    return df.assign(**extra)


def run(df, **ex):
    return run_backtest(df, EngineConfig(exits=ExitRules(**ex), maker_fee_bp=0, taker_fee_bp=0, exit_ttl_bars=99))


# entry: long limit at bid 99.5 (close 100), filled in bar 1 (low 99 < 99.5)
BASE_O = [100, 100]
BASE_H = [100.5, 100.5]
BASE_L = [99.6, 99]


def test_stop_is_checked_before_the_target_in_the_same_bar():
    # bar 2 spans both the 2% stop (97.51) and the 2% target (101.49): the stop wins
    df = frame(BASE_O + [100, 100], BASE_H + [102, 100], BASE_L + [97, 100], [100] * 4)
    t = run(df, stop_loss=0.02, take_profits=((0.02, 1.0),)).trades
    assert list(t["exit"]) == ["stop"] and t.iloc[0]["exit_price"] == pytest.approx(99.5 * 0.98)


def test_gap_through_the_stop_fills_at_the_open():
    df = frame(BASE_O + [95, 95], BASE_H + [96, 96], BASE_L + [94, 94], [100, 100, 95, 95])
    t = run(df, stop_loss=0.02).trades.iloc[0]
    assert t["exit"] == "stop" and t["exit_price"] == 95


def test_target_ladder_closes_fractions_of_the_original_size():
    # targets at +1% (100.495) for half and +2% (101.49) for the rest
    df = frame(BASE_O + [100, 101, 101], BASE_H + [100.6, 101.6, 101], BASE_L + [100, 100.8, 100.8], [100] * 5)
    t = run(df, take_profits=((0.01, 0.5), (0.02, 0.5))).trades
    assert list(t["exit"]) == ["target", "target"] and list(t["size"]) == [0.5, 0.5]
    assert t["position_id"].nunique() == 1


def test_breakeven_after_the_first_target():
    df = frame(BASE_O + [100, 99.8], BASE_H + [100.6, 99.9], BASE_L + [100, 99], [100, 100, 100, 99.2])
    t = run(df, stop_loss=0.05, take_profits=((0.01, 0.5),), breakeven_after=1).trades
    assert list(t["exit"]) == ["target", "breakeven"]
    assert t.iloc[1]["exit_price"] == pytest.approx(99.5)            # stopped at the entry price


def test_trailing_stop_ratchets_up_and_exits():
    df = frame(BASE_O + [100, 104, 103], BASE_H + [102, 105, 103], BASE_L + [100, 103, 101], [100, 100, 101, 104, 102])
    t = run(df, trailing_stop=0.02).trades.iloc[0]
    assert t["exit"] == "stop" and t["exit_price"] == pytest.approx(105 * 0.98)


def test_time_stop_closes_after_n_bars():
    df = frame(BASE_O + [100] * 4, BASE_H + [100.4] * 4, BASE_L + [99.6] * 4, [100] * 6)
    t = run(df, time_stop_bars=2).trades.iloc[0]
    assert t["exit"] == "time" and t["bars_held"] == 2


def test_no_reentry_the_same_way_until_the_signal_resets():
    df = frame(BASE_O + [100] * 6, BASE_H + [100.4] * 6, BASE_L + [99] * 6, [100] * 8)
    assert len(run(df, time_stop_bars=1).positions) == 1


def test_atr_distances_use_atr_before_entry():
    n = 40
    lows = [99] * 32 + [98] * 8                                      # ATR ~2 -> stop 0.8 below the 99.5 entry
    df = frame([100] * n, [101] * n, lows, [100] * n, sig=[0] * 30 + [1] * 10)
    t = run(df, unit="atr", stop_loss=0.4).trades.iloc[0]
    assert t["exit"] == "stop" and 98.6 < t["exit_price"] < 98.8


def test_short_borrow_and_roll_costs():
    n = 6
    base = dict(o=[100] * n, h=[101] * n, lo=[99] * n, c=[100] * n)
    short = frame(**base, sig=[-1] * n)
    cfg = EngineConfig(short_borrow_bp_per_year=365 * 24 * 10, maker_fee_bp=0, taker_fee_bp=0)  # 10bp a bar
    t = run_backtest(short, cfg).trades.iloc[0]
    assert t["borrow_bp"] == pytest.approx(10 * t["bars_held"])
    rolled = frame(**base, roll=[False, False, True, False, False, False])
    t2 = run_backtest(rolled, EngineConfig(roll_cost_bp=7, maker_fee_bp=0, taker_fee_bp=0)).trades.iloc[0]
    assert t2["roll_bp"] == 7
