import io
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from quantlab import monitor
from quantlab.data.lake import Lake
from quantlab.data.sources import binance
from quantlab.data.synthetic import panel
from quantlab.research import vault


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_HOME", str(tmp_path / "home"))


def test_lake_upsert_is_idempotent_and_queryable(tmp_path):
    lake = Lake(tmp_path / "lake")
    df = panel(n_bars=100)
    lake.write("synthetic", "bars", df)
    lake.write("synthetic", "bars", df.iloc[:50])            # overlap: no duplicates
    back = lake.read("synthetic", "bars")
    assert len(back) == len(df)
    n = lake.duckdb().execute("SELECT count(*) FROM synthetic__bars").fetchone()[0]
    assert n == len(df)
    cat = lake.catalog()
    assert cat.iloc[0]["symbols"] == df["symbol"].nunique()


def test_lake_respects_the_vault(tmp_path):
    lake = Lake(tmp_path / "lake")
    lake.write("oos", "bars", panel(n_bars=50))
    vault.seal(tmp_path / "lake" / "oos")
    with pytest.raises(vault.VaultError):
        lake.read("oos", "bars")


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


def test_binance_kline_zip_with_and_without_header():
    row = "1704067200000,42000,42100,41900,42050,10,1704070799999,420000,100,5,210000,0\n"
    hdr = ",".join(binance.KLINE_COLS) + "\n"
    a = binance.parse_klines_zip(_zip(row), "BTCUSDT")
    b = binance.parse_klines_zip(_zip(hdr + row), "BTCUSDT")
    assert a.equals(b) and a.iloc[0]["timestamp"] == pd.Timestamp("2024-01-01", tz="UTC")
    assert a.iloc[0]["quote_volume"] == 420000


def test_funding_attaches_on_the_settlement_bar():
    k = panel(n_bars=10, symbols=("BTCUSDT",)).drop(columns=["funding_rate"])
    f = pd.DataFrame({"symbol": ["BTCUSDT"], "timestamp": [k.timestamp.iloc[3]], "funding_rate": [0.0001]})
    out = binance.attach_funding(k, f)
    assert out["funding_rate"].sum() == pytest.approx(0.0001) and out["funding_rate"].iloc[3] == 0.0001


def test_monitor_flags_failing_stale_and_ok(tmp_path):
    with monitor.job("good"):
        pass
    with pytest.raises(ValueError):
        with monitor.job("bad"):
            raise ValueError("boom")
    t = monitor.check({"good": 24, "bad": 24, "never": 24}).set_index("name")["status"]
    assert t["good"] == "OK" and t["bad"] == "FAILING" and t["never"] == "NEVER_RAN"
    later = datetime.now(timezone.utc) + timedelta(days=3)
    assert monitor.check({"good": 24}, now=later).iloc[0]["status"] == "STALE"
