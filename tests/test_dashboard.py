"""Every dashboard page renders without an exception, and the main actions run.

Runs headlessly with Streamlit's AppTest against synthetic data in a temporary lake.
"""
import ast
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "dashboard" / "views"


@pytest.fixture(autouse=True)
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QUANTLAB_LAKE", str(tmp_path / "lake"))
    monkeypatch.setenv("QUANTLAB_SEC_DB", str(tmp_path / "sec" / "insider.duckdb"))
    monkeypatch.syspath_prepend(str(ROOT / "dashboard"))
    from quantlab.data.lake import Lake
    from quantlab.data.synthetic import panel
    Lake(tmp_path / "lake").write("synthetic", "bars", panel(n_bars=1200))


def app(view: str):
    at = st_testing.AppTest.from_file(str(VIEWS / f"{view}.py"), default_timeout=300)
    at.run()
    return at


def errors(at):
    return [e.value for e in at.exception] + [e.value for e in at.error]


def click(at, label: str):
    btn = next(b for b in at.button if b.label == label)
    btn.click().run()
    return at


def test_every_navigation_entry_points_at_a_real_file():
    tree = ast.parse((ROOT / "dashboard" / "app.py").read_text())
    base = next(n.value.value for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "V")
    pages = [n.args[0].right.value for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "Page" and isinstance(n.args[0], ast.BinOp)]
    assert len(pages) >= 13
    for p in pages:                                      # st.Page paths resolve relative to app.py
        assert (ROOT / "dashboard" / base / p).exists(), p


@pytest.mark.parametrize("view", sorted(p.stem for p in VIEWS.glob("*.py")))
def test_page_renders(view):
    assert errors(app(view)) == []


def test_backtest_runs_and_reports():
    at = click(app("backtest"), "Run backtest")
    assert errors(at) == []
    labels = [m.label for m in at.metric]
    assert {"Sharpe", "Max drawdown", "Day t", "DSR"} <= set(labels)


def test_options_lab_runs_on_a_synthetic_chain():
    at = app("options")
    at.slider[0].set_value(80).run()
    at = click(at, "Run options backtest")
    assert errors(at) == [] and any(m.label == "Trades" for m in at.metric)


def test_walk_forward_runs():
    at = app("walkforward")
    at.number_input[0].set_value(10).run()
    at.number_input[1].set_value(5).run()
    at = click(at, "Run walk-forward")
    assert errors(at) == []
