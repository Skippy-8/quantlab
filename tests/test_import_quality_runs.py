import pandas as pd
import pytest

from quantlab.data import importer, quality
from quantlab.data.synthetic import panel
from quantlab.engine import evaluate
from quantlab.portfolio import simulate
from quantlab.research import runs
from quantlab.strategies import REGISTRY


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_HOME", str(tmp_path / "home"))


def test_import_guesses_columns_and_parses_epoch_ms():
    raw = pd.DataFrame({"Ticker": ["aapl", "aapl"], "open_time": [1704067200000, 1704153600000],
                        "Open": [1, 2], "High": [2, 3], "Low": [0.5, 1.5], "Close": [1.5, 2.5], "Vol": [10, 20]})
    out = importer.standardize(raw)
    assert list(out["symbol"].unique()) == ["AAPL"]
    assert out["timestamp"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert out["volume"].sum() == 30


def test_import_close_only_series_and_explicit_mapping():
    raw = pd.DataFrame({"when": ["2024-01-01", "2024-01-02"], "px": [10.0, 11.0]})
    out = importer.standardize(raw, mapping={"timestamp": "when", "close": "px"}, symbol="spy")
    assert out["open"].tolist() == [10.0, 11.0] and out["symbol"].iat[0] == "SPY"
    with pytest.raises(ValueError):
        importer.standardize(pd.DataFrame({"a": [1]}))


def test_quality_finds_gaps_bad_bars_outliers_and_splits():
    df = panel(n_bars=300, symbols=("AAA",))
    df = df.drop(index=range(100, 110))                                 # a gap
    df.loc[150, "high"] = df.loc[150, "low"] - 1                         # a broken bar
    df.loc[200:, ["open", "high", "low", "close", "bbo_bid", "bbo_ask"]] /= 2   # an unadjusted 2:1 split
    rep = quality.report(df)
    checks = set(rep["findings"]["check"])
    assert {"gap", "bad_bar", "split?"} <= checks
    assert rep["symbols"].iloc[0]["grade"] == "D"


def test_clean_data_grades_a():
    assert quality.report(panel(n_bars=300, symbols=("AAA",)))["symbols"].iloc[0]["grade"] in ("A", "B")


def test_runs_round_trip_and_compare():
    df = panel(n_bars=500)
    ids = []
    for fast in (5, 10):
        res = evaluate(REGISTRY["sma_crossover"].make(fast=fast, slow=30), df)
        ids.append(runs.save(f"sma {fast}", "sma_crossover", {"fast": fast}, res, simulate(res)))
    assert len(runs.list_runs()) == 2
    back = runs.load(ids[0])
    assert back["manifest"]["params"] == {"fast": 5} and len(back["positions"]) > 0
    cmp = runs.compare(ids)
    assert list(cmp.index) == ["sma 5", "sma 10"] and "sharpe" in cmp
    runs.delete(ids[1])
    assert len(runs.list_runs()) == 1
