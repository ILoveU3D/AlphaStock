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
from .fundamentals import (fetch_a_cashflow, fetch_a_financials,
                           fetch_fx_hkdcny,
                           fetch_hk_f10, fetch_us_financials,
                           frames_year_context)
from .kline import (fetch_kline_any, kline_cache_path, kline_is_fresh,
                    load_kline, save_kline)
from .quotes import (exclude_non_operating_names, exclude_risk_names,
                     fetch_market_quotes)

MASTER_COLUMNS = [
    "market", "code", "name", "industry", "currency", "price", "market_cap",
    "pe_ttm", "pb", "ps", "dividend_yield", "rev_yoy", "profit_yoy",
    "rev_q_yoy", "roe", "gross_margin", "net_margin", "debt_ratio",
    "ocf_yield", "cash_conversion",
    "pos_52w", "drawdown_52w", "ret_250d", "ret_60d", "volatility",
    "report_date", "value_score", "growth_score", "quality_score",
    "safety_score", "momentum_score", "cashflow_score", "data_completeness",
]

KLINE_FEATURES = ("pos_52w", "drawdown_52w", "ret_250d", "ret_60d",
                  "volatility")


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
    for extra in ("cash_conversion", "ocf"):
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


def kline_features(snap_dir: Path, market: str, code: str) -> dict:
    return kline_metrics(load_kline(kline_cache_path(snap_dir, market,
                                                     str(code))))


# ---------------------------------------------------------------------------
# Master assembly
# ---------------------------------------------------------------------------
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
        feats = pd.DataFrame(
            [kline_features(snap_dir, market, c) for c in df["code"]],
            index=df.index)
        for col in KLINE_FEATURES:
            df[col] = feats[col] if col in feats.columns else None
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=MASTER_COLUMNS)
    master = pd.concat(frames, ignore_index=True)

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

    hk_f10 = None
    if "HK" in cands_by_market:
        hk_stats = {"fetched": 0, "reused": 0, "failed": 0}
        hk_f10 = fetch_hk_deep(cands_by_market["HK"]["code"].astype(str),
                               snap_dir, f10_reuse, hk_stats)
        manifest["datasets"]["hk_f10"] = dict(hk_stats)
        log(f"    [HK] f10 {hk_stats}")

    master = build_master(cands_by_market, snap_dir, hk_f10, fx)
    master.to_csv(snap_dir / "master.csv", index=False)
    manifest["datasets"]["master"] = len(master)

    manifest["elapsed_sec"] = round(time.time() - t0, 1)
    (snap_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (data_dir / "latest.json").write_text(
        json.dumps({"snapshot": snap_dir.name}), encoding="utf-8")
    log(f"    master: {len(master)} stocks "
        f"({manifest['elapsed_sec']}s)")
    return snap_dir
