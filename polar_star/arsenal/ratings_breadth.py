"""ratings-breadth (老兵) — sell-side rating list -> coverage breadth,
revision direction, consensus EPS and target-price band.

Migrated from intel/interpret.py in the 2026-10-13 zero-algorithm move;
behavior byte-identical.  每家机构只取最新一份评级（旧评级只计入
上/下调计数），覆盖机构数量与主力机构名供 AI 判断权威性与覆盖密度。
Replaces the dormant analyst-revision-breadth slot in the cannon
roster — this veteran is already armed with live code.
"""

from collections import Counter

from .statsutil import num_or_none


def ratings_summary(items: list) -> dict | None:
    """A 股评级列表（新→旧）→ 汇总：分布/上调下调/一致 EPS/目标价。"""
    if not items:
        return None
    by_org: dict[str, list] = {}
    for i in items:
        by_org.setdefault(i.payload.get("org") or "", []).append(i)
    dist: Counter = Counter()
    ups = downs = inits = 0
    eps_now, eps_next, tps = [], [], []
    for lst in by_org.values():
        latest = lst[0]
        r = latest.payload.get("rating") or ""
        if r:
            dist[r] += 1
        for it in lst:
            ch = str(it.payload.get("rating_change") or "")
            if ch == "2":
                ups += 1
            elif ch == "1":
                downs += 1
            elif ch == "4":
                inits += 1
        e1 = num_or_none(latest.payload.get("eps_this_year"))
        e2 = num_or_none(latest.payload.get("eps_next_year"))
        if e1:
            eps_now.append(e1)
        if e2:
            eps_next.append(e2)
        tp = num_or_none(latest.payload.get("target_price"))
        if tp:
            tps.append(tp)

    def _avg(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    top = [o for o, _ in sorted(
        Counter(i.payload.get("org") or "" for i in items).items(),
        key=lambda kv: -kv[1]) if o][:3]
    return {"total": len(items), "orgs": len(by_org), "top_orgs": top,
            "distribution": dict(dist), "upgrades": ups,
            "downgrades": downs, "initiations": inits,
            "eps_this_year_avg": _avg(eps_now),
            "eps_next_year_avg": _avg(eps_next),
            "target_price_high": max(tps) if tps else None,
            "target_price_low": min(tps) if tps else None}


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, items=None) -> dict:
    """Breadth read on intel rating items (ctx['intel_ratings'] or param)."""
    items = items if items is not None else ctx.get("intel_ratings") or []
    summary = ratings_summary(items)
    return {
        "weapon": "ratings-breadth",
        "anchor": "覆盖广度(机构数) x 修订方向(上/下调) x 目标价带; "
                  "事实层, 不排名 — 广度本身不是买入理由",
        "items": len(items),
        "summary": summary,
    }
