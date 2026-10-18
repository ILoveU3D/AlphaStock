"""Full-market profile distillation campaign (user mandate 2026-10-18).

Same division of labor as the modeling campaign (mandate 2026-10-04):
the machine builds the tiered queue and bulk-fetches raw source text
ahead of the AI frontier; the distillation itself (scores + written
arguments) stays the AI's alone, one company at a time.

Tier order is REUSED from the modeling campaign (holdings -> funnel by
core_score -> market industry by industry) — who to cover is the same
question for both assets, so there is no reason to fork the ordering.

Campaign state lives in profiles/campaign.json (LOCAL-ONLY, atomic
writes; profiles/ is gitignored). Per-company state is never stored —
it is derived from disk: fetched = raw file exists; distilled =
assessment exists and is not stale (a stale distillation re-enters the
work queue: re-distill before any verdict, mandate 2026-10-18).
"""

import json
from datetime import datetime
from pathlib import Path

from . import config, profile as prof


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Campaign file
# ---------------------------------------------------------------------------
def campaign_path() -> Path:
    return prof.profiles_dir() / "campaign.json"


def load_campaign() -> "dict | None":
    p = campaign_path()
    if not p.exists():
        return None
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(c, dict) or not c.get("queue"):
        return None
    return c


def save_campaign(c: dict) -> Path:
    from .atomic import atomic_write_text
    c["updated_at"] = _now()
    p = campaign_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(c, ensure_ascii=False, indent=2))
    return p


# ---------------------------------------------------------------------------
# Queue build (tier builders reused from the modeling campaign)
# ---------------------------------------------------------------------------
def init(data_dir=None) -> dict:
    """(Re)build the campaign queue from the latest snapshot + users."""
    from .model.campaign import (TIER_LABELS, funnel_targets,
                                 holdings_targets, market_targets)
    from .report import resolve_snapshot
    snap_dir = resolve_snapshot(data_dir)
    t1 = holdings_targets()
    known = {t["id"] for t in t1}
    t2 = [t for t in funnel_targets(snap_dir) if t["id"] not in known]
    known |= {t["id"] for t in t2}
    t3, gaps = market_targets(snap_dir, known)
    c = {
        "version": 1, "created_at": _now(), "snapshot": snap_dir.name,
        "note": ("full-market profile distillation campaign (user mandate "
                 "2026-10-18): machine builds the queue and fetches raw "
                 "text; the AI distills one company at a time. Quality "
                 "bar: business core for every name; culture core only "
                 "when behavior-level evidence exists (else veto-only)."),
        "tier_labels": TIER_LABELS,
        "gaps": gaps,
        "queue": t1 + t2 + t3,
    }
    save_campaign(c)
    return c


# ---------------------------------------------------------------------------
# Derived state (never stored)
# ---------------------------------------------------------------------------
def _fetched_ids() -> set:
    out = set()
    d = prof.raw_dir()
    if not d.exists():
        return out
    for p in d.glob("*/*.json"):
        market = p.parent.name.upper()
        if market not in ("A", "HK", "US"):
            continue
        from .users import normalize_code
        out.add(f"{market}:{normalize_code(market, p.stem)}")
    return out


def _distilled_ids() -> set:
    """Non-stale assessments only — a stale distillation re-enters the
    work queue (its evidence base changed; re-distill before verdicts)."""
    return {a["id"] for a in prof.list_assessments()
            if not a.get("raw_stale")}


def progress() -> dict:
    c = load_campaign()
    if c is None:
        return {"initialized": False}
    fetched = _fetched_ids()
    distilled = _distilled_ids()
    labels = c.get("tier_labels") or {}
    tiers, done_total, ready_total = [], 0, 0
    for tier in (1, 2, 3):
        rows = [q for q in c["queue"] if q.get("tier") == tier]
        done = sum(1 for q in rows if q["id"] in distilled)
        ready = sum(1 for q in rows
                    if q["id"] not in distilled and q["id"] in fetched)
        done_total += done
        ready_total += ready
        tiers.append({"tier": tier, "label": labels.get(str(tier), ""),
                      "total": len(rows), "distilled": done,
                      "fetched": ready,
                      "pending": len(rows) - done - ready})
    total = len(c["queue"])
    return {
        "initialized": True, "snapshot": c.get("snapshot"),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "queue_total": total, "distilled": done_total,
        "fetched": ready_total,
        "distilled_pct": (round(100.0 * done_total / total, 2)
                          if total else 0.0),
        "tiers": tiers, "gaps": c.get("gaps") or [],
        "next": [q["id"] for q in c["queue"] if q["id"] not in distilled][:10],
    }


def next_targets(n: int = 10) -> list:
    """The AI work queue: first N undistilled targets in campaign order,
    each labeled fetched/unfetched."""
    c = load_campaign()
    if c is None:
        return []
    fetched = _fetched_ids()
    distilled = _distilled_ids()
    out = []
    for q in c["queue"]:
        if q["id"] in distilled:
            continue
        row = dict(q)
        row["fetched"] = q["id"] in fetched
        out.append(row)
        if len(out) >= n:
            break
    return out
