"""quantlab sql (read-only SQL over the lake) and the general-purpose quality profile."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantlab import cli
from quantlab.data import quality
from quantlab.data.lake import Lake
from quantlab.research import vault
from quantlab.research.vault import VaultError
from quantlab.sec.parser import parse
from quantlab.sec.store import InsiderStore

DAYS = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")


def bars(symbol: str, close: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": DAYS, "symbol": symbol, "open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": 1e6})


@pytest.fixture
def lake(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QUANTLAB_LAKE", str(tmp_path / "lake"))
    monkeypatch.setenv("QUANTLAB_SEC_DB", str(tmp_path / "sec" / "insider.duckdb"))
    rng = np.random.default_rng(3)
    lk = Lake()
    lk.write("yahoo", "daily", pd.concat([bars("SPY", 400 * np.exp(np.cumsum(rng.normal(0, 0.01, 120)))),
                                          bars("TLT", 90 * np.exp(np.cumsum(rng.normal(0, 0.008, 120))))]))
    rate = 4.0 + np.cumsum(rng.normal(0, 0.05, 120))
    lk.write("fred", "series", pd.DataFrame({"timestamp": DAYS, "symbol": "DGS10", "open": rate, "high": rate,
                                             "low": rate, "close": rate, "volume": 0.0}))
    return lk


def test_join_macro_regimes_with_asset_returns(lake):
    q = """
        WITH m AS (SELECT date_trunc('month', timestamp) AS month,
                          last(close ORDER BY timestamp) - first(close ORDER BY timestamp) AS rate_chg
                   FROM fred__series WHERE symbol = 'DGS10' GROUP BY 1),
             a AS (SELECT symbol, date_trunc('month', timestamp) AS month,
                          last(close ORDER BY timestamp) / first(close ORDER BY timestamp) - 1 AS ret
                   FROM yahoo__daily GROUP BY 1, 2)
        SELECT a.symbol, a.month, m.rate_chg, a.ret,
               CASE WHEN m.rate_chg > 0 THEN 'rising' ELSE 'falling' END AS regime
        FROM a JOIN m USING (month) ORDER BY a.symbol, a.month"""
    got = lake.sql(q)
    assert len(got) == 2 * 4 and set(got["regime"]) <= {"rising", "falling"}

    px = lake.read("yahoo", "daily")
    rt = lake.read("fred", "series")
    month = lambda d: d["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M")  # noqa: E731
    want_rate = rt.groupby(month(rt))["close"].agg(lambda s: s.iloc[-1] - s.iloc[0])
    want_ret = px.groupby(["symbol", month(px)])["close"].agg(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    for r in got.itertuples():
        p = pd.Timestamp(r.month).tz_localize(None).to_period("M")
        assert r.rate_chg == pytest.approx(want_rate[p])
        assert r.ret == pytest.approx(want_ret[(r.symbol, p)])


def test_window_function_drawdown_matches_pandas(lake):
    got = lake.sql("""
        SELECT symbol, timestamp, close / max(close) OVER (PARTITION BY symbol ORDER BY timestamp) - 1 AS dd
        FROM yahoo__daily ORDER BY symbol, timestamp""")
    px = lake.read("yahoo", "daily")
    want = px["close"] / px.groupby("symbol")["close"].cummax() - 1
    np.testing.assert_allclose(got["dd"].to_numpy(), want.to_numpy())


@pytest.mark.parametrize("q", [
    "COPY (SELECT * FROM yahoo__daily) TO 'out.csv'",
    "CREATE TABLE t AS SELECT 1",
    "INSERT INTO t VALUES (1)",
    "DROP VIEW yahoo__daily",
    "ATTACH 'other.duckdb' AS o",
    "SELECT 1; SELECT 2",
])
def test_only_single_select_statements_run(lake, tmp_path, monkeypatch, q):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        lake.sql(q)
    assert not (tmp_path / "out.csv").exists()


def test_sql_cannot_read_a_sealed_vault(lake, tmp_path):
    lake.write("holdout", "bars", bars("SPY", np.linspace(100, 110, 120)))
    vault.seal(Path(lake.root) / "holdout" / "bars", register=tmp_path / "reg.jsonl")
    assert ("holdout", "bars") not in lake.readable()
    with pytest.raises(Exception, match="holdout__bars"):
        lake.sql("SELECT count(*) FROM holdout__bars")
    with pytest.raises(VaultError):
        lake.read("holdout", "bars")
    assert "holdout" not in set(lake.catalog()["source"])


def test_sec_store_is_attached_read_only_and_joins_prices(lake, tmp_path):
    xml = (Path(__file__).parent / "fixtures" / "form4_example.xml").read_bytes()
    rows = parse(xml, "0001234567-25-000001", "9999999", "SPY", "2024-02-05T21:15:00Z", "4", "2024-02-05")
    store = InsiderStore(tmp_path / "sec" / "insider.duckdb")
    store.write(rows, "0001234567-25-000001", "SPY", "4")
    store.close()
    got = lake.sql("""
        SELECT t.ticker, t.transaction_code, p.close
        FROM sec.insider_transactions t
        JOIN yahoo__daily p ON p.symbol = t.ticker AND p.timestamp = date_trunc('day', t.acceptance_datetime_utc)
        ORDER BY t.line""", sec_db=tmp_path / "sec" / "insider.duckdb")
    assert list(got["transaction_code"]) == ["P", "S"] and got["close"].notna().all()
    with pytest.raises(ValueError):
        lake.sql("DELETE FROM sec.insider_transactions", sec_db=tmp_path / "sec" / "insider.duckdb")
    assert "sec.insider_transactions" in set(lake.tables(tmp_path / "sec" / "insider.duckdb")["name"])


def test_cli_formats_export_and_errors(lake, tmp_path, capsys):
    assert cli.main(["sql", "SELECT symbol, count(*) AS n FROM yahoo__daily GROUP BY 1 ORDER BY 1",
                     "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"symbol": "SPY", "n": 120}, {"symbol": "TLT", "n": 120}]
    out = tmp_path / "x.parquet"
    assert cli.main(["sql", "SELECT * FROM fred__series", "--export", str(out)]) == 0
    assert len(pd.read_parquet(out)) == 120
    assert cli.main(["sql", "--tables"]) == 0
    assert {"fred__series", "yahoo__daily"} <= set(capsys.readouterr().out.split())
    assert cli.main(["sql", "COPY (SELECT 1) TO 'x.csv'"]) == 2
    assert "only read-only SELECT" in capsys.readouterr().err


def test_profile_reports_schema_and_completeness_for_any_table():
    df = pd.DataFrame({"ticker": ["A", "B", None, "A"], "value_usd": [1.0, np.nan, 3.0, 4.0],
                       "officer": [True, False, True, None]})
    p = quality.profile(df)
    assert p["schema"] == {"rows": 4, "columns": 3}
    c = p["columns"].set_index("column")
    assert c.loc["ticker", "non_null_pct"] == 75.0 and c.loc["ticker", "distinct"] == 2
    assert c.loc["value_usd", "nulls"] == 1 and (c.loc["value_usd", "min"], c.loc["value_usd", "max"]) == (1.0, 4.0)


def test_report_adds_profile_and_ohlc_completeness_without_changing_grades():
    df = bars("SPY", 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 120))))
    before = quality.report(df)["symbols"].iloc[0]["grade"]
    df.loc[5, "close"] = np.nan
    rep = quality.report(df)
    assert rep["symbols"].iloc[0]["complete_pct"] == pytest.approx(100 * 119 / 120, abs=0.01)
    assert rep["schema"]["symbols"] == 1 and rep["schema"]["median_step"] == "1 days 00:00:00"
    assert rep["columns"].set_index("column").loc["close", "nulls"] == 1
    assert before == "A" and rep["symbols"].iloc[0]["grade"] == "B"   # one non-severe finding
    assert rep["findings"].iloc[0]["check"] == "missing" and rep["findings"].iloc[0]["detail"] == "empty close"


def test_cli_quality_profiles_a_query_result(lake, capsys):
    assert cli.main(["quality", "--sql", "SELECT symbol, close AS level FROM fred__series"]) == 0
    out = capsys.readouterr().out
    assert "schema: rows 120, columns 2, symbols 1" in out and "level" in out
    assert cli.main(["quality", "yahoo/daily"]) == 0
    assert "complete_pct" in capsys.readouterr().out
