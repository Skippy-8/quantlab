"""The machine-readable CLI output the Node console depends on."""
import json

from quantlab import cli
from quantlab.stats.deflated import noise_bar
from quantlab.strategies import REGISTRY


def test_strategies_json_lists_every_template(capsys):
    cli.main(["strategies", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in rows] == sorted(REGISTRY)
    assert all(set(r) == {"name", "description", "defaults", "grid"} for r in rows)


def test_registry_json_reports_k_and_bar(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QUANTLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QUANTLAB_LAKE", str(tmp_path / "lake"))
    cli.main(["fetch", "synthetic", "--bars", "600"])
    for fast in (10, 20, 10):          # the repeat is a run, not a new trial
        cli.main(["backtest", "sma_crossover", "--study", "j", "--param", f"fast={fast}"])
    capsys.readouterr()
    cli.main(["registry", "--json"])
    [row] = json.loads(capsys.readouterr().out)
    assert row == {"study": "j", "runs": 3, "k": 2, "bar": noise_bar(2, 2.0), "preregistered": False}


def test_fetch_fred_lands_macro_series_in_the_lake(tmp_path, monkeypatch, capsys):
    import pandas as pd
    import requests

    from quantlab.data.lake import Lake

    class Resp:
        def __init__(self, sid):
            self.text = f"observation_date,{sid}\n2024-01-01,4.0\n2024-01-02,.\n2024-01-03,4.2\n"

        def raise_for_status(self):
            pass

    seen = []
    monkeypatch.setattr(requests, "get", lambda url, timeout: seen.append(url) or Resp(url.split("id=")[1].split("&")[0]))
    monkeypatch.setenv("QUANTLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QUANTLAB_LAKE", str(tmp_path / "lake"))
    cli.main(["fetch", "fred", "DGS10", "UNRATE", "--start", "2024-01"])
    assert all("cosd=2024-01-01" in u for u in seen)
    df = Lake().read("fred", "series")
    assert sorted(df["symbol"].unique()) == ["DGS10", "UNRATE"]
    assert len(df) == 4                       # FRED's "." missing values are dropped
    assert (df["close"] == df["open"]).all() and df["close"].tolist()[:2] == [4.0, 4.2]
    assert isinstance(df["timestamp"].iloc[0], pd.Timestamp)
