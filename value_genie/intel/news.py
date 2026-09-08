"""News subsystem (P2: A-share per-stock timeline, design §4).

np-listapi wap getListInfo — per-stock CMS news feed. No sentiment
scoring by design (design §1 non-goal): items carry neutral impact
and the AI agent interprets heat/context.
"""

from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from .model import IntelItem


def fetch_stock_news(market_id: str, code: str, name: str = "",
                     days: int = None) -> list | None:
    """近 days 天个股新闻时间线（np-listapi）。

    market_id: 东财市场前缀（1=沪, 0=深+北）——即 Match.market_id。
    返回 IntelItem 列表（subsystem="news"），新→旧由接口保证（sr 默认）；
    源失败返回 None（fail-closed），空时间线返回 []。
    """
    days = days or config.INTEL_NEWS_DAYS
    since = (date.today() - timedelta(days=days)).isoformat()
    raw = EM_WEB.get_json(config.EM_NEWS_URL, params={
        "client": "wap", "type": 1,
        "mTypeAndCode": f"{market_id}.{code}",
        "pageSize": 50, "pageIndex": 1, "req_trace": "1",
    })
    if raw is None or raw.get("code") != 1:
        return None
    rows = ((raw.get("data") or {}).get("list")) or []
    items = []
    for r in rows:
        when = str(r.get("Art_ShowTime") or "")[:10]
        if not when or when < since:      # lexical ISO compare
            continue
        items.append(IntelItem(
            market="A", code=code, name=name,
            subsystem="news", kind="news",
            event_date=date.fromisoformat(when),
            title=str(r.get("Art_Title") or ""),
            url=str(r.get("Art_Url") or ""),
            source="eastmoney", impact="neutral",
            payload={"media": str(r.get("Art_MediaName") or ""),
                     "show_time": str(r.get("Art_ShowTime") or "")}))
    return items
