"""Per-stock intelligence report (情报通道, design §7).

Section assembly for ``intel X``: radar row + event details from the
snapshot's full-market batch tables (zero network for snapshot stocks),
live per-stock notices / ratings / news, earnings-quality detail.
Fail-closed per section: a failed section becomes {"missing": reason},
never fabricated data. P2 covers A-shares; HK/US degrade with an
explicit P3 note.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from .announcements import fetch_stock_notices
from .model import earnings_quality
from .news import fetch_stock_news
from .radar import (_appointment_items, _buyback_items, _eq_records,
                    _forecast_items, _holder_items, _placement_items,
                    _read_csv, _unlock_items, RADAR_COLUMNS)
from .ratings import fetch_stock_ratings


def _radar_row(snap: Path | None, market: str, code: str) -> dict | None:
    """雷达行 from master/watchlist (照 analyze._snapshot_factors 模式)。"""
    if snap is None:
        return None
    for fname in ("master.csv", "watchlist.csv"):
        p = Path(snap) / fname
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            continue
        if "market" not in df.columns or "code" not in df.columns:
            continue
        hit = df[(df["market"] == market)
                 & (df["code"].astype(str) == str(code))]
        if not hit.empty:
            r = hit.iloc[0]
            return {c: (None if pd.isna(r.get(c)) else r.get(c))
                    for c in RADAR_COLUMNS}
    return None


def _table(name: str, snap: Path, code: str, fetcher, label: str):
    """快照批表 filter code；表缺失 → 实时单股兜底（fetcher(code=...)）。

    Returns normalized DataFrame, None on both-paths failure. The saved
    batch tables are full-market, so any A-share (in or out of the
    funnel universe) is covered without network.
    """
    df = _read_csv(Path(snap) / name)
    if df is not None:
        hit = df[df["code"].astype(str) == str(code)]
        return hit if not hit.empty else df.iloc[0:0]
    if fetcher is None:
        return None
    try:
        return fetcher()          # caller closes over code/windows
    except Exception:             # noqa: BLE001 — fail-closed per section
        return None


def _stock_events(snap: Path, code: str, asof: date) -> list:
    """事件明细 IntelItems：快照表（或单股兜底）→ radar 的 *_items。"""
    from .announcements import (fetch_a_buybacks, fetch_a_holder_changes,
                                fetch_a_placements, fetch_a_unlocks)
    from .earnings import fetch_a_appointments, fetch_a_forecasts
    lookback = (asof - timedelta(
        days=config.INTEL_LOOKBACK_DAYS)).isoformat()
    forward = (asof + timedelta(
        days=config.INTEL_FORECAST_DAYS)).isoformat()
    codes = pd.Index([code], name="code")

    unlocks = _table("a_unlocks.csv", snap, code,
                     lambda: fetch_a_unlocks(asof.isoformat(), forward,
                                             code=code), "unlocks")
    holders = _table("a_holder_changes.csv", snap, code,
                     lambda: fetch_a_holder_changes(lookback, code=code),
                     "holders")
    buybacks = _table("a_buybacks.csv", snap, code,
                      lambda: fetch_a_buybacks(lookback, code=code),
                      "buybacks")
    placements = _table("a_placements.csv", snap, code,
                        lambda: fetch_a_placements(lookback, code=code),
                        "placements")
    forecasts = _table("a_forecasts.csv", snap, code,
                       lambda: fetch_a_forecasts(lookback, code=code),
                       "forecasts")
    appoints = _table("a_appointments.csv", snap, code,
                      lambda: fetch_a_appointments(asof.isoformat(),
                                                   forward, code=code),
                      "appoints")
    items = []
    for fn, tbl in ((_unlock_items, unlocks),
                    (_holder_items, holders),
                    (_buyback_items, buybacks),
                    (_placement_items, placements),
                    (_forecast_items, forecasts),
                    (_appointment_items, appoints)):
        if tbl is None:
            continue
        items += fn(tbl, codes)
    return items


def _eq_detail(snap: Path, code: str) -> list[str] | None:
    """粉饰信号明细（中文描述列表）；输入表缺失返回 None。"""
    fin = _read_csv(Path(snap) / "a_financials.csv")
    if fin is None:
        return None
    balance = _read_csv(Path(snap) / "a_balance.csv")
    eq_recs = _eq_records(Path(snap), balance)
    if eq_recs is None:
        return None
    rec = eq_recs.get(str(code))
    if rec is None:
        return []
    descs = {
        "eq_receivables": "应收增速远超营收（回款质量恶化）",
        "eq_inventory": "存货增速远超营收（渠道压货风险）",
        "eq_ocf_gap": "经营现金流/净利润过低（利润含金量不足）",
        "eq_nonrecurring": "扣非利润占比过低（非经常性损益撑业绩）",
    }
    return [descs.get(s, s) for s in earnings_quality(rec)]


def build_intel_report(match, snapshot_dir=None,
                       asof: date | None = None) -> dict:
    """单股舆情情报 result dict（五个板块 + 雷达行，fail-closed）。"""
    snap = Path(snapshot_dir) if snapshot_dir else None
    asof = asof or date.today()
    result = {"match": match, "snapshot": snap.name if snap else None,
              "asof": asof.isoformat()}

    if match.market != "A":
        result.update({"radar": {},
                       "events": {"missing": "P3: HK/US 未覆盖"},
                       "eq": {"missing": "P3: HK/US 未覆盖"},
                       "notices": {"missing": "P3: HK/US 未覆盖"},
                       "ratings": {"missing": "P3: HK/US 未覆盖"},
                       "news": {"missing": "P3: HK/US 未覆盖"}})
        return result

    result["radar"] = _radar_row(snap, "A", match.code) or {}
    result["events"] = (_stock_events(snap, match.code, asof)
                        if snap else [])

    eq = _eq_detail(snap, match.code) if snap else None
    result["eq"] = ({"missing": "财报输入表缺失"} if eq is None else eq)

    notices = fetch_stock_notices(match.code, name=match.name)
    result["notices"] = ({"missing": "notice source failed"}
                         if notices is None else notices)
    ratings = fetch_stock_ratings(match.code, name=match.name)
    result["ratings"] = ({"missing": "ratings source failed"}
                         if ratings is None else ratings)
    news = fetch_stock_news(match.market_id or "0", match.code,
                            name=match.name)
    result["news"] = ({"missing": "news source failed"}
                      if news is None else news)
    return result
