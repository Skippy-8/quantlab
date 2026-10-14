import numpy as np
import pandas as pd
import pytest

from quantlab import indicators as I
from quantlab.data.synthetic import panel
from quantlab.engine import EngineConfig, check_no_lookahead, check_symbol_order_invariance, evaluate, prepare
from quantlab.rules import EXAMPLES, RuleError, RuleStrategy, evaluate_expr

DF = prepare(panel(n_bars=400))
ONE_ARG = {"lag": (lambda df: I.lag(df, "close", 2)), "highest": (lambda df: I.highest(df, "high", 10)),
           "lowest": (lambda df: I.lowest(df, "low", 10))}


@pytest.mark.parametrize("name", sorted(I.REGISTRY))
def test_every_indicator_is_causal_and_per_symbol(name):
    f = ONE_ARG.get(name) or (lambda df: I.REGISTRY[name](df))

    def strat(df):
        v = f(df)
        return df.assign(signal=np.where(v > v.groupby(df["symbol"]).transform(
            lambda s: s.expanding().median()), 1, 0))
    assert check_no_lookahead(strat, DF) and check_symbol_order_invariance(strat, DF)


def test_rsi_matches_a_hand_computation_on_a_trend():
    up = pd.DataFrame({"symbol": "X", "close": np.arange(1, 60, dtype=float)})
    assert I.rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    assert I.sma(up, 5).iloc[-1] == pytest.approx(np.mean(np.arange(55, 60)))


def test_expressions_evaluate_and_combine():
    s = evaluate_expr("rsi(14) < 30 and close > sma(50)", DF)
    manual = (I.rsi(DF, 14) < 30) & (DF["close"] > I.sma(DF, 50))
    assert (s == manual.fillna(False)).all()
    x = evaluate_expr("crosses_above(ema(5), ema(20))", DF)
    assert x.sum() > 0 and x.dtype == bool


@pytest.mark.parametrize("bad", ["__import__('os')", "close.__class__", "open('x')", "[1, 2]", "lambda: 1",
                                 "exec('1')", "sma(20)[0]", "unknown_fn(3)", "nonsense > 1"])
def test_rules_cannot_run_arbitrary_code(bad):
    with pytest.raises(RuleError):
        evaluate_expr(bad, DF)


def test_position_logic_entry_exit_and_reversal():
    df = pd.DataFrame({"symbol": "X", "timestamp": pd.date_range("2024", periods=6, freq="h", tz="UTC"),
                       "open": 1.0, "high": 1.0, "low": 1.0, "volume": 1.0,
                       "close": [1.0, 5.0, 5.0, 2.0, 0.5, 5.0]})
    r = RuleStrategy("t", long_entry="close > 4", long_exit="close < 3", short_entry="close < 1")
    assert r.signal_fn()(df)["signal"].tolist() == [0, 1, 1, 0, -1, 1]


@pytest.mark.parametrize("spec", EXAMPLES, ids=[e.name for e in EXAMPLES])
def test_example_rule_strategies_run_through_the_engine(spec):
    df = panel(n_bars=900)
    spec.validate(df)
    res = evaluate(spec.signal_fn(), df, EngineConfig(exits=spec.exit_rules()))
    assert res.summary["integrity_checks"] == "passed"


def test_yaml_round_trip_and_unknown_keys(tmp_path):
    spec = EXAMPLES[2]
    back = RuleStrategy.from_yaml(spec.to_yaml())
    assert back == spec and back.exit_rules().take_profits == ((0.03, 0.5), (0.06, 0.5))
    p = spec.save(tmp_path)
    assert p.read_text().startswith("name:")
    with pytest.raises(RuleError):
        RuleStrategy.from_yaml("name: x\nbogus: 1\n")
