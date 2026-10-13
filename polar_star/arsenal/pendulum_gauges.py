"""pendulum-gauges (DORMANT) — Howard Marks' sentiment pendulum gauges.

VIX, put/call ratio and fund-flow gauges are the dials of Marks'
pendulum (extreme fear <-> extreme greed); none of the required
options/volatility/fund-flow feeds exists in the snapshot-pure context,
so the weapon is registered but disarmed.  run() always returns the
dormant envelope — no proxy gauges from price action are fabricated.

Lineage: Howard Marks, Mastering the Market Cycle (2018) — the
pendulum never stops at fair value; the gauges locate where in the
swing we stand.
"""

ANCHOR = ("情绪钟摆仪表——数据未就位, 休眠; 红灯可否决,"
          "绿灯不构成买入理由")


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "pendulum-gauges",
        "anchor": ANCHOR,
        "status": "dormant",
        "reason": "VIX / put-call / fund-flow gauges not built",
        "wake_condition": "options & volatility data source",
    }
