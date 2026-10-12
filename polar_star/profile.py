"""Company profiles: AI-distilled business/culture assessments (Phase 5).

Layout (user mandate 2026-09-29: company data stays LOCAL, never pushed):

- raw:        ``data/profiles/raw/<market>/<code>.json`` — fetched source
  text (company profile / main business / meta), regenerable, cleanable.
- assessment: ``profiles/<market>/<code>.json`` — the AI distillation
  (scores + written arguments), local-persistent, UNTRACKED via
  .gitignore. The distillation is the asset; the raw is its evidence.

Schema is stable by design (source / raw_hash / scores / argument text)
so the directory can later be packaged into a portable dataset.

Closed loop (D3 hook): the AI reads intel (earnings digest /
announcements / news) plus the raw profile text, writes the distillation
via ``profile assess``, and ``apply_distilled_culture`` feeds the
culture score into the three-core ranking — culture scores only exist
when a real distillation does; everything else stays veto-only.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .users import normalize_code

SCHEMA_VERSION = 1

# marker written into core_gaps when a distillation supplies the culture
# core (replaces cores.CULTURE_UNSCORED for that row)
CULTURE_DISTILLED = "culture distilled (profile)"


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Paths & persistence (atomic writes; same contract as users.py/thesis.py)
# ---------------------------------------------------------------------------
def profiles_dir() -> Path:
    return Path(config.PROFILES_DIR)


def raw_dir() -> Path:
    return Path(config.PROFILE_RAW_DIR)


def raw_path(market: str, code: str) -> Path:
    code = normalize_code(market, code)
    return raw_dir() / market.lower() / f"{code}.json"


def assessment_path(market: str, code: str) -> Path:
    code = normalize_code(market, code)
    return profiles_dir() / market.lower() / f"{code}.json"


def content_hash(*texts: str) -> str:
    """sha1[:12] over the content-bearing fields; bump detection only."""
    h = hashlib.sha1()
    for t in texts:
        h.update((t or "").encode("utf-8"))
    return h.hexdigest()[:12]


def _load_json(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt {what} file {path}: {exc}") from None
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(
            f"corrupt {what} file {path}: top level must be an object "
            f"with an 'id'")
    return data


def load_raw(market: str, code: str) -> dict | None:
    p = raw_path(market, code)
    return _load_json(p, "profile raw") if p.exists() else None


def load_assessment(market: str, code: str) -> dict | None:
    p = assessment_path(market, code)
    return _load_json(p, "profile assessment") if p.exists() else None


def new_raw(market: str, code: str, name: str = "", source: str = "",
            source_url: str = "", summary: str = "",
            main_business: str = "", vision: str = "",
            meta: dict | None = None) -> dict:
    """Build a raw record (content_hash computed from the text fields)."""
    code = normalize_code(market, code)
    return {
        "id": f"{market}:{code}", "market": market, "code": code,
        "name": name, "fetched_at": _now(),
        "source": source, "source_url": source_url,
        "summary": summary or "", "main_business": main_business or "",
        "vision": vision or "", "meta": dict(meta or {}),
        "content_hash": content_hash(summary, main_business, vision),
    }


def save_raw(raw: dict) -> Path:
    from .atomic import atomic_write_text
    p = raw_path(raw["market"], raw["code"])
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(raw, ensure_ascii=False, indent=2))
    return p


def save_assessment(assessment: dict) -> Path:
    from .atomic import atomic_write_text
    p = assessment_path(assessment["market"], assessment["code"])
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(assessment, ensure_ascii=False,
                                    indent=2))
    return p


# ---------------------------------------------------------------------------
# Assessment (the AI's written distillation — the only writer is `assess`)
# ---------------------------------------------------------------------------
def _check_score(value, label: str) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number, got {value!r}")
    if not (0.0 <= v <= 100.0):
        raise ValueError(f"{label} must be in [0, 100], got {value!r}")
    return v


def assess(market: str, code: str, name: str = "",
           business_score=None, culture_score=None,
           moat_type: str = "", machine_lifecycle: str = "",
           founder_led=None, benfen: list | None = None,
           business_arg: str = "", culture_arg: str = "",
           dcf_arg: str = "", verdict: str = "",
           agent: str | None = None) -> dict:
    """Write the AI's distillation for one company.

    At least one of business/culture score is required (an assessment
    without any score is just notes — keep those in the analysis prose).
    When a raw file exists the assessment pins its hash/fetch time, so a
    later re-fetch with changed content marks the distillation stale.
    """
    b = _check_score(business_score, "business_score")
    c = _check_score(culture_score, "culture_score")
    if b is None and c is None:
        raise ValueError(
            "at least one of --business-score / --culture-score is "
            "required (scoreless notes belong in the analysis prose)")
    code = normalize_code(market, code)
    raw = load_raw(market, code)
    assessment = {
        "id": f"{market}:{code}", "market": market, "code": code,
        "name": name or (raw or {}).get("name", ""),
        "version": SCHEMA_VERSION,
        "assessed_at": _now(),
        "agent": agent,
        "raw_hash": (raw or {}).get("content_hash"),
        "raw_fetched_at": (raw or {}).get("fetched_at"),
        "business": {
            "score": b, "moat_type": moat_type or "",
            "machine_lifecycle": machine_lifecycle or "",
            "argument": business_arg or "",
        },
        "culture": {
            "score": c, "founder_led": founder_led,
            "benfen_evidence": list(benfen or []),
            "argument": culture_arg or "",
        },
        "dcf": {"argument": dcf_arg or ""},
        "verdict": verdict or "",
    }
    save_assessment(assessment)
    return assessment


# ---------------------------------------------------------------------------
# Freshness & the culture-core hook (D3)
# ---------------------------------------------------------------------------
def is_stale(assessment: dict, raw: dict | None) -> bool:
    """A distillation is stale when the raw it pinned has since changed
    (content_hash mismatch). Missing raw cannot prove staleness."""
    if not assessment or not raw:
        return False
    pinned = assessment.get("raw_hash")
    return bool(pinned) and pinned != raw.get("content_hash")


def list_assessments() -> list[dict]:
    """All assessments (schema-drift tolerant: corrupt files are skipped
    with a stderr note, not fatal)."""
    import sys
    out = []
    root = profiles_dir()
    if not root.exists():
        return out
    for p in sorted(root.glob("*/*.json")):
        try:
            a = _load_json(p, "profile assessment")
        except ValueError as exc:
            print(f"    [warn] {exc}", file=sys.stderr)
            continue
        a["raw_stale"] = is_stale(a, load_raw(a["market"], a["code"]))
        out.append(a)
    return out


def load_culture_scores(include_stale: bool = False) -> dict:
    """{'A:600900': 72.0, ...} — distilled culture scores only; stale
    distillation excluded by default (its evidence base changed)."""
    scores = {}
    for a in list_assessments():
        if a.get("raw_stale") and not include_stale:
            continue
        c = (a.get("culture") or {}).get("score")
        if c is None:
            continue
        scores[a["id"]] = float(c)
    return scores


def apply_distilled_culture(df: pd.DataFrame,
                            scores: dict | None = None) -> tuple:
    """Overlay distilled culture scores onto a scored frame (D3 hook).

    Rows WITH a distillation get ``core_culture`` = the distilled score,
    ``core_score`` recomputed as the skipna mean of the three cores, and
    the unscored-culture gap line replaced by CULTURE_DISTILLED.  Rows
    without one are untouched (culture stays veto-only there).
    Returns (frame, overlaid_count). Pure display-layer transform — the
    stored snapshot is not modified.
    """
    if scores is None:
        scores = load_culture_scores()
    if not scores or "market" not in df.columns \
            or "code" not in df.columns:
        return df, 0
    out = df.copy()
    ids = out["market"].astype(str) + ":" + out["code"].astype(str)
    mapped = pd.to_numeric(ids.map(scores), errors="coerce")
    has = mapped.notna()
    n = int(has.sum())
    if n == 0:
        return out, 0
    out.loc[has, "core_culture"] = mapped[has]
    cols = [c for c in ("core_business", "core_culture", "core_dcf")
            if c in out.columns]
    out["core_score"] = out[cols].mean(axis=1, skipna=True)

    if "core_gaps" in out.columns:
        from .strategy.cores import CULTURE_UNSCORED

        def _fix(g):
            if not isinstance(g, str) or not g:
                return g
            parts = [p for p in g.split("; ")
                     if p and p != CULTURE_UNSCORED]
            parts.append(CULTURE_DISTILLED)
            return "; ".join(parts)
        out.loc[has, "core_gaps"] = out.loc[has, "core_gaps"].map(_fix)
    return out, n


# ---------------------------------------------------------------------------
# Legacy migration (_redesign_keep_profiles single-file layout -> split)
# ---------------------------------------------------------------------------
def import_legacy(src_dir) -> dict:
    """Split-migrate legacy single-file profiles (raw + assessment in one
    JSON) into the Phase 5 layout.  Files without an assessed score are
    imported as raw-only.  Returns counts."""
    src = Path(src_dir)
    counts = {"raw": 0, "assessments": 0, "skipped": 0}
    for p in sorted(src.glob("*/*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            counts["skipped"] += 1
            continue
        if not isinstance(data, dict) or not data.get("market"):
            counts["skipped"] += 1
            continue
        market, code = data["market"], data["code"]
        r = data.get("raw") or {}
        if r:
            raw = new_raw(market, code, name=data.get("name", ""),
                          source=r.get("source", ""),
                          source_url=r.get("source_url", ""),
                          summary=r.get("summary", ""),
                          main_business=r.get("main_business", ""),
                          vision=r.get("vision", ""),
                          meta=r.get("meta") or {})
            raw["fetched_at"] = r.get("fetched_at") or raw["fetched_at"]
            raw["content_hash"] = (r.get("content_hash")
                                   or raw["content_hash"])
            save_raw(raw)
            counts["raw"] += 1
        a = data.get("assessment") or {}
        biz, cul = a.get("business") or {}, a.get("culture") or {}
        if biz.get("score") is None and cul.get("score") is None:
            continue
        assessment = {
            "id": f"{market}:{normalize_code(market, code)}",
            "market": market,
            "code": normalize_code(market, code),
            "name": data.get("name", ""),
            "version": SCHEMA_VERSION,
            "assessed_at": a.get("assessed_at") or _now(),
            "agent": a.get("agent"),
            "raw_hash": a.get("raw_hash"),
            "raw_fetched_at": a.get("raw_fetched_at"),
            "business": {
                "score": biz.get("score"),
                "moat_type": biz.get("moat_type", ""),
                "machine_lifecycle": biz.get("machine_lifecycle", ""),
                "argument": biz.get("argument", ""),
            },
            "culture": {
                "score": cul.get("score"),
                "founder_led": cul.get("founder_led"),
                "benfen_evidence": list(cul.get("benfen_evidence") or []),
                "argument": cul.get("argument", ""),
            },
            "dcf": {"argument": (a.get("dcf") or {}).get("argument", "")},
            "verdict": a.get("verdict", ""),
        }
        save_assessment(assessment)
        counts["assessments"] += 1
    return counts
