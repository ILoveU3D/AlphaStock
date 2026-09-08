"""Per-stock intelligence report (情报通道, design §7).

Section assembly for ``intel X``: radar row + event details from the
snapshot's full-market batch tables (zero network for snapshot stocks),
live per-stock notices / ratings / news, earnings-quality detail.
Fail-closed per section: a failed section becomes {"missing": reason},
never fabricated data. A: full five sections. HK: notices + news
(Eastmoney mirror); research ratings have no source — explicit missing
note. US: filings (EDGAR) + news + consensus (stockanalysis). Radar
batch tables and earnings-quality inputs are A-share-only; HK/US
sections degrade with explicit notes.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from .announcements import fetch_stock_notices, fetch_us_filings
from .model import earnings_quality, item_to_row
from .news import fetch_stock_news
from .radar import (_appointment_items, _buyback_items, _eq_records,
                    _forecast_items, _holder_items, _placement_items,
                    _read_csv, _unlock_items, RADAR_COLUMNS)
from .ratings import fetch_stock_ratings, fetch_us_consensus


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
    """单股舆情情报 result dict（五个板块 + 雷达行，fail-closed）。

    A: 全五板块。HK: 公告+新闻（东财镜像），研报无源（显式降级）。
    US: 披露文件（EDGAR）+ 新闻 + 一致评级（stockanalysis）。
    雷达批表与粉饰信号输入为 A 股专属——HK/US 相应板块显式标注。
    """
    snap = Path(snapshot_dir) if snapshot_dir else None
    asof = asof or date.today()
    market = match.market
    result = {"match": match, "snapshot": snap.name if snap else None,
              "asof": asof.isoformat()}

    result["radar"] = _radar_row(snap, market, match.code) or {}

    if market == "A":
        result["events"] = (_stock_events(snap, match.code, asof)
                            if snap else [])
        eq = _eq_detail(snap, match.code) if snap else None
        result["eq"] = ({"missing": "财报输入表缺失"} if eq is None else eq)
    else:
        result["events"] = {
            "missing": "雷达批表当前仅覆盖 A 股（HK/US 批量事件属后续阶段）"}
        result["eq"] = {
            "missing": "粉饰信号输入（应收/存货/OCF/扣非）为 A 股快照专属"}

    if market == "US":
        notices = fetch_us_filings(match.code, name=match.name)
        result["notices"] = ({"missing": "EDGAR source failed"}
                             if notices is None else notices)
    elif market == "HK":
        notices = fetch_stock_notices(match.code, name=match.name,
                                      market="HK")
        result["notices"] = ({"missing": "notice source failed"}
                             if notices is None else notices)
    else:
        notices = fetch_stock_notices(match.code, name=match.name)
        result["notices"] = ({"missing": "notice source failed"}
                             if notices is None else notices)

    if market == "HK":
        result["ratings"] = {
            "missing": "港股研报源缺失（东财 reportapi 不含港股）；"
                       "评级动向请看新闻时间线"}
    elif market == "US":
        ratings = fetch_us_consensus(match.code, name=match.name)
        result["ratings"] = ({"missing": "ratings source failed"}
                             if ratings is None else ratings)
    else:
        ratings = fetch_stock_ratings(match.code, name=match.name)
        result["ratings"] = ({"missing": "ratings source failed"}
                             if ratings is None else ratings)

    if market == "US":
        news = fetch_stock_news(match.market_id or "", match.code,
                                name=match.name, market="US")
    elif market == "HK":
        news = fetch_stock_news(match.market_id or "116", match.code,
                                name=match.name, market="HK")
    else:
        news = fetch_stock_news(match.market_id or "0", match.code,
                                name=match.name)
    result["news"] = ({"missing": "news source failed"}
                      if news is None else news)
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _items_block(items, limit=3) -> str:
    if not items:
        return "0 条"
    head = " · ".join(f"{i.event_date.strftime('%m-%d')} {i.title}"
                      for i in items[:limit])
    more = f" …(+{len(items) - limit})" if len(items) > limit else ""
    return f"{len(items)} 条（最近: {head}{more}）"


def _radar_line(radar: dict) -> str:
    if not radar:
        return "快照无雷达行（快照外股票或旧快照）"

    def _n(key, fmt="{:.1f}", default="无"):
        v = radar.get(key)
        if v is None:
            return default
        try:
            return fmt.format(float(v))
        except (TypeError, ValueError):
            return default

    due = radar.get("report_due_days")
    due_s = ("无预约" if due is None or float(due) >= 999
             else f"{int(float(due))}天")
    return (f"解禁30天 {_n('unlock_pct_30d')}% | "
            f"90天 {_n('unlock_pct_90d')}% | "
            f"减持计划 {'有' if _n('holder_cut_flag', '{:.0f}') == '1' else '无'} | "
            f"增发 {'有' if _n('dilution_flag', '{:.0f}') == '1' else '无'} | "
            f"回购 {'有' if _n('buyback_active', '{:.0f}') == '1' else '无'} | "
            f"财报预约 {due_s} | "
            f"预告方向 {_n('forecast_flag', '{:.0f}')} | "
            f"粉饰信号 {_n('eq_flags', '{:.0f}')} | "
            f"intel_red={_n('intel_red', '{:.0f}')}")


def render_intel(result: dict) -> str:
    m = result["match"]
    lines = [f"== 舆情情报: {m.name} ({m.market}/{m.code}) =="]
    lines.append(f"[事件雷达] {_radar_line(result.get('radar') or {})}")
    events = result.get("events")
    if isinstance(events, dict):
        lines.append(f"[事件明细] 数据缺失: {events.get('missing', '')}")
    else:
        lines.append(f"[事件明细] {_items_block(events)}")

    eq = result.get("eq")
    if isinstance(eq, dict):
        lines.append(f"[财报信号] 数据缺失: {eq.get('missing', '')}")
    elif eq:
        lines.append("[财报信号] 粉饰信号 "
                     f"{len(eq)} 项: " + "; ".join(eq))
    else:
        lines.append("[财报信号] 无粉饰信号")

    notices = result.get("notices")
    if isinstance(notices, dict):
        lines.append(f"[公告时间线] 数据缺失: {notices.get('missing', '')}")
    elif result["match"].market == "US":
        lines.append(f"[披露文件时间线] 近{config.INTEL_FILING_DAYS}天 "
                     f"{_items_block(notices)}")
    else:
        lines.append(f"[公告时间线] 近{config.INTEL_NOTICE_DAYS}天 "
                     f"{_items_block(notices)}")

    ratings = result.get("ratings")
    if isinstance(ratings, dict):
        lines.append(f"[投行评级] 数据缺失: {ratings.get('missing', '')}")
    elif ratings and ratings[0].kind == "consensus":
        rest = ratings[1:]
        latest = (f"最近: {rest[0].event_date.strftime('%m-%d')} "
                  f"{rest[0].title}"
                  + (f" 目标价 ${rest[0].payload.get('target_price')}"
                     if rest[0].payload.get("target_price") else "")
                  ) if rest else "无个体评级明细"
        lines.append(f"[投行评级] {ratings[0].title}；近期个体评级 "
                     f"{len(rest)} 份（{latest}）")
    else:
        latest = (f"最近: {ratings[0].event_date.strftime('%m-%d')} "
                  f"{ratings[0].title}"
                  + (f" ←{ratings[0].payload.get('last_rating')}"
                     if ratings[0].payload.get("last_rating") else "")
                  ) if ratings else "无研报"
        lines.append(f"[投行评级] 近{config.INTEL_RATING_DAYS}天 "
                     f"{len(ratings)} 份（{latest}）")

    news = result.get("news")
    if isinstance(news, dict):
        lines.append(f"[新闻时间线] 数据缺失: {news.get('missing', '')}")
    else:
        media = (f" · {news[0].payload.get('media', '')}"
                 if news and news[0].payload.get("media") else "")
        head = (f"最近: {news[0].event_date.strftime('%m-%d')} "
                f"{news[0].title}{media}") if news else "无新闻"
        lines.append(f"[新闻时间线] 近{config.INTEL_NEWS_DAYS}天 "
                     f"{len(news)} 条（{head}）"
                     "——热度供 AI 结合语境解读，不自动打分")

    snap = result.get("snapshot")
    lines.append(f"data as of: radar/events/eq: snapshot {snap or '无'}; "
                 f"notices/ratings/news: live {result['asof']}")
    return "\n".join(lines)


def to_json(result: dict) -> str:
    """Pure-JSON contract: sections missing → null, items → item dicts."""
    import json

    def _items(sec):
        v = result.get(sec)
        if isinstance(v, dict) or v is None:
            return None
        rows = []
        for i in v:
            row = item_to_row(i)
            row["payload"] = i.payload     # nested object, not CSV string
            rows.append(row)
        return rows

    payload = {
        "match": {"market": result["match"].market,
                  "code": result["match"].code,
                  "name": result["match"].name},
        "snapshot": result.get("snapshot"),
        "asof": result.get("asof"),
        "radar": result.get("radar") or None,
        "events": _items("events"),
        "eq": (None if isinstance(result.get("eq"), dict)
               else result.get("eq")),
        "notices": _items("notices"),
        "ratings": _items("ratings"),
        "news": _items("news"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
