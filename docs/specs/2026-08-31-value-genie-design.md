# Value Genie (价值投资精灵) — Design Spec

Date: 2026-08-31
Status: Approved by user

## Goal

Evolve the existing consumer-stocks-screener (2-script, Chinese, consumer-only,
HK/US only) into a mature open-source project that screens **all stocks** in
A-share, HK, and US markets for the single goal of finding the **most
undervalued, highest-growth, best-quality** value investment candidates, with
an interactive web UI, swappable strategies, fresh data, and English
code/naming (Chinese README allowed).

## Key Decisions

| Decision | Choice |
|---|---|
| Universe | Full-market funnel: all ~5,400 A-shares + ~2,700 HK + ~9,000 US enter stage-1 screening; top ~200 per market get deep data |
| Web tech | Streamlit + Plotly (pure Python) |
| Strategy | One unified multi-factor engine + preset profiles (Magic Formula / GARP / Deep Value / Balanced / Custom sliders) |
| Dates | Snapshot-per-run with date-stamped directories; UI shows as-of date, offers historical snapshot switch |
| Naming | All code, variables, comments, filenames, UI text in English; README in Chinese; project name "Value Genie" (价值投资精灵), repo `value-genie` |

## Project Structure

```
value-genie/
├── value_genie/                # Python package
│   ├── __init__.py
│   ├── __main__.py             # CLI entry: fetch / screen
│   ├── config.py               # endpoints, defaults, strategy presets, paths
│   ├── fetch/
│   │   ├── __init__.py
│   │   ├── http.py             # retry + rate-limit cooldown HTTP client
│   │   ├── quotes.py           # full-market batch quotes (A/HK/US, clist paging)
│   │   ├── fundamentals.py     # A-share batch financials / HK F10 / US SEC EDGAR
│   │   ├── kline.py            # daily klines (EM primary + Tencent fallback)
│   │   └── pipeline.py         # funnel orchestration, incremental updates, manifest
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── factors.py          # factor computation + per-market percentile ranks
│   │   ├── composite.py        # weighted composite scoring engine
│   │   └── presets.py          # strategy preset profiles
│   └── report.py               # CSV / Markdown exports
├── app.py                      # Streamlit interactive dashboard
├── tests/                      # pytest unit tests
├── pyproject.toml
├── requirements.txt
├── README.md                   # Chinese, concise
└── LICENSE                     # MIT (keep)
```

Usage:
```bash
python -m value_genie fetch            # incremental data pipeline (--refresh for full)
python -m value_genie screen           # CLI screening
streamlit run app.py                   # interactive web app
```

## Data Pipeline (funnel)

```
Stage 1 — full market quotes (3 markets, paged batch, 100% coverage)
         + A-share batch financials (EM datacenter paged report)
         + US batch financials (SEC EDGAR frames by concept)
    → first-pass composite score on the whole market
Stage 2 — top ~200 per market candidates
    → deep data: klines (position/momentum/volatility), HK F10, US companyfacts
    → full factor table → final composite score → ranking + exports
```

| Data | Market | Source | Coverage |
|---|---|---|---|
| Full-market quotes | A/HK/US | EM clist paging | 100% |
| Batch financials | A | EM datacenter paged reports | 100% |
| Batch financials | US | SEC EDGAR frames (per-concept, market-wide) | mainstream filers |
| Deep financials | HK/US candidates | EM F10 / SEC companyfacts | top candidates |
| Klines | candidates | EM primary + Tencent fallback | top candidates |

### Freshness guarantees (requirement 3)

- manifest records timestamps for every dataset
- quotes must be from the latest trading day; klines ≤ 1 trading day stale;
  fundamentals ≤ 1 reporting period stale; stale data auto-refetched
- UI shows as-of date banner with staleness warning
- incremental mode reuses fresh data, re-fetches stale data

## Strategy Engine (requirements 4 & 7)

Unified 4-pillar factor engine, per-market percentile scores 0–100:

| Pillar | Factors |
|---|---|
| Value | earnings yield (1/PE), book yield (1/PB), sales yield (1/PS), dividend yield |
| Growth | revenue YoY, net profit YoY, latest quarter revenue YoY |
| Quality | ROE, gross margin, net margin, low leverage (Piotroski-style health) |
| Safety | 52-week position, volatility, drawdown from 52-week high |

Hard gates (always on): positive earnings, positive revenue growth, exclude
ST/delisting-risk names, minimum market cap (configurable). Composite =
weighted average of available pillars with weight renormalization on missing
data (reuse proven logic from current analyze.py).

Preset profiles (weight archives over the same engine; UI switch + custom
sliders):

| Preset | Value/Growth/Quality/Safety | Inspiration |
|---|---|---|
| Balanced (default) | 35/25/30/10 | multi-factor blend |
| Magic Formula | 50/0/50/0 | Greenblatt |
| GARP | 25/45/30/0 | growth at reasonable price |
| Deep Value | 55/0/25/20 | deep value |
| Custom | user sliders | — |

## Web UI (requirement 5)

- Sidebar: snapshot date dropdown (historical switch), A/HK/US checkboxes,
  strategy preset + weight sliders, market-cap / result-count filters
- Main: data-freshness banner → best-picks ranking table (composite + 4 pillar
  breakdown + key metrics) → Plotly charts (score distribution, value-quality
  scatter bubble chart, top-picks bar chart) → per-stock detail (kline chart +
  factor radar + vs-market-median comparison) → CSV download
- Strategy/weight changes recompute instantly (no re-fetch)

## Data Storage

```
data/
├── snapshots/
│   └── YYYYMMDD/          # one folder per run day
│       ├── manifest.json
│       ├── a_shares.csv  hk_stocks.csv  us_stocks.csv   # stage-1 full market
│       ├── candidates.csv                            # stage-2 deep pool
│       └── kline/{MARKET}_{CODE}.csv
└── latest -> snapshots/YYYYMMDD   # pointer file (latest.json) for default load
```

## Other

- README (Chinese, concise): badges, one-line pitch, feature table, quick
  start, architecture diagram, strategy methodology, data sources, disclaimer
- Remove old scripts (`fetch_data.py`, `analyze.py`) and old Chinese-named
  data files (git history preserves them); commit a fresh snapshot after first
  successful pipeline run so clones are reproducible
- Tests: pytest covering factor computation, weight renormalization, preset
  validation, candidate selection
- Full refresh ~20–30 min; incremental much faster
- FX handling: HKD/CNY auto-detected (existing logic), all scores computed
  within-market so cross-currency comparison is avoided

## Non-goals

- Backtesting engine (possible future version)
- Real-time intraday data
- Non-English UI (stock names shown as returned by sources)
