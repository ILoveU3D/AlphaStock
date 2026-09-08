# Intel HK/US Coverage (P3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `intel X` per-stock intelligence command from A-shares to HK and US markets (news / notices / ratings sections), with explicit fail-closed degradation where no source exists.

**Architecture:** All validated endpoints reuse the existing intel subsystem modules — news.py generalizes to three markets via Eastmoney's `np-listapi` (prefix 116=HK, 105/106=US), announcements.py adds HK (`ann_type=H` mirror) and US (EDGAR submissions timeline), ratings.py adds US consensus from stockanalysis.com's embedded flight-data blob. report.py drops its P2 "A-shares only" early-return and wires per-market sections. Radar batch tables stay A-only (documented limitation). Every section fails closed: missing source → `{"missing": reason}`, never fabricated.

**Tech Stack:** Python 3.10+, pandas, requests (already vendored in global env — never add dependencies).

**Probe-validated endpoints (2026-09-09, see Field Notes):**
- HK notices: `np-anotice-stock` with `ann_type="H"`, `stock_list="00700"` — same response shape as A; detail URL template `data.eastmoney.com/notices/detail/{code}/{art}.html` works for HK codes (HTTP 200 verified).
- HK/US news: `np-listapi` `mTypeAndCode="116.00700"` / `"105.AAPL"` / `"106.IBM"` — identical shape to A-share news. AMEX prefix `107` returns empty data (limitation).
- HK research reports: **no source found** — `reportapi` qType=0/1 both return 0 hits for HK codes; the HK research page XHR was hunted across probes p3c–p3h without success. Degrade with explicit note.
- US filings: `data.sec.gov/submissions/CIK{cik:010d}.json` — `filings.recent` parallel arrays (accessionNumber, filingDate, form, primaryDocument, items, reportDate), newest-first, ~1000 filings deep (90-day window needs no pagination).
- US ratings: `stockanalysis.com/stocks/{slug}/ratings/` — Next.js flight data embedded in HTML: `widget:{all:{count:44,consensus:"Buy",price_target:324.53,currency:"USD"}}` + `ratings:[{action_rt,pt_now,pt_old,firm,analyst,date,rating_new,rating_old,time,...}]`. Parse = quote-aware balanced bracket scan + bare-key quoting + leading-dot float fix (`stars:.6` → `0.6`). Verified live: 8 ratings parsed for AAPL.

---

### Task 1: config constants + SA fetcher with get_text

**Files:**
- Modify: `value_genie/config.py` (after `EM_REPORT_URL` block, ~line 259)
- Modify: `value_genie/fetch/http.py` (Fetcher class + singleton block)
- Test: `tests/test_http.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_http.py` (follow its existing `patch.object(f.session, "get")` mocking style):

```python
class TestGetText:
    def test_returns_body_on_200(self):
        f = Fetcher({"User-Agent": "test"}, "T")
        resp = _FakeResp(200, b"<html>hi</html>")
        with patch.object(f.session, "get", return_value=resp):
            assert f.get_text("http://x") == "<html>hi</html>"

    def test_none_on_404(self):
        f = Fetcher({"User-Agent": "test"}, "T")
        resp = _FakeResp(404, b"nope")
        with patch.object(f.session, "get", return_value=resp):
            assert f.get_text("http://x") is None
```

If `tests/test_http.py` has no `_FakeResp` helper, add it first (check the file; it likely already has an equivalent — reuse that name and skip redefining):

```python
class _FakeResp:
    def __init__(self, status, body=b"", text=""):
        self.status_code = status
        self._body = body
        self.text = text
        self.encoding = "utf-8"
    def iter_content(self, chunk_size=65536):
        yield self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_http.py -q`
Expected: FAIL — `AttributeError: 'Fetcher' object has no attribute 'get_text'`

- [ ] **Step 3: Implement**

In `value_genie/config.py`, after the `INTEL_RATING_DAYS` line (~259):

```python
SEC_SUBMISSIONS_URL_TMPL = ("https://data.sec.gov/submissions/"
                            "CIK{cik:010d}.json")
EDGAR_DOC_URL_TMPL = ("https://www.sec.gov/Archives/edgar/data/"
                      "{cik}/{acc}/{doc}")
SA_RATINGS_URL_TMPL = "https://stockanalysis.com/stocks/{slug}/ratings/"
INTEL_FILING_DAYS = 90      # US EDGAR 披露文件回看窗口（天）
US_NEWS_PREFIXES = ("105", "106")   # np-listapi 美股前缀（NASDAQ/NYSE）
```

In `value_genie/fetch/http.py`, add a `get_text` method to `Fetcher` right after `get_json` (same retry skeleton, returns decoded text):

```python
    def get_text(self, url, params=None, timeout=20, retries=2,
                 cooldown_after=5, cooldown_sec=75, total_timeout=None):
        """GET a URL and return the body as text (for HTML pages).
        None on persistent failure; 404 counts as no data."""
        total_timeout = total_timeout or max(45, timeout * 3)
        last_err = None
        attempt = 0
        total_attempts = retries + 1
        while attempt < total_attempts:
            attempt += 1
            try:
                deadline = time.monotonic() + total_timeout
                with self.session.get(url, params=params, timeout=timeout,
                                      stream=True) as r:
                    chunks = []
                    for chunk in r.iter_content(chunk_size=65536):
                        chunks.append(chunk)
                        if time.monotonic() > deadline:
                            raise requests.Timeout(
                                f"download exceeded {total_timeout}s")
                    body = b"".join(chunks)
                    status = r.status_code
                    enc = r.encoding or "utf-8"
                if status == 200:
                    self.consecutive_fail = 0
                    return body.decode(enc, errors="replace")
                if status == 404:
                    self.consecutive_fail = 0
                    return None
                last_err = f"HTTP {status}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
            self.consecutive_fail += 1
            if self.consecutive_fail >= cooldown_after and attempt < total_attempts:
                print(f"    [cooldown] {self.name} failed "
                      f"{self.consecutive_fail}x ({last_err}), "
                      f"sleeping {cooldown_sec}s...", file=sys.stderr)
                time.sleep(cooldown_sec)
            else:
                time.sleep(2.0 * attempt)
        print(f"    [warn] {self.name} request failed: {url[:70]} -> "
              f"{last_err}", file=sys.stderr)
        return None
```

Add the SA singleton after `EM_WEB`:

```python
SA = Fetcher({"User-Agent": config.EM_UA}, "SA")  # stockanalysis.com HTML
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_http.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/config.py value_genie/fetch/http.py tests/test_http.py
git commit -m "feat(intel): SA fetcher (get_text) + P3 endpoint constants"
```

---

### Task 2: model.py — filing / consensus kinds

**Files:**
- Modify: `value_genie/intel/model.py` (IMPACT_BY_KIND dict)
- Test: `tests/test_intel_model.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intel_model.py`:

```python
def test_impact_filing_and_consensus():
    assert model.IMPACT_BY_KIND["filing"] == "neutral"
    assert model.IMPACT_BY_KIND["consensus"] == "neutral"
```

(Adjust the import alias to match the file's existing import style — check the top of the test file first.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_intel_model.py -q`
Expected: FAIL — KeyError

- [ ] **Step 3: Implement**

In `IMPACT_BY_KIND` (value_genie/intel/model.py), after the `"notice"` entry:

```python
    "notice": "neutral",
    "filing": "neutral",       # US EDGAR disclosure (AI reads form type)
    "consensus": "neutral",    # US analyst consensus snapshot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_intel_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/model.py tests/test_intel_model.py
git commit -m "feat(intel): filing/consensus impact kinds for P3"
```

---

### Task 3: news.py — three-market news timeline + US prefix fallback

**Files:**
- Modify: `value_genie/intel/news.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intel_sources.py` (reuse its existing fixture/monkeypatch style for `EM_WEB.get_json`; check the file first and mirror it):

```python
def _news_raw(show_time="2026-09-08 10:00:00", title="腾讯新闻"):
    return {"code": 1, "data": {"list": [{
        "Art_ShowTime": show_time, "Art_Title": title,
        "Art_Url": "http://finance.eastmoney.com/a/1.html",
        "Art_MediaName": "证券日报"}]}}


class TestFetchStockNewsMultiMarket:
    def test_hk_market_tag(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params["mTypeAndCode"])
            return _news_raw()

        monkeypatch.setattr(news.EM_WEB, "get_json", fake)
        items = news.fetch_stock_news("116", "00700", "腾讯控股",
                                      market="HK")
        assert calls == ["116.00700"]
        assert items[0].market == "HK"
        assert items[0].code == "00700"

    def test_us_market_tag(self, monkeypatch):
        monkeypatch.setattr(news.EM_WEB, "get_json",
                            lambda url, params=None, **kw: _news_raw(
                                title="Apple news"))
        items = news.fetch_stock_news("105", "AAPL", "Apple", market="US")
        assert items[0].market == "US"
        assert items[0].code == "AAPL"

    def test_us_blank_prefix_falls_back(self, monkeypatch):
        tried = []

        def fake(url, params=None, **kw):
            tried.append(params["mTypeAndCode"])
            if params["mTypeAndCode"].startswith("105."):
                return {"code": 1, "data": {}}   # wrong exchange: empty
            return _news_raw(title="NYSE story")

        monkeypatch.setattr(news.EM_WEB, "get_json", fake)
        items = news.fetch_stock_news("", "IBM", "IBM", market="US")
        assert tried == ["105.IBM", "106.IBM"]
        assert items and items[0].payload.get("media") == "证券日报"

    def test_us_all_prefixes_empty_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(news.EM_WEB, "get_json",
                            lambda url, params=None, **kw:
                            {"code": 1, "data": {}})
        assert news.fetch_stock_news("", "XYZ", "XYZ", market="US") == []

    def test_source_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(news.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert news.fetch_stock_news("116", "00700", market="HK") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k news`
Expected: FAIL — `fetch_stock_news() got an unexpected keyword argument 'market'`

- [ ] **Step 3: Implement**

Rewrite `value_genie/intel/news.py` body — extract `_news_once`, parametrize market, add US fallback:

```python
"""News subsystem (P2: A-share per-stock timeline; P3: HK/US, design §4).

np-listapi wap getListInfo — per-stock CMS news feed, one endpoint for
all three markets (mTypeAndCode prefix: 1/0=A, 116=HK, 105/106=US).
No sentiment scoring by design (design §1 non-goal): items carry neutral
impact and the AI agent interprets heat/context.
"""

from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from .model import IntelItem


def _news_once(market: str, market_id: str, code: str, name: str,
               days: int) -> list | None:
    """One np-listapi call. Source failure → None (fail-closed)."""
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
            market=market, code=code, name=name,
            subsystem="news", kind="news",
            event_date=date.fromisoformat(when),
            title=str(r.get("Art_Title") or ""),
            url=str(r.get("Art_Url") or ""),
            source="eastmoney", impact="neutral",
            payload={"media": str(r.get("Art_MediaName") or ""),
                     "show_time": str(r.get("Art_ShowTime") or "")}))
    return items


def fetch_stock_news(market_id: str, code: str, name: str = "",
                     days: int = None, market: str = "A") -> list | None:
    """近 days 天个股新闻时间线（np-listapi，A/HK/US 同一端点）。

    market_id: 东财市场前缀（A: 1=沪/0=深+北, HK: 116, US: 105/106）
    ——即 Match.market_id。US 且前缀缺失时按 NASDAQ→NYSE 顺序试
    （错交易所前缀返回空列表而非报错，AMEX 107 无数据为已知局限）。
    返回 IntelItem 列表（subsystem="news"），新→旧由接口保证；
    源失败返回 None（fail-closed），空时间线返回 []。
    """
    days = days or config.INTEL_NEWS_DAYS
    if market == "US" and not market_id:
        out = None
        for mid in config.US_NEWS_PREFIXES:
            got = _news_once("US", mid, code, name, days)
            if got:
                return got
            if got is not None:
                out = got               # remember last success-but-empty
        return out if out is not None else []
    prefix = market_id or ("116" if market == "HK" else "0")
    return _news_once(market, prefix, code, name, days)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k news`
Expected: PASS (including the pre-existing A-share news tests — they call `fetch_stock_news(market_id, code, name)` positionally, which still works)

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/news.py tests/test_intel_sources.py
git commit -m "feat(intel): three-market news timeline + US prefix fallback"
```

---

### Task 4: announcements.py — HK notices + US EDGAR filings

**Files:**
- Modify: `value_genie/intel/announcements.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intel_sources.py`:

```python
def _hk_notice_raw():
    return {"data": {"list": [{
        "art_code": "AN202609081829135004",
        "notice_date": "2026-09-08 00:00:00",
        "title": "翌日披露报表 - 已发行股份变动及股份购回",
        "columns": [{"column_code": "011005001", "column_name": "股份購回"}],
    }]}}


class TestFetchStockNoticesHK:
    def test_hk_ann_type(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params["ann_type"])
            return _hk_notice_raw()

        monkeypatch.setattr(annc.EM_WEB, "get_json", fake)
        items = annc.fetch_stock_notices("00700", "腾讯控股", market="HK")
        assert calls == ["H"]
        assert items[0].market == "HK"
        assert items[0].payload["category"] == "股份購回"
        assert "AN202609081829135004" in items[0].url


class TestFetchUsFilings:
    def _submissions(self):
        return {
            "cik": "0000320193",
            "filings": {"recent": {
                "accessionNumber": ["0000320193-26-000018",
                                    "0000320193-26-000017",
                                    "0000320193-26-000016"],
                "filingDate": ["2026-09-08", "2026-09-05", "2026-08-20"],
                "form": ["8-K", "144", "10-Q"],
                "primaryDocument": ["a1.htm", "x144.htm", "a10q.htm"],
                "items": ["Item 2.02", "", "item 2"],
                "reportDate": ["2026-09-08", "", "2026-06-30"],
            }}}

    def test_filters_material_forms_and_marks_market(self, monkeypatch):
        monkeypatch.setattr(annc, "_load_cik_map",
                            lambda: {"AAPL": 320193})
        monkeypatch.setattr(annc.SEC, "get_json",
                            lambda url, params=None, **kw:
                            self._submissions())
        items = annc.fetch_us_filings("AAPL", "Apple")
        assert [i.payload["form"] for i in items] == ["8-K", "10-Q"]
        assert all(i.market == "US" for i in items)
        assert all(i.kind == "filing" for i in items)
        assert items[0].url.startswith(
            "https://www.sec.gov/Archives/edgar/data/320193/")

    def test_days_window(self, monkeypatch):
        monkeypatch.setattr(annc, "_load_cik_map",
                            lambda: {"AAPL": 320193})
        monkeypatch.setattr(annc.SEC, "get_json",
                            lambda url, params=None, **kw:
                            self._submissions())
        items = annc.fetch_us_filings("AAPL", "Apple", days=10)
        assert [i.payload["form"] for i in items] == ["8-K"]

    def test_unknown_ticker_returns_none(self, monkeypatch):
        monkeypatch.setattr(annc, "_load_cik_map", lambda: {})
        assert annc.fetch_us_filings("NOPE") is None

    def test_edgar_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(annc, "_load_cik_map",
                            lambda: {"AAPL": 320193})
        monkeypatch.setattr(annc.SEC, "get_json",
                            lambda url, params=None, **kw: None)
        assert annc.fetch_us_filings("AAPL") is None

    def test_material_form_matcher(self):
        assert annc._is_material_form("4")
        assert annc._is_material_form("4/A")
        assert annc._is_material_form("8-K")
        assert annc._is_material_form("8-K/A")
        assert annc._is_material_form("10-Q")
        assert annc._is_material_form("SC 13G/A")
        assert annc._is_material_form("424B5")
        assert not annc._is_material_form("144")
        assert not annc._is_material_form("424B2"[0:1] + "44")  # "444"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k "HK or Filings"`
Expected: FAIL — `fetch_stock_notices() got an unexpected keyword argument 'market'` / `fetch_us_filings` not defined

- [ ] **Step 3: Implement**

In `value_genie/intel/announcements.py`:

3a. Change imports (top of file):

```python
import re
from datetime import date, timedelta

import pandas as pd

from .. import config
from ..fetch.http import EM_WEB, SEC
from ._dc import code_col, dc_report, name_col, norm_dates
from .model import IntelItem
```

3b. Change `fetch_stock_notices` signature and ann_type/IntelItem market:

```python
def fetch_stock_notices(code: str, name: str = "", days: int = None,
                        market: str = "A") -> list | None:
    """近 days 天个股公告列表（np-anotice-stock），带分类与详情 URL。

    market="A" → ann_type="A"；market="HK" → ann_type="H"（东财港股
    镜像，响应结构与 A 股一致，详情 URL 模板通用）。
    返回 IntelItem 列表（subsystem="announcements", kind="notice"，
    impact=neutral——公告性质由 AI 结合分类语境解读），源失败 None。
    """
    days = days or config.INTEL_NOTICE_DAYS
    since = (date.today() - timedelta(days=days)).isoformat()
    raw = EM_WEB.get_json(config.EM_NOTICE_URL, params={
        "sr": -1, "page_size": 50, "page_index": 1,
        "ann_type": "H" if market == "HK" else "A",
        "stock_list": code, "f_node": 0, "s_node": 0,
    })
```

(only the `ann_type` line and the `IntelItem(market=market, ...)` line change inside the loop — replace `market="A"` with `market=market` in the IntelItem constructor)

3c. Add US EDGAR filings at the end of the file:

```python
# ---------------------------------------------------------------------------
# US: EDGAR submissions timeline (P3)
# ---------------------------------------------------------------------------
EDGAR_MATERIAL_EXACT = {"4", "4/A", "3", "3/A", "25", "25-NSE",
                        "CERT", "CORRESP"}
EDGAR_MATERIAL_PREFIXES = ("8-K", "10-K", "10-Q", "S-1", "S-3", "S-4",
                           "S-8", "SC 13G", "SC 13D", "DEF 14A",
                           "DEFA14A", "424B", "FWP", "PX14A6G")


def _is_material_form(form: str) -> bool:
    """Material filing filter: insider/economic events + periodic reports
    + offerings/proxies. Drops noise (144 proposed-sale notices, S-8
    boilerplate extensions kept — cheap and occasionally relevant)."""
    if form in EDGAR_MATERIAL_EXACT:
        return True
    return any(form.startswith(p) for p in EDGAR_MATERIAL_PREFIXES)


def _load_cik_map() -> dict:
    """US ticker (Eastmoney form) -> CIK. Thin lazy wrapper so tests can
    monkeypatch without touching the fundamentals module."""
    from ..fetch.fundamentals import load_sec_cik_map
    return load_sec_cik_map() or {}


def fetch_us_filings(ticker: str, name: str = "",
                     days: int = None) -> list | None:
    """近 days 天 EDGAR 披露文件时间线（submissions API, P3）。

    kind="filing", impact=neutral——文件性质（8-K 重大事项 / 10-Q 季报
    / Form 4 内部人交易）由 AI 读 payload["form"] 解读。
    filings.recent 覆盖近千条提交（新→旧），90 天窗口无需分页。
    无匹配 CIK 或源失败 → None（fail-closed），无匹配文件 → []。
    """
    days = days or config.INTEL_FILING_DAYS
    cik = _load_cik_map().get(ticker)
    if not cik:
        return None
    d = SEC.get_json(config.SEC_SUBMISSIONS_URL_TMPL.format(cik=cik),
                     timeout=30)
    if d is None:
        return None
    rec = ((d.get("filings") or {}).get("recent")) or {}
    forms = rec.get("form") or []
    n = len(forms)

    def col(key, i):
        vals = rec.get(key) or []
        return str(vals[i]) if i < len(vals) else ""

    since = (date.today() - timedelta(days=days)).isoformat()
    items = []
    for i, form in enumerate(forms):
        if not _is_material_form(str(form)):
            continue
        fd = col("filingDate", i)[:10]
        if not fd or fd < since:
            continue
        acc = col("accessionNumber", i)
        doc = col("primaryDocument", i)
        items.append(IntelItem(
            market="US", code=ticker, name=name,
            subsystem="announcements", kind="filing",
            event_date=date.fromisoformat(fd),
            title=f"{form} filing",
            url=(config.EDGAR_DOC_URL_TMPL.format(
                cik=cik, acc=acc.replace("-", ""), doc=doc)
                if acc and doc else ""),
            source="sec_edgar", impact="neutral",
            payload={"form": str(form), "accession": acc,
                     "items": col("items", i),
                     "report_date": col("reportDate", i)[:10]}))
    return items
```

Remove the unused `import re` if not needed (it is not needed — do not add it).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_intel_sources.py -q`
Expected: PASS (new + all pre-existing)

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/announcements.py tests/test_intel_sources.py
git commit -m "feat(intel): HK notices (ann_type=H) + US EDGAR filings timeline"
```

---

### Task 5: ratings.py — US consensus from stockanalysis.com

**Files:**
- Modify: `value_genie/intel/ratings.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intel_sources.py`:

```python
_SA_HTML = (
    '<!doctype html><html><body>'
    'x' * 50
    'widget:{all:{count:44,consensus:"Buy",price_target:324.53,'
    'currency:"USD"}},'
    'ratings:[{action_rt:"Maintains",pt_now:366,pt_old:null,firm:"HSBC",'
    'analyst:"Nicolas Cote Colisson",date:"2026-09-08",'
    'rating_new:"Buy",rating_old:"",time:"11:15:07",'
    'scores:{score:44.2,stars:.6,total:43},curr:"USD"},'
    '{action_rt:"Upgrades",pt_now:300,pt_old:270,firm:"Needham",'
    'analyst:"Laura Martin",date:"2026-09-07",rating_new:"Buy",'
    'rating_old:"Hold",time:"10:55:34",curr:"USD"}]}'
    'rest-of-page</body></html>'
)


class TestFetchUsConsensus:
    def test_parses_widget_and_ratings(self, monkeypatch):
        monkeypatch.setattr(ratings.SA, "get_text",
                            lambda url, **kw: _SA_HTML)
        items = ratings.fetch_us_consensus("AAPL", "Apple")
        assert items[0].kind == "consensus"
        assert items[0].payload["consensus"] == "Buy"
        assert items[0].payload["count"] == 44
        assert items[0].payload["price_target"] == 324.53
        assert items[1].kind == "rating"
        assert items[1].payload["org"] == "HSBC"
        assert items[1].payload["target_price"] == 366
        assert items[1].impact == "neutral"          # Maintains
        assert items[2].payload["org"] == "Needham"
        assert items[2].impact == "positive"         # Upgrades
        assert items[2].payload["last_rating"] == "Hold"

    def test_slug_mapping(self, monkeypatch):
        urls = []
        monkeypatch.setattr(ratings.SA, "get_text",
                            lambda url, **kw: urls.append(url)
                            or _SA_HTML)
        ratings.fetch_us_consensus("BRK_B")
        assert urls == ["https://stockanalysis.com/stocks/brk-b/ratings/"]

    def test_source_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(ratings.SA, "get_text",
                            lambda url, **kw: None)
        assert ratings.fetch_us_consensus("AAPL") is None

    def test_blob_missing_returns_none(self, monkeypatch):
        monkeypatch.setattr(ratings.SA, "get_text",
                            lambda url, **kw: "<html>no data</html>")
        assert ratings.fetch_us_consensus("AAPL") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k Consensus`
Expected: FAIL — `fetch_us_consensus` not defined

- [ ] **Step 3: Implement**

In `value_genie/intel/ratings.py` — update module docstring, imports, and append the US section:

```python
"""Ratings subsystem (P2: A-share analyst reports; P3: US consensus,
design §4).

A: reportapi.eastmoney.com/report/list — sell-side reports with rating,
rating change, EPS forecasts and (usually empty) target price.
US: stockanalysis.com ratings page — consensus widget + individual
ratings parsed from the embedded Next.js flight-data blob.
HK: no source found (reportapi carries no HK reports) — degrade with an
explicit note at the report layer; rating headlines surface via news.
"""

import json
import re
from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB, SA
from .model import IntelItem
```

Append after `fetch_stock_ratings`:

```python
# ---------------------------------------------------------------------------
# US: stockanalysis.com consensus (P3)
# ---------------------------------------------------------------------------
def _sa_flight_array(html: str, key: str) -> str | None:
    """Extract `key:[...]` from an embedded flight-data payload via a
    quote-aware balanced bracket scan (probe-verified 2026-09-09)."""
    j = html.find(f"{key}:[")
    if j < 0:
        return None
    k = j + len(key) + 1            # position of '['
    depth, in_str, esc = 0, False, False
    start = k
    while k < len(html):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return html[start:k + 1]
        k += 1
    return None


def _sa_json(blob: str) -> list | None:
    """Bare-key JS array literal -> parsed list. Two probe-validated
    fixes: quote bare keys, and leading-dot floats (stars:.6 -> 0.6)."""
    fixed = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)',
                   r'\1"\2"\3', blob)
    fixed = re.sub(r'([{:[,\s])\.(\d)', r'\g<1>0.\2', fixed)
    try:
        v = json.loads(fixed)
        return v if isinstance(v, list) else None
    except json.JSONDecodeError:
        return None


def fetch_us_consensus(ticker: str, name: str = "") -> list | None:
    """US 一致评级 + 个体评级时间线（stockanalysis.com）。

    返回 IntelItem 列表：首项 kind="consensus"（一致评级/覆盖家数/
    目标价快照），随后 kind="rating" 个体评级（新→旧）。Upgrades→
    positive / Downgrades→negative，其余 neutral。源失败或页面无
    评级数据 → None（fail-closed）。
    """
    slug = ticker.lower().replace("_", "-")
    url = config.SA_RATINGS_URL_TMPL.format(slug=slug)
    html = SA.get_text(url)
    if html is None:
        return None
    i = html.find("widget:{all:{")
    blob = _sa_flight_array(html, "ratings")
    if i < 0 or not blob:
        return None
    ratings = _sa_json(blob)
    if not ratings:
        return None
    seg = html[i:i + 160]
    m = re.search(r'count:(\d+),consensus:"([^"]*)"', seg)
    if not m:
        return None
    count, consensus = int(m.group(1)), m.group(2)
    pm = re.search(r'price_target:([\d.]+)', seg)
    pt = float(pm.group(1)) if pm else None
    items = [IntelItem(
        market="US", code=ticker, name=name,
        subsystem="ratings", kind="consensus",
        event_date=date.today(),
        title=(f"一致评级 {consensus} · {count}家覆盖"
               + (f" · 目标价 ${pt:.2f}" if pt is not None else "")),
        url=url, source="stockanalysis", impact="neutral",
        payload={"consensus": consensus, "count": count,
                 "price_target": pt})]
    for r in ratings:
        d = str(r.get("date") or "")[:10]
        if not d:
            continue
        action = str(r.get("action_rt") or "")
        items.append(IntelItem(
            market="US", code=ticker, name=name,
            subsystem="ratings", kind="rating",
            event_date=date.fromisoformat(d),
            title=f"{r.get('firm') or ''} {r.get('rating_new') or ''}",
            source="stockanalysis",
            impact={"Upgrades": "positive",
                    "Downgrades": "negative"}.get(action, "neutral"),
            payload={"org": str(r.get("firm") or ""),
                     "rating": str(r.get("rating_new") or ""),
                     "last_rating": str(r.get("rating_old") or ""),
                     "action": action,
                     "target_price": _f(r.get("pt_now")),
                     "prev_target": _f(r.get("pt_old")),
                     "analyst": str(r.get("analyst") or "")}))
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_intel_sources.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/ratings.py tests/test_intel_sources.py
git commit -m "feat(intel): US consensus + rating history via stockanalysis.com"
```

---

### Task 6: report.py — three-market assembly

**Files:**
- Modify: `value_genie/intel/report.py`
- Test: `tests/test_intel_report.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intel_report.py` (mirror the existing `TestBuildIntelReport` mocking style — monkeypatch fetchers in the `ir` module namespace):

```python
class TestBuildIntelReportHKUS:
    def _hk_match(self):
        return Match("HK", "00700", "腾讯控股", 100.0, "116")

    def _us_match(self):
        return Match("US", "AAPL", "Apple", 100.0, "105")

    def test_hk_assembly(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "HK", "code": "00700", "name": "腾讯控股",
              "intel_red": 0.0}])})
        notice = IntelItem(market="HK", code="00700", name="腾讯控股",
                           subsystem="announcements", kind="notice",
                           event_date=date(2026, 9, 8), title="翌日披露报表",
                           source="eastmoney", impact="neutral", payload={})
        news = IntelItem(market="HK", code="00700", name="腾讯控股",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="腾讯新闻",
                         source="eastmoney", impact="neutral", payload={})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda code, name="", **kw: [notice])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, code, name="", **kw: [news])
        res = ir.build_intel_report(self._hk_match(), snapshot_dir=snap)
        assert res["notices"] == [notice]
        assert res["news"] == [news]
        assert isinstance(res["ratings"], dict) and "missing" in res["ratings"]
        assert "missing" in res["events"] and "missing" in res["eq"]
        assert res["radar"]["intel_red"] == 0.0

    def test_us_assembly(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "US", "code": "AAPL", "name": "Apple",
              "intel_red": 0.0}])})
        filing = IntelItem(market="US", code="AAPL", name="Apple",
                           subsystem="announcements", kind="filing",
                           event_date=date(2026, 9, 8), title="8-K filing",
                           source="sec_edgar", impact="neutral",
                           payload={"form": "8-K"})
        cons = IntelItem(market="US", code="AAPL", name="Apple",
                         subsystem="ratings", kind="consensus",
                         event_date=date(2026, 9, 9), title="一致评级 Buy",
                         source="stockanalysis", impact="neutral", payload={})
        rating = IntelItem(market="US", code="AAPL", name="Apple",
                           subsystem="ratings", kind="rating",
                           event_date=date(2026, 9, 8), title="HSBC Buy",
                           source="stockanalysis", impact="neutral",
                           payload={"org": "HSBC", "rating": "Buy"})
        news = IntelItem(market="US", code="AAPL", name="Apple",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="Apple news",
                         source="eastmoney", impact="neutral", payload={})
        monkeypatch.setattr(ir, "fetch_us_filings",
                            lambda code, name="": [filing])
        monkeypatch.setattr(ir, "fetch_us_consensus",
                            lambda code, name="": [cons, rating])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, code, name="", **kw: [news])
        res = ir.build_intel_report(self._us_match(), snapshot_dir=snap)
        assert res["notices"] == [filing]
        assert res["ratings"] == [cons, rating]
        assert res["news"] == [news]
        assert "missing" in res["events"] and "missing" in res["eq"]

    def test_us_render_labels(self, monkeypatch):
        res = {"match": self._us_match(), "snapshot": "20260909",
               "asof": "2026-09-09", "radar": {},
               "events": {"missing": "雷达批表当前仅覆盖 A 股"},
               "eq": {"missing": "A 股快照专属"},
               "notices": [], "ratings": [], "news": []}
        out = ir.render_intel(res)
        assert "披露文件时间线" in out
        assert "US/AAPL" in out

    def test_hk_render_keeps_notice_label(self, monkeypatch):
        res = {"match": self._hk_match(), "snapshot": "20260909",
               "asof": "2026-09-09", "radar": {},
               "events": {"missing": "x"}, "eq": {"missing": "x"},
               "notices": [], "ratings": {"missing": "y"}, "news": []}
        out = ir.render_intel(res)
        assert "公告时间线" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_intel_report.py -q -k HKUS`
Expected: FAIL — HK/US reports currently return the P2 "P3: HK/US 未覆盖" stub

- [ ] **Step 3: Implement**

In `value_genie/intel/report.py`:

3a. Update imports at top:

```python
from .announcements import fetch_stock_notices, fetch_us_filings
from .model import earnings_quality, item_to_row
from .news import fetch_stock_news
from .radar import (_appointment_items, _buyback_items, _eq_records,
                    _forecast_items, _holder_items, _placement_items,
                    _read_csv, _unlock_items, RADAR_COLUMNS)
from .ratings import fetch_stock_ratings, fetch_us_consensus
```

3b. Update module docstring — replace "P2 covers A-shares; HK/US degrade with an explicit P3 note." with "A: full five sections. HK: notices + news (Eastmoney mirror); research ratings have no source — explicit missing note. US: filings (EDGAR) + news + consensus (stockanalysis). Radar batch tables and earnings-quality inputs are A-share-only; HK/US sections degrade with explicit notes."

3c. Replace the `if match.market != "A":` early-return block and the section assembly in `build_intel_report`:

```python
def build_intel_report(match, snapshot_dir=None,
                       asof: date | None = None) -> dict:
    """单股舆情情报 result dict（五个板块 + 雷达行，fail-closed）。

    A: 全五板块。HK: 公告+新闻（东财镜像），研报无源（显式降级）。
    US: 披露文件（EDGAR）+ 新闻 + 一致评级（stockanalysis）。
    雷达批表与粉饰信号输入为 A 股专属——HK/US 相应板块显式标注。
    """
    snap = Path(snapshot_dir) if snapshot_dir else None
    asof = asof or date.today()
    market = match.market
    result = {"match": match, "snapshot": snap.name if snap else None,
              "asof": asof.isoformat()}

    result["radar"] = _radar_row(snap, market, match.code) or {}

    if market == "A":
        result["events"] = (_stock_events(snap, match.code, asof)
                            if snap else [])
        eq = _eq_detail(snap, match.code) if snap else None
        result["eq"] = ({"missing": "财报输入表缺失"} if eq is None else eq)
    else:
        result["events"] = {
            "missing": "雷达批表当前仅覆盖 A 股（HK/US 批量事件属后续阶段）"}
        result["eq"] = {
            "missing": "粉饰信号输入（应收/存货/OCF/扣非）为 A 股快照专属"}

    if market == "US":
        notices = fetch_us_filings(match.code, name=match.name)
        result["notices"] = ({"missing": "EDGAR source failed"}
                             if notices is None else notices)
    else:
        notices = fetch_stock_notices(match.code, name=match.name,
                                      market=market)
        result["notices"] = ({"missing": "notice source failed"}
                             if notices is None else notices)

    if market == "HK":
        result["ratings"] = {
            "missing": "港股研报源缺失（东财 reportapi 不含港股）；"
                       "评级动向请看新闻时间线"}
    elif market == "US":
        ratings = fetch_us_consensus(match.code, name=match.name)
        result["ratings"] = ({"missing": "ratings source failed"}
                             if ratings is None else ratings)
    else:
        ratings = fetch_stock_ratings(match.code, name=match.name)
        result["ratings"] = ({"missing": "ratings source failed"}
                             if ratings is None else ratings)

    news = fetch_stock_news(match.market_id or "", match.code,
                            name=match.name, market=market)
    result["news"] = ({"missing": "news source failed"}
                      if news is None else news)
    return result
```

3d. In `render_intel`, make the notices label market-aware (replace the notices block):

```python
    notices = result.get("notices")
    if isinstance(notices, dict):
        lines.append(f"[公告时间线] 数据缺失: {notices.get('missing', '')}")
    elif result["match"].market == "US":
        lines.append(f"[披露文件时间线] 近{config.INTEL_FILING_DAYS}天 "
                     f"{_items_block(notices)}")
    else:
        lines.append(f"[公告时间线] 近{config.INTEL_NOTICE_DAYS}天 "
                     f"{_items_block(notices)}")
```

And make the ratings line consensus-aware (replace the ratings block):

```python
    ratings = result.get("ratings")
    if isinstance(ratings, dict):
        lines.append(f"[投行评级] 数据缺失: {ratings.get('missing', '')}")
    elif ratings and ratings[0].kind == "consensus":
        rest = ratings[1:]
        latest = (f"最近: {rest[0].event_date.strftime('%m-%d')} "
                  f"{rest[0].title}"
                  + (f" 目标价 ${rest[0].payload.get('target_price')}"
                     if rest[0].payload.get("target_price") else "")
                  ) if rest else "无个体评级明细"
        lines.append(f"[投行评级] {ratings[0].title}；近期个体评级 "
                     f"{len(rest)} 份（{latest}）")
    else:
        latest = (f"最近: {ratings[0].event_date.strftime('%m-%d')} "
                  f"{ratings[0].title}"
                  + (f" ←{ratings[0].payload.get('last_rating')}"
                     if ratings[0].payload.get("last_rating") else "")
                  ) if ratings else "无研报"
        lines.append(f"[投行评级] 近{config.INTEL_RATING_DAYS}天 "
                     f"{len(ratings)} 份（{latest}）")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_intel_report.py -q`
Expected: PASS (new + pre-existing A-share tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/report.py tests/test_intel_report.py
git commit -m "feat(intel): three-market intel report assembly (HK/US)"
```

---

### Task 7: sources.py — P3 capability registration

**Files:**
- Modify: `value_genie/intel/sources.py`
- Test: `tests/test_intel_sources.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intel_sources.py` (check its existing import style for the registry first):

```python
class TestP3SourceRegistration:
    def test_eastmoney_caps(self):
        caps = [s for s in list_sources() if s.id == "eastmoney"][0]
        for cap in ("notice:HK", "news:HK", "news:US"):
            assert cap in caps.capabilities

    def test_sec_edgar_notice_us(self):
        caps = [s for s in list_sources() if s.id == "sec_edgar"][0]
        assert "notice:US" in caps.capabilities

    def test_stockanalysis_registered(self):
        caps = [s for s in list_sources() if s.id == "stockanalysis"]
        assert caps and "ratings:US" in caps[0].capabilities
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_intel_sources.py -q -k Registration`
Expected: FAIL — caps not registered

- [ ] **Step 3: Implement**

Rewrite `value_genie/intel/sources.py`:

```python
"""Intel data source registration (design §4).

P1: eastmoney gains events:A + announce:A (A-share batch event tables
for the radar channel). P2: notice/news/ratings:A per-stock channels.
P3: eastmoney mirror covers HK notices/news + US news; sec_edgar adds
notice:US (submissions timeline); stockanalysis provides ratings:US.
HK research ratings have no source (probe-verified) — the report layer
degrades explicitly.
"""

from ..strategy.registry import (DataSource, list_sources,
                                 register_source, set_source_order)


def _register_intel_sources():
    """Extend existing entries in place + register new sources.

    Mutating the registered DataSource in place (register_source would
    need the whole entry duplicated); idempotent by construction.
    """
    for ds in list_sources():
        if ds.id == "eastmoney":
            for cap in ("events:A", "announce:A", "notice:A",
                        "notice:HK", "news:A", "news:HK", "news:US",
                        "ratings:A"):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
        elif ds.id == "sec_edgar":
            for cap in ("notice:US",):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
    register_source(DataSource(
        id="stockanalysis", name="StockAnalysis",
        capabilities=["ratings:US"]))
    set_source_order("events", "A", ["eastmoney"])
    set_source_order("announce", "A", ["eastmoney"])
    set_source_order("notice", "A", ["eastmoney"])
    set_source_order("notice", "HK", ["eastmoney"])
    set_source_order("notice", "US", ["sec_edgar"])
    set_source_order("news", "A", ["eastmoney"])
    set_source_order("news", "HK", ["eastmoney"])
    set_source_order("news", "US", ["eastmoney"])
    set_source_order("ratings", "A", ["eastmoney"])
    set_source_order("ratings", "US", ["stockanalysis"])


_register_intel_sources()
```

Check: `register_source` on an id that may already exist (double import) — look at `register_source` in `value_genie/strategy/registry.py`; if it raises on duplicates, guard with an id check first. Mirror whatever pattern `fetch/sources.py` uses.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_intel_sources.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add value_genie/intel/sources.py tests/test_intel_sources.py
git commit -m "feat(intel): P3 source registration (HK/US notice+news, US ratings)"
```

---

### Task 8: AGENTS.md routing + skills/16-intel.md + probe cleanup

**Files:**
- Modify: `AGENTS.md` (routing table)
- Create: `skills/16-intel.md`
- Delete: `_probe_p3*.py` (11 files)

- [ ] **Step 1: AGENTS.md routing row**

In AGENTS.md routing table, add after the "审视我的持仓 / 深度分析持仓" row:

```markdown
| "X的舆情/解禁/公告/研报/财报解读" | intel | `python -m value_genie intel X`（A 全板块；HK 公告+新闻，研报无源；US EDGAR 披露+新闻+一致评级） |
```

- [ ] **Step 2: Create skills/16-intel.md**

Check `skills/15-trading.md` frontmatter fields and mirror the format exactly. Structure:

```markdown
---
id: intel
order: 16
triggers: 舆情/情报/公告/解禁/研报/评级/财报解读/事件雷达
commands: intel X / intel X --json
---

# Intel (舆情情报) Playbook

## Body

intel X 输出五个板块（事件雷达 / 公告或披露文件时间线 / 财报信号 /
投行评级 / 新闻时间线）。市场覆盖：A 全板块；HK 公告+新闻（东财港股
镜像），研报无源显式降级；US EDGAR 披露文件 + 新闻 + stockanalysis
一致评级。雷达批表（解禁/减持/回购/定增/预告/预约）仅 A 股。

### AI 解读框架
- 解禁：看结构（大股东 vs 财投、成本、占比）；30 天 ≥5% 是红旗。
- 评级：方向 + 调整轨迹（连续上调/下调比单次动作重要）；目标价
  变化轨迹比绝对值重要。
- 粉饰信号：单看一项不定罪，组合出现（应收+存货+OCF 缺口）才升级。
- 事件与周期：解禁/财报日对 short horizon 是催化，对 long horizon
  通常只是噪音——按 ask X 的四周期剖面分别说。
- HK 研报缺失时：用新闻时间线里的评级标题（"大摩下调目标价"）做
  替代证据，并在答案中说明数据缺口。

## Field Notes

- (2026-09-09) 港股研报端点不存在：reportapi qType=0/1 对 HK 代码均
  0 hits；hkStock 页面 XHR 藏在 minified main.js 中未定位——HK 评级
  走新闻时间线降级，找到端点后再补。
- (2026-09-09) stockanalysis.com 评级页为 Next.js flight data，无公开
  API：正则引用 bare key + 前导零浮点（stars:.6）两步修复后
  json.loads 可解析；无评级页 404 → fail-closed None。
- (2026-09-09) np-listapi 美股前缀：105=NASDAQ、106=NYSE 有新闻，
  107=AMEX 返回空 data——快照外美股自动按 105→106 试。
- (2026-09-09) EDGAR submissions.filings.recent 覆盖近千条提交（新→
  旧），90 天窗口无需分页；144（拟议内部人出售）是噪音已过滤。
```

- [ ] **Step 3: Delete probe scripts**

Delete: `_probe_p3_hk.py`, `_probe_p3_us.py`, `_probe_p3b.py` … `_probe_p3k.py` (all `_probe_p3*` files — they are untracked throwaways).

- [ ] **Step 4: Run full test suite**

Run: `python -B -m pytest tests -q`
Expected: all PASS (~490+)

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md skills/16-intel.md
git rm --cached --ignore-unmatch _probe_p3*.py 2>/dev/null || true
git commit -m "docs(intel): AGENTS routing + intel playbook (P3 findings)"
```

(probes are untracked — no git rm needed; just delete them.)

---

### Task 9: Live verification + push

- [ ] **Step 1: Freshness check**

Run: `python -m value_genie doctor`
Expected: PASS or WARN (snapshot exists from today). Note hours in output.

- [ ] **Step 2: Live HK intel**

Run: `python -m value_genie intel 00700`
Expected: [公告时间线] HK notices with 翌日披露报表 etc.; [投行评级] 数据缺失 (港股研报源缺失…); [新闻时间线] news items; [事件明细]/[财报信号] explicit missing notes.

- [ ] **Step 3: Live US intel**

Run: `python -m value_genie intel AAPL`
Expected: [披露文件时间线] EDGAR filings (8-K/10-Q/Form 4); [投行评级] consensus line (一致评级 … 家覆盖 · 目标价 $…) + individual ratings; [新闻时间线] news.

- [ ] **Step 4: Regression — A-share intel still works**

Run: `python -m value_genie intel 600519`
Expected: unchanged P2 behavior (notices/ratings/news live, radar/events/eq from snapshot).

- [ ] **Step 5: JSON contract spot check**

Run: `python -m value_genie intel AAPL --json`
Expected: pure JSON; sections missing → null; consensus item first in ratings.

- [ ] **Step 6: Push**

```bash
git push origin feat/intel-gates-p2
```

(If rejected because the remote moved: the user pre-approved force-with-lease on this feature branch — `git push --force-with-lease origin feat/intel-gates-p2`. NEVER push main.)

---

## Self-Review

- **Spec coverage:** spec §7 情报通道 three markets ✓ (Tasks 3-6); spec §4 sources registration ✓ (Task 7); spec §8 配套 (AGENTS.md, skills/16-intel.md, http.py SA singleton) ✓ (Tasks 1, 8); radar HK/US batch explicitly out of scope with documented degradation (spec §6.1's HK/US batch line remains future work — noted in report.py and playbook). HK 研报 endpoint hunt (probes p3c–p3h) exhausted → explicit degradation matches the fail-closed design §9.3.
- **Placeholder scan:** no TBD/TODO; every code step has complete code; test steps have complete assertions.
- **Type consistency:** `fetch_stock_notices(code, name, days=None, market="A")` used consistently; `fetch_us_filings(ticker, name="", days=None)`; `fetch_us_consensus(ticker, name="")` returns `list | None` matching report.py's None-check; `fetch_stock_news(market_id, code, name, days, market)` call sites updated in report.py only (analyze.py doesn't call news directly — verified).
