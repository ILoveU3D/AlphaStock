"""On-demand profile raw fetchers (Phase 5 prototype — no bulk).

Only the L3 deep-review shortlist gets fetched, one stock at a time.
Sources (probe-finalized 2026-09-29, data/probe_profiles.py):

- A:  datacenter ``RPT_F10_ORG_BASICINFO`` — long summary in
  ``ORG_PROFIE`` (sic), one-line vision in ``ORG_PROFILE``.
- HK: datacenter ``RPT_HKF10_INFO_ORGPROFILE`` — long summary in
  ``ORG_PROFILE`` (different column than A!).
- US: SEC submissions meta + stockanalysis profile ``description``
  from the embedded flight-data blob.

All network entry points are module-level (monkeypatch boundary);
a source failure returns None (fail-closed) and never clobbers an
existing raw file.
"""

import json
import re

from .. import config
from ..profile import new_raw, save_raw
from .http import DC, SA, SEC


def _a_secucode(code: str) -> str:
    """600900 -> 600900.SH (6/9 -> SH, 0/2/3 -> SZ, 4/8 -> BJ)."""
    head = code[0]
    suffix = "SH" if head in "69" else "BJ" if head in "48" else "SZ"
    return f"{code}.{suffix}"


def _txt(v) -> str:
    return str(v).strip() if v not in (None, "") else ""


# ---------------------------------------------------------------------------
# A-share: Eastmoney F10 org basicinfo
# ---------------------------------------------------------------------------
def fetch_profile_a(code: str) -> dict | None:
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.A_ORG_BASICINFO_REPORT, "columns": "ALL",
        "filter": f'(SECUCODE="{_a_secucode(code)}")',
        "pageNumber": 1, "pageSize": 1, "source": "F10", "client": "PC"})
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    r = rows[0]
    meta = {
        "org_name": _txt(r.get("ORG_NAME")),
        "chairman": _txt(r.get("CHAIRMAN")),
        "president": _txt(r.get("PRESIDENT")),
        "secretary": _txt(r.get("SECRETARY")),
        "founded": _txt(r.get("FOUND_DATE")),
        "listed": _txt(r.get("LISTING_DATE")),
        "website": _txt(r.get("ORG_WEB")),
        "address": _txt(r.get("ADDRESS")),
        "control_holder": _txt(r.get("CONTROL_HOLDER")),
        "real_controller": _txt(r.get("REAL_CONTROLER")),
        "independent_directors": _txt(r.get("INDEDIRECTORS")),
        "employees": _txt(r.get("TOTAL_NUM")),
        "industry": _txt(r.get("EM2016")),
        "org_form": _txt(r.get("ORG_FORM")),
        "top_profit_product": _txt(r.get("MAXPROFIT_PRODUCT")),
        "income_structure": _txt(r.get("INCOME_STRU_NAME")),
        "income_structure_ratio": _txt(r.get("INCOME_STRU_RATIO")),
        "auditor": _txt(r.get("ACCOUNT_FIRM")),
        "concepts": _txt(r.get("BLGAINIAN")),
        "business_scope": _txt(r.get("BUSINESS_SCOPE")),
    }
    return new_raw("A", code, name=_txt(r.get("SECURITY_NAME_ABBR")),
                   source="eastmoney_f10_org_basicinfo",
                   source_url=config.DC_SEC_URL,
                   summary=_txt(r.get("ORG_PROFIE")),
                   main_business=_txt(r.get("MAIN_BUSINESS")),
                   vision=_txt(r.get("ORG_PROFILE")), meta=meta)


# ---------------------------------------------------------------------------
# HK: Eastmoney HK F10 org profile
# ---------------------------------------------------------------------------
def fetch_profile_hk(code5: str) -> dict | None:
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_ORGPROFILE_REPORT, "columns": "ALL",
        "filter": f'(SECUCODE="{code5}.HK")',
        "pageNumber": 1, "pageSize": 1, "source": "F10", "client": "PC"})
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    r = rows[0]
    meta = {
        "org_name": _txt(r.get("ORG_NAME")),
        "org_en": _txt(r.get("ORG_EN_ABBR")),
        "chairman": _txt(r.get("CHAIRMAN")),
        "secretary": _txt(r.get("SECRETARY")),
        "founded": _txt(r.get("FOUND_DATE")),
        "listed": _txt(r.get("LISTING_DATE")),
        "website": _txt(r.get("ORG_WEB")),
        "address": _txt(r.get("ADDRESS")),
        "employees": _txt(r.get("EMP_NUM")),
        "industry": _txt(r.get("INDUSTRY_TYPE")),
        "belong_industry": _txt(r.get("BELONG_INDUSTRY")),
        "auditor": _txt(r.get("ACCOUNT_FIRM")),
        "org_type": _txt(r.get("ORG_TYPE")),
        "currency": _txt(r.get("CURRENCY")),
        "trade_unit": _txt(r.get("TRADE_UNIT")),
    }
    return new_raw("HK", code5, name=_txt(r.get("SECURITY_NAME_ABBR")),
                   source="eastmoney_hkf10_orgprofile",
                   source_url=config.DC_SEC_URL,
                   summary=_txt(r.get("ORG_PROFILE")),
                   main_business=_txt(r.get("MAIN_BUSINESS")),
                   vision="", meta=meta)


# ---------------------------------------------------------------------------
# US: SEC submissions meta + stockanalysis description
# ---------------------------------------------------------------------------
_SA_DESC_RE = re.compile(r'description:"((?:[^"\\]|\\.)*)"')


def _sa_description(ticker: str) -> str:
    """Company description from the stockanalysis profile flight blob."""
    slug = ticker.lower().replace("_", "-")
    html = SA.get_text(config.SA_PROFILE_URL_TMPL.format(slug=slug))
    if not html:
        return ""
    m = _SA_DESC_RE.search(html)
    if not m:
        return ""
    try:  # the blob is a JS string literal — decode its escapes
        return json.loads(f'"{m.group(1)}"')
    except json.JSONDecodeError:
        return m.group(1).replace('\\"', '"').replace("\\n", " ")


def fetch_profile_us(ticker: str) -> dict | None:
    from .fundamentals import load_sec_cik_map
    cik = (load_sec_cik_map() or {}).get(ticker)
    meta, name = {}, ""
    if cik:
        d = SEC.get_json(config.SEC_SUBMISSIONS_URL_TMPL.format(cik=cik),
                         timeout=30)
        if d:
            name = _txt(d.get("name"))
            meta = {
                "org_name": name,
                "sic": _txt(d.get("sic")),
                "industry": _txt(d.get("sicDescription")),
                "entity_type": _txt(d.get("entityType")),
                "filer_category": _txt(d.get("filerCategory")),
                "fiscal_year_end": _txt(d.get("fiscalYearEnd")),
                "state_of_incorporation":
                    _txt(d.get("stateOfIncorporation")),
                "cik": _txt(d.get("cik")),
                "exchanges": ",".join(d.get("exchanges") or []),
            }
    summary = _sa_description(ticker)
    if not meta and not summary:
        return None
    return new_raw("US", ticker, name=name,
                   source="stockanalysis+sec_submissions",
                   source_url=config.SA_PROFILE_URL_TMPL.format(
                       slug=ticker.lower().replace("_", "-")),
                   summary=summary,
                   main_business=meta.get("industry", ""),
                   vision="", meta=meta)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
FETCHERS = {"A": fetch_profile_a, "HK": fetch_profile_hk,
            "US": fetch_profile_us}


def fetch_profile(market: str, code: str) -> dict | None:
    """Fetch the raw profile for one stock; None on source failure."""
    fn = FETCHERS.get(market)
    if fn is None:
        raise ValueError(f"unknown market {market!r}")
    return fn(code)


def update_raw(market: str, code: str) -> dict | None:
    """Fetch and persist; an unchanged content_hash just bumps
    fetched_at (save_raw rewrites the file either way).  A failed fetch
    returns None and leaves any existing raw untouched (fail-closed)."""
    raw = fetch_profile(market, code)
    if raw is None:
        return None
    save_raw(raw)
    return raw
