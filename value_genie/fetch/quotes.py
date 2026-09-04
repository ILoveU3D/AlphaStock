"""Full-market quote fetching via Eastmoney clist paged API.

Covers the entire listed universe per market (A-share / HK / US) with a
single paged endpoint, providing price, valuation and size fields used by
the stage-1 funnel.
"""

import time

import pandas as pd

from .. import config
from .http import TX, em_push2_get, num

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


# ---------------------------------------------------------------------------
# Tencent realtime quote fallback (price redundancy when EM ulist fails)
# ---------------------------------------------------------------------------
def fetch_quote_tx(symbol: str) -> dict | None:
    """Tencent realtime quote (GBK text), e.g. sh588060 / hk00700 / usAAPL.

    Returns {code, name, price, prev_close, pct_chg} or None. Layout:
    idx1 name, idx2 code, idx3 price, idx4 prev close.
    """
    try:
        r = TX.session.get(config.TX_QUOTE_URL + symbol, timeout=10)
        if r.status_code != 200:
            return None
        text = r.content.decode("gbk", errors="replace")
    except Exception:  # noqa: BLE001 — network layer must never raise
        return None
    line = text.strip().splitlines()[0] if text.strip() else ""
    if "=" not in line:
        return None
    payload = line.split("=", 1)[1].strip().strip(';').strip('"')
    parts = payload.split("~")
    if len(parts) < 5:
        return None
    name, code = parts[1], parts[2]
    price, prev = num(parts[3]), num(parts[4])
    if not name or price is None:
        return None
    pct = ((price / prev - 1.0) * 100.0
           if prev is not None and prev > 0 else None)
    return {"code": code, "name": name, "price": price,
            "prev_close": prev, "pct_chg": pct}


def _tx_quote_symbols(market: str, code: str) -> list:
    """Tencent symbol candidates for a realtime quote (US: no suffix)."""
    if market == "A":
        # SH: 6/9 stocks, 5 funds (ETFs like 588060); SZ: everything else
        if code.startswith(("5", "6", "9")):
            return [f"sh{code}"]
        if code.startswith(("4", "8")):
            return [f"bj{code}", f"sz{code}"]
        return [f"sz{code}"]
    if market == "HK":
        return [f"hk{code}"]
    syms = [f"us{code}"]
    if "_" in code:
        # class shares: Tencent may know the dot-separated form (BRK.B)
        syms.append(f"us{code.replace('_', '.')}")
    return syms


def fetch_quote_any(market: str, code: str, market_id: str = "") -> dict | None:
    """One quote row, EM ulist first, Tencent realtime as fallback.

    Covers symbols outside the clist universe (ETFs, funds) and EM
    outages. Returns a dict with code/name/price/pe_ttm/pb/market_cap/
    market_id where available, or None when both sources fail.
    """
    secid = None
    if market == "A":
        secid = ("1." if str(code)[:1] in ("5", "6") else "0.") + code
    elif market == "HK":
        secid = "116." + str(code).zfill(5)
    elif market == "US" and market_id:
        secid = f"{market_id}.{code}"
    if secid:
        df = fetch_quotes_by_secids([secid])
        if not df.empty:
            row = df.iloc[0].to_dict()
            if market == "HK":
                row["code"] = str(row["code"]).zfill(5)
            return row
    for sym in _tx_quote_symbols(market, str(code)):
        q = fetch_quote_tx(sym)
        if q is not None:
            q["market_id"] = market_id
            return q
    return None


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
