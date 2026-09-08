"""News subsystem (P2: A-share per-stock timeline; P3: HK/US, design §4).

np-listapi wap getListInfo — per-stock CMS news feed, one endpoint for
all three markets (mTypeAndCode prefix: 1/0=A, 116=HK, 105/106=US).
No sentiment scoring by design (design §1 non-goal): items carry neutral
impact and the AI agent interprets heat/context.
"""

from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from .model import IntelItem


def _news_once(market: str, market_id: str, code: str, name: str,
               days: int) -> list | None:
    """One np-listapi call. Source failure → None (fail-closed)."""
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
            market=market, code=code, name=name,
            subsystem="news", kind="news",
            event_date=date.fromisoformat(when),
            title=str(r.get("Art_Title") or ""),
            url=str(r.get("Art_Url") or ""),
            source="eastmoney", impact="neutral",
            payload={"media": str(r.get("Art_MediaName") or ""),
                     "show_time": str(r.get("Art_ShowTime") or "")}))
    return items


def fetch_stock_news(market_id: str, code: str, name: str = "",
                     days: int = None, market: str = "A") -> list | None:
    """近 days 天个股新闻时间线（np-listapi，A/HK/US 同一端点）。

    market_id: 东财市场前缀（A: 1=沪/0=深+北, HK: 116, US: 105/106）
    ——即 Match.market_id。US 且前缀缺失时按 NASDAQ→NYSE 顺序试
    （错交易所前缀返回空列表而非报错；AMEX 107 无数据为已知局限，
    快照外美股由本兜底覆盖）。返回 IntelItem 列表
    （subsystem="news"），新→旧由接口保证；源失败返回 None
    （fail-closed），空时间线返回 []。
    """
    days = days or config.INTEL_NEWS_DAYS
    if market == "US" and not market_id:
        saw_empty = False
        for mid in config.US_NEWS_PREFIXES:
            got = _news_once("US", mid, code, name, days)
            if got:
                return got
            if got is not None:
                saw_empty = True
        return [] if saw_empty else None   # all-failed → fail-closed
    prefix = market_id or ("116" if market == "HK" else "0")
    return _news_once(market, prefix, code, name, days)
