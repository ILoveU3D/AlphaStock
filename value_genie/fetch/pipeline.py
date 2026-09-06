"""Snapshot pipeline: quotes -> gates -> funnel -> deep data -> master.csv.

Two-stage funnel:
1. Full-market quotes (+ batch financials for A/US) pass hard gates and a
   stage-1 pillar blend to select ~CANDIDATES_PER_MARKET names per market.
2. Candidates get deep data: daily klines (all markets) and HK F10
   financials, then final gates, master assembly and pillar scoring.

Everything lands in a date-stamped snapshot directory; fresh klines and
recent HK F10 rows are reused from the latest prior snapshot.
"""

import json
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .. import config
from ..strategy.composite import apply_composite
from ..strategy.factors import PILLARS, add_pillar_scores, kline_metrics
from .fundamentals import (fetch_a_cashflow, fetch_a_cashflow_annual,
                           fetch_a_dividends, fetch_a_financials,
                           fetch_a_financials_one, fetch_fx_hkdcny,
                           fetch_hk_cashflow, fetch_hk_f10,
                           fetch_us_financials,
                           fetch_us_financials_one, frames_year_context)
from .kline import (fetch_kline_any, kline_cache_path, kline_is_fresh,
                    load_kline, save_kline)
from .quotes import (exclude_non_operating_names, exclude_risk_names,
                     fetch_market_quotes, fetch_quote_any)

MASTER_COLUMNS = [
    "market", "code", "name", "industry", "currency", "price", "market_cap",
    "pe_ttm", "pb", "ps", "dividend_yield", "rev_yoy", "profit_yoy",
    "rev_q_yoy", "roe", "gross_margin", "net_margin", "debt_ratio",
    "ocf_yield", "cash_conversion",
    "fcf_yield", "borrowed_dividend", "capex_to_ocf",
    "pos_52w", "drawdown_52w", "ret_250d", "ret_60d", "volatility",
    "ret_5d", "ret_20d", "vol_20d",
    "report_date", "value_score", "growth_score", "quality_score",
    "safety_score", "momentum_score", "cashflow_score", "data_completeness",
]

KLINE_FEATURES = ("pos_52w", "drawdown_52w", "ret_250d", "ret_60d",
                  "volatility", "ret_5d", "ret_20d", "vol_20d")


# ---------------------------------------------------------------------------
# Stage 1: gates and funnel
# ---------------------------------------------------------------------------
def apply_gates(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Hard universe gates: size, liquidity, positive valuation, growth."""
    out = df.copy()
    if market == "A":
        out = exclude_risk_names(out)
    elif market == "US":
        out = exclude_non_operating_names(out)
    if out.empty:
        return out
    out = out[out["market_cap"] >= config.MIN_MARKET_CAP[market]]
    if market == "HK":
        out = out[out["amount"] >= config.MIN_HK_DAILY_AMOUNT]
    out = out[out["pe_ttm"] > 0]
    if market == "US" and "rev_yoy" in out.columns:
        # operating-company check: US names must carry SEC frames data,
        # otherwise leveraged ETPs with phantom PEs invade the funnel
        out = out[out["rev_yoy"].notna()]
    elif "rev_yoy" in out.columns:
        out = out[out["rev_yoy"].isna() | (out["rev_yoy"] > 0)]
    return out


def merge_a_financials(quotes: pd.DataFrame, fins: pd.DataFrame | None,
                       cashflow: pd.DataFrame | None = None) -> pd.DataFrame:
    """Left-join A-share financials + operating cash flow; derive metrics."""
    out = quotes.copy()
    if fins is None or fins.empty:
        return out
    f = fins.drop_duplicates(subset="code")[
        ["code", "report_date", "revenue", "rev_yoy", "profit", "profit_yoy",
         "roe", "gross_margin"]]
    out = out.merge(f, on="code", how="left")
    if cashflow is not None and not cashflow.empty \
            and "ocf" in cashflow.columns:
        cf = cashflow.drop_duplicates(subset="code")[["code", "ocf"]]
        out = out.merge(cf, on="code", how="left")
        out["ocf_yield"] = out.apply(
            lambda r: r["ocf"] / r["market_cap"] * 100.0
            if r.get("ocf") and r.get("market_cap")
            and r["market_cap"] > 0 else None, axis=1)
        out["cash_conversion"] = out.apply(
            lambda r: r["ocf"] / r["profit"] * 100.0
            if r.get("ocf") and r.get("profit") and r["profit"] != 0
            else None, axis=1)
    out["net_margin"] = out.apply(
        lambda r: r["profit"] / r["revenue"] * 100.0
        if r.get("profit") and r.get("revenue") else None, axis=1)
    out["ps"] = out.apply(
        lambda r: r["market_cap"] / r["revenue"]
        if r.get("revenue") and r["revenue"] > 0 else None, axis=1)
    return out


def merge_us_financials(quotes: pd.DataFrame,
                        fins: pd.DataFrame | None) -> pd.DataFrame:
    """Left-join SEC frame metrics and derive ps / report_date."""
    out = quotes.copy()
    if fins is None or fins.empty:
        return out
    join_cols = ["ticker", "rev", "rev_yoy", "profit_yoy", "rev_q_yoy",
                 "roe", "gross_margin", "net_margin", "debt_ratio"]
    for extra in ("cash_conversion", "ocf", "capex", "div_paid",
                  "net_fin_cf"):
        if extra in fins.columns:
            join_cols.append(extra)
    f = fins.drop_duplicates(subset="ticker")[join_cols]
    out = out.merge(f, left_on="code", right_on="ticker", how="left")
    out["ps"] = out.apply(
        lambda r: r["market_cap"] / r["rev"]
        if r.get("rev") and r["rev"] > 0 else None, axis=1)
    out["report_date"] = f"{frames_year_context()['cy']}-12-31"
    if "ocf" in out.columns:
        out["ocf_yield"] = out.apply(
            lambda r: r["ocf"] / r["market_cap"] * 100.0
            if r.get("ocf") and r.get("market_cap")
            and r["market_cap"] > 0 else None, axis=1)
    return out


def stage1_blend(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Score the stage-1 pool and blend available pillars into one rank."""
    scored = add_pillar_scores(df)
    blended = apply_composite(scored, config.FUNNEL_WEIGHTS[market],
                              min_pillars=1)
    return blended.rename(columns={"composite_score": "stage1_score"})


def select_candidates(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Top-N per market by stage-1 blend score."""
    if df.empty:
        return df
    return df.sort_values("stage1_score", ascending=False).head(
        config.CANDIDATES_PER_MARKET)


# ---------------------------------------------------------------------------
# Stage 2: deep data
# ---------------------------------------------------------------------------
def fetch_klines(cands: pd.DataFrame, market: str, snap_dir: Path,
                 reuse_dirs: list, stats: dict,
                 force: bool = False) -> None:
    """Ensure a cached kline CSV for every candidate (incremental).

    Fresh caches are searched in every reuse dir (today's partial snapshot
    first, then the latest prior snapshot) so crashed runs resume cheaply.
    """
    if cands.empty:
        return
    for _, row in cands.iterrows():
        code = str(row["code"])
        mid = str(row.get("market_id") or "")
        path = kline_cache_path(snap_dir, market, code)
        if not force and path.exists() and kline_is_fresh(path, market):
            stats["reused"] += 1
            continue
        reused = False
        if not force:
            for prev_dir in reuse_dirs:
                prev = kline_cache_path(prev_dir, market, code)
                if prev.exists() and kline_is_fresh(prev, market):
                    save_kline(load_kline(prev), path)
                    stats["reused"] += 1
                    reused = True
                    break
        if reused:
            continue
        df = fetch_kline_any(market, code, mid, lmt=config.KLINE_DAYS)
        if df is not None and not df.empty:
            save_kline(df, path)
            stats["fetched"] += 1
        else:
            stats["failed"] += 1
        time.sleep(0.25)


def fetch_hk_deep(codes, snap_dir: Path, reuse_dirs: list,
                  stats: dict) -> pd.DataFrame:
    """Per-stock HK F10 latest metrics, reusing recent snapshot rows."""
    have = {}
    for prev_dir in reuse_dirs:
        rp = prev_dir / "hk_f10.csv"
        if not rp.exists():
            continue
        try:
            prev = pd.read_csv(rp, dtype={"code": str})
            for _, r in prev.iterrows():
                have.setdefault(str(r["code"]), dict(r))
        except (OSError, pd.errors.ParserError, ValueError):
            continue
    rows = []
    for code in codes:
        code = str(code)
        if code in have:
            rows.append(have[code])
            stats["reused"] += 1
            continue
        f10 = fetch_hk_f10(code)
        if f10 is not None and not f10.empty:
            latest = f10.iloc[0].to_dict()
            latest["code"] = code
            rows.append(latest)
            stats["fetched"] += 1
        else:
            stats["failed"] += 1
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(snap_dir / "hk_f10.csv", index=False)
    return df


def fetch_hk_cashflow_deep(codes, snap_dir: Path, reuse_dirs: list,
                           stats: dict) -> pd.DataFrame:
    """Annual HK cashflow rows for candidates + watch symbols, reusing
    rows saved in a recent snapshot (same chain as fetch_hk_deep)."""
    have = {}
    for prev_dir in reuse_dirs:
        rp = prev_dir / "hk_cashflow.csv"
        if not rp.exists():
            continue
        try:
            prev = pd.read_csv(rp, dtype={"code": str})
            for _, r in prev.iterrows():
                have.setdefault(str(r["code"]), dict(r))
        except (OSError, pd.errors.ParserError, ValueError):
            continue
    rows = []
    for code in codes:
        code = str(code)
        if code in have:
            rows.append(have[code])
            stats["reused"] += 1
            continue
        cf = fetch_hk_cashflow(code)
        if cf is not None and not cf.empty:
            rows.append(cf.iloc[0].to_dict())
            stats["fetched"] += 1
        else:
            stats["failed"] += 1
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(snap_dir / "hk_cashflow.csv", index=False)
    return df


def load_annual_cashflows(snap_dir: Path) -> pd.DataFrame:
    """Annual-basis cash flows for the DCF-first factors, all markets.

    - A: a_cashflow_annual.csv (ocf/capex/net_fin_cf) + a_dividends.csv
      (FY cash dividends declared, matched by report year)
    - HK: hk_cashflow.csv (annual row per code, CNY amounts)
    - US: us_financials.csv extra columns (SEC cy frames)
    Missing files/columns degrade to NaN per row; empty when absent.
    """
    cols = ["market", "code", "ocf", "capex", "div_paid", "net_fin_cf"]
    parts = []

    def _read(name, key):
        p = snap_dir / name
        if not p.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(p, dtype={key: str})
        except (OSError, pd.errors.ParserError, ValueError):
            return pd.DataFrame()

    a = _read("a_cashflow_annual.csv", "code")
    if not a.empty:
        d = pd.DataFrame({"market": "A", "code": a["code"].astype(str)})
        for c in ("ocf", "capex", "net_fin_cf"):
            d[c] = (pd.to_numeric(a[c], errors="coerce")
                    if c in a.columns else float("nan"))
        d["div_paid"] = float("nan")
        d["fy"] = (a["report_date"].astype(str).str.slice(0, 4)
                   if "report_date" in a.columns else "")
        div = _read("a_dividends.csv", "code")
        if not div.empty and {"code", "fy", "div_paid"} <= set(div.columns):
            div = div.drop_duplicates(subset=["code", "fy"])
            # CSV round-trip re-types fy as int64; d["fy"] is str
            div = div.assign(fy=div["fy"].astype(str))[
                ["code", "fy", "div_paid"]]
            d = d.merge(div, on=["code", "fy"], how="left",
                        suffixes=("", "_d"))
            d["div_paid"] = d["div_paid_d"]
            d = d.drop(columns=["div_paid_d"])
        parts.append(d.drop(columns=["fy"]))
    hk = _read("hk_cashflow.csv", "code")
    if not hk.empty:
        d = pd.DataFrame({"market": "HK",
                          "code": hk["code"].astype(str).str.zfill(5)})
        for c in ("ocf", "capex", "div_paid", "net_fin_cf"):
            d[c] = (pd.to_numeric(hk[c], errors="coerce")
                    if c in hk.columns else float("nan"))
        parts.append(d)
    us = _read("us_financials.csv", "ticker")
    if not us.empty and "capex" in us.columns:
        d = pd.DataFrame({"market": "US", "code": us["ticker"].astype(str)})
        d["ocf"] = pd.to_numeric(us.get("ocf"), errors="coerce")
        for c in ("capex", "div_paid", "net_fin_cf"):
            d[c] = pd.to_numeric(us.get(c), errors="coerce")
        parts.append(d)
    if not parts:
        return pd.DataFrame(columns=cols)
    return pd.concat(parts, ignore_index=True)


def add_cashflow_factors(df: pd.DataFrame, fx: float | None,
                         annual: pd.DataFrame) -> pd.DataFrame:
    """Join annual cash flows and derive the DCF-first factor set.

    - fcf_yield: (ocf - capex) / market cap, annual basis — the
      first-order DCF anchor (owner-earnings yield)
    - borrowed_dividend: 1 when FY dividends exceed FCF, exceed half
      of OCF, and financing is a net inflow — dividend kept alive to
      preserve refinancing eligibility (A-share mechanism) rather
      than to reward shareholders; 0 = pass (innocent until proven)
    - capex_to_ocf: reinvestment intensity (display-only)

    ocf_yield is re-based onto the annual figure where available:
    the interim-basis value built from half-year reports understates
    the run-rate ~2x mid-season and distorts Buffett's >=5 gate; rows
    without annual data keep the interim value as fallback.
    HK F10 amounts are CNY while market cap is HKD — converted via fx.
    """
    out = df
    if annual.empty:
        out = df.copy()
        out["fcf_yield"] = float("nan")
        out["capex_to_ocf"] = float("nan")
        out["borrowed_dividend"] = 0
        return out
    # master rows can already carry an interim ocf (A merge / HK F10 /
    # US frames) — merging annual alongside would suffix them into
    # ocf_x/ocf_y and trip the guard below; annual is authoritative
    dup = [c for c in ("ocf", "capex", "div_paid", "net_fin_cf")
           if c in df.columns]
    base = df.drop(columns=dup) if dup else df
    out = base.merge(annual, on=["market", "code"], how="left")
    if "ocf" not in out.columns:
        out["fcf_yield"] = float("nan")
        out["capex_to_ocf"] = float("nan")
        out["borrowed_dividend"] = 0
        return out
    ocf = pd.to_numeric(out.get("ocf"), errors="coerce")
    capex = pd.to_numeric(out.get("capex"), errors="coerce")
    fin = pd.to_numeric(out.get("net_fin_cf"), errors="coerce")
    div = pd.to_numeric(out.get("div_paid"), errors="coerce")
    mcap = pd.to_numeric(out.get("market_cap"), errors="coerce")
    conv = pd.Series(1.0, index=out.index)
    if fx and fx > 0:
        conv[out["market"] == "HK"] = 1.0 / fx  # CNY amount -> HKD

    fcf = ocf - capex
    out["fcf_yield"] = (fcf * conv / mcap.where(mcap > 0) * 100.0).where(
        fcf.notna() & mcap.notna())
    out["capex_to_ocf"] = (capex / ocf.where(ocf != 0)).where(
        capex.notna() & ocf.notna())
    flagged = (div > fcf) & (div > ocf * 0.5) & (fin > 0)
    out["borrowed_dividend"] = flagged.fillna(False).astype(int)

    yld = (ocf * conv / mcap.where(mcap > 0) * 100.0).where(
        ocf.notna() & mcap.notna())
    if "ocf_yield" in out.columns:
        out["ocf_yield"] = yld.fillna(out["ocf_yield"])
    else:
        out["ocf_yield"] = yld
    return out


def kline_features(snap_dir: Path, market: str, code: str) -> dict:
    return kline_metrics(load_kline(kline_cache_path(snap_dir, market,
                                                     str(code))))


def backfill_kline_factors(df: pd.DataFrame, snap_dir: Path) -> pd.DataFrame:
    """Add kline-derived factor columns from the snapshot's kline cache.

    Peer frames rebuilt from quotes CSVs lack kline metrics (those live
    only in master.csv); without this, a target ranks its momentum
    against itself and always shows the 100th percentile. Rows without
    a cached kline stay NaN — pandas ranks skip NaN.
    """
    import sys

    if df is None or df.empty:
        return df
    missing = [c for c in KLINE_FEATURES if c not in df.columns]
    if not missing:
        return df
    out = df.copy()
    for col in missing:
        out[col] = float("nan")
    filled = 0
    for i, row in out.iterrows():
        feats = kline_features(snap_dir, row["market"], str(row["code"]))
        if not feats:
            continue
        filled += 1
        for col in missing:
            v = feats.get(col)
            if v is not None:
                out.at[i, col] = v
    if filled:
        print(f"[INFO] backfilled kline factors for {filled} rows "
              f"from kline cache", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Master assembly
# ---------------------------------------------------------------------------
def _apply_hk_f10(df: pd.DataFrame, hk_map: dict, fx: float | None) -> None:
    """Merge HK F10 metrics into rows in place (F10 amounts are CNY)."""
    for code, rec in hk_map.items():
        mask = df["code"].astype(str) == code
        if not mask.any():
            continue
        for col in ("report_date", "rev_yoy", "profit_yoy", "roe",
                    "gross_margin", "net_margin", "debt_ratio",
                    "dividend_yield", "ocf"):
            df.loc[mask, col] = rec.get(col)
        rev = rec.get("revenue")
        # F10 revenue is CNY; convert to HKD for price-to-sales
        if rev and fx and fx > 0:
            df.loc[mask, "ps"] = df.loc[mask, "market_cap"] * fx / rev
        ocf = rec.get("ocf")
        profit = rec.get("profit")
        if ocf and profit and profit != 0:
            # both CNY — no FX mismatch
            df.loc[mask, "cash_conversion"] = ocf / profit * 100.0
        if ocf and fx and fx > 0:
            # ocf is CNY; market cap is HKD — convert via fx
            caps = df.loc[mask, "market_cap"]
            df.loc[mask, "ocf_yield"] = (
                ocf / fx / caps.where(caps > 0) * 100.0)


def build_master(cands_by_market: dict, snap_dir: Path,
                 hk_f10: pd.DataFrame | None,
                 fx: float | None) -> pd.DataFrame:
    """Assemble the master frame, apply final gates, score pillars."""
    hk_map = {}
    if hk_f10 is not None and not hk_f10.empty:
        hk_map = {str(r["code"]): dict(r) for _, r in hk_f10.iterrows()}

    frames = []
    for market, cands in cands_by_market.items():
        if cands is None or cands.empty:
            continue
        df = cands.copy()
        df["currency"] = config.MARKET_CURRENCIES[market]
        if market == "HK":
            _apply_hk_f10(df, hk_map, fx)
        feats = pd.DataFrame(
            [kline_features(snap_dir, market, c) for c in df["code"]],
            index=df.index)
        for col in KLINE_FEATURES:
            df[col] = feats[col] if col in feats.columns else None
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=MASTER_COLUMNS)
    master = pd.concat(frames, ignore_index=True)

    master = add_cashflow_factors(master, fx, load_annual_cashflows(snap_dir))

    # final gate: profitable growth where the data exists
    if "profit_yoy" in master.columns:
        master = master[master["profit_yoy"].isna()
                        | (master["profit_yoy"] > 0)]

    master = add_pillar_scores(master)
    score_cols = [f"{p}_score" for p in PILLARS]
    for col in score_cols:
        if col not in master.columns:
            master[col] = float("nan")
    master["data_completeness"] = (
        master[score_cols].notna().sum(axis=1) / len(PILLARS))
    return master.reindex(columns=MASTER_COLUMNS)


# ---------------------------------------------------------------------------
# Holdings watchlist (deep data for held symbols the funnel excludes)
# ---------------------------------------------------------------------------
def collect_watch_symbols(max_symbols: int | None = None) -> list:
    """Deduped [(market, code, name)] across every user's holdings.

    Held symbols deserve deep data even when the funnel excludes them:
    loss-makers fail the pe>0 gate (摩尔线程), ETFs sit outside the stock
    universe (科创50ETF), negative profit_yoy names fail the final gate
    (PDD), share classes used to miss the SEC ticker join (BRK_B).
    Capped at config.WATCHLIST_MAX so a bloated portfolio cannot stall
    the pipeline.
    """
    from .. import users

    out: dict = {}
    try:
        profiles = users.list_users()
    except Exception:  # noqa: BLE001 — watchlist must never break fetch
        return []
    for u in profiles:
        for h in u.holdings:
            out.setdefault((h.market, str(h.code)), h.name)
    items = [(m, c, n) for (m, c), n in out.items()]
    return items[:max_symbols or config.WATCHLIST_MAX]


def _watch_quote(market: str, code: str, quotes_row) -> dict:
    """Quote dict for a watch symbol: snapshot row first, else a live
    fetch (EM ulist -> Tencent realtime) for out-of-universe symbols."""
    if quotes_row is not None:
        rec = dict(quotes_row)
        rec["code"] = str(rec.get("code") or code)
        return rec
    return fetch_quote_any(market, code) or {}


def _has_price(row: dict) -> bool:
    p = row.get("price")
    try:
        return p is not None and not pd.isna(p) and float(p) > 0
    except (TypeError, ValueError):
        return False


def _watch_a_financials(codes: list, snap_dir: Path) -> pd.DataFrame:
    """A-share financials for watch codes: batch file + per-stock
    fallback for names missing from it (recent IPO late filers)."""
    fin = pd.DataFrame()
    p = snap_dir / "a_financials.csv"
    if p.exists():
        try:
            fin = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            fin = pd.DataFrame()
    if fin.empty or "code" not in fin.columns:
        return fin
    have = set(fin["code"].astype(str))
    extra = []
    for c in codes:
        if c in have:
            continue
        one = fetch_a_financials_one(c)
        if one is not None and not one.empty:
            extra.append(one.iloc[0])
    if extra:
        fin = pd.concat([fin, pd.DataFrame(extra)], ignore_index=True)
    return fin


def _watch_us_financials(codes: list, snap_dir: Path) -> pd.DataFrame:
    """US financials for watch codes: frames file + SEC companyconcept
    fallback for tickers the frames aggregation misses entirely, and
    for rows whose derivable columns are gaps (an older frames pull
    has no cost column, so PDD-style gross margins never derived)."""
    fin = pd.DataFrame()
    p = snap_dir / "us_financials.csv"
    if p.exists():
        try:
            fin = pd.read_csv(p, dtype={"ticker": str})
        except (OSError, pd.errors.ParserError, ValueError):
            fin = pd.DataFrame()
    cols = (list(fin.columns) if not fin.empty and "ticker" in fin.columns
            else ["ticker", "rev", "rev_prev", "rev_q", "rev_q_prev",
                  "profit", "profit_prev", "gross_profit", "cost",
                  "equity", "equity_prev", "liabilities", "assets",
                  "ocf", "rev_yoy", "profit_yoy", "rev_q_yoy",
                  "net_margin", "gross_margin", "ps_revenue", "roe",
                  "debt_ratio", "cash_conversion"])
    extra = []
    for c in codes:
        hit = (fin.index[fin["ticker"].astype(str) == c]
               if not fin.empty and "ticker" in fin.columns else [])
        if len(hit):
            # derivable-column gap in the batch row -> single-stock
            # fallback fills ONLY the missing fields (never overwrites)
            row = fin.loc[hit[0]]
            gap = any(col in row.index and pd.isna(row.get(col))
                      for col in ("gross_margin", "rev_yoy", "roe"))
            if not gap:
                continue
            rec = fetch_us_financials_one(c)
            if rec:
                for k, v in rec.items():
                    if k == "ticker":
                        continue
                    if k not in fin.columns:
                        fin[k] = None
                    if pd.isna(fin.at[hit[0], k]):
                        fin.at[hit[0], k] = v
            continue
        rec = fetch_us_financials_one(c)
        if rec:
            row = {k: None for k in cols}
            row.update(rec)
            row["ticker"] = c
            extra.append(row)
    if extra:
        fin = pd.concat([fin, pd.DataFrame(extra)], ignore_index=True)
    return fin


def build_watchlist(snap_dir: Path, reuse_dirs: list,
                    master: pd.DataFrame, hk_f10: pd.DataFrame | None,
                    fx: float | None, manifest: dict,
                    quiet: bool = False) -> pd.DataFrame:
    """Deep data for held symbols missing from master.csv -> watchlist.csv.

    For every user-held symbol the funnel excluded: a quote (snapshot
    row, else EM ulist, else Tencent), a cached kline (same reuse chain
    as candidates), fundamentals (batch file, else per-stock fallback)
    and kline-derived factors. Pillar scores are percentiles against
    the master pool + watch peers. master.csv semantics stay untouched.
    """
    log = (lambda *a: None) if quiet else print
    empty = pd.DataFrame(columns=MASTER_COLUMNS)
    if master is None:
        master = pd.DataFrame()
    master_keys = set()
    if master is not None and not master.empty:
        master_keys = set(zip(master["market"].astype(str),
                              master["code"].astype(str)))
    watch = [s for s in collect_watch_symbols()
             if (s[0], s[1]) not in master_keys]
    if not watch:
        empty.to_csv(snap_dir / "watchlist.csv", index=False)
        manifest["datasets"]["watchlist"] = 0
        return empty

    quotes_lookup: dict = {}
    for market in config.MARKETS:
        p = snap_dir / f"{market.lower()}_quotes.csv"
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            continue
        if "code" not in df.columns:
            continue
        for _, r in df.iterrows():
            quotes_lookup[(market, str(r["code"]))] = r

    hk_map = {}
    if hk_f10 is not None and not hk_f10.empty:
        hk_map = {str(r["code"]): dict(r) for _, r in hk_f10.iterrows()}

    by_market: dict = {}
    for market, code, name in watch:
        row = _watch_quote(market, code, quotes_lookup.get((market, code)))
        if not _has_price(row):
            # out-of-universe symbol neither EM nor Tencent serves
            manifest["failures"].append(
                f"watchlist {market}/{code}: no quote from any source")
            continue
        row.setdefault("name", name)
        row.setdefault("market", market)
        row["code"] = str(code)
        by_market.setdefault(market, []).append(row)

    frames = []
    wstats = {"fetched": 0, "reused": 0, "failed": 0}
    a_cf = None
    p = snap_dir / "a_cashflow.csv"
    if p.exists():
        try:
            a_cf = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            a_cf = None
    for market, rows in by_market.items():
        df = pd.DataFrame(rows)
        # snapshot quote rows already carry a market column
        if "market" not in df.columns:
            df.insert(0, "market", market)
        else:
            df["market"] = market
        if market == "HK":
            df["code"] = df["code"].astype(str).str.zfill(5)
        # klines for watch symbols (same cache/reuse chain as candidates)
        fetch_klines(df, market, snap_dir, reuse_dirs, wstats)
        # fundamentals per market, reusing the funnel merge logic
        if market == "A":
            fin = _watch_a_financials(list(df["code"].astype(str)),
                                      snap_dir)
            df = merge_a_financials(df, fin, a_cf)
        elif market == "US":
            fin = _watch_us_financials(list(df["code"].astype(str)),
                                       snap_dir)
            df = merge_us_financials(df, fin)
        elif market == "HK":
            sub_map = {c: hk_map[c] for c in df["code"].astype(str)
                       if c in hk_map}
            _apply_hk_f10(df, sub_map, fx)
        df["currency"] = config.MARKET_CURRENCIES[market]
        feats = pd.DataFrame(
            [kline_features(snap_dir, market, c) for c in df["code"]],
            index=df.index)
        for col in KLINE_FEATURES:
            df[col] = feats[col] if col in feats.columns else None
        frames.append(df)

    if not frames:
        empty.to_csv(snap_dir / "watchlist.csv", index=False)
        manifest["datasets"]["watchlist"] = 0
        return empty

    watch_df = pd.concat(frames, ignore_index=True)

    watch_df = add_cashflow_factors(watch_df, fx,
                                    load_annual_cashflows(snap_dir))

    # score against master peers + watch peers (percentiles by market)
    score_frame = pd.concat(
        [master, watch_df], ignore_index=True, sort=False)
    score_frame = add_pillar_scores(score_frame)
    scored = score_frame.iloc[len(score_frame) - len(watch_df):]
    score_cols = [f"{p}_score" for p in PILLARS]
    for col in score_cols:
        if col not in scored.columns:
            scored[col] = float("nan")
    scored["data_completeness"] = (
        scored[score_cols].notna().sum(axis=1) / len(PILLARS))
    out = scored.reindex(columns=MASTER_COLUMNS)
    out.to_csv(snap_dir / "watchlist.csv", index=False)
    manifest["datasets"]["watchlist"] = len(out)
    manifest["datasets"]["watchlist_klines"] = dict(wstats)
    log(f"    [watchlist] {len(out)} held symbols "
        f"(klines {wstats})")
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _prior_snapshot(data_dir: Path, exclude: Path) -> Path | None:
    snaps = data_dir / "snapshots"
    if not snaps.is_dir():
        return None
    dirs = sorted((d for d in snaps.iterdir()
                   if d.is_dir() and d.resolve() != exclude.resolve()),
                  key=lambda d: d.name, reverse=True)
    return dirs[0] if dirs else None


def _snapshot_age_days(snap_dir: Path) -> int:
    try:
        d = datetime.strptime(snap_dir.name, "%Y%m%d").date()
        return (date.today() - d).days
    except ValueError:
        return 10 ** 6  # unparseable -> treat as ancient


def run_fetch(markets=None, data_dir=None, refresh: bool = False,
              quiet: bool = False) -> Path:
    """Run the full pipeline; returns the snapshot directory path."""
    t0 = time.time()
    markets = [m.upper() for m in (markets or config.MARKETS)]
    for m in markets:
        if m not in config.MARKETS:
            raise ValueError(f"unknown market {m!r}")
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    snap_dir = data_dir / "snapshots" / datetime.now().strftime("%Y%m%d")
    snap_dir.mkdir(parents=True, exist_ok=True)

    # reuse chain for deep data: today's dir first (same-day rerun or
    # crashed-run resume), then the latest prior snapshot
    kline_reuse: list[Path] = []
    f10_reuse: list[Path] = []
    if not refresh:
        if any(snap_dir.iterdir()):
            kline_reuse.append(snap_dir)
        prior = _prior_snapshot(data_dir, snap_dir)
        if prior is not None and prior not in kline_reuse:
            kline_reuse.append(prior)
        f10_reuse = [d for d in kline_reuse
                     if _snapshot_age_days(d) <= config.DEEP_FRESH_DAYS]

    manifest = {"created_at": datetime.now().isoformat(timespec="seconds"),
                "markets": markets, "refresh": refresh, "datasets": {},
                "failures": []}
    log = (lambda *a: None) if quiet else print
    log(f"== value-genie fetch -> {snap_dir} ==")

    fx = None
    if "HK" in markets:
        fx = fetch_fx_hkdcny()
        manifest["fx_hkdcny"] = fx
        log(f"    [FX] HKD/CNY = {fx}")
    if "US" in markets:
        from .fundamentals import fetch_fx_usdcny
        fx_us = fetch_fx_usdcny()
        manifest["fx_usdcny"] = fx_us
        log(f"    [FX] USD/CNY = {fx_us}")

    def _load_or_fetch(path: Path, fetcher, dtype_col: str,
                      label: str) -> pd.DataFrame | None:
        """Resume helper: reuse today's saved dataset, else fetch it."""
        if not refresh and path.exists():
            try:
                df = pd.read_csv(path, dtype={dtype_col: str})
                if not df.empty:
                    log(f"    [{label}] reused {len(df)} rows from today")
                    return df
            except (OSError, pd.errors.ParserError, ValueError):
                pass
        df = fetcher()
        if df is not None and not df.empty:
            df.to_csv(path, index=False)
        return df

    a_fin = None
    a_cf = None
    if "A" in markets:
        a_fin = _load_or_fetch(snap_dir / "a_financials.csv",
                               lambda: fetch_a_financials(quiet=quiet),
                               "code", "A fin")
        a_cf = _load_or_fetch(snap_dir / "a_cashflow.csv",
                              lambda: fetch_a_cashflow(quiet=quiet),
                              "code", "A cashflow")
        a_cf_ann = _load_or_fetch(
            snap_dir / "a_cashflow_annual.csv",
            lambda: fetch_a_cashflow_annual(quiet=quiet),
            "code", "A annual cf")
        if a_cf_ann is not None and not a_cf_ann.empty \
                and "report_date" in a_cf_ann.columns:
            years = sorted({str(d)[:4] for d in a_cf_ann["report_date"]})
            _load_or_fetch(
                snap_dir / "a_dividends.csv",
                lambda: fetch_a_dividends(years, quiet=quiet),
                "code", "A dividends")
    us_fin = None
    if "US" in markets:
        us_fin = _load_or_fetch(snap_dir / "us_financials.csv",
                                lambda: fetch_us_financials(quiet=quiet),
                                "ticker", "US fin")

    cands_by_market = {}
    for market in markets:
        if market == "US" and (us_fin is None or us_fin.empty):
            # without SEC frames the operating-company gate cannot bite
            # and leveraged ETPs with phantom PEs would flood the funnel
            manifest["failures"].append("US: no SEC financials fetched")
            log("    [US] SKIP: no SEC financials, market dropped")
            continue
        qpath = snap_dir / f"{market.lower()}_quotes.csv"
        quotes, reused_quotes = None, False
        if not refresh and qpath.exists():
            try:
                quotes = pd.read_csv(qpath, dtype={"code": str})
            except (OSError, pd.errors.ParserError, ValueError):
                quotes = pd.DataFrame()
            if not quotes.empty:
                reused_quotes = True
                log(f"    [{market}] quotes: {len(quotes)} reused from today")
            else:
                quotes = None
        if quotes is None:
            quotes = fetch_market_quotes(market)
        if quotes.empty or "code" not in quotes.columns:
            manifest["failures"].append(f"{market}: no quotes fetched")
            continue
        if not reused_quotes:
            quotes.to_csv(qpath, index=False)
        # join batch financials before gating so the growth gate bites
        if market == "A":
            df = merge_a_financials(quotes, a_fin, a_cf)
        elif market == "US":
            df = merge_us_financials(quotes, us_fin)
        else:
            df = quotes
        df = apply_gates(df, market)
        gated = len(df)
        df = stage1_blend(df, market)
        df = select_candidates(df, market)
        cands_by_market[market] = df
        manifest["datasets"][market] = {
            "quotes": len(quotes), "gated": gated, "candidates": len(df)}
        log(f"    [{market}] quotes={len(quotes)} gated={gated} "
            f"candidates={len(df)}")

    kstats = {}
    for market, cands in cands_by_market.items():
        kstats[market] = {"fetched": 0, "reused": 0, "failed": 0}
        fetch_klines(cands, market, snap_dir, kline_reuse, kstats[market],
                     force=refresh)
        manifest["datasets"][f"{market}_klines"] = dict(kstats[market])
        if not quiet:
            log(f"    [{market}] klines {kstats[market]}")

    # held-but-excluded symbols need HK F10 too (watchlist deep pass)
    watch_syms = collect_watch_symbols()

    hk_f10 = None
    if "HK" in cands_by_market:
        hk_stats = {"fetched": 0, "reused": 0, "failed": 0}
        hk_codes = list(cands_by_market["HK"]["code"].astype(str))
        hk_codes += [c for m, c, _ in watch_syms
                     if m == "HK" and c not in set(hk_codes)]
        hk_f10 = fetch_hk_deep(hk_codes, snap_dir, f10_reuse, hk_stats)
        manifest["datasets"]["hk_f10"] = dict(hk_stats)
        log(f"    [HK] f10 {hk_stats}")
        hk_cf_stats = {"fetched": 0, "reused": 0, "failed": 0}
        fetch_hk_cashflow_deep(hk_codes, snap_dir, f10_reuse, hk_cf_stats)
        manifest["datasets"]["hk_cashflow"] = dict(hk_cf_stats)
        log(f"    [HK] cashflow {hk_cf_stats}")

    master = build_master(cands_by_market, snap_dir, hk_f10, fx)
    master.to_csv(snap_dir / "master.csv", index=False)
    manifest["datasets"]["master"] = len(master)

    # deep data for holdings the funnel excluded (watchlist.csv)
    build_watchlist(snap_dir, kline_reuse, master, hk_f10, fx, manifest,
                    quiet=quiet)

    manifest["elapsed_sec"] = round(time.time() - t0, 1)
    (snap_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (data_dir / "latest.json").write_text(
        json.dumps({"snapshot": snap_dir.name}), encoding="utf-8")
    log(f"    master: {len(master)} stocks "
        f"({manifest['elapsed_sec']}s)")
    return snap_dir
