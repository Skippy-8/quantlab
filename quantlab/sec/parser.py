"""Form 3 / 4 / 5 ownership-document parser (raw EDGAR XML).

One row per non-derivative transaction (Table I), carrying:
* who: reporting owner CIK and name, director / officer / 10%-owner flags, officer title;
* what: security, transaction code (P = open-market purchase, S = sale, ...),
  acquired/disposed, shares, price, shares owned afterwards;
* when: the TRANSACTION date, the filing date, and the EDGAR ACCEPTANCE timestamp.
  Only the acceptance timestamp is point in time: it is when the market could
  first have known. Backtests must key on it, never on the transaction date;
* plans: the Rule 10b5-1 checkbox (Forms filed from April 2023) and whether
  the row cites a footnote mentioning a 10b5-1 plan. Pre-planned trades carry
  little information, so studies usually separate them.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import time as dtime

import pandas as pd

_RULE = re.compile(r"10b5-?1", re.I)
_ADOPTED = re.compile(r"adopted(?:\s+by\s+the\s+reporting\s+person)?(?:\s+\w+){0,3}?\s+on\s+"
                      r"([A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(el, path: str, default: str = "") -> str:
    if el is None:
        return default
    node = el.find(path)
    return node.text.strip() if node is not None and node.text else default


def _float(v):
    try:
        return float(str(v).replace(",", "").strip()) if v not in (None, "") else None
    except ValueError:
        return None


def _flag(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "y", "yes")


def _tri(v: str):
    v = (v or "").strip().lower()
    return True if v in ("1", "true", "y", "yes") else False if v in ("0", "false", "n", "no") else None


def _date(v):
    try:
        return pd.to_datetime(v).date() if v else None
    except (ValueError, TypeError):
        return None


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def market_session(ts: pd.Timestamp) -> str:
    """Which US session a filing becomes public in: the earliest a trade could act on it."""
    t = ts.tz_convert("America/New_York").time()
    if t < dtime(9, 30):
        return "PRE_MARKET"
    if t <= dtime(16, 0):
        return "REGULAR"
    if t <= dtime(20, 0):
        return "POST_MARKET"
    return "NEXT_OPEN"


def _plan_date(text: str):
    m = _ADOPTED.search(text or "")
    return _date(m.group(1).replace(".", "")) if m else None


def parse(xml_bytes: bytes, accession: str, cik: str, ticker: str, acceptance, form_type: str = "",
          filing_date=None) -> list[dict]:
    """Parse one ownership document. Returns [] for anything that is not one."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    _strip_ns(root)
    if root.tag != "ownershipDocument":
        return []
    acc = _utc(acceptance)
    notes = {fn.get("id"): (fn.text or "").strip() for fn in root.iter("footnote") if fn.get("id")}
    remarks = _text(root, "remarks")
    aff = _tri(_text(root, "aff10b5One"))
    doc_plan = next((_plan_date(t) for t in [*notes.values(), remarks] if _RULE.search(t) and _plan_date(t)), None)
    owner = root.find(".//reportingOwner")
    ocik = _text(owner, ".//rptOwnerCik")
    base = {
        "accession_number": accession, "cik": str(cik).zfill(10), "ticker": ticker.upper(),
        "form_type": (form_type or _text(root, "documentType")).upper(),
        "acceptance_datetime_utc": acc, "market_session": market_session(acc),
        "filing_date": _date(str(filing_date)) if filing_date else acc.date(),
        "period_of_report": _date(_text(root, "periodOfReport")),
        "owner_cik": ocik.zfill(10) if ocik else "", "owner_name": _text(owner, ".//rptOwnerName"),
        "officer_title": _text(owner, ".//officerTitle"),
        "is_director": _flag(_text(owner, ".//isDirector", "0")),
        "is_officer": _flag(_text(owner, ".//isOfficer", "0")),
        "is_ten_percent_owner": _flag(_text(owner, ".//isTenPercentOwner", "0")),
        "aff10b5one": aff,
    }
    rows = []
    for i, txn in enumerate(root.findall(".//nonDerivativeTransaction")):
        ids = [f.get("id") for f in txn.iter("footnoteId") if f.get("id")]
        cites = [notes.get(x, "") for x in ids]
        hit = any(_RULE.search(t) for t in cites)
        pdate = next((_plan_date(t) for t in cites if _RULE.search(t) and _plan_date(t)), None)
        shares = _float(_text(txn, ".//transactionAmounts/transactionShares/value"))
        price = _float(_text(txn, ".//transactionAmounts/transactionPricePerShare/value"))
        rows.append({**base, "line": i,
                     "security_title": _text(txn, ".//securityTitle/value"),
                     "transaction_date": _date(_text(txn, ".//transactionDate/value")),
                     "transaction_code": _text(txn, ".//transactionCoding/transactionCode").upper()[:1],
                     "acquired_disposed": _text(txn, ".//transactionAmounts/transactionAcquiredDisposedCode/value").upper()[:1],
                     "shares": shares, "price": price,
                     "value_usd": shares * price if shares is not None and price is not None else None,
                     "shares_owned_after": _float(_text(txn, ".//postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                     "direct_or_indirect": _text(txn, ".//ownershipNature/directOrIndirectOwnership/value"),
                     "in_10b5_1_footnote": hit,
                     "plan_adoption_date": pdate or (doc_plan if (hit or aff is True) else None)})
    return rows
