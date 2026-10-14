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
