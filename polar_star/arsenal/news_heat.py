"""news-heat (老兵) — news timeline -> heat counts (day granularity) +
freshness of the latest item.

Migrated from intel/interpret.py in the 2026-10-13 zero-algorithm move;
behavior byte-identical.  today/3天/7天 vs 前7天 → 升温/降温/持平
(短线关注边际变化，升温=注意力聚集，骤升往往是高潮预警).
"""

from datetime import date, datetime


def news_heat(items: list, asof: date | None = None) -> dict | None:
    """新闻时间线 → 热度计数（日粒度）+ 最新一条时效。

    items 新→旧由 API 保证。
    """
    if not items:
        return None
    asof = asof or date.today()
    days = [max(0, (asof - i.event_date).days) for i in items]
    today = sum(1 for d in days if d == 0)
    n3 = sum(1 for d in days if d <= 2)
    n7 = sum(1 for d in days if d <= 6)
    prior7 = sum(1 for d in days if 7 <= d <= 13)
    if n7 >= 3 and n7 >= 2 * prior7:
        verdict = "升温"
    elif prior7 >= 3 and n7 * 3 <= prior7:
        verdict = "降温"
    else:
        verdict = "持平"
    out = {"today": today, "d3": n3, "d7": n7, "prior7": prior7,
           "verdict": verdict, "latest_hours": None}
    st = str(items[0].payload.get("show_time") or "")
    try:
        t = datetime.strptime(st[:19], "%Y-%m-%d %H:%M:%S")
        out["latest_hours"] = round(
            (datetime.now() - t).total_seconds() / 3600.0, 1)
    except ValueError:
        pass
    return out


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, items=None, asof: date | None = None) -> dict:
    """Heat read on intel news items (ctx['intel_news'] or param)."""
    items = items if items is not None else ctx.get("intel_news") or []
    heat = news_heat(items, asof)
    return {
        "weapon": "news-heat",
        "anchor": "7日热度 vs 前7日: 升温=注意力聚集(骤升常是高潮预警), "
                  "降温=注意力退潮; 事实层, 不排名",
        "items": len(items),
        "heat": heat,
    }
