"""Multi-year statement history, per stock, on demand (L3 modeling only).

- US: SEC companyconcept (multi-year XBRL), CIK via the existing ticker map
- A:  Eastmoney datacenter F10 statement reports (probe-finalized)
- HK: Eastmoney HKF10 main indicators (probe-finalized)

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
    return _fetch_history_a_probe(code)


def fetch_history_hk(code: str) -> dict | None:
    return _fetch_history_hk_probe(code)


# --- A-share: per-stock annual rows from the pipeline-proven reports -------
# 字段名由 data/probe_model_history.py 探针定稿 (2026-10-02, 600900 实测).
# 探针铁律: 日期单引号, 字符串双引号; 空窗口 (9201) 合法跳过.
A_INCOME_REPORT = "RPT_LICO_FN_CPD"          # 业绩报表 (config.A_REPORT_NAME)
A_CASHFLOW_REPORT = "RPT_DMSK_FN_CASHFLOW"
A_BALANCE_REPORT = "RPT_DMSK_FN_BALANCE"
A_INCOME_FIELDS = {"revenue": "TOTAL_OPERATE_INCOME",
                   "net_income": "PARENT_NETPROFIT"}
A_CASHFLOW_FIELDS = {"ocf": "NETCASH_OPERATE",
                     "capex": "CONSTRUCT_LONG_ASSET"}
A_BALANCE_FIELDS = {"cash": "MONETARYFUNDS", "debt": "TOTAL_LIABILITIES"}
# 各表日期过滤键不一致 (管线实测): LICO 用 REPORTDATE, DMSK 表用 REPORT_DATE.
_A_DATE_KEYS = {A_INCOME_REPORT: "REPORTDATE"}


def _a_report(report: str, secucode: str, rd: str) -> list | None:
    key = _A_DATE_KEYS.get(report, "REPORT_DATE")
    d = DC.get_json(config.DC_WEB_URL, params={
        "reportName": report, "columns": "ALL",
        "filter": f"({key}='{rd}')(SECUCODE=\"{secucode}\")",
        "pageNumber": 1, "pageSize": 5, "source": "WEB", "client": "WEB"})
    return ((d or {}).get("result") or {}).get("data") or None


def _fetch_history_a_probe(code: str) -> dict | None:
    from ..fetch.profiles import _a_secucode
    secucode = _a_secucode(code)
    this_year = date.today().year
    # 最近的候选年报期 (当年年报可能尚未披露, 9201 空窗口合法跳过)
    rds = [f"{y}-12-31" for y in range(this_year - 1,
                                       this_year - 1 - config.MODEL_HISTORY_YEARS - 1, -1)]
    by_fy: dict = {}
    name = ""
    for rd in rds:
        fy = int(rd[:4])
        inc = _a_report(A_INCOME_REPORT, secucode, rd)
        if not inc:
            continue
        row = inc[0]
        name = name or row.get("SECURITY_NAME_ABBR") or ""
        y = by_fy.setdefault(fy, {"fy": fy})
        for f, col in A_INCOME_FIELDS.items():
            y[f] = _num(row.get(col))
        cf = _a_report(A_CASHFLOW_REPORT, secucode, rd)
        if cf:
            for f, col in A_CASHFLOW_FIELDS.items():
                y[f] = _num(cf[0].get(col))
        bs = _a_report(A_BALANCE_REPORT, secucode, rd)
        if bs:
            for f, col in A_BALANCE_FIELDS.items():
                y[f] = _num(bs[0].get(col))
    if not by_fy:
        return None
    years = [by_fy[fy] for fy in sorted(by_fy)][-config.MODEL_HISTORY_YEARS:]
    gaps = ["a-share income report has no ebit field; "
            "statements carry no da/shares — set assumptions.shares "
            "manually (F10 股本) before trusting per-share output"]
    return store.new_history("A", code, name=name,
                             source="eastmoney_datacenter_f10",
                             currency="CNY", years=years, gaps=gaps)


# --- HK: HKF10 main indicators, per stock, desc by REPORT_DATE -------------
# 字段名探针定稿 (2026-10-02, 00998 实测, 年报/中报混合返回, 只留 12-31).
HK_MAIN_FIELDS = {"revenue": "OPERATE_INCOME",
                  "ebit": "OPERATE_PROFIT",
                  "net_income": "HOLDER_PROFIT",
                  "ocf": "NETCASH_OPERATE",
                  "cash": "END_CASH",
                  "debt": "TOTAL_LIABILITIES"}


def _hk_main(secucode: str) -> list | None:
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_REPORT_NAME, "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 30, "sortTypes": "-1",
        "sortColumns": "REPORT_DATE", "source": "F10", "client": "PC"})
    return ((d or {}).get("result") or {}).get("data") or None


def _fetch_history_hk_probe(code: str) -> dict | None:
    secucode = code if "." in code else f"{code}.HK"
    rows = _hk_main(secucode)
    if not rows:
        return None
    annual = {}
    name = ""
    for r in rows:
        rd = str(r.get("REPORT_DATE") or "")[:10]
        if not rd.endswith("12-31"):
            continue
        fy = int(rd[:4])
        name = name or r.get("SECURITY_NAME_ABBR") or ""
        y = annual.setdefault(fy, {"fy": fy})
        for f, col in HK_MAIN_FIELDS.items():
            v = _num(r.get(col))
            if v is not None or f not in y:
                y[f] = v
    if not annual:
        return None
    years = [annual[fy] for fy in sorted(annual)][-config.MODEL_HISTORY_YEARS:]
    gaps = ["hk main indicators lack da/capex — engine falls back to "
            "ratios; ISSUED_COMMON_SHARES is a snapshot constant, not "
            "as-of-period, so set assumptions.shares manually",
            "amounts are reporting-currency (CNY for mainland reporters); "
            "the CURRENCY field tags the listing currency, not the amounts"]
    return store.new_history("HK", code, name=name,
                             source="eastmoney_hkf10_mainindicator",
                             currency="CNY", years=years, gaps=gaps)


def fetch_history(market: str, code: str) -> dict | None:
    """Dispatch by market; None on source failure (fail-closed)."""
    fn = {"A": fetch_history_a, "HK": fetch_history_hk,
          "US": fetch_history_us}.get(market)
    return fn(code) if fn else None
