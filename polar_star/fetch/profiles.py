"""Profile raw fetchers: on-demand single stock + full-market bulk.

Single-stock path serves the L3 deep-review shortlist; the bulk path
(user mandate 2026-10-18, full-market profile campaign) fetches every
quoted name ahead of the AI distillation frontier.

Sources (probe-finalized 2026-09-29, data/probe_profiles.py):

- A:  datacenter ``RPT_F10_ORG_BASICINFO`` — long summary in
  ``ORG_PROFIE`` (sic), one-line vision in ``ORG_PROFILE``.
- HK: datacenter ``RPT_HKF10_INFO_ORGPROFILE`` — long summary in
  ``ORG_PROFILE`` (different column than A!).
- US: SEC submissions meta + stockanalysis profile ``description``
  from the embedded flight-data blob.

Bulk fast path: the A/HK datacenter reports also answer WITHOUT a
secucode filter (pageSize 500, paged), so a whole market costs a dozen
requests instead of thousands; names missing from the paged pass fall
back to the single-stock path. US stays per-stock (SEC submissions is
per-CIK by design; the SEC client's semaphore=1 keeps EDGAR polite).

All network entry points are module-level (monkeypatch boundary);
a source failure returns None (fail-closed) and never clobbers an
existing raw file.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import config
from ..profile import new_raw, save_raw
from .http import DC, SA, SEC

BULK_PAGE_SIZE = 500


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
def _a_raw_from_row(r: dict, code: str) -> dict:
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


def fetch_profile_a(code: str) -> dict | None:
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.A_ORG_BASICINFO_REPORT, "columns": "ALL",
        "filter": f'(SECUCODE="{_a_secucode(code)}")',
        "pageNumber": 1, "pageSize": 1, "source": "F10", "client": "PC"})
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    return _a_raw_from_row(rows[0], code)


def _paged_rows(report: str) -> "list | None":
    """Bulk fast path: page the whole datacenter report without a
    secucode filter. Returns the row list, or None when the report
    refuses an unfiltered query (caller falls back to per-stock)."""
    rows, page, pages = [], 1, None
    while True:
        d = DC.get_json(config.DC_SEC_URL, params={
            "reportName": report, "columns": "ALL",
            "pageNumber": page, "pageSize": BULK_PAGE_SIZE,
            "source": "F10", "client": "PC"}, timeout=30)
        result = (d or {}).get("result") or {}
        batch = result.get("data") or []
        if page == 1 and not batch:
            return None
        rows.extend(batch)
        if pages is None:
            try:
                pages = int(result.get("pages") or 0) or None
            except (TypeError, ValueError):
                pages = None
        page += 1
        if not batch or len(batch) < BULK_PAGE_SIZE:
            break
        if pages and page > pages:
            break
    return rows


def _bulk_code(secucode: str) -> str:
    """'600900.SH' -> '600900' (bulk rows carry the suffixed secucode)."""
    return _txt(secucode).split(".")[0]


def _fetch_all_a(codes: set) -> tuple:
    """Returns (raws, missed): raws saved from the paged pass, missed =
    target codes the bulk report did not cover (per-stock fallback)."""
    raws = []
    rows = _paged_rows(config.A_ORG_BASICINFO_REPORT)
    if rows is None:
        return raws, set(codes)
    seen = set()
    for r in rows:
        code = _bulk_code(r.get("SECUCODE"))
        if not code or code in seen:
            continue
        seen.add(code)
        raws.append(_a_raw_from_row(r, code))
    return raws, set(codes) - seen


# ---------------------------------------------------------------------------
# HK: Eastmoney HK F10 org profile
# ---------------------------------------------------------------------------
def _hk_raw_from_row(r: dict, code5: str) -> dict:
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


def fetch_profile_hk(code5: str) -> dict | None:
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_ORGPROFILE_REPORT, "columns": "ALL",
        "filter": f'(SECUCODE="{code5}.HK")',
        "pageNumber": 1, "pageSize": 1, "source": "F10", "client": "PC"})
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    return _hk_raw_from_row(rows[0], code5)


def _fetch_all_hk(codes: set) -> tuple:
    raws = []
    rows = _paged_rows(config.HK_ORGPROFILE_REPORT)
    if rows is None:
        return raws, set(codes)
    seen = set()
    for r in rows:
        code = _bulk_code(r.get("SECUCODE")).zfill(5)
        if not code.strip("0") or code in seen:
            continue
        seen.add(code)
        raws.append(_hk_raw_from_row(r, code))
    return raws, set(codes) - seen


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


# ---------------------------------------------------------------------------
# Full-market bulk (user mandate 2026-10-18: profile campaign machine side)
# ---------------------------------------------------------------------------
def _universe(markets: tuple) -> dict:
    """{market: [codes]} — every quoted name, via the modeling campaign's
    market_targets (same full-market answer, no fork)."""
    from ..model.campaign import market_targets
    from ..report import resolve_snapshot
    snap_dir = resolve_snapshot(None)
    targets, _gaps = market_targets(snap_dir, set())
    out = {m: [] for m in markets}
    for t in targets:
        if t["market"] in out:
            out[t["market"]].append(t["code"])
    return out


def _per_stock_fallback(market: str, codes: list,
                        on_progress=None) -> tuple:
    """Thread-pooled single-stock path (the DC/SEC/SA semaphores bound
    per-host concurrency). Returns (saved_ids, failed_ids)."""
    fn = FETCHERS[market]
    saved, failed = [], []
    workers = config.FETCH_WORKERS.get("default", 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, code): code for code in codes}
        done = 0
        for fut in as_completed(futs):
            code = futs[fut]
            done += 1
            try:
                raw = fut.result()
            except Exception:  # noqa: BLE001 — one miss never sinks the run
                raw = None
            if raw is None:
                failed.append(code)
            else:
                save_raw(raw)
                saved.append(raw["id"])
            if on_progress and done % 50 == 0:
                on_progress(market, done, len(codes))
    return saved, failed


def fetch_all(markets=("A", "HK", "US"), targets: "dict | None" = None,
              force: bool = False, on_progress=None) -> dict:
    """Bulk-fetch raw profiles for every target code.

    ``targets``: optional {market: [codes]}; defaults to the full quoted
    universe. Existing raws are skipped unless ``force``. A/HK try the
    paged bulk fast path first, then per-stock fallback for misses; US
    is per-stock throughout. Fail-closed per stock — a failed fetch
    never clobbers an existing raw. Returns per-market tallies.
    """
    from ..profile import raw_path
    if targets is None:
        targets = _universe(tuple(markets))
    report = {}
    for market in markets:
        codes = list(targets.get(market) or [])
        if not force:
            todo = [c for c in codes if not raw_path(market, c).exists()]
        else:
            todo = codes
        skipped = len(codes) - len(todo)
        saved, failed = [], []
        todo_set = set(todo)
        if todo:
            if market in ("A", "HK"):
                bulk = (_fetch_all_a if market == "A"
                        else _fetch_all_hk)(todo_set)
                raws, missed = bulk
                for raw in raws:
                    if force or raw["code"] in todo_set:
                        save_raw(raw)
                        saved.append(raw["id"])
                if missed:
                    s, f = _per_stock_fallback(market, sorted(missed),
                                               on_progress)
                    saved += s
                    failed += f
            else:
                s, f = _per_stock_fallback(market, todo, on_progress)
                saved += s
                failed += f
        report[market] = {"targets": len(codes), "skipped": skipped,
                          "saved": len(saved), "failed": len(failed),
                          "failed_ids": failed[:50]}
    return report
