"""Full-market quote fetching via Eastmoney clist paged API.

Covers the entire listed universe per market (A-share / HK / US) with a
single paged endpoint, providing price, valuation and size fields used by
the stage-1 funnel.
"""

import time

import pandas as pd

from .. import config
from .http import em_push2_get, num

PAGE_SIZE = 100
PAGE_SLEEP = 0.6


def _parse_clist_rows(rows: list) -> list:
    """Map raw clist field dicts to master-style dicts."""
    out = []
    for r in rows or []:
        code = str(r.get("f12", ""))
        price = num(r.get("f2"))
        if not code or price is None:
            continue
        rec = {col: r.get(fid) for fid, col in config.CLIST_FIELDS.items()}
        rec["code"] = code
        for col in ("price", "pct_chg", "volume", "amount", "turnover",
                    "pe_dyn", "pe_static", "pe_ttm", "pb",
                    "market_cap", "float_cap"):
            rec[col] = num(rec.get(col))
        rec["market_id"] = str(r.get("f13", ""))
        rec["name"] = str(r.get("f14", ""))
        rec["industry"] = str(r.get("f100", "") or "")
        out.append(rec)
    return out


def fetch_market_quotes(market: str) -> pd.DataFrame:
    """Fetch the full listed universe for one market.

    Returns a DataFrame with columns: market, code, name, industry,
    market_id, price, pct_chg, volume, amount, turnover, pe_dyn, pe_static,
    pe_ttm, pb, market_cap, float_cap. Empty frame on total failure.
    """
    all_rows, pn = [], 1
    page_fails = 0
    while True:
        d = em_push2_get("/api/qt/clist/get", params={
            "pn": pn, "pz": PAGE_SIZE, "po": 0, "np": 1, "fltt": 2,
            "invt": 2, "fid": "f12", "fs": config.EM_FS[market],
            "fields": config.CLIST_FIELD_IDS, "ut": config.EM_UT_LIST,
        })
        data = (d or {}).get("data") or {}
        rows = data.get("diff") or []
        total = data.get("total", 0)
        if not rows:
            if all_rows and len(all_rows) >= total:
                break  # last page already complete
            page_fails += 1
            if page_fails > config.QUOTE_PAGE_RETRIES:
                print(f"    [{market}] WARN: page {pn} failed "
                      f"{page_fails - 1}x, continuing with partial quotes")
                break
            time.sleep(4.0 * page_fails)
            continue  # retry the same page
        page_fails = 0
        all_rows.extend(_parse_clist_rows(rows))
        if pn % 10 == 0 or len(all_rows) >= total:
            print(f"    [{market}] quotes: {len(all_rows)}/{total}")
        if len(all_rows) >= total:
            break
        pn += 1
        time.sleep(PAGE_SLEEP)
    if not all_rows:
        print(f"    [{market}] WARN: no quotes fetched")
        return pd.DataFrame(columns=["market", "code"])
    df = pd.DataFrame(all_rows)
    df.insert(0, "market", market)
    # A-share codes arrive zero-padded; normalize HK to 5 digits, drop .SH/.SZ
    if market == "HK":
        df["code"] = df["code"].astype(str).str.zfill(5)
    return df


def fetch_quotes_by_secids(secids: list) -> pd.DataFrame:
    """Real-time quotes for explicit secids like '1.600519', '116.02555'.

    Uses the same push2 field layout as the clist batch endpoint, so
    rows carry the same columns. Empty frame on failure.
    """
    if not secids:
        return pd.DataFrame()
    d = em_push2_get("/api/qt/ulist.np/get", params={
        "secids": ",".join(secids), "fltt": 2, "invt": 2, "np": 1,
        "fields": config.CLIST_FIELD_IDS, "ut": config.EM_UT_LIST,
    })
    rows = ((d or {}).get("data") or {}).get("diff") or []
    return pd.DataFrame(_parse_clist_rows(rows))


def exclude_risk_names(df: pd.DataFrame) -> pd.DataFrame:
    """Drop A-share ST / delisting-risk names."""
    if df.empty or "name" not in df.columns:
        return df
    mask = ~df["name"].str.contains("|".join(config.A_EXCLUDE_NAME_SUBSTR),
                                    na=False)
    return df[mask]


def exclude_non_operating_names(df: pd.DataFrame) -> pd.DataFrame:
    """Drop US leveraged/inverse ETPs and preferred share classes.

    Eastmoney US listings include hundreds of non-operating products
    whose tiny positive PE lets them dominate any value ranking.
    """
    if df.empty or "name" not in df.columns:
        return df
    pat = "|".join(config.US_EXCLUDE_NAME_PATTERNS)
    mask = ~df["name"].str.contains(pat, na=False, regex=True, case=False)
    return df[mask]
