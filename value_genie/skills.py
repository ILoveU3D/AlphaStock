"""Skill store: parse, validate and evolve playbooks under skills/.

A skill file is a YAML-subset frontmatter block plus a markdown body:

    ---
    id: single-stock-analysis
    title: Single Stock Analysis
    order: 1
    triggers:
      - "你怎么看待X"
    commands:
      - ask
    version: 1
    updated_at: 2026-09-01T12:00:00
    ---
    # Playbook
    ...
    ## Field Notes
    - [2026-09-01 14:32] (ai) lesson text

The frontmatter subset (scalars + string lists) is parsed with a small
built-in parser, keeping the toolkit free of non-pandas dependencies so
any AI environment can run it without installing anything.

Evolution contract:
- agents append one-line lessons via append_note() (author "ai");
- humans rewrite bodies/triggers via save_skill()/edit_skill()
  (author "human") or the Streamlit Skills Manager;
- every overwrite bumps the version, timestamps the file and keeps a
  backup under skills/.backup/<file-stem>/ (last 10 versions).
"""

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

NOTE_RE = re.compile(r"^- \[([^\]]+)\] \((ai|human)\) (.+)$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REQUIRED = ("id", "title", "triggers", "commands")
BACKUP_KEEP = 10


class SkillFormatError(ValueError):
    """A skill file cannot be parsed or fails validation."""


@dataclass
class Skill:
    id: str
    title: str
    triggers: list
    commands: list
    version: int = 1
    order: int = 99
    updated_at: str = ""
    body: str = ""
    path: Path | None = None


# ---------------------------------------------------------------------------
# Frontmatter mini-parser (scalars + string lists only)
# ---------------------------------------------------------------------------
def _parse_scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text: str) -> tuple:
    """Split '---\\n<meta>\\n---\\n<body>'; raise SkillFormatError."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, re.DOTALL)
    if not m:
        raise SkillFormatError("missing frontmatter block")
    meta: dict = {}
    current_list = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        km = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if km:
            key, value = km.group(1), km.group(2).strip()
            if value == "":
                meta[key] = []
                current_list = key
            else:
                meta[key] = _parse_scalar(value)
                current_list = None
        elif line.strip().startswith("- ") and current_list:
            meta[current_list].append(_parse_scalar(line.strip()[2:]))
        else:
            raise SkillFormatError(f"unparsable frontmatter line: {line!r}")
    return meta, m.group(2)


def _fmt_scalar(v) -> str:
    v = str(v)
    if v == "" or re.search(r"[:#\"\n]|^\s|\s$", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def parse_skill(text: str, path: Path | None = None) -> Skill:
    """Validate and build a Skill from file text."""
    meta, body = parse_frontmatter(text)
    missing = [k for k in REQUIRED
               if k not in meta or meta[k] in ("", [], None)]
    if missing:
        raise SkillFormatError(
            "missing required field(s): " + ", ".join(missing))
    sid = str(meta["id"])
    if not SLUG_RE.match(sid):
        raise SkillFormatError(f"bad id {sid!r}: lowercase slug expected")
    if path is not None and path.stem != sid \
            and not path.stem.endswith("-" + sid):
        raise SkillFormatError(
            f"id {sid!r} does not match filename {path.name!r}")
    try:
        version = int(meta.get("version", 1))
        order = int(meta.get("order", 99))
    except (TypeError, ValueError) as exc:
        raise SkillFormatError(f"version/order must be integers: {exc}") \
            from None
    return Skill(
        id=sid, title=str(meta["title"]),
        triggers=[str(t) for t in meta["triggers"]],
        commands=[str(c) for c in meta["commands"]],
        version=version, order=order,
        updated_at=str(meta.get("updated_at", "")),
        body=body.rstrip() + "\n", path=path)


def render_skill(s: Skill) -> str:
    """Serialize a Skill back to file text (roundtrip-safe)."""
    lines = ["---",
             f"id: {s.id}",
             f"title: {_fmt_scalar(s.title)}",
             f"order: {s.order}",
             "triggers:"]
    lines += [f"  - {_fmt_scalar(t)}" for t in s.triggers]
    lines.append("commands:")
    lines += [f"  - {_fmt_scalar(c)}" for c in s.commands]
    lines += [f"version: {s.version}",
              f"updated_at: {s.updated_at or _now()}",
              "---", ""]
    return "\n".join(lines) + "\n" + s.body.rstrip() + "\n"


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------
def load_skills(skills_dir) -> tuple:
    """(skills, errors): parsed skills sorted by order; error strings."""
    skills, errors = [], []
    d = Path(skills_dir)
    if not d.is_dir():
        return skills, errors
    for p in sorted(d.glob("*.md")):
        try:
            skills.append(parse_skill(p.read_text(encoding="utf-8"), p))
        except (SkillFormatError, OSError) as exc:
            errors.append(f"{p.name}: {exc}")
    skills.sort(key=lambda s: (s.order, s.id))
    return skills, errors


def find_skill(skills_dir, key: str) -> Skill:
    """Look up by id or filename stem; raise with available ids."""
    skills, errors = load_skills(skills_dir)
    for s in skills:
        if s.id == key or (s.path and s.path.stem == key):
            return s
    hint = ", ".join(s.id for s in skills) or "none found"
    extra = f"; load errors: {'; '.join(errors)}" if errors else ""
    raise SkillFormatError(f"unknown skill {key!r}; available: {hint}{extra}")


def field_notes(s: Skill) -> list:
    """[(timestamp, author, text)] parsed from the Field Notes section."""
    out, in_section = [], False
    for line in s.body.splitlines():
        if re.match(r"\s*##\s+Field Notes\s*$", line, re.I):
            in_section = True
            continue
        if in_section:
            m = NOTE_RE.match(line.strip())
            if m:
                out.append((m.group(1), m.group(2), m.group(3)))
    return out


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _note_line(note: tuple) -> str:
    return f"- [{note[0]}] ({note[1]}) {note[2]}"


def _append_note_line(body: str, note_line: str) -> str:
    if re.search(r"(?m)^##\s+Field Notes\s*$", body):
        return body.rstrip() + "\n" + note_line + "\n"
    return body.rstrip() + "\n\n## Field Notes\n" + note_line + "\n"


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _backup(path: Path) -> None:
    bdir = path.parent / ".backup" / path.stem
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.copy2(path, bdir / f"{stamp}.md")
    for old in sorted(bdir.glob("*.md"))[:-BACKUP_KEEP]:
        old.unlink()


def _persist(skills_dir, s: Skill, bump: bool = True) -> Path:
    """Backup, bump version, validate roundtrip, write atomically."""
    path = s.path or Path(skills_dir) / f"{s.order:02d}-{s.id}.md"
    if bump:
        s.version += 1
    s.updated_at = _now()
    text = render_skill(s)
    parse_skill(text, path)      # roundtrip validation before writing
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _backup(path)
    _write_atomic(path, text)
    s.path = path
    return path


def save_skill(skills_dir, skill: Skill, author: str = "human") -> Path:
    """Rewrite a whole skill file. Humans only (agents use append_note)."""
    if author != "human":
        raise SkillFormatError(
            "skill rewrites are human-only; agents use append_note")
    return _persist(skills_dir, skill)


def append_note(skills_dir, skill_id: str, text: str,
                author: str = "ai") -> Skill:
    """Append a one-line timestamped lesson to Field Notes."""
    s = find_skill(skills_dir, skill_id)
    text = " ".join(str(text).splitlines()).strip()
    if not text:
        raise SkillFormatError("note text is empty")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    s.body = _append_note_line(s.body, f"- [{stamp}] ({author}) {text}")
    _persist(skills_dir, s)
    return s


def edit_skill(skills_dir, skill_id: str, add_triggers=None,
               remove_triggers=None, body=None,
               author: str = "human") -> Skill:
    """Structured edits: triggers and (for humans) the playbook body."""
    if author != "human":
        raise SkillFormatError(
            "skill edits are human-only; agents use append_note")
    s = find_skill(skills_dir, skill_id)
    for t in add_triggers or []:
        if t not in s.triggers:
            s.triggers.append(t)
    for t in remove_triggers or []:
        s.triggers = [x for x in s.triggers if x != t]
    if body is not None:
        s.body = body
    if not s.triggers:
        raise SkillFormatError("skill must keep at least one trigger")
    _persist(skills_dir, s)
    return s


def promote_note(skills_dir, skill_id: str, index: int) -> Skill:
    """Move field note #index into the playbook body; drop the note."""
    s = find_skill(skills_dir, skill_id)
    notes = field_notes(s)
    if not 0 <= index < len(notes):
        raise SkillFormatError(f"no field note #{index}")
    note = notes[index]
    marker = _note_line(note)
    out, inserted = [], False
    for line in s.body.splitlines():
        if not inserted and re.match(r"\s*##\s+Field Notes\s*$", line, re.I):
            out.append(f"- {note[2]}  "
                       f"(promoted from a {note[1]} field note, {note[0]})")
            out.append("")
            out.append(line)     # keep the section header for the rest
            inserted = True
        elif inserted and line.strip() == marker:
            continue    # drop the promoted note line
        else:
            out.append(line)
    s.body = "\n".join(out) + "\n"
    _persist(skills_dir, s)
    return s


def delete_note(skills_dir, skill_id: str, index: int) -> Skill:
    """Remove field note #index (noise cleanup)."""
    s = find_skill(skills_dir, skill_id)
    notes = field_notes(s)
    if not 0 <= index < len(notes):
        raise SkillFormatError(f"no field note #{index}")
    marker = _note_line(notes[index])
    s.body = "\n".join(line for line in s.body.splitlines()
                       if line.strip() != marker) + "\n"
    _persist(skills_dir, s)
    return s
