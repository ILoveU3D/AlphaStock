"""Multi-year statement history, per stock, on demand (L3 modeling only).

- US: SEC companyconcept (multi-year XBRL), CIK via the existing ticker map
- A:  Eastmoney datacenter F10 statement reports (probe-finalized, Task 6)
- HK: Eastmoney HKF10 main indicators + probes (Task 6)

Network entry points are module-level (monkeypatch boundary); a source
failure returns None (fail-closed) and never clobbers an existing file.
"""

from datetime import date

from .. import config
from ..fetch.http import DC, SEC, num as _num
from . import store

# US XBRL concepts: primary with fallbacks (filers disagree on tags).
_US_CONCEPTS = {
    "revenue": ("Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "ebit": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "da": ("DepreciationDepletionAndAmortization",
           "DepreciationAmortizationAndAccretionNet"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "debt": ("LongTermDebt", "LongTermDebtNoncurrent"),
    "shares": ("CommonStockSharesOutstanding",
               "EntityCommonStockSharesOutstanding"),
}
_US_DURATION_MIN_DAYS = 300


def _us_cik(code: str) -> int | None:
    from ..fetch.fundamentals import load_sec_cik_map, normalize_us_ticker
    return load_sec_cik_map().get(normalize_us_ticker(code))


def _us_concept(cik: int, concept: str) -> dict | None:
    return SEC.get_json(
        config.SEC_CONCEPT_URL.format(cik=cik, concept=concept))


def _us_annual(payload: dict | None) -> dict:
    """companyconcept payload -> {fy: val}; annual FY rows only, latest
    filed wins on duplicates."""
    out = {}
    for e in ((payload or {}).get("units") or {}).get("USD", []):
        if e.get("form") not in ("10-K", "20-F") or e.get("fp") != "FY":
            continue
        start, end = e.get("start"), e.get("end")
        if start and end:
            try:
                d0 = date.fromisoformat(start)
                d1 = date.fromisoformat(end)
                if (d1 - d0).days < _US_DURATION_MIN_DAYS:
                    continue
            except ValueError:
                continue
        fy, val, filed = e.get("fy"), e.get("val"), e.get("filed", "")
        if fy is None or val is None:
            continue
        if fy not in out or filed > out[fy][0]:
            out[fy] = (filed, float(val))
    return {fy: v for fy, (_, v) in out.items()}


def fetch_history_us(code: str) -> dict | None:
    cik = _us_cik(code)
    if cik is None:
        return None
    series, name = {}, ""
    for field, concepts in _US_CONCEPTS.items():
        for concept in concepts:
            payload = _us_concept(cik, concept)
            if payload:
                name = name or payload.get("entityName") or ""
                s = _us_annual(payload)
                if s:
                    series[field] = s
                    break
    if "revenue" not in series:
        return None
    fys = sorted({fy for s in series.values() for fy in s})
    fys = fys[-config.MODEL_HISTORY_YEARS:]
    years = [{"fy": fy,
              **{f: series.get(f, {}).get(fy) for f in _US_CONCEPTS}}
             for fy in fys]
    gaps = [f"no us xbrl history for {f}"
            for f in _US_CONCEPTS if f not in series]
    return store.new_history("US", code, name=name,
                             source="sec_companyconcept",
                             currency="USD", years=years, gaps=gaps)


def fetch_history_a(code: str) -> dict | None:
    return _fetch_history_a_probe(code)   # Task 6


def fetch_history_hk(code: str) -> dict | None:
    return _fetch_history_hk_probe(code)  # Task 6


def _fetch_history_a_probe(code: str):
    raise NotImplementedError("A-share history lands in Task 6")


def _fetch_history_hk_probe(code: str):
    raise NotImplementedError("HK history lands in Task 6")


def fetch_history(market: str, code: str) -> dict | None:
    """Dispatch by market; None on source failure (fail-closed)."""
    fn = {"A": fetch_history_a, "HK": fetch_history_hk,
          "US": fetch_history_us}.get(market)
    return fn(code) if fn else None
