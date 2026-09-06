"""Fundamentals fetching: A-share batch reports, US SEC frames, HK F10, FX.

A-shares use the Eastmoney datacenter performance report (paged, full
market). US stocks use SEC EDGAR XBRL frames (one request per concept gives
the whole market). HK stocks use the per-stock F10 main-indicator report
(deep pass only, for funnel candidates).
"""

import time
from datetime import date

import pandas as pd

from .. import config
from .http import DC, SEC, em_push2_get, num


# ---------------------------------------------------------------------------
# A-share batch financials (业绩报表)
# ---------------------------------------------------------------------------
A_FIELD_MAP = {
    "SECURITY_CODE": "code",
    "REPORTDATE": "report_date",
    "TOTAL_OPERATE_INCOME": "revenue",
    "YSTZ": "rev_yoy",
    "PARENT_NETPROFIT": "profit",
    "SJLTZ": "profit_yoy",
    "WEIGHTAVG_ROE": "roe",
    "XSMLL": "gross_margin",
    "BPS": "bps",
}


def candidate_report_dates(today: date | None = None, lookback: int = 4) -> list:
    """Recent quarter-end dates, newest first (reporting basis)."""
    today = today or date.today()
    ends = []
    y = today.year
    for yy in (y, y - 1):
        ends += [date(yy, 12, 31), date(yy, 9, 30),
                 date(yy, 6, 30), date(yy, 3, 31)]
    return sorted((d for d in ends if d < today), reverse=True)[:lookback]


def _fetch_lico_page(report_date: str, page: int) -> dict:
    """One page of the A-share performance report for a report date."""
    return DC.get_json(config.DC_WEB_URL, params={
        "reportName": config.A_REPORT_NAME,
        "columns": "ALL",
        "filter": f"(REPORTDATE='{report_date}')",
        "pageNumber": page,
        "pageSize": config.A_PAGE_SIZE,
        "sortTypes": "1",
        "sortColumns": "SECURITY_CODE",
        "source": "WEB",
        "client": "WEB",
    }, retries=3) or {}


def _parse_lico(d: dict) -> pd.DataFrame:
    rows = ((d.get("result") or {}).get("data")) or []
    if not rows:
        return pd.DataFrame(columns=list(A_FIELD_MAP.values()))
    df = pd.DataFrame(rows)
    keep = [c for c in A_FIELD_MAP if c in df.columns]
    df = df[keep].rename(columns=A_FIELD_MAP)
    for col in ("revenue", "rev_yoy", "profit", "profit_yoy", "roe",
                "gross_margin", "bps"):
        if col in df.columns:
            df[col] = df[col].map(num)
    df["report_date"] = df["report_date"].astype(str).str.slice(0, 10)
    return df


def merge_a_periods(latest: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    """Merge two report periods: rows from `latest` win; codes only present
    in `prev` are appended (late filers keep their previous-period metrics).
    """
    if latest.empty:
        return prev
    if prev.empty:
        return latest
    extra = prev[~prev["code"].isin(set(latest["code"]))]
    return pd.concat([latest, extra], ignore_index=True)


def fetch_a_financials(quiet: bool = False) -> pd.DataFrame:
    """Fetch full-market A-share financials for the latest report period
    (plus the previous period as a backfill for late filers).
    """
    dates = candidate_report_dates()
    latest_df = prev_df = pd.DataFrame()
    chosen = None
    for i, rd in enumerate(dates):
        d = _fetch_lico_page(rd.isoformat(), 1)
        total = ((d.get("result") or {}).get("count")) or 0
        if not quiet:
            print(f"    [A] report {rd}: {total} rows")
        if total >= config.A_MIN_REPORT_ROWS:
            chosen = rd
            pages = []
            for pn in range(1, total // config.A_PAGE_SIZE + 2):
                pages.append(_parse_lico(_fetch_lico_page(rd.isoformat(), pn)))
                time.sleep(0.4)
            latest_df = pd.concat(pages, ignore_index=True)
            # backfill from the previous quarter for late filers
            if i + 1 < len(dates):
                prd = dates[i + 1]
                d2 = _fetch_lico_page(prd.isoformat(), 1)
                t2 = ((d2.get("result") or {}).get("count")) or 0
                if t2:
                    pages2 = []
                    for pn in range(1, t2 // config.A_PAGE_SIZE + 2):
                        pages2.append(_parse_lico(
                            _fetch_lico_page(prd.isoformat(), pn)))
                        time.sleep(0.4)
                    prev_df = pd.concat(pages2, ignore_index=True)
            break
    if chosen is None:
        print("    [A] WARN: no report period found with enough rows")
        return pd.DataFrame(columns=list(A_FIELD_MAP.values()))
    df = merge_a_periods(latest_df, prev_df)
    if not quiet:
        print(f"    [A] financials: {len(df)} stocks "
              f"(period {chosen}, backfill {len(prev_df)})")
    return df


# ---------------------------------------------------------------------------
# A-share batch cash flow (现金流量表)
# ---------------------------------------------------------------------------
A_CASHFLOW_MAP = {
    "SECURITY_CODE": "code",
    "REPORT_DATE": "report_date",
    "NETCASH_OPERATE": "ocf",
    "CONSTRUCT_LONG_ASSET": "capex",
    "NETCASH_FINANCE": "net_fin_cf",
}


def _fetch_cashflow_page(report_date: str, page: int) -> dict:
    """One page of the A-share cash flow report for a report date."""
    return DC.get_json(config.DC_WEB_URL, params={
        "reportName": config.A_CASHFLOW_REPORT_NAME,
        "columns": "ALL",
        "filter": f"(REPORT_DATE='{report_date}')",
        "pageNumber": page,
        "pageSize": config.A_PAGE_SIZE,
        "sortTypes": "1",
        "sortColumns": "SECURITY_CODE",
        "source": "WEB",
        "client": "WEB",
    }, retries=3) or {}


def _parse_cashflow(d: dict) -> pd.DataFrame:
    rows = ((d.get("result") or {}).get("data")) or []
    cols = list(A_CASHFLOW_MAP.values())
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    keep = [c for c in A_CASHFLOW_MAP if c in df.columns]
    df = df[keep].rename(columns=A_CASHFLOW_MAP)
    for c in ("ocf", "capex", "net_fin_cf"):
        if c in df.columns:
            df[c] = df[c].map(num)
    df["report_date"] = (df["report_date"].astype(str).str.slice(0, 10)
                         if "report_date" in df.columns else "")
    return df.drop_duplicates(subset="code", keep="first")


def fetch_a_cashflow(quiet: bool = False) -> pd.DataFrame:
    """Full-market A-share operating cash flow (NETCASH_OPERATE) for the
    latest report period, with previous-period backfill for late filers.
    """
    dates = candidate_report_dates()
    out = pd.DataFrame(columns=list(A_CASHFLOW_MAP.values()))
    chosen = None
    for i, rd in enumerate(dates):
        d = _fetch_cashflow_page(rd.isoformat(), 1)
        total = ((d.get("result") or {}).get("count")) or 0
        if not quiet:
            print(f"    [A] cashflow {rd}: {total} rows")
        if total >= config.A_MIN_REPORT_ROWS:
            chosen = rd
            latest = pd.DataFrame()
            for pn in range(1, total // config.A_PAGE_SIZE + 2):
                page_df = _parse_cashflow(
                    _fetch_cashflow_page(rd.isoformat(), pn))
                if not page_df.empty:
                    latest = pd.concat([latest, page_df], ignore_index=True)
                time.sleep(0.4)
            prev = pd.DataFrame()
            if i + 1 < len(dates):
                prd = dates[i + 1]
                d2 = _fetch_cashflow_page(prd.isoformat(), 1)
                t2 = ((d2.get("result") or {}).get("count")) or 0
                if t2:
                    for pn in range(1, t2 // config.A_PAGE_SIZE + 2):
                        page_df = _parse_cashflow(
                            _fetch_cashflow_page(prd.isoformat(), pn))
                        if not page_df.empty:
                            prev = pd.concat([prev, page_df],
                                             ignore_index=True)
                        time.sleep(0.4)
            out = merge_a_periods(latest, prev)
            if not quiet:
                print(f"    [A] cashflow: {len(out)} stocks "
                      f"(period {chosen}, backfill {len(prev)})")
            break
    if chosen is None and not quiet:
        print("    [A] WARN: no cashflow period found with enough rows")
    return out


def annual_report_dates(today: date | None = None, lookback: int = 2) -> list:
    """Recent 12-31 report dates, newest first (annual-reporting basis)."""
    today = today or date.today()
    y = today.year
    ends = [date(yy, 12, 31) for yy in (y - 1, y - 2, y - 3)]
    return sorted((d for d in ends if d < today), reverse=True)[:lookback]


def fetch_a_cashflow_annual(quiet: bool = False) -> pd.DataFrame:
    """Full-market A-share ANNUAL cash flow (12-31 report dates).

    Annual basis is the denominator contract for fcf_yield /
    borrowed_dividend: interim (6-month) figures understate the
    run-rate ~2x mid-season. Latest annual period with mass filings,
    previous annual as late-filer backfill.
    """
    dates = annual_report_dates()
    out = pd.DataFrame(columns=list(A_CASHFLOW_MAP.values()))
    chosen = None
    for i, rd in enumerate(dates):
        d = _fetch_cashflow_page(rd.isoformat(), 1)
        total = ((d.get("result") or {}).get("count")) or 0
        if not quiet:
            print(f"    [A] annual cashflow {rd}: {total} rows")
        if total >= config.A_MIN_REPORT_ROWS:
            chosen = rd
            latest = pd.DataFrame()
            for pn in range(1, total // config.A_PAGE_SIZE + 2):
                page_df = _parse_cashflow(
                    _fetch_cashflow_page(rd.isoformat(), pn))
                if not page_df.empty:
                    latest = pd.concat([latest, page_df], ignore_index=True)
                time.sleep(0.4)
            prev = pd.DataFrame()
            if i + 1 < len(dates):
                prd = dates[i + 1]
                d2 = _fetch_cashflow_page(prd.isoformat(), 1)
                t2 = ((d2.get("result") or {}).get("count")) or 0
                if t2:
                    for pn in range(1, t2 // config.A_PAGE_SIZE + 2):
                        page_df = _parse_cashflow(
                            _fetch_cashflow_page(prd.isoformat(), pn))
                        if not page_df.empty:
                            prev = pd.concat([prev, page_df],
                                             ignore_index=True)
                        time.sleep(0.4)
            out = merge_a_periods(latest, prev)
            if not quiet:
                print(f"    [A] annual cashflow: {len(out)} stocks "
                      f"(period {chosen})")
            break
    if chosen is None and not quiet:
        print("    [A] WARN: no annual cashflow period found")
    return out


# ---------------------------------------------------------------------------
# US batch financials (SEC EDGAR frames)
# ---------------------------------------------------------------------------
def frames_year_context(today: date | None = None) -> dict:
    """Compute frame period keys relative to today.

    cy/cy_prev: latest complete calendar years (a year is complete once its
    10-Ks are due, ~mid-April of the following year).
    q/q_prev: latest quarter with filings in (quarter end + ~50 days).
    """
    today = today or date.today()
    cy = today.year - 1
    if today.month > 4:
        cy = today.year - 1  # last year's 10-Ks are in by Apr 30
    cy_prev = cy - 1
    quarters = []
    for yy in (today.year, today.year - 1):
        quarters += [date(yy, 12, 31), date(yy, 9, 30),
                     date(yy, 6, 30), date(yy, 3, 31)]
    quarters = sorted(q for q in quarters if (today - q).days >= 50)
    q_end = quarters[-1]
    q_prev_end = date(q_end.year - 1, q_end.month, q_end.day)
    return {
        "cy": cy, "cy_prev": cy_prev,
        "q": f"{q_end.year}Q{(q_end.month - 1) // 3 + 1}",
        "q_prev": f"{q_prev_end.year}Q{(q_prev_end.month - 1) // 3 + 1}",
    }


def frame_name(kind: str, period_key: str, ctx: dict) -> str:
    """Build the SEC frames identifier for a concept kind and period key."""
    if kind == "instant":
        year = ctx[period_key]
        return f"CY{year}Q4I"
    mapping = {"cy": f"CY{ctx['cy']}", "cy_prev": f"CY{ctx['cy_prev']}",
               "q": f"CY{ctx['q']}", "q_prev": f"CY{ctx['q_prev']}"}
    return mapping[period_key]


def parse_frame(d: dict) -> dict:
    """frames JSON -> {cik: value}."""
    out = {}
    for e in (d or {}).get("data") or []:
        cik = e.get("cik")
        val = num(e.get("val"))
        if cik is None or val is None:
            continue
        out[int(cik)] = val
    return out


def normalize_us_ticker(ticker: str) -> str:
    """SEC ticker form -> Eastmoney code form.

    SEC's ticker file writes class shares as ``BRK-A`` / ``BRK.B`` while
    Eastmoney quote codes use ``BRK_B`` — normalize to underscores so
    frames data joins quotes for every share class.
    """
    return str(ticker).upper().replace("-", "_").replace(".", "_")


def load_sec_cik_map() -> dict:
    """normalized ticker -> cik from SEC's official ticker file.

    Class shares (BRK-A/BRK-B -> one cik) each keep their own entry, so
    every traded class can find its registrant's financials.
    """
    d = SEC.get_json(config.SEC_TICKERS_URL, timeout=30)
    if not d:
        return {}
    return {normalize_us_ticker(v["ticker"]): int(v["cik_str"])
            for v in d.values()}


def sum_oneoff_frames(frames: dict, key: str, concepts) -> dict:
    """{cik: total one-off disposal gain/loss} summed across concepts.

    A filer reports a given disposal under at most one of the one-off
    concepts, so summing is a guard against tag-choice differences.
    """
    total = {}
    for concept in concepts:
        for cik, val in (frames.get((concept, key)) or {}).items():
            total[cik] = total.get(cik, 0.0) + val
    return total


def derive_us_metrics(rec: dict) -> dict:
    """Derive growth/quality metrics from raw frame values (all USD).

    Profit-based metrics use a RECURRING basis: pre-tax one-off disposal
    gains/losses (rec["oneoff"] / rec["oneoff_prev"]) are stripped from
    net income first, so a bottom line inflated by asset sales (WTM's
    Bamboo disposal, Boyd's FanDuel stake sale) no longer boosts
    profit_yoy / net_margin / roe. One-offs are pre-tax while net income
    is after-tax, so affected names are scored conservatively.

    Gross margin falls back to (rev - cost_of_revenue) / rev when the
    filer does not tag GrossProfit for the period (PDD stopped after
    CY2022 but keeps tagging CostOfRevenue).
    """
    rev, rev_p = rec.get("rev"), rec.get("rev_prev")
    ni, ni_p = rec.get("profit"), rec.get("profit_prev")
    oneoff, oneoff_p = rec.get("oneoff"), rec.get("oneoff_prev")
    if ni is not None and oneoff is not None:
        ni = ni - oneoff
    if ni_p is not None and oneoff_p is not None:
        ni_p = ni_p - oneoff_p
    q, q_p = rec.get("rev_q"), rec.get("rev_q_prev")
    out = {}
    if rev and rev_p:
        out["rev_yoy"] = (rev - rev_p) / abs(rev_p) * 100.0
    if ni is not None and ni_p:
        out["profit_yoy"] = (ni - ni_p) / abs(ni_p) * 100.0
    if q is not None and q_p:
        out["rev_q_yoy"] = (q - q_p) / abs(q_p) * 100.0
    if rev:
        if ni is not None:
            out["net_margin"] = ni / rev * 100.0
        gp = rec.get("gross_profit")
        if gp is None and rec.get("cost") is not None:
            gp = rev - rec["cost"]
        if gp is not None:
            out["gross_margin"] = gp / rev * 100.0
        out["ps_revenue"] = rev  # denominator for price-to-sales
    eq, eq_p = rec.get("equity"), rec.get("equity_prev")
    if ni is not None and eq and eq_p:
        out["roe"] = ni / ((eq + eq_p) / 2) * 100.0
    liab, assets = rec.get("liabilities"), rec.get("assets")
    if liab is not None and assets:
        out["debt_ratio"] = liab / assets * 100.0
    ocf_val = rec.get("ocf")
    if ocf_val is not None and ni is not None and ni != 0:
        out["cash_conversion"] = ocf_val / ni * 100.0
    return out


def fetch_a_financials_one(code: str) -> pd.DataFrame:
    """Per-stock A-share financials fallback (same report, same schema as
    the batch fetch) for held names missing from the batch file — e.g.
    very recent IPOs that filed after the batch page was pulled."""
    d = DC.get_json(config.DC_WEB_URL, params={
        "reportName": config.A_REPORT_NAME,
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": 1,
        "pageSize": 2,
        "sortTypes": "-1",
        "sortColumns": "REPORTDATE",
        "source": "WEB",
        "client": "WEB",
    }, retries=2) or {}
    return _parse_lico(d)


def fetch_us_financials(quiet: bool = False) -> pd.DataFrame:
    """Fetch market-wide US fundamentals from SEC EDGAR frames.

    Returns a DataFrame indexed by ticker with rev/profit levels, YoY growth,
    margins, ROE and leverage where available.
    """
    ctx = frames_year_context()
    if not quiet:
        print(f"    [US] frames context: {ctx}")

    # concept+period -> {cik: val}
    frames = {}
    for concept, kind, keys in config.US_FRAMES_SPEC:
        for key in keys:
            fname = frame_name(kind, key, ctx)
            url = config.SEC_FRAMES_URL.format(concept=concept, unit="USD",
                                               frame=fname)
            d = SEC.get_json(url, timeout=60, retries=2)
            frames[(concept, key)] = parse_frame(d)
            time.sleep(0.3)
            if not quiet:
                print(f"    [US] frame {concept}/{fname}: "
                      f"{len(frames[(concept, key)])} entities")

    cik_map = load_sec_cik_map()
    # one cik may trade under several normalized tickers (BRK_A / BRK_B)
    cik_to_tickers: dict = {}
    for t, c in cik_map.items():
        cik_to_tickers.setdefault(c, []).append(t)

    def pref(primary, secondary):
        merged = dict(secondary or {})
        merged.update(primary or {})
        return merged

    rev = pref(frames[("RevenueFromContractWithCustomerExcludingAssessedTax",
                       "cy")],
               frames[("Revenues", "cy")])
    rev_p = pref(frames[("RevenueFromContractWithCustomerExcludingAssessedTax",
                         "cy_prev")],
                 frames[("Revenues", "cy_prev")])
    rev_q = frames[("RevenueFromContractWithCustomerExcludingAssessedTax", "q")]
    rev_q_p = frames[("RevenueFromContractWithCustomerExcludingAssessedTax",
                      "q_prev")]
    ni = frames[("NetIncomeLoss", "cy")]
    ni_p = frames[("NetIncomeLoss", "cy_prev")]
    gp = frames[("GrossProfit", "cy")]
    cost = pref(frames.get(("CostOfRevenue", "cy")),
                frames.get(("CostOfGoodsAndServicesSold", "cy")))
    eq = frames[("StockholdersEquity", "cy")]
    eq_p = frames[("StockholdersEquity", "cy_prev")]
    liab = frames[("Liabilities", "cy")]
    assets = frames[("Assets", "cy")]
    ocf = frames.get(("NetCashProvidedByUsedInOperatingActivities", "cy")) or {}

    oneoff = sum_oneoff_frames(frames, "cy", config.US_ONEOFF_CONCEPTS)
    oneoff_p = sum_oneoff_frames(frames, "cy_prev",
                                 config.US_ONEOFF_CONCEPTS)

    rows = []
    for cik in set(rev) | set(ni):
        tickers = cik_to_tickers.get(cik)
        if not tickers:
            continue
        rec = {"rev": rev.get(cik), "rev_prev": rev_p.get(cik),
               "rev_q": rev_q.get(cik), "rev_q_prev": rev_q_p.get(cik),
               "profit": ni.get(cik), "profit_prev": ni_p.get(cik),
               "gross_profit": gp.get(cik), "cost": cost.get(cik),
               "equity": eq.get(cik), "equity_prev": eq_p.get(cik),
               "liabilities": liab.get(cik), "assets": assets.get(cik),
               "oneoff": oneoff.get(cik), "oneoff_prev": oneoff_p.get(cik),
               "ocf": ocf.get(cik)}
        rec.update(derive_us_metrics(rec))
        for ticker in tickers:
            row = dict(rec)
            row["ticker"] = ticker
            rows.append(row)
    df = pd.DataFrame(rows)
    if not quiet:
        print(f"    [US] financials: {len(df)} tickers")
    return df


# ---------------------------------------------------------------------------
# US per-stock fallback (SEC companyconcept) — redundancy for held names
# the market-wide frames file misses entirely
# ---------------------------------------------------------------------------
def _concept_facts(d: dict) -> list:
    return ((d or {}).get("units") or {}).get("USD") or []


def _pick_fact(facts: list, frame: str, start: str = "",
               end: str = ""):
    """Fact dict for a target frame; falls back to period dates.

    ``frame`` matches the XBRL frame tag (CY2025, CY2025Q4I...); when no
    fact carries it (some filings never enter the frames aggregation),
    duration facts are matched by (start, end) and instant facts by end.
    """
    for e in facts:
        if e.get("frame") == frame:
            return e
    if start and end:
        for e in facts:
            if e.get("start") == start and e.get("end") == end:
                return e
    if end and not start:
        cands = [e for e in facts if e.get("end") == end]
        if cands:
            return cands[-1]
    return None


def fetch_us_financials_one(ticker: str, quiet: bool = False) -> dict | None:
    """Per-ticker US fundamentals via SEC companyconcept (all periods of
    one concept for one registrant). Used when the frames file has no row
    for a held ticker. Returns a rec in fetch_us_financials row form
    (without ``ticker`` key) or None when nothing resolves."""
    cik = load_sec_cik_map().get(normalize_us_ticker(ticker))
    if not cik:
        return None
    ctx = frames_year_context()
    cy, cy_prev = ctx["cy"], ctx["cy_prev"]

    def concept_val(concept: str, frame: str, start: str = "",
                    end: str = ""):
        url = config.SEC_CONCEPT_URL.format(cik=cik, concept=concept)
        d = SEC.get_json(url, timeout=30, retries=1)
        fact = _pick_fact(_concept_facts(d), frame, start, end)
        return num(fact.get("val")) if fact else None

    def dur(year):
        return (f"{year}-01-01", f"{year}-12-31")

    s, e = dur(cy)
    sp, ep = dur(cy_prev)
    rev = concept_val("RevenueFromContractWithCustomerExcludingAssessedTax",
                      f"CY{cy}", s, e)
    if rev is None:
        rev = concept_val("Revenues", f"CY{cy}", s, e)
    rev_p = concept_val(
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        f"CY{cy_prev}", sp, ep)
    if rev_p is None:
        rev_p = concept_val("Revenues", f"CY{cy_prev}", sp, ep)
    rec = {
        "rev": rev, "rev_prev": rev_p,
        "profit": concept_val("NetIncomeLoss", f"CY{cy}", s, e),
        "profit_prev": concept_val("NetIncomeLoss", f"CY{cy_prev}", sp, ep),
        "gross_profit": concept_val("GrossProfit", f"CY{cy}", s, e),
        "cost": concept_val("CostOfRevenue", f"CY{cy}", s, e),
        "equity": concept_val("StockholdersEquity", f"CY{cy}Q4I", end=e),
        "equity_prev": concept_val("StockholdersEquity", f"CY{cy_prev}Q4I",
                                   end=ep),
        "liabilities": concept_val("Liabilities", f"CY{cy}Q4I", end=e),
        "assets": concept_val("Assets", f"CY{cy}Q4I", end=e),
        "ocf": concept_val("NetCashProvidedByUsedInOperatingActivities",
                           f"CY{cy}", s, e),
    }
    if rec["rev"] is None and rec["profit"] is None:
        return None
    rec.update(derive_us_metrics(rec))
    if not quiet:
        print(f"    [US] companyconcept fallback {ticker}: "
              f"rev={rec.get('rev')}")
    return rec


# ---------------------------------------------------------------------------
# HK F10 (deep pass)
# ---------------------------------------------------------------------------
HK_F10_MAP = {
    "SECUCODE": "secucode",
    "REPORT_DATE": "report_date",
    "REPORT_TYPE": "report_type",
    "OPERATE_INCOME": "revenue",
    "OPERATE_INCOME_YOY": "rev_yoy",
    "HOLDER_PROFIT": "profit",
    "HOLDER_PROFIT_YOY": "profit_yoy",
    "GROSS_PROFIT_RATIO": "gross_margin",
    "NET_PROFIT_RATIO": "net_margin",
    "ROE_AVG": "roe",
    "DEBT_ASSET_RATIO": "debt_ratio",
    "DPS_HKD": "dps_hkd",
    "DIVIDEND_RATE": "dividend_yield",
    "NETCASH_OPERATE": "ocf",
}


def fetch_hk_f10(code5: str) -> pd.DataFrame | None:
    """Latest 12 report periods of HK F10 main indicators (CNY amounts)."""
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_REPORT_NAME,
        "columns": "ALL",
        "filter": f'(SECUCODE="{code5}.HK")',
        "pageNumber": 1,
        "pageSize": 12,
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "F10",
        "client": "PC",
    })
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df = df[[c for c in HK_F10_MAP if c in df.columns]].rename(
        columns=HK_F10_MAP)
    for col in ("revenue", "rev_yoy", "profit", "profit_yoy", "gross_margin",
                "net_margin", "roe", "debt_ratio", "dps_hkd", "dividend_yield"):
        if col in df.columns:
            df[col] = df[col].map(num)
    df["report_date"] = df["report_date"].astype(str).str.slice(0, 10)
    df.insert(0, "code", code5)
    return df


def fetch_hk_lot(code5: str) -> int | None:
    """Board lot size (TRADE_UNIT) for one HK stock; None on failure."""
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": config.HK_ORGPROFILE_REPORT,
        "columns": "ALL",
        "filter": f'(SECUCODE="{code5}.HK")',
        "pageNumber": 1,
        "pageSize": 1,
        "source": "F10",
        "client": "PC",
    })
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    try:
        return int(rows[0].get("TRADE_UNIT") or 0) or None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------
def fetch_fx_hkdcny() -> float:
    """HKD/CNY rate via Eastmoney ulist; ~0.92 fallback."""
    d = em_push2_get("/api/qt/ulist.np/get", params={
        "secids": "133.HKDCNH,133.HKDCNY",
        "fields": "f2,f12,f13", "ut": config.EM_UT_QUOTE,
        "fltt": 2, "invt": 2, "pn": 1, "np": 1,
    })
    for r in ((d or {}).get("data") or {}).get("diff") or []:
        p = num(r.get("f2"))
        if p and 0.5 < p < 2.0:
            return p
    print("    [FX] HKD/CNY not fetched, using fallback 0.92")
    return 0.92


def fetch_fx_usdcny() -> float:
    """USD/CNY rate via Eastmoney ulist (USDCNH spot); ~7.2 fallback."""
    d = em_push2_get("/api/qt/ulist.np/get", params={
        "secids": "133.USDCNH,119.USDCNY",
        "fields": "f2,f12,f13", "ut": config.EM_UT_QUOTE,
        "fltt": 2, "invt": 2, "pn": 1, "np": 1,
    })
    for r in ((d or {}).get("data") or {}).get("diff") or []:
        p = num(r.get("f2"))
        if p and 5.0 < p < 9.0:
            return p
    print("    [FX] USD/CNY not fetched, using fallback 7.2")
    return 7.2
