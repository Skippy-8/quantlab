import pandas as pd
import pytest

from quantlab.data.synthetic import panel
from quantlab.engine import EngineConfig, ExitRules, evaluate, run_backtest
from quantlab.portfolio import ContractSpec, Sizing, simulate
from quantlab.strategies import REGISTRY


def one_trade(prices, sig):
    n = len(prices)
    df = pd.DataFrame({"symbol": "X", "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
                       "open": prices, "high": [p + 1 for p in prices], "low": [p - 1 for p in prices],
                       "close": prices, "volume": 1.0, "bbo_bid": [p - 0.5 for p in prices],
                       "bbo_ask": [p + 0.5 for p in prices], "signal": sig})
    return run_backtest(df, EngineConfig(maker_fee_bp=0, taker_fee_bp=0))


def test_fixed_notional_realises_the_engine_net_in_dollars():
    res = one_trade([100, 100, 110, 110, 110], [1, 1, 0, 0, 0])
    pf = simulate(res, Sizing(method="fixed_notional", notional=10_000, initial_capital=50_000))
    net_bp = res.positions.iloc[0]["net_bp"]
    assert pf.ledger.iloc[0]["pnl"] == pytest.approx(10_000 * net_bp / 1e4)
    assert pf.stats["final_equity"] == pytest.approx(50_000 + 10_000 * net_bp / 1e4)


def test_leverage_cap_skips_positions():
    df = panel(n_bars=600)
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), df)
    pf = simulate(res, Sizing(method="fixed_fraction", fraction=0.6, max_leverage=1.0))
    assert pf.stats["positions_skipped"]["leverage"] > 0
    assert pf.stats["positions_taken"] + sum(pf.stats["positions_skipped"].values()) == len(res.positions)


def test_max_positions_limit():
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), panel(n_bars=600))
    pf = simulate(res, Sizing(method="fixed_fraction", fraction=0.05, max_positions=1))
    assert pf.stats["positions_skipped"]["max_positions"] > 0


def test_futures_round_to_whole_contracts():
    res = one_trade([100, 100, 110, 110, 110], [1, 1, 0, 0, 0])
    pf = simulate(res, Sizing(method="fixed_notional", notional=25_000, initial_capital=100_000,
                              contracts={"X": ContractSpec(multiplier=50, initial_margin=1_000)}))
    led = pf.ledger.iloc[0]
    assert led["qty"] == 5 and led["notional"] == pytest.approx(5 * 99.5 * 50)   # 25,000 / 4,975 = 5.02


def test_risk_per_trade_needs_a_stop_and_sizes_off_it():
    res = one_trade([100, 100, 110, 110, 110], [1, 1, 0, 0, 0])
    with pytest.raises(ValueError):
        simulate(res, Sizing(method="risk_per_trade"))
    df = panel(n_bars=400)
    cfg = EngineConfig(exits=ExitRules(stop_loss=0.02))
    res2 = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), df, cfg)
    pf = simulate(res2, Sizing(method="risk_per_trade", risk_fraction=0.01, max_weight=1.0, max_leverage=5.0))
    first = pf.ledger.iloc[0]
    assert first["notional"] == pytest.approx(100_000 * 0.01 / 0.02, rel=0.05)


def test_vol_target_sizes_calm_assets_larger():
    df = panel(n_bars=800, symbols=("CALM",), vol=0.002)
    wild = panel(n_bars=800, symbols=("WILD",), vol=0.02, seed=3)
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), pd.concat([df, wild]))
    led = simulate(res, Sizing(method="vol_target", max_leverage=10, max_weight=5)).ledger
    by = led.groupby("symbol")["notional"].median()
    assert by["CALM"] > 3 * by["WILD"]


def test_equity_curve_is_marked_every_bar():
    res = evaluate(REGISTRY["sma_crossover"].make(fast=5, slow=20), panel(n_bars=300))
    pf = simulate(res)
    assert len(pf.equity) == res.frame["timestamp"].nunique()
    assert pf.daily_returns.index.is_monotonic_increasing
