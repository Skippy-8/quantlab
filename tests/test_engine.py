import numpy as np
import pandas as pd
import pytest

from quantlab.data.synthetic import panel
from quantlab.engine import EngineConfig, LookaheadError, evaluate, run_backtest
from quantlab.strategies import REGISTRY


def bars(highs, lows, closes, bid=None, ask=None, sig=None, funding=None):
    n = len(closes)
    df = pd.DataFrame({"symbol": "X", "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
                       "open": closes, "high": highs, "low": lows, "close": closes, "volume": 1.0,
                       "bbo_bid": bid if bid is not None else [c - 0.5 for c in closes],
                       "bbo_ask": ask if ask is not None else [c + 0.5 for c in closes],
                       "signal": sig if sig is not None else [0] * n})
    if funding is not None:
        df["funding_rate"] = funding
    return df


def test_touching_the_bid_is_not_a_fill():
    # long signal at bar 0 rests at bid 99.5; bar 1 low == 99.5 (touch) -> no fill; bar 2 trades through
    df = bars(highs=[100, 101, 101, 101], lows=[99, 99.5, 99.4, 99.4], closes=[100] * 4, sig=[1, 1, 1, 1])
    res = run_backtest(df, EngineConfig(entry_ttl_bars=5))
    t = res.trades.iloc[0]
    assert pd.Timestamp(t.entry_time) == df.timestamp[2]
    assert t.entry_price == 99.5 and t.exit == "eod"


def test_unfilled_entry_expires_and_is_never_booked():
    df = bars(highs=[101] * 6, lows=[100.2] * 6, closes=[100.6] * 6, sig=[1] * 6)   # bid 100.1: never traded through
    res = run_backtest(df, EngineConfig(entry_ttl_bars=2))
    assert res.trades.empty and res.summary["entries_expired"] >= 1


def test_exit_crosses_at_the_bid_after_its_ttl_and_pays_taker():
    sig = [1, 1, 0, 0, 0, 0]
    df = bars(highs=[101, 101, 100.5, 100.5, 100.5, 100.5], lows=[99, 99, 99.6, 99.6, 99.6, 99.6],
              closes=[100] * 6, sig=sig)
    cfg = EngineConfig(exit_ttl_bars=2, maker_fee_bp=2, taker_fee_bp=5)
    t = run_backtest(df, cfg).trades.iloc[0]
    assert t.exit == "taker" and t.fee_bp == 7
    assert t.exit_price == 99.5                     # crossed at the bid


def test_funding_is_charged_to_longs_and_paid_to_shorts():
    fund = [0, 0, 0.001, 0, 0, 0]
    common = dict(highs=[101] * 6, lows=[99] * 6, closes=[100] * 6, funding=fund)
    long_ = run_backtest(bars(sig=[1] * 6, **common)).trades.iloc[0]
    short = run_backtest(bars(sig=[-1] * 6, **common)).trades.iloc[0]
    assert long_.funding_bp == pytest.approx(-10.0) and short.funding_bp == pytest.approx(10.0)


def test_lookahead_is_rejected():
    def peeks(df):
        nxt = df.groupby("symbol")["close"].shift(-1)
        return df.assign(signal=np.where(nxt > df["close"], 1, -1))
    with pytest.raises(LookaheadError):
        evaluate(peeks, panel(n_bars=400))


def test_full_sample_statistics_are_rejected():
    def zscore_full(df):    # each symbol z-scored against its WHOLE history, future included
        z = df.groupby("symbol")["close"].transform(lambda s: (s - s.mean()) / s.std())
        return df.assign(signal=np.where(z < 0, 1, 0))
    with pytest.raises(LookaheadError):
        evaluate(zscore_full, panel(n_bars=400))


def test_cross_symbol_leak_is_rejected():
    def leaks(df):   # rolling without groupby: one symbol's rows bleed into the next
        m = df["close"].rolling(20).mean()
        return df.assign(signal=np.where(df["close"] > m, 1, 0))
    with pytest.raises(LookaheadError):
        evaluate(leaks, panel(n_bars=400))


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_example_strategy_passes_the_integrity_checks(name):
    spec = REGISTRY[name]
    res = evaluate(spec.make(**spec.defaults), panel(n_bars=900))
    assert res.summary["integrity_checks"] == "passed"


def test_missing_quotes_are_assumed_and_flagged():
    df = panel(n_bars=300).drop(columns=["bbo_bid", "bbo_ask"])
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), df)
    assert res.summary["quotes"]["assumed"] is True and "assumed" in res.summary["quotes"]["note"]


def test_score_window_forces_flat_outside_it():
    df = panel(n_bars=900)
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), df, score_from="2024-02-01")
    assert (pd.to_datetime(res.trades.entry_time, utc=True) >= pd.Timestamp("2024-02-01", tz="UTC")).all()
