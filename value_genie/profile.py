"""Company profile registry: the three-core knowledge base.

Origin (user mandate 2026-09-29): business model, corporate culture and
future vision are the core references for stock selection — they must
live locally, fetched once and updated incrementally, instead of being
re-derived from quantitative proxies forever.  The three-core redesign
(commit 4c796ff) made business/culture/dcf the only ranking keys; this
registry supplies the *textual evidence* those cores are argued from.

Two zones, strictly separated:

- ``raw`` — source text fetched by ``fetch/profiles.py`` (company
  summary / main business / vision + governance meta).  Fetchers write
  only this zone; the AI never edits it.
- ``assessment`` — the AI's distilled judgment (per-core score 0-100 on
  the CORE_ANCHORS scale + written argument), written only via the
  ``profile assess`` CLI.  ``assessment.raw_fetched_at`` records which
  raw version it was distilled from; when raw is re-fetched and the
  content hash changes, the assessment goes *stale* — cores blending
  drops it and the L3 review is told to re-assess.

Files live under ``profiles/<market>/<code>.json`` (top-level,
git-tracked — never inside the cleanable ``data/`` tree), one file per
company, atomic writes; same persistence contract as ``thesis.py``.
"""

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from . import config
from .atomic import atomic_write_text
from .users import normalize_code

PROFILE_ID_RE = re.compile(r"^(A|HK|US):.+$")
_MARKET_DIRS = {"A": "a", "HK": "hk", "US": "us"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ProfileRaw:
    """Source text zone — written only by fetchers."""
    fetched_at: str = ""
    source: str = ""
    source_url: str = ""
    summary: str = ""          # 公司简介 / business description
    main_business: str = ""    # 主营业务 / main business
    vision: str = ""           # future vision (Phase 2 sources)
    meta: dict = field(default_factory=dict)   # chairman, founded, ...
    content_hash: str = ""     # sha1(summary+main_business+vision)[:12]


@dataclass
class ProfileAssessment:
    """AI-distilled zone — written only via `profile assess`.

    Scores are 0-100 absolute (CORE_ANCHORS scale); None = not
    assessed.  ``raw_hash`` links the assessment to the raw content it
    was distilled from (staleness detection)."""
    assessed_at: str | None = None
    raw_fetched_at: str | None = None   # informational only
    raw_hash: str | None = None         # content_hash at assess time;
                                        # staleness key (collision-free)
    agent: str | None = None
    business: dict = field(default_factory=dict)
    # {score, moat_type, machine_lifecycle, argument}
    culture: dict = field(default_factory=dict)
    # {score, founder_led, benfen_evidence[], argument}
    dcf: dict = field(default_factory=dict)      # {argument}
    verdict: str = ""


@dataclass
class Profile:
    id: str                    # "A:600900" / "HK:00998" / "US:MU"
    market: str
    code: str                  # master.csv form
    name: str = ""
    version: int = 0
    created_at: str = ""
    updated_at: str = ""
    raw: ProfileRaw = field(default_factory=ProfileRaw)
    assessment: ProfileAssessment = field(
        default_factory=ProfileAssessment)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def content_hash(summary: str, main_business: str, vision: str) -> str:
    h = hashlib.sha1("\n".join(
        [summary or "", main_business or "", vision or ""]
    ).encode("utf-8"))
    return h.hexdigest()[:12]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def profiles_dir() -> Path:
    return Path(config.PROFILES_DIR)


def profile_path(market: str, code: str) -> Path:
    market = str(market).strip().upper()
    if market not in _MARKET_DIRS:
        raise ValueError(
            f"bad market {market!r}; expected one of "
            f"{', '.join(_MARKET_DIRS)}")
    code = normalize_code(market, code)
    if not code:
        raise ValueError("empty code")
    return profiles_dir() / _MARKET_DIRS[market] / f"{code}.json"


def _load_zone(cls, data, path, zone):
    """Schema-drift tolerant zone load: unknown fields dropped with a
    stderr warning; non-dict zone raises ValueError."""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError(
            f"corrupt profile file {path}: {zone!r} must be an object")
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        print(f"[WARN] {path}: ignoring unknown {zone} fields "
              f"{sorted(unknown)}", file=sys.stderr)
    return cls(**{k: v for k, v in data.items() if k in known})


def load_profile(market: str, code: str) -> Profile:
    """Load one company profile; FileNotFoundError when absent,
    ValueError on structurally broken files."""
    path = profile_path(market, code)
    if not path.exists():
        raise FileNotFoundError(
            f"no profile for {market}/{normalize_code(market, code)}; "
            f"fetch one with `python -m value_genie profile fetch "
            f"{market}:{normalize_code(market, code)}`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt profile file {path}: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(
            f"corrupt profile file {path}: top level must be an object")
    if not data.get("id"):
        raise ValueError(f"corrupt profile file {path}: missing 'id'")
    raw = _load_zone(ProfileRaw, data.get("raw"), path, "raw")
    assess = _load_zone(ProfileAssessment, data.get("assessment"),
                        path, "assessment")
    known = {f.name for f in fields(Profile)} - {"raw", "assessment"}
    unknown = set(data) - known - {"raw", "assessment"}
    if unknown:
        print(f"[WARN] {path}: ignoring unknown profile fields "
              f"{sorted(unknown)}", file=sys.stderr)
    return Profile(
        **{k: v for k, v in data.items() if k in known},
        raw=raw, assessment=assess)


def save_profile(p: Profile) -> Path:
    """Atomic write; bumps version + updated_at."""
    path = profile_path(p.market, p.code)
    path.parent.mkdir(parents=True, exist_ok=True)
    p.version = int(p.version or 0) + 1
    p.updated_at = _now()
    if not p.created_at:
        p.created_at = p.updated_at
    atomic_write_text(path, json.dumps(asdict(p), ensure_ascii=False,
                                       indent=2))
    return path


def list_profiles(market: str | None = None) -> list:
    """All profiles (optionally one market), sorted by (market, code);
    unreadable files skipped with a warning."""
    d = profiles_dir()
    out = []
    markets = [market.upper()] if market else list(_MARKET_DIRS)
    for m in markets:
        sub = d / _MARKET_DIRS.get(m, m.lower())
        if not sub.is_dir():
            continue
        for path in sorted(sub.glob("*.json")):
            try:
                out.append(load_profile(m, path.stem))
            except (ValueError, OSError) as exc:
                print(f"[WARN] skipping unreadable profile file: {exc}",
                      file=sys.stderr)
    return out


def find_profile(stock: str) -> Profile:
    """Resolve chain entry: any name/code/ticker form -> Profile."""
    from . import resolve as rz

    matches = rz.resolve(stock)
    if not matches:
        raise ValueError(f"cannot resolve {stock!r} to a listed company")
    m = matches[0]
    try:
        return load_profile(m.market, m.code)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"{m.name} ({m.market}/{m.code}) has no profile yet; "
            f"fetch one with `python -m value_genie profile fetch "
            f"{stock}`") from None


# ---------------------------------------------------------------------------
# Freshness + zone writes
# ---------------------------------------------------------------------------
def raw_is_fresh(p: Profile, today: datetime | None = None) -> bool:
    """Raw zone reuse window (config.PROFILE_FRESH_DAYS)."""
    if not p.raw.fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(p.raw.fetched_at)
    except ValueError:
        return False
    return (today or datetime.now()) - fetched <= timedelta(
        days=config.PROFILE_FRESH_DAYS)


def assessment_is_stale(p: Profile) -> bool:
    """Assessment distilled from different raw content (hash-keyed:
    same-second refetches must not fake validity)."""
    a = p.assessment
    return bool(a.assessed_at) and a.raw_hash != p.raw.content_hash


def set_raw(p: Profile, raw: dict, name: str = "") -> bool:
    """Fetcher write path. Returns True when the content changed (hash
    differs); an unchanged payload only bumps fetched_at, leaving any
    assessment valid."""
    summary = str(raw.get("summary") or "").strip()
    main_business = str(raw.get("main_business") or "").strip()
    vision = str(raw.get("vision") or "").strip()
    new_hash = content_hash(summary, main_business, vision)
    changed = new_hash != p.raw.content_hash
    p.raw = ProfileRaw(
        fetched_at=_now(),
        source=str(raw.get("source") or ""),
        source_url=str(raw.get("source_url") or ""),
        summary=summary, main_business=main_business, vision=vision,
        meta=dict(raw.get("meta") or {}),
        content_hash=new_hash)
    if name and (not p.name or p.name == p.code):
        # empty name, or a code-as-name wart from offline resolution —
        # both yield to a real pool name
        p.name = name
    return changed


def _check_score(value, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not 0 <= value <= 100:
        raise ValueError(
            f"{label} score must be 0-100 (CORE_ANCHORS scale), "
            f"got {value!r}")


def set_assessment(p: Profile, business: dict | None = None,
                   culture: dict | None = None,
                   dcf: dict | None = None,
                   verdict: str | None = None,
                   agent: str = "") -> Profile:
    """AI write path (the `profile assess` CLI). Requires a non-empty
    raw zone — never distill from thin air. Scores 0-100 or None."""
    if not p.raw.fetched_at or not (
            p.raw.summary or p.raw.main_business):
        raise ValueError(
            f"{p.id}: raw zone is empty — fetch source text before "
            f"assessing (`profile fetch {p.id}`)")
    business = dict(business or {})
    culture = dict(culture or {})
    dcf = dict(dcf or {})
    _check_score(business.get("score"), "business")
    _check_score(culture.get("score"), "culture")
    a = p.assessment
    a.assessed_at = _now()
    a.raw_fetched_at = p.raw.fetched_at
    a.raw_hash = p.raw.content_hash
    a.agent = agent or a.agent
    if business:
        a.business = {**a.business, **business}
    if culture:
        a.culture = {**a.culture, **culture}
    if dcf:
        a.dcf = {**a.dcf, **dcf}
    if verdict is not None:
        a.verdict = verdict
    return p


# ---------------------------------------------------------------------------
# Pool + cores bridge
# ---------------------------------------------------------------------------
def pool_members(snap_dir) -> list:
    """(market, code, name) dedup'd from the snapshot's master.csv +
    watchlist.csv — the profile registry's coverage target (candidate
    pool first, growing with the funnel)."""
    snap_dir = Path(snap_dir)
    out: dict = {}
    for fname in ("master.csv", "watchlist.csv"):
        path = snap_dir / fname
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype={"code": str})
        for _, r in df.iterrows():
            market = str(r.get("market") or "").upper()
            if market not in _MARKET_DIRS:
                continue
            code = normalize_code(market, str(r.get("code") or ""))
            if code:
                out[(market, code)] = str(r.get("name") or "")
    return [(m, c, n) for (m, c), n in sorted(out.items())]


def stale_assessment_keys() -> set:
    """{(market, code)} whose assessment exists but was distilled from
    older raw content — cores declares the gap, L3 re-assesses."""
    return {(p.market, p.code) for p in list_profiles()
            if assessment_is_stale(p)}


def load_assessment_frame() -> pd.DataFrame:
    """The only cores-facing view: DataFrame[market, code, a_business,
    a_culture] of assessed AND non-stale profiles. Stale assessments
    are excluded — re-distillation is an L3 duty, not a blend input."""
    rows = []
    for p in list_profiles():
        a = p.assessment
        if not a.assessed_at or assessment_is_stale(p):
            continue
        rows.append({
            "market": p.market, "code": p.code,
            "a_business": (a.business or {}).get("score"),
            "a_culture": (a.culture or {}).get("score")})
    return pd.DataFrame(rows, columns=["market", "code",
                                       "a_business", "a_culture"])
