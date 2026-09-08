"""Event radar: full-market A-share event tables -> per-stock risk
columns merged into master.csv / watchlist.csv (design 2026-09-08 §6).

Batch channel of the intel subsystem, runs at the tail of run_fetch.
Semantics: no event = 0.0 (positive confirmation); only a failed
source yields NaN so gates fail-closed on missing data only. P1 covers
A-shares; HK/US rows keep NaN until P3.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from . import model
from .announcements import (fetch_a_buybacks, fetch_a_holder_changes,
                            fetch_a_placements, fetch_a_unlocks)
from .earnings import (fetch_a_appointments, fetch_a_balance,
                       fetch_a_forecasts)

RADAR_COLUMNS = [
    "unlock_pct_30d", "unlock_pct_90d", "holder_cut_flag", "dilution_flag",
    "buyback_active", "report_due_days", "forecast_flag", "eq_flags",
    "intel_red",
]

DETAIL_FILE = "event_radar.csv"


# ---------------------------------------------------------------------------
# Merge helper (pipeline-facing)
# ---------------------------------------------------------------------------
def merge_radar(df: pd.DataFrame, radar: pd.DataFrame) -> pd.DataFrame:
    """Left-join radar columns onto a master/watchlist frame.

    The NaN radar columns that build_master/build_watchlist reindex
    added are dropped first, so the merge never creates _x/_y
    duplicates; the final column order matches MASTER_COLUMNS (radar
    columns are its tail).
    """
    drop = [c for c in radar.columns
            if c in df.columns and c not in ("market", "code")]
    out = df.drop(columns=drop)
    return out.merge(radar, on=["market", "code"], how="left")


# ---------------------------------------------------------------------------
# Per-table aggregations (None table -> NaN column, fail-closed)
# ---------------------------------------------------------------------------
def _agg_unlock(unlocks, asof: date, days: int, codes: pd.Index):
    """Summed unlock % of total shares over (asof, asof+days]."""
    if unlocks is None:
        return None
    if unlocks.empty or "free_date" not in unlocks.columns:
        return pd.Series(0.0, index=codes)   # no events -> 0
    end = (asof + timedelta(days=days)).isoformat()
    w = unlocks[(unlocks["free_date"] > asof.isoformat())
                & (unlocks["free_date"] <= end)]
    s = w.groupby("code")["unlock_pct"].sum()
    return s.reindex(codes).fillna(0.0)


def _agg_flag(table, mask_fn, codes):
    """0/1 per code: 1 when any table row matches mask_fn."""
    if table is None:
        return None
    if table.empty or "code" not in table.columns:
        return pd.Series(0.0, index=codes)   # no events -> 0
    hit = table[mask_fn(table)]
    s = pd.Series(1.0, index=pd.Index(sorted(set(hit["code"])),
                                      name="code"))
    return s.reindex(codes).fillna(0.0)


def _holder_cut_mask(asof: date):
    """减持 + 窗口未截止（end_date 缺失视为进行中，宁可误报）。"""
    def mask(df):
        end = df["end_date"]
        ongoing = end.isna() | (end >= asof.isoformat())
        return (df["direction"] == "减持") & ongoing
    return mask


def _any_mask(df):
    return pd.Series(True, index=df.index)


def _agg_report_due(appoints, asof: date, codes):
    """Days to the next unpublished appointment; 999 = none in window."""
    if appoints is None:
        return None
    if appoints.empty or "appoint_date" not in appoints.columns:
        return pd.Series(999.0, index=codes)
    fut = appoints[(appoints["appoint_date"] > asof.isoformat())
                   & (appoints["is_published"].astype(str) == "0")]
    if fut.empty:
        return pd.Series(999.0, index=codes)
    due = (pd.to_datetime(fut["appoint_date"]) - pd.Timestamp(asof)).dt.days
    s = fut.assign(due=due).groupby("code")["due"].min()
    return s.reindex(codes).fillna(999.0)


def _agg_forecast(forecasts, codes):
    """Direction of the latest forecast notice per code (-1/0/1)."""
    if forecasts is None:
        return None
    if forecasts.empty:
        return pd.Series(0.0, index=codes)
    latest = (forecasts.sort_values("notice_date")
              .groupby("code").tail(1))
    s = latest.set_index("code")["predict_type"].map(
        lambda t: model.FORECAST_DIRECTION.get(str(t), 0))
    return s.reindex(codes).fillna(0.0)


# ---------------------------------------------------------------------------
# Earnings-quality inputs (snapshot files + balance batch table)
# ---------------------------------------------------------------------------
def _read_csv(path: Path):
    try:
        df = pd.read_csv(path, dtype={"code": str})
        return df if not df.empty else None
    except (OSError, pd.errors.ParserError, ValueError):
        return None


def _report_date_of(snap_dir: Path):
    """Modal report_date of a_financials.csv (= the chosen period)."""
    fin = _read_csv(snap_dir / "a_financials.csv")
    if fin is None or "report_date" not in fin.columns:
        return None
    try:
        return str(fin["report_date"].mode().iloc[0])
    except IndexError:
        return None


def _eq_records(snap_dir: Path, balance):
    """{code: earnings_quality input rec} from snapshot financials.

    None when the balance batch failed — eq_flags then goes NaN for
    all stocks (fail-closed, design §6.2). Stocks missing rows in any
    input simply trigger fewer signals.
    """
    if balance is None:
        return None
    fin = _read_csv(snap_dir / "a_financials.csv")
    if fin is None:
        return None
    m = fin.drop_duplicates(subset="code")
    cf = _read_csv(snap_dir / "a_cashflow.csv")
    if cf is not None and "ocf" in cf.columns:
        m = m.merge(cf[["code", "ocf"]].drop_duplicates(subset="code"),
                    on="code", how="left")
    if (not balance.empty
            and all(c in balance.columns
                    for c in ("code", "rece_yoy", "inv_yoy"))):
        m = m.merge(balance[["code", "rece_yoy", "inv_yoy"]]
                    .drop_duplicates(subset="code"), on="code", how="left")
    cols = [c for c in ("rev_yoy", "profit", "ocf", "deduct_eps",
                        "basic_eps", "rece_yoy", "inv_yoy")
            if c in m.columns]
    return m.set_index("code")[cols].to_dict("index")


# ---------------------------------------------------------------------------
# Detail (IntelItem) builders — universe-scoped
# ---------------------------------------------------------------------------
def _iso(v) -> date:
    return date.fromisoformat(str(v)[:10])


def _num(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def _unlock_items(unlocks, codes) -> list:
    if unlocks is None or unlocks.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in unlocks.iterrows():
        if str(r["code"]) not in uni:
            continue
        pct = r["unlock_pct"]
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind="unlock",
            event_date=_iso(r["free_date"]),
            title=(f"限售解禁 {pct:.1f}% 总股本"
                   if pd.notna(pct) else "限售解禁"),
            source="eastmoney", impact=model.IMPACT_BY_KIND["unlock"],
            payload={"unlock_pct": _num(pct),
                     "lift_cap_wan": _num(r.get("lift_cap_wan"))}))
    return items


def _holder_items(holders, codes) -> list:
    if holders is None or holders.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in holders.iterrows():
        if str(r["code"]) not in uni:
            continue
        kind = "holder_cut" if r["direction"] == "减持" else "holder_add"
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind=kind,
            event_date=_iso(r["notice_date"]),
            title=(f"股东{r['direction']} "
                   f"{r.get('holder_name') or ''}").strip(),
            source="eastmoney", impact=model.IMPACT_BY_KIND[kind],
            payload={"direction": str(r["direction"]),
                     "change_num_wan": _num(r.get("change_num_wan")),
                     "end_date": (None if pd.isna(r.get("end_date"))
                                  else str(r["end_date"]))}))
    return items


def _buyback_items(buybacks, codes) -> list:
    if buybacks is None or buybacks.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in buybacks.iterrows():
        if str(r["code"]) not in uni:
            continue
        amt = r.get("amount_yuan")
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind="buyback",
            event_date=_iso(r["announce_date"]),
            title=("回购" + (f" {amt / 1e8:.2f} 亿元"
                           if pd.notna(amt) else "")),
            source="eastmoney", impact=model.IMPACT_BY_KIND["buyback"],
            payload={"amount_yuan": _num(amt),
                     "shares": _num(r.get("shares"))}))
    return items


def _placement_items(placements, codes) -> list:
    if placements is None or placements.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in placements.iterrows():
        if str(r["code"]) not in uni:
            continue
        dil = r.get("dilution_pct")
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="announcements", kind="placement",
            event_date=_iso(r["issue_date"]),
            title=("定增发行" + (f" 稀释 {dil:.1f}%"
                                if pd.notna(dil) else "")),
            source="eastmoney", impact=model.IMPACT_BY_KIND["placement"],
            payload={"dilution_pct": _num(dil),
                     "net_raise": _num(r.get("net_raise")),
                     "seo_type": str(r.get("seo_type") or "")}))
    return items


def _forecast_items(forecasts, codes) -> list:
    if forecasts is None or forecasts.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in forecasts.iterrows():
        if str(r["code"]) not in uni:
            continue
        t = str(r["predict_type"])
        direction = model.FORECAST_DIRECTION.get(t, 0)
        kind = {1: "forecast_up", -1: "forecast_down"}.get(
            direction, "forecast_flat")
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="earnings", kind=kind,
            event_date=_iso(r["notice_date"]),
            title=f"业绩预告: {t}",
            source="eastmoney", impact=model.IMPACT_BY_KIND[kind],
            payload={"predict_type": t,
                     "change_pct": _num(r.get("change_pct"))}))
    return items


def _appointment_items(appoints, codes) -> list:
    if appoints is None or appoints.empty:
        return []
    uni = set(codes)
    items = []
    for _, r in appoints.iterrows():
        if str(r["code"]) not in uni:
            continue
        items.append(model.IntelItem(
            market="A", code=str(r["code"]),
            name=str(r.get("name") or ""),
            subsystem="earnings", kind="report_date",
            event_date=_iso(r["appoint_date"]),
            title=f"财报披露预约: {r.get('report_type') or ''}",
            source="eastmoney",
            impact=model.IMPACT_BY_KIND["report_date"],
            payload={"is_published": str(r.get("is_published") or ""),
                     "report_type": str(r.get("report_type") or "")}))
    return items


def _eq_items(eq_recs, fin_rd, codes) -> list:
    if not eq_recs:
        return []
    items = []
    for code in codes:
        rec = eq_recs.get(str(code), {})
        for flag in model.earnings_quality(rec):
            items.append(model.IntelItem(
                market="A", code=str(code), name="",
                subsystem="earnings", kind="eq_flag",
                event_date=(_iso(fin_rd) if fin_rd else date.today()),
                title=f"财报粉饰信号: {flag}",
                source="snapshot",
                impact=model.IMPACT_BY_KIND["eq_flag"],
                payload={"signal": flag}))
    return items


def _write_detail(snap: Path, items) -> None:
    df = pd.DataFrame([model.item_to_row(i) for i in items],
                      columns=model.DETAIL_COLUMNS)
    df.to_csv(snap / DETAIL_FILE, index=False)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _load_or_fetch(path: Path, fetcher, label: str, refresh: bool, log):
    """Snapshot resume convention: reuse today's saved table unless
    refresh (design §6.1). A raising fetcher degrades to None."""
    if not refresh and path.exists():
        try:
            df = pd.read_csv(path, dtype={"code": str})
            if not df.empty:
                log(f"    [{label}] reused {len(df)} rows from today")
                return df
        except (OSError, pd.errors.ParserError, ValueError):
            pass
    try:
        df = fetcher()
    except Exception as e:  # noqa: BLE001 — one bad report must not
        print(f"    [{label}] fetch error: {e}",   # kill the whole fetch
              file=sys.stderr)
        df = None
    if df is not None and not df.empty:
        df.to_csv(path, index=False)
    return df


def build_event_radar(snap_dir, master, watch, manifest=None,
                      refresh: bool = False, quiet: bool = False,
                      asof: date | None = None):
    """A-share event radar for the master + watchlist universe.

    Returns a frame [market, code, RADAR_COLUMNS] for the pipeline to
    merge into master.csv / watchlist.csv, or None when there is
    nothing to merge (no A universe / radar failed outright — columns
    stay NaN, fail-closed). Writes event_radar.csv (IntelItem detail).
    Single-table source failures degrade only their columns to NaN and
    land in manifest.failures.
    """
    log = (lambda *a: None) if quiet else print
    snap = Path(snap_dir)
    asof = asof or date.today()

    frames = [df for df in (master, watch)
              if df is not None and not df.empty]
    if not frames:
        _write_detail(snap, [])
        return None
    uni = pd.concat(frames, ignore_index=True)[["market", "code"]]
    uni = uni[uni["market"] == "A"].drop_duplicates()
    codes = pd.Index(uni["code"].astype(str), name="code")
    if codes.empty:
        _write_detail(snap, [])          # P1: 本次运行无 A 股覆盖
        return None

    lookback = (asof - timedelta(
        days=config.INTEL_LOOKBACK_DAYS)).isoformat()
    forward = (asof + timedelta(
        days=config.INTEL_FORECAST_DAYS)).isoformat()

    def _fail(label):
        if manifest is not None:
            manifest.setdefault("failures", []).append(
                f"intel {label}: source failed")
        log(f"    [{label}] source failed -> NaN (fail-closed)")

    def _lf(name, fetcher, label):
        df = _load_or_fetch(snap / name, fetcher, label, refresh, log)
        if df is None:
            _fail(label)
        return df

    fin_rd = _report_date_of(snap)
    unlocks = _lf("a_unlocks.csv",
                  lambda: fetch_a_unlocks(asof.isoformat(), forward),
                  "A unlocks")
    holders = _lf("a_holder_changes.csv",
                  lambda: fetch_a_holder_changes(lookback), "A holders")
    buybacks = _lf("a_buybacks.csv",
                   lambda: fetch_a_buybacks(lookback), "A buybacks")
    placements = _lf("a_placements.csv",
                     lambda: fetch_a_placements(lookback), "A placements")
    forecasts = _lf("a_forecasts.csv",
                    lambda: fetch_a_forecasts(lookback), "A forecasts")
    appoints = _lf("a_appointments.csv",
                   lambda: fetch_a_appointments(asof.isoformat(),
                                                forward),
                   "A appointments")
    balance = (None if not fin_rd else
               _lf("a_balance.csv", lambda: fetch_a_balance(fin_rd),
                   "A balance"))
    eq_recs = None if balance is None else _eq_records(snap, balance)

    try:
        cols = {
            "unlock_pct_30d": _agg_unlock(unlocks, asof, 30, codes),
            "unlock_pct_90d": _agg_unlock(unlocks, asof, 90, codes),
            "holder_cut_flag": _agg_flag(holders,
                                         _holder_cut_mask(asof), codes),
            "dilution_flag": _agg_flag(placements, _any_mask, codes),
            "buyback_active": _agg_flag(buybacks, _any_mask, codes),
            "report_due_days": _agg_report_due(appoints, asof, codes),
            "forecast_flag": _agg_forecast(forecasts, codes),
            "eq_flags": (None if eq_recs is None else
                         pd.Series({c: len(model.earnings_quality(
                             eq_recs.get(c, {})))
                             for c in codes}, index=codes)),
        }
        out = pd.DataFrame({"market": "A", "code": list(codes)})
        for c in cols:                     # intel_red is derived below
            out[c] = (cols[c].to_numpy() if cols[c] is not None
                      else float("nan"))

        have = out[["unlock_pct_30d", "holder_cut_flag", "dilution_flag",
                   "eq_flags"]].notna().all(axis=1)
        red = ((out["unlock_pct_30d"] >= config.UNLOCK_RED_PCT)
               | (out["holder_cut_flag"] == 1)
               | (out["dilution_flag"] == 1)
               | (out["eq_flags"] >= config.EQ_FLAG_RED))
        out["intel_red"] = red.astype(float).where(have)

        items = (_unlock_items(unlocks, codes)
                 + _holder_items(holders, codes)
                 + _buyback_items(buybacks, codes)
                 + _placement_items(placements, codes)
                 + _forecast_items(forecasts, codes)
                 + _appointment_items(appoints, codes)
                 + _eq_items(eq_recs, fin_rd, codes))
        _write_detail(snap, items)
        if manifest is not None:
            manifest["datasets"]["event_radar"] = len(items)
            manifest["datasets"]["radar_stocks"] = len(out)
        log(f"    [intel] radar: {len(out)} stocks, {len(items)} events")
        return out
    except Exception as e:  # noqa: BLE001 — radar must never break fetch
        print(f"[WARN] intel radar assembly failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        if manifest is not None:
            manifest["failures"].append(
                f"intel radar: {type(e).__name__}: {str(e)[:120]}")
        return None
