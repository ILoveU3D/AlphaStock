# 现金流优先估值体系 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec v2.1（`docs/superpowers/specs/2026-09-05-cashflow-first-valuation-design.md`）：年报口径的 fcf_yield / borrowed_dividend / capex_to_ocf 三因子（A/HK/US 三市场），ocf_yield 年报口径修正，四位大师 gates 吸收，ask 输出与判断层 Field Notes。

**Architecture:** 数据层三个新抓取（A 年报现金流 + A 分红事件表批量、HK per-stock 现金流量表、US frames 三概念）→ pipeline 层 `load_annual_cashflows` 统一装载 + `add_cashflow_factors` 统一算因子（build_master 与 build_watchlist 共用）→ 展示层（ask 旗标/指标、EVIDENCE_METRICS、peer 百分位）→ 策略层（masters gates、user set-style、Field Notes）。所有新列对旧快照 NaN 容错。

**Tech Stack:** Python 3.10+, pandas, requests（均已装在全局 Python，禁止 vendor）。测试 `python -B -m pytest tests -q`。

**关键事实（实施者必读）：**
- A 股行情（`CLIST_FIELDS`）**没有** dividend_yield 字段；A 股 div_paid 必须走 `RPT_SHAREBONUS_DET`。
- 港股 F10 金额全部是 **CNY**；港股市值是 **HKD**；fx = CNY/HKD（`fetch_fx_hkdcny()`，约 0.92）。
- 港股财年不统一：年报行用 `REPORT_DATE − START_DATE` 跨度 ∈ [330, 400] 天识别。
- `RPT_HKF10_FN_CASHFLOW_PC` 科目码：`003999` 经营净额、`005005` 购建固定资产、`005007` 购建无形资产、`007004` 已付股息、`007999` 融资净额。
- A 股 `RPT_DMSK_FN_CASHFLOW`：`NETCASH_OPERATE`/`CONSTRUCT_LONG_ASSET`/`NETCASH_FINANCE` 都在返回里（`columns: ALL`）。
- SEC frames 支付类概念值为正数（流出记正）。
- 测试全部离线（monkeypatch DC/SEC），一次联网验证放在 Task 8。

---

### Task 1: A 股年报现金流抓取

**Files:**
- Modify: `value_genie/fetch/fundamentals.py`（`A_CASHFLOW_MAP` 区块，约 L132-210）
- Test: `tests/test_fundamentals.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_fundamentals.py` 末尾追加：

```python
class TestAnnualReportDates:
    def test_newest_first(self):
        out = f.annual_report_dates(date(2026, 9, 5))
        assert out == [date(2025, 12, 31), date(2024, 12, 31)]


class TestParseCashflow:
    def test_keeps_capex_and_financing(self):
        d = {"result": {"data": [{
            "SECURITY_CODE": "600519",
            "REPORT_DATE": "2025-12-31 00:00:00",
            "NETCASH_OPERATE": "1000", "CONSTRUCT_LONG_ASSET": "200",
            "NETCASH_FINANCE": "-50"}]}}
        df = f._parse_cashflow(d)
        assert df.iloc[0]["ocf"] == 1000.0
        assert df.iloc[0]["capex"] == 200.0
        assert df.iloc[0]["net_fin_cf"] == -50.0


class TestFetchACashflowAnnual:
    def test_picks_latest_annual_period(self, monkeypatch):
        pages = {
            ("2025-12-31", 1): {"result": {"count": 1200, "data": [
                {"SECURITY_CODE": "600519", "REPORT_DATE": "2025-12-31",
                 "NETCASH_OPERATE": "100", "CONSTRUCT_LONG_ASSET": "10",
                 "NETCASH_FINANCE": "1"}]}},
            ("2024-12-31", 1): {"result": {"count": 1000, "data": []}},
        }

        def fake_page(rd, pn):
            return pages.get((rd, pn), {"result": {"count": 0}})

        monkeypatch.setattr(f, "_fetch_cashflow_page", fake_page)
        out = f.fetch_a_cashflow_annual(quiet=True)
        assert len(out) == 1
        assert out.iloc[0]["ocf"] == 100.0
        assert out.iloc[0]["capex"] == 10.0

    def test_falls_back_when_latest_missing(self, monkeypatch):
        # FY2025 annuals not mass-filed yet -> falls to FY2024
        pages = {
            ("2025-12-31", 1): {"result": {"count": 3, "data": []}},
            ("2024-12-31", 1): {"result": {"count": 1200, "data": [
                {"SECURITY_CODE": "000001", "REPORT_DATE": "2024-12-31",
                 "NETCASH_OPERATE": "7", "CONSTRUCT_LONG_ASSET": "2",
                 "NETCASH_FINANCE": "-1"}]}},
        }

        def fake_page(rd, pn):
            return pages.get((rd, pn), {"result": {"count": 0}})

        monkeypatch.setattr(f, "_fetch_cashflow_page", fake_page)
        out = f.fetch_a_cashflow_annual(quiet=True)
        assert len(out) == 1
        assert out.iloc[0]["code"] == "000001"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_fundamentals.py -q -k "Annual or ParseCashflow or AnnualReportDates"`
Expected: FAIL（`AttributeError: annual_report_dates` / `fetch_a_cashflow_annual` 不存在；`_parse_cashflow` 无 capex 列）

- [ ] **Step 3: 实现**

`value_genie/fetch/fundamentals.py`，把 `A_CASHFLOW_MAP` 改为：

```python
A_CASHFLOW_MAP = {
    "SECURITY_CODE": "code",
    "REPORT_DATE": "report_date",
    "NETCASH_OPERATE": "ocf",
    "CONSTRUCT_LONG_ASSET": "capex",
    "NETCASH_FINANCE": "net_fin_cf",
}
```

`_parse_cashflow` 中 `if "ocf" in df.columns: df["ocf"] = df["ocf"].map(num)` 一行替换为：

```python
    for c in ("ocf", "capex", "net_fin_cf"):
        if c in df.columns:
            df[c] = df[c].map(num)
```

在 `fetch_a_cashflow` 之后追加两个函数：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_fundamentals.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/fetch/fundamentals.py tests/test_fundamentals.py
git commit -m "feat(fetch): A-share annual cashflow (capex/net_fin_cf via DMSK, 12-31 periods)"
```

---

### Task 2: A 股分红事件表抓取

**Files:**
- Modify: `value_genie/fetch/fundamentals.py`（Task 1 函数之后追加）
- Test: `tests/test_fundamentals.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestFetchADividends:
    def test_aggregates_events_per_fy(self, monkeypatch):
        # two FY2025 events for 600519 (interim + annual), one bare
        # commitment row without amounts must be skipped
        def fake_page(year, pn):
            if year != "2025" or pn > 1:
                return {"result": {"count": 3, "data": []}}
            return {"result": {"count": 3, "data": [
                {"SECURITY_CODE": "600519", "REPORT_DATE": "2025-09-30",
                 "PRETAX_BONUS_RMB": "239.57", "TOTAL_SHARES": "1256197800"},
                {"SECURITY_CODE": "600519", "REPORT_DATE": "2025-12-31",
                 "PRETAX_BONUS_RMB": "280.2423", "TOTAL_SHARES": "1256197800"},
                {"SECURITY_CODE": "000002", "REPORT_DATE": "2026-06-30",
                 "PRETAX_BONUS_RMB": None, "TOTAL_SHARES": None},
            ]}}

        monkeypatch.setattr(f, "_fetch_dividend_page", fake_page)
        out = f.fetch_a_dividends(["2025"], quiet=True)
        assert len(out) == 1
        r = out.iloc[0]
        assert r["code"] == "600519" and r["fy"] == "2025"
        assert r["div_paid"] == pytest.approx(
            (239.57 + 280.2423) / 10.0 * 1256197800)

    def test_no_events_returns_empty(self, monkeypatch):
        monkeypatch.setattr(f, "_fetch_dividend_page",
                            lambda year, pn: {"result": {"count": 0}})
        assert f.fetch_a_dividends(["2025"], quiet=True).empty
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_fundamentals.py -q -k Dividends`
Expected: FAIL（`_fetch_dividend_page` 不存在）

- [ ] **Step 3: 实现**

`fetch_a_cashflow_annual` 之后追加：

```python
# ---------------------------------------------------------------------------
# A-share cash dividends (分红送配事件表) — div_paid input
# ---------------------------------------------------------------------------
A_DIVIDEND_REPORT_NAME = "RPT_SHAREBONUS_DET"


def _fetch_dividend_page(year: str, page: int) -> dict:
    """One page of A-share cash-dividend events for a fiscal year."""
    return DC.get_json(config.DC_WEB_URL, params={
        "reportName": A_DIVIDEND_REPORT_NAME,
        "columns": "ALL",
        "filter": (f"(REPORT_DATE>='{year}-01-01')"
                   f"(REPORT_DATE<='{year}-12-31')"),
        "pageNumber": page,
        "pageSize": config.A_PAGE_SIZE,
        "sortTypes": "1",
        "sortColumns": "SECURITY_CODE",
        "source": "WEB",
        "client": "WEB",
    }, retries=3) or {}


def fetch_a_dividends(years: list, quiet: bool = False) -> pd.DataFrame:
    """FY cash dividends declared per A-share, aggregated from the
    dividend-events report: div_paid = sum(PRETAX_BONUS_RMB / 10
    x TOTAL_SHARES) over events whose REPORT_DATE falls in the fiscal
    year. Events without a cash amount (bare commitments) are skipped.

    This is the A-share div_paid input for borrowed_dividend — the
    mechanism is strongest here: a dividend record is a precondition
    for refinancing eligibility, so strained companies keep paying.
    """
    rows = []
    for year in years:
        d = _fetch_dividend_page(year, 1)
        total = ((d.get("result") or {}).get("count")) or 0
        if not total:
            continue
        acc: dict = {}
        for pn in range(1, total // config.A_PAGE_SIZE + 2):
            page = (((_fetch_dividend_page(year, pn).get("result") or {})
                     .get("data")) or [])
            for r in page:
                dps = num(r.get("PRETAX_BONUS_RMB"))  # CNY per 10 shares
                shares = num(r.get("TOTAL_SHARES"))
                code = str(r.get("SECURITY_CODE") or "")
                if not code or dps is None or not shares:
                    continue
                key = (code, year)
                acc[key] = acc.get(key, 0.0) + dps / 10.0 * shares
            time.sleep(0.4)
        if not quiet:
            print(f"    [A] dividends {year}: {len(acc)} stocks")
        rows += [{"code": c, "fy": y, "div_paid": v}
                 for (c, y), v in acc.items()]
    return pd.DataFrame(rows, columns=["code", "fy", "div_paid"])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_fundamentals.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/fetch/fundamentals.py tests/test_fundamentals.py
git commit -m "feat(fetch): A-share FY cash dividends via RPT_SHAREBONUS_DET (div_paid source)"
```

---

### Task 3: 港股现金流量表抓取

**Files:**
- Modify: `value_genie/fetch/fundamentals.py`（`fetch_hk_lot` 之后、FX 区块之前追加）
- Test: `tests/test_fundamentals.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def _hk_row(rd, sd, item, amt):
    return {"REPORT_DATE": rd, "START_DATE": sd, "STD_ITEM_CODE": item,
            "STD_ITEM_NAME": "x", "AMOUNT": amt}


class TestHkCashflow:
    def test_annual_row_selected_and_mapped(self, monkeypatch):
        # interim (H1) rows must lose to the FY2025 annual group
        data = [
            _hk_row("2026-06-30", "2026-01-01", "003999", "500"),
            _hk_row("2026-06-30", "2026-01-01", "005005", "100"),
            _hk_row("2025-12-31", "2025-01-01", "003999", "1000"),
            _hk_row("2025-12-31", "2025-01-01", "005005", "200"),
            _hk_row("2025-12-31", "2025-01-01", "005007", "50"),
            _hk_row("2025-12-31", "2025-01-01", "007004", "300"),
            _hk_row("2025-12-31", "2025-01-01", "007999", "80"),
        ]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        df = f.fetch_hk_cashflow("06831")
        r = df.iloc[0]
        assert r["code"] == "06831"
        assert r["report_date"] == "2025-12-31"
        assert r["ocf"] == 1000.0
        assert r["capex"] == 250.0
        assert r["div_paid"] == 300.0
        assert r["net_fin_cf"] == 80.0

    def test_march_year_end_is_annual(self, monkeypatch):
        # HK fiscal years end in Mar/Jun/Sep/Dec — span, not month,
        # marks the annual report
        data = [_hk_row("2026-03-31", "2025-04-01", "003999", "900")]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        df = f.fetch_hk_cashflow("00005")
        assert df.iloc[0]["ocf"] == 900.0

    def test_no_annual_period_returns_none(self, monkeypatch):
        data = [_hk_row("2026-06-30", "2026-01-01", "003999", "500")]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        assert f.fetch_hk_cashflow("06831") is None

    def test_missing_item_stays_absent(self, monkeypatch):
        data = [_hk_row("2025-12-31", "2025-01-01", "003999", "1000")]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        r = f.fetch_hk_cashflow("06831").iloc[0]
        assert pd.isna(r.get("div_paid"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_fundamentals.py -q -k HkCashflow`
Expected: FAIL（`fetch_hk_cashflow` 不存在）

- [ ] **Step 3: 实现**

`fetch_hk_lot` 之后追加：

```python
# ---------------------------------------------------------------------------
# HK F10 cashflow statement (annual row) — CNY amounts
# ---------------------------------------------------------------------------
HK_CASHFLOW_ITEMS = {
    "003999": "ocf",          # 经营业务现金净额
    "005005": "capex_a",      # 购建固定资产
    "005007": "capex_b",      # 购建无形资产及其他资产
    "007004": "div_paid",     # 已付股息(融资活动)
    "007999": "net_fin_cf",   # 融资业务现金净额
}


def fetch_hk_cashflow(code5: str) -> pd.DataFrame | None:
    """Latest ANNUAL row of the HK F10 cashflow statement (CNY amounts).

    Long table: one row per (REPORT_DATE, STD_ITEM_CODE). Annual
    periods are identified by a START_DATE..REPORT_DATE span of
    330-400 days — HK fiscal year-ends are not uniform (Mar/Jun/Sep/
    Dec), so the span, not the month, marks the annual report.
    Returns a one-row DataFrame or None.
    """
    d = DC.get_json(config.DC_SEC_URL, params={
        "reportName": "RPT_HKF10_FN_CASHFLOW_PC",
        "columns": "ALL",
        "filter": f'(SECUCODE="{code5}.HK")',
        "pageNumber": 1,
        "pageSize": 120,
        "sortTypes": "-1,1",
        "sortColumns": "REPORT_DATE,STD_ITEM_CODE",
        "source": "F10",
        "client": "PC",
    })
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    for c in ("REPORT_DATE", "START_DATE"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    if "START_DATE" not in df.columns:
        return None
    span = (df["REPORT_DATE"] - df["START_DATE"]).dt.days
    ann = df[(span >= 330) & (span <= 400)]
    if ann.empty:
        return None
    latest = ann["REPORT_DATE"].max()
    ann = ann[ann["REPORT_DATE"] == latest]
    rec = {"code": code5, "report_date": latest.date().isoformat()}
    for _, r in ann.iterrows():
        key = HK_CASHFLOW_ITEMS.get(str(r.get("STD_ITEM_CODE")))
        val = num(r.get("AMOUNT"))
        if key in ("capex_a", "capex_b"):
            if val is not None:
                rec["capex"] = rec.get("capex", 0.0) + val
        elif key and val is not None:
            rec[key] = val
    return pd.DataFrame([rec])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_fundamentals.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/fetch/fundamentals.py tests/test_fundamentals.py
git commit -m "feat(fetch): HK annual cashflow via RPT_HKF10_FN_CASHFLOW_PC (ocf/capex/div_paid/net_fin_cf)"
```

---

### Task 4: US frames 三概念

**Files:**
- Modify: `value_genie/config.py`（`US_FRAMES_SPEC`，L100-120）
- Modify: `value_genie/fetch/fundamentals.py`（`fetch_us_financials` rec、`fetch_us_financials_one`）
- Test: `tests/test_fundamentals.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestUsCashflowFrames:
    def test_spec_contains_new_concepts(self):
        from value_genie import config
        concepts = {c for c, _, _ in config.US_FRAMES_SPEC}
        assert "PaymentsToAcquirePropertyPlantAndEquipment" in concepts
        assert "PaymentsOfDividendsCommonStock" in concepts
        assert "NetCashProvidedByUsedInFinancingActivities" in concepts

    def test_one_ticker_gains_cashflow_fields(self, monkeypatch):
        ctx = f.frames_year_context()
        vals = {
            "PaymentsToAcquirePropertyPlantAndEquipment": 200.0,
            "PaymentsOfDividendsCommonStock": 50.0,
            "NetCashProvidedByUsedInFinancingActivities": 80.0,
            "RevenueFromContractWithCustomerExcludingAssessedTax": 1000.0,
        }

        def fake_get_json(url, *args, **kwargs):
            if "company_tickers" in url:
                return {"0": {"ticker": "PDD", "cik_str": 123}}
            concept = url.rsplit("/", 1)[-1].split(".")[0]
            return {"units": {"USD": [
                {"frame": f"CY{ctx['cy']}", "val": vals.get(concept)}]}}

        monkeypatch.setattr(f.SEC, "get_json", fake_get_json)
        rec = f.fetch_us_financials_one("PDD", quiet=True)
        assert rec["capex"] == 200.0
        assert rec["div_paid"] == 50.0
        assert rec["net_fin_cf"] == 80.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_fundamentals.py -q -k UsCashflow`
Expected: FAIL（spec 无新概念 / rec 无新字段）

- [ ] **Step 3: 实现**

`config.py` `US_FRAMES_SPEC` 的 `("Assets", "instant", ["cy"]),` 行后追加三行：

```python
    # cashflow-first factors: capex / dividends paid / net financing
    ("PaymentsToAcquirePropertyPlantAndEquipment", "duration", ["cy"]),
    ("PaymentsOfDividendsCommonStock", "duration", ["cy"]),
    ("NetCashProvidedByUsedInFinancingActivities", "duration", ["cy"]),
```

`fundamentals.py` `fetch_us_financials` 中 `ocf = frames.get(...)` 行后追加，并把 rec 字典扩三列：

```python
    capex = frames.get(("PaymentsToAcquirePropertyPlantAndEquipment",
                        "cy")) or {}
    div_paid = frames.get(("PaymentsOfDividendsCommonStock", "cy")) or {}
    net_fin = frames.get(
        ("NetCashProvidedByUsedInFinancingActivities", "cy")) or {}
```

`rec = {...}` 里 `"ocf": ocf.get(cik)` 后追加：

```python
               "capex": capex.get(cik), "div_paid": div_paid.get(cik),
               "net_fin_cf": net_fin.get(cik),
```

`fetch_us_financials_one` 的 `rec = {...}`（`"profit_prev"` 行附近）追加三键：

```python
        "capex": concept_val(
            "PaymentsToAcquirePropertyPlantAndEquipment", f"CY{cy}", s, e),
        "div_paid": concept_val(
            "PaymentsOfDividendsCommonStock", f"CY{cy}", s, e),
        "net_fin_cf": concept_val(
            "NetCashProvidedByUsedInFinancingActivities", f"CY{cy}", s, e),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_fundamentals.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/config.py value_genie/fetch/fundamentals.py tests/test_fundamentals.py
git commit -m "feat(fetch): US capex/div_paid/net_fin_cf via SEC frames (+per-stock fallback)"
```

---

### Task 5: pipeline 因子层与集成（核心）

**Files:**
- Modify: `value_genie/fetch/pipeline.py`（MASTER_COLUMNS、imports、新函数、`merge_us_financials`、`build_master`、`build_watchlist`、`run()`、`fetch_hk_cashflow_deep`）
- Modify: `value_genie/strategy/factors.py`（`PILLAR_FACTORS`）
- Test: `tests/test_cashflow.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_cashflow.py`：

```python
"""Tests for annual-basis cashflow factors (fcf_yield /
borrowed_dividend / capex_to_ocf) and their pipeline integration."""

import numpy as np
import pandas as pd
import pytest

from value_genie.fetch import pipeline as pl
from value_genie.strategy.factors import PILLAR_FACTORS


def _master():
    return pd.DataFrame({
        "market": ["A", "HK", "US"],
        "code": ["600519", "06831", "PDD"],
        "market_cap": [100.0, 100.0, 100.0],
        "ocf_yield": [5.0, 5.0, 5.0],
    })


def _annual():
    return pd.DataFrame({
        "market": ["A", "HK", "US"],
        "code": ["600519", "06831", "PDD"],
        "ocf": [20.0, 20.0, 20.0],
        "capex": [5.0, 5.0, 5.0],
        "div_paid": [16.0, 16.0, 16.0],
        "net_fin_cf": [10.0, 10.0, 10.0],
    })


class TestAddCashflowFactors:
    def test_fcf_yield_same_currency_and_hk_fx(self):
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert out.loc[out["market"] == "A", "fcf_yield"].iloc[0] \
            == pytest.approx(15.0)
        assert out.loc[out["market"] == "HK", "fcf_yield"].iloc[0] \
            == pytest.approx(15.0 / 0.8)
        assert out.loc[out["market"] == "US", "fcf_yield"].iloc[0] \
            == pytest.approx(15.0)

    def test_ocf_yield_rebased_annual(self):
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert out.loc[out["market"] == "A", "ocf_yield"].iloc[0] \
            == pytest.approx(20.0)
        assert out.loc[out["market"] == "HK", "ocf_yield"].iloc[0] \
            == pytest.approx(25.0)

    def test_borrowed_dividend_true_positive(self):
        # div 16 > fcf 15, > ocf*0.5 = 10, net_fin 10 > 0
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert (out["borrowed_dividend"] == 1).all()

    def test_capex_borrower_not_flagged(self):
        # borrowing for capex with a small dividend stays clean
        ann = _annual()
        ann.loc[ann["market"] == "A", "capex"] = 18.0   # fcf = 2
        ann.loc[ann["market"] == "A", "div_paid"] = 4.0  # < ocf*0.5
        ann.loc[ann["market"] == "A", "net_fin_cf"] = 50.0
        out = pl.add_cashflow_factors(_master(), 0.8, ann)
        assert out.loc[out["market"] == "A", "borrowed_dividend"].iloc[0] == 0

    def test_negative_financing_not_flagged(self):
        ann = _annual()
        ann.loc[ann["market"] == "US", "net_fin_cf"] = -10.0
        out = pl.add_cashflow_factors(_master(), 0.8, ann)
        assert out.loc[out["market"] == "US", "borrowed_dividend"].iloc[0] == 0

    def test_missing_data_is_innocent(self):
        ann = _annual()
        ann.loc[ann["market"] == "US",
                ["capex", "div_paid", "net_fin_cf"]] = np.nan
        out = pl.add_cashflow_factors(_master(), 0.8, ann)
        assert out.loc[out["market"] == "US", "borrowed_dividend"].iloc[0] == 0
        assert pd.isna(out.loc[out["market"] == "US", "fcf_yield"].iloc[0])

    def test_empty_annual_passes_through(self):
        out = pl.add_cashflow_factors(_master(), 0.8, pd.DataFrame())
        assert (out["borrowed_dividend"] == 0).all()
        assert pd.isna(out["fcf_yield"]).all()
        assert (out["ocf_yield"] == 5.0).all()  # interim untouched

    def test_capex_to_ocf(self):
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert out.loc[0, "capex_to_ocf"] == pytest.approx(0.25)


class TestLoadAnnualCashflows:
    def test_joins_all_three_sources(self, tmp_path):
        pd.DataFrame({"code": ["600519"], "report_date": ["2025-12-31"],
                      "ocf": [100.0], "capex": [20.0],
                      "net_fin_cf": [-5.0]}
                     ).to_csv(tmp_path / "a_cashflow_annual.csv", index=False)
        pd.DataFrame({"code": ["600519"], "fy": ["2025"], "div_paid": [65.0]}
                     ).to_csv(tmp_path / "a_dividends.csv", index=False)
        pd.DataFrame({"code": ["06831"], "report_date": ["2025-12-31"],
                      "ocf": [50.0], "capex": [10.0], "div_paid": [8.0],
                      "net_fin_cf": [2.0]}
                     ).to_csv(tmp_path / "hk_cashflow.csv", index=False)
        pd.DataFrame({"ticker": ["PDD"], "rev": [1.0], "ocf": [200.0],
                      "capex": [40.0], "div_paid": [0.0],
                      "net_fin_cf": [30.0]}
                     ).to_csv(tmp_path / "us_financials.csv", index=False)
        out = pl.load_annual_cashflows(tmp_path)
        a = out[out["market"] == "A"].iloc[0]
        assert a["code"] == "600519" and a["div_paid"] == 65.0
        hk = out[out["market"] == "HK"].iloc[0]
        assert hk["code"] == "06831" and hk["div_paid"] == 8.0
        us = out[out["market"] == "US"].iloc[0]
        assert us["code"] == "PDD" and us["capex"] == 40.0

    def test_empty_when_no_files(self, tmp_path):
        assert pl.load_annual_cashflows(tmp_path).empty


class TestMasterIntegration:
    def test_columns_registered(self):
        assert {"fcf_yield", "borrowed_dividend", "capex_to_ocf"} \
            <= set(pl.MASTER_COLUMNS)
        assert ("fcf_yield", 1) in PILLAR_FACTORS["cashflow"]

    def test_build_master_carries_factors(self, tmp_path):
        pd.DataFrame({"code": ["600519"], "fy": ["2025"],
                      "div_paid": [16.0]}
                     ).to_csv(tmp_path / "a_dividends.csv", index=False)
        pd.DataFrame({"code": ["600519"], "report_date": ["2025-12-31"],
                      "ocf": [20.0], "capex": [5.0], "net_fin_cf": [10.0]}
                     ).to_csv(tmp_path / "a_cashflow_annual.csv", index=False)
        cands = {"A": pd.DataFrame({
            "market": ["A"], "code": ["600519"], "name": ["贵州茅台"],
            "price": [1500.0], "market_cap": [100.0], "pe_ttm": [20.0],
        })}
        master = pl.build_master(cands, tmp_path, None, None)
        row = master.iloc[0]
        assert row["fcf_yield"] == pytest.approx(15.0)
        assert row["borrowed_dividend"] == 1
        assert row["capex_to_ocf"] == pytest.approx(0.25)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_cashflow.py -q`
Expected: FAIL（`add_cashflow_factors` / `load_annual_cashflows` 不存在）

- [ ] **Step 3: 实现**

**3a. `factors.py`** — `PILLAR_FACTORS["cashflow"]` 改为：

```python
    "cashflow": [("ocf_yield", 1), ("cash_conversion", 1),
                 ("fcf_yield", 1)],
```

**3b. `pipeline.py` MASTER_COLUMNS** — `"ocf_yield", "cash_conversion",` 行后插：

```python
    "fcf_yield", "borrowed_dividend", "capex_to_ocf",
```

**3c. imports** — `from .fundamentals import (...)` 增加 `fetch_a_cashflow_annual, fetch_a_dividends, fetch_hk_cashflow`。

**3d. 新函数**（`fetch_hk_deep` 之后追加）：

```python
def fetch_hk_cashflow_deep(codes, snap_dir: Path, reuse_dirs: list,
                           stats: dict) -> pd.DataFrame:
    """Annual HK cashflow rows for candidates + watch symbols, reusing
    rows saved in a recent snapshot (same chain as fetch_hk_deep)."""
    have = {}
    for prev_dir in reuse_dirs:
        rp = prev_dir / "hk_cashflow.csv"
        if not rp.exists():
            continue
        try:
            prev = pd.read_csv(rp, dtype={"code": str})
            for _, r in prev.iterrows():
                have.setdefault(str(r["code"]), dict(r))
        except (OSError, pd.errors.ParserError, ValueError):
            continue
    rows = []
    for code in codes:
        code = str(code)
        if code in have:
            rows.append(have[code])
            stats["reused"] += 1
            continue
        cf = fetch_hk_cashflow(code)
        if cf is not None and not cf.empty:
            rows.append(cf.iloc[0].to_dict())
            stats["fetched"] += 1
        else:
            stats["failed"] += 1
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(snap_dir / "hk_cashflow.csv", index=False)
    return df


def load_annual_cashflows(snap_dir: Path) -> pd.DataFrame:
    """Annual-basis cash flows for the DCF-first factors, all markets.

    - A: a_cashflow_annual.csv (ocf/capex/net_fin_cf) + a_dividends.csv
      (FY cash dividends declared, matched by report year)
    - HK: hk_cashflow.csv (annual row per code, CNY amounts)
    - US: us_financials.csv extra columns (SEC cy frames)
    Missing files/columns degrade to NaN per row; empty when absent.
    """
    cols = ["market", "code", "ocf", "capex", "div_paid", "net_fin_cf"]
    parts = []

    def _read(name, key):
        p = snap_dir / name
        if not p.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(p, dtype={key: str})
        except (OSError, pd.errors.ParserError, ValueError):
            return pd.DataFrame()

    a = _read("a_cashflow_annual.csv", "code")
    if not a.empty:
        d = pd.DataFrame({"market": "A", "code": a["code"].astype(str)})
        for c in ("ocf", "capex", "net_fin_cf"):
            d[c] = (pd.to_numeric(a[c], errors="coerce")
                    if c in a.columns else float("nan"))
        d["div_paid"] = float("nan")
        d["fy"] = (a["report_date"].astype(str).str.slice(0, 4)
                   if "report_date" in a.columns else "")
        div = _read("a_dividends.csv", "code")
        if not div.empty and {"code", "fy", "div_paid"} <= set(div.columns):
            div = div.drop_duplicates(subset=["code", "fy"])
            d = d.merge(div, on=["code", "fy"], how="left",
                        suffixes=("", "_d"))
            d["div_paid"] = d["div_paid_d"]
            d = d.drop(columns=["div_paid_d"])
        parts.append(d.drop(columns=["fy"]))
    hk = _read("hk_cashflow.csv", "code")
    if not hk.empty:
        d = pd.DataFrame({"market": "HK",
                          "code": hk["code"].astype(str).str.zfill(5)})
        for c in ("ocf", "capex", "div_paid", "net_fin_cf"):
            d[c] = (pd.to_numeric(hk[c], errors="coerce")
                    if c in hk.columns else float("nan"))
        parts.append(d)
    us = _read("us_financials.csv", "ticker")
    if not us.empty and "capex" in us.columns:
        d = pd.DataFrame({"market": "US", "code": us["ticker"].astype(str)})
        d["ocf"] = pd.to_numeric(us.get("ocf"), errors="coerce")
        for c in ("capex", "div_paid", "net_fin_cf"):
            d[c] = pd.to_numeric(us.get(c), errors="coerce")
        parts.append(d)
    if not parts:
        return pd.DataFrame(columns=cols)
    return pd.concat(parts, ignore_index=True)


def add_cashflow_factors(df: pd.DataFrame, fx: float | None,
                         annual: pd.DataFrame) -> pd.DataFrame:
    """Join annual cash flows and derive the DCF-first factor set.

    - fcf_yield: (ocf - capex) / market cap, annual basis — the
      first-order DCF anchor (owner-earnings yield)
    - borrowed_dividend: 1 when FY dividends exceed FCF, exceed half
      of OCF, and financing is a net inflow — dividend kept alive to
      preserve refinancing eligibility (A-share mechanism) rather
      than to reward shareholders; 0 = pass (innocent until proven)
    - capex_to_ocf: reinvestment intensity (display-only)

    ocf_yield is re-based onto the annual figure where available:
    the interim-basis value built from half-year reports understates
    the run-rate ~2x mid-season and distorts Buffett's >=5 gate; rows
    without annual data keep the interim value as fallback.
    HK F10 amounts are CNY while market cap is HKD — converted via fx.
    """
    out = df
    if annual.empty:
        out = df.copy()
        out["fcf_yield"] = float("nan")
        out["capex_to_ocf"] = float("nan")
        out["borrowed_dividend"] = 0
        return out
    out = df.merge(annual, on=["market", "code"], how="left")
    if "ocf" not in out.columns:
        out["fcf_yield"] = float("nan")
        out["capex_to_ocf"] = float("nan")
        out["borrowed_dividend"] = 0
        return out
    ocf = pd.to_numeric(out.get("ocf"), errors="coerce")
    capex = pd.to_numeric(out.get("capex"), errors="coerce")
    fin = pd.to_numeric(out.get("net_fin_cf"), errors="coerce")
    div = pd.to_numeric(out.get("div_paid"), errors="coerce")
    mcap = pd.to_numeric(out.get("market_cap"), errors="coerce")
    conv = pd.Series(1.0, index=out.index)
    if fx and fx > 0:
        conv[out["market"] == "HK"] = 1.0 / fx  # CNY amount -> HKD

    fcf = ocf - capex
    out["fcf_yield"] = (fcf * conv / mcap.where(mcap > 0) * 100.0).where(
        fcf.notna() & mcap.notna())
    out["capex_to_ocf"] = (capex / ocf.where(ocf != 0)).where(
        capex.notna() & ocf.notna())
    flagged = (div > fcf) & (div > ocf * 0.5) & (fin > 0)
    out["borrowed_dividend"] = flagged.fillna(False).astype(int)

    yld = (ocf * conv / mcap.where(mcap > 0) * 100.0).where(
        ocf.notna() & mcap.notna())
    if "ocf_yield" in out.columns:
        out["ocf_yield"] = yld.fillna(out["ocf_yield"])
    else:
        out["ocf_yield"] = yld
    return out
```

**3e. `merge_us_financials`** — `for extra in ("cash_conversion", "ocf"):` 改为：

```python
    for extra in ("cash_conversion", "ocf", "capex", "div_paid",
                  "net_fin_cf"):
```

**3f. `build_master`** — `master = pd.concat(frames, ignore_index=True)` 之后插入：

```python
    master = add_cashflow_factors(master, fx, load_annual_cashflows(snap_dir))
```

**3g. `build_watchlist`** — `watch_df = pd.concat(frames, ignore_index=True)` 之后插入：

```python
    watch_df = add_cashflow_factors(watch_df, fx,
                                    load_annual_cashflows(snap_dir))
```

**3h. `run()`** — A 股块（`a_cf = _load_or_fetch(...)` 之后）追加：

```python
        a_cf_ann = _load_or_fetch(
            snap_dir / "a_cashflow_annual.csv",
            lambda: fetch_a_cashflow_annual(quiet=quiet),
            "code", "A annual cf")
        if a_cf_ann is not None and not a_cf_ann.empty \
                and "report_date" in a_cf_ann.columns:
            years = sorted({str(d)[:4] for d in a_cf_ann["report_date"]})
            _load_or_fetch(
                snap_dir / "a_dividends.csv",
                lambda: fetch_a_dividends(years, quiet=quiet),
                "code", "A dividends")
```

`if "A" in markets:` 块的初始化行 `a_fin = None / a_cf = None` 顺带加 `a_cf_ann = None`（其实局部作用域不必须，保持风格一致即可）。

HK 深抓块（`hk_f10 = fetch_hk_deep(...)` 与 manifest 行之间）追加：

```python
        hk_cf_stats = {"fetched": 0, "reused": 0, "failed": 0}
        fetch_hk_cashflow_deep(hk_codes, snap_dir, f10_reuse, hk_cf_stats)
        manifest["datasets"]["hk_cashflow"] = dict(hk_cf_stats)
        log(f"    [HK] cashflow {hk_cf_stats}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_cashflow.py tests/test_pipeline.py tests/test_factors.py -q`
Expected: 全部 PASS（test_pipeline 旧用例不回归）

- [ ] **Step 5: Commit**

```bash
git add value_genie/fetch/pipeline.py value_genie/strategy/factors.py tests/test_cashflow.py
git commit -m "feat(pipeline): annual-basis cashflow factors (fcf_yield/borrowed_dividend/capex_to_ocf) + ocf_yield annual rebase, 3 markets"
```

---

### Task 6: ask 输出与 peer 百分位

**Files:**
- Modify: `value_genie/analyze.py`（imports、`_flat_row`、`risk_flags`、`_snapshot_factors`、`build_peer_set`、`analyze_stock`、`render_brief`、`EVIDENCE_METRICS`）
- Test: `tests/test_analyze.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_analyze.py` 末尾追加：

```python
import pandas as pd


class TestSnapshotFactors:
    def test_reads_master_row(self, tmp_path):
        pd.DataFrame({"market": ["A"], "code": ["600519"],
                      "fcf_yield": [8.0], "borrowed_dividend": [0],
                      "capex_to_ocf": [0.2], "ocf_yield": [10.0]}
                     ).to_csv(tmp_path / "master.csv", index=False)
        out = a._snapshot_factors(tmp_path, "A", "600519")
        assert out["fcf_yield"] == 8.0
        assert out["borrowed_dividend"] == 0

    def test_falls_back_to_watchlist(self, tmp_path):
        pd.DataFrame({"market": ["US"], "code": ["PDD"],
                      "fcf_yield": [12.0], "borrowed_dividend": [1]}
                     ).to_csv(tmp_path / "watchlist.csv", index=False)
        out = a._snapshot_factors(tmp_path, "US", "PDD")
        assert out["fcf_yield"] == 12.0
        assert out["borrowed_dividend"] == 1

    def test_no_snapshot_returns_empty(self, tmp_path):
        assert a._snapshot_factors(tmp_path, "A", "600519") == {}


class TestBorrowedDividendFlag:
    def test_flagged_verbatim(self):
        result = {"quote": {}, "fundamentals": {}, "warnings": [],
                  "cashflow_factors": {"borrowed_dividend": 1}}
        flags = a.risk_flags(result)
        assert any("borrowed dividend" in fl for fl in flags)

    def test_clean_row_not_flagged(self):
        result = {"quote": {}, "fundamentals": {}, "warnings": [],
                  "cashflow_factors": {"borrowed_dividend": 0}}
        assert not any("borrowed dividend" in fl
                       for fl in a.risk_flags(result))
```

（若 test_analyze.py 已 import `a`/pd，跳过重复 import。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_analyze.py -q -k "Snapshot or Borrowed"`
Expected: FAIL（`_snapshot_factors` 不存在）

- [ ] **Step 3: 实现**

**3a. imports** — analyze.py 顶部补 `import json`（若无）；`from .fetch.pipeline import (...)` 加 `add_cashflow_factors, load_annual_cashflows`。

**3b. `EVIDENCE_METRICS`** — 末尾 `("drawdown_52w", ...)` 行后追加：

```python
    ("ocf_yield", "OCF yield % (annual)", False),
    ("fcf_yield", "FCF yield % (annual)", False),
    ("capex_to_ocf", "Capex/OCF", True),
```

**3c. `_flat_row`** — `row.update(result.get("fundamentals") or {})` 后插一行：

```python
    row.update(result.get("cashflow_factors") or {})
```

**3d. `risk_flags`** — `if result.get("warnings"):` 前追加：

```python
    if (v := _num("borrowed_dividend")) is not None and v > 0:
        flags.append("borrowed dividend: 年报分红超过自由现金流且筹资净流入"
                     "（A 股语境：保再融资资格的借钱分红，危险信号）")
```

**3e. 新函数**（`_flat_row` 之后）：

```python
def _snapshot_factors(snap, market: str, code: str) -> dict:
    """Cashflow-first factors for the target from the snapshot's
    master/watchlist rows (annual basis, snapshot market cap)."""
    if snap is None:
        return {}
    for fname in ("master.csv", "watchlist.csv"):
        p = snap / fname
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            continue
        if "market" not in df.columns or "code" not in df.columns:
            continue
        hit = df[(df["market"] == market)
                 & (df["code"].astype(str) == str(code))]
        if not hit.empty:
            r = hit.iloc[0]
            return {k: r.get(k) for k in ("ocf_yield", "fcf_yield",
                                         "capex_to_ocf",
                                         "borrowed_dividend")}
    return {}


def _manifest_fx(snap) -> float | None:
    """HKD/CNY rate recorded by the fetch run, if any."""
    try:
        m = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
        v = m.get("fx_hkdcny")
        return float(v) if v else None
    except (OSError, ValueError, TypeError):
        return None
```

**3f. `analyze_stock`** — `result["fundamentals"] = fins` 之后追加：

```python
    result["cashflow_factors"] = _snapshot_factors(snap, match.market,
                                                    match.code)
```

peer 打分行 `row = _target_row(match, quote, fins, klm)` 替换为：

```python
            row = _target_row(match, quote, fins, klm)
            row.update({k: v for k, v in result["cashflow_factors"].items()
                        if v is not None
                        and not (isinstance(v, float) and pd.isna(v))})
```

**3g. `build_peer_set`** — `return backfill_kline_factors(gated, snap)` 替换为：

```python
    annual = load_annual_cashflows(snap)
    if not annual.empty:
        gated = add_cashflow_factors(gated, _manifest_fx(snap), annual)
    return backfill_kline_factors(gated, snap)
```

**3h. `render_brief`** — 指标循环 `for col, label in (("pe_ttm", "PE"), ("rev_yoy", "rev YoY"), ("roe", "ROE")):` 改为：

```python
    for col, label in (("pe_ttm", "PE"), ("rev_yoy", "rev YoY"),
                       ("roe", "ROE"), ("fcf_yield", "FCF yield"),
                       ("capex_to_ocf", "capex/ocf")):
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_analyze.py tests/test_report.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/analyze.py tests/test_analyze.py
git commit -m "feat(analyze): ask shows fcf_yield/capex_to_ocf + borrowed-dividend flag; peers gain annual cashflow factors"
```

---

### Task 7: 大师 gates 吸收 + AGENTS.md

**Files:**
- Modify: `value_genie/strategy/masters.py`
- Modify: `AGENTS.md`（大师门槛表）
- Test: `tests/test_masters.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_masters.py` 末尾追加（顶部若无则补 import）：

```python
import pandas as pd

from value_genie.strategy.registry import evaluate_gates, get_strategy


class TestCashflowFirstGates:
    def test_buffett_absorbs_both(self):
        gates = {c: (op, v) for c, op, v in get_strategy("buffett").gates}
        assert gates["borrowed_dividend"] == ("<=", 0.0)
        assert gates["fcf_yield"] == (">=", 4.0)

    def test_fundamental_masters_reject_borrowed_dividend(self):
        for sid in ("munger", "graham", "duan"):
            assert any(c == "borrowed_dividend"
                       for c, _, _ in get_strategy(sid).gates), sid

    def test_price_masters_untouched(self):
        for sid in ("livermore", "sheng"):
            assert not any(c == "borrowed_dividend"
                           for c, _, _ in get_strategy(sid).gates), sid

    def test_flagged_row_excluded_from_buffett(self):
        df = pd.DataFrame({
            "market": ["A", "A"], "code": ["1", "2"],
            "roe": [20.0, 20.0], "gross_margin": [50.0, 50.0],
            "debt_ratio": [30.0, 30.0], "ocf_yield": [8.0, 8.0],
            "fcf_yield": [6.0, 6.0],
            "borrowed_dividend": [0, 1]})
        mask = evaluate_gates(df, get_strategy("buffett").gates)
        assert list(mask) == [True, False]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_masters.py -q -k Cashflow`
Expected: FAIL

- [ ] **Step 3: 实现**

`masters.py` 四处 gates 列表追加：

buffett（`("ocf_yield", ">=", 5.0),` 后）：

```python
            ("fcf_yield", ">=", 4.0),
            ("borrowed_dividend", "<=", 0.0),
```

munger（`("debt_ratio", "<=", 50.0),` 后）：

```python
            ("borrowed_dividend", "<=", 0.0),
```

graham（`("roe", ">=", 10.0),` 后）：

```python
            ("borrowed_dividend", "<=", 0.0),
```

duan（`("volatility", "pctl<=", 60),` 后）：

```python
            ("borrowed_dividend", "<=", 0.0),
```

`AGENTS.md` 大师表：buffett 行 Key gates 改为 `ROE≥15%, 毛利率≥40%, 负债率≤60%, OCF yield≥5%, FCF yield≥4%, 借钱分红否决`；munger/graham/duan 三行 Key gates 各补 `借钱分红否决`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_masters.py tests/test_registry.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/strategy/masters.py AGENTS.md tests/test_masters.py
git commit -m "feat(masters): buffett/munger/graham/duan gates reject borrowed dividends; buffett adds fcf_yield>=4"
```

---

### Task 8: 全量测试 + 联网验证 + 用户风格 + Field Notes

**Files:**
- Modify: `users/me.json`（仅经 CLI）
- Modify: skills Field Notes（仅经 `skill note`）
- 无新代码文件

- [ ] **Step 1: 全量测试**

Run: `python -B -m pytest tests -q`
Expected: 全部 PASS，无回归

- [ ] **Step 2: 强制刷新当日快照的现金流数据**

今天的快照 `data/snapshots/20260905/` 里 `us_financials.csv` 是旧 schema（无新列），resume 会直接复用它。删掉它让 fetch 重抓（其余文件照常 resume，省时间）：

```powershell
Remove-Item data\snapshots\20260905\us_financials.csv
python -B -m value_genie fetch
```

Expected: fetch 正常完成；日志出现 `[A] annual cashflow`、`[A] dividends 2025`、`[HK] cashflow {...}`、`[US] frame PaymentsToAcquire...`。

- [ ] **Step 3: 数据抽查（power shell 里跑 python -B -c）**

```powershell
python -B -c "import pandas as pd; m = pd.read_csv(r'data\snapshots\20260905\master.csv'); print(m[['market','code','name','ocf_yield','fcf_yield','capex_to_ocf','borrowed_dividend']].describe(include='all')); print(m[m['borrowed_dividend']==1][['market','code','name']].head(20).to_string())"
```

Expected: 三市场 fcf_yield 有可观填充；borrowed_dividend=1 的名单非空且数量合理（全市场 0 个=检测没生效，几百个=过严，都要查）。

茅台分红金额核对：

```powershell
python -B -c "import pandas as pd; d = pd.read_csv(r'data\snapshots\20260905\a_dividends.csv'); print(d[d['code']=='600519'])"
```

Expected: fy=2025 的 div_paid ≈ 6.5e10（(239.57+280.2423)/10 × 12.56 亿股 ≈ 653 亿元）。量级差一个 fx/股本单位即查 `TOTAL_SHARES` 口径。

HK 抽查（绿茶 06831，年报口径 ocf/capex 为 CNY、量级 vs 净利润合理）：

```powershell
python -B -c "import pandas as pd; print(pd.read_csv(r'data\snapshots\20260905\hk_cashflow.csv').head())"
```

- [ ] **Step 4: CLI 冒烟**

```powershell
python -B -m value_genie ask 绿茶集团
python -B -m value_genie ask 600519 --evidence
python -B -m value_genie screen --strategy buffett
```

Expected: ask 出现 `FCF yield` 行；evidence 表出现 OCF yield / FCF yield / Capex/OCF 三行；buffett 屏正常出票（门槛含 fcf_yield>=4 后数量可能减少——这本身是修正）。

- [ ] **Step 5: 用户风格落盘（CLI，非手改文件）**

```powershell
python -B -m value_genie user set-style me --weight value=0.10 --weight growth=0.25 --weight quality=0.25 --weight safety=0.15 --weight momentum=0.05 --weight cashflow=0.20 --gate "ret_20d<=-3" --gate "roe>=10" --gate "rev_yoy>=0" --gate "borrowed_dividend<=0" --gate "debt_ratio<=60"
python -B -m value_genie user show me
```

Expected: 权重六项和=1.00（自动归一化），gates 五条齐全。

- [ ] **Step 6: Field Notes（append-only，不改 Playbook 正文）**

```powershell
python -B -m value_genie skill note trading "S001 framework v2 (cashflow-first): (1) 估值锚从 PE 换成 FCF 收益率（DCF 一阶近似，年报口径）; (2) 买入前四问写进 --note：负债怎么来的、准备怎么处理？现金流怎么来的、准备怎么处理？; (3) borrowed_dividend=1 一票否决——A 股机制：分红是再融资资格的敲门砖，现金流出问题的公司保资格式分红（分红出去的钱从筹资端回来）; (4) 烟蒂备用仓（银行/保险/稳健）必须过 graham 屏（pe_pb<=22.5），格雷厄姆安全边际算术，不做价格目标"
python -B -m value_genie skill note holding-deep-review "四问测试 + DCF 三问（未来现金流从哪来/多少/什么折现率）+ borrowed_dividend 检查（年报分红超 FCF 且筹资净流入 = 借钱分红，一票否决）"
python -B -m value_genie skill note single-stock-analysis "fcf_yield = (年报经营现金流 - 资本开支)/市值 = DCF 一阶锚；capex_to_ocf = 再投资强度；borrowed_dividend=1 = 年报分红超过 FCF 且筹资净流入（A 股语境：保再融资资格的借钱分红，危险信号）"
```

- [ ] **Step 7: 最终提交**

```bash
git status --short
git add users/me.json trading/ 2>$null
git commit -m "chore: user style cashflow-first weights/gates + trading skill field notes (if changed)"
```

（若 users/me.json 与 skills 无 diff，跳过空提交。）

---

## Self-Review 记录

- **Spec 覆盖**：§1 数据层=Task 1-4；§2 因子层=Task 5；§3 风格层=Task 8 Step 5；§3a 大师=Task 7；§4 输出层=Task 6+8 Step 4；§5 判断层=Task 8 Step 6；§6 测试=各任务+Task 8 全量与联网验证。§0 rationale 体现在 add_cashflow_factors docstring、masters 注释、Field Notes。
- **占位符扫描**：无 TBD/TODO；所有代码块完整。
- **类型一致性**：`add_cashflow_factors(df, fx, annual)` 签名在 Task 5/6 一致；`_snapshot_factors(snap, market, code)` 在定义与调用一致；`fetch_a_dividends(years, quiet)` 与 run() 调用一致。
- **已知风险**：(1) `RPT_SHAREBONUS_DET` 年度区间链式 filter 若不被接受，回退为按 REPORT_DATE 等值抓 4 个季度各一次（同函数内改 filter 即可，测试不受影响——测试 monkeypatch 的是 `_fetch_dividend_page`）。(2) `RPT_HKF10_FN_CASHFLOW_PC` 若存在 CURRENCY 列且部分公司非 CNY 行混入，Task 8 Step 3 的量级抽查会暴露（对不上 fx 倍数即修：解析时按 CURRENCY 过滤）。
