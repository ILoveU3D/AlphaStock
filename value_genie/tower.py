"""Cognitive tower (认知巴别塔): philosophy bricks under tower/.

A brick is one distilled thought — the atomic unit of the tower:

    ---
    id: dcf-universal-law
    title: DCF 普适法则
    statement: 一切价值皆是未来现金流的折现。
    source: conversation:2026-09-08
    status: axiom
    tags:
      - epistemology
    links:
      - "derives-from:dcf-universal-law"
    version: 1
    created_at: 2026-09-08T00:00:00
    updated_at: 2026-09-18T12:00:00
    ---
    ## 论证
    ...
    ## Field Notes
    - [2026-09-18 14:00] (ai) note text

Storage contract (design doc 2026-09-18):
- flat tower/<id>.md, git-tracked top-level dir (never inside data/);
- the tower has NO floors/hierarchy — the name is only a name; the
  single axiom (DCF universal law) is the final arbiter, not a layer;
- statuses: axiom (unique, seeded) > mission > law > principle >
  hypothesis > observation; refuted bricks are never deleted;
- every status migration requires a reason and is archived as a
  Field Note (thoughts compound, mistakes are assets);
- links form an open graph: derives-from / refines / contradicts /
  applies-to / tension (tension is permanent, never force-resolved).

The generic machinery (frontmatter mini-parser, atomic write,
backups, note-line format) is imported from skills.py — zero new
dependencies, identical roundtrip guarantees.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .skills import (NOTE_RE, _append_note_line, _backup, _fmt_scalar,
                     _now, _write_atomic, parse_frontmatter)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
STATUSES = ("axiom", "mission", "law", "principle",
            "hypothesis", "observation", "refuted")
LINK_TYPES = ("derives-from", "refines", "contradicts",
              "applies-to", "tension")
AXIOM_ID = "dcf-universal-law"
REQUIRED = ("id", "title", "statement", "source", "status")


class TowerFormatError(ValueError):
    """A brick cannot be parsed or fails validation."""


@dataclass
class Brick:
    id: str
    title: str
    statement: str
    source: str
    status: str
    tags: list = field(default_factory=list)
    links: list = field(default_factory=list)   # ["type:target", ...]
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    path: Path | None = None


# ---------------------------------------------------------------------------
# Parse / render
# ---------------------------------------------------------------------------
def parse_brick(text: str, path: Path | None = None) -> Brick:
    """Validate and build a Brick from file text."""
    try:
        meta, body = parse_frontmatter(text)
    except ValueError as exc:
        raise TowerFormatError(str(exc)) from None
    missing = [k for k in REQUIRED
               if k not in meta or meta[k] in ("", [], None)]
    if missing:
        raise TowerFormatError(
            "missing required field(s): " + ", ".join(missing))
    bid = str(meta["id"])
    if not SLUG_RE.match(bid):
        raise TowerFormatError(f"bad id {bid!r}: lowercase slug expected")
    if path is not None and path.stem != bid:
        raise TowerFormatError(
            f"id {bid!r} does not match filename {path.name!r}")
    status = str(meta["status"])
    if status not in STATUSES:
        raise TowerFormatError(
            f"bad status {status!r}; choose from {', '.join(STATUSES)}")
    if status == "axiom" and bid != AXIOM_ID:
        raise TowerFormatError(
            f"axiom is unique and fixed as {AXIOM_ID!r}, got {bid!r}")
    try:
        version = int(meta.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise TowerFormatError(f"version must be an integer: {exc}") \
            from None
    tags = _as_list(meta.get("tags"))
    links = _as_list(meta.get("links"))
    for link in links:
        _check_link_syntax(link)
    return Brick(
        id=bid, title=str(meta["title"]), statement=str(meta["statement"]),
        source=str(meta["source"]), status=status, tags=tags, links=links,
        version=version, created_at=str(meta.get("created_at", "")),
        updated_at=str(meta.get("updated_at", "")),
        body=body.rstrip() + "\n", path=path)


def render_brick(b: Brick) -> str:
    """Serialize a Brick back to file text (roundtrip-safe)."""
    lines = ["---",
             f"id: {b.id}",
             f"title: {_fmt_scalar(b.title)}",
             f"statement: {_fmt_scalar(b.statement)}",
             f"source: {_fmt_scalar(b.source)}",
             f"status: {b.status}"]
    lines.append("tags:")
    lines += [f"  - {_fmt_scalar(t)}" for t in b.tags]
    lines.append("links:")
    lines += [f"  - {_fmt_scalar(l)}" for l in b.links]
    lines += [f"version: {b.version}",
              f"created_at: {b.created_at or _now()}",
              f"updated_at: {b.updated_at or _now()}",
              "---", ""]
    return "\n".join(lines) + "\n" + b.body.rstrip() + "\n"


def _as_list(value) -> list:
    """Normalize a frontmatter field to a string list ("[]"/None -> [])."""
    if value is None or value == "[]" or value == "":
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def _check_link_syntax(link: str) -> None:
    t, sep, target = link.partition(":")
    if not sep or t not in LINK_TYPES or not SLUG_RE.match(target):
        raise TowerFormatError(
            f"bad link {link!r}; expected type:target with type in "
            f"{', '.join(LINK_TYPES)}")


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------
def load_bricks(tower_dir) -> tuple:
    """(bricks, errors): parsed bricks sorted by id; error strings."""
    bricks, errors = [], []
    d = Path(tower_dir)
    if not d.is_dir():
        return bricks, errors
    for p in sorted(d.glob("*.md")):
        try:
            bricks.append(parse_brick(p.read_text(encoding="utf-8"), p))
        except (TowerFormatError, OSError) as exc:
            errors.append(f"{p.name}: {exc}")
    axioms = [b for b in bricks if b.status == "axiom"]
    if len(axioms) > 1:
        errors.append("multiple axiom bricks: "
                      + ", ".join(b.id for b in axioms))
    bricks.sort(key=lambda b: b.id)
    return bricks, errors


def find_brick(tower_dir, key: str) -> Brick:
    """Look up by id or filename stem; raise with available ids."""
    bricks, errors = load_bricks(tower_dir)
    for b in bricks:
        if b.id == key or (b.path and b.path.stem == key):
            return b
    hint = ", ".join(b.id for b in bricks[:40]) or "none found"
    extra = f"; load errors: {'; '.join(errors)}" if errors else ""
    raise TowerFormatError(f"unknown brick {key!r}; available: {hint}{extra}")


def field_notes(b: Brick) -> list:
    """[(timestamp, author, text)] parsed from the Field Notes section."""
    out, in_section = [], False
    for line in b.body.splitlines():
        if re.match(r"\s*##\s+Field Notes\s*$", line, re.I):
            in_section = True
            continue
        if in_section:
            m = NOTE_RE.match(line.strip())
            if m:
                out.append((m.group(1), m.group(2), m.group(3)))
    return out


def save_brick(tower_dir, b: Brick, bump: bool = True) -> Path:
    """Backup, bump version, validate roundtrip, write atomically.

    created_at is set once (first save) and never changed afterwards.
    """
    path = b.path or Path(tower_dir) / f"{b.id}.md"
    if bump:
        b.version += 1
    if not b.created_at:
        b.created_at = _now()
    b.updated_at = _now()
    text = render_brick(b)
    parse_brick(text, path)      # roundtrip validation before writing
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _backup(path)
    _write_atomic(path, text)
    b.path = path
    return path


def _validate_links(links, known_ids) -> None:
    for link in links:
        _check_link_syntax(link)
        target = link.split(":", 1)[1]
        if target not in known_ids:
            raise TowerFormatError(
                f"link target {target!r} not found; available ids: "
                f"{', '.join(sorted(known_ids)[:40])}")


def add_brick(tower_dir, b: Brick) -> Brick:
    """Insert a new brick (duplicate ids / bad links / axiom rejected)."""
    bricks, _ = load_bricks(tower_dir)
    if any(x.id == b.id for x in bricks):
        raise TowerFormatError(f"brick id {b.id!r} already exists")
    if b.status == "axiom":
        raise TowerFormatError(
            "axiom is unique and already seeded "
            f"({AXIOM_ID}); new bricks start at any non-axiom status")
    known = {x.id for x in bricks} | {b.id}
    _validate_links(b.links, known)
    b.version = 0        # first save lands at version 1
    save_brick(tower_dir, b)
    return b


def append_note(tower_dir, brick_id: str, text: str,
                author: str = "ai") -> Brick:
    """Append a one-line timestamped note to Field Notes."""
    b = find_brick(tower_dir, brick_id)
    text = " ".join(str(text).splitlines()).strip()
    if not text:
        raise TowerFormatError("note text is empty")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    b.body = _append_note_line(b.body, f"- [{stamp}] ({author}) {text}")
    save_brick(tower_dir, b)
    return b


def add_link(tower_dir, brick_id: str, link: str) -> Brick:
    """Add one `type:target` link to a brick (syntax + target checked)."""
    _check_link_syntax(link)
    b = find_brick(tower_dir, brick_id)
    bricks, _ = load_bricks(tower_dir)
    target = link.split(":", 1)[1]
    known = {x.id for x in bricks}
    if target not in known:
        raise TowerFormatError(
            f"link target {target!r} not found; available ids: "
            f"{', '.join(sorted(known)[:40])}")
    if link not in b.links:
        b.links.append(link)
        save_brick(tower_dir, b)
    return b


def set_brick(tower_dir, brick_id: str, status=None, reason=None,
              add_tags=None, drop_tags=None, body=None) -> Brick:
    """Status migration (reason mandatory) / tag edits / body rewrite."""
    b = find_brick(tower_dir, brick_id)
    if status is not None and status != b.status:
        if status not in STATUSES:
            raise TowerFormatError(
                f"bad status {status!r}; choose from {', '.join(STATUSES)}")
        if status == "axiom":
            raise TowerFormatError(
                "axiom cannot be granted via set; the single axiom "
                f"({AXIOM_ID}) is established by seed")
        if not (reason or "").strip():
            raise TowerFormatError(
                "status change requires --reason "
                "(promotion rationale / refutation evidence)")
        old = b.status
        b.status = status
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        b.body = _append_note_line(
            b.body,
            f"- [{stamp}] (ai) status: {old} -> {status} — {reason.strip()}")
    for t in add_tags or []:
        if t not in b.tags:
            b.tags.append(t)
    for t in drop_tags or []:
        b.tags = [x for x in b.tags if x != t]
    if body is not None:
        b.body = body
    save_brick(tower_dir, b)
    return b


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def search_bricks(tower_dir, query: str) -> list:
    """Substring match over id/title/statement/tags/body (case-insensitive)."""
    bricks, _ = load_bricks(tower_dir)
    q = str(query).lower()
    out = []
    for b in bricks:
        hay = " ".join([b.id, b.title, b.statement,
                        " ".join(b.tags), " ".join(b.links), b.body])
        if q in hay.lower():
            out.append(b)
    return out


def _age_days(iso: str):
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).days
    except (ValueError, TypeError):
        return None


def tower_stats(tower_dir) -> dict:
    """Honest numbers only: depth, breadth, growth, scars."""
    bricks, errors = load_bricks(tower_dir)
    counts = {s: 0 for s in STATUSES}
    kinds = {"book": 0, "master": 0, "conversation": 0, "ai": 0}
    for b in bricks:
        counts[b.status] = counts.get(b.status, 0) + 1
        kind = b.source.split(":", 1)[0] if ":" in b.source else b.source
        if kind in kinds:
            kinds[kind] += 1
    tension = sum(1 for b in bricks
                  for l in b.links if l.startswith("tension:"))
    notes_total = sum(len(field_notes(b)) for b in bricks)

    def _note_age(ts: str):
        try:
            return (datetime.now()
                    - datetime.strptime(ts, "%Y-%m-%d %H:%M")).days
        except ValueError:
            return None

    recent_notes = sum(
        1 for b in bricks for ts, _, _ in field_notes(b)
        if _note_age(ts) is not None and _note_age(ts) <= 30)
    recent_bricks = sum(
        1 for b in bricks
        if b.created_at and _age_days(b.created_at) is not None
        and _age_days(b.created_at) <= 30)
    ages = [a for a in (_age_days(b.created_at) for b in bricks)
            if a is not None]
    return {
        "total_bricks": len(bricks),
        "by_status": counts,
        "by_kind": kinds,
        "tension_links": tension,
        "total_notes": notes_total,
        "recent_bricks_30d": recent_bricks,
        "recent_notes_30d": recent_notes,
        "tower_age_days": max(ages) if ages else 0,
        "load_errors": len(errors),
        "axiom": [b.id for b in bricks if b.status == "axiom"],
        "mission_titles": [b.title for b in bricks if b.status == "mission"],
        "law_titles": [b.title for b in bricks if b.status == "law"],
        "refuted_titles": [b.title for b in bricks if b.status == "refuted"],
    }
