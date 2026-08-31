# Value Genie Implementation Plan

> **For agentic workers:** Execute tasks in order. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rebuild consumer-stocks-screener as `value-genie`: full-market A/HK/US value-investment screener with unified multi-factor engine, snapshot data pipeline, and Streamlit web UI. All code English; README Chinese.

**Architecture:** Two-stage funnel pipeline (full-market quotes + batch financials → top ~200/market deep data) writing date-stamped snapshots; scoring engine (4 pillars, per-market percentiles, preset weight archives) decoupled from fetching; Streamlit app recomputes composites instantly from master.csv.

**Tech Stack:** Python 3.10+, pandas, numpy, requests, Streamlit, Plotly, tabulate, pytest.

**Spec:** `docs/specs/2026-08-31-value-genie-design.md`

---

## Data source reference (verified working patterns from old fetch_data.py)

- EM clist paging: `http://push2.eastmoney.com/api/qt/clist/get` params `pn,pz=100,po=0,np=1,fltt=2,invt=2,fid=f12,fs,fields,ut=bd1d9ddb04089700cf9c27f6f7426281`
  - fs A-share: `m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048`; HK: `m:128`; US: `m:105,m:106,m:107`
  - fields: `f2,f3,f5,f6,f8,f9,f12,f13,f14,f20,f21,f23,f100,f114,f115` (price, pct, vol, amount, turnover, PE-dyn, code, mkt-id, name, mcap, float-mcap, PB, industry, PE-static, PE-TTM)
- EM kline: `http://push2his.eastmoney.com/api/qt/stock/kline/get` (klt=101, fqt=1, lmt=300); Tencent fallback `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,320,qfq`
- HK F10: `https://datacenter.eastmoney.com/securities/api/data/v1/get` reportName=`RPT_HKF10_FN_MAININDICATOR` filter `(SECUCODE="{code}.HK")` pageSize=12
- A-share batch financials: `https://datacenter-web.eastmoney.com/api/data/v1/get` reportName=`RPT_LICO_FN_CPD` filter `(REPORTDATE='YYYY-MM-DD')` pageSize=500, columns=ALL. Fields: SECURITY_CODE, REPORTDATE, TOTAL_OPERATE_INCOME, YSTZ (rev YoY), PARENT_NETPROFIT, SJLTZ (profit YoY), WEIGHTAVG_ROE, XSMLL (gross margin), BPS. Latest period detection: try recent quarter-ends desc until a page returns ≥1000 rows; also fetch previous period for backfill.
- US batch financials: SEC frames `https://data.sec.gov/api/xbrl/frames/us-gaap/{Concept}/{unit}/{Frame}.json`, Frame ∈ CY2025, CY2024, CY2026Q2, CY2025Q2; Concepts: RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, NetIncomeLoss, GrossProfit, StockholdersEquity, Liabilities, Assets. CIK→ticker via `https://www.sec.gov/files/company_tickers.json`. All SEC requests need User-Agent header.
- FX HKD/CNY: EM ulist secids `133.HKDCNH,133.HKDCNY`.

## Module interfaces (contract for all tasks)

```python
# fetch/http.py
class Fetcher:  # port of old Fetcher, English logs
    def get_json(url, params=None, timeout=20, retries=2, cooldown_after=5, cooldown_sec=75) -> dict | None
def em_push2_url(path) -> str  # host rotation
def num(v) -> float | None

# fetch/quotes.py
def fetch_market_quotes(market: str) -> pd.DataFrame
# columns: market, code, name, industry, price, pct_chg, amount, turnover, pe_dyn, pe_static,
#           pe_ttm, pb, market_cap, float_cap, market_id

# fetch/fundamentals.py
def fetch_a_financials() -> pd.DataFrame      # code, report_date, revenue, rev_yoy, profit, profit_yoy, roe, gross_margin, bps
def fetch_us_financials() -> pd.DataFrame     # ticker, rev, rev_prev, rev_yoy, profit, profit_prev, profit_yoy, rev_q_yoy, gross_profit, equity, equity_prev, liabilities, assets
def fetch_hk_f10(code5: str) -> pd.DataFrame | None   # English cols, 12 report periods
def fetch_fx_hkdcny() -> float

# fetch/kline.py
def fetch_kline(secid: str, lmt=300) -> pd.DataFrame | None   # date, open, close, high, low, volume, amount
def fetch_kline_tx(symbol: str, lmt=320) -> pd.DataFrame | None
def kline_is_fresh(path: Path, market: str) -> bool
def load_kline(path) -> pd.DataFrame | None

# strategy/factors.py
def kline_metrics(kl: pd.DataFrame) -> dict  # pos_52w, drawdown_52w, ret_250d, ret_60d, volatility
def add_pillar_scores(df: pd.DataFrame) -> pd.DataFrame  # value/growth/quality/safety scores, per-market percentiles

# strategy/presets.py
PRESETS: dict[str, dict]  # name -> {value, growth, quality, safety} weights summing to 1

# strategy/composite.py
def apply_composite(df, weights: dict, min_pillars=3) -> pd.DataFrame  # adds composite_score, data_completeness

# fetch/pipeline.py
def run_fetch(markets, data_dir, refresh) -> Path   # snapshot dir path; writes quotes/financials/klines/master.csv/manifest.json

# report.py
def build_report(master, fetch_meta) -> str  # markdown English
def write_outputs(master, out_dir, preset) -> None

# __main__.py: python -m value_genie {fetch,screen} [--refresh --markets a,hk,us --preset balanced --top 20 --data-dir --out-dir]
```

## Snapshot layout

```
data/snapshots/YYYYMMDD/{manifest.json, a_quotes.csv, hk_quotes.csv, us_quotes.csv,
                         a_financials.csv, us_financials.csv, hk_f10.csv, kline/A_600519.csv ...,
                         master.csv}
data/latest.json  # {"snapshot": "20260831"}
```

master.csv columns: market, code, name, industry, currency, price, market_cap, pe_ttm, pb, ps,
dividend_yield, rev_yoy, profit_yoy, rev_q_yoy, roe, gross_margin, net_margin, debt_ratio,
pos_52w, drawdown_52w, ret_250d, ret_60d, volatility, report_date,
value_score, growth_score, quality_score, safety_score, data_completeness.

## Funnel rules (config.py)

- Gates: PE_TTM > 0; rev_yoy > 0 where available; min mcap A 3e9 CNY / HK 2e9 HKD / US 1e9 USD;
  HK min daily amount 5e6 HKD; A-share name excludes "ST"/"退".
- Stage-1 blend weights (funnel only): A/US value .4 growth .3 quality .3; HK value 1.0.
- CANDIDATES_PER_MARKET = 200.
- Pillar percentile pool = per-market candidate pool in master.
- Final gates post-deep: profit_yoy > 0 where available (HK from F10).

## Presets

| key | value | growth | quality | safety |
|---|---|---|---|---|
| balanced (default) | .35 | .25 | .30 | .10 |
| magic_formula | .50 | 0 | .50 | 0 |
| garp | .25 | .45 | .30 | 0 |
| deep_value | .55 | 0 | .25 | .20 |

---

### Task 1: Scaffold & cleanup
- [ ] Check `git status`; init repo if needed; commit current state as baseline
- [ ] Create `value_genie/` + subpackages, `tests/`, `app.py`, `pyproject.toml`, `requirements.txt`
- [ ] Write `value_genie/config.py` (paths, endpoints, fs strings, field maps, gates, funnel weights, presets moved later to strategy)
- [ ] Update `.gitignore` (data/, output/, __pycache__/, .venv/, .pytest_cache/)
- [ ] Delete `fetch_data.py`, `analyze.py`, old `data/*`, old `output/*`
- [ ] Verify `python -c "import value_genie"`; commit

### Task 2: fetch/http.py
- [ ] Port Fetcher (retry + cooldown), em_push2_url host rotation, num(); English logs
- [ ] tests/test_http.py: num() coercion cases; Fetcher 404→None via mock session
- [ ] Run pytest; commit

### Task 3: fetch/quotes.py
- [ ] `fetch_market_quotes(market)` → paged clist → English DataFrame; drop null price; A-share ST/退 exclusion helper
- [ ] tests/test_quotes.py: _parse_clist_rows on synthetic diff payload
- [ ] Run pytest; commit

### Task 4: fetch/fundamentals.py
- [ ] A: period detection (try quarter-ends desc, ≥1000 rows = current), 2-period fetch + merge (prefer latest non-null)
- [ ] US: frames fetch list (config FRAMES_SPEC), concept merge (RCWCEAT priority over Revenues), cik→ticker map, derived cols (yoy, margins, roe, leverage)
- [ ] HK: fetch_hk_f10 ported to English columns
- [ ] FX: port fetch_fx_hkdcny
- [ ] tests/test_fundamentals.py: _pick_latest_report_date, _merge_frames (synthetic), _derive_us_metrics
- [ ] Run pytest; commit

### Task 5: fetch/kline.py
- [ ] Port EM kline + Tencent fallback (symbol candidates per market), kline_is_fresh (market-aware trading-day rule), load_kline
- [ ] tests/test_kline.py: freshness with tmp csv files; parse of synthetic kline payload
- [ ] Run pytest; commit

### Task 6: strategy/factors.py
- [ ] kline_metrics (pos_52w, drawdown_52w, ret_250d, ret_60d, volatility)
- [ ] add_pillar_scores: per-market percentile pillar scores (value: PE/PB/PS/dividend inverted; growth: rev_yoy/profit_yoy/rev_q_yoy; quality: roe/gross_margin/net_margin/low debt_ratio; safety: low pos_52w, low volatility, deep drawdown), mean of available sub-factors
- [ ] tests/test_factors.py: synthetic 2-market frame → known percentile ordering; missing-subfactor renorm
- [ ] Run pytest; commit

### Task 7: strategy/presets.py + composite.py
- [ ] PRESETS dict; apply_composite with weight renormalization over available pillars, min_pillars=3, adds composite_score + data_completeness
- [ ] tests/test_composite.py: full-weights case; missing pillar renorm; below min_pillars → NaN; invalid preset raises
- [ ] Run pytest; commit

### Task 8: fetch/pipeline.py
- [ ] run_fetch: quotes → gates → stage-1 blend → top-200/market candidates → deep (klines all candidates; HK F10 per HK candidate; US/A merge batch financials) → final gates → master assembly (incl. HK PS via FX, dividend from HK F10) → add_pillar_scores → snapshot dir write (incremental: reuse fresh klines + hk_f10 from latest prior snapshot; --refresh forces full)
- [ ] manifest.json: per-dataset timestamps, quote dates, counts, failures, elapsed
- [ ] tests/test_pipeline.py: monkeypatched fetchers returning synthetic data → assert snapshot files + master.csv columns + candidate cap
- [ ] Run pytest; commit

### Task 9: report.py + __main__.py
- [ ] build_report: methodology, gates, preset table, TOP20 overall + per-market TOP10, notes (markdown, tabulate)
- [ ] CLI: fetch (markets/refresh/data-dir), screen (preset/top/out-dir) → writes output/ranking.csv + output/report.md, prints top table
- [ ] tests/test_report.py: report contains key sections from synthetic master
- [ ] Run pytest; commit

### Task 10: app.py (Streamlit)
- [ ] Sidebar: snapshot selectbox, market multiselect, preset selectbox, 4 weight sliders (normalized), top-N
- [ ] Main: freshness banner (manifest), metric row, ranking table + CSV download, tabs: Charts (composite histogram, value-quality bubble scatter, top-N stacked bar), Stock detail (kline line chart, pillar radar vs market median, metrics table)
- [ ] Manual smoke test: `streamlit run app.py` with real snapshot
- [ ] Commit

### Task 11: End-to-end real run + README + polish
- [ ] `python -m value_genie fetch` full real run; inspect manifest/master; `python -m value_genie screen`; `streamlit run app.py`
- [ ] Rewrite README.md (Chinese, concise: badges, pitch, features, quick start, architecture, methodology, presets table, data sources, disclaimer, project name 价值投资精灵 / value-genie)
- [ ] Full pytest pass; final commit
