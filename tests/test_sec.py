import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from quantlab.sec import client
from quantlab.sec.parser import market_session, parse
from quantlab.sec.store import InsiderStore
from quantlab.sec.sync import iter_filings, raw_doc

XML = (Path(__file__).parent / "fixtures" / "form4_example.xml").read_bytes()
ACC = "2025-03-05T21:15:00Z"          # 16:15 New York: public after the close


def rows():
    return parse(XML, "0001234567-25-000001", "9999999", "exmp", ACC, "4", "2025-03-05")


def test_parses_roles_codes_and_amounts():
    r = rows()
    assert len(r) == 2
    buy, sale = r
    assert buy["is_officer"] and not buy["is_director"] and buy["officer_title"] == "Chief Financial Officer"
    assert buy["transaction_code"] == "P" and buy["shares"] == 1000 and buy["value_usd"] == pytest.approx(50250)
    assert buy["owner_cik"] == "0001234567" and buy["ticker"] == "EXMP"


def test_point_in_time_fields():
    buy = rows()[0]
    assert buy["acceptance_datetime_utc"] == pd.Timestamp(ACC)
    assert buy["transaction_date"] == dt.date(2025, 3, 3)          # trade date is NOT the public date
    assert buy["market_session"] == "POST_MARKET"


def test_10b5_1_plan_is_detected_per_row():
    buy, sale = rows()
    assert buy["in_10b5_1_footnote"] is False and buy["plan_adoption_date"] is None
    assert sale["in_10b5_1_footnote"] is True and sale["plan_adoption_date"] == dt.date(2024, 11, 15)


def test_non_ownership_documents_yield_nothing():
    assert parse(b"<html><body>FORM 4</body></html>", "a", "1", "x", ACC) == []


def test_store_is_idempotent_and_point_in_time(tmp_path):
    s = InsiderStore(tmp_path / "ins.duckdb")
    s.write(rows(), "0001234567-25-000001", "EXMP", "4")
    s.write(rows(), "0001234567-25-000001", "EXMP", "4")        # re-ingest changes nothing
    assert s.summary()["rows"] == 2
    assert len(s.as_of("2025-03-05 20:00:00+00:00", "EXMP")) == 0   # not public yet
    assert len(s.as_of("2025-03-06", "EXMP")) == 2
    p = s.purchases()
    assert len(p) == 1 and p.iloc[0]["officer"]


def test_xsl_prefix_is_stripped_to_reach_the_raw_xml():
    assert raw_doc("xslF345X05/wk-form4_1.xml") == "wk-form4_1.xml"


def test_paging_follows_older_files_back_to_since():
    sub = {"filings": {"recent": {"accessionNumber": ["a1"], "form": ["4"], "primaryDocument": ["d"],
                                  "filingDate": ["2025-01-02"], "acceptanceDateTime": ["x"]},
                       "files": [{"name": "old.json", "filingTo": "2024-06-30"},
                                 {"name": "older.json", "filingTo": "2019-01-01"}]}}
    pages = {"old.json": {"accessionNumber": ["a2"], "form": ["4"], "primaryDocument": ["d"],
                          "filingDate": ["2024-03-01"], "acceptanceDateTime": ["x"]}}
    got = [r["accessionNumber"] for r in iter_filings(sub, "2024-01-01", fetch_json=lambda u: pages[u.split("/")[-1]])]
    assert got == ["a1", "a2"]


def test_client_refuses_to_run_without_a_contact(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError):
        client.user_agent()
    assert market_session(pd.Timestamp("2025-03-05T15:00:00Z")) == "REGULAR"   # 10:00 New York


def test_purchases_have_a_total_order_when_filings_share_an_acceptance_time(tmp_path):
    store = InsiderStore(tmp_path / "s.duckdb")
    same = "2025-03-05T21:15:00Z"
    for i, tk in enumerate(["ZZZ", "AAA", "MMM"]):
        r = parse(XML, f"0001234567-25-00000{i}", "9999999", tk.lower(), same, "4", "2025-03-05")
        store.write(r, f"0001234567-25-00000{i}", tk, "4")
    assert list(store.purchases()["ticker"]) == ["AAA", "MMM", "ZZZ"]
