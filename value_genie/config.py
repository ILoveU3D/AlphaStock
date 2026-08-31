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

# Eastmoney market id -> kline secid prefix.
EM_MARKET_ID = {"A": ("0", "1"), "HK": ("116",),
                "US": ("105", "106", "107")}

# ---------------------------------------------------------------------------
# Eastmoney push2 endpoints
# ---------------------------------------------------------------------------
EM_UT_LIST = "bd1d9ddb04089700cf9c27f6f7426281"
EM_UT_QUOTE = "fa5fd1943c7b386f172d6893dbfba10b"
EM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# http (not https) is required for push2/push2his, https gets connection-reset.
EM_PUSH2_HOSTS = ["push2.eastmoney.com", "33.push2.eastmoney.com",
                  "17.push2.eastmoney.com", "88.push2.eastmoney.com"]

CLIST_URL = "http://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
ULIST_URL = "http://push2.eastmoney.com/api/qt/ulist.np/get"

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
SEC_HEADERS = {
    "User-Agent": "ValueGenie value-screening research script (github.com/value-genie)",
    "Accept-Encoding": "gzip, deflate",
}

# (concept, unit, frame) tuples fetched for the whole US market.
# Annual frames give YoY bases; Q2 frames give latest-quarter YoY.
US_FRAMES_SPEC = [
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "{cy}"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "{cy_prev}"),
    ("Revenues", "USD", "{cy}"),
    ("Revenues", "USD", "{cy_prev}"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "{q}"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "{q_prev}"),
    ("NetIncomeLoss", "USD", "{cy}"),
    ("NetIncomeLoss", "USD", "{cy_prev}"),
    ("GrossProfit", "USD", "{cy}"),
    ("StockholdersEquity", "USD", "{cy}"),
    ("StockholdersEquity", "USD", "{cy_prev}"),
    ("Liabilities", "USD", "{cy}"),
    ("Assets", "USD", "{cy}"),
]

# Tencent fallback endpoints for klines.
TX_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
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
