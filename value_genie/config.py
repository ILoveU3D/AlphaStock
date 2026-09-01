"""Central configuration: endpoints, universes, gates, funnel rules, paths.

All tunable constants live here so the rest of the codebase stays declarative.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
OUTPUT_DIR = BASE_DIR / "output"
SKILLS_DIR = BASE_DIR / "skills"
LATEST_POINTER = DATA_DIR / "latest.json"

# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------
MARKETS = ("A", "HK", "US")

MARKET_LABELS = {"A": "A-share", "HK": "Hong Kong", "US": "US"}

MARKET_CURRENCIES = {"A": "CNY", "HK": "HKD", "US": "USD"}

# Eastmoney clist `fs` filter strings for each market's full universe.
# A: Shanghai main/GEM + Shenzhen main/STAR + Beijing exchange.
# US: NASDAQ / NYSE / AMEX (OTC deliberately excluded).
EM_FS = {
    "A": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
    "HK": "m:128",
    "US": "m:105,m:106,m:107",
}

# ---------------------------------------------------------------------------
# Eastmoney push2 endpoints
# ---------------------------------------------------------------------------
EM_UT_LIST = "bd1d9ddb04089700cf9c27f6f7426281"
EM_UT_QUOTE = "fa5fd1943c7b386f172d6893dbfba10b"
EM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# push2 mirror hosts, tried in order. The `delay` mirrors serve the same
# clist/ulist/kline APIs (~15 min lag, irrelevant for daily screening) and
# are far more tolerant of heavy automated traffic.
# http (not https) is required for push2, https gets connection-reset.
EM_PUSH2_HOSTS = ["push2delay.eastmoney.com", "push2.eastmoney.com",
                  "33.push2.eastmoney.com", "17.push2.eastmoney.com",
                  "88.push2.eastmoney.com"]
# Skip a mirror for this many seconds after it fails once.
EM_HOST_COOLDOWN = 60.0
# Retries for a single clist page before continuing with partial data.
QUOTE_PAGE_RETRIES = 3

# clist field map: EM field id -> master column name.
CLIST_FIELDS = {
    "f2": "price", "f3": "pct_chg", "f5": "volume", "f6": "amount",
    "f8": "turnover", "f9": "pe_dyn", "f12": "code", "f13": "market_id",
    "f14": "name", "f20": "market_cap", "f21": "float_cap", "f23": "pb",
    "f100": "industry", "f114": "pe_static", "f115": "pe_ttm",
}
CLIST_FIELD_IDS = ",".join(CLIST_FIELDS)

# ---------------------------------------------------------------------------
# Eastmoney datacenter endpoints (financial reports)
# ---------------------------------------------------------------------------
DC_WEB_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
DC_SEC_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

# A-share batch performance report (业绩报表), paged by REPORTDATE.
A_REPORT_NAME = "RPT_LICO_FN_CPD"
A_CASHFLOW_REPORT_NAME = "RPT_DMSK_FN_CASHFLOW"
A_PAGE_SIZE = 500
# A report is considered "current season" when at least this many rows exist.
A_MIN_REPORT_ROWS = 1000

# HK F10 main indicators, per stock, latest 12 report periods.
HK_REPORT_NAME = "RPT_HKF10_FN_MAININDICATOR"

# ---------------------------------------------------------------------------
# SEC EDGAR endpoints (US fundamentals via XBRL frames)
# ---------------------------------------------------------------------------
SEC_FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{frame}.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC requires a declared automated-tool UA with contact info:
# https://www.sec.gov/os/accessing-edgar-data
SEC_HEADERS = {
    "User-Agent": "ValueGenie Research valuegenie.research@outlook.com",
    "Accept-Encoding": "gzip, deflate",
}

# US frames spec: (concept, kind, period_keys).
# kind "duration" concepts take frames like CY2025 / CY2026Q2;
# kind "instant" concepts take frames like CY2025Q4I (period-end values).
# Period keys: cy / cy_prev = latest and prior complete calendar years,
# q / q_prev = latest reported quarter and its year-ago counterpart.
US_FRAMES_SPEC = [
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "duration",
     ["cy", "cy_prev", "q", "q_prev"]),
    ("Revenues", "duration", ["cy", "cy_prev"]),
    ("NetIncomeLoss", "duration", ["cy", "cy_prev"]),
    ("NetCashProvidedByUsedInOperatingActivities", "duration", ["cy"]),
    ("GrossProfit", "duration", ["cy"]),
    ("StockholdersEquity", "instant", ["cy", "cy_prev"]),
    ("Liabilities", "instant", ["cy"]),
    ("Assets", "instant", ["cy"]),
    # one-off P&L items (must stay in sync with US_ONEOFF_CONCEPTS below)
    ("DisposalGroupNotDiscontinuedOperationGainLossOnDisposal", "duration",
     ["cy", "cy_prev"]),
    ("GainLossOnDispositionOfAssets1", "duration", ["cy", "cy_prev"]),
    ("GainLossOnSaleOfBusiness", "duration", ["cy", "cy_prev"]),
]

# One-off (disposal) gain/loss concepts summed into `oneoff` and stripped
# from net income so profit_yoy / net_margin / roe reflect RECURRING
# earnings. Filers tag the same economic event differently: WTM's Bamboo
# disposal used the first concept, Boyd's FanDuel stake sale the second,
# most business sales the third. Values are pre-tax, so affected names
# are scored conservatively (see derive_us_metrics).
US_ONEOFF_CONCEPTS = (
    "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
    "GainLossOnDispositionOfAssets1",
    "GainLossOnSaleOfBusiness",
)

# Tencent fallback endpoints for klines, tried in order. The legacy
# fqkline/get path started returning HTTP 501 (2026-08); newfqkline/get and
# the proxy.finance.qq.com mirror of the old path both still serve data.
TX_KLINE_URLS = [
    "https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get",
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get",
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
]
TX_UA = {"User-Agent": "Mozilla/5.0"}
US_TX_SUFFIX = {"105": "OQ", "106": "N", "107": "A", "138": "PS"}

# ---------------------------------------------------------------------------
# Universe gates (hard filters, always applied)
# ---------------------------------------------------------------------------
MIN_MARKET_CAP = {"A": 3e9, "HK": 2e9, "US": 1e9}      # local currency
MIN_HK_DAILY_AMOUNT = 5e6                               # HKD turnover floor
KLINE_DAYS = 300                                        # bars per candidate
MIN_PILLARS = 3                                         # for composite score

# A-share risk-name exclusion substrings.
A_EXCLUDE_NAME_SUBSTR = ("ST", "退")

# US non-operating product exclusion patterns (regex, case-insensitive):
# leveraged/inverse ETPs, preferred share classes, sector basket products.
# Eastmoney mixes English and localized Chinese display names.
US_EXCLUDE_NAME_PATTERNS = (
    r"\b\d+(?:\.\d+)?x\b",           # 2x / 3x / 1.5x leverage multipliers
    r"inverse|leveraged|leverage",
    r"\bpfd\b|preferred",
    r"\bseries [a-z]\b",             # "Series D" preferred classes
    r"\b(?:etf|etn|etrn|uit)\b",
    r"microsectors",                   # MicroSectors leveraged baskets
    r"做多|做空|两倍|二倍|三倍|四倍|五倍|优先股",  # localized leveraged/pfd
)

# ---------------------------------------------------------------------------
# Funnel (stage-1 pre-ranking, before deep data)
# ---------------------------------------------------------------------------
CANDIDATES_PER_MARKET = 200

# Stage-1 blend weights per market over available pillar scores.
FUNNEL_WEIGHTS = {
    "A": {"value": 0.40, "growth": 0.30, "quality": 0.30},
    "US": {"value": 0.40, "growth": 0.30, "quality": 0.30},
    "HK": {"value": 1.00, "growth": 0.00, "quality": 0.00},
}

# ---------------------------------------------------------------------------
# Data freshness rules (incremental mode)
# ---------------------------------------------------------------------------
# Klines are fresh if the last bar is within this many calendar days
# (A/HK: same trading day; US allows 3 days for timezone lag).
KLINE_FRESH_DAYS = {"A": 0, "HK": 0, "US": 3}
# HK F10 / deep financials reuse window in days.
DEEP_FRESH_DAYS = 7

DEFAULT_PRESET = "balanced"
DEFAULT_TOP_N = 20
