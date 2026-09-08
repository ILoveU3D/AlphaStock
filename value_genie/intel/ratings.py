"""Ratings subsystem (P2: A-share analyst reports; P3: US consensus,
design §4).

A: reportapi.eastmoney.com/report/list — sell-side reports with rating,
rating change, EPS forecasts and (usually empty) target price.
US: stockanalysis.com ratings page — consensus widget + individual
ratings parsed from the embedded Next.js flight-data blob.
HK: no source found (reportapi carries no HK reports — probe
2026-09-09); the report layer degrades with an explicit note and
rating headlines surface via the news timeline.
"""

import json
import re
from datetime import date, timedelta

from .. import config
from ..fetch.http import EM_WEB, SA
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


# ---------------------------------------------------------------------------
# US: stockanalysis.com consensus (P3)
# ---------------------------------------------------------------------------
def _sa_flight_array(html: str, key: str) -> str | None:
    """Extract `key:[...]` from an embedded flight-data payload via a
    quote-aware balanced bracket scan (probe-verified 2026-09-09)."""
    j = html.find(f"{key}:[")
    if j < 0:
        return None
    k = j + len(key) + 1            # position of '['
    depth, in_str, esc = 0, False, False
    start = k
    while k < len(html):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return html[start:k + 1]
        k += 1
    return None


def _sa_json(blob: str) -> list | None:
    """Bare-key JS array literal -> parsed list. Two probe-validated
    fixes: quote bare keys, and leading-dot floats (stars:.6 -> 0.6)."""
    fixed = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)',
                   r'\1"\2"\3', blob)
    fixed = re.sub(r'([{:[,\s])\.(\d)', r'\g<1>0.\2', fixed)
    try:
        v = json.loads(fixed)
        return v if isinstance(v, list) else None
    except json.JSONDecodeError:
        return None


def fetch_us_consensus(ticker: str, name: str = "") -> list | None:
    """US 一致评级 + 个体评级时间线（stockanalysis.com）。

    返回 IntelItem 列表：首项 kind="consensus"（一致评级/覆盖家数/
    目标价快照），随后 kind="rating" 个体评级（新→旧）。Upgrades→
    positive / Downgrades→negative，其余 neutral。源失败或页面无
    评级数据 → None（fail-closed）。类别股 slug：BRK_B → brk-b。
    """
    slug = ticker.lower().replace("_", "-")
    url = config.SA_RATINGS_URL_TMPL.format(slug=slug)
    html = SA.get_text(url)
    if html is None:
        return None
    i = html.find("widget:{all:{")
    blob = _sa_flight_array(html, "ratings")
    if i < 0 or not blob:
        return None
    ratings = _sa_json(blob)
    if not ratings:
        return None
    seg = html[i:i + 160]
    m = re.search(r'count:(\d+),consensus:"([^"]*)"', seg)
    if not m:
        return None
    count, consensus = int(m.group(1)), m.group(2)
    pm = re.search(r'price_target:([\d.]+)', seg)
    pt = float(pm.group(1)) if pm else None
    items = [IntelItem(
        market="US", code=ticker, name=name,
        subsystem="ratings", kind="consensus",
        event_date=date.today(),
        title=(f"一致评级 {consensus} · {count}家覆盖"
               + (f" · 目标价 ${pt:.2f}" if pt is not None else "")),
        url=url, source="stockanalysis", impact="neutral",
        payload={"consensus": consensus, "count": count,
                 "price_target": pt})]
    for r in ratings:
        d = str(r.get("date") or "")[:10]
        if not d:
            continue
        action = str(r.get("action_rt") or "")
        items.append(IntelItem(
            market="US", code=ticker, name=name,
            subsystem="ratings", kind="rating",
            event_date=date.fromisoformat(d),
            title=f"{r.get('firm') or ''} {r.get('rating_new') or ''}",
            source="stockanalysis",
            impact={"Upgrades": "positive",
                    "Downgrades": "negative"}.get(action, "neutral"),
            payload={"org": str(r.get("firm") or ""),
                     "rating": str(r.get("rating_new") or ""),
                     "last_rating": str(r.get("rating_old") or ""),
                     "action": action,
                     "target_price": _f(r.get("pt_now")),
                     "prev_target": _f(r.get("pt_old")),
                     "analyst": str(r.get("analyst") or "")}))
    return items
