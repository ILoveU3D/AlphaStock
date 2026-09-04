"""Daily kline (OHLCV) fetching with Eastmoney primary and Tencent fallback.

Klines are cached per candidate as CSV files inside the snapshot directory;
freshness is market-aware (A/HK must include the latest completed trading
day, US may lag up to 3 calendar days because its session closes early
morning Beijing time).
"""

import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from .http import TX, em_push2_get, num

KLINE_COLS = ["date", "open", "close", "high", "low", "volume", "amount"]

# clist quote market ids (f13) differ from kline secid prefixes for HK:
# quotes say 128, klines want 116. A (0/1) and US (105/106/107) match.
CLIST_TO_SECID = {"128": "116"}


# ---------------------------------------------------------------------------
# Eastmoney primary
# ---------------------------------------------------------------------------
def fetch_kline(secid: str, lmt: int = 300) -> pd.DataFrame | None:
    """Daily forward-adjusted kline from Eastmoney push2his.

    `secid` is the Eastmoney security id, e.g. "1.600519", "116.00700",
    "105.AAPL". Returns None when no data is available.
    """
    d = em_push2_get("/api/qt/stock/kline/get", params={
        "secid": secid, "klt": 101, "fqt": 1, "lmt": lmt,
        "end": "20500101", "iscr": 0,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "ut": config.EM_UT_QUOTE,
    })
    klines = (((d or {}).get("data")) or {}).get("klines") or []
    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) < 6:
            continue
        rows.append({"date": p[0], "open": num(p[1]), "close": num(p[2]),
                     "high": num(p[3]), "low": num(p[4]),
                     "volume": num(p[5]),
                     "amount": num(p[6]) if len(p) > 6 else None})
    return pd.DataFrame(rows, columns=KLINE_COLS) if rows else None


# ---------------------------------------------------------------------------
# Tencent fallback
# ---------------------------------------------------------------------------
def tx_symbol_candidates(market: str, code: str,
                         market_id: str = "") -> list:
    """Tencent symbol candidates for one stock, best guess first."""
    if market == "A":
        if code.startswith(("6", "9")):
            return [f"sh{code}"]
        if code.startswith(("4", "8")):
            return [f"bj{code}", f"sz{code}"]
        return [f"sz{code}"]
    if market == "HK":
        return [f"hk{code}"]
    # US: "us{TICKER}.{exchange}", primary exchange from quote market_id
    # first (OQ=NASDAQ, N=NYSE, A=AMEX), then the rest as fallback.
    primary = config.US_TX_SUFFIX.get(market_id or "")
    suffixes = ([primary] if primary else []) + [
        s for s in config.US_TX_SUFFIX.values() if s != primary]
    syms = [f"us{code}.{s}" for s in suffixes]
    if "_" in code:
        # class shares: Tencent uses the dot-separated SEC form
        # (BRK_B -> usBRK.B.N); Eastmoney's underscore form fails there
        syms += [f"us{code.replace('_', '.')}.{s}" for s in suffixes]
    return syms


def fetch_kline_tx(symbol: str, lmt: int = 320) -> pd.DataFrame | None:
    """Daily forward-adjusted kline from Tencent. None on no data.

    Tries each configured endpoint in order; rows carry optional extra
    elements (dict at index 6, more strings after) which are ignored.
    """
    for url in config.TX_KLINE_URLS:
        d = TX.get_json(url, params={
            "param": f"{symbol},day,,,{lmt},qfq"}, retries=2)
        data = ((d or {}).get("data") or {}).get(symbol) or {}
        klines = data.get("qfqday") or data.get("day") or []
        rows = []
        for item in klines:
            # [date, open, close, high, low, volume, ...]
            if not isinstance(item, (list, tuple)) or len(item) < 6:
                continue
            rows.append({"date": str(item[0]), "open": num(item[1]),
                         "close": num(item[2]), "high": num(item[3]),
                         "low": num(item[4]), "volume": num(item[5]),
                         "amount": (num(item[6]) if len(item) > 6
                                    and not isinstance(item[6], dict)
                                    else None)})
        if rows:
            return pd.DataFrame(rows, columns=KLINE_COLS)
    return None


def fetch_kline_any(market: str, code: str, market_id: str = "",
                    lmt: int = 300) -> pd.DataFrame | None:
    """EM first, then every Tencent symbol candidate."""
    secid_prefix = CLIST_TO_SECID.get(market_id, market_id)
    secid = f"{secid_prefix}.{code}" if secid_prefix else None
    if secid:
        df = fetch_kline(secid, lmt=lmt)
        if df is not None and not df.empty:
            return df
        time.sleep(0.2)
    for sym in tx_symbol_candidates(market, code, market_id):
        df = fetch_kline_tx(sym, lmt=lmt + 20)
        if df is not None and not df.empty:
            return df
    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def save_kline(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def load_kline(path: Path) -> pd.DataFrame | None:
    """Read a cached kline CSV; None when missing or unreadable."""
    try:
        return pd.read_csv(path, dtype={"date": str})
    except (OSError, pd.errors.ParserError, ValueError):
        return None


def kline_cache_path(snapshot_dir: Path, market: str, code: str) -> Path:
    return snapshot_dir / "kline" / f"{market}_{code}.csv"


def last_expected_trading_day(market: str, now: datetime | None = None) -> date:
    """Most recent date whose session should be fully reflected in klines.

    A/HK bars appear after the ~16:00 close; the US session closes early
    morning Beijing time, so its latest bar lags one calendar day.
    """
    now = now or datetime.now()
    d = now.date()
    if market == "US":
        d -= timedelta(days=1)
    elif now.hour < 17:
        d -= timedelta(days=1)
    while d.weekday() >= 5:  # skip Sat/Sun
        d -= timedelta(days=1)
    return d


def kline_is_fresh(path: Path, market: str,
                   now: datetime | None = None) -> bool:
    """True when the cached kline covers the latest expected trading day
    (plus the per-market tolerance in calendar days)."""
    kl = load_kline(path)
    if kl is None or kl.empty or "date" not in kl.columns:
        return False
    try:
        last = pd.to_datetime(kl["date"].iloc[-1]).date()
    except (ValueError, TypeError):
        return False
    expected = last_expected_trading_day(market, now)
    return (expected - last).days <= config.KLINE_FRESH_DAYS[market]
