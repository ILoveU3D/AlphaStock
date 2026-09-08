# Intel Event Radar P1 (A-share) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the intel radar batch channel for A-shares — full-market event tables (解禁/减持/回购/定增/业绩预告/披露预约) + earnings-quality flags, merged as 9 risk columns into master.csv / watchlist.csv, with event_radar.csv detail and doctor coverage.

**Architecture:** New `value_genie/intel/` subpackage split by subsystem (per user mandate): `model.py` (IntelItem + eq signals), `_dc.py` (shared Eastmoney datacenter pager), `earnings.py` / `announcements.py` (per-subsystem A-share fetchers), `radar.py` (aggregation + merge). `run_fetch()` calls `build_event_radar()` after master/watchlist assembly. Semantics: no event = 0.0 (positive confirmation), source failure = NaN (gates fail-closed). Spec: `docs/superpowers/specs/2026-09-08-intel-sentiment-system-design.md`.

**Tech Stack:** Python 3.10+, pandas, requests (already installed globally — never vendor). Tests: pytest with all network mocked.

**Out of scope (P2/P3/P4):** `intel X` command, ask/recommend/holding integration, HK/US sources, graham/livermore gates, skill 16, AGENTS.md/README.

---

## File Structure

```
value_genie/intel/                 # NEW subpackage
  __init__.py                      # imports fetch first, then sources (order-safe)
  sources.py                       # extends eastmoney registry entry: events:A, announce:A
  _dc.py                           # shared datacenter pager + code/name/date helpers
  model.py                         # IntelItem, IMPACT_BY_KIND, FORECAST_DIRECTION,
                                   #   item_to_row/row_to_item, earnings_quality
  announcements.py                 # fetch_a_unlocks / holder_changes / buybacks / placements
  earnings.py                      # fetch_a_forecasts / appointments / balance
  radar.py                         # RADAR_COLUMNS, build_event_radar, merge_radar

value_genie/config.py              # MODIFY: report-name constants + thresholds
value_genie/fetch/pipeline.py      # MODIFY: MASTER_COLUMNS += RADAR_COLUMNS; radar pass
value_genie/fetch/fundamentals.py  # MODIFY: A_FIELD_MAP += deduct_eps, basic_eps
value_genie/doctor.py              # MODIFY: event_radar.csv check

tests/test_intel_model.py          # NEW
tests/test_intel_sources.py        # NEW (registration + dc_report + fetchers)
tests/test_intel_radar.py          # NEW
tests/test_pipeline.py             # MODIFY: intel stubs + radar assertions
tests/test_fundamentals.py         # MODIFY: _parse_lico deduct EPS
tests/test_overview.py             # MODIFY: make_snap + doctor check
```

**Import-order safety:** `fetch.pipeline` imports `intel.radar` at module top. `intel/__init__` imports `value_genie.fetch` FIRST (so eastmoney is registered before intel extends it) — verified no cycle: `fetch/__init__` imports only `http` + `sources`, never intel.

---

### Task 0: Baseline, branch, commit pending docs

**Files:**
- Create: `docs/superpowers/plans/2026-09-08-intel-radar-p1.md` (this file)
- Commit pending: `docs/superpowers/specs/2026-09-08-intel-sentiment-system-design.md`, `skills/04-data-ops.md`

- [ ] **Step 1: Verify baseline is green**

```bash
python -B -m pytest tests -q
```

Expected: all tests pass (434 passed as of 2026-09-08).

- [ ] **Step 2: Create feature branch off the spec branch** (spec must ride in the same PR)

```bash
git checkout -b feat/intel-radar-p1
```

- [ ] **Step 3: Commit the pending doc changes + this plan**

```bash
git add docs/superpowers/specs/2026-09-08-intel-sentiment-system-design.md skills/04-data-ops.md docs/superpowers/plans/2026-09-08-intel-radar-p1.md
git commit -m "docs(intel): P1 radar implementation plan + probe appendix + DC field notes"
```

---

### Task 1: Config constants + intel package skeleton + source registration

**Files:**
- Modify: `value_genie/config.py` (append a new section after the `HK_ORGPROFILE_REPORT` line at the end)
- Create: `value_genie/intel/__init__.py`, `value_genie/intel/sources.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intel_sources.py`:

```python
"""Tests for value_genie.intel source registration + datacenter
fetchers (all network mocked)."""

from value_genie.strategy.registry import get_sources, list_sources


def test_import_intel_alone_extends_eastmoney():
    """Importing intel must be order-safe: intel/__init__ imports fetch
    first so the eastmoney entry exists before capabilities extend."""
    import value_genie.intel  # noqa: F401 — deliberately no fetch import
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert "events:A" in ds.capabilities
    assert "announce:A" in ds.capabilities
    assert [s.id for s in get_sources("events", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("announce", "A")] == ["eastmoney"]


def test_registration_is_idempotent():
    import value_genie.intel  # noqa: F401
    import value_genie.intel.sources as src
    src._register_intel_sources()   # second call must not duplicate caps
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert ds.capabilities.count("events:A") == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -B -m pytest tests/test_intel_sources.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'value_genie.intel'`.

- [ ] **Step 3: Add config constants**

Append to `value_genie/config.py` (after the `HK_ORGPROFILE_REPORT` line):

```python
# ---------------------------------------------------------------------------
# Intel event radar (P1: A-share batch event tables, design 2026-09-08)
# ---------------------------------------------------------------------------
A_UNLOCK_REPORT_NAME = "RPT_LIFT_STAGE"             # 解禁时间表
A_HOLDER_REPORT_NAME = "RPT_SHARE_HOLDER_INCREASE"  # 股东增减持
A_BUYBACK_REPORT_NAME = "RPTA_WEB_GPHG"             # 回购（不可带 sortColumns）
A_PLACEMENT_REPORT_NAME = "RPT_SEO_DETAIL"          # 定增
A_FORECAST_REPORT_NAME = "RPT_PUBLIC_OP_NEWPREDICT" # 业绩预告
A_APPOINT_REPORT_NAME = "RPT_PUBLIC_BS_APPOIN"      # 披露预约
A_BALANCE_REPORT_NAME = "RPT_DMSK_FN_BALANCE"       # 资产负债表（eq 信号用）

INTEL_LOOKBACK_DAYS = 90    # 公告/预告回看窗口（天）
INTEL_FORECAST_DAYS = 90    # 解禁/披露预约前看窗口（天）
UNLOCK_RED_PCT = 5.0        # unlock_pct_30d 红旗阈值（%）
EQ_FLAG_RED = 3             # eq_flags 触发 intel_red 的计数
REPORT_DUE_WARN = 14        # report_due_days 预警阈值（P2 渲染用）
EQ_GROWTH_PAD = 10.0        # 应收/存货同比超过营收同比的幅度（pct）
EQ_OCF_RATIO_MIN = 0.5      # OCF/净利润 下限
EQ_NONRECURRING_MIN = 0.6   # 扣非每股/基本每股 下限（A股专属）
```

- [ ] **Step 4: Create the intel package**

Create `value_genie/intel/__init__.py`:

```python
"""Intel subsystem: event radar + per-stock intelligence.

Importing the subpackage auto-registers intel data source capabilities
(extending the base sources registered by ``value_genie.fetch``).
"""

from .. import fetch  # noqa: F401 — base sources must register first
from . import sources  # noqa: F401 — extends them (events/announce)
```

Create `value_genie/intel/sources.py`:

```python
"""Intel data source registration (design §4).

P1: eastmoney gains events:A + announce:A (A-share batch event tables
for the radar channel). P3 will register cninfo / hkexnews / yahoo /
stockanalysis as new entries for HK/US coverage.
"""

from ..strategy.registry import list_sources, set_source_order


def _register_intel_sources():
    """Extend the existing eastmoney entry with intel capabilities.

    Mutates the registered DataSource in place (register_source would
    need the whole entry duplicated); idempotent by construction.
    """
    for ds in list_sources():
        if ds.id == "eastmoney":
            for cap in ("events:A", "announce:A"):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
    set_source_order("events", "A", ["eastmoney"])
    set_source_order("announce", "A", ["eastmoney"])


_register_intel_sources()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -B -m pytest tests/test_intel_sources.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add value_genie/config.py value_genie/intel/__init__.py value_genie/intel/sources.py tests/test_intel_sources.py
git commit -m "feat(intel): package skeleton + source registration + config constants"
```

---

### Task 2: IntelItem unified data model

**Files:**
- Create: `value_genie/intel/model.py`
- Test: `tests/test_intel_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intel_model.py`:

```python
"""Tests for value_genie.intel.model (no network)."""

from datetime import date

from value_genie.intel import model


class TestIntelItem:
    def test_defaults(self):
        it = model.IntelItem(
            market="A", code="688795", name="摩尔线程-U",
            subsystem="announcements", kind="unlock",
            event_date=date(2026, 9, 12), title="限售解禁")
        assert it.impact == "neutral"
        assert it.payload == {}
        assert it.url == ""
        assert it.source == "eastmoney"

    def test_row_round_trip(self):
        it = model.IntelItem(
            market="A", code="688795", name="摩尔线程-U",
            subsystem="announcements", kind="unlock",
            event_date=date(2026, 9, 12), title="限售解禁 12% 总股本",
            source="eastmoney", impact="negative",
            payload={"unlock_pct": 12.0})
        row = model.item_to_row(it)
        assert row["event_date"] == "2026-09-12"
        back = model.row_to_item(row)
        assert back == it

    def test_impact_map_values(self):
        assert set(model.IMPACT_BY_KIND.values()) <= {
            "positive", "negative", "neutral"}
        assert model.IMPACT_BY_KIND["unlock"] == "negative"
        assert model.IMPACT_BY_KIND["buyback"] == "positive"
        assert model.IMPACT_BY_KIND["holder_add"] == "positive"

    def test_forecast_direction(self):
        assert model.FORECAST_DIRECTION["预增"] == 1
        assert model.FORECAST_DIRECTION["扭亏"] == 1
        assert model.FORECAST_DIRECTION["首亏"] == -1
        assert model.FORECAST_DIRECTION["续亏"] == -1
        # unknown PREDICT_TYPE -> neutral via .get default
        assert model.FORECAST_DIRECTION.get("预盈", 0) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -B -m pytest tests/test_intel_model.py -v
```

Expected: FAIL — `ModuleNotFoundError` / `ImportError` (model.py does not exist).

- [ ] **Step 3: Write model.py (item + maps only; earnings_quality lands in Task 3)**

Create `value_genie/intel/model.py`:

```python
"""Intel unified data model: IntelItem, impact mapping, forecast
direction (design 2026-09-08 §3/§5).

``impact`` is a static per-kind mapping (解禁=negative, 回购=positive),
NOT sentiment inference — interpreting the text is the AI agent's job.
"""

import json
from dataclasses import dataclass, field
from datetime import date


@dataclass
class IntelItem:
    market: str            # "A" | "HK" | "US"
    code: str              # snapshot code form (600519 / 00700 / AAPL)
    name: str
    subsystem: str         # "earnings" | "announcements" | "news" | "ratings"
    kind: str              # unlock|holder_cut|holder_add|buyback|placement|
                           # forecast_up|forecast_down|forecast_flat|
                           # report_date|eq_flag|...
    event_date: date
    title: str
    url: str = ""
    source: str = "eastmoney"
    impact: str = "neutral"    # positive|negative|neutral
    payload: dict = field(default_factory=dict)


IMPACT_BY_KIND = {
    "unlock": "negative",
    "holder_cut": "negative",
    "holder_add": "positive",
    "buyback": "positive",
    "placement": "negative",
    "forecast_up": "positive",
    "forecast_down": "negative",
    "forecast_flat": "neutral",
    "report_date": "neutral",
    "eq_flag": "negative",
}

# A股业绩预告 PREDICT_TYPE -> 方向 (-1/0/1)
FORECAST_DIRECTION = {
    "预增": 1, "略增": 1, "扭亏": 1, "续盈": 1,
    "预减": -1, "略减": -1, "首亏": -1, "续亏": -1,
    "预平": 0, "不确定": 0,
}

DETAIL_COLUMNS = ["market", "code", "name", "subsystem", "kind",
                  "event_date", "impact", "title", "url", "source",
                  "payload"]


def item_to_row(item: IntelItem) -> dict:
    """Flatten an IntelItem to an event_radar.csv row (payload→JSON)."""
    return {
        "market": item.market, "code": item.code, "name": item.name,
        "subsystem": item.subsystem, "kind": item.kind,
        "event_date": item.event_date.isoformat(),
        "impact": item.impact, "title": item.title, "url": item.url,
        "source": item.source,
        "payload": json.dumps(item.payload, ensure_ascii=False),
    }


def row_to_item(row) -> IntelItem:
    """Rebuild an IntelItem from an event_radar.csv row/dict."""
    d = row if isinstance(row, dict) else dict(row)
    return IntelItem(
        market=d["market"], code=str(d["code"]), name=d.get("name", ""),
        subsystem=d["subsystem"], kind=d["kind"],
        event_date=date.fromisoformat(str(d["event_date"])[:10]),
        impact=d.get("impact", "neutral"),
        title=d.get("title", ""), url=d.get("url") or "",
        source=d.get("source", ""),
        payload=json.loads(d.get("payload") or "{}"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -B -m pytest tests/test_intel_model.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/model.py tests/test_intel_model.py
git commit -m "feat(intel): IntelItem unified data model"
```

---

### Task 3: Earnings-quality red flags (earnings_quality)

**Files:**
- Modify: `value_genie/intel/model.py` (append)
- Test: `tests/test_intel_model.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_intel_model.py`:

```python
class TestEarningsQuality:
    def test_receivables_flag(self):
        assert model.earnings_quality(
            {"rev_yoy": 20.0, "rece_yoy": 35.0}) == ["eq_receivables"]
        # exactly at the pad (20+10) -> not a flag
        assert model.earnings_quality(
            {"rev_yoy": 20.0, "rece_yoy": 30.0}) == []

    def test_inventory_flag(self):
        assert model.earnings_quality(
            {"rev_yoy": 5.0, "inv_yoy": 20.0}) == ["eq_inventory"]

    def test_ocf_gap(self):
        assert model.earnings_quality(
            {"ocf": 40.0, "profit": 100.0}) == ["eq_ocf_gap"]
        assert model.earnings_quality(
            {"ocf": 50.0, "profit": 100.0}) == []      # boundary: not <
        assert model.earnings_quality(
            {"ocf": -10.0, "profit": 100.0}) == ["eq_ocf_gap"]
        # loss-maker: a negative-profit ratio is meaningless -> skip
        assert model.earnings_quality(
            {"ocf": 10.0, "profit": -100.0}) == []

    def test_nonrecurring(self):
        assert model.earnings_quality(
            {"deduct_eps": 0.5, "basic_eps": 1.0}) == ["eq_nonrecurring"]
        assert model.earnings_quality(
            {"deduct_eps": 0.6, "basic_eps": 1.0}) == []  # boundary
        assert model.earnings_quality(
            {"deduct_eps": 0.1, "basic_eps": -1.0}) == []  # negative base

    def test_all_four(self):
        rec = {"rev_yoy": 10.0, "rece_yoy": 30.0, "inv_yoy": 30.0,
               "ocf": 10.0, "profit": 100.0,
               "deduct_eps": 0.1, "basic_eps": 1.0}
        assert model.earnings_quality(rec) == [
            "eq_receivables", "eq_inventory", "eq_ocf_gap",
            "eq_nonrecurring"]

    def test_missing_inputs_never_flag(self):
        assert model.earnings_quality({}) == []
        assert model.earnings_quality(
            {"rev_yoy": None, "rece_yoy": float("nan")}) == []
        assert model.earnings_quality({"rece_yoy": 99.0}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_intel_model.py -v
```

Expected: FAIL — `AttributeError: ... has no attribute 'earnings_quality'`.

- [ ] **Step 3: Implement earnings_quality**

Append to `value_genie/intel/model.py`:

```python
def earnings_quality(rec: dict) -> list:
    """Earnings-quality red flags for one stock (design §5).

    ``rec`` keys (all optional, NaN-safe): rev_yoy, rece_yoy (应收
    YoY %), inv_yoy (存货 YoY %), ocf, profit, deduct_eps, basic_eps.
    Returns triggered signal ids:

      eq_receivables   应收同比 > 营收同比 + EQ_GROWTH_PAD
      eq_inventory     存货同比 > 营收同比 + EQ_GROWTH_PAD
      eq_ocf_gap       OCF/净利润 < EQ_OCF_RATIO_MIN (profit>0 only —
                       a loss-maker's ratio is meaningless)
      eq_nonrecurring  扣非每股/基本每股 < EQ_NONRECURRING_MIN (A股专属)

    eq_goodwill deferred: RPT_DMSK_FN_BALANCE has no goodwill field
    (design §5); revisit with a per-stock fallback in P3.
    Missing inputs never trigger a flag — a flag needs both sides of
    its comparison. Signals are observations, not verdicts.
    """
    from .. import config

    def _num(key):
        try:
            v = rec.get(key)
            if v is None or v != v:          # None or NaN
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    rev = _num("rev_yoy")
    rece = _num("rece_yoy")
    inv = _num("inv_yoy")
    ocf = _num("ocf")
    profit = _num("profit")
    deduct = _num("deduct_eps")
    basic = _num("basic_eps")

    flags = []
    if rev is not None and rece is not None \
            and rece > rev + config.EQ_GROWTH_PAD:
        flags.append("eq_receivables")
    if rev is not None and inv is not None \
            and inv > rev + config.EQ_GROWTH_PAD:
        flags.append("eq_inventory")
    if ocf is not None and profit is not None and profit > 0 \
            and ocf / profit < config.EQ_OCF_RATIO_MIN:
        flags.append("eq_ocf_gap")
    if deduct is not None and basic is not None and basic > 0 \
            and deduct / basic < config.EQ_NONRECURRING_MIN:
        flags.append("eq_nonrecurring")
    return flags
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -B -m pytest tests/test_intel_model.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/model.py tests/test_intel_model.py
git commit -m "feat(intel): earnings-quality red flag computation"
```

---

### Task 4: Shared datacenter pager (_dc.py)

**Files:**
- Create: `value_genie/intel/_dc.py`
- Test: `tests/test_intel_sources.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_intel_sources.py`:

```python
# ---------------------------------------------------------------------------
# dc_report paging helper (network mocked at the DC singleton)
# ---------------------------------------------------------------------------
import pandas as pd
import pytest

from value_genie.intel import _dc


def _dc_json(rows, count=None, pages=1):
    return {"result": {"count": count if count is not None else len(rows),
                       "pages": pages, "data": rows}}


class TestDcReport:
    def test_pages_and_merges(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params)
            if params["pageNumber"] == 1:
                return _dc_json([{"SECURITY_CODE": "600519"}],
                                count=700, pages=2)
            return _dc_json([{"SECURITY_CODE": "601318"}],
                            count=700, pages=2)

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        df = _dc.dc_report("RPT_TEST", ['(FREE_DATE>="2026-09-08")'])
        assert len(df) == 2
        assert len(calls) == 2
        assert calls[0]["filter"] == '(FREE_DATE>="2026-09-08")'
        assert calls[0]["reportName"] == "RPT_TEST"
        assert calls[0]["sortColumns"] == "SECURITY_CODE"

    def test_empty_window_returns_empty_df(self, monkeypatch):
        monkeypatch.setattr(
            _dc.DC, "get_json",
            lambda url, params=None, **kw: _dc_json([]))
        assert _dc.dc_report("RPT_TEST", []).empty

    def test_transport_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            _dc.DC, "get_json", lambda url, params=None, **kw: None)
        assert _dc.dc_report("RPT_TEST", []) is None

    def test_report_error_returns_none(self, monkeypatch):
        # "报表配置不存在"-shaped: HTTP 200 + success:false + result null
        monkeypatch.setattr(
            _dc.DC, "get_json",
            lambda url, params=None, **kw: {"success": False,
                                            "result": None})
        assert _dc.dc_report("RPT_TEST", []) is None

    def test_sort_columns_omitted_when_none(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([{"SCODE": "600519"}])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        _dc.dc_report("RPTA_WEB_GPHG", [], sort_columns=None)
        assert "sortColumns" not in seen    # probe rule: GPHG breaks on sort

    def test_code_col_prefers_security_code(self):
        df = pd.DataFrame({"SECURITY_CODE": ["600519"], "SCODE": ["x"]})
        assert list(_dc.code_col(df)) == ["600519"]
        df2 = pd.DataFrame({"SCODE": ["600519"]})
        assert list(_dc.code_col(df2)) == ["600519"]

    def test_name_col_tolerates_missing(self):
        df = pd.DataFrame({"SNAME": ["茅台"]})
        assert list(_dc.name_col(df)) == ["茅台"]
        assert _dc.name_col(pd.DataFrame({"X": [1]})) == ""

    def test_norm_dates(self):
        df = pd.DataFrame({"d": ["2026-09-12 00:00:00"], "x": [1]})
        out = _dc.norm_dates(df, "d")
        assert out["d"].iloc[0] == "2026-09-12"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_intel_sources.py -v
```

Expected: FAIL — `ModuleNotFoundError` / `ImportError` for `value_genie.intel._dc`.

- [ ] **Step 3: Implement _dc.py**

Create `value_genie/intel/_dc.py`:

```python
"""Shared Eastmoney datacenter paging helper for intel fetchers.

Eastmoney datacenter probe rules (verified 2026-09-09, design
appendix A):
1. String filter values MUST be double-quoted — single quotes trip an
   ANTLR InputMismatchException on some reports.
2. RPTA_WEB_GPHG must be fetched WITHOUT sortColumns/sortTypes
   ("SECURITY_CODE排序列不存在") — pass sort_columns=None.
3. A non-filterable field silently voids the whole filter and returns
   the FULL table — callers must re-filter rows in pandas and sanity
   check counts.
"""

import time

import pandas as pd

from .. import config
from ..fetch.http import DC


def dc_report(report_name: str, filters: list, *,
              page_size: int = None, sort_columns: str = "SECURITY_CODE",
              max_pages: int = 60, retries: int = 3,
              sleep_sec: float = 0.4, quiet: bool = True,
              label: str = "") -> pd.DataFrame | None:
    """Paged datacenter report fetch -> raw-row DataFrame.

    ``filters`` are ``(FIELD=value)`` chunks joined verbatim (the
    caller controls quoting). Returns None on transport failure or a
    report-level error ({"success": false}) so callers can mark the
    derived columns NaN (fail-closed, design §6.2); an empty DataFrame
    means a valid empty window.
    """
    page_size = page_size or config.A_PAGE_SIZE
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": "".join(filters),
        "pageSize": page_size,
        "source": "WEB",
        "client": "WEB",
    }
    if sort_columns:
        params["sortColumns"] = sort_columns
        params["sortTypes"] = "1"
    frames = []
    page = 1
    while page <= max_pages:
        raw = DC.get_json(config.DC_WEB_URL,
                          params={**params, "pageNumber": page},
                          retries=retries)
        if raw is None or raw.get("success") is False:
            return None
        result = raw.get("result") or {}
        rows = result.get("data") or []
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        if not quiet:
            print(f"    [{label}] page {page}: {len(rows)} rows")
        if page >= (result.get("pages") or 1):
            break
        page += 1
        time.sleep(sleep_sec)
    return (pd.concat(frames, ignore_index=True)
            if frames else pd.DataFrame())


def code_col(df: pd.DataFrame):
    """Security code series from a raw DC frame (SECURITY_CODE or SCODE)."""
    for c in ("SECURITY_CODE", "SCODE"):
        if c in df.columns:
            return df[c].astype(str)
    raise KeyError("no SECURITY_CODE/SCODE column in datacenter report")


def name_col(df: pd.DataFrame, default=""):
    """Display-name series, tolerant of per-report naming."""
    for c in ("SECURITY_NAME_ABBR", "SNAME"):
        if c in df.columns:
            return df[c].astype(str)
    return default


def norm_dates(df: pd.DataFrame, *cols) -> pd.DataFrame:
    """Trim datetime-ish columns to ISO dates (YYYY-MM-DD) so window
    comparisons stay lexical."""
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.slice(0, 10)
    return df
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -B -m pytest tests/test_intel_sources.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/_dc.py tests/test_intel_sources.py
git commit -m "feat(intel): shared datacenter paging helper"
```

---

### Task 5: A-share announcement event fetchers (announcements.py)

**Files:**
- Create: `value_genie/intel/announcements.py`
- Test: `tests/test_intel_sources.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_intel_sources.py`:

```python
# ---------------------------------------------------------------------------
# A-share announcement fetchers (解禁/增减持/回购/定增)
# ---------------------------------------------------------------------------
from value_genie.intel import announcements as ann


class TestFetchAUnlocks:
    def test_normalizes_rows(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "688795", "SECURITY_NAME_ABBR": "摩尔线程-U",
                "FREE_DATE": "2026-09-12 00:00:00",
                "TOTAL_RATIO": 0.12, "FREE_SHARES": 12345.6,
                "LIFT_MARKET_CAP": 50000.0, "NEW": 40.55}]))
        df = ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        assert df.iloc[0]["code"] == "688795"
        assert df.iloc[0]["name"] == "摩尔线程-U"
        assert df.iloc[0]["unlock_pct"] == pytest.approx(12.0)  # decimal -> %
        assert df.iloc[0]["free_date"] == "2026-09-12"
        assert df.iloc[0]["lift_cap_wan"] == 50000.0

    def test_filter_double_quotes(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        assert seen["filter"] == ('(FREE_DATE>="2026-09-08")'
                                  '(FREE_DATE<="2026-12-07")')

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json",
                            lambda url, params=None, **kw: None)
        assert ann.fetch_a_unlocks("2026-09-08", "2026-12-07") is None


class TestFetchAHolderChanges:
    def test_normalizes_rows(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "DIRECTION": "减持", "CHANGE_NUM": 100.5,
                "NOTICE_DATE": "2026-08-01 00:00:00",
                "END_DATE": "2026-11-01 00:00:00",
                "HOLDER_NAME": "某国资"}]))
        df = ann.fetch_a_holder_changes("2026-08-01")
        assert df.iloc[0]["direction"] == "减持"
        assert df.iloc[0]["change_num_wan"] == 100.5
        assert df.iloc[0]["notice_date"] == "2026-08-01"
        assert df.iloc[0]["end_date"] == "2026-11-01"
        assert df.iloc[0]["holder_name"] == "某国资"


class TestFetchABuybacks:
    def test_uses_scode_and_no_sort(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([{
                "SCODE": "000858", "SNAME": "五粮液",
                "HGJE": 5.0e8, "HGSL": 2.0e7,
                "GGRQ": "2026-09-01 00:00:00",
                "TDATE": "2026-09-01 00:00:00"}])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        df = ann.fetch_a_buybacks("2026-08-01")
        assert "sortColumns" not in seen        # probe rule 2
        assert seen["filter"] == '(GGRQ>="2026-08-01")'
        assert df.iloc[0]["code"] == "000858"   # SCODE -> code
        assert df.iloc[0]["amount_yuan"] == 5.0e8
        assert df.iloc[0]["shares"] == 2.0e7
        assert df.iloc[0]["announce_date"] == "2026-09-01"


class TestFetchAPlacements:
    def test_dilution_pct(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "ISSUE_DATE": "2026-08-15 00:00:00", "ISSUE_NUM": 1.0e7,
                "ISSUE_SHARE_BEFORE": 1.0e9, "ISSUE_SHARE_AFTER": 1.01e9,
                "NET_RAISE_FUNDS": 2.0e9, "SEO_TYPE": "定向增发"}]))
        df = ann.fetch_a_placements("2026-08-01")
        assert df.iloc[0]["dilution_pct"] == pytest.approx(1.0)
        assert df.iloc[0]["issue_date"] == "2026-08-15"
        assert df.iloc[0]["net_raise"] == 2.0e9
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_intel_sources.py -v
```

Expected: FAIL — `ImportError: cannot import name 'announcements'`.

- [ ] **Step 3: Implement announcements.py**

Create `value_genie/intel/announcements.py`:

```python
"""Announcements subsystem (P1: A-share batch event tables, design §4).

Each fetcher returns a normalized DataFrame (columns documented per
function) or None on source failure — the radar marks derived columns
NaN in that case (fail-closed). Date columns are normalized to ISO so
window comparisons stay lexical.
"""

import pandas as pd

from .. import config
from ._dc import code_col, dc_report, name_col, norm_dates


def fetch_a_unlocks(start: str, end: str,
                    quiet: bool = True) -> pd.DataFrame | None:
    """解禁时间表 RPT_LIFT_STAGE，窗口 [start, end]（ISO 日期）。

    Columns: code, name, free_date (ISO), unlock_pct (解禁股/总股本 %,
    TOTAL_RATIO 是小数，×100), lift_cap_wan (解禁市值，万元).
    """
    df = dc_report(config.A_UNLOCK_REPORT_NAME,
                   [f'(FREE_DATE>="{start}")', f'(FREE_DATE<="{end}")'],
                   quiet=quiet, label="A unlocks")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "free_date": df["FREE_DATE"],
        "unlock_pct": pd.to_numeric(df["TOTAL_RATIO"],
                                    errors="coerce") * 100.0,
        "lift_cap_wan": pd.to_numeric(df["LIFT_MARKET_CAP"],
                                      errors="coerce"),
    })
    return norm_dates(out, "free_date")


def fetch_a_holder_changes(since: str,
                           quiet: bool = True) -> pd.DataFrame | None:
    """股东增减持 RPT_SHARE_HOLDER_INCREASE，公告日 >= since。

    Columns: code, name, direction ("减持"/"增持"), change_num_wan (万股),
    notice_date/end_date (ISO，END_DATE 为减持窗口截止，可空),
    holder_name.
    """
    df = dc_report(config.A_HOLDER_REPORT_NAME,
                   [f'(NOTICE_DATE>="{since}")'],
                   quiet=quiet, label="A holder changes")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "direction": df["DIRECTION"].astype(str),
        "change_num_wan": pd.to_numeric(df["CHANGE_NUM"],
                                        errors="coerce"),
        "notice_date": df["NOTICE_DATE"],
        "end_date": df["END_DATE"],
        "holder_name": (df["HOLDER_NAME"].astype(str)
                        if "HOLDER_NAME" in df.columns else ""),
    })
    return norm_dates(out, "notice_date", "end_date")


def fetch_a_buybacks(since: str,
                     quiet: bool = True) -> pd.DataFrame | None:
    """回购 RPTA_WEB_GPHG，公告日 (GGRQ) >= since。

    该报表用 SCODE/SNAME 且不可带 sortColumns（探针铁律 2）。
    Columns: code, name, amount_yuan (HGJE，元), shares (HGSL，股),
    announce_date (GGRQ, ISO).
    """
    df = dc_report(config.A_BUYBACK_REPORT_NAME,
                   [f'(GGRQ>="{since}")'],
                   sort_columns=None,     # probe rule: GPHG 无该排序列
                   quiet=quiet, label="A buybacks")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "amount_yuan": pd.to_numeric(df["HGJE"], errors="coerce"),
        "shares": (pd.to_numeric(df["HGSL"], errors="coerce")
                   if "HGSL" in df.columns else None),
        "announce_date": df["GGRQ"],
    })
    return norm_dates(out, "announce_date")


def fetch_a_placements(since: str,
                       quiet: bool = True) -> pd.DataFrame | None:
    """定增 RPT_SEO_DETAIL，发行日 (ISSUE_DATE) >= since。

    P1 语义：dilution_flag = 回看窗口内**已完成**的定增（进行中的
    预案在另一张报表，后续阶段接入）。
    Columns: code, name, issue_date (ISO), issue_num, net_raise (元),
    dilution_pct ((after-before)/before %), seo_type.
    """
    df = dc_report(config.A_PLACEMENT_REPORT_NAME,
                   [f'(ISSUE_DATE>="{since}")'],
                   quiet=quiet, label="A placements")
    if df is None:
        return None
    if df.empty:
        return df
    before = pd.to_numeric(df["ISSUE_SHARE_BEFORE"], errors="coerce")
    after = pd.to_numeric(df["ISSUE_SHARE_AFTER"], errors="coerce")
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "issue_date": df["ISSUE_DATE"],
        "issue_num": pd.to_numeric(df["ISSUE_NUM"], errors="coerce"),
        "net_raise": pd.to_numeric(df["NET_RAISE_FUNDS"],
                                   errors="coerce"),
        "dilution_pct": (after - before) / before * 100.0,
        "seo_type": (df["SEO_TYPE"].astype(str)
                     if "SEO_TYPE" in df.columns else ""),
    })
    return norm_dates(out, "issue_date")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -B -m pytest tests/test_intel_sources.py -v
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/announcements.py tests/test_intel_sources.py
git commit -m "feat(intel): A-share announcement event fetchers"
```

---

### Task 6: A-share earnings event fetchers + deduct EPS fields

**Files:**
- Create: `value_genie/intel/earnings.py`
- Modify: `value_genie/fetch/fundamentals.py` (`A_FIELD_MAP` + `_parse_lico` numeric loop)
- Test: `tests/test_intel_sources.py` (append), `tests/test_fundamentals.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_intel_sources.py`:

```python
# ---------------------------------------------------------------------------
# A-share earnings fetchers (业绩预告/披露预约/资产负债表)
# ---------------------------------------------------------------------------
from value_genie.intel import earnings as ear


class TestFetchAForecasts:
    def test_normalizes_rows_and_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "PREDICT_TYPE": "首亏", "INCREASE_JZ": -120.0,
                "NOTICE_DATE": "2026-08-30 00:00:00"}])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        df = ear.fetch_a_forecasts("2026-08-01")
        assert seen["filter"] == ('(NOTICE_DATE>="2026-08-01")'
                                  '(IS_LATEST="T")')
        assert df.iloc[0]["predict_type"] == "首亏"
        assert df.iloc[0]["change_pct"] == -120.0
        assert df.iloc[0]["notice_date"] == "2026-08-30"


class TestFetchAAppointments:
    def test_normalizes_rows(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "APPOINT_PUBLISH_DATE": "2026-10-28 00:00:00",
                "IS_PUBLISH": "0", "REPORT_TYPE_NAME": "三季报"}]))
        df = ear.fetch_a_appointments("2026-09-08", "2026-12-07")
        assert df.iloc[0]["appoint_date"] == "2026-10-28"
        assert df.iloc[0]["is_published"] == "0"
        assert df.iloc[0]["report_type"] == "三季报"

    def test_empty_window_is_valid(self, monkeypatch):
        # 三季报预约 9 月末才挂出：未来窗口为空是正常时序，不是失败
        monkeypatch.setattr(_dc.DC, "get_json",
                            lambda url, params=None, **kw: _dc_json([]))
        assert ear.fetch_a_appointments("2026-09-08",
                                        "2026-12-07").empty


class TestFetchABalance:
    def test_normalizes_yoy_columns(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519",
                "ACCOUNTS_RECE_RATIO": 58.0, "INVENTORY_RATIO": 12.0,
                "ACCOUNTS_RECE": 1.0e9, "INVENTORY": 2.0e9}]))
        df = ear.fetch_a_balance("2026-06-30")
        assert df.iloc[0]["rece_yoy"] == 58.0   # YoY %, 非占比（已探针验证）
        assert df.iloc[0]["inv_yoy"] == 12.0
        assert df.iloc[0]["receivable"] == 1.0e9
        assert df.iloc[0]["report_date"] == "2026-06-30"
```

Append to `tests/test_fundamentals.py`:

```python
class TestParseLicoDeductEPS:
    def test_maps_deduct_and_basic_eps(self):
        d = {"result": {"data": [{
            "SECURITY_CODE": "600519", "REPORTDATE": "2026-06-30 00:00:00",
            "TOTAL_OPERATE_INCOME": 1e10, "YSTZ": 15.0,
            "PARENT_NETPROFIT": 1.5e9, "SJLTZ": 18.0,
            "WEIGHTAVG_ROE": 15.0, "XSMLL": 50.0, "BPS": 30.0,
            "DEDUCT_BASIC_EPS": 2.1, "BASIC_EPS": 3.0}]}}
        df = f._parse_lico(d)
        assert df.iloc[0]["deduct_eps"] == 2.1
        assert df.iloc[0]["basic_eps"] == 3.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_intel_sources.py tests/test_fundamentals.py -v
```

Expected: FAIL — `ImportError: cannot import name 'earnings'` and the deduct EPS assert fails.

- [ ] **Step 3: Implement earnings.py**

Create `value_genie/intel/earnings.py`:

```python
"""Earnings subsystem (P1: A-share forecast / appointment / balance
batch tables, design §4)."""

import pandas as pd

from .. import config
from ._dc import code_col, dc_report, name_col, norm_dates


def fetch_a_forecasts(since: str,
                      quiet: bool = True) -> pd.DataFrame | None:
    """业绩预告 RPT_PUBLIC_OP_NEWPREDICT，最新公告 (IS_LATEST=T) 且
    NOTICE_DATE >= since。

    Columns: code, name, predict_type (预增/预减/首亏/扭亏…),
    change_pct (INCREASE_JZ 幅度), notice_date (ISO).
    """
    df = dc_report(config.A_FORECAST_REPORT_NAME,
                   [f'(NOTICE_DATE>="{since}")', '(IS_LATEST="T")'],
                   quiet=quiet, label="A forecasts")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "predict_type": df["PREDICT_TYPE"].astype(str),
        "change_pct": pd.to_numeric(df["INCREASE_JZ"], errors="coerce"),
        "notice_date": df["NOTICE_DATE"],
    })
    return norm_dates(out, "notice_date")


def fetch_a_appointments(start: str, end: str,
                         quiet: bool = True) -> pd.DataFrame | None:
    """披露预约 RPT_PUBLIC_BS_APPOIN，预约日窗口 [start, end]。

    空窗口是正常时序（三季报预约 9 月末才挂出），不是接口失败。
    Columns: code, name, appoint_date (ISO), is_published ("0"=未披露),
    report_type.
    """
    df = dc_report(config.A_APPOINT_REPORT_NAME,
                   [f'(APPOINT_PUBLISH_DATE>="{start}")',
                    f'(APPOINT_PUBLISH_DATE<="{end}")'],
                   quiet=quiet, label="A appointments")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "name": name_col(df),
        "appoint_date": df["APPOINT_PUBLISH_DATE"],
        "is_published": (df["IS_PUBLISH"].astype(str)
                         if "IS_PUBLISH" in df.columns else ""),
        "report_type": (df["REPORT_TYPE_NAME"].astype(str)
                        if "REPORT_TYPE_NAME" in df.columns else ""),
    })
    return norm_dates(out, "appoint_date")


def fetch_a_balance(report_date: str,
                    quiet: bool = True) -> pd.DataFrame | None:
    """资产负债表批表 RPT_DMSK_FN_BALANCE（全市场约 5.6k 行）。

    ACCOUNTS_RECE_RATIO / INVENTORY_RATIO = 应收/存货 YoY 增速 %
    （TCL/长安/比亚迪三股交叉验证，非占比）；该表无商誉字段
    （eq_goodwill 推迟，设计 §5）。
    Columns: code, rece_yoy, inv_yoy, receivable, inventory,
    report_date.
    """
    df = dc_report(config.A_BALANCE_REPORT_NAME,
                   [f'(REPORT_DATE="{report_date}")'],
                   quiet=quiet, label="A balance")
    if df is None:
        return None
    if df.empty:
        return df
    out = pd.DataFrame({
        "code": code_col(df),
        "rece_yoy": pd.to_numeric(df["ACCOUNTS_RECE_RATIO"],
                                  errors="coerce"),
        "inv_yoy": pd.to_numeric(df["INVENTORY_RATIO"],
                                 errors="coerce"),
        "receivable": pd.to_numeric(df["ACCOUNTS_RECE"],
                                    errors="coerce"),
        "inventory": pd.to_numeric(df["INVENTORY"], errors="coerce"),
    })
    out["report_date"] = report_date
    return out
```

- [ ] **Step 4: Extend A_FIELD_MAP in fundamentals.py**

In `value_genie/fetch/fundamentals.py`, extend the map and the numeric loop:

```python
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
    "DEDUCT_BASIC_EPS": "deduct_eps",   # 扣非每股（eq_nonrecurring 用）
    "BASIC_EPS": "basic_eps",           # 基本每股
}
```

And in `_parse_lico`, extend the numeric conversion tuple:

```python
    for col in ("revenue", "rev_yoy", "profit", "profit_yoy", "roe",
                "gross_margin", "bps", "deduct_eps", "basic_eps"):
```

(The loop's `if col in df.columns` guard already handles old rows lacking the fields — reused same-day CSVs from before this change simply carry no deduct_eps, and earnings_quality skips the signal.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -B -m pytest tests/test_intel_sources.py tests/test_fundamentals.py -v
```

Expected: all pass (23 in test_intel_sources + existing fundamentals tests + 1 new).

- [ ] **Step 6: Commit**

```bash
git add value_genie/intel/earnings.py value_genie/fetch/fundamentals.py tests/test_intel_sources.py tests/test_fundamentals.py
git commit -m "feat(intel): A-share earnings event fetchers + deduct EPS fields"
```

---

### Task 7: Event radar core (radar.py)

**Files:**
- Create: `value_genie/intel/radar.py`
- Test: `tests/test_intel_radar.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_intel_radar.py`:

```python
"""Tests for value_genie.intel.radar (no network)."""

from datetime import date, timedelta

import pandas as pd

from value_genie.intel import radar


def _snap(tmp_path, fins=None, cfs=None):
    snap = tmp_path / "snapshots" / date.today().strftime("%Y%m%d")
    snap.mkdir(parents=True)
    pd.DataFrame(fins if fins is not None else [
        {"code": "600519", "report_date": "2026-06-30", "revenue": 1e10,
         "rev_yoy": 15.0, "profit": 1.5e9, "roe": 15.0,
         "gross_margin": 50.0},
        {"code": "000858", "report_date": "2026-06-30", "revenue": 5e9,
         "rev_yoy": 10.0, "profit": 8e8, "roe": 12.0,
         "gross_margin": 45.0},
    ]).to_csv(snap / "a_financials.csv", index=False)
    if cfs is not None:
        pd.DataFrame(cfs).to_csv(snap / "a_cashflow.csv", index=False)
    return snap


def _master(codes=("600519", "000858")):
    return pd.DataFrame({"market": "A", "code": list(codes),
                         "name": [f"N{c}" for c in codes]})


def _stub_empty(monkeypatch, **overrides):
    """Patch every radar fetcher to an empty table unless overridden."""
    def empty(*a, **k):
        return pd.DataFrame()

    for name in ("fetch_a_unlocks", "fetch_a_holder_changes",
                 "fetch_a_buybacks", "fetch_a_placements",
                 "fetch_a_forecasts", "fetch_a_appointments",
                 "fetch_a_balance"):
        if name not in overrides:
            monkeypatch.setattr(radar, name, empty)
    for name, fn in overrides.items():
        monkeypatch.setattr(radar, name, fn)


def test_unlock_windows_and_red_flag(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    d60 = (date.today() + timedelta(days=60)).isoformat()
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: pd.DataFrame([
        {"code": "600519", "name": "A", "free_date": d10,
         "unlock_pct": 8.0, "lift_cap_wan": 1e6},
        {"code": "600519", "name": "A", "free_date": d60,
         "unlock_pct": 4.0, "lift_cap_wan": 5e5},
    ]))
    out = radar.build_event_radar(snap, _master(), None)
    row = out[out["code"] == "600519"].iloc[0]
    assert row["unlock_pct_30d"] == 8.0
    assert row["unlock_pct_90d"] == 12.0           # 8 + 4 累加
    assert row["intel_red"] == 1.0                 # 30d >= 5%
    r858 = out[out["code"] == "000858"].iloc[0]
    assert r858["unlock_pct_30d"] == 0.0           # 无事件 = 正面确认 0
    assert r858["intel_red"] == 0.0


def test_source_failure_is_nan_fail_closed(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: None)
    out = radar.build_event_radar(snap, _master(), None)
    row = out.iloc[0]
    assert pd.isna(row["unlock_pct_30d"])
    assert pd.isna(row["unlock_pct_90d"])
    assert pd.isna(row["intel_red"])       # 无法确认无红旗 -> NaN
    assert row["holder_cut_flag"] == 0.0   # 其余源仍为正面确认


def test_holder_cut_ongoing_window(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_holder_changes=lambda s: pd.DataFrame([
        # 进行中减持（end_date 在未来）-> flag
        {"code": "600519", "name": "A", "direction": "减持",
         "change_num_wan": 10.0, "notice_date": "2026-08-01",
         "end_date": (date.today() + timedelta(days=5)).isoformat(),
         "holder_name": "H1"},
        # 已截止减持（end_date 在过去）-> 不 flag
        {"code": "000858", "name": "B", "direction": "减持",
         "change_num_wan": 10.0, "notice_date": "2026-08-01",
         "end_date": (date.today() - timedelta(days=1)).isoformat(),
         "holder_name": "H2"},
        # 增持永不 flag
        {"code": "600519", "name": "A", "direction": "增持",
         "change_num_wan": 10.0, "notice_date": "2026-08-01",
         "end_date": (date.today() + timedelta(days=5)).isoformat(),
         "holder_name": "H3"},
    ]))
    out = radar.build_event_radar(snap, _master(), None)
    assert out[out["code"] == "600519"].iloc[0]["holder_cut_flag"] == 1.0
    assert out[out["code"] == "000858"].iloc[0]["holder_cut_flag"] == 0.0
    assert out[out["code"] == "600519"].iloc[0]["intel_red"] == 1.0


def test_dilution_and_buyback_flags(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch,
        fetch_a_placements=lambda s: pd.DataFrame([
            {"code": "600519", "name": "A", "issue_date": "2026-08-15",
             "issue_num": 1e7, "net_raise": 2e9, "dilution_pct": 1.0,
             "seo_type": "定向增发"}]),
        fetch_a_buybacks=lambda s: pd.DataFrame([
            {"code": "000858", "name": "B", "amount_yuan": 5e8,
             "shares": 2e7, "announce_date": "2026-09-01"}]))
    out = radar.build_event_radar(snap, _master(), None)
    assert out[out["code"] == "600519"].iloc[0]["dilution_flag"] == 1.0
    assert out[out["code"] == "000858"].iloc[0]["buyback_active"] == 1.0
    # 回购是正面信号：不触发 intel_red
    assert out[out["code"] == "000858"].iloc[0]["intel_red"] == 0.0


def test_report_due_and_forecast_direction(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d20 = (date.today() + timedelta(days=20)).isoformat()
    _stub_empty(monkeypatch,
        fetch_a_appointments=lambda s, e: pd.DataFrame([
            {"code": "600519", "name": "A", "appoint_date": d20,
             "is_published": "0", "report_type": "三季报"},
            {"code": "000858", "name": "B", "appoint_date": d20,
             "is_published": "1", "report_type": "三季报"},  # 已披露->忽略
        ]),
        fetch_a_forecasts=lambda s: pd.DataFrame([
            {"code": "600519", "name": "A", "predict_type": "首亏",
             "change_pct": -120.0, "notice_date": "2026-08-30"}]))
    out = radar.build_event_radar(snap, _master(), None)
    assert out[out["code"] == "600519"].iloc[0]["report_due_days"] == 20
    assert out[out["code"] == "000858"].iloc[0]["report_due_days"] == 999
    assert out[out["code"] == "600519"].iloc[0]["forecast_flag"] == -1
    assert out[out["code"] == "000858"].iloc[0]["forecast_flag"] == 0.0


def test_eq_flags_from_snapshot_financials(tmp_path, monkeypatch):
    snap = _snap(tmp_path, cfs=[{"code": "600519", "ocf": 1e8},
                                {"code": "000858", "ocf": 9e8}])
    _stub_empty(monkeypatch, fetch_a_balance=lambda rd: pd.DataFrame([
        {"code": "600519", "rece_yoy": 40.0, "inv_yoy": 5.0,
         "receivable": 1e9, "inventory": 1e9, "report_date": rd},
        {"code": "000858", "rece_yoy": 12.0, "inv_yoy": 11.0,
         "receivable": 1e8, "inventory": 1e8, "report_date": rd},
    ]))
    out = radar.build_event_radar(snap, _master(), None)
    # 600519: 应收 40 > 15+10 -> eq_receivables; OCF/净利 0.067 < 0.5 -> eq_ocf_gap
    assert out[out["code"] == "600519"].iloc[0]["eq_flags"] == 2
    r858 = out[out["code"] == "000858"].iloc[0]
    assert r858["eq_flags"] == 0      # 12 < 20; OCF/净利 1.125
    assert r858["intel_red"] == 0.0   # eq 2 < EQ_FLAG_RED=3


def test_eq_nan_when_balance_fails(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_balance=lambda rd: None)
    out = radar.build_event_radar(snap, _master(), None)
    assert pd.isna(out.iloc[0]["eq_flags"])
    assert pd.isna(out.iloc[0]["intel_red"])
    assert out.iloc[0]["unlock_pct_30d"] == 0.0   # 其余列不受影响


def test_event_radar_detail_csv(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    _stub_empty(monkeypatch,
        fetch_a_unlocks=lambda s, e: pd.DataFrame([
            {"code": "600519", "name": "A", "free_date": d10,
             "unlock_pct": 8.0, "lift_cap_wan": 1e6}]),
        fetch_a_holder_changes=lambda s: pd.DataFrame([
            {"code": "000858", "name": "B", "direction": "减持",
             "change_num_wan": 100.0, "notice_date": "2026-08-01",
             "end_date": date.today().isoformat(), "holder_name": "H"}]))
    out = radar.build_event_radar(snap, _master(), None)
    detail = pd.read_csv(snap / "event_radar.csv", dtype={"code": str})
    kinds = dict(zip(detail["code"], detail["kind"]))
    assert kinds["600519"] == "unlock"
    assert kinds["000858"] == "holder_cut"
    u = detail[detail["kind"] == "unlock"].iloc[0]
    assert u["impact"] == "negative"
    assert u["subsystem"] == "announcements"
    import json
    assert json.loads(u["payload"])["unlock_pct"] == 8.0


def test_detail_rows_scoped_to_universe(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: pd.DataFrame([
        {"code": "600519", "name": "A", "free_date": d10,
         "unlock_pct": 8.0, "lift_cap_wan": 1e6},
        {"code": "601398", "name": "NotInUniverse", "free_date": d10,
         "unlock_pct": 3.0, "lift_cap_wan": 1e5}]))
    radar.build_event_radar(snap, _master(), None)
    detail = pd.read_csv(snap / "event_radar.csv", dtype={"code": str})
    assert set(detail["code"]) == {"600519"}   # 非候选股不进明细


def test_same_day_rerun_reuses_saved_tables(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    calls = []

    def unlock_fetch(s, e):
        calls.append(1)
        return pd.DataFrame([
            {"code": "600519", "name": "A", "free_date": d10,
             "unlock_pct": 8.0, "lift_cap_wan": 1e6}])

    _stub_empty(monkeypatch, fetch_a_unlocks=unlock_fetch)
    radar.build_event_radar(snap, _master(), None)
    out2 = radar.build_event_radar(snap, _master(), None)
    assert len(calls) == 1                      # 当日表落盘后被复用
    assert out2[out2["code"] == "600519"].iloc[0][
        "unlock_pct_30d"] == 8.0


def test_non_a_universe_writes_empty_detail(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    master = pd.DataFrame({"market": ["US"], "code": ["AAPL"]})
    called = []

    def unlock_fetch(s, e):
        called.append(1)
        return pd.DataFrame()

    _stub_empty(monkeypatch, fetch_a_unlocks=unlock_fetch)
    out = radar.build_event_radar(snap, master, None)
    assert out is None                       # 无 A 覆盖 -> 不合并
    assert not called                        # 不发起任何 A 股抓取
    assert (snap / "event_radar.csv").exists()


def test_watchlist_codes_join_the_universe(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: pd.DataFrame([
        {"code": "688795", "name": "摩尔线程-U", "free_date": d10,
         "unlock_pct": 12.0, "lift_cap_wan": 2e5}]))
    master = _master()                       # 漏斗内的 600519/000858
    watch = pd.DataFrame({"market": ["A"], "code": ["688795"],
                          "name": ["摩尔线程-U"]})
    out = radar.build_event_radar(snap, master, watch)
    row = out[out["code"] == "688795"].iloc[0]   # 持仓进雷达覆盖
    assert row["unlock_pct_30d"] == 12.0
    assert row["intel_red"] == 1.0


def test_merge_radar_no_duplicate_columns():
    master = pd.DataFrame({"market": ["A", "HK"],
                           "code": ["600519", "00700"],
                           "price": [10.0, 20.0]})
    # 模拟 build_master reindex 已经补出的 NaN 雷达列
    for c in radar.RADAR_COLUMNS:
        master[c] = float("nan")
    radar_df = pd.DataFrame(
        {"market": ["A"], "code": ["600519"],
         **{c: [0.0] for c in radar.RADAR_COLUMNS}})
    out = radar.merge_radar(master, radar_df)
    assert "unlock_pct_30d_x" not in out.columns     # 无 _x/_y 重复列
    assert out[out["code"] == "600519"].iloc[0][
        "unlock_pct_30d"] == 0.0
    assert pd.isna(out[out["code"] == "00700"].iloc[0][
        "unlock_pct_30d"])                          # 未覆盖市场 = NaN


def test_source_failures_recorded_in_manifest(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: None,
                fetch_a_buybacks=lambda s: None)
    manifest = {"datasets": {}, "failures": []}
    radar.build_event_radar(snap, _master(), None, manifest=manifest)
    assert any("A unlocks" in f for f in manifest["failures"])
    assert any("A buybacks" in f for f in manifest["failures"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_intel_radar.py -v
```

Expected: FAIL — `ImportError: cannot import name 'radar'`.

- [ ] **Step 3: Implement radar.py**

Create `value_genie/intel/radar.py`:

```python
"""Event radar: full-market A-share event tables -> per-stock risk
columns merged into master.csv / watchlist.csv (design 2026-09-08 §6).

Batch channel of the intel subsystem, runs at the tail of run_fetch.
Semantics: no event = 0.0 (positive confirmation); only a failed
source yields NaN so gates fail-closed on missing data only. P1 covers
A-shares; HK/US rows keep NaN until P3.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from . import model
from .announcements import (fetch_a_buybacks, fetch_a_holder_changes,
                            fetch_a_placements, fetch_a_unlocks)
from .earnings import (fetch_a_appointments, fetch_a_balance,
                       fetch_a_forecasts)

RADAR_COLUMNS = [
    "unlock_pct_30d", "unlock_pct_90d", "holder_cut_flag", "dilution_flag",
    "buyback_active", "report_due_days", "forecast_flag", "eq_flags",
    "intel_red",
]

DETAIL_FILE = "event_radar.csv"


# ---------------------------------------------------------------------------
# Merge helper (pipeline-facing)
# ---------------------------------------------------------------------------
def merge_radar(df: pd.DataFrame, radar: pd.DataFrame) -> pd.DataFrame:
    """Left-join radar columns onto a master/watchlist frame.

    The NaN radar columns that build_master/build_watchlist reindex
    added are dropped first, so the merge never creates _x/_y
    duplicates; the final column order matches MASTER_COLUMNS (radar
    columns are its tail).
    """
    drop = [c for c in radar.columns
            if c in df.columns and c not in ("market", "code")]
    out = df.drop(columns=drop)
    return out.merge(radar, on=["market", "code"], how="left")


# ---------------------------------------------------------------------------
# Per-table aggregations (None table -> NaN column, fail-closed)
# ---------------------------------------------------------------------------
def _agg_unlock(unlocks, asof: date, days: int, codes: pd.Index):
    """Summed unlock % of total shares over (asof, asof+days]."""
    if unlocks is None:
        return None
    end = (asof + timedelta(days=days)).isoformat()
    w = unlocks[(unlocks["free_date"] > asof.isoformat())
                & (unlocks["free_date"] <= end)]
    s = w.groupby("code")["unlock_pct"].sum()
    return s.reindex(codes).fillna(0.0)


def _agg_flag(table, mask_fn, codes):
    """0/1 per code: 1 when any table row matches mask_fn."""
    if table is None:
        return None
    hit = table[mask_fn(table)]
    s = pd.Series(1.0, index=pd.Index(sorted(set(hit["code"])),
                                       name="code"))
    return s.reindex(codes).fillna(0.0)


def _holder_cut_mask(asof: date):
    """减持 + 窗口未截止（end_date 缺失视为进行中，宁可误报）。"""
    def mask(df):
        end = df["end_date"]
        ongoing = end.isna() | (end >= asof.isoformat())
        return (df["direction"] == "减持") & ongoing
    return mask


def _any_mask(df):
    return pd.Series(True, index=df.index)


def _agg_report_due(appoints, asof: date, codes):
    """Days to the next unpublished appointment; 999 = none in window."""
    if appoints is None:
        return None
    fut = appoints[(appoints["appoint_date"] > asof.isoformat())
                   & (appoints["is_published"].astype(str) == "0")]
    if fut.empty:
        return pd.Series(999.0, index=codes)
    due = (pd.to_datetime(fut["appoint_date"]) - pd.Timestamp(asof)).dt.days
    s = fut.assign(due=due).groupby("code")["due"].min()
    return s.reindex(codes).fillna(999.0)


def _agg_forecast(forecasts, codes):
    """Direction of the latest forecast notice per code (-1/0/1)."""
    if forecasts is None:
        return None
    if forecasts.empty:
        return pd.Series(0.0, index=codes)
    latest = (forecasts.sort_values("notice_date")
              .groupby("code").tail(1))
    s = latest.set_index("code")["predict_type"].map(
        lambda t: model.FORECAST_DIRECTION.get(str(t), 0))
    return s.reindex(codes).fillna(0.0)


# ---------------------------------------------------------------------------
# Earnings-quality inputs (snapshot files + balance batch table)
# ---------------------------------------------------------------------------
def _read_csv(path: Path):
    try:
        df = pd.read_csv(path, dtype={"code": str})
        return df if not df.empty else None
    except (OSError, pd.errors.ParserError, ValueError):
        return None


def _report_date_of(snap_dir: Path):
    """Modal report_date of a_financials.csv (= the chosen period)."""
    fin = _read_csv(snap_dir / "a_financials.csv")
    if fin is None or "report_date" not in fin.columns:
        return None
    try:
        return str(fin["report_date"].mode().iloc[0])
    except IndexError:
        return None


def _eq_records(snap_dir: Path, balance):
    """{code: earnings_quality input rec} from snapshot financials.

    None when the balance batch failed — eq_flags then goes NaN for
    all stocks (fail-closed, design §6.2). Stocks missing rows in any
    input simply trigger fewer signals.
    """
    if balance is None:
        return None
    fin = _read_csv(snap_dir / "a_financials.csv")
    if fin is None:
        return None
    m = fin.drop_duplicates(subset="code")
    cf = _read_csv(snap_dir / "a_cashflow.csv")
    if cf is not None and "ocf" in cf.columns:
        m = m.merge(cf[["code", "ocf"]].drop_duplicates(subset="code"),
                    on="code", how="left")
    m = m.merge(balance[["code", "rece_yoy", "inv_yoy"]]
                .drop_duplicates(subset="code"), on="code", how="left")
    cols = [c for c in ("rev_yoy", "profit", "ocf", "deduct_eps",
                        "basic_eps", "rece_yoy", "inv_yoy")
            if c in m.columns]
    return m.set_index("code")[cols].to_dict("index")


# ---------------------------------------------------------------------------
# Detail (IntelItem) builders — universe-scoped
# ---------------------------------------------------------------------------
def _iso(v) -> date:
    return date.fromisoformat(str(v)[:10])


def _num(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def _unlock_items(unlocks, codes) -> list:
    if unlocks is None or unlocks.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in unlocks.iterrows():
        if str(r["code"]) not in uni:
            continue
        pct = r["unlock_pct"]
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind="unlock",
            event_date=_iso(r["free_date"]),
            title=(f"限售解禁 {pct:.1f}% 总股本"
                   if pd.notna(pct) else "限售解禁"),
            source="eastmoney", impact=model.IMPACT_BY_KIND["unlock"],
            payload={"unlock_pct": _num(pct),
                     "lift_cap_wan": _num(r.get("lift_cap_wan"))}))
    return items


def _holder_items(holders, codes) -> list:
    if holders is None or holders.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in holders.iterrows():
        if str(r["code"]) not in uni:
            continue
        kind = "holder_cut" if r["direction"] == "减持" else "holder_add"
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind=kind,
            event_date=_iso(r["notice_date"]),
            title=(f"股东{r['direction']} "
                   f"{r.get('holder_name') or ''}").strip(),
            source="eastmoney", impact=model.IMPACT_BY_KIND[kind],
            payload={"direction": str(r["direction"]),
                     "change_num_wan": _num(r.get("change_num_wan")),
                     "end_date": (None if pd.isna(r.get("end_date"))
                                  else str(r["end_date"]))}))
    return items


def _buyback_items(buybacks, codes) -> list:
    if buybacks is None or buybacks.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in buybacks.iterrows():
        if str(r["code"]) not in uni:
            continue
        amt = r.get("amount_yuan")
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind="buyback",
            event_date=_iso(r["announce_date"]),
            title=("回购" + (f" {amt / 1e8:.2f} 亿元"
                           if pd.notna(amt) else "")),
            source="eastmoney", impact=model.IMPACT_BY_KIND["buyback"],
            payload={"amount_yuan": _num(amt),
                     "shares": _num(r.get("shares"))}))
    return items


def _placement_items(placements, codes) -> list:
    if placements is None or placements.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in placements.iterrows():
        if str(r["code"]) not in uni:
            continue
        dil = r.get("dilution_pct")
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind="placement",
            event_date=_iso(r["issue_date"]),
            title=("定增发行" + (f" 稀释 {dil:.1f}%"
                                if pd.notna(dil) else "")),
            source="eastmoney", impact=model.IMPACT_BY_KIND["placement"],
            payload={"dilution_pct": _num(dil),
                     "net_raise": _num(r.get("net_raise")),
                     "seo_type": str(r.get("seo_type") or "")}))
    return items


def _forecast_items(forecasts, codes) -> list:
    if forecasts is None or forecasts.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in forecasts.iterrows():
        if str(r["code"]) not in uni:
            continue
        t = str(r["predict_type"])
        direction = model.FORECAST_DIRECTION.get(t, 0)
        kind = {1: "forecast_up", -1: "forecast_down"}.get(
            direction, "forecast_flat")
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="earnings", kind=kind,
            event_date=_iso(r["notice_date"]),
            title=f"业绩预告: {t}",
            source="eastmoney", impact=model.IMPACT_BY_KIND[kind],
            payload={"predict_type": t,
                     "change_pct": _num(r.get("change_pct"))}))
    return items


def _appointment_items(appoints, codes) -> list:
    if appoints is None or appoints.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in appoints.iterrows():
        if str(r["code"]) not in uni:
            continue
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="earnings", kind="report_date",
            event_date=_iso(r["appoint_date"]),
            title=f"财报披露预约: {r.get('report_type') or ''}",
            source="eastmoney",
            impact=model.IMPACT_BY_KIND["report_date"],
            payload={"is_published": str(r.get("is_published") or ""),
                     "report_type": str(r.get("report_type") or "")}))
    return items


def _eq_items(eq_recs, fin_rd, codes) -> list:
    if not eq_recs:
        return []
    items = []
    for code in codes:
        rec = eq_recs.get(str(code), {})
        for flag in model.earnings_quality(rec):
            items.append(model.IntelItem(
                market="A", code=str(code), name="",
                subsystem="earnings", kind="eq_flag",
                event_date=(_iso(fin_rd) if fin_rd else date.today()),
                title=f"财报粉饰信号: {flag}",
                source="snapshot",
                impact=model.IMPACT_BY_KIND["eq_flag"],
                payload={"signal": flag}))
    return items


def _write_detail(snap: Path, items) -> None:
    df = pd.DataFrame([model.item_to_row(i) for i in items],
                      columns=model.DETAIL_COLUMNS)
    df.to_csv(snap / DETAIL_FILE, index=False)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _load_or_fetch(path: Path, fetcher, label: str, refresh: bool, log):
    """Snapshot resume convention: reuse today's saved table unless
    refresh (design §6.1). A raising fetcher degrades to None."""
    if not refresh and path.exists():
        try:
            df = pd.read_csv(path, dtype={"code": str})
            if not df.empty:
                log(f"    [{label}] reused {len(df)} rows from today")
                return df
        except (OSError, pd.errors.ParserError, ValueError):
            pass
    try:
        df = fetcher()
    except Exception as e:  # noqa: BLE001 — one bad report must not
        print(f"    [{label}] fetch error: {e}",   # kill the whole fetch
              file=sys.stderr)
        df = None
    if df is not None and not df.empty:
        df.to_csv(path, index=False)
    return df


def build_event_radar(snap_dir, master, watch, manifest=None,
                      refresh: bool = False, quiet: bool = False,
                      asof: date | None = None):
    """A-share event radar for the master + watchlist universe.

    Returns a frame [market, code, RADAR_COLUMNS] for the pipeline to
    merge into master.csv / watchlist.csv, or None when there is
    nothing to merge (no A universe / radar failed outright — columns
    stay NaN, fail-closed). Writes event_radar.csv (IntelItem detail).
    Single-table source failures degrade only their columns to NaN and
    land in manifest.failures.
    """
    log = (lambda *a: None) if quiet else print
    snap = Path(snap_dir)
    asof = asof or date.today()

    frames = [df for df in (master, watch)
              if df is not None and not df.empty]
    if not frames:
        _write_detail(snap, [])
        return None
    uni = pd.concat(frames, ignore_index=True)[["market", "code"]]
    uni = uni[uni["market"] == "A"].drop_duplicates()
    codes = pd.Index(uni["code"].astype(str), name="code")
    if codes.empty:
        _write_detail(snap, [])          # P1: 本次运行无 A 股覆盖
        return None

    lookback = (asof - timedelta(
        days=config.INTEL_LOOKBACK_DAYS)).isoformat()
    forward = (asof + timedelta(
        days=config.INTEL_FORECAST_DAYS)).isoformat()

    def _fail(label):
        if manifest is not None:
            manifest.setdefault("failures", []).append(
                f"intel {label}: source failed")
        log(f"    [{label}] source failed -> NaN (fail-closed)")

    def _lf(name, fetcher, label):
        df = _load_or_fetch(snap / name, fetcher, label, refresh, log)
        if df is None:
            _fail(label)
        return df

    fin_rd = _report_date_of(snap)
    unlocks = _lf("a_unlocks.csv",
                  lambda: fetch_a_unlocks(asof.isoformat(), forward),
                  "A unlocks")
    holders = _lf("a_holder_changes.csv",
                  lambda: fetch_a_holder_changes(lookback), "A holders")
    buybacks = _lf("a_buybacks.csv",
                   lambda: fetch_a_buybacks(lookback), "A buybacks")
    placements = _lf("a_placements.csv",
                     lambda: fetch_a_placements(lookback), "A placements")
    forecasts = _lf("a_forecasts.csv",
                    lambda: fetch_a_forecasts(lookback), "A forecasts")
    appoints = _lf("a_appointments.csv",
                   lambda: fetch_a_appointments(asof.isoformat(),
                                                forward),
                   "A appointments")
    balance = (None if not fin_rd else
               _lf("a_balance.csv", lambda: fetch_a_balance(fin_rd),
                   "A balance"))
    eq_recs = None if balance is None else _eq_records(snap, balance)

    try:
        cols = {
            "unlock_pct_30d": _agg_unlock(unlocks, asof, 30, codes),
            "unlock_pct_90d": _agg_unlock(unlocks, asof, 90, codes),
            "holder_cut_flag": _agg_flag(holders,
                                         _holder_cut_mask(asof), codes),
            "dilution_flag": _agg_flag(placements, _any_mask, codes),
            "buyback_active": _agg_flag(buybacks, _any_mask, codes),
            "report_due_days": _agg_report_due(appoints, asof, codes),
            "forecast_flag": _agg_forecast(forecasts, codes),
            "eq_flags": (None if eq_recs is None else
                         pd.Series({c: len(model.earnings_quality(
                             eq_recs.get(c, {})))
                             for c in codes}, index=codes)),
        }
        out = pd.DataFrame({"market": "A", "code": list(codes)})
        for c in RADAR_COLUMNS:
            out[c] = (cols[c].to_numpy() if cols[c] is not None
                      else float("nan"))

        have = out[["unlock_pct_30d", "holder_cut_flag", "dilution_flag",
                    "eq_flags"]].notna().all(axis=1)
        red = ((out["unlock_pct_30d"] >= config.UNLOCK_RED_PCT)
               | (out["holder_cut_flag"] == 1)
               | (out["dilution_flag"] == 1)
               | (out["eq_flags"] >= config.EQ_FLAG_RED))
        out["intel_red"] = red.astype(float).where(have)

        items = (_unlock_items(unlocks, codes)
                 + _holder_items(holders, codes)
                 + _buyback_items(buybacks, codes)
                 + _placement_items(placements, codes)
                 + _forecast_items(forecasts, codes)
                 + _appointment_items(appoints, codes)
                 + _eq_items(eq_recs, fin_rd, codes))
        _write_detail(snap, items)
        if manifest is not None:
            manifest["datasets"]["event_radar"] = len(items)
            manifest["datasets"]["radar_stocks"] = len(out)
        log(f"    [intel] radar: {len(out)} stocks, {len(items)} events")
        return out
    except Exception as e:  # noqa: BLE001 — radar must never break fetch
        print(f"[WARN] intel radar assembly failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        if manifest is not None:
            manifest["failures"].append(
                f"intel radar: {type(e).__name__}: {str(e)[:120]}")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -B -m pytest tests/test_intel_radar.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/radar.py tests/test_intel_radar.py
git commit -m "feat(intel): event radar aggregation + detail csv"
```

---

### Task 8: Pipeline integration (MASTER_COLUMNS + run_fetch radar pass)

**Files:**
- Modify: `value_genie/fetch/pipeline.py` (imports, `MASTER_COLUMNS`, `run_fetch` tail)
- Test: `tests/test_pipeline.py` (modify)

- [ ] **Step 1: Write the failing test changes**

In `tests/test_pipeline.py`:

**(a)** Add a shared intel stub helper after the `_kline_df`/`_quotes` helpers (module level, before `a_quotes`):

```python
def stub_intel_fetchers(monkeypatch):
    """Patch value_genie.intel.radar's fetchers: 600519 unlock 8% in
    10d (red flag), 000858 active buyback, 600519 balance row (no eq
    trigger: rece 20 < 15+10)."""
    from value_genie.intel import radar as _radar
    _d10 = (date.today() + timedelta(days=10)).isoformat()
    monkeypatch.setattr(_radar, "fetch_a_unlocks", lambda s, e: pd.DataFrame([
        {"code": "600519", "name": "Kweichow Moutai", "free_date": _d10,
         "unlock_pct": 8.0, "lift_cap_wan": 1.0e6}]))
    monkeypatch.setattr(_radar, "fetch_a_holder_changes",
                        lambda s: pd.DataFrame())
    monkeypatch.setattr(_radar, "fetch_a_buybacks",
                        lambda s: pd.DataFrame([
                            {"code": "000858", "name": "Wuliangye",
                             "amount_yuan": 5.0e8, "shares": 2.0e7,
                             "announce_date": date.today().isoformat()}]))
    monkeypatch.setattr(_radar, "fetch_a_placements",
                        lambda s: pd.DataFrame())
    monkeypatch.setattr(_radar, "fetch_a_forecasts",
                        lambda s: pd.DataFrame())
    monkeypatch.setattr(_radar, "fetch_a_appointments",
                        lambda s, e: pd.DataFrame())
    monkeypatch.setattr(_radar, "fetch_a_balance",
                        lambda rd: pd.DataFrame([
                            {"code": "600519", "rece_yoy": 20.0,
                             "inv_yoy": 5.0, "receivable": 1.0e9,
                             "inventory": 2.0e9, "report_date": rd}]))
```

**(b)** In the `patched_fetchers` fixture, add at the end (before `return counters`):

```python
    stub_intel_fetchers(monkeypatch)
```

**(c)** In `test_run_fetch_full_flow`, extend the file-existence loop with the radar artifacts and add radar assertions after the existing `us = ...` block:

```python
    for name in ("master.csv", "manifest.json", "a_quotes.csv",
                 "hk_quotes.csv", "us_quotes.csv", "a_financials.csv",
                 "us_financials.csv", "hk_f10.csv",
                 "kline/A_600519.csv", "kline/HK_00700.csv",
                 "kline/US_AAPL.csv", "event_radar.csv", "a_unlocks.csv",
                 "a_buybacks.csv", "a_balance.csv"):
        assert (snap / name).exists(), name
```

```python
    # intel radar columns: A covered (0.0 = no event), HK/US NaN (P1)
    a519 = master[master["code"] == "600519"].iloc[0]
    assert a519["unlock_pct_30d"] == 8.0
    assert a519["unlock_pct_90d"] == 8.0
    assert a519["intel_red"] == 1.0
    a858 = master[master["code"] == "000858"].iloc[0]
    assert a858["buyback_active"] == 1.0
    assert a858["intel_red"] == 0.0
    hk700 = master[master["code"] == "00700"].iloc[0]
    assert pd.isna(hk700["unlock_pct_30d"])
    detail = pd.read_csv(snap / "event_radar.csv", dtype={"code": str})
    assert "unlock" in set(detail["kind"])
    assert "buyback" in set(detail["kind"])
    assert manifest["datasets"]["event_radar"] == 2
```

**(d)** In `test_run_fetch_skips_us_without_sec_financials` (it does NOT use `patched_fetchers`), add the stub right after the other monkeypatch lines:

```python
    stub_intel_fetchers(monkeypatch)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_pipeline.py -v
```

Expected: FAIL — `AttributeError: module 'value_genie.intel.radar' has no attribute 'RADAR_COLUMNS'` at pipeline import (radar exists but pipeline not wired yet the test imports `pl.MASTER_COLUMNS` which lacks radar tail once wired)... actually at this step the failure is: `stub_intel_fetchers` patches attributes that exist, tests run, but master lacks radar columns → the new asserts fail (`KeyError: 'unlock_pct_30d'`).

- [ ] **Step 3: Wire the pipeline**

In `value_genie/fetch/pipeline.py`:

**(a)** Add the import after the existing `from .quotes import ...` block:

```python
from ..intel.radar import RADAR_COLUMNS, build_event_radar, merge_radar
```

**(b)** Change `MASTER_COLUMNS` to append the radar tail:

```python
MASTER_COLUMNS = [
    "market", "code", "name", "industry", "currency", "price", "market_cap",
    "pe_ttm", "pb", "ps", "dividend_yield", "rev_yoy", "profit_yoy",
    "rev_q_yoy", "roe", "gross_margin", "net_margin", "debt_ratio",
    "ocf_yield", "cash_conversion",
    "fcf_yield", "borrowed_dividend", "capex_to_ocf",
    "pos_52w", "drawdown_52w", "ret_250d", "ret_60d", "volatility",
    "ret_5d", "ret_20d", "vol_20d",
    "report_date", "value_score", "growth_score", "quality_score",
    "safety_score", "momentum_score", "cashflow_score", "data_completeness",
] + list(RADAR_COLUMNS)
```

**(c)** In `run_fetch`, capture the watchlist return and add the radar pass (replacing the current `build_watchlist(...)` call block at the end):

```python
    # deep data for holdings the funnel excluded (watchlist.csv)
    watch = build_watchlist(snap_dir, kline_reuse, master, hk_f10, fx,
                            manifest, quiet=quiet)

    # intel radar: A-share event risk columns into master + watchlist
    # (design 2026-09-08 §6; P1 = A-share batch tables, fail-closed)
    radar_df = build_event_radar(snap_dir, master, watch, manifest,
                                 refresh=refresh, quiet=quiet)
    if radar_df is not None and not radar_df.empty:
        master = merge_radar(master, radar_df)
        master.to_csv(snap_dir / "master.csv", index=False)
        if watch is not None and not watch.empty:
            watch = merge_radar(watch, radar_df)
            watch.to_csv(snap_dir / "watchlist.csv", index=False)
```

(The old code called `build_watchlist(...)` without capturing the return; the new code binds it to `watch`.)

- [ ] **Step 4: Run the pipeline tests**

```bash
python -B -m pytest tests/test_pipeline.py -v
```

Expected: all pass, including the existing `assert list(master.columns) == pl.MASTER_COLUMNS` (radar tail added to both) and `test_watchlist_deep_data_for_excluded_holdings` (`list(wl.columns) == pl.MASTER_COLUMNS`).

- [ ] **Step 5: Run the full suite** (regression: report/analyze/recommend read master.csv)

```bash
python -B -m pytest tests -q
```

Expected: all pass. If `test_report`/`test_analyze`/`test_recommend` fixtures build synthetic master frames without radar columns, they must still pass — report.py `REPORT_COLUMNS` is unchanged and reads by column name, so radar columns are additive.

- [ ] **Step 6: Commit**

```bash
git add value_genie/fetch/pipeline.py tests/test_pipeline.py
git commit -m "feat(intel): radar merge into master/watchlist (fetch pipeline)"
```

---

### Task 9: Doctor event_radar check

**Files:**
- Modify: `value_genie/doctor.py` (after the watchlist check block, before the manifest block)
- Test: `tests/test_overview.py` (modify `make_snap` + new test)

- [ ] **Step 1: Write the failing test changes**

In `tests/test_overview.py`, add an `event_radar.csv` to `make_snap` (after the watchlist.csv write):

```python
    pd.DataFrame(columns=["market", "code", "subsystem", "kind",
                          "event_date", "impact", "title", "url",
                          "source", "payload"]).to_csv(
        snap / "event_radar.csv", index=False)
```

And append a new test to `TestDoctor`:

```python
    def test_event_radar_check(self, tmp_path):
        snap = make_snap(tmp_path)
        checks = dr.run_checks(data_dir=tmp_path)
        er = [c for c in checks if "event_radar" in c[2]]
        assert er and er[0][0] == "PASS"       # 0 rows is valid (P1)
        (snap / "event_radar.csv").unlink()
        checks = dr.run_checks(data_dir=tmp_path)
        er = [c for c in checks if "event_radar" in c[2]]
        assert er and er[0][0] == "WARN" and "missing" in er[0][2]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -B -m pytest tests/test_overview.py -v
```

Expected: FAIL — no check mentions event_radar (first assert `er` empty). Note: without the doctor change, the pre-existing `test_freshness_gate_healthy_is_pass` would still pass because make_snap now writes the file — the WARN-only-missing contract is what's new.

- [ ] **Step 3: Implement the doctor check**

In `value_genie/doctor.py`, insert after the watchlist check block (after the `except ... "watchlist.csv unreadable"` line) and before the manifest block:

```python
    # intel radar: missing -> WARN (舆情缺失允许降级运行, design §8),
    # never FAIL — the screener stays usable, only intel-gated screens
    # degrade (their gates skip with a WARN, see evaluate_gates).
    er = snap / "event_radar.csv"
    if not er.exists():
        out.append(("WARN", "-",
                    "event_radar.csv missing (old snapshot or intel "
                    "fetch failed)"))
    else:
        try:
            n = len(pd.read_csv(er, dtype={"code": str}))
            out.append(("PASS", "-", f"event_radar rows: {n}"))
        except (OSError, pd.errors.ParserError, ValueError):
            out.append(("WARN", "-", "event_radar.csv unreadable"))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -B -m pytest tests/test_overview.py tests/test_cli.py -v
```

Expected: all pass (test_cli freshness gates are mocked; doctor exit-code tests mock run_checks).

- [ ] **Step 5: Commit**

```bash
git add value_genie/doctor.py tests/test_overview.py
git commit -m "feat(intel): doctor event_radar health check"
```

---

### Task 10: Full suite + live fetch verification + push

**Files:**
- No new source files. Verifies the whole chain against the real Eastmoney endpoints.

- [ ] **Step 1: Run the full test suite**

```bash
python -B -m pytest tests -q
```

Expected: all pass (~480 tests).

- [ ] **Step 2: Live fetch smoke test** (validates the probe constants against real endpoints; ~10-15 min)

```bash
python -m value_genie fetch
```

Expected: completes without crashing; the log shows `[A unlocks]`, `[A holders]`, `[A buybacks]`, `[A placements]`, `[A forecasts]`, `[A appointments]`, `[A balance]` lines and a final `[intel] radar: N stocks, M events` line.

- [ ] **Step 3: Inspect the live snapshot artifacts**

```bash
python -m value_genie doctor
```

Expected: `event_radar rows: N` PASS line; no new FAILs.

```bash
python -c "import pandas as pd, glob; snap=sorted(glob.glob('data/snapshots/*'))[-1]; d=pd.read_csv(snap+'/event_radar.csv', dtype={'code':str}); print(d['kind'].value_counts()); print(d.head(15).to_string()); m=pd.read_csv(snap+'/master.csv', dtype={'code':str}); print(m[['market','code','unlock_pct_30d','holder_cut_flag','dilution_flag','buyback_active','report_due_days','forecast_flag','eq_flags','intel_red']].head(10).to_string())"
```

Expected: unlock/buyback/holder/placement/forecast/report_date/eq_flag kinds present (some may be legitimately empty depending on the date — 三季报预约空窗是正常时序); master radar columns mostly 0.0 with at least some non-zero unlock_pct_30d (there is always *some* unlock in the next 90 days market-wide); intel_red sparse (0/1).

- [ ] **Step 4: Record live-check findings in Field Notes** (self-refinement protocol; only if something noteworthy was observed)

```bash
python -m value_genie skill note data-ops "intel radar P1 live check: <observed row counts / endpoint quirks / timestamp formats>"
```

- [ ] **Step 5: Final commit + push the feature branch** (NEVER push main — repo rule; user opens/merges the PR on GitHub)

```bash
git add -A
git commit -m "test(intel): live fetch verification"
git push -u origin feat/intel-radar-p1
```

---

## Self-Review (completed during plan writing)

**Spec coverage (P1 scope, design §11.1):**
- model + sources 注册 → Tasks 1-3
- A 股事件批表（解禁/减持/回购/定增/预告/预约披露）→ Tasks 5-6
- 粉饰信号（资产负债表批表 + 扣非字段）→ Tasks 3, 6
- radar 集成 fetch → Task 8
- master 列（§6.2 全部 9 列 + 无事件=0.0/源失败=NaN 语义）→ Tasks 7-8
- doctor → Task 9
- 测试（§10 的 test_intel_model/sources/radar + pipeline/doctor 扩展）→ Tasks 1-9
- 断点续跑（raw 表 CSV 落盘复用）→ Task 7 `_load_or_fetch`
- manifest.failures 单源失败记录 → Task 7（`_fail`）

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `RADAR_COLUMNS` order == master tail order (Task 8 asserts `list(master.columns) == pl.MASTER_COLUMNS`); radar fetchers imported by name into radar.py so tests monkeypatch `value_genie.intel.radar.fetch_a_*`; `build_event_radar(snap_dir, master, watch, manifest, refresh, quiet)` matches the pipeline call.

## Known risks (flagged, not blocking)

1. `RPT_SEO_DETAIL`/`RPT_SHARE_HOLDER_INCREASE` code column name assumed `SECURITY_CODE` — `code_col()` falls back to `SCODE`, and Task 10's live fetch is the definitive check.
2. dc_report treats `{"success": false}` as source failure and empty `result.data` as a valid empty window — if live behavior differs, adjust per Task 10 findings + Field Notes.
3. `test_pipeline` stubs make radar deterministic; the same-day reuse of *empty* raw tables intentionally refetches (matches existing pipeline behavior for empty datasets).
