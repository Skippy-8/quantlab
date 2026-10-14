"""Backfill / incremental sync of Forms 3, 4 and 5 for a list of tickers.

* The ticker -> CIK map comes from SEC's public ``company_tickers.json``.
* Each company's ``submissions`` JSON lists its newest ~1,000 filings in
  ``filings.recent``; older ones are in ``filings.files[]`` pages, which are
  followed back to ``since``.
* EDGAR's ``primaryDocument`` for these forms points at an XSL-RENDERED page
  (``xslF345X05/form4.xml``); the raw XML is the same file without that folder.
* Filings already in ``ingested_filings`` are skipped, so a killed run resumes.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Iterable

from quantlab.sec import client
from quantlab.sec.parser import parse
from quantlab.sec.store import InsiderStore

FORMS = {"3", "4", "5", "3/A", "4/A", "5/A"}
_XSL = re.compile(r"^xslF345X\d+/")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/{name}"


def raw_doc(primary_doc: str) -> str:
    return _XSL.sub("", primary_doc or "")


def cik_map() -> dict[str, str]:
    d = client.fetch_json(TICKERS_URL)
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in d.values()}


def _rows(block: dict):
    keys = ("accessionNumber", "form", "primaryDocument", "filingDate", "acceptanceDateTime")
    cols = [block.get(k, []) for k in keys]
    for i in range(min((len(c) for c in cols), default=0)):
        yield {k: c[i] for k, c in zip(keys, cols, strict=True)}


def iter_filings(sub: dict, since: str, fetch_json: Callable = client.fetch_json) -> Iterable[dict]:
    f = sub.get("filings", {}) or {}
    for r in _rows(f.get("recent", {}) or {}):
        if (r.get("filingDate") or "") >= since:
            yield r
    for page in f.get("files", []) or []:
        if (page.get("filingTo") or "") < since:
            continue
        for r in _rows(fetch_json(SUBMISSIONS.format(name=page["name"])) or {}):
            if (r.get("filingDate") or "") >= since:
                yield r


def sync(tickers: list[str], since: str, store: InsiderStore | None = None, log=print,
         heartbeat: Callable[[dict], None] | None = None) -> dict:
    store = store or InsiderStore()
    ciks = cik_map()
    known = store.known()
    tot = {"tickers": 0, "filings": 0, "rows": 0, "skipped_known": 0, "errors": 0}
    for tk in tickers:
        cik = ciks.get(tk.upper())
        if not cik:
            log(f"[sec] {tk}: no CIK")
            continue
        sub = client.fetch_json(SUBMISSIONS.format(name=f"CIK{cik}.json"))
        n_rows = n_fil = 0
        for r in iter_filings(sub, since):
            form = (r.get("form") or "").upper()
            acc = r.get("accessionNumber")
            if form not in FORMS or not acc:
                continue
            if acc in known:
                tot["skipped_known"] += 1
                continue
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
                   f"{raw_doc(r.get('primaryDocument'))}")
            try:
                rows = parse(client.fetch(url), acc, cik, tk, r.get("acceptanceDateTime"), form, r.get("filingDate"))
            except Exception as exc:                     # one bad filing must not stop a backfill
                tot["errors"] += 1
                log(f"[sec] {tk} {acc}: {type(exc).__name__}: {exc}")
                continue
            n_rows += store.write(rows, acc, tk, form)
            n_fil += 1
            known.add(acc)
        tot["tickers"] += 1
        tot["filings"] += n_fil
        tot["rows"] += n_rows
        log(f"[sec] {tk:<6} filings {n_fil:>5}  rows {n_rows:>6}  ({time.strftime('%H:%M:%S')})")
        if heartbeat:
            heartbeat({"ticker": tk, **tot})
    return tot
