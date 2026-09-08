"""Ratings subsystem (P2: A-share analyst reports, design §4).

reportapi.eastmoney.com/report/list — sell-side reports with rating,
rating change, EPS forecasts and (usually empty) target price.
"""

from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB
from .model import IntelItem

REPORT_URL_TMPL = "https://data.eastmoney.com/report/info/{info}.html"

# Eastmoney ratingChange convention (observed 3=maintain when
# rating==last_rating; 1/2/4 per EM web convention): 1=下调 2=上调
# 3=维持 4=首次。Payload keeps the raw value; impact uses it only as a
# category hint — the agent reads rating vs last_rating directly.
_RATING_IMPACT = {"1": "negative", "2": "positive"}


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def fetch_stock_ratings(code: str, name: str = "",
                        days: int = None) -> list | None:
    """近 days 天投行研报评级（reportapi，qType=0 个股研报）。

    返回 IntelItem 列表（subsystem="ratings", kind="rating"），
    源失败 None（fail-closed），无研报 []。目标价（indvAimPriceT/L）
    A 股普遍为空——保持 None，绝不编造。
    """
    days = days or config.INTEL_RATING_DAYS
    end = date.today()
    begin = end - timedelta(days=days)
    raw = EM_WEB.get_json(config.EM_REPORT_URL, params={
        "qType": 0, "code": code, "pageNo": 1, "pageSize": 50,
        "beginTime": begin.isoformat(), "endTime": end.isoformat(),
    })
    if raw is None or "data" not in raw:
        return None
    rows = raw.get("data") or []
    items = []
    for r in rows:
        pd_ = str(r.get("publishDate") or "")[:10]
        if not pd_:
            continue
        change = str(r.get("ratingChange") or "")
        items.append(IntelItem(
            market="A", code=code, name=name,
            subsystem="ratings", kind="rating",
            event_date=date.fromisoformat(pd_),
            title=f"{r.get('orgSName') or ''} {r.get('emRatingName') or ''}",
            url=(REPORT_URL_TMPL.format(info=r.get("infoCode"))
                 if r.get("infoCode") else ""),
            source="eastmoney",
            impact=_RATING_IMPACT.get(change, "neutral"),
            payload={"org": str(r.get("orgSName") or ""),
                     "rating": str(r.get("emRatingName") or ""),
                     "last_rating": str(r.get("lastEmRatingName") or ""),
                     "rating_change": change,
                     "eps_this_year": _f(r.get("predictThisYearEps")),
                     "eps_next_year": _f(r.get("predictNextYearEps")),
                     "target_price": (_f(r.get("indvAimPriceT"))
                                      or _f(r.get("indvAimPriceL"))),
                     "researcher": str(r.get("researcher") or "")}))
    return items
