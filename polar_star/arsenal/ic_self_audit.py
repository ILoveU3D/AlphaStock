"""ic-self-audit (DORMANT) — information-coefficient audit of our scores.

IC (rank correlation between a score and forward returns) is the
hygiene check on every score the toolkit emits (core_score, pillar
scores, weapon readings).  It needs a snapshot TIME SERIES — scores
from dated snapshots crossed with the returns that followed — and the
arsenal currently holds a single snapshot (post 2026-10-13 cleanup),
so the weapon is registered but disarmed.  run() always returns the
dormant envelope.

Lineage: house quant hygiene; Grinold & Kahn, Active Portfolio
Management (1999) — the IC is the canonical skill measure.
"""

ANCHOR = ("IC 自审计——快照时间序列不足, 休眠; 红灯可否决,"
          "绿灯不构成买入理由")


def run(ctx: dict, **params) -> dict:
    return {
        "weapon": "ic-self-audit",
        "anchor": ANCHOR,
        "status": "dormant",
        "reason": ("snapshot time series absent — single snapshot after "
                   "the 2026-10-13 cleanup"),
        "wake_condition": (">= 3 dated snapshots for score-vs-forward-"
                           "return rank IC"),
    }
