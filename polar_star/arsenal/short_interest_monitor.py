"""short-interest-monitor (DORMANT) — FINRA biweekly short-interest lens.

The weapon is registered but disarmed: the FINRA biweekly
short-interest feed (or exchange filing equivalent) is not built, so
there is nothing honest to compute.  run() always returns the dormant
envelope — no fabricated proxies from price/volume are offered.

Lineage: short-interest as a sentiment/squeeze gauge (contrarian
reading at high SI, crowding risk at low SI) — standard market-micro
structure practice; wakes when the data source lands.
"""

ANCHOR = ("空头兴趣监测——数据未就位, 休眠; 红灯可否决,"
          "绿灯不构成买入理由")


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "short-interest-monitor",
        "anchor": ANCHOR,
        "status": "dormant",
        "reason": "FINRA biweekly short-interest feed not built",
        "wake_condition": ("short-interest data source (FINRA biweekly "
                           "/ exchange filings)"),
    }
