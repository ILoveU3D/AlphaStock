"""Company-profile raw-text fetchers (A/HK/US) + incremental updater.

Sources (all probe-validated 2026-09-29):

- A:  Eastmoney datacenter ``RPT_F10_ORG_BASICINFO`` — ORG_PROFIE
  (sic — Eastmoney's own typo'd column carries the long 公司简介;
  ORG_PROFILE is only a one-line slogan) / MAIN_BUSINESS (主营业务) /
  BUSINESS_SCOPE (经营范围) plus governance meta (CHAIRMAN /
  CONTROL_HOLDER / REAL_CONTROLER / FOUND_DATE / EMP total / income
  structure / BLGAINIAN concept boards).
- HK: Eastmoney datacenter ``RPT_HKF10_INFO_ORGPROFILE``
  (columns ALL — same report as ``fetch_hk_lot``) — ORG_PROFILE /
  MAIN_BUSINESS / CHAIRMAN / EMP_NUM / FOUND_DATE.
- US: SEC submissions API (entity meta: sic/sicDescription/category/
  fiscalYearEnd/stateOfIncorporation) + stockanalysis.com main page
  flight-data ``description:"..."`` (business summary text).

Every network function is module-level (monkeypatch boundary).  Source
failure returns None (fail-closed) — an empty profile file is never
written; the previous file is kept.
"""

import time

from .. import config
from ..profile import (Profile, load_profile, profile_path, raw_is_fresh,
                       save_profile, set_raw)
from .http import DC, SA, SEC
from .sa_parse import sa_flight_string

_A_META_MAP = {
    "ORG_NAME": "org_name", "CHAIRMAN": "chairman",
    "PRESIDENT": "president", "SECRETARY": "secretary",
    "FOUND_DATE": "founded", "LISTING_DATE": "listed",
    "ORG_WEB": "website", "ADDRESS": "address",
    "CONTROL_HOLDER": "control_holder",
    "REAL_CONTROLER": "real_controller",
    "INDEDIRECTORS": "independent_directors",
    "TOTAL_NUM": "employees", "EM2016": "industry",
    "ORG_FORM": "org_form", "MAXPROFIT_PRODUCT": "top_profit_product",
    "INCOME_STRU_NAME": "income_structure",
    "INCOME_STRU_RATIO": "income_structure_ratio",
    "ACCOUNT_FIRM": "auditor", "BLGAINIAN": "concepts",
}
_HK_META_MAP = {
    "ORG_NAME": "org_name", "ORG_EN_ABBR": "org_name_en",
    "CHAIRMAN": "chairman", "SECRETARY": "secretary",
    "FOUND_DATE": "founded", "LISTING_DATE": "listed",
    "ORG_WEB": "website", "ADDRESS": "address",
    "EMP_NUM": "employees", "BELONG_INDUSTRY": "industry",
    "ACCOUNT_FIRM": "auditor", "ORG_TYPE": "org_form",
}


def _a_secucode(code6: str) -> str:
    """600900 -> 600900.SH; 000858 -> 000858.SZ; 4/8xxxxx -> .BJ."""
    if code6.startswith("6"):
        return f"{code6}.SH"
    if code6.startswith(("4", "8")):
        return f"{code6}.BJ"
    return f"{code6}.SZ"


def fetch_profile_a(code6: str) -> dict | None:
    """A 股公司概况原文；源失败 None。"""
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.A_PROFILE_REPORT,
        "columns": "ALL",
        "filter": f'(SECUCODE="{_a_secucode(code6)}")',
        "pageNumber": 1, "pageSize": 1,
        "source": "F10", "client": "PC"})
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    r = rows[0]
    meta = {dst: str(r[src]).strip() for src, dst in _A_META_MAP.items()
            if r.get(src) not in (None, "")}
    # ORG_PROFIE (Eastmoney's typo'd column) carries the long 公司简介;
    # ORG_PROFILE is only a one-line slogan — prefer the long form.
    summary = str(r.get("ORG_PROFIE") or r.get("ORG_PROFILE") or ""
                  ).strip()
    return {"summary": summary,
            "main_business": str(r.get("MAIN_BUSINESS") or "").strip(),
            "vision": "",
            "meta": {**meta,
                     "business_scope": str(
                         r.get("BUSINESS_SCOPE") or "").strip()},
            "source": "eastmoney_f10_org_basicinfo",
            "source_url": config.DC_SEC_URL}


def fetch_profile_hk(code5: str) -> dict | None:
    """HK 公司概况原文（东财 HK F10，与 fetch_hk_lot 同报表）。"""
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_ORGPROFILE_REPORT,
        "columns": "ALL",
        "filter": f'(SECUCODE="{code5}.HK")',
        "pageNumber": 1, "pageSize": 1,
        "source": "F10", "client": "PC"})
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    r = rows[0]
    meta = {dst: str(r[src]).strip() for src, dst in _HK_META_MAP.items()
            if r.get(src) not in (None, "")}
    return {"summary": str(r.get("ORG_PROFILE") or "").strip(),
            "main_business": str(r.get("MAIN_BUSINESS") or "").strip(),
            "vision": "",
            "meta": meta,
            "source": "eastmoney_hk_f10_orgprofile",
            "source_url": config.DC_SEC_URL}


def _load_cik_map() -> dict:
    """US ticker (Eastmoney form) -> CIK; lazy wrapper for tests."""
    from .fundamentals import load_sec_cik_map
    return load_sec_cik_map() or {}


def fetch_profile_us(ticker: str) -> dict | None:
    """US 公司简介：stockanalysis description 正文 + SEC meta。正文
    缺失视为源失败（None）——meta 单独不构成商业模式素材。"""
    slug = ticker.lower().replace("_", "-")
    url = config.SA_PROFILE_URL_TMPL.format(slug=slug)
    html = SA.get_text(url)
    if html is None:
        return None
    summary = sa_flight_string(html, "description")
    if not summary:
        return None
    meta = {}
    cik = _load_cik_map().get(ticker)
    if cik:
        d = SEC.get_json(config.SEC_SUBMISSIONS_URL_TMPL.format(cik=cik))
        if d:
            meta = {
                "org_name": str(d.get("name") or ""),
                "sic": str(d.get("sic") or ""),
                "industry": str(d.get("sicDescription") or ""),
                "entity_type": str(d.get("entityType") or ""),
                "filer_category": str(d.get("category") or ""),
                "fiscal_year_end": str(d.get("fiscalYearEnd") or ""),
                "state_of_incorporation": str(
                    d.get("stateOfIncorporation") or ""),
                "cik": str(cik),
            }
            meta = {k: v for k, v in meta.items() if v}
    return {"summary": summary.strip(),
            "main_business": "", "vision": "",
            "meta": meta,
            "source": "stockanalysis+sec_submissions",
            "source_url": url}


FETCHERS = {"A": fetch_profile_a, "HK": fetch_profile_hk,
            "US": fetch_profile_us}


def update_profiles(symbols, force: bool = False,
                    quiet: bool = True) -> dict:
    """Incremental update for ``symbols`` = profile.pool_members()
    output [(market, code, name), ...].

    Per symbol: skip when raw is fresh (unless ``force``); fetch via
    the market's fetcher; None -> counted failed, old file untouched;
    content-unchanged -> fetched_at bump only (assessment stays valid).
    Returns counters {fetched, skipped_fresh, changed, failed, errors}.
    """
    stats = {"fetched": 0, "skipped_fresh": 0, "changed": 0,
             "failed": 0, "errors": []}
    for market, code, name in symbols:
        fetcher = FETCHERS.get(market)
        if fetcher is None:
            stats["failed"] += 1
            stats["errors"].append(f"{market}/{code}: unknown market")
            continue
        try:
            p = load_profile(market, code)
        except FileNotFoundError:
            p = Profile(id=f"{market}:{code}", market=market, code=code,
                        name=name)
        if not force and raw_is_fresh(p):
            stats["skipped_fresh"] += 1
            continue
        try:
            raw = fetcher(code)
        except Exception as exc:            # source hiccup: fail-closed
            stats["failed"] += 1
            stats["errors"].append(
                f"{market}/{code}: {type(exc).__name__}: {exc}")
            continue
        if raw is None:
            stats["failed"] += 1
            continue
        changed = set_raw(p, raw, name=name)
        save_profile(p)
        stats["fetched"] += 1
        if changed:
            stats["changed"] += 1
        if not quiet:
            tag = "changed" if changed else "fresh"
            print(f"  profile {market}/{code} {p.name}: {tag}")
        time.sleep(0.4)      # same inter-call budget as _dc.dc_report
    return stats
