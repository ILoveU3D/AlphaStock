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
    total = 0
    partial = False
    while True:
        d = em_push2_get("/api/qt/clist/get", params={
            "pn": pn, "pz": PAGE_SIZE, "po": 0, "np": 1, "fltt": 2,
            "invt": 2, "fid": "f12", "fs": config.EM_FS[market],
            "fields": config.CLIST_FIELD_IDS, "ut": config.EM_UT_LIST,
        })
        data = (d or {}).get("data") or {}
        rows = data.get("diff") or []
        if d is not None:
            # only a successful response may advance the total; a failed
            # page leaves it at the last known value
            total = data.get("total") or total
        if not rows:
            if d is not None and all_rows and len(all_rows) >= total:
                break  # last page already complete
            page_fails += 1
            if page_fails > config.QUOTE_PAGE_RETRIES:
                print(f"    [{market}] WARN: page {pn} failed "
                      f"{page_fails - 1}x, continuing with partial quotes")
                partial = True
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
    if not all_rows or partial:
        # EM push2 outage (or a truncated universe): prefer a COMPLETE
        # Tencent-degraded universe over a partial/rich EM one — the funnel
        # screens the whole market, so missing rows lose candidates.
        tx = fetch_market_quotes_tx(market)
        if not tx.empty:
            return tx
    if not all_rows:
        print(f"    [{market}] WARN: no quotes fetched")
        return pd.DataFrame(columns=["market", "code"])
    df = pd.DataFrame(all_rows)
    df.insert(0, "market", market)
    # A-share codes arrive zero-padded; normalize HK to 5 digits, drop .SH/.SZ
    if market == "HK":
        df["code"] = df["code"].astype(str).str.zfill(5)
    if partial:
        # the pipeline must not persist a half universe as complete
        df.attrs["partial"] = True
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
# Tencent full-market batch fallback (EM push2 outage)
# ---------------------------------------------------------------------------
TX_BATCH_SIZE = 50
TX_BATCH_SLEEP = 0.25


def _prev_universe_quotes(market: str) -> pd.DataFrame:
    """Universe for the Tencent fallback: most recent persisted quotes CSV,
    else a degraded stand-in (US = us_financials tickers, the same universe
    the SEC operating-company gate screens; other markets = latest
    master.csv slice).

    Quotes CSVs are same-day scratch — a completed run persists none, so
    without the stand-ins an EM outage day finds no universe exactly when
    the fallback is needed (2026-09-30 outage: US silently dropped).
    """
    root = config.SNAPSHOTS_DIR
    if not root.exists():
        return pd.DataFrame()
    fname = f"{market.lower()}_quotes.csv"
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
    for d in dirs:
        p = d / fname
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            continue
        if not df.empty and "code" in df.columns:
            return df
    # quotes CSVs are same-day scratch (a completed run keeps none), so a
    # same-day EM outage finds no persisted universe exactly when the TX
    # fallback is needed. Degraded universes: US screens the SEC-frames
    # universe anyway (operating-company gate), so the us_financials
    # ticker list is the complete candidate set; other markets fall back
    # to the latest master.csv slice (funnel survivors — new entrants are
    # missed, declared via the fallback attr downstream).
    if market == "US":
        for d in dirs:
            p = d / "us_financials.csv"
            if not p.exists():
                continue
            try:
                fin = pd.read_csv(p, dtype={"ticker": str})
            except (OSError, pd.errors.ParserError, ValueError):
                continue
            if not fin.empty and "ticker" in fin.columns:
                codes = fin["ticker"].dropna().astype(str).unique()
                return pd.DataFrame({"code": codes, "industry": ""})
    for d in dirs:
        p = d / "master.csv"
        if not p.exists():
            continue
        try:
            m = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            continue
        if not m.empty and "market" in m.columns and "code" in m.columns:
            m = m[m["market"].astype(str) == market]
            keep = [c for c in ("code", "name", "industry", "market_id")
                    if c in m.columns]
            if not m.empty:
                return m[keep].reset_index(drop=True)
    return pd.DataFrame()


def fetch_market_quotes_tx(market: str,
                           universe: pd.DataFrame | None = None) -> pd.DataFrame:
    """Full-market quotes via Tencent's batch endpoint (EM push2 fallback).

    Field basis (probed 2026-09-28; HK/US idx37 re-probed 2026-09-30):
    idx1 name, idx2 code (US carries the
    '.OQ'-style suffix — the request-symbol map is authoritative), idx3
    price, idx4 prev close, idx6 volume, idx37 amount (A: 10k CNY units;
    HK/US: raw local currency), idx38 turnover (A only),
    idx39 PE (Tencent dynamic basis — NOT EM
    pe_ttm), idx44/45 float/total market cap in 100M local currency,
    idx46 PB (A only; HK/US carry a string there -> None). industry and
    market_id are inherited from the latest persisted universe. pe_dyn /
    pe_static stay None. The frame's attrs mark fallback=tencent.
    """
    if universe is None:
        universe = _prev_universe_quotes(market)
    if universe.empty:
        print(f"    [{market}] WARN: no persisted universe for TX fallback")
        return pd.DataFrame()
    sym2code, symbols = {}, []
    for c in universe["code"].astype(str):
        cands = _tx_quote_symbols(market, c)
        if cands:
            sym2code[cands[0]] = c
            symbols.append(cands[0])
    rows = []
    for i in range(0, len(symbols), TX_BATCH_SIZE):
        batch = symbols[i:i + TX_BATCH_SIZE]
        try:
            r = TX.session.get(config.TX_QUOTE_URL + ",".join(batch),
                               timeout=15)
            if r.status_code != 200:
                continue
            text = r.content.decode("gbk", errors="replace")
        except Exception:  # noqa: BLE001 — degraded path must not raise
            continue
        for line in text.strip().splitlines():
            if "=" not in line:
                continue
            sym = line.split("=", 1)[0].strip()
            sym = sym[2:] if sym.startswith("v_") else sym
            payload = line.split("=", 1)[1].strip().strip(";").strip('"')
            parts = payload.split("~")
            if len(parts) < 47:
                continue  # "none"/error rows and short layouts
            price, prev = num(parts[3]), num(parts[4])
            if price is None:
                continue
            # idx37 turnover: A = 万元 (×1e4); HK/US = raw local currency
            # (probed 2026-09-30: hk00700 idx37 == volume×price exactly,
            # usNVDA likewise) — without it the HK liquidity gate
            # (amount >= MIN_HK_DAILY_AMOUNT) zeroes the whole TX frame
            amount_raw = num(parts[37])
            if market == "A":
                amount = amount_raw * 1e4 if amount_raw is not None else None
            else:
                amount = amount_raw
            mcap, fcap = num(parts[45]), num(parts[44])
            rows.append({
                "code": sym2code.get(sym, parts[2].split(".")[0]),
                "name": parts[1],
                "price": price,
                "pct_chg": ((price / prev - 1.0) * 100.0
                            if prev is not None and prev > 0 else None),
                "volume": num(parts[6]),
                "amount": amount,
                "turnover": num(parts[38]) if market == "A" else None,
                "pe_dyn": None,
                "pe_static": None,
                "pe_ttm": num(parts[39]),
                "pb": num(parts[46]),
                "market_cap": mcap * 1e8 if mcap is not None else None,
                "float_cap": fcap * 1e8 if fcap is not None else None,
            })
        if (i // TX_BATCH_SIZE) % 20 == 0:
            print(f"    [{market}] tx quotes: {len(rows)}/{len(symbols)}")
        time.sleep(TX_BATCH_SLEEP)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.insert(0, "market", market)
    static_cols = [c for c in ("industry", "market_id")
                   if c in universe.columns]
    if static_cols:
        df = df.merge(universe[["code"] + static_cols], on="code",
                      how="left")
        for c in static_cols:
            df[c] = df[c].fillna("")
    else:
        df["industry"], df["market_id"] = "", ""
    df.attrs["fallback"] = "tencent"
    df.attrs["pe_basis"] = "tencent_idx39"
    print(f"    [{market}] quotes: {len(df)} via Tencent fallback "
          f"(pe=idx39 basis, pb A-share only)")
    return df



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
