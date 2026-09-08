"""Intel unified data model: IntelItem, impact mapping, forecast
direction (design 2026-09-08 §3/§5).

``impact`` is a static per-kind mapping (解禁=negative, 回购=positive),
NOT sentiment inference — interpreting the text is the AI agent's job.
"""

import json
from dataclasses import dataclass, field
from datetime import date


@dataclass
class IntelItem:
    market: str            # "A" | "HK" | "US"
    code: str              # snapshot code form (600519 / 00700 / AAPL)
    name: str
    subsystem: str         # "earnings" | "announcements" | "news" | "ratings"
    kind: str              # unlock|holder_cut|holder_add|buyback|placement|
                           # forecast_up|forecast_down|forecast_flat|
                           # report_date|eq_flag|...
    event_date: date
    title: str
    url: str = ""
    source: str = "eastmoney"
    impact: str = "neutral"    # positive|negative|neutral
    payload: dict = field(default_factory=dict)


IMPACT_BY_KIND = {
    "unlock": "negative",
    "holder_cut": "negative",
    "holder_add": "positive",
    "buyback": "positive",
    "placement": "negative",
    "forecast_up": "positive",
    "forecast_down": "negative",
    "forecast_flat": "neutral",
    "report_date": "neutral",
    "eq_flag": "negative",
}

# A股业绩预告 PREDICT_TYPE -> 方向 (-1/0/1)
FORECAST_DIRECTION = {
    "预增": 1, "略增": 1, "扭亏": 1, "续盈": 1,
    "预减": -1, "略减": -1, "首亏": -1, "续亏": -1,
    "预平": 0, "不确定": 0,
}

DETAIL_COLUMNS = ["market", "code", "name", "subsystem", "kind",
                  "event_date", "impact", "title", "url", "source",
                  "payload"]


def item_to_row(item: IntelItem) -> dict:
    """Flatten an IntelItem to an event_radar.csv row (payload→JSON)."""
    return {
        "market": item.market, "code": item.code, "name": item.name,
        "subsystem": item.subsystem, "kind": item.kind,
        "event_date": item.event_date.isoformat(),
        "impact": item.impact, "title": item.title, "url": item.url,
        "source": item.source,
        "payload": json.dumps(item.payload, ensure_ascii=False),
    }


def row_to_item(row) -> IntelItem:
    """Rebuild an IntelItem from an event_radar.csv row/dict."""
    d = row if isinstance(row, dict) else dict(row)
    return IntelItem(
        market=d["market"], code=str(d["code"]), name=d.get("name", ""),
        subsystem=d["subsystem"], kind=d["kind"],
        event_date=date.fromisoformat(str(d["event_date"])[:10]),
        impact=d.get("impact", "neutral"),
        title=d.get("title", ""), url=d.get("url") or "",
        source=d.get("source", ""),
        payload=json.loads(d.get("payload") or "{}"),
    )
