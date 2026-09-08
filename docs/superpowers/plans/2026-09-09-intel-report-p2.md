# Intel P2: Per-Stock Intelligence Command (intel X) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m value_genie intel X` renders a five-section per-stock intelligence report (event radar / announcement timeline / earnings-quality signals / analyst ratings / news timeline) for A-shares, with `--json` output and red-flag integration into `ask`.

**Architecture:** Three new Eastmoney web endpoints (np-anotice-stock announcements, np-listapi news, reportapi research reports) served by one new `EM_WEB` Fetcher singleton. New `value_genie/intel/report.py` assembles: radar row + event details from the snapshot's full-market batch tables (zero network for stocks already covered), live per-stock fetches for the three intel sections, fail-closed per section. `analyze_stock()` gains an `intel` key; `risk_flags()` surfaces `intel_red` verbatim.

**Tech Stack:** Python 3.10+, pandas, requests (existing `fetch/http.Fetcher`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-intel-sentiment-system-design.md` §7 (情报通道), §11.2 (P2 scope). P4 items (master gates, skill 16, AGENTS/README) are out of scope here.

---

## Verified endpoints (probe 2026-09-09, `_probe_p2*.py`)

All three return HTTP 200 with clean JSON. Details recorded so this plan is executable without re-probing:

1. **Announcements** `GET https://np-anotice-stock.eastmoney.com/api/security/ann`
   - params: `sr=-1, page_size=50, page_index=1, ann_type=A, stock_list=<code>, f_node=0, s_node=0`
   - shape: `{"data": {"list": [{"art_code": "AN2026...", "title": "...", "notice_date": "2026-09-07 00:00:00", "columns": [{"column_code": "...", "column_name": "限售股份上市流通"}], "codes": [{"stock_code": "688795", ...}]}]}}`
   - detail URL (verified 200): `https://data.eastmoney.com/notices/detail/{code}/{art_code}.html`
   - no envelope code field — treat transport None as failure, missing `data.list` as empty.

2. **News** `GET https://np-listapi.eastmoney.com/comm/wap/getListInfo`
   - params: `client=wap, type=1, mTypeAndCode={market_id}.{code}, pageSize=50, pageIndex=1, req_trace=1`
   - `market_id` == `Match.market_id` (1=SH, 0=SZ+BJ) — zero conversion.
   - shape: `{"code": 1, "message": "success", "data": {"list": [{"Art_ShowTime": "2026-09-08 20:55:07", "Art_Title": "...", "Art_MediaName": "每日经济新闻", "Art_Url": "http://finance.eastmoney.com/a/....html"}]}}`
   - success envelope is `code == 1` (NOT 0 — differs from DC).

3. **Research reports** `GET https://reportapi.eastmoney.com/report/list`
   - params: `qType=0, code=<code>, pageNo=1, pageSize=50, beginTime=YYYY-MM-DD, endTime=YYYY-MM-DD`
   - shape: `{"hits": N, "size": N, "data": [{"orgSName": "国金证券", "publishDate": "2026-08-22 00:00:00.000", "emRatingName": "买入", "lastEmRatingName": "买入", "ratingChange": 3, "predictThisYearEps": "3.544", "predictNextYearEps": "1.262", "indvAimPriceT": "", "indvAimPriceL": "", "infoCode": "AP2026...", "title": "...", "researcher": "..."}]}`
   - `ratingChange`: 3 observed with rating==last_rating → 3=maintain; Eastmoney convention 1=downgrade, 2=upgrade, 4=first coverage (impact mapping uses this, payload keeps the raw value; agent interpretation reads rating vs last_rating directly).
   - `indvAimPriceT`/`indvAimPriceL` (target price) are usually EMPTY for A-shares — render "—" when blank, never fabricate.
   - report detail URL convention: `https://data.eastmoney.com/report/info/{infoCode}.html`.

**Quoting rules for DC single-stock fallback filters** (P1 probe rules, `intel/_dc.py` docstring): dates single-quoted, strings/booleans double-quoted → `(SECURITY_CODE="688795")`. Buyback report uses `SCODE` not `SECURITY_CODE` and must NOT carry sortColumns.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `value_genie/config.py` | Modify | 3 URL constants + 3 window constants (P2 section) |
| `value_genie/fetch/http.py` | Modify | `EM_WEB` Fetcher singleton |
| `value_genie/intel/sources.py` | Modify | extend eastmoney capabilities (`news:A`, `ratings:A`, `notice:A`) + source order |
| `value_genie/intel/news.py` | Create | `fetch_stock_news()` → IntelItem list |
| `value_genie/intel/ratings.py` | Create | `fetch_stock_ratings()` → IntelItem list |
| `value_genie/intel/announcements.py` | Modify | add `fetch_stock_notices()`; add optional `code` param to 4 batch fetchers (single-stock fallback) |
| `value_genie/intel/earnings.py` | Modify | add optional `code` param to 3 batch fetchers (single-stock fallback) |
| `value_genie/intel/model.py` | Modify | impact map entries for `news`/`rating`/`notice` kinds |
| `value_genie/intel/report.py` | Create | `build_intel_report()` / `render_intel()` / `to_json()` |
| `value_genie/__main__.py` | Modify | `intel` subcommand + `cmd_intel` |
| `value_genie/analyze.py` | Modify | `intel` key in result; `risk_flags` intel section; brief verdict suffix |
| `tests/test_intel_sources.py` | Modify | capabilities + 3 new fetchers + code-param filters |
| `tests/test_intel_report.py` | Create | assembly/render/json/fail-closed |
| `tests/test_cli.py` | Modify | `TestIntel` + ask intel integration |

Naming note: `value_genie/intel/report.py` shadows `value_genie/report.py` by basename. Inside the package always import as `from .intel import report as intel_report` (or `from ..intel import report` in `__main__`) — never bare `from . import report` inside intel.

---

### Task 1: Config constants + EM_WEB singleton + source registration

**Files:**
- Modify: `value_genie/config.py` (after the `EQ_NONRECURRING_MIN` line, ~L252)
- Modify: `value_genie/fetch/http.py` (singleton block, ~L98-102)
- Modify: `value_genie/intel/sources.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_intel_sources.py`)

```python
def test_import_intel_extends_news_ratings_capabilities():
    import value_genie.intel  # noqa: F401
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert "news:A" in ds.capabilities
    assert "ratings:A" in ds.capabilities
    assert "notice:A" in ds.capabilities
    assert [s.id for s in get_sources("news", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("ratings", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("notice", "A")] == ["eastmoney"]


def test_em_web_singleton_and_urls():
    from value_genie.fetch.http import EM_WEB
    from value_genie import config
    assert EM_WEB.name == "EM_WEB"
    assert config.EM_NOTICE_URL.startswith("https://np-anotice-stock")
    assert config.EM_NEWS_URL.startswith("https://np-listapi")
    assert config.EM_REPORT_URL.startswith("https://reportapi")
    assert config.INTEL_NOTICE_DAYS == 90
    assert config.INTEL_NEWS_DAYS == 30
    assert config.INTEL_RATING_DAYS == 365
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k "capabilities or em_web"`
Expected: 2 failures (`news:A` missing; `EM_WEB` ImportError).

- [ ] **Step 3: Implement**

`value_genie/config.py` — append after the P1 intel block (after `EQ_NONRECURRING_MIN`):

```python
# Intel per-stock report (P2: A-share) — eastmoney web endpoints ------
EM_NOTICE_URL = ("https://np-anotice-stock.eastmoney.com"
                 "/api/security/ann")          # 个股公告列表
EM_NEWS_URL = ("https://np-listapi.eastmoney.com"
               "/comm/wap/getListInfo")        # 个股新闻时间线
EM_REPORT_URL = "https://reportapi.eastmoney.com/report/list"  # 研报评级
INTEL_NOTICE_DAYS = 90    # 公告时间线回看窗口（天）
INTEL_NEWS_DAYS = 30      # 新闻时间线回看窗口（天）
INTEL_RATING_DAYS = 365   # 研报评级回看窗口（天）
```

`value_genie/fetch/http.py` — after the `TX = Fetcher(...)` line:

```python
EM_WEB = Fetcher({"User-Agent": config.EM_UA}, "EM_WEB")  # np-anotice / np-listapi / reportapi
```

`value_genie/intel/sources.py` — extend the capability loop and add source orders:

```python
def _register_intel_sources():
    """Extend the existing eastmoney entry with intel capabilities."""
    for ds in list_sources():
        if ds.id == "eastmoney":
            for cap in ("events:A", "announce:A", "notice:A",
                        "news:A", "ratings:A"):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
    set_source_order("events", "A", ["eastmoney"])
    set_source_order("announce", "A", ["eastmoney"])
    set_source_order("notice", "A", ["eastmoney"])
    set_source_order("news", "A", ["eastmoney"])
    set_source_order("ratings", "A", ["eastmoney"])
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -B -m pytest tests/test_intel_sources.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add value_genie/config.py value_genie/fetch/http.py value_genie/intel/sources.py tests/test_intel_sources.py
git commit -m "feat(intel): P2 config constants + EM_WEB fetcher + source registration"
```

---

### Task 2: news.py — per-stock news timeline

**Files:**
- Create: `value_genie/intel/news.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_intel_sources.py`)

```python
# ---------------------------------------------------------------------------
# Per-stock news timeline (np-listapi)
# ---------------------------------------------------------------------------
from datetime import date, timedelta

from value_genie.intel import news as nws


def _news_json(rows):
    return {"code": 1, "message": "success",
            "data": {"page_index": 1, "list": rows}}


class TestFetchStockNews:
    def test_normalizes_items_and_window(self, monkeypatch):
        today = date.today()
        recent = (today - timedelta(days=2)).isoformat()
        stale = (today - timedelta(days=60)).isoformat()
        rows = [
            {"Art_ShowTime": f"{recent} 20:55:07",
             "Art_Title": "摩尔线程解禁", "Art_MediaName": "每日经济新闻",
             "Art_Url": "http://finance.eastmoney.com/a/1.html"},
            {"Art_ShowTime": f"{stale} 09:00:00",
             "Art_Title": "旧闻（窗口外，应被过滤）",
             "Art_MediaName": "x", "Art_Url": "http://x/2.html"},
        ]
        seen = {}

        def fake(url, params=None, **kw):
            seen.update({"url": url, "params": params})
            return _news_json(rows)

        monkeypatch.setattr(nws.EM_WEB, "get_json", fake)
        items = nws.fetch_stock_news("1", "688795", name="摩尔线程-U")
        assert seen["params"]["mTypeAndCode"] == "1.688795"
        assert len(items) == 1                     # stale row filtered
        it = items[0]
        assert it.subsystem == "news" and it.kind == "news"
        assert it.event_date.isoformat() == recent
        assert it.title == "摩尔线程解禁"
        assert it.url == "http://finance.eastmoney.com/a/1.html"
        assert it.payload["media"] == "每日经济新闻"
        assert it.impact == "neutral"

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(nws.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert nws.fetch_stock_news("1", "688795") is None

    def test_envelope_code_not_success_none(self, monkeypatch):
        # np-listapi success envelope is code==1; anything else is failure
        monkeypatch.setattr(
            nws.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"code": 0, "data": None})
        assert nws.fetch_stock_news("1", "688795") is None

    def test_empty_list_is_empty_not_none(self, monkeypatch):
        monkeypatch.setattr(nws.EM_WEB, "get_json",
                            lambda url, params=None, **kw: _news_json([]))
        assert nws.fetch_stock_news("1", "688795") == []
```

- [ ] **Step 2: Run, verify fail** (`ModuleNotFoundError: value_genie.intel.news`)

Run: `python -B -m pytest tests/test_intel_sources.py -q -k news`

- [ ] **Step 3: Implement `value_genie/intel/news.py`**

```python
"""News subsystem (P2: A-share per-stock timeline, design §4).

np-listapi wap getListInfo — per-stock CMS news feed. No sentiment
scoring by design (design §1 non-goal): items carry neutral impact
and the AI agent interprets heat/context.
"""

from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from .model import IntelItem


def fetch_stock_news(market_id: str, code: str, name: str = "",
                     days: int = None) -> list | None:
    """近 days 天个股新闻时间线（np-listapi）。

    market_id: 东财市场前缀（1=沪, 0=深+北）——即 Match.market_id。
    返回 IntelItem 列表（subsystem="news"），新→旧由接口保证（sr 默认）；
    源失败返回 None（fail-closed），空时间线返回 []。
    """
    days = days or config.INTEL_NEWS_DAYS
    since = (date.today() - timedelta(days=days)).isoformat()
    raw = EM_WEB.get_json(config.EM_NEWS_URL, params={
        "client": "wap", "type": 1,
        "mTypeAndCode": f"{market_id}.{code}",
        "pageSize": 50, "pageIndex": 1, "req_trace": "1",
    })
    if raw is None or raw.get("code") != 1:
        return None
    rows = ((raw.get("data") or {}).get("list")) or []
    items = []
    for r in rows:
        when = str(r.get("Art_ShowTime") or "")[:10]
        if not when or when < since:      # lexical ISO compare
            continue
        items.append(IntelItem(
            market="A", code=code, name=name,
            subsystem="news", kind="news",
            event_date=date.fromisoformat(when),
            title=str(r.get("Art_Title") or ""),
            url=str(r.get("Art_Url") or ""),
            source="eastmoney", impact="neutral",
            payload={"media": str(r.get("Art_MediaName") or ""),
                     "show_time": str(r.get("Art_ShowTime") or "")}))
    return items
```

- [ ] **Step 4: Run, verify pass**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k news`

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/news.py tests/test_intel_sources.py
git commit -m "feat(intel): per-stock news timeline fetcher (np-listapi)"
```

---

### Task 3: ratings.py — analyst rating history

**Files:**
- Create: `value_genie/intel/ratings.py`
- Modify: `value_genie/intel/model.py` (IMPACT_BY_KIND entries)
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_intel_sources.py`)

```python
# ---------------------------------------------------------------------------
# Per-stock analyst ratings (reportapi)
# ---------------------------------------------------------------------------
from value_genie.intel import ratings as rtg


def _rating_row(**over):
    row = {
        "orgSName": "国金证券", "publishDate": "2026-08-22 00:00:00.000",
        "emRatingName": "买入", "lastEmRatingName": "增持",
        "ratingChange": 2, "predictThisYearEps": "3.544",
        "predictNextYearEps": "1.262", "indvAimPriceT": "",
        "indvAimPriceL": "", "infoCode": "AP202608221828313285",
        "title": "全功能GPU领军", "researcher": "刘高畅",
    }
    row.update(over)
    return row


class TestFetchStockRatings:
    def test_normalizes_items(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update({"url": url, "params": params})
            return {"hits": 1, "size": 1, "data": [_rating_row()]}

        monkeypatch.setattr(rtg.EM_WEB, "get_json", fake)
        items = rtg.fetch_stock_ratings("688795", name="摩尔线程-U")
        assert seen["params"]["code"] == "688795"
        assert len(items) == 1
        it = items[0]
        assert it.subsystem == "ratings" and it.kind == "rating"
        assert it.event_date.isoformat() == "2026-08-22"
        assert it.title == "国金证券 买入"
        assert it.url == ("https://data.eastmoney.com/report/info/"
                          "AP202608221828313285.html")
        assert it.impact == "positive"          # ratingChange 2 = upgrade
        assert it.payload["rating"] == "买入"
        assert it.payload["last_rating"] == "增持"
        assert it.payload["target_price"] is None   # blank stays None

    def test_downgrade_is_negative(self, monkeypatch):
        monkeypatch.setattr(
            rtg.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"hits": 1, "size": 1,
                                            "data": [_rating_row(
                                                ratingChange=1)]})
        items = rtg.fetch_stock_ratings("688795")
        assert items[0].impact == "negative"

    def test_maintain_is_neutral(self, monkeypatch):
        monkeypatch.setattr(
            rtg.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"hits": 1, "size": 1,
                                            "data": [_rating_row(
                                                ratingChange=3)]})
        items = rtg.fetch_stock_ratings("688795")
        assert items[0].impact == "neutral"

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(rtg.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert rtg.fetch_stock_ratings("688795") is None

    def test_empty_data_is_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            rtg.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"hits": 0, "data": []})
        assert rtg.fetch_stock_ratings("688795") == []
```

- [ ] **Step 2: Run, verify fail**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k rating`

- [ ] **Step 3: Implement `value_genie/intel/ratings.py`**

```python
"""Ratings subsystem (P2: A-share analyst reports, design §4).

reportapi.eastmoney.com/report/list — sell-side reports with rating,
rating change, EPS forecasts and (usually empty) target price.
"""

from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from .model import IntelItem

REPORT_URL_TMPL = "https://data.eastmoney.com/report/info/{info}.html"

# Eastmoney ratingChange convention (observed 3=maintain when
# rating==last_rating; 1/2/4 per EM web convention): 1=下调 2=上调
# 3=维持 4=首次。Payload keeps the raw value; impact uses it only as a
# category hint — the agent reads rating vs last_rating directly.
_RATING_IMPACT = {"1": "negative", "2": "positive"}


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def fetch_stock_ratings(code: str, name: str = "",
                        days: int = None) -> list | None:
    """近 days 天投行研报评级（reportapi，qType=0 个股研报）。

    返回 IntelItem 列表（subsystem="ratings", kind="rating"），
    源失败 None（fail-closed），无研报 []。目标价（indvAimPriceT/L）
    A 股普遍为空——保持 None，绝不编造。
    """
    days = days or config.INTEL_RATING_DAYS
    end = date.today()
    begin = end - timedelta(days=days)
    raw = EM_WEB.get_json(config.EM_REPORT_URL, params={
        "qType": 0, "code": code, "pageNo": 1, "pageSize": 50,
        "beginTime": begin.isoformat(), "endTime": end.isoformat(),
    })
    if raw is None or "data" not in raw:
        return None
    rows = raw.get("data") or []
    items = []
    for r in rows:
        pd_ = str(r.get("publishDate") or "")[:10]
        if not pd_:
            continue
        change = str(r.get("ratingChange") or "")
        items.append(IntelItem(
            market="A", code=code, name=name,
            subsystem="ratings", kind="rating",
            event_date=date.fromisoformat(pd_),
            title=f"{r.get('orgSName') or ''} {r.get('emRatingName') or ''}",
            url=(REPORT_URL_TMPL.format(info=r.get("infoCode"))
                 if r.get("infoCode") else ""),
            source="eastmoney",
            impact=_RATING_IMPACT.get(change, "neutral"),
            payload={"org": str(r.get("orgSName") or ""),
                     "rating": str(r.get("emRatingName") or ""),
                     "last_rating": str(r.get("lastEmRatingName") or ""),
                     "rating_change": change,
                     "eps_this_year": _f(r.get("predictThisYearEps")),
                     "eps_next_year": _f(r.get("predictNextYearEps")),
                     "target_price": (_f(r.get("indvAimPriceT"))
                                      or _f(r.get("indvAimPriceL"))),
                     "researcher": str(r.get("researcher") or "")}))
    return items
```

Also add `news`/`rating`/`notice` to `IMPACT_BY_KIND` in `value_genie/intel/model.py` (default-neutral entries so any future item_to_row consumers find them):

```python
    "news": "neutral",
    "rating": "neutral",      # per-item: upgrade/downgrade overrides
    "notice": "neutral",
```

- [ ] **Step 4: Run, verify pass**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k rating`

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/ratings.py value_genie/intel/model.py tests/test_intel_sources.py
git commit -m "feat(intel): analyst rating history fetcher (reportapi)"
```

---

### Task 4: announcements.py — per-stock notice list + single-stock fallback params

**Files:**
- Modify: `value_genie/intel/announcements.py`
- Modify: `value_genie/intel/earnings.py`
- Test: `tests/test_intel_sources.py`

Two changes in one task (they share the test file and the "single-stock fallback" theme):

**(a)** `fetch_stock_notices(code, name, days)` — np-anotice-stock per-stock announcement list with category + detail URL.
**(b)** Optional `code` param on the seven P1 batch fetchers so old snapshots (no saved batch tables) can still fetch a single stock live: filter gains `(SECURITY_CODE="{code}")` (or `(SCODE="{code}")` for the buyback report — probe rule: GPHG uses SCODE and no sortColumns).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_intel_sources.py`)

```python
# ---------------------------------------------------------------------------
# Per-stock notice list (np-anotice-stock) + batch fetcher code filters
# ---------------------------------------------------------------------------
from value_genie.intel import announcements as ann2  # ann already imported


def _notice_json(rows):
    return {"data": {"list": rows}}


class TestFetchStockNotices:
    def test_normalizes_items_with_category_and_url(self, monkeypatch):
        rows = [{
            "art_code": "AN202608281828639681",
            "title": "摩尔线程:关于限售股份上市流通的提示性公告",
            "notice_date": "2026-08-28 00:00:00",
            "columns": [{"column_code": "001002002003",
                         "column_name": "限售股份上市流通"}],
        }]
        seen = {}

        def fake(url, params=None, **kw):
            seen.update({"url": url, "params": params})
            return _notice_json(rows)

        monkeypatch.setattr(ann2.EM_WEB, "get_json", fake)
        items = ann2.fetch_stock_notices("688795", name="摩尔线程-U")
        assert seen["params"]["stock_list"] == "688795"
        assert len(items) == 1
        it = items[0]
        assert it.subsystem == "announcements" and it.kind == "notice"
        assert it.event_date.isoformat() == "2026-08-28"
        assert it.payload["category"] == "限售股份上市流通"
        assert it.url == ("https://data.eastmoney.com/notices/detail/"
                          "688795/AN202608281828639681.html")
        assert it.impact == "neutral"

    def test_window_filters_old_notices(self, monkeypatch):
        from datetime import date as _d, timedelta as _td
        old = (_d.today() - _td(days=120)).isoformat()
        rows = [{"art_code": "X", "title": "旧公告",
                 "notice_date": f"{old} 00:00:00", "columns": []}]
        monkeypatch.setattr(ann2.EM_WEB, "get_json",
                            lambda url, params=None, **kw: _notice_json(rows))
        assert ann2.fetch_stock_notices("688795") == []

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(ann2.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert ann2.fetch_stock_notices("688795") is None


class TestBatchFetcherCodeFilter:
    def test_unlocks_single_stock_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07", code="688795")
        assert '(SECURITY_CODE="688795")' in seen["filter"]

    def test_buybacks_single_stock_uses_scode(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_buybacks("2026-08-01", code="688795")
        assert '(SCODE="688795")' in seen["filter"]
        assert "sortColumns" not in seen

    def test_holder_changes_single_stock_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_holder_changes("2026-08-01", code="688795")
        assert '(SECURITY_CODE="688795")' in seen["filter"]

    def test_balance_single_stock_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ear.fetch_a_balance("2026-06-30", code="688795")
        assert '(SECURITY_CODE="688795")' in seen["filter"]

    def test_no_code_keeps_batch_behavior(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        assert "SECURITY_CODE=" not in seen["filter"]
```

- [ ] **Step 2: Run, verify fail**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k "notice or code_filter or CodeFilter"`
Expected: failures — `fetch_stock_notices` missing, `code=` kwarg TypeError.

- [ ] **Step 3: Implement**

In `value_genie/intel/announcements.py` — add the import and the new fetcher:

```python
from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from ._dc import code_col, dc_report, name_col, norm_dates
from .model import IntelItem

NOTICE_URL_TMPL = ("https://data.eastmoney.com/notices/detail/"
                   "{code}/{art}.html")


def fetch_stock_notices(code: str, name: str = "",
                        days: int = None) -> list | None:
    """近 days 天个股公告列表（np-anotice-stock），带分类与详情 URL。

    返回 IntelItem 列表（subsystem="announcements", kind="notice"，
    impact=neutral——公告性质由 AI 结合分类语境解读），源失败 None。
    """
    days = days or config.INTEL_NOTICE_DAYS
    since = (date.today() - timedelta(days=days)).isoformat()
    raw = EM_WEB.get_json(config.EM_NOTICE_URL, params={
        "sr": -1, "page_size": 50, "page_index": 1, "ann_type": "A",
        "stock_list": code, "f_node": 0, "s_node": 0,
    })
    if raw is None:
        return None
    rows = ((raw.get("data") or {}).get("list")) or []
    items = []
    for r in rows:
        nd = str(r.get("notice_date") or "")[:10]
        if not nd or nd < since:
            continue
        cols = r.get("columns") or []
        cat = "；".join(str(c.get("column_name") or "")
                       for c in cols if c.get("column_name")) or "公告"
        art = str(r.get("art_code") or "")
        items.append(IntelItem(
            market="A", code=code, name=name,
            subsystem="announcements", kind="notice",
            event_date=date.fromisoformat(nd),
            title=str(r.get("title") or ""),
            url=NOTICE_URL_TMPL.format(code=code, art=art) if art else "",
            source="eastmoney", impact="neutral",
            payload={"category": cat, "art_code": art}))
    return items
```

Then add the optional `code` param to the four batch fetchers (each gains `code: str | None = None` in the signature and appends its filter):

```python
def fetch_a_unlocks(start: str, end: str, code: str | None = None,
                    quiet: bool = True) -> pd.DataFrame | None:
    """... (docstring unchanged; code!=None -> single-stock filter)"""
    filters = [f"(FREE_DATE>='{start}')", f"(FREE_DATE<='{end}')"]
    if code:
        filters.append(f'(SECURITY_CODE="{code}")')
    df = dc_report(config.A_UNLOCK_REPORT_NAME, filters,
                   quiet=quiet, label="A unlocks")
    ...
```

Same pattern for `fetch_a_holder_changes` / `fetch_a_placements` / `fetch_a_forecasts` / `fetch_a_appointments` / `fetch_a_balance` (all append `f'(SECURITY_CODE="{code}")'`). `fetch_a_buybacks` appends `f'(SCODE="{code}")'` instead (probe rule: GPHG uses SCODE).

`earnings.py` fetchers (`fetch_a_forecasts`, `fetch_a_appointments`, `fetch_a_balance`) get the same treatment. Normalize each function body to build a `filters` list first, then a single `dc_report(...)` call — keeps the diff mechanical.

- [ ] **Step 4: Run, verify pass**

Run: `python -B -m pytest tests/test_intel_sources.py -q`

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/announcements.py value_genie/intel/earnings.py tests/test_intel_sources.py
git commit -m "feat(intel): per-stock notice list + single-stock fallback filters"
```

---

### Task 5: report.py — build_intel_report assembly

**Files:**
- Create: `value_genie/intel/report.py`
- Test: `tests/test_intel_report.py`

Core assembly. Section sources:

| section | data path | failure mode |
|---|---|---|
| `radar` | master/watchlist row (RADAR_COLUMNS); missing stock → derive events only | `{}` + note |
| `events` | snapshot batch tables `a_*.csv` filtered by code (zero network); table missing → live single-stock fetch (Task 4 `code=` param); both missing → `missing` note | list or missing note |
| `eq` | snapshot `a_financials.csv`/`a_cashflow.csv`/`a_balance.csv` → `model.earnings_quality(rec)` detail; rec assembled like `radar._eq_records` | list or missing note |
| `notices` | live `fetch_stock_notices` | list or missing note |
| `ratings` | live `fetch_stock_ratings` | list or missing note |
| `news` | live `fetch_stock_news` (market_id from match) | list or missing note |

Reuse from `radar.py`: `_unlock_items` / `_holder_items` / `_buyback_items` / `_placement_items` / `_forecast_items` / `_appointment_items` / `_read_csv` / `_eq_records` (import the private helpers — same package, stable surface, P1-tested).

- [ ] **Step 1: Write the failing tests** (`tests/test_intel_report.py`)

```python
"""Tests for value_genie.intel.report (per-stock intelligence assembly)."""

from datetime import date

import pandas as pd
import pytest

from value_genie.intel import report as ir
from value_genie.resolve import Match


def _snap(tmp_path, files: dict):
    snap = tmp_path / "snapshots" / "20260909"
    snap.mkdir(parents=True)
    for name, df in files.items():
        df.to_csv(snap / name, index=False)
    return snap


def _match(market="A", code="688795", mid="1"):
    return Match(market, code, "摩尔线程-U", 100.0, mid)


class TestRadarRow:
    def test_reads_master_row(self, tmp_path):
        files = {"master.csv": pd.DataFrame([{
            "market": "A", "code": "688795", "name": "摩尔线程-U",
            "unlock_pct_30d": 12.0, "intel_red": 1.0,
            "holder_cut_flag": 0.0, "dilution_flag": 0.0,
            "buyback_active": 0.0, "report_due_days": 49.0,
            "forecast_flag": 0.0, "eq_flags": 0.0,
            "unlock_pct_90d": 12.0}])}
        snap = _snap(tmp_path, files)
        row = ir._radar_row(snap, "A", "688795")
        assert row["unlock_pct_30d"] == 12.0
        assert row["intel_red"] == 1.0

    def test_watchlist_fallback(self, tmp_path):
        files = {"watchlist.csv": pd.DataFrame([{
            "market": "A", "code": "688795", "intel_red": 1.0}])}
        snap = _snap(tmp_path, files)
        assert ir._radar_row(snap, "A", "688795")["intel_red"] == 1.0

    def test_missing_stock_returns_none(self, tmp_path):
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "A", "code": "600519", "intel_red": 0.0}])})
        assert ir._radar_row(snap, "A", "688795") is None

    def test_no_snapshot_returns_none(self, tmp_path):
        assert ir._radar_row(tmp_path, "A", "688795") is None


class TestBuildIntelReport:
    def test_full_assembly(self, tmp_path, monkeypatch):
        files = {
            "master.csv": pd.DataFrame([{
                "market": "A", "code": "688795", "name": "摩尔线程-U",
                "unlock_pct_30d": 12.0, "unlock_pct_90d": 12.0,
                "holder_cut_flag": 0.0, "dilution_flag": 0.0,
                "buyback_active": 0.0, "report_due_days": 49.0,
                "forecast_flag": 0.0, "eq_flags": 2.0, "intel_red": 1.0}]),
            "a_unlocks.csv": pd.DataFrame([{
                "code": "688795", "name": "摩尔线程-U",
                "free_date": "2026-09-12", "unlock_pct": 12.0,
                "lift_cap_wan": 1070000.0}]),
            "a_financials.csv": pd.DataFrame([{
                "code": "688795", "report_date": "2026-06-30",
                "rev_yoy": 22.0, "profit": 1.0e9, "deduct_eps": 0.3,
                "basic_eps": 0.5}]),
        }
        snap = _snap(tmp_path, files)
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": [
                                type("I", (), {"__dict__": {}})()])
        # Simpler: monkeypatch to real IntelItems
        from value_genie.intel.model import IntelItem
        notice = IntelItem(market="A", code="688795", name="摩尔线程-U",
                           subsystem="announcements", kind="notice",
                           event_date=date(2026, 9, 7), title="投资者关系活动",
                           source="eastmoney", impact="neutral",
                           payload={})
        rating = IntelItem(market="A", code="688795", name="摩尔线程-U",
                           subsystem="ratings", kind="rating",
                           event_date=date(2026, 8, 22), title="国金证券 买入",
                           source="eastmoney", impact="positive",
                           payload={"org": "国金证券", "rating": "买入"})
        news = IntelItem(market="A", code="688795", name="摩尔线程-U",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="解禁报道",
                         source="eastmoney", impact="neutral",
                         payload={"media": "每经"})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": [notice])
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": [rating])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [news])
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        assert result["match"].code == "688795"
        assert result["radar"]["unlock_pct_30d"] == 12.0
        kinds = [i.kind for i in result["events"]]
        assert "unlock" in kinds
        assert len(result["notices"]) == 1
        assert len(result["ratings"]) == 1
        assert result["ratings"][0].impact == "positive"
        assert len(result["news"]) == 1
        assert "missing" not in result["eq"]      # eq is a detail list

    def test_section_failure_is_missing_not_error(self, tmp_path, monkeypatch):
        snap = _snap(tmp_path, {})     # empty snapshot dir, no master
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)   # source failure
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": None)
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        assert result["notices"] == {"missing": "notice source failed"}
        assert result["ratings"] == {"missing": "ratings source failed"}
        assert result["news"] == {"missing": "news source failed"}
        assert result["radar"] == {}

    def test_non_a_market_degrades(self, tmp_path, monkeypatch):
        snap = _snap(tmp_path, {})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": None)
        result = ir.build_intel_report(
            Match("HK", "00700", "腾讯", 100.0, "116"),
            snapshot_dir=snap, asof=date(2026, 9, 9))
        assert result["events"] == {"missing": "P3: HK/US 未覆盖"}
        assert result["eq"] == {"missing": "P3: HK/US 未覆盖"}
```

- [ ] **Step 2: Run, verify fail**

Run: `python -B -m pytest tests/test_intel_report.py -q`
Expected: `ModuleNotFoundError` / `AttributeError` for `ir._radar_row` etc.

- [ ] **Step 3: Implement `value_genie/intel/report.py`**

```python
"""Per-stock intelligence report (情报通道, design §7).

Section assembly for ``intel X``: radar row + event details from the
snapshot's full-market batch tables (zero network for snapshot stocks),
live per-stock notices / ratings / news, earnings-quality detail.
Fail-closed per section: a failed section becomes {"missing": reason},
never fabricated data. P2 covers A-shares; HK/US degrade with an
explicit P3 note.
"""

from datetime import date, timedelta
from pathlib import Path

from .. import config
from .announcements import fetch_stock_notices
from .model import IntelItem, earnings_quality
from .news import fetch_stock_news
from .radar import (_appointment_items, _buyback_items, _eq_records,
                    _forecast_items, _holder_items, _placement_items,
                    _read_csv, _unlock_items, RADAR_COLUMNS)
from .ratings import fetch_stock_ratings

_TABLE_FETCHERS = None   # lazy: avoids circular import cost at module load


def _radar_row(snap: Path | None, market: str, code: str) -> dict | None:
    """雷达行 from master/watchlist (照 analyze._snapshot_factors 模式)。"""
    if snap is None:
        return None
    import pandas as pd
    for fname in ("master.csv", "watchlist.csv"):
        p = Path(snap) / fname
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
            return {c: (None if pd.isna(r.get(c)) else r.get(c))
                    for c in RADAR_COLUMNS}
    return None


def _table(name: str, snap: Path, code: str, fetcher, label: str):
    """快照批表 filter code；表缺失 → 实时单股兜底（fetcher(code=...)）。

    Returns normalized DataFrame, None on both-paths failure. The saved
    batch tables are full-market, so any A-share (in or out of the
    funnel universe) is covered without network.
    """
    df = _read_csv(Path(snap) / name)
    if df is not None:
        hit = df[df["code"].astype(str) == str(code)]
        return hit if not hit.empty else df.iloc[0:0]
    if fetcher is None:
        return None
    try:
        return fetcher()          # caller closes over code/windows
    except Exception:             # noqa: BLE001 — fail-closed per section
        return None


def _stock_events(snap: Path, code: str, asof: date) -> list:
    """事件明细 IntelItems：快照表（或单股兜底）→ radar 的 *_items。"""
    from .announcements import (fetch_a_buybacks, fetch_a_holder_changes,
                                fetch_a_placements, fetch_a_unlocks)
    from .earnings import fetch_a_appointments, fetch_a_balance, \
        fetch_a_forecasts
    lookback = (asof - timedelta(
        days=config.INTEL_LOOKBACK_DAYS)).isoformat()
    forward = (asof + timedelta(
        days=config.INTEL_FORECAST_DAYS)).isoformat()
    codes = pd.Index([code], name="code")

    unlocks = _table("a_unlocks.csv", snap, code,
                     lambda: fetch_a_unlocks(asof.isoformat(), forward,
                                             code=code), "unlocks")
    holders = _table("a_holder_changes.csv", snap, code,
                     lambda: fetch_a_holder_changes(lookback, code=code),
                     "holders")
    buybacks = _table("a_buybacks.csv", snap, code,
                      lambda: fetch_a_buybacks(lookback, code=code),
                      "buybacks")
    placements = _table("a_placements.csv", snap, code,
                        lambda: fetch_a_placements(lookback, code=code),
                        "placements")
    forecasts = _table("a_forecasts.csv", snap, code,
                       lambda: fetch_a_forecasts(lookback, code=code),
                       "forecasts")
    appoints = _table("a_appointments.csv", snap, code,
                      lambda: fetch_a_appointments(asof.isoformat(),
                                                   forward, code=code),
                      "appoints")
    items = []
    for fn, tbl in ((_unlock_items, unlocks),
                    (_holder_items, holders),
                    (_buyback_items, buybacks),
                    (_placement_items, placements),
                    (_forecast_items, forecasts),
                    (_appointment_items, appoints)):
        if tbl is None:
            continue
        items += fn(tbl, codes)
    return items


def _eq_detail(snap: Path, code: str) -> list[str] | None:
    """粉饰信号明细（中文描述列表）；输入表缺失返回 None。"""
    fin = _read_csv(Path(snap) / "a_financials.csv")
    if fin is None:
        return None
    balance = _read_csv(Path(snap) / "a_balance.csv")
    eq_recs = _eq_records(Path(snap), balance)
    if eq_recs is None:
        return None
    rec = eq_recs.get(str(code))
    if rec is None:
        return []
    descs = {
        "eq_receivables": "应收增速远超营收（回款质量恶化）",
        "eq_inventory": "存货增速远超营收（渠道压货风险）",
        "eq_ocf_gap": "经营现金流/净利润过低（利润含金量不足）",
        "eq_nonrecurring": "扣非利润占比过低（非经常性损益撑业绩）",
    }
    return [descs.get(s, s) for s in earnings_quality(rec)]


def build_intel_report(match, snapshot_dir=None,
                       asof: date | None = None) -> dict:
    """单股舆情情报 result dict（五个板块 + 雷达行，fail-closed）。"""
    snap = Path(snapshot_dir) if snapshot_dir else None
    asof = asof or date.today()
    result = {"match": match, "snapshot": snap.name if snap else None,
              "asof": asof.isoformat()}

    if match.market != "A":
        result.update({"radar": {},
                       "events": {"missing": "P3: HK/US 未覆盖"},
                       "eq": {"missing": "P3: HK/US 未覆盖"},
                       "notices": {"missing": "P3: HK/US 未覆盖"},
                       "ratings": {"missing": "P3: HK/US 未覆盖"},
                       "news": {"missing": "P3: HK/US 未覆盖"}})
        return result

    result["radar"] = _radar_row(snap, "A", match.code) or {}
    result["events"] = (_stock_events(snap, match.code, asof)
                        if snap else [])

    eq = _eq_detail(snap, match.code) if snap else None
    result["eq"] = ({"missing": "财报输入表缺失"} if eq is None else eq)

    notices = fetch_stock_notices(match.code, name=match.name)
    result["notices"] = ({"missing": "notice source failed"}
                         if notices is None else notices)
    ratings = fetch_stock_ratings(match.code, name=match.name)
    result["ratings"] = ({"missing": "ratings source failed"}
                         if ratings is None else ratings)
    news = fetch_stock_news(match.market_id or "0", match.code,
                            name=match.name)
    result["news"] = ({"missing": "news source failed"}
                      if news is None else news)
    return result
```

Notes for the implementer:
- `_stock_events` needs `import pandas as pd` at module top (used for `pd.Index`) — add it with the other imports and drop the local import inside `_radar_row`.
- `radar._eq_records(snap, balance)` returns `{code: rec}` or None when the balance table is None; feeding a None balance (a_balance.csv missing) gives None → eq section reports missing. That is intended for old snapshots; the live fallback for balance is omitted deliberately (YAGNI — snapshot always writes it since P1).
- `_table`'s `label` parameter is only for logging; keep the signature but logging is optional (quiet by default).

- [ ] **Step 4: Run, verify pass**

Run: `python -B -m pytest tests/test_intel_report.py -q`

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/report.py tests/test_intel_report.py
git commit -m "feat(intel): per-stock intelligence assembly (build_intel_report)"
```

---

### Task 6: report.py — render_intel + to_json

**Files:**
- Modify: `value_genie/intel/report.py`
- Test: `tests/test_intel_report.py`

Render format (design §7, adapted to verified data shapes):

```
== 舆情情报: 摩尔线程-U (A/688795) ==
[事件雷达] 解禁30天 12.0% | 90天 12.0% | 减持计划 无 | 增发 无 | 回购 无 | 财报预约 49天 | 预告方向 0 | 粉饰信号 2 | intel_red=1
[事件明细] 2 条: 09-12 限售解禁 12.0% 总股本 · 08-28 股东减持 ...
[公告时间线] 近90天 3 条（最近: 09-07 投资者关系活动记录表 | 08-28 限售股份上市流通 ...）
[财报信号] 粉饰信号 2 项: 应收增速远超营收（回款质量恶化）; 经营现金流/净利润过低（利润含金量不足）
[投行评级] 近1年 5 份（最近: 08-22 国金证券 买入 ←增持）
[新闻时间线] 近30天 17 条（最近: 09-08 摩尔线程超100亿元限售股解禁… · 每日经济新闻）
data as of: radar: snapshot 20260909; notices/ratings/news: live 2026-09-09
```

Missing sections render as `[公告时间线] 数据缺失: notice source failed` (AGENTS.md rule 4 — say what is missing, never improvise).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_intel_report.py`)

```python
# ---------------------------------------------------------------------------
# Rendering + JSON
# ---------------------------------------------------------------------------
from value_genie.intel.model import IntelItem


def _full_result(tmp_path, monkeypatch):
    files = {"master.csv": pd.DataFrame([{
        "market": "A", "code": "688795", "name": "摩尔线程-U",
        "unlock_pct_30d": 12.0, "unlock_pct_90d": 12.0,
        "holder_cut_flag": 0.0, "dilution_flag": 0.0,
        "buyback_active": 0.0, "report_due_days": 49.0,
        "forecast_flag": 0.0, "eq_flags": 2.0, "intel_red": 1.0}])}
    snap = _snap(tmp_path, files)
    notice = IntelItem(market="A", code="688795", name="摩尔线程-U",
                       subsystem="announcements", kind="notice",
                       event_date=date(2026, 9, 7), title="投资者关系活动",
                       url="http://d/1.html", source="eastmoney",
                       impact="neutral", payload={"category": "调研活动"})
    rating = IntelItem(market="A", code="688795", name="摩尔线程-U",
                       subsystem="ratings", kind="rating",
                       event_date=date(2026, 8, 22), title="国金证券 买入",
                       source="eastmoney", impact="positive",
                       payload={"org": "国金证券", "rating": "买入",
                                "last_rating": "增持"})
    news = IntelItem(market="A", code="688795", name="摩尔线程-U",
                     subsystem="news", kind="news",
                     event_date=date(2026, 9, 8), title="解禁报道",
                     source="eastmoney", impact="neutral",
                     payload={"media": "每经"})
    monkeypatch.setattr(ir, "fetch_stock_notices",
                        lambda c, name="": [notice])
    monkeypatch.setattr(ir, "fetch_stock_ratings",
                        lambda c, name="": [rating])
    monkeypatch.setattr(ir, "fetch_stock_news",
                        lambda mid, c, name="": [news])
    return ir.build_intel_report(_match(), snapshot_dir=snap,
                                 asof=date(2026, 9, 9))


class TestRenderIntel:
    def test_renders_all_sections(self, tmp_path, monkeypatch):
        result = _full_result(tmp_path, monkeypatch)
        text = ir.render_intel(result)
        assert "舆情情报: 摩尔线程-U (A/688795)" in text
        assert "[事件雷达]" in text and "intel_red=1" in text
        assert "解禁30天 12.0%" in text
        assert "[公告时间线]" in text and "投资者关系活动" in text
        assert "[投行评级]" in text and "国金证券 买入" in text
        assert "[新闻时间线]" in text and "解禁报道" in text
        assert "data as of:" in text

    def test_missing_section_says_so(self, tmp_path, monkeypatch):
        snap = _snap(tmp_path, {})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": None)
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        text = ir.render_intel(result)
        assert "数据缺失: notice source failed" in text
        assert "数据缺失: ratings source failed" in text
        assert "数据缺失: news source failed" in text


class TestIntelJson:
    def test_to_json_is_pure_and_parseable(self, tmp_path, monkeypatch):
        result = _full_result(tmp_path, monkeypatch)
        payload = json.loads(ir.to_json(result))
        assert payload["match"]["code"] == "688795"
        assert payload["radar"]["unlock_pct_30d"] == 12.0
        assert payload["notices"][0]["kind"] == "notice"
        assert payload["ratings"][0]["payload"]["rating"] == "买入"
        assert payload["eq"] == [] or isinstance(payload["eq"], list)

    def test_to_json_missing_section_null(self, tmp_path, monkeypatch):
        snap = _snap(tmp_path, {})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [])
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        payload = json.loads(ir.to_json(result))
        assert payload["notices"] is None      # missing -> null
        assert payload["ratings"] == []
```

(Add `import json` to the test file header.)

- [ ] **Step 2: Run, verify fail** (`ir.render_intel` / `ir.to_json` missing)

Run: `python -B -m pytest tests/test_intel_report.py -q -k "render or json"`

- [ ] **Step 3: Implement** (append to `value_genie/intel/report.py`)

```python
# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _items_block(items, limit=3) -> str:
    if not items:
        return "0 条"
    head = " · ".join(f"{i.event_date.strftime('%m-%d')} {i.title}"
                      for i in items[:limit])
    more = f" …(+{len(items) - limit})" if len(items) > limit else ""
    return f"{len(items)} 条（最近: {head}{more}）"


def _radar_line(radar: dict) -> str:
    if not radar:
        return "快照无雷达行（快照外股票或旧快照）"

    def _n(key, fmt="{:.1f}", default="无"):
        v = radar.get(key)
        if v is None:
            return default
        try:
            return fmt.format(float(v))
        except (TypeError, ValueError):
            return default

    due = radar.get("report_due_days")
    due_s = ("无预约" if due is None or float(due) >= 999
             else f"{int(float(due))}天")
    return (f"解禁30天 {_n('unlock_pct_30d')}% | "
            f"90天 {_n('unlock_pct_90d')}% | "
            f"减持计划 {'有' if _n('holder_cut_flag', '{:.0f}') == '1' else '无'} | "
            f"增发 {'有' if _n('dilution_flag', '{:.0f}') == '1' else '无'} | "
            f"回购 {'有' if _n('buyback_active', '{:.0f}') == '1' else '无'} | "
            f"财报预约 {due_s} | "
            f"预告方向 {_n('forecast_flag', '{:.0f}')} | "
            f"粉饰信号 {_n('eq_flags', '{:.0f}')} | "
            f"intel_red={_n('intel_red', '{:.0f}')}")


def _fmt_num(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def render_intel(result: dict) -> str:
    m = result["match"]
    lines = [f"== 舆情情报: {m.name} ({m.market}/{m.code}) =="]
    lines.append(f"[事件雷达] {_radar_line(result.get('radar') or {})}")
    events = result.get("events")
    if isinstance(events, dict):
        lines.append(f"[事件明细] 数据缺失: {events.get('missing', '')}")
    else:
        lines.append(f"[事件明细] {_items_block(events)}")

    eq = result.get("eq")
    if isinstance(eq, dict):
        lines.append(f"[财报信号] 数据缺失: {eq.get('missing', '')}")
    elif eq:
        lines.append("[财报信号] 粉饰信号 "
                     f"{len(eq)} 项: " + "; ".join(eq))
    else:
        lines.append("[财报信号] 无粉饰信号")

    notices = result.get("notices")
    if isinstance(notices, dict):
        lines.append(f"[公告时间线] 数据缺失: {notices.get('missing', '')}")
    else:
        lines.append(f"[公告时间线] 近{config.INTEL_NOTICE_DAYS}天 "
                     f"{_items_block(notices)}")

    ratings = result.get("ratings")
    if isinstance(ratings, dict):
        lines.append(f"[投行评级] 数据缺失: {ratings.get('missing', '')}")
    else:
        latest = (f"最近: {ratings[0].event_date.strftime('%m-%d')} "
                  f"{ratings[0].title}"
                  + (f" ←{ratings[0].payload.get('last_rating')}"
                     if ratings[0].payload.get("last_rating") else "")
                  ) if ratings else "无研报"
        lines.append(f"[投行评级] 近{config.INTEL_RATING_DAYS}天 "
                     f"{len(ratings)} 份（{latest}）")

    news = result.get("news")
    if isinstance(news, dict):
        lines.append(f"[新闻时间线] 数据缺失: {news.get('missing', '')}")
    else:
        media = (f" · {news[0].payload.get('media', '')}"
                 if news and news[0].payload.get("media") else "")
        head = (f"最近: {news[0].event_date.strftime('%m-%d')} "
                f"{news[0].title}{media}") if news else "无新闻"
        lines.append(f"[新闻时间线] 近{config.INTEL_NEWS_DAYS}天 "
                     f"{len(news)} 条（{head}）"
                     "——热度供 AI 结合语境解读，不自动打分")

    snap = result.get("snapshot")
    lines.append(f"data as of: radar/events/eq: snapshot {snap or '无'}; "
                 f"notices/ratings/news: live {result['asof']}")
    return "\n".join(lines)


def to_json(result: dict) -> str:
    """Pure-JSON contract: sections missing → null, items → item dicts."""
    import json

    def _items(sec):
        v = result.get(sec)
        if isinstance(v, dict) or v is None:
            return None
        return [item_to_row(i) for i in v]

    from .model import item_to_row
    payload = {
        "match": {"market": result["match"].market,
                  "code": result["match"].code,
                  "name": result["match"].name},
        "snapshot": result.get("snapshot"),
        "asof": result.get("asof"),
        "radar": result.get("radar") or None,
        "events": _items("events"),
        "eq": (None if isinstance(result.get("eq"), dict)
               else result.get("eq")),
        "notices": _items("notices"),
        "ratings": _items("ratings"),
        "news": _items("news"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
```

Move `from .model import IntelItem, earnings_quality, item_to_row` to the top-of-file import block while adding this (drop the local import in `to_json`).

- [ ] **Step 4: Run, verify pass**

Run: `python -B -m pytest tests/test_intel_report.py -q`

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/report.py tests/test_intel_report.py
git commit -m "feat(intel): intel X rendering + pure JSON output"
```

---

### Task 7: CLI intel subcommand

**Files:**
- Modify: `value_genie/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli.py`, inside/near `TestAsk` conventions)

```python
class TestIntelCmd:
    def _patch(self, monkeypatch, report_result):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "688795", "摩尔线程-U", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.intel.report.build_intel_report",
            lambda m, snapshot_dir=None, asof=None: report_result)

    def _result(self):
        return {"match": Match("A", "688795", "摩尔线程-U", 100.0, "1"),
                "snapshot": "20260909", "asof": "2026-09-09",
                "radar": {"unlock_pct_30d": 12.0, "intel_red": 1.0},
                "events": [], "eq": [],
                "notices": [], "ratings": [], "news": []}

    def test_renders_report(self, capsys, monkeypatch):
        self._patch(monkeypatch, self._result())
        rc = main(["intel", "摩尔线程"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "舆情情报: 摩尔线程-U (A/688795)" in out
        assert "[事件雷达]" in out

    def test_json_pure_stdout(self, capsys, monkeypatch):
        self._patch(monkeypatch, self._result())
        rc = main(["intel", "摩尔线程", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["match"]["code"] == "688795"

    def test_no_match_returns_2(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr("value_genie.resolve.resolve",
                            lambda q, **k: [])
        rc = main(["intel", "不存在股"])
        assert rc == 2

    def test_freshness_fail_blocks(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("FAIL", "no snapshot"))
        rc = main(["intel", "摩尔线程"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "[FRESHNESS BLOCKED]" in captured.err

    def test_no_check_skips_gate(self, capsys, monkeypatch):
        called = []
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: called.append(1) or ("FAIL", "x"))
        self._patch(monkeypatch, self._result())
        rc = main(["intel", "摩尔线程", "--no-check"])
        assert rc == 0
        assert called == []
```

Note: `json` is already imported in test_cli.py; `Match` likewise. Check the imports at the top of the file and reuse them.

- [ ] **Step 2: Run, verify fail**

Run: `python -B -m pytest tests/test_cli.py -q -k IntelCmd`
Expected: argparse error `invalid choice: 'intel'` → rc 2.

- [ ] **Step 3: Implement** in `value_genie/__main__.py`

Command function (next to `cmd_ask`):

```python
def cmd_intel(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import resolve as rs
    from .intel import report as intel_report
    try:
        snap = report.resolve_snapshot(args.data_dir)
    except FileNotFoundError:
        snap = None
    matches = rs.resolve(args.query, snapshot_dir=snap)
    if not matches:
        print(f"no match for {args.query!r}; try a full name or code",
              file=sys.stderr)
        return 2
    m = matches[0]
    if len(matches) > 1:
        others = ", ".join(x.label() for x in matches[1:4])
        print(f"resolved: {m.label()} (also matched: {others})",
              file=sys.stderr)
    result = intel_report.build_intel_report(m, snapshot_dir=snap)
    if args.json:
        print(intel_report.to_json(result))
    else:
        print(intel_report.render_intel(result))
    return 0
```

Parser registration (next to the `ask` parser inside `build_parser`):

```python
pi = sub.add_parser("intel", help="per-stock intelligence report (舆情)")
pi.add_argument("query", help="stock name, code or ticker (Chinese ok)")
pi.add_argument("--json", action="store_true",
                help="machine-readable JSON output")
pi.add_argument("--data-dir", default=None, help="data directory")
pi.add_argument("--no-check", action="store_true",
               help="skip freshness gate (for automated pipelines)")
pi.set_defaults(func=cmd_intel)
```

Check how `report` is imported at module level in `__main__.py` (cmd_ask uses `report.resolve_snapshot`) — reuse the same module-level import; the intel module is imported with the explicit alias `intel_report` to avoid the basename clash.

- [ ] **Step 4: Run, verify pass**

Run: `python -B -m pytest tests/test_cli.py -q -k IntelCmd`

- [ ] **Step 5: Commit**

```bash
git add value_genie/__main__.py tests/test_cli.py
git commit -m "feat(intel): intel X CLI subcommand (freshness-gated)"
```

---

### Task 8: ask integration (intel key + risk flags + verdict wording)

**Files:**
- Modify: `value_genie/analyze.py`
- Test: `tests/test_cli.py` (or `tests/test_analyze.py` if it exists — check first; P1 tests live in test_cli.py, follow that)

Design §7.1: `analyze_stock()` gains an `intel` key (radar row); `risk_flags()` appends an `intel red` flag listing the concrete triggers; `render_brief` verdict line gains a `[intel red flag]` suffix when `intel_red == 1`; `_as_of` gains `intel: snapshot`. Verdict algorithm itself is untouched — 否决权在 gates，不在得分.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli.py`)

```python
class TestAskIntelIntegration:
    def _fake_result(self, intel=None):
        base = fake_result(Match("A", "688795", "摩尔线程-U", 100.0, "1"))
        base["intel"] = intel or {}
        return base

    def test_risk_flag_when_intel_red(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "688795", "摩尔线程-U", 100.0, "1")])
        result = self._fake_result(intel={
            "unlock_pct_30d": 12.0, "unlock_pct_90d": 12.0,
            "holder_cut_flag": 1.0, "dilution_flag": 0.0,
            "eq_flags": 2.0, "intel_red": 1.0})
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: result)
        rc = main(["ask", "摩尔线程"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "intel red" in out
        assert "解禁" in out and "减持" in out

    def test_no_flag_when_clean(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "688795", "摩尔线程-U", 100.0, "1")])
        result = self._fake_result(intel={
            "unlock_pct_30d": 0.0, "holder_cut_flag": 0.0,
            "dilution_flag": 0.0, "eq_flags": 0.0, "intel_red": 0.0})
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: result)
        rc = main(["ask", "摩尔线程"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "intel red" not in out
```

Check `fake_result` in test_cli.py (P1 survey: L194-200) — it builds a minimal result dict; the test adds `intel` on top. If `fake_result` already includes `risk_flags`, the appended intel flag must come from the real `risk_flags()` function — if `fake_result` stubs risk_flags as a static list, adjust the fake to call the real one for the intel key (`from value_genie.analyze import risk_flags; base["risk_flags"] = risk_flags(base)`).

- [ ] **Step 2: Run, verify fail**

Run: `python -B -m pytest tests/test_cli.py -q -k IntelIntegration`
Expected: fail — brief output has no "intel red" line (render doesn't know the key yet).

- [ ] **Step 3: Implement** in `value_genie/analyze.py`

(a) Radar-row reader (next to `_snapshot_factors`):

```python
def _intel_factors(snap, market: str, code: str) -> dict:
    """Intel radar row from master/watchlist (P1 radar columns)."""
    if snap is None:
        return {}
    from .intel.radar import RADAR_COLUMNS
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
            return {c: (None if pd.isna(r.get(c)) else r.get(c))
                    for c in RADAR_COLUMNS if c in df.columns}
    return {}
```

(b) In `analyze_stock()`, after `result["cashflow_factors"] = ...`:

```python
    result["intel"] = _intel_factors(snap, match.market, match.code)
```

(c) In `risk_flags()`, after the `borrowed_dividend` check, before the warnings block:

```python
    intel = result.get("intel") or {}

    def _inum(col):
        v = intel.get(col)
        try:
            f = float(v)
            return None if f != f else f
        except (TypeError, ValueError):
            return None

    if _inum("intel_red") == 1:
        triggers = []
        v = _inum("unlock_pct_30d")
        if v is not None and v >= config.UNLOCK_RED_PCT:
            triggers.append(f"30天解禁 {v:.1f}%")
        if _inum("holder_cut_flag") == 1:
            triggers.append("减持计划进行中")
        if _inum("dilution_flag") == 1:
            triggers.append("增发摊薄")
        v = _inum("eq_flags")
        if v is not None and v >= config.EQ_FLAG_RED:
            triggers.append(f"财报粉饰信号 {int(v)} 项")
        flags.append("intel red: " + "；".join(triggers)
                     if triggers else "intel red: 红旗汇总触发")
```

Add `from . import config` to analyze.py imports if absent (check — it likely already imports config for DEFAULT_PRESET).

(d) In `render_brief()`, verdict line — find the line that appends `result["verdict"]` and extend:

```python
    verdict = str(result.get("verdict") or "")
    if (result.get("intel") or {}).get("intel_red") == 1:
        verdict += " [intel red flag]"
```

Use `verdict` in the printed line instead of `result["verdict"]` (leave the dict value untouched — the algorithm is not modified).

(e) In `_as_of()`, append after the kline part:

```python
    if result.get("intel") is not None and result.get("snapshot"):
        parts.append(f"intel: snapshot {result['snapshot']}")
```

- [ ] **Step 4: Run, verify pass — then full suite**

Run: `python -B -m pytest tests/test_cli.py -q -k IntelIntegration`
Then: `python -B -m pytest tests -q` (whole suite — brief render changes can ripple into other ask tests).

- [ ] **Step 5: Commit**

```bash
git add value_genie/analyze.py tests/test_cli.py
git commit -m "feat(intel): ask integration - intel key, risk flags, verdict wording"
```

---

### Task 9: Full suite + live verification + Field Note + push

**Files:** No new source files.

- [ ] **Step 1: Full test suite**

Run: `python -B -m pytest tests -q`
Expected: all pass (P1 481 + new ~40).

- [ ] **Step 2: Live verification — Moore Threads as the touchstone**

The stock that motivated the whole intel system. Freshness gate applies (snapshot 20260909 < 24h old at time of writing; if stale, run fetch first or use --no-check for the smoke test only):

```bash
python -m value_genie intel 摩尔线程
python -m value_genie intel 摩尔线程 --json
python -m value_genie ask 摩尔线程
```

Verify by reading the output:
- `intel` console: five sections present; 事件雷达 shows the Dec unlock (probe showed 920174-like unlock rows exist for it — check `unlock_pct_90d` non-zero); 公告时间线 non-empty (调研活动/解禁公告 observed 2026-09-07/08-28); 投行评级 non-empty (国金证券 08-22 买入 observed); 新闻时间线 non-empty (解禁报道 observed); no `数据缺失` lines.
- `intel --json`: `json.loads` clean; `radar.unlock_pct_90d` > 0; `ratings[0].payload.rating` present.
- `ask`: `intel red` flag present if radar row says intel_red=1 (check master.csv first: `unlock_pct_30d` for 688795 — the Dec unlock is beyond 30d so intel_red may be 0; that is correct behavior, state it in the verification note, do NOT fudge).
- Also smoke a snapshot-outside stock to exercise the live fallback: pick an A-share NOT in master.csv/watchlist.csv (e.g. a random loss-maker code from a_quotes.csv) and run `intel <code> --no-check`; expect 事件明细/eq to come from the snapshot batch tables (they are full-market) and render normally.

- [ ] **Step 3: Record the probe/endpoint knowledge as a Field Note**

```bash
python -m value_genie skill note data-ops "intel P2 live check (2026-09-09): np-anotice-stock /reportapi / np-listapi endpoints verified; np-listapi success envelope is code==1 (not 0); reportapi ratingChange 3=maintain observed with rating==last_rating, 1=downgrade 2=upgrade per EM convention; indvAimPriceT/L target price usually EMPTY for A-shares — render '—', never fabricate; mTypeAndCode prefix == Match.market_id (1=SH, 0=SZ+BJ)"
```

- [ ] **Step 4: Final commit + push the feature branch** (NEVER push main — repo rule; user opens/merges the PR on GitHub)

```bash
git add -A
git commit -m "test(intel): live verification notes"
git push -u origin feat/intel-gates-p2
```

Note: `git add -A` here is safe because probe files `_probe_p2*.py` are deleted in Step 2's cleanup — delete them right after the live check, before this commit:

```bash
git rm --cached _probe_p2.py _probe_p2b.py _probe_p2c.py 2>/dev/null; rm -f _probe_p2.py _probe_p2b.py _probe_p2c.py
```

(Or simply `DeleteFile` them; they are untracked so plain deletion suffices — do NOT commit probe files.)

---

## Self-review notes (checked during planning)

1. **Spec coverage vs design §7:** five sections ✅ (radar/events/notices/eq/ratings/news — events+radar map to the 事件雷达/事件明细 lines), resolve chain ✅ (Task 7), freshness gate ✅ (Task 7), snapshot-outside fallback ✅ (Task 5 `_table` + Task 4 `code` params), --json ✅ (Task 6), ask integration ✅ (Task 8), fail-closed ✅ (per-section missing, Task 5/6). P4 items (gates, recommend/holding block, skill 16, AGENTS/README) intentionally excluded.
2. **No placeholders:** every code step carries full code; the only "check first" items are import-level facts (test file imports, `config` already imported in analyze.py) that the implementer verifies with a Read — cheap and safe.
3. **Type consistency:** `build_intel_report(match, snapshot_dir=None, asof=None) -> dict` used identically in Tasks 5/6/7; `fetch_stock_notices(code, name="", days=None)` monkeypatched with `lambda c, name=""` consistently; IntelItem field names match model.py; `Match(market, code, name, score, market_id)` positional order matches resolve.py.
4. **Known risks (flagged, not blocking):**
   - `RPTA_WEB_GPHG` single-stock filter `(SCODE="...")` unverified by probe — if it errors or silently voids (probe rule 3: non-filterable field voids the whole filter → full table returns), the buyback fallback returns the full table filtered in pandas by `_table`'s code filter anyway. Worst case: one extra request. Test asserts the filter string only, not server behavior.
   - `ratingChange` 1/2/4 semantics are convention-based (3=maintain is the only observed value). Payload keeps the raw value; impact mislabels at worst one direction word — the agent reads rating vs last_rating.
   - np-listapi `Art_ShowTime` for scheduled-future articles — window filter uses `when < since` (only drops old), future-dated items pass through; fine for a timeline.
