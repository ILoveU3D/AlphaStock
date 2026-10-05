"""Full-market modeling campaign queue (user mandate 2026-10-04).

skills/19 campaign order: holdings/keyhole -> funnel candidates ->
industry by industry. The division of labor is unchanged (mandate
2026-10-03): the machine builds the ordered queue, gathers raw
material ahead of the AI frontier and tracks progress — the
understanding layer (model.json) stays the AI's alone, one company
at a time. This module is the monitor's hands, never the modeler.

Campaign state lives in models/campaign.json (LOCAL-ONLY, atomic
writes). Per-company state is never stored — it is derived from
disk: gathered = raw/history.json exists; modeled = lint-complete
dossier.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import config
from ..users import list_users, normalize_code
from . import store

TIER_HOLDINGS = 1    # keyhole + every user's positions
TIER_FUNNEL = 2      # master.csv candidates, core_score-ranked
TIER_MARKET = 3      # everything quoted, industry by industry
TIER_LABELS = {TIER_HOLDINGS: "holdings", TIER_FUNNEL: "funnel",
               TIER_MARKET: "market"}

FAIL_MAX = 3              # gather failures before a target is parked
GATHER_BACKLOG_CAP = 300  # gathered-but-unmodeled ceiling


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _clean(s) -> str:
    if s is None:
        return ""
    t = str(s).strip()
    return "" if t.lower() in ("nan", "none") else t


def _mk(market: str, code, name, tier: int) -> dict:
    code = normalize_code(market, str(code).strip())
    return {"id": f"{market}:{code}", "market": market, "code": code,
            "name": _clean(name), "tier": tier}


# ---------------------------------------------------------------------------
# Campaign file
# ---------------------------------------------------------------------------
def campaign_path() -> Path:
    return store.models_dir() / "campaign.json"


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
    from ..atomic import atomic_write_text
    c["updated_at"] = _now()
    p = campaign_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(c, ensure_ascii=False, indent=2))
    return p


# ---------------------------------------------------------------------------
# Tier builders
# ---------------------------------------------------------------------------
def holdings_targets() -> list:
    """Tier 1: every user's open positions (the keyhole lives here)."""
    out, seen = [], set()
    for u in list_users():
        for h in (getattr(u, "holdings", None) or []):
            t = _mk(h.market, h.code, h.name, TIER_HOLDINGS)
            if t["id"] not in seen:
                seen.add(t["id"])
                out.append(t)
    return out


def funnel_targets(snap_dir: Path) -> list:
    """Tier 2: funnel candidates ranked by core_score (the only key)."""
    from ..report import load_master
    master = load_master(snap_dir)
    if "core_score" not in master.columns:
        master = master.assign(core_score=None)
    df = master[master["market"].astype(str).isin(("A", "HK", "US"))].copy()
    df["_cs"] = pd.to_numeric(df["core_score"], errors="coerce")
    df = df.sort_values("_cs", ascending=False, na_position="last")
    out, seen = [], set()
    for _, r in df.iterrows():
        t = _mk(r["market"], r["code"], r.get("name"), TIER_FUNNEL)
        if t["id"] not in seen:
            seen.add(t["id"])
            out.append(t)
    return out


def _quotes_targets(snap_dir: Path, market: str, tier: int,
                    exclude: set) -> tuple:
    p = snap_dir / f"{market.lower()}_quotes.csv"
    if not p.exists():
        return [], f"{market} quotes missing in snapshot {snap_dir.name}"
    df = pd.read_csv(p, dtype={"code": str, "market": str})
    if "market" in df.columns:
        df = df[df["market"].astype(str) == market]
    if "market_cap" in df.columns:
        caps = pd.to_numeric(df["market_cap"], errors="coerce").fillna(0.0)
    else:
        caps = pd.Series(0.0, index=df.index)
    df["_cap"] = caps
    df["_ind"] = (df["industry"].fillna("~").astype(str)
                  if "industry" in df.columns else "~")
    if market == "A" and "name" in df.columns:
        # ST/退市-risk names sink to the tier tail, whatever their size
        df["_risk"] = (df["name"].astype(str).str.upper()
                       .str.contains("ST|退", regex=True))
    else:
        df["_risk"] = False
    df = df.sort_values(["_risk", "_ind", "_cap"],
                        ascending=[True, True, False])
    out, seen = [], set()
    for _, r in df.iterrows():
        t = _mk(market, r["code"], r.get("name"), tier)
        if t["id"] in exclude or t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    return out, None


def _hk_batch_targets(tier: int, exclude: set,
                      snap_dir: "Path | None" = None) -> tuple:
    """Tier-3 HK names from the mainindicator batch (the full list the
    funnel stage-1 sees); the batch df carries HK_BATCH_MAP-renamed
    columns (code/...), so names are joined from snapshot hk_quotes
    where present. Snapshot hk_quotes is only the liquid subset —
    regression guard: the 2026-10-04 bug looked for the raw
    SECURITY_CODE column name and silently dropped ~2,200 HK names."""
    err, df = None, None
    try:
        from ..fetch.fundamentals import fetch_hk_mainindicator_batch
        df = fetch_hk_mainindicator_batch(quiet=True)
    except Exception as exc:
        err = str(exc)
    if df is None or df.empty:
        gap = "HK mainindicator batch unavailable"
        if err:
            gap += f" ({err[:120]})"
        return [], gap + " — tier-3 HK limited to snapshot quotes"
    code_col = next((c for c in ("code", "SECURITY_CODE")
                     if c in df.columns), None)
    if code_col is None:
        return [], ("HK batch lacks a code column — tier-3 HK limited "
                    "to snapshot quotes")
    name_col = next((c for c in ("name", "SECURITY_NAME_ABBR",
                                 "SECURITY_NAME")
                     if c in df.columns), None)
    names = {}
    if snap_dir is not None:
        qp = snap_dir / "hk_quotes.csv"
        if qp.exists():
            try:
                qdf = pd.read_csv(qp, dtype={"code": str})
                if {"code", "name"}.issubset(qdf.columns):
                    names = dict(zip(
                        qdf["code"].astype(str).str.zfill(5),
                        qdf["name"].astype(str)))
            except (OSError, ValueError):
                names = {}
    out, seen = [], set()
    for _, r in df.iterrows():
        code = str(r[code_col]).strip()
        fallback = r.get(name_col) if name_col else ""
        t = _mk("HK", code, names.get(code, fallback), tier)
        if t["id"] in exclude or t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    return out, None


def market_targets(snap_dir: Path, exclude: set) -> tuple:
    """Tier 3: every quoted name not in tiers 1-2 — A and US grouped by
    industry then market cap (risk names last); HK from the full batch."""
    out, gaps = [], []
    for market in ("A", "US"):
        rows, gap = _quotes_targets(snap_dir, market, TIER_MARKET, exclude)
        out.extend(rows)
        if gap:
            gaps.append(gap)
    hk, gap = _hk_batch_targets(TIER_MARKET, exclude, snap_dir)
    out.extend(hk)
    if gap:
        gaps.append(gap)
        fb, _ = _quotes_targets(snap_dir, "HK", TIER_MARKET, exclude)
        out.extend(fb)
    return out, gaps


def init(data_dir=None) -> dict:
    """(Re)build the campaign queue from the latest snapshot + users."""
    from ..report import resolve_snapshot
    snap_dir = resolve_snapshot(data_dir)
    t1 = holdings_targets()
    known = {t["id"] for t in t1}
    t2 = [t for t in funnel_targets(snap_dir) if t["id"] not in known]
    known |= {t["id"] for t in t2}
    t3, gaps = market_targets(snap_dir, known)
    c = {
        "version": 1, "created_at": _now(), "snapshot": snap_dir.name,
        "note": ("full-market modeling campaign (user mandate 2026-10-04): "
                 "machine builds the queue and gathers ahead; the AI "
                 "writes dossiers one company at a time (mandate "
                 "2026-10-03)"),
        "gaps": gaps, "failures": {},
        "queue": t1 + t2 + t3,
    }
    save_campaign(c)
    return c


# ---------------------------------------------------------------------------
# Derived state (never stored)
# ---------------------------------------------------------------------------
def _modeled_ids() -> set:
    from . import archive as marc
    return {r["id"] for r in marc.status() if r["complete"]}


def _incomplete_ids() -> set:
    from . import archive as marc
    return {r["id"] for r in marc.status() if not r["complete"]}


def _gathered_ids() -> set:
    out = set()
    d = store.models_dir()
    if not d.exists():
        return out
    for p in d.glob("*/*/raw/history.json"):
        market = p.parent.parent.parent.name.upper()
        code = p.parent.parent.name
        out.add(f"{market}:{normalize_code(market, code)}")
    return out


def progress() -> dict:
    c = load_campaign()
    if c is None:
        return {"initialized": False}
    modeled = _modeled_ids()
    incomplete = _incomplete_ids()
    gathered = _gathered_ids()
    failures = c.get("failures") or {}
    tiers, done_total, ready_total = [], 0, 0
    for tier in (TIER_HOLDINGS, TIER_FUNNEL, TIER_MARKET):
        rows = [q for q in c["queue"] if q.get("tier") == tier]
        done = sum(1 for q in rows if q["id"] in modeled)
        ready = sum(1 for q in rows
                    if q["id"] not in modeled and q["id"] in gathered)
        done_total += done
        ready_total += ready
        tiers.append({"tier": tier, "label": TIER_LABELS[tier],
                      "total": len(rows), "modeled": done,
                      "ready": ready, "pending": len(rows) - done - ready})
    total = len(c["queue"])
    return {
        "initialized": True, "snapshot": c.get("snapshot"),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "queue_total": total, "modeled": done_total, "ready": ready_total,
        "modeled_pct": round(100.0 * done_total / total, 2) if total else 0.0,
        "incomplete_dossiers": sorted(incomplete - modeled),
        "parked": {k: v for k, v in failures.items()
                   if v.get("count", 0) >= FAIL_MAX},
        "tiers": tiers, "gaps": c.get("gaps") or [],
        "next": [q["id"] for q in c["queue"] if q["id"] not in modeled][:10],
    }


def next_targets(n: int = 10) -> list:
    """The AI work queue: first N unmodeled targets in campaign order,
    each labeled gathered/ungathered."""
    c = load_campaign()
    if c is None:
        return []
    modeled = _modeled_ids()
    gathered = _gathered_ids()
    out = []
    for q in c["queue"]:
        if q["id"] in modeled:
            continue
        row = dict(q)
        row["gathered"] = q["id"] in gathered
        out.append(row)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# Gather-ahead monitor (the machine side of the hourly loop)
# ---------------------------------------------------------------------------
def _bump(failures: dict, id_: str, err: str) -> None:
    cur = failures.get(id_) or {}
    failures[id_] = {"count": int(cur.get("count", 0)) + 1,
                     "last": str(err)[:200], "at": _now()}


def gather_batch(n: int = 10,
                 backlog_cap: int = GATHER_BACKLOG_CAP) -> dict:
    """Gather raw material for the next N unmodeled targets (campaign
    order). Stays ``backlog_cap`` ahead of the AI frontier at most; a
    target failing FAIL_MAX times is parked, not retried forever."""
    from . import gather as mg
    from ..report import resolve_snapshot
    c = load_campaign()
    if c is None:
        return {"error": "no campaign — run `model campaign init` first"}
    try:
        snap_dir = resolve_snapshot(None)
    except FileNotFoundError as exc:
        return {"error": f"no snapshot for gather: {exc}"}
    modeled = _modeled_ids()
    gathered = _gathered_ids()
    backlog = len(gathered - modeled)
    failures = c.get("failures") or {}
    targets = []
    for q in c["queue"]:
        if len(targets) >= n or backlog + len(targets) >= backlog_cap:
            break
        i = q["id"]
        if i in modeled or i in gathered:
            continue
        if failures.get(i, {}).get("count", 0) >= FAIL_MAX:
            continue
        targets.append(q)
    results = []
    for q in targets:
        try:
            rep = mg.gather(q["market"], q["code"], snap_dir=snap_dir)
            if rep["gathered"].get("history") is not None:
                failures.pop(q["id"], None)
                results.append({"id": q["id"], "ok": True,
                                "gaps": rep["gaps"]})
            else:
                _bump(failures, q["id"], "history missing after gather")
                results.append({"id": q["id"], "ok": False,
                                "gaps": rep["gaps"]})
        except Exception as exc:
            _bump(failures, q["id"], str(exc))
            results.append({"id": q["id"], "ok": False, "error": str(exc)})
    c["failures"] = failures
    save_campaign(c)
    ok_n = sum(1 for r in results if r["ok"])
    return {"attempted": len(results), "ok": ok_n,
            "failed": len(results) - ok_n,
            "backlog": backlog + ok_n, "backlog_cap": backlog_cap,
            "parked": {k: v for k, v in failures.items()
                       if v.get("count", 0) >= FAIL_MAX},
            "results": results}


# ---------------------------------------------------------------------------
# Hourly monitor (scheduled-task entry point; machine side only)
# ---------------------------------------------------------------------------
MONITOR_LOG_NAME = "_monitor.log"
MONITOR_TASK_NAME = "ValueGenieCampaignMonitor"   # schtasks /TN name


def monitor_log_path() -> Path:
    return store.models_dir() / MONITOR_LOG_NAME


def _log_append(lines: list) -> None:
    p = monitor_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _retire_scheduled_task() -> bool:
    """The campaign's `end the automation` clause: when every target is
    modeled the monitor deletes its own scheduled task. Deleting a
    running task stops future runs only — the in-flight pass finishes."""
    import subprocess
    try:
        r = subprocess.run(
            ["schtasks", "/Delete", "/TN", MONITOR_TASK_NAME, "/F"],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def monitor_pass(gather_n: int = 20, retire_task: bool = True) -> dict:
    """One unattended hourly pass: top up the gather backlog (backpressure
    capped, fail-3 park), append a progress record to models/_monitor.log,
    and retire the scheduled task when every target is modeled. Machine
    side only — it never writes model.json (red line, skills/19)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if load_campaign() is None:
        lines = [f"[{ts}] monitor: no campaign under models/ — run "
                 f"`model campaign init`; pass skipped"]
        _log_append(lines)
        return {"ok": False, "error": "no campaign", "complete": False,
                "retired": False, "log": lines[0]}
    rep = gather_batch(gather_n)
    p = progress()
    tiers = {t["tier"]: t for t in p["tiers"]}
    lines = [
        f"[{ts}] monitor: modeled {p['modeled']}/{p['queue_total']} "
        f"({p['modeled_pct']}%) | ready {p['ready']}/{GATHER_BACKLOG_CAP} "
        f"| t1 {tiers[1]['modeled']}/{tiers[1]['total']} "
        f"t2 {tiers[2]['modeled']}/{tiers[2]['total']} "
        f"t3 {tiers[3]['modeled']}/{tiers[3]['total']}"
        + (f" | next {p['next'][0]}" if p.get("next") else " | queue clear"),
    ]
    if "error" in rep:
        lines.append(f"  gather error: {rep['error']}")
    for r in rep.get("results") or []:
        if not r["ok"]:
            err = r.get("error") or "; ".join(r.get("gaps") or [])
            lines.append(f"  gather FAIL {r['id']}: {err}")
    if rep.get("parked"):
        lines.append(f"  parked (failed x{FAIL_MAX}): "
                     f"{', '.join(list(rep['parked'])[:8])}")
    complete = bool(p["queue_total"]) and p["modeled"] >= p["queue_total"]
    retired = False
    if complete:
        lines.append(f"[{ts}] CAMPAIGN COMPLETE — {p['queue_total']}/"
                     f"{p['queue_total']} targets modeled; retiring the "
                     f"hourly monitor (scheduled task removed)")
        if retire_task:
            retired = _retire_scheduled_task()
    _log_append(lines)
    return {"ok": "error" not in rep, "complete": complete,
            "retired": retired, "gather": rep, "progress": p,
            "log": "\n".join(lines)}
