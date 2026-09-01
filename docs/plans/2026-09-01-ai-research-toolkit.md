# AI-First Research Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the repo into an AI-first financial research toolkit: any AI reads `AGENTS.md`, routes stock questions to `ask` / `compare` / `overview` / `doctor` CLI tools, and evolves playbooks via `skill note` (AI path) and a Streamlit Skills Manager (human path).

**Architecture:** Six new modules (`skills`, `resolve`, `analyze`, `overview`, `doctor` plus `fetch_quotes_by_secids` in quotes) layered on the existing Phase 1 pipeline. Skills are markdown files with a YAML-subset frontmatter parsed by a built-in zero-dependency parser. All prose (AGENTS.md, skills/) is English per project convention; README stays Chinese.

**Tech Stack:** Python 3.10+, pandas, requests (already vendored in `libs/`), stdlib `difflib`/`re`/`json`. No new dependencies.

**Spec:** `docs/specs/2026-09-01-ai-research-toolkit-design.md`

**Sandbox notes (critical):**
- Run tests with: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\<file>.py -q --basetemp=tmp\ptN` (project convention; `-B` avoids pycache write errors).
- Terminals get killed after ~10 min — keep every command short; never chain long runs.
- Console mojibake for Chinese is display-only; verify UTF-8 content by redirecting to a file under `tmp\` and using the Read tool.

---

### Task 1: `value_genie/skills.py` — skill store

**Files:**
- Modify: `value_genie/config.py` (add SKILLS_DIR after OUTPUT_DIR, ~line 14)
- Create: `value_genie/skills.py`
- Test: `tests/test_skills.py`

- [ ] **Step 1: Add SKILLS_DIR to config.py**

In `value_genie/config.py`, after the `OUTPUT_DIR = BASE_DIR / "output"` line:

```python
SKILLS_DIR = BASE_DIR / "skills"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_skills.py`:

```python
"""Tests for value_genie.skills (skill file store)."""

from pathlib import Path

from value_genie import skills as sk

SAMPLE = """---
id: demo-skill
title: Demo Skill
order: 7
triggers:
  - "你怎么看待X"
  - "X值得买吗"
commands:
  - ask
version: 2
updated_at: 2026-09-01T10:00:00
---
# Playbook
step one

## Field Notes
- [2026-09-01 10:30] (ai) smartbox resolves delisted names
- [2026-09-01 11:00] (human) tightened trigger wording
"""


def make_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    (d / "07-demo-skill.md").write_text(SAMPLE, encoding="utf-8")
    return d


class TestParse:
    def test_parses_frontmatter_and_body(self):
        s = sk.parse_skill(SAMPLE)
        assert s.id == "demo-skill"
        assert s.title == "Demo Skill"
        assert s.order == 7
        assert s.version == 2
        assert s.triggers == ["你怎么看待X", "X值得买吗"]
        assert s.commands == ["ask"]
        assert s.body.startswith("# Playbook")
        assert "## Field Notes" in s.body

    def test_missing_required_field_raises(self):
        bad = SAMPLE.replace("title: Demo Skill\n", "")
        try:
            sk.parse_skill(bad)
            assert False, "expected SkillFormatError"
        except sk.SkillFormatError as exc:
            assert "title" in str(exc)

    def test_bad_id_raises(self):
        bad = SAMPLE.replace("id: demo-skill", "id: Demo Skill!")
        try:
            sk.parse_skill(bad)
            assert False, "expected SkillFormatError"
        except sk.SkillFormatError:
            pass

    def test_no_frontmatter_raises(self):
        try:
            sk.parse_skill("# just markdown\n")
            assert False, "expected SkillFormatError"
        except sk.SkillFormatError:
            pass

    def test_render_roundtrip(self):
        s = sk.parse_skill(SAMPLE)
        again = sk.parse_skill(sk.render_skill(s))
        assert again.id == s.id
        assert again.triggers == s.triggers
        assert again.version == s.version
        assert again.body.strip() == s.body.strip()


class TestLoad:
    def test_loads_good_reports_bad(self, tmp_path):
        d = make_dir(tmp_path)
        (d / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
        items, errors = sk.load_skills(d)
        assert [s.id for s in items] == ["demo-skill"]
        assert len(errors) == 1 and "broken.md" in errors[0]

    def test_find_skill_by_id_and_stem(self, tmp_path):
        d = make_dir(tmp_path)
        assert sk.find_skill(d, "demo-skill").id == "demo-skill"
        assert sk.find_skill(d, "07-demo-skill").id == "demo-skill"

    def test_find_skill_unknown_raises(self, tmp_path):
        d = make_dir(tmp_path)
        try:
            sk.find_skill(d, "nope")
            assert False, "expected SkillFormatError"
        except sk.SkillFormatError as exc:
            assert "demo-skill" in str(exc)  # suggests available ids


class TestEvolution:
    def test_append_note_adds_line_and_bumps_version(self, tmp_path):
        d = make_dir(tmp_path)
        s = sk.append_note(d, "demo-skill", "lesson learned here")
        assert s.version == 3
        notes = sk.field_notes(s)
        assert notes[-1][1] == "ai"
        assert "lesson learned here" in notes[-1][2]
        on_disk = sk.parse_skill(
            (d / "07-demo-skill.md").read_text(encoding="utf-8"))
        assert len(sk.field_notes(on_disk)) == 3

    def test_append_note_creates_backup(self, tmp_path):
        d = make_dir(tmp_path)
        sk.append_note(d, "demo-skill", "another lesson")
        assert len(list((d / ".backup" / "07-demo-skill").glob("*.md"))) == 1

    def test_save_skill_human_only(self, tmp_path):
        d = make_dir(tmp_path)
        s = sk.find_skill(d, "demo-skill")
        try:
            sk.save_skill(d, s, author="ai")
            assert False, "expected SkillFormatError"
        except sk.SkillFormatError:
            pass

    def test_save_skill_bumps_version_and_writes_atomically(self, tmp_path):
        d = make_dir(tmp_path)
        s = sk.find_skill(d, "demo-skill")
        s.title = "Renamed Skill"
        path = sk.save_skill(d, s, author="human")
        assert path.name == "07-demo-skill.md"
        assert s.version == 3
        assert not list(d.glob("*.tmp"))
        assert sk.find_skill(d, "demo-skill").title == "Renamed Skill"

    def test_edit_skill_triggers(self, tmp_path):
        d = make_dir(tmp_path)
        s = sk.edit_skill(d, "demo-skill",
                          add_triggers=["X还能买吗"],
                          remove_triggers=["X值得买吗"])
        assert "X还能买吗" in s.triggers
        assert "X值得买吗" not in s.triggers

    def test_edit_skill_rejects_empty_triggers(self, tmp_path):
        d = make_dir(tmp_path)
        try:
            sk.edit_skill(d, "demo-skill",
                          remove_triggers=["你怎么看待X", "X值得买吗"])
            assert False, "expected SkillFormatError"
        except sk.SkillFormatError:
            pass

    def test_promote_note_moves_text_into_body(self, tmp_path):
        d = make_dir(tmp_path)
        s = sk.promote_note(d, "demo-skill", 0)
        assert len(sk.field_notes(s)) == 1                       # removed
        assert "smartbox resolves delisted names" in s.body      # promoted

    def test_delete_note_removes_line(self, tmp_path):
        d = make_dir(tmp_path)
        s = sk.delete_note(d, "demo-skill", 1)
        assert len(sk.field_notes(s)) == 1
        assert sk.field_notes(s)[0][2] == "smartbox resolves delisted names"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_skills.py -q --basetemp=tmp\pt_s1`
Expected: FAIL with `ModuleNotFoundError: No module named 'value_genie.skills'`

- [ ] **Step 4: Implement `value_genie/skills.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_skills.py -q --basetemp=tmp\pt_s2`
Expected: `20 passed`

---

### Task 2: Six skill playbooks + AGENTS.md

**Files:**
- Create: `skills/01-single-stock-analysis.md`
- Create: `skills/02-compare-stocks.md`
- Create: `skills/03-market-overview.md`
- Create: `skills/04-data-ops.md`
- Create: `skills/05-macro-themes.md`
- Create: `skills/06-investment-philosophy.md`
- Create: `AGENTS.md`

- [ ] **Step 1: Write the six skill files**

Create `skills/01-single-stock-analysis.md`:

```markdown
---
id: single-stock-analysis
title: Single Stock Analysis
order: 1
triggers:
  - "你怎么看待X"
  - "What do you think of X"
  - "X值得买吗"
  - "Is X a buy"
commands:
  - ask
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

Answer "what do you think of X" with a verdict first, evidence later.

1. Resolve the name (Chinese, code or ticker all work):
   `python -m value_genie ask 茶百道`
   The command prints the resolved label plus close alternative matches —
   if the resolution looks wrong, retry with a more specific name.
2. Read the brief output: verdict band, live price, three key numbers
   (PE percentile, revenue growth, ROE) and a risk-flag count.
3. Write the answer: lead with the verdict in one sentence, then the key
   numbers. State the data-as-of line verbatim. Do NOT dump the full
   metric table unless asked.
4. When the human asks "why" / "证据" / "reasons", run:
   `python -m value_genie ask 茶百道 --evidence`
   and walk through the metric/percentile table, pillar scores and risk
   flags in plain language.
5. For machine-readable consumption use `--json`.

## Interpretation

- Verdict bands (blended value/growth/quality/safety percentile vs the
  market's gated universe): outstanding >= 85, attractive >= 70,
  reasonable >= 40, unattractive >= 20, poor below that.
- "PE at 12th pctile" means cheaper than 88% of the comparable universe.
- Risk flags are hard observations (leverage > 70%, contracting revenue
  or profit, drawdown beyond -40%, high volatility), not opinions.

## Cautions

- If output says "live quote unavailable", prices come from the last
  snapshot — say so explicitly.
- New listings may have no kline history; momentum metrics show as "-".
- After answering, if you learned something reusable (a resolution
  quirk, a data gap workaround), append a field note:
  `python -m value_genie skill note single-stock-analysis "lesson"`

## Field Notes
```

Create `skills/02-compare-stocks.md`:

```markdown
---
id: compare-stocks
title: Compare Stocks
order: 2
triggers:
  - "X和Y哪个好"
  - "X vs Y"
  - "compare X and Y"
commands:
  - compare
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

1. Run with all names at once (2+ supported):
   `python -m value_genie compare 茶百道 古茗 奈雪的茶`
2. The table shows price, PE with peer percentile, revenue growth, ROE,
   blended composite percentile, verdict and risk count per name.
3. Structure the answer around the printed takeaways: which name is
   cheapest (lowest PE percentile), which grows fastest, which is
   safest — then add the blended rank as the tiebreaker.
4. Cross-market comparisons (A vs HK vs US) are valid: percentiles are
   computed within each market's own universe, so "12th pctile in HK"
   and "15th pctile in US" are comparable statements about relative
   cheapness.
5. If two names resolve to the same stock, drop the duplicate and say so.

## Cautions

- Percentiles need a snapshot; without one the command fails with
  "run fetch first" — run the data-ops skill first.

## Field Notes
```

Create `skills/03-market-overview.md`:

```markdown
---
id: market-overview
title: Market Overview
order: 3
triggers:
  - "现在港股有什么机会"
  - "What looks attractive in market X now"
  - "市场概览"
commands:
  - overview
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

1. Run: `python -m value_genie overview --markets A,HK --top 10`
   (omit --markets for all three).
2. Per market you get: candidate count, median PE/PB/revenue growth,
   breadth (% of candidates above their 52-week midpoint), top sectors
   among the top-50 names, and the top-10 table.
3. Answer pattern: start with the market's valuation level (medians) and
   breadth, then name 2-3 standout stocks from the top table with their
   one-line thesis (cheap + growing + profitable).
4. Snapshot age matters for overviews — quote the snapshot date and run
   the data-ops skill if it is stale.

## Cautions

- The overview ranks only the ~200 candidates per market that passed
  the funnel gates; it is a curated shortlist, not the raw universe.

## Field Notes
```

Create `skills/04-data-ops.md`:

```markdown
---
id: data-ops
title: Data Operations
order: 4
triggers:
  - "数据新鲜吗"
  - "update the data"
  - "why is fetching broken"
commands:
  - doctor
  - fetch
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

Run `doctor` BEFORE answering price-sensitive questions when the last
known snapshot is older than one trading day:

    python -m value_genie doctor

- All PASS → proceed; data is fresh enough.
- WARN on snapshot age or kline lag → tell the human data may be stale,
  offer to refresh, and prefer live-quote commands (`ask`) meanwhile.
- FAIL (no snapshots / ancient data) → run fetch before answering:
  `python -m value_genie fetch` (A+HK+US, ~10 min, incremental).

## Source failure playbook (learned the hard way)

- Eastmoney push2 rate-limits: the client rotates mirror hosts
  (push2delay first) with cooldowns; partial quote pages are kept with
  a warning — check `manifest.json` `failures` for what is missing.
- Tencent klines: legacy fqkline/get returns HTTP 501; the client tries
  newfqkline/get and the proxy.finance.qq.com mirror automatically.
- US fundamentals come from SEC EDGAR frames (annual/quarterly, weeks
  of lag). If US financials are missing entirely, the pipeline SKIPS
  the US market rather than ranking garbage — say so, do not improvise.
- Long fetches can be killed mid-run; re-running resumes and reuses
  everything already saved to today's snapshot directory.

## Field Notes
```

Create `skills/05-macro-themes.md`:

```markdown
---
id: macro-themes
title: Macro Themes (Geopolitics, Gold, Rates)
order: 5
triggers:
  - "地缘政治对市场的影响"
  - "黄金还能买吗"
  - "Fed rate impact"
commands:
  - overview
  - ask
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

Macro questions get a reasoning framework plus toolkit corroboration —
never vibes alone.

## Framework

1. First-order effect: what directly reprices (energy, currencies,
   rate expectations, risk appetite).
2. Second-order effect: who benefits/harms from THAT move (e.g. oil up
   → energy margins up, airlines down; rates up → growth stocks'
   duration hurts, insurers' book yields help).
3. Safe-haven flows: gold / USD / defensives — check positioning and
   momentum, not just the narrative.
4. Base rates: most geopolitical shocks mean-revert within months;
   distinguish repricing of cashflows from repricing of sentiment.

## Toolkit corroboration

- Risk appetite: `overview` — breadth (% above 52w mid) and median
  valuations per market; collapsing breadth = risk-off in progress.
- Defensive rotation: sector mix of the top-50 in each market; watch
  utilities/consumer-staples share rising.
- Single names: `ask X --evidence` → volatility and drawdown_52w
  percentiles show how a name is absorbing the shock.

## Cautions

- The toolkit has no gold/FX/index feeds yet; for those quote the
  human's own sources or well-known data, and mark them as such.
- Separate what the data shows from your macro narrative; if they
  conflict, say so.

## Field Notes
```

Create `skills/06-investment-philosophy.md`:

```markdown
---
id: investment-philosophy
title: Investment Philosophy (House Voice)
order: 6
triggers:
  - "什么是好公司"
  - "价值投资"
  - "how to think about valuation"
commands: []
version: 1
updated_at: 2026-09-01T12:00:00
---
# Playbook

This is the house voice for EVERY answer from this toolkit.

## Core tenets

1. Margin of safety: cheapness is protection against being wrong.
   A great business at a terrible price is a bad stock.
2. Circle of competence: prefer saying "I don't know" over
   extrapolating a story. Data gaps are facts, not annoyances.
3. Moats over momentum: durable ROE and gross margins beat one hot
   year of growth. Check quality percentiles before growth percentiles.
4. Mean reversion is the default; sustained outperformance needs a
   reason you can name.
5. Risk is permanent loss, not volatility — but volatility percentiles
   still tell you how much pain a position can inflict.

## Phrasing rules

- Always give the data-as-of timestamp when citing numbers.
- Distinguish "cheap" (low PE percentile) from "good value" (cheap AND
  profitable AND growing) — the blended verdict encodes the difference.
- Present risk flags as observations, uncertainty as ranges, and never
  fabricate numbers the toolkit did not print.
- No price targets. Verdict bands and percentiles only.

## Field Notes
```

- [ ] **Step 2: Write AGENTS.md**

Create `AGENTS.md`:

```markdown
# AGENTS.md — Value Genie for AI Agents

You are operating **Value Genie**, a value-investment research toolkit
covering A-share, Hong Kong and US equities. This file tells you what
the toolkit can do, when to use what, and how to leave it smarter than
you found it.

## What this repo is

- `python -m value_genie fetch` builds a dated snapshot: full-market
  quotes + financials (Eastmoney / SEC EDGAR), funnel to ~200
  candidates per market, deep klines + HK F10, scored `master.csv`.
- Analysis commands read the latest snapshot (and live quotes where
  noted) — no LLM runs inside the toolkit; you write the prose.
- `streamlit run app.py` is the human-facing dashboard; agents use the
  CLI.

## Freshness contract

- `ask` always pulls the LIVE quote for price/PE/PB; fundamentals and
  percentiles come from the latest snapshot.
- Before any price-sensitive answer, if the snapshot may be older than
  one trading day, run `python -m value_genie doctor` and follow skill
  `data-ops`.
- Never present snapshot-day numbers as "current" — cite the
  data-as-of line the commands print.

## Routing table

| The human asks | Skill | Command |
|---|---|---|
| "你怎么看待X / what do you think of X" | single-stock-analysis | `python -m value_genie ask X` |
| "...but why / 证据" | single-stock-analysis | `python -m value_genie ask X --evidence` |
| "X和Y哪个好 / X vs Y" | compare-stocks | `python -m value_genie compare X Y` |
| "现在港股有什么机会 / what's attractive now" | market-overview | `python -m value_genie overview --markets HK` |
| "数据新鲜吗 / is the data current" | data-ops | `python -m value_genie doctor` |
| Macro / gold / geopolitics | macro-themes | framework + `overview` / `ask --evidence` |
| Philosophy / how to value | investment-philosophy | house voice for every answer |

Playbooks live in `skills/` — read the relevant one before answering.
`python -m value_genie skill list` indexes them.

## Answer shape (hard rules)

1. Verdict first, one sentence. Then key numbers with units and the
   data-as-of line. Evidence tables only when asked.
2. Percentiles are within the stock's own market universe; say "12th
   percentile of the HK gated universe", not "12th percentile globally".
3. Report risk flags verbatim as observations; never soften them.
4. If resolution, data or coverage failed, say exactly what is missing
   — do not improvise numbers.

## Self-refinement protocol (leave the toolkit smarter)

After answering, if you hit a quirk or found a better procedure
(resolution trick, source failure workaround, ambiguity in a skill),
record it in one concrete line:

    python -m value_genie skill note single-stock-analysis "smartbox resolves names missing from snapshot after delistings"

Notes append to the skill's Field Notes; every future agent inherits
them. Humans periodically promote good notes into the playbook body
via the Streamlit Skills Manager. Agents never rewrite bodies —
append-only keeps the system trustworthy.

## Environment

- Python 3.10+; pandas + requests only (`libs/` vendors them if the
  host lacks them: set PYTHONPATH to include `libs/`).
- Tests: `python -B -m pytest tests -q` (each file standalone).
- Data lives in `data/snapshots/YYYYMMDD/`; never edit snapshot files.
```

- [ ] **Step 3: Verify the skill store loads the real files**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -c "from value_genie import skills as sk, config; items, errors = sk.load_skills(config.SKILLS_DIR); print([s.id for s in items]); print(errors)"`
Expected: `['single-stock-analysis', 'compare-stocks', 'market-overview', 'data-ops', 'macro-themes', 'investment-philosophy']` and `[]`

---

### Task 3: `value_genie/resolve.py` — symbol resolution

**Files:**
- Create: `value_genie/resolve.py`
- Test: `tests/test_resolve.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resolve.py`:

```python
"""Tests for value_genie.resolve (no network)."""

import pandas as pd

from value_genie import resolve as rs


class TestParseCodeForm:
    def test_a_share_forms(self):
        assert rs.parse_code_form("600519") == ("A", "600519", "1")
        assert rs.parse_code_form("sh600519") == ("A", "600519", "1")
        assert rs.parse_code_form("600519.SH") == ("A", "600519", "1")
        assert rs.parse_code_form("000001") == ("A", "000001", "0")

    def test_hk_forms(self):
        assert rs.parse_code_form("00700") == ("HK", "00700", "116")
        assert rs.parse_code_form("700") == ("HK", "00700", "116")
        assert rs.parse_code_form("hk00700") == ("HK", "00700", "116")
        assert rs.parse_code_form("02555.HK") == ("HK", "02555", "116")

    def test_us_forms(self):
        assert rs.parse_code_form("AAPL") == ("US", "AAPL", "")
        assert rs.parse_code_form("aapl") == ("US", "AAPL", "")

    def test_names_return_none(self):
        assert rs.parse_code_form("茶百道") is None
        assert rs.parse_code_form("摩尔线程") is None


def frames():
    return {
        "A": pd.DataFrame({
            "code": ["600519", "688795"],
            "name": ["贵州茅台", "摩尔线程"],
            "market_id": ["1", "1"],
        }),
        "HK": pd.DataFrame({
            "code": ["02555", "02150"],
            "name": ["茶百道", "奈雪的茶"],
            "market_id": ["116", "116"],
        }),
        "US": pd.DataFrame({
            "code": ["AAPL"],
            "name": ["Apple Inc"],
            "market_id": ["105"],
        }),
    }


class TestSearchFrames:
    def test_exact_match_scores_highest(self):
        out = rs.search_frames("茶百道", frames())
        assert out and out[0].market == "HK" and out[0].code == "02555"
        assert out[0].score == 100.0

    def test_contains_match(self):
        out = rs.search_frames("茅台", frames())
        assert any(m.code == "600519" for m in out)

    def test_no_match_returns_empty(self):
        assert rs.search_frames("苹果", frames()) == []

    def test_english_contains(self):
        out = rs.search_frames("Apple", frames())
        assert any(m.code == "AAPL" for m in out)


class TestSmartbox:
    def test_parses_suggest_response(self, monkeypatch):
        d = {"QuotationCodeTable": {"Data": [
            {"Code": "02555", "Name": "茶百道", "MktNum": "116"},
            {"Code": "AAPL", "Name": "Apple Inc", "MktNum": "105"},
            {"Code": "600519", "Name": "贵州茅台", "MktNum": "1"},
            {"Code": "XYZ", "Name": "Junk", "MktNum": "999"},
        ]}}
        monkeypatch.setattr(rs.SB, "get_json", lambda *a, **k: d)
        got = {(m.market, m.code) for m in rs.search_smartbox("whatever")}
        assert ("HK", "02555") in got
        assert ("US", "AAPL") in got
        assert ("A", "600519") in got
        assert all(m.market in ("A", "HK", "US") for m in
                   rs.search_smartbox("whatever"))  # unknown market dropped

    def test_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(rs.SB, "get_json", lambda *a, **k: None)
        assert rs.search_smartbox("whatever") == []


class TestResolve:
    def test_snapshot_resolution_no_network(self, tmp_path):
        snap = tmp_path / "20260901"
        snap.mkdir()
        for mk, df in frames().items():
            df.to_csv(snap / f"{mk.lower()}_quotes.csv", index=False)
        out = rs.resolve("茶百道", snapshot_dir=snap, live=False)
        assert out[0].market == "HK" and out[0].code == "02555"
        assert out[0].name == "茶百道"

    def test_code_form_wins_without_snapshot(self):
        out = rs.resolve("600519", snapshot_dir=None, live=False)
        assert out and out[0].market == "A" and out[0].code == "600519"

    def test_dedup_and_name_enrichment(self, tmp_path):
        snap = tmp_path / "20260901"
        snap.mkdir()
        for mk, df in frames().items():
            df.to_csv(snap / f"{mk.lower()}_quotes.csv", index=False)
        out = rs.resolve("02555", snapshot_dir=snap, live=False)
        assert len(out) == 1
        assert out[0].name == "茶百道"    # enriched from snapshot

    def test_smartbox_fallback_without_snapshot(self, monkeypatch):
        d = {"QuotationCodeTable": {"Data": [
            {"Code": "02555", "Name": "茶百道", "MktNum": "116"}]}}
        monkeypatch.setattr(rs.SB, "get_json", lambda *a, **k: d)
        out = rs.resolve("茶百道", snapshot_dir=None, live=True)
        assert out and out[0].code == "02555" and out[0].market_id == "116"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_resolve.py -q --basetemp=tmp\pt_r1`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `value_genie/resolve.py`**

```python
"""Symbol resolution: free text -> market/code/name matches.

Chain: exact code forms (600519 / 02555.HK / AAPL) -> snapshot quote
name search (exact > substring > fuzzy) -> Eastmoney smartbox live
search, which works even with no snapshot on disk.
"""

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config
from .fetch.http import Fetcher

SB = Fetcher({"User-Agent": config.EM_UA}, "SB")
SMARTBOX_URL = "https://searchapi.eastmoney.com/api/suggest/get"
SMARTBOX_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
SMARTBOX_MKT = {"0": "A", "1": "A", "116": "HK",
                "105": "US", "106": "US", "107": "US"}


@dataclass
class Match:
    market: str
    code: str
    name: str
    score: float
    market_id: str = ""

    def label(self) -> str:
        return f"{self.name} ({self.market}/{self.code})"


def parse_code_form(query: str):
    """(market, code, market_id) when the query is a code form, else None.

    market_id is the Eastmoney push2 prefix needed for live quotes
    (A: 1=SH / 0=SZ+BJ, HK: 116; US is exchange-dependent and left
    blank — smartbox or the snapshot fills it in).
    """
    q = query.strip().lower()
    m = re.fullmatch(r"(?:sh|sz|bj)?(\d{6})(?:\.(?:sh|sz|bj))?", q)
    if m:
        code = m.group(1)
        return ("A", code, "1" if code[0] == "6" else "0")
    m = re.fullmatch(r"(?:hk)?(\d{1,5})(?:\.hk)?", q)
    if m:
        return ("HK", m.group(1).zfill(5), "116")
    m = re.fullmatch(r"(?:us)?([a-z]{1,6})", q)
    if m:
        return ("US", query.strip().upper(), "")
    return None


def search_frames(query: str, frames: dict) -> list:
    """Name matches across {market: DataFrame with code/name}."""
    q = query.strip()
    if not q:
        return []
    out = []
    for market, df in frames.items():
        if df is None or df.empty or "name" not in df.columns:
            continue
        names = df["name"].astype(str)
        exact = df[names == q]
        if not exact.empty:
            for _, r in exact.iterrows():
                out.append(Match(market, str(r["code"]), str(r["name"]),
                                 100.0, str(r.get("market_id") or "")))
            continue
        for _, r in df[names.str.contains(re.escape(q), na=False)].iterrows():
            out.append(Match(market, str(r["code"]), str(r["name"]),
                             80.0, str(r.get("market_id") or "")))
        for _, r in df[names.map(lambda n:
                                 difflib.SequenceMatcher(None, n, q).ratio()
                                 >= 0.6)].iterrows():
            ratio = difflib.SequenceMatcher(None, str(r["name"]), q).ratio()
            out.append(Match(market, str(r["code"]), str(r["name"]),
                             round(ratio * 60.0, 1),
                             str(r.get("market_id") or "")))
    out.sort(key=lambda m: -m.score)
    return out


def load_snapshot_frames(snapshot_dir=None) -> dict:
    """{market: quotes DataFrame} from a snapshot dir (latest default)."""
    from .report import resolve_snapshot
    snap = Path(snapshot_dir) if snapshot_dir else resolve_snapshot()
    frames = {}
    for market in config.MARKETS:
        p = snap / f"{market.lower()}_quotes.csv"
        if p.exists():
            frames[market] = pd.read_csv(p, dtype={"code": str})
    return frames


def search_smartbox(query: str, count: int = 8) -> list:
    """Live Eastmoney suggest search; empty list on failure."""
    d = SB.get_json(SMARTBOX_URL, params={
        "input": query, "type": "14", "token": SMARTBOX_TOKEN,
        "count": count}, retries=2)
    items = ((d or {}).get("QuotationCodeTable") or {}).get("Data") or []
    out = []
    for it in items:
        market = SMARTBOX_MKT.get(str(it.get("MktNum") or ""))
        code = str(it.get("Code") or "").strip()
        name = str(it.get("Name") or "").strip()
        if not market or not code or not name:
            continue
        if market == "HK":
            code = code.zfill(5)
        out.append(Match(market, code, name, 50.0,
                         str(it.get("MktNum") or "")))
    return out


def resolve(query: str, snapshot_dir=None, live: bool = True) -> list:
    """All candidate matches for a query, best first."""
    out = []
    form = parse_code_form(query)
    if form:
        out.append(Match(form[0], form[1], query.strip(), 120.0, form[2]))
    try:
        frames = load_snapshot_frames(snapshot_dir)
    except FileNotFoundError:
        frames = {}
    out += search_frames(query, frames)
    if live and len(out) < 3:
        seen = {(m.market, m.code) for m in out}
        out += [m for m in search_smartbox(query)
                if (m.market, m.code) not in seen]
    best = {}
    for m in out:
        key = (m.market, m.code)
        if key not in best or m.score > best[key].score:
            best[key] = m
    res = sorted(best.values(), key=lambda m: -m.score)
    # enrich code-form matches with real display names
    for m in res:
        df = frames.get(m.market)
        if df is not None and not df.empty and "name" in df.columns:
            hit = df[df["code"].astype(str) == m.code]
            if not hit.empty:
                m.name = str(hit.iloc[0]["name"])
                if not m.market_id and "market_id" in hit.columns:
                    m.market_id = str(hit.iloc[0].get("market_id") or "")
    return res
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_resolve.py -q --basetemp=tmp\pt_r2`
Expected: `12 passed`

---

### Task 4: live quotes + `value_genie/analyze.py`

**Files:**
- Modify: `value_genie/fetch/quotes.py` (add `fetch_quotes_by_secids` after `fetch_market_quotes`, before `exclude_risk_names`)
- Create: `value_genie/analyze.py`
- Test: `tests/test_analyze.py`

- [ ] **Step 1: Add `fetch_quotes_by_secids` to quotes.py**

In `value_genie/fetch/quotes.py`, insert between `fetch_market_quotes` and `exclude_risk_names`:

```python
def fetch_quotes_by_secids(secids: list) -> pd.DataFrame:
    """Real-time quotes for explicit secids like '1.600519', '116.02555'.

    Uses the same push2 field layout as the clist batch endpoint, so
    rows carry the same columns. Empty frame on failure.
    """
    if not secids:
        return pd.DataFrame()
    d = em_push2_get("/api/qt/ulist.np/get", params={
        "secids": ",".join(secids), "fltt": 2, "invt": 2, "np": 1,
        "fields": config.CLIST_FIELD_IDS, "ut": config.EM_UT_LIST,
    })
    rows = ((d or {}).get("data") or {}).get("diff") or []
    return pd.DataFrame(_parse_clist_rows(rows))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_analyze.py`:

```python
"""Tests for value_genie.analyze (no network)."""

from pathlib import Path

import pandas as pd

from value_genie import analyze as az
from value_genie.resolve import Match


class TestPercentile:
    def test_higher_is_better(self):
        s = pd.Series([1, 2, 3, 4, 5])
        assert az.percentile(5, s) == 90.0
        assert az.percentile(1, s) == 10.0

    def test_lower_is_better_inverted(self):
        s = pd.Series([10, 20, 30, 40, 50])
        assert az.percentile(10, s, lower_is_better=True) == 90.0
        assert az.percentile(50, s, lower_is_better=True) == 10.0

    def test_nan_value_returns_none(self):
        assert az.percentile(float("nan"), pd.Series([1, 2])) is None


class TestVerdictBand:
    def test_bands(self):
        assert az.verdict_band(90) == "outstanding opportunity"
        assert az.verdict_band(75) == "attractive"
        assert az.verdict_band(50) == "reasonable"
        assert az.verdict_band(25) == "unattractive"
        assert az.verdict_band(5) == "poor"
        assert "inconclusive" in az.verdict_band(None)


class TestRiskFlags:
    def _result(self, **over):
        r = {"quote": {}, "fundamentals": {}, "kline": {}, "warnings": []}
        r.update(over)
        return r

    def test_flags_fire_on_thresholds(self):
        flags = az.risk_flags(self._result(
            fundamentals={"debt_ratio": 80.0, "rev_yoy": -4.0,
                          "profit_yoy": -10.0},
            kline={"drawdown_52w": -55.0, "volatility": 70.0}))
        joined = " | ".join(flags)
        assert "leverage" in joined
        assert "revenue contracting" in joined
        assert "profit contracting" in joined
        assert "drawdown" in joined
        assert "volatility" in joined

    def test_clean_profile_has_no_flags(self):
        assert az.risk_flags(self._result(
            fundamentals={"debt_ratio": 40.0, "rev_yoy": 10.0,
                          "profit_yoy": 15.0},
            kline={"drawdown_52w": -10.0, "volatility": 25.0})) == []


# ---------------------------------------------------------------------------
# Fixture snapshot
# ---------------------------------------------------------------------------
def make_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "20260901"
    snap.mkdir(exist_ok=True)
    codes = ["600001", "600002", "600003"]
    quotes = pd.DataFrame({
        "market": "A", "code": codes,
        "name": ["Alpha Co", "Beta Co", "Gamma Co"],
        "market_id": "1", "industry": "food",
        "price": [10.0, 20.0, 30.0],
        "pe_ttm": [10.0, 20.0, 30.0], "pb": [1.0, 2.0, 3.0],
        "market_cap": [5e10, 6e10, 7e10],
    })
    quotes.to_csv(snap / "a_quotes.csv", index=False)
    fins = pd.DataFrame({
        "code": codes,
        "report_date": ["2026-06-30"] * 3,
        "revenue": [1e10, 2e10, 3e10],
        "rev_yoy": [10.0, 20.0, 5.0],
        "profit": [1e9, 2e9, 3e9],
        "profit_yoy": [15.0, 25.0, -5.0],
        "roe": [15.0, 20.0, 10.0],
        "gross_margin": [30.0, 40.0, 20.0],
    })
    fins.to_csv(snap / "a_financials.csv", index=False)
    kdir = snap / "kline"
    kdir.mkdir()
    for i, code in enumerate(codes):
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(),
                               periods=300)
        close = pd.Series(range(100, 100 + 300)) * (1.0 + i * 0.1)
        pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": close, "close": close,
            "high": close * 1.01, "low": close * 0.99,
            "volume": [1e6] * 300, "amount": [1e8] * 300,
        }).to_csv(kdir / f"A_{code}.csv", index=False)
    return snap


def live_quote_df(pe=10.0):
    return pd.DataFrame([{
        "market": "A", "code": "600001", "name": "Alpha Co",
        "market_id": "1", "price": 10.5, "pct_chg": 1.2,
        "pe_ttm": pe, "pb": 1.1, "market_cap": 5.2e10,
    }])


class TestAnalyzeStock:
    def test_full_flow_a_share(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", live_quote_df)
        monkeypatch.setattr(az, "fetch_kline_any",
                            lambda *a, **k: None)
        m = Match("A", "600001", "Alpha Co", 100.0, "1")
        r = az.analyze_stock(m, snapshot_dir=snap)
        assert r["quote"]["price"] == 10.5
        assert r["fundamentals"]["rev_yoy"] == 10.0
        assert r["kline"]["ret_250d"] is not None
        assert 0 <= r["composite_percentile"] <= 100
        assert r["verdict"] in ("outstanding opportunity", "attractive",
                                "reasonable", "unattractive", "poor")
        # Alpha is the cheapest of 3 -> oriented PE percentile is high
        assert r["percentiles"]["pe_ttm"] > 50
        assert r["risk_flags"] == []

    def test_live_quote_failure_degrades(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids",
                            lambda s: pd.DataFrame())
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        r = az.analyze_stock(Match("A", "600001", "Alpha Co", 100.0, "1"),
                             snapshot_dir=snap)
        assert r["quote"] is None
        assert any("live quote" in w for w in r["warnings"])

    def test_hk_live_quote_zfills_code(self, monkeypatch):
        seen = {}

        def fake(secids):
            seen["secids"] = secids
            return pd.DataFrame([{"market": "HK", "code": "2555",
                                  "name": "茶百道", "market_id": "116",
                                  "price": 9.9, "pe_ttm": 12.0}])

        monkeypatch.setattr(az, "fetch_quotes_by_secids", fake)
        row = az.live_quote(Match("HK", "02555", "茶百道", 100.0, "116"))
        assert seen["secids"] == ["116.02555"]
        assert row["code"] == "02555"


class TestRender:
    def _result(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", live_quote_df)
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        return az.analyze_stock(Match("A", "600001", "Alpha Co", 100.0, "1"),
                                snapshot_dir=snap)

    def test_brief_mentions_name_verdict_price(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_brief(r)
        assert "Alpha Co" in text
        assert "verdict" in text
        assert "10.50" in text
        assert "PE" in text

    def test_evidence_has_table_and_flags(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_evidence(r)
        assert "evidence" in text
        assert "peer pctile" in text
        assert "risk flags" in text
        assert "data as of" in text

    def test_to_json_roundtrip(self, tmp_path, monkeypatch):
        import json
        r = self._result(tmp_path, monkeypatch)
        data = json.loads(az.to_json(r))
        assert data["match"]["code"] == "600001"
        assert data["verdict"] == r["verdict"]


class TestCompare:
    def test_compare_two(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)

        def quotes(secids):
            pe = 15.0 if "600002" in secids[0] else 10.0
            return pd.DataFrame([{"market": "A", "code": "60000X",
                                  "name": "X", "market_id": "1",
                                  "price": 10.0, "pe_ttm": pe,
                                  "pb": 1.0, "market_cap": 5e10}])

        monkeypatch.setattr(az, "fetch_quotes_by_secids", quotes)
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        df = az.compare_stocks(
            [Match("A", "600001", "Alpha Co", 100.0, "1"),
             Match("A", "600002", "Beta Co", 100.0, "1")],
            snapshot_dir=snap)
        assert len(df) == 2
        assert set(df.columns) >= {"name", "pe_ttm", "verdict",
                                   "composite_pctile", "risks"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_analyze.py -q --basetemp=tmp\pt_a1`
Expected: FAIL with `ModuleNotFoundError: No module named 'value_genie.analyze'`

- [ ] **Step 4: Implement `value_genie/analyze.py`**

```python
"""Single-stock analysis engine.

Assembles a live quote, snapshot fundamentals and kline metrics for one
resolved stock, ranks it against its market's gated peer universe, and
renders a deterministic verdict. Output is brief-first (verdict + key
numbers) with the full evidence table available on demand — the calling
AI writes the prose; this module supplies facts.
"""

import json
from pathlib import Path

import pandas as pd

from . import config
from .fetch.fundamentals import fetch_hk_f10
from .fetch.kline import (fetch_kline_any, kline_cache_path,
                          kline_is_fresh, load_kline)
from .fetch.pipeline import apply_gates, merge_a_financials, \
    merge_us_financials
from .fetch.quotes import fetch_quotes_by_secids
from .report import resolve_snapshot
from .resolve import Match
from .strategy.composite import apply_composite
from .strategy.factors import PILLARS, add_pillar_scores, kline_metrics
from .strategy.presets import PRESETS

# (column, label, lower_is_better) — evidence table layout
EVIDENCE_METRICS = [
    ("pe_ttm", "PE (TTM)", True),
    ("pb", "PB", True),
    ("ps", "P/S", True),
    ("dividend_yield", "Div yield %", False),
    ("rev_yoy", "Revenue YoY %", False),
    ("profit_yoy", "Profit YoY %", False),
    ("rev_q_yoy", "Revenue QoQ YoY %", False),
    ("roe", "ROE %", False),
    ("gross_margin", "Gross margin %", False),
    ("net_margin", "Net margin %", False),
    ("debt_ratio", "Debt ratio %", True),
    ("ret_250d", "1y return %", False),
    ("ret_60d", "3m return %", False),
    ("volatility", "Volatility %", True),
    ("drawdown_52w", "Drawdown %", False),
]

VERDICTS = [
    (85, "outstanding opportunity"),
    (70, "attractive"),
    (40, "reasonable"),
    (20, "unattractive"),
    (0, "poor"),
]


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------
def percentile(value, series, lower_is_better: bool = False):
    """Oriented percentile of value in series (0-100, higher=better)."""
    s = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if s.empty or value is None or pd.isna(value):
        return None
    frac = (float((s < value).mean())
            + 0.5 * float((s == value).mean())) * 100.0
    return round(100.0 - frac if lower_is_better else frac, 1)


def verdict_band(pct):
    """Five-band label from the blended composite percentile."""
    if pct is None:
        return "inconclusive (insufficient data)"
    for floor, label in VERDICTS:
        if pct >= floor:
            return label
    return "poor"


def _flat_row(result: dict) -> dict:
    row = dict(result.get("quote") or {})
    row.update(result.get("fundamentals") or {})
    for k, v in (result.get("kline") or {}).items():
        if not k.startswith("_"):
            row[k] = v
    return row


def risk_flags(result: dict) -> list:
    """Hard observations, not opinions."""
    row = _flat_row(result)
    flags = []

    def _num(col):
        v = row.get(col)
        try:
            f = float(v)
            return None if pd.isna(f) else f
        except (TypeError, ValueError):
            return None

    if (v := _num("debt_ratio")) is not None and v > 70:
        flags.append(f"high leverage: debt ratio {v:.0f}%")
    if (v := _num("rev_yoy")) is not None and v < 0:
        flags.append(f"revenue contracting: {v:.1f}% YoY")
    if (v := _num("profit_yoy")) is not None and v < 0:
        flags.append(f"profit contracting: {v:.1f}% YoY")
    if (v := _num("drawdown_52w")) is not None and v < -40:
        flags.append(f"deep drawdown: {v:.0f}% from 52w high")
    if (v := _num("volatility")) is not None and v > 60:
        flags.append(f"high volatility: {v:.0f}% annualized")
    if result.get("warnings"):
        flags.append("incomplete data: " + "; ".join(result["warnings"]))
    return flags


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------
def build_peer_set(snapshot_dir, market: str) -> pd.DataFrame:
    """The gated universe for a market, rebuilt from snapshot files."""
    snap = Path(snapshot_dir)
    quotes = pd.read_csv(snap / f"{market.lower()}_quotes.csv",
                         dtype={"code": str})
    if market == "A":
        fin = None
        if (snap / "a_financials.csv").exists():
            fin = pd.read_csv(snap / "a_financials.csv",
                              dtype={"code": str})
        df = merge_a_financials(quotes, fin)
    elif market == "US":
        fin = None
        if (snap / "us_financials.csv").exists():
            fin = pd.read_csv(snap / "us_financials.csv",
                              dtype={"ticker": str})
        df = merge_us_financials(quotes, fin)
    else:
        df = quotes
    return apply_gates(df, market)


def live_quote(match: Match):
    """Real-time quote row via push2 ulist; None on failure."""
    if not match.market_id:
        return None
    df = fetch_quotes_by_secids([f"{match.market_id}.{match.code}"])
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    if match.market == "HK":
        row["code"] = str(row["code"]).zfill(5)
    return row


HK_F10_FIELDS = ("report_date", "revenue", "rev_yoy", "profit_yoy",
                 "roe", "gross_margin", "net_margin", "debt_ratio",
                 "dividend_yield")
A_FIN_FIELDS = ("report_date", "revenue", "rev_yoy", "profit_yoy",
                "roe", "gross_margin")
US_FIN_FIELDS = ("rev", "rev_yoy", "profit_yoy", "rev_q_yoy", "roe",
                 "gross_margin", "net_margin", "debt_ratio")


def target_fundamentals(match: Match, snapshot_dir) -> dict:
    """Fundamental metrics for the target, snapshot-first, HK live."""
    snap = Path(snapshot_dir) if snapshot_dir else None
    if snap is not None:
        if match.market == "A" and (snap / "a_financials.csv").exists():
            f = pd.read_csv(snap / "a_financials.csv",
                            dtype={"code": str})
            hit = f[f["code"] == match.code]
            if not hit.empty:
                r = hit.iloc[0]
                return {k: r.get(k) for k in A_FIN_FIELDS}
        if match.market == "US" and (snap / "us_financials.csv").exists():
            f = pd.read_csv(snap / "us_financials.csv",
                            dtype={"ticker": str})
            hit = f[f["ticker"] == match.code]
            if not hit.empty:
                r = hit.iloc[0]
                return {k: r.get(k) for k in US_FIN_FIELDS}
        if match.market == "HK" and (snap / "hk_f10.csv").exists():
            f = pd.read_csv(snap / "hk_f10.csv", dtype={"code": str})
            hit = f[f["code"] == match.code]
            if not hit.empty:
                r = hit.iloc[0]
                return {k: r.get(k) for k in HK_F10_FIELDS}
    if match.market == "HK":
        f10 = fetch_hk_f10(match.code)
        if f10 is not None and not f10.empty:
            r = f10.iloc[0]
            return {k: r.get(k) for k in HK_F10_FIELDS}
    return {}


def target_kline_metrics(match: Match, snapshot_dir) -> dict:
    """Kline-derived momentum metrics; fresh cache preferred."""
    kl = None
    if snapshot_dir is not None:
        p = kline_cache_path(Path(snapshot_dir), match.market, match.code)
        if p.exists() and kline_is_fresh(p, match.market):
            kl = load_kline(p)
    if kl is None:
        kl = fetch_kline_any(match.market, match.code,
                             match.market_id, lmt=config.KLINE_DAYS)
    out = kline_metrics(kl)
    out["_bars"] = len(kl) if kl is not None else 0
    out["_last_date"] = (str(kl["date"].iloc[-1])
                         if kl is not None and not kl.empty else None)
    return out


def _target_row(match: Match, quote, fins: dict, klm: dict) -> dict:
    row = {"market": match.market, "code": match.code,
           "name": match.name}
    for col in ("price", "pe_ttm", "pb", "market_cap", "pct_chg"):
        if quote and quote.get(col) is not None:
            row[col] = quote.get(col)
    row.update({k: v for k, v in (fins or {}).items()
                if v is not None and not (isinstance(v, float)
                                          and pd.isna(v))})
    row.update({k: v for k, v in klm.items() if not k.startswith("_")})
    rev = row.get("revenue") or row.get("rev")
    if rev and row.get("market_cap"):
        # HK F10 revenue is CNY while market cap is HKD — HK peers carry
        # no ps column at all, so only derive ps where currencies match.
        if match.market in ("A", "US"):
            row["ps"] = row["market_cap"] / rev
    return row


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def analyze_stock(match: Match, snapshot_dir=None, live: bool = True) -> dict:
    """Full analysis for one resolved stock."""
    snap = None
    if snapshot_dir is not None:
        snap = Path(snapshot_dir)
    else:
        try:
            snap = resolve_snapshot()
        except FileNotFoundError:
            snap = None
    result = {"match": match,
              "snapshot": snap.name if snap else None,
              "warnings": []}

    quote = live_quote(match) if live else None
    if quote is None:
        result["warnings"].append(
            "live quote unavailable; using snapshot/fallback data")
    result["quote"] = quote

    fins = target_fundamentals(match, snap) if snap else {}
    if not fins and match.market == "HK":
        fins = target_fundamentals(match, None)
    if not fins:
        result["warnings"].append("no fundamentals available")
    result["fundamentals"] = fins

    klm = target_kline_metrics(match, snap)
    result["kline"] = klm

    pct, scores, composite_pct = {}, {}, None
    if snap is not None:
        peers = build_peer_set(snap, match.market)
        peers = peers[peers["code"].astype(str) != match.code]
        if peers.empty:
            result["warnings"].append("empty peer universe")
        else:
            row = _target_row(match, quote, fins, klm)
            frame = pd.concat(
                [peers, pd.DataFrame([row])], ignore_index=True)
            frame = add_pillar_scores(frame)
            scored = apply_composite(
                frame, PRESETS[config.DEFAULT_PRESET]["weights"],
                min_pillars=1)
            tgt = scored.iloc[-1]
            scores = {}
            for p in PILLARS:
                v = tgt.get(f"{p}_score")
                scores[p] = (None if v is None or pd.isna(v)
                            else round(float(v), 1))
            comp = tgt.get("composite_score")
            if comp is not None and not pd.isna(comp):
                composite_pct = round(float(
                    (scored["composite_score"] < comp).mean() * 100.0), 1)
            for col, _label, lower in EVIDENCE_METRICS:
                if col in frame.columns:
                    p = percentile(tgt.get(col), frame[col], lower)
                    if p is not None:
                        pct[col] = p
    result["percentiles"] = pct
    result["scores"] = scores
    result["composite_percentile"] = composite_pct
    result["verdict"] = verdict_band(composite_pct)
    result["risk_flags"] = risk_flags(result)
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _as_of(result: dict) -> str:
    parts = []
    if result.get("quote"):
        parts.append("quote: live")
    rd = (result.get("fundamentals") or {}).get("report_date")
    if rd:
        parts.append(f"fundamentals: {rd}")
    ld = (result.get("kline") or {}).get("_last_date")
    if ld:
        parts.append(f"kline: {ld}")
    return "; ".join(parts) or "unknown"


def render_brief(result: dict) -> str:
    m = result["match"]
    q = result.get("quote") or {}
    row = _flat_row(result)
    p = result.get("percentiles") or {}
    lines = [f"{m.name}  [{m.market}/{m.code}]"]
    if q.get("price") is not None:
        chg = q.get("pct_chg")
        chg_s = f" ({chg:+.2f}% today)" if chg is not None else ""
        lines.append(f"price: {q['price']:,.2f} "
                     f"{config.MARKET_CURRENCIES[m.market]}{chg_s}")
    lines.append(f"verdict: {result['verdict']}")
    if result.get("composite_percentile") is not None:
        lines.append(f"blended rank: {result['composite_percentile']:.0f}th "
                     f"percentile of the {m.market} gated universe")
    for col, label in (("pe_ttm", "PE"), ("rev_yoy", "rev YoY"),
                       ("roe", "ROE")):
        v = row.get(col)
        if v is not None and not pd.isna(v):
            extra = f" ({p[col]:.0f}th pctile)" if col in p else ""
            lines.append(f"{label}: {v:,.1f}{extra}")
    flags = result["risk_flags"]
    if flags:
        lines.append(f"risk flags: {len(flags)} - " + "; ".join(flags))
    else:
        lines.append("risk flags: 0")
    lines.append(f"data as of: {_as_of(result)}")
    return "\n".join(lines)


def render_evidence(result: dict) -> str:
    m = result["match"]
    row = _flat_row(result)
    p = result.get("percentiles") or {}
    lines = [f"== {m.name} [{m.market}/{m.code}] - evidence ==",
             f"verdict: {result['verdict']}"]
    sc = [f"{k}={v:.0f}" for k, v in (result.get("scores") or {}).items()
          if v is not None]
    if sc:
        lines.append("pillar scores (peer percentiles): " + "  ".join(sc))
    if result.get("composite_percentile") is not None:
        lines.append(f"blended composite: "
                     f"{result['composite_percentile']:.0f}th percentile")
    lines += ["", f"{'metric':<20}{'value':>12}{'peer pctile':>13}"]
    for col, label, _lower in EVIDENCE_METRICS:
        v = row.get(col)
        vs = ("-" if v is None or (isinstance(v, float) and pd.isna(v))
              else f"{v:,.2f}")
        ps = f"{p[col]:.0f}" if col in p else "-"
        lines.append(f"{label:<20}{vs:>12}{ps:>13}")
    flags = result["risk_flags"]
    lines += ["", f"risk flags ({len(flags)}):"]
    lines += [f"  - {f}" for f in flags] or ["  none"]
    lines += ["", f"data as of: {_as_of(result)}"]
    return "\n".join(lines)


def to_json(result: dict) -> str:
    m = result["match"]
    payload = {
        "market": m.market, "code": m.code, "name": m.name,
        "snapshot": result.get("snapshot"),
        "verdict": result["verdict"],
        "composite_percentile": result.get("composite_percentile"),
        "scores": result.get("scores"),
        "percentiles": result.get("percentiles"),
        "metrics": {k: v for k, v in _flat_row(result).items()
                    if isinstance(v, (int, float, str))
                    and not (isinstance(v, float) and pd.isna(v))},
        "risk_flags": result["risk_flags"],
        "warnings": result["warnings"],
        "data_as_of": _as_of(result),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2,
                      default=str)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def compare_stocks(matches, snapshot_dir=None) -> pd.DataFrame:
    """Side-by-side table of resolved stocks."""
    rows = []
    for m in matches:
        r = analyze_stock(m, snapshot_dir)
        row = _flat_row(r)
        rows.append({
            "market": m.market, "code": m.code, "name": m.name,
            "price": row.get("price"),
            "pe_ttm": row.get("pe_ttm"),
            "pe_pctile": (r["percentiles"] or {}).get("pe_ttm"),
            "rev_yoy": row.get("rev_yoy"),
            "roe": row.get("roe"),
            "composite_pctile": r["composite_percentile"],
            "verdict": r["verdict"],
            "risks": len(r["risk_flags"]),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_analyze.py -q --basetemp=tmp\pt_a2`
Expected: `16 passed`

---

### Task 5: CLI — `ask` / `compare` / `overview` / `doctor` / `skill`

**Files:**
- Modify: `value_genie/__main__.py`
- Test: `tests/test_cli.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
# ---------------------------------------------------------------------------
# AI-toolkit commands (ask / compare / overview / doctor / skill)
# ---------------------------------------------------------------------------
from value_genie.resolve import Match


def fake_result(m):
    return {"match": m, "quote": None, "fundamentals": {},
            "kline": {}, "warnings": ["live quote unavailable"],
            "percentiles": {"pe_ttm": 83.3}, "scores": {},
            "composite_percentile": None,
            "verdict": "inconclusive (insufficient data)",
            "risk_flags": [], "snapshot": None}


class TestAsk:
    def test_ask_brief(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = cli.main(["ask", "Alpha Co"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Alpha Co" in out
        assert "verdict" in out
        assert "also matched" not in out

    def test_ask_shows_alternatives(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1"),
                            Match("HK", "02555", "茶百道", 50.0, "116")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = cli.main(["ask", "alpha"])
        assert rc == 0
        assert "also matched" in capsys.readouterr().out

    def test_ask_json(self, capsys, monkeypatch):
        import json
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = cli.main(["ask", "Alpha Co", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["code"] == "600001"

    def test_ask_no_match_returns_2(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.resolve.resolve",
                            lambda q, **k: [])
        assert cli.main(["ask", "nonsense"]) == 2
        assert "no match" in capsys.readouterr().out

    def test_compare(self, capsys, monkeypatch):
        import pandas as pd
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.compare_stocks",
            lambda ms, snapshot_dir=None: pd.DataFrame([{
                "market": "A", "code": "600001", "name": "Alpha Co",
                "price": 10.0, "pe_ttm": 10.0, "pe_pctile": 83.3,
                "rev_yoy": 10.0, "roe": 15.0, "composite_pctile": 80.0,
                "verdict": "attractive", "risks": 0}]))
        rc = cli.main(["compare", "Alpha Co"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Alpha Co" in out


class TestOverviewCli:
    def test_overview(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.overview.market_overview",
            lambda markets=None, top_n=10: {
                "snapshot": "20260901", "markets": {}})
        rc = cli.main(["overview"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "20260901" in out


class TestDoctorCli:
    def test_doctor_exit_zero_on_pass(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.run_checks",
                            lambda data_dir=None: [("PASS", "-", "ok")])
        rc = cli.main(["doctor"])
        assert rc == 0
        assert "ok" in capsys.readouterr().out

    def test_doctor_exit_one_on_fail(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.run_checks",
            lambda data_dir=None: [("FAIL", "-", "no snapshots found")])
        rc = cli.main(["doctor"])
        assert rc == 1
        assert "fetch" in capsys.readouterr().out


class TestSkillCli:
    def test_skill_list_real_dir(self, capsys, monkeypatch):
        rc = cli.main(["skill", "list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "single-stock-analysis" in out

    def test_skill_note_roundtrip(self, capsys, monkeypatch, tmp_path):
        import shutil as _sh
        from value_genie import config as cfg, skills as sk
        d = tmp_path / "skills"
        _sh.copytree(cfg.SKILLS_DIR, d)
        monkeypatch.setattr(cfg, "SKILLS_DIR", d)
        rc = cli.main(["skill", "note", "single-stock-analysis",
                       "test lesson"])
        assert rc == 0
        s = sk.find_skill(d, "single-stock-analysis")
        assert sk.field_notes(s)[-1][2] == "test lesson"

    def test_skill_edit_adds_trigger(self, capsys, monkeypatch, tmp_path):
        import shutil as _sh
        from value_genie import config as cfg, skills as sk
        d = tmp_path / "skills"
        _sh.copytree(cfg.SKILLS_DIR, d)
        monkeypatch.setattr(cfg, "SKILLS_DIR", d)
        rc = cli.main(["skill", "edit", "single-stock-analysis",
                       "--add-trigger", "X还能买吗"])
        assert rc == 0
        assert "X还能买吗" in sk.find_skill(d,
                                            "single-stock-analysis").triggers


class TestParserSurface:
    def test_parser_accepts_new_commands(self):
        p = cli.build_parser()
        assert p.parse_args(["ask", "X", "--evidence"]).evidence
        assert p.parse_args(["ask", "X", "--json"]).json
        assert p.parse_args(["compare", "X", "Y"]).stocks == ["X", "Y"]
        assert p.parse_args(["overview", "--top", "5"]).top == 5
        assert p.parse_args(["skill", "note", "id", "text"]).text == "text"
```

Check the top of `tests/test_cli.py` imports first — it already imports `cli` (as `from value_genie import __main__ as cli` or similar); keep its existing style and only append the block above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_cli.py -q --basetemp=tmp\pt_c1`
Expected: new tests FAIL (`SystemExit: 2` from argparse for unknown commands / AttributeError)

- [ ] **Step 3: Implement the CLI in `value_genie/__main__.py`**

Update the module docstring usage block to:

```python
"""Command-line interface: fetch market data, screen snapshots, analyze.

Usage:
    python -m value_genie fetch [--markets A,HK,US] [--refresh]
    python -m value_genie screen [--preset balanced] [--set value=0.4]
                                 [--top 20] [--markets A,HK] [--snapshot DATE]
    python -m value_genie ask 茶百道 [--evidence] [--json]
    python -m value_genie compare 茶百道 古茗
    python -m value_genie overview [--markets A,HK] [--top 10]
    python -m value_genie doctor
    python -m value_genie skill list|show|note|edit ...

`ask` resolves any name/code to a stock and prints a brief verdict
(live quote + snapshot percentiles); `--evidence` adds the full table.
See AGENTS.md for the AI-facing playbook.
"""
```

Add the new subcommand handlers after `cmd_screen`:

```python
def cmd_ask(args) -> int:
    from . import analyze as az
    from .resolve import resolve as resolve_stock
    matches = resolve_stock(args.query)
    if not matches:
        print(f"no match for {args.query!r}; try a full name or code")
        return 2
    m = matches[0]
    if len(matches) > 1:
        others = ", ".join(x.label() for x in matches[1:4])
        print(f"resolved: {m.label()} (also matched: {others})")
    result = az.analyze_stock(m)
    if args.json:
        print(az.to_json(result))
    elif args.evidence:
        print(az.render_evidence(result))
    else:
        print(az.render_brief(result))
    return 0


def cmd_compare(args) -> int:
    from . import analyze as az
    from .resolve import resolve as resolve_stock
    matches = []
    for q in args.stocks:
        ms = resolve_stock(q)
        if not ms:
            print(f"no match for {q!r}; try a full name or code")
            return 2
        matches.append(ms[0])
    # drop duplicate resolutions
    seen, uniq = set(), []
    for m in matches:
        if (m.market, m.code) not in seen:
            seen.add((m.market, m.code))
            uniq.append(m)
    df = az.compare_stocks(uniq)
    print("== Value Genie compare ==")
    print(df.to_string(index=False, float_format=lambda v: f"{v:.1f}"))
    if len(df) >= 2:
        cheap = df.dropna(subset=["pe_pctile"])
        grow = df.dropna(subset=["rev_yoy"])
        if not cheap.empty:
            c = cheap.sort_values("pe_pctile").iloc[0]
            print(f"\ncheapest: {c['name']} "
                  f"(PE {c['pe_pctile']:.0f}th pctile)")
        if not grow.empty:
            g = grow.sort_values("rev_yoy", ascending=False).iloc[0]
            print(f"fastest growth: {g['name']} "
                  f"(rev YoY {g['rev_yoy']:.1f}%)")
    return 0


def cmd_overview(args) -> int:
    from . import overview as ov
    markets = _parse_markets(args.markets)
    try:
        data = ov.market_overview(markets=markets, top_n=args.top)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    print(ov.render_overview(data))
    return 0


def cmd_doctor(args) -> int:
    from . import doctor as dr
    checks = dr.run_checks(args.data_dir)
    print(dr.render_checks(checks))
    return dr.doctor_exit_code(checks)


def cmd_skill(args) -> int:
    from . import skills as sk
    d = config.SKILLS_DIR
    if args.skill_cmd == "list":
        items, errors = sk.load_skills(d)
        for e in errors:
            print(f"ERROR {e}")
        if not items:
            print(f"no skills found under {d}")
            return 1
        for s in items:
            print(f"{s.id:<28} v{s.version:<4} notes="
                  f"{len(sk.field_notes(s)):<3} {s.title}")
        return 0
    try:
        if args.skill_cmd == "show":
            s = sk.find_skill(d, args.skill_id)
            print(s.path.read_text(encoding="utf-8"))
        elif args.skill_cmd == "note":
            s = sk.append_note(d, args.skill_id, args.text)
            print(f"noted on {s.id} (v{s.version}): {args.text}")
        elif args.skill_cmd == "edit":
            s = sk.edit_skill(d, args.skill_id,
                              add_triggers=args.add_trigger,
                              remove_triggers=args.remove_trigger)
            print(f"updated {s.id} -> v{s.version}; "
                  f"triggers: {', '.join(s.triggers)}")
    except sk.SkillFormatError as exc:
        print(exc)
        return 2
    return 0
```

In `build_parser`, after the `screen` parser block, add:

```python
    pa = sub.add_parser("ask", help="analyze one stock (verdict first)")
    pa.add_argument("query", help="stock name, code or ticker (Chinese ok)")
    pa.add_argument("--evidence", action="store_true",
                    help="print the full metric/percentile tables")
    pa.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    pa.set_defaults(func=cmd_ask)

    pc = sub.add_parser("compare", help="compare 2+ stocks side by side")
    pc.add_argument("stocks", nargs="+", help="names/codes to compare")
    pc.set_defaults(func=cmd_compare)

    po = sub.add_parser("overview", help="market digest from latest snapshot")
    po.add_argument("--markets", default=None, metavar="A,HK,US",
                    help="markets to include (default: all)")
    po.add_argument("--top", type=int, default=10,
                    help="top names per market (default: 10)")
    po.add_argument("--data-dir", default=None, help="data directory")
    po.set_defaults(func=cmd_overview)

    pdoc = sub.add_parser("doctor", help="check snapshot health/freshness")
    pdoc.add_argument("--data-dir", default=None, help="data directory")
    pdoc.set_defaults(func=cmd_doctor)

    psk = sub.add_parser("skill", help="inspect / evolve AI skills")
    psk_sub = psk.add_subparsers(dest="skill_cmd", required=True)
    p_list = psk_sub.add_parser("list", help="list all skills")
    p_show = psk_sub.add_parser("show", help="print one skill file")
    p_show.add_argument("skill_id")
    p_note = psk_sub.add_parser(
        "note", help="append a field note (AI self-refinement)")
    p_note.add_argument("skill_id")
    p_note.add_argument("text", help="one concrete lesson line")
    p_edit = psk_sub.add_parser("edit", help="edit triggers (human path)")
    p_edit.add_argument("skill_id")
    p_edit.add_argument("--add-trigger", action="append", default=None,
                        metavar="T", help="trigger to add (repeatable)")
    p_edit.add_argument("--remove-trigger", action="append", default=None,
                        metavar="T", help="trigger to remove (repeatable)")
    psk.set_defaults(func=cmd_skill)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_cli.py -q --basetemp=tmp\pt_c2`
Expected: all pass (existing + ~13 new)

---

### Task 6: `overview.py` + `doctor.py`

**Files:**
- Create: `value_genie/overview.py`
- Create: `value_genie/doctor.py`
- Test: `tests/test_overview.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_overview.py`:

```python
"""Tests for value_genie.overview and value_genie.doctor (no network)."""

import json
from pathlib import Path

import pandas as pd

from value_genie import doctor as dr
from value_genie import overview as ov


def master_df():
    rows = []
    for i in range(6):
        rows.append({
            "market": "A", "code": f"60000{i}", "name": f"A{i}",
            "industry": "food" if i % 2 else "banks",
            "price": 10.0 + i, "pe_ttm": 10.0 + i, "pb": 1.0 + i / 10,
            "rev_yoy": 5.0 + i, "roe": 10.0 + i,
            "pos_52w": 30.0 + i * 8,
            "value_score": 50.0 + i, "growth_score": 50.0 + i,
            "quality_score": 50.0 + i, "safety_score": 50.0 + i,
        })
    for i in range(4):
        rows.append({
            "market": "HK", "code": f"0000{i}", "name": f"H{i}",
            "industry": "property",
            "price": 20.0 + i, "pe_ttm": 8.0 + i, "pb": 0.8 + i / 10,
            "rev_yoy": -2.0 + i, "roe": 12.0 + i,
            "pos_52w": 40.0 + i * 5,
            "value_score": 60.0 + i, "growth_score": 40.0 + i,
            "quality_score": 55.0 + i, "safety_score": 45.0 + i,
        })
    return pd.DataFrame(rows)


def make_snap(tmp_path: Path, stale_kline: bool = False) -> Path:
    import datetime as dt
    snap = tmp_path / "20260901"
    snap.mkdir(exist_ok=True)
    master_df().to_csv(snap / "master.csv", index=False)
    kdir = snap / "kline"
    kdir.mkdir(exist_ok=True)
    end = (pd.Timestamp.today() - (pd.Timedelta(days=30)
                                   if stale_kline else pd.Timedelta(0))
           ).normalize()
    dates = pd.bdate_range(end=end, periods=300).strftime("%Y-%m-%d")
    for mk in ("A", "HK"):
        pd.DataFrame({"date": dates, "close": range(300)}).to_csv(
            kdir / f"{mk}_X.csv", index=False)
    (snap / "manifest.json").write_text(
        json.dumps({"failures": []}), encoding="utf-8")
    return snap


class TestOverview:
    def test_market_overview_structure(self, tmp_path):
        snap = make_snap(tmp_path)
        data = ov.market_overview(snapshot_dir=snap)
        assert data["snapshot"] == "20260901"
        assert set(data["markets"]) == {"A", "HK"}
        a = data["markets"]["A"]
        assert a["candidates"] == 6
        assert a["median_pe"] == 12.5     # median of 10..15
        assert "food" in a["top_sectors"]
        assert len(a["top"]) == 6         # fewer rows than top_n

    def test_market_filter(self, tmp_path):
        snap = make_snap(tmp_path)
        data = ov.market_overview(snapshot_dir=snap, markets=["HK"])
        assert set(data["markets"]) == {"HK"}

    def test_render_mentions_markets(self, tmp_path):
        text = ov.render_overview(
            ov.market_overview(snapshot_dir=make_snap(tmp_path)))
        assert "20260901" in text
        assert "[A]" in text and "[HK]" in text


class TestDoctor:
    def test_no_snapshots_fails(self, tmp_path):
        checks = dr.run_checks(data_dir=tmp_path)
        assert checks[0][0] == "FAIL"
        assert dr.doctor_exit_code(checks) == 1

    def test_healthy_snapshot_passes(self, tmp_path):
        checks = dr.run_checks(data_dir=make_snap(tmp_path).parent)
        statuses = {c[0] for c in checks}
        assert "FAIL" not in statuses
        assert dr.doctor_exit_code(checks) == 0

    def test_stale_kline_warns(self, tmp_path):
        snap = make_snap(tmp_path, stale_kline=True)
        checks = dr.run_checks(data_dir=snap.parent)
        kline_checks = [c for c in checks if "klines" in c[2]]
        assert kline_checks and kline_checks[0][0] in ("WARN", "FAIL")

    def test_render_includes_action_line(self, tmp_path):
        checks = dr.run_checks(data_dir=tmp_path)
        text = dr.render_checks(checks)
        assert "doctor" in text or "==" in text
        assert "fetch" in text        # recommended action present
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_overview.py -q --basetemp=tmp\pt_o1`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `value_genie/overview.py`**

```python
"""Market overview digest from the latest snapshot master.

Per market: candidate count, median valuations, breadth, top sectors
among the top-50 and the top-N table — enough for an AI to answer
"what looks attractive in HK right now".
"""

from pathlib import Path

import pandas as pd

from . import config, report


def _med(df: pd.DataFrame, col: str):
    if col not in df.columns or df[col].isna().all():
        return None
    return round(float(df[col].median()), 2)


def market_overview(snapshot_dir=None, markets=None, top_n: int = 10) -> dict:
    """Digest dict for the requested markets of a snapshot."""
    snap = Path(snapshot_dir) if snapshot_dir else report.resolve_snapshot()
    master = report.load_master(snap)
    markets = markets or list(config.MARKETS)
    out = {"snapshot": snap.name, "markets": {}}
    for mk in markets:
        df = master[master["market"] == mk]
        if df.empty:
            continue
        top = report.screen(master, preset=config.DEFAULT_PRESET,
                            top_n=top_n, markets=[mk])
        top50 = report.screen(master, preset=config.DEFAULT_PRESET,
                              top_n=50, markets=[mk])
        entry = {
            "candidates": len(df),
            "median_pe": _med(df, "pe_ttm"),
            "median_pb": _med(df, "pb"),
            "median_rev_yoy": _med(df, "rev_yoy"),
            "top_sectors": {},
            "top": top,
        }
        if "pos_52w" in df.columns and df["pos_52w"].notna().any():
            entry["above_52w_mid"] = round(
                float((df["pos_52w"] > 50).mean() * 100.0), 1)
        if "industry" in top50.columns:
            entry["top_sectors"] = {
                str(k): int(v) for k, v in
                top50["industry"].fillna("(unknown)")
                .value_counts().head(5).items()}
        out["markets"][mk] = entry
    return out


def render_overview(ov_data: dict) -> str:
    lines = [f"== Value Genie market overview - "
             f"snapshot {ov_data['snapshot']} =="]
    for mk, d in ov_data["markets"].items():
        lines += ["",
                  f"[{mk}] candidates={d['candidates']}"
                  f"  median PE={d['median_pe']}"
                  f"  median PB={d['median_pb']}"
                  f"  median rev YoY={d['median_rev_yoy']}%"]
        if "above_52w_mid" in d:
            lines.append(f"    breadth: {d['above_52w_mid']}% of candidates "
                         f"above their 52w midpoint")
        if d["top_sectors"]:
            lines.append("    top sectors (of top-50): " + ", ".join(
                f"{k} ({v})" for k, v in d["top_sectors"].items()))
        t = d["top"]
        cols = [c for c in ("rank", "code", "name", "price", "pe_ttm",
                            "rev_yoy", "roe", "composite_score")
                if c in t.columns]
        lines.append(t[cols].to_string(
            index=False, float_format=lambda v: f"{v:.1f}"))
    return "\n".join(lines)
```

- [ ] **Step 4: Implement `value_genie/doctor.py`**

```python
"""Data health checks: snapshot age, coverage, kline freshness, failures.

Output: PASS / WARN / FAIL lines plus a recommended action. Exit code 1
on any FAIL so scripts and agents can gate on it.
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import config
from .report import resolve_snapshot


def _parse_day(name: str):
    try:
        return datetime.strptime(name, "%Y%m%d").date()
    except ValueError:
        return None


def _kline_lag(path: Path):
    try:
        df = pd.read_csv(path, usecols=["date"])
        last = datetime.strptime(str(df["date"].iloc[-1]),
                                 "%Y-%m-%d").date()
        return (date.today() - last).days
    except (OSError, ValueError, IndexError, KeyError):
        return None


def run_checks(data_dir=None) -> list:
    """[(status, market, message)] with status PASS / WARN / FAIL."""
    try:
        snap = resolve_snapshot(data_dir)
    except FileNotFoundError:
        return [("FAIL", "-",
                 "no snapshots found; run: python -m value_genie fetch")]
    out = [("PASS", "-", f"latest snapshot: {snap.name}")]
    d = _parse_day(snap.name)
    if d:
        age = (date.today() - d).days
        status = "PASS" if age <= 1 else ("WARN" if age <= 7 else "FAIL")
        out.append((status, "-", f"snapshot age: {age} day(s)"))
    for mk in config.MARKETS:
        q = snap / f"{mk.lower()}_quotes.csv"
        if not q.exists():
            out.append((f"WARN", mk, "quotes file missing (not fetched?)"))
            continue
        n = len(pd.read_csv(q, dtype={"code": str}))
        out.append(("PASS" if n >= 1000 else "WARN", mk,
                    f"quotes rows: {n}"))
        kdir = snap / "kline"
        if kdir.is_dir():
            files = list(kdir.glob(f"{mk}_*.csv"))
            lags = [x for x in (_kline_lag(f) for f in files)
                    if x is not None]
            if lags:
                worst = max(lags)
                tol = config.KLINE_FRESH_DAYS[mk] + 2
                status = ("PASS" if worst <= tol
                          else ("WARN" if worst <= 7 else "FAIL"))
                out.append((status, mk,
                            f"klines: {len(files)} files, worst last-bar "
                            f"lag {worst} day(s)"))
    for name, min_rows in (("a_financials.csv", 1000),
                           ("us_financials.csv", 500),
                           ("hk_f10.csv", 50)):
        p = snap / name
        if not p.exists():
            out.append(("WARN", name.split("_")[0].upper(),
                        f"{name} missing"))
        else:
            n = len(pd.read_csv(p))
            out.append(("PASS" if n >= min_rows else "WARN",
                        name.split("_")[0].upper(), f"{name} rows: {n}"))
    mp = snap / "manifest.json"
    if mp.exists():
        try:
            fails = (json.loads(mp.read_text(encoding="utf-8"))
                     .get("failures") or [])
            if fails:
                out.append(("WARN", "-",
                            "manifest failures: " + "; ".join(fails)))
        except ValueError:
            out.append(("WARN", "-", "manifest.json unreadable"))
    return out


def render_checks(checks: list) -> str:
    icon = {"PASS": "ok  ", "WARN": "warn", "FAIL": "FAIL"}
    lines = ["== Value Genie doctor =="]
    for status, market, msg in checks:
        lines.append(f"[{icon[status]}] {market:>3}  {msg}")
    if any(c[0] == "FAIL" and "no snapshots" in c[2] for c in checks):
        lines += ["", "action: python -m value_genie fetch"]
    elif (any(c[0] == "FAIL" for c in checks)
          or any(c[0] == "WARN" and "age" in c[2] for c in checks)):
        lines += ["",
                  "action: python -m value_genie fetch   (refresh stale data)"]
    return "\n".join(lines)


def doctor_exit_code(checks: list) -> int:
    return 1 if any(c[0] == "FAIL" for c in checks) else 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m pytest tests\test_overview.py -q --basetemp=tmp\pt_o2`
Expected: `8 passed`

---

### Task 7: Streamlit Skills Manager page

**Files:**
- Modify: `app.py` (add page router + `render_skills_manager`)

- [ ] **Step 1: Add the page router and Skills Manager to app.py**

In `app.py`, directly after the `RADAR_METRICS` list definition (around line 55), insert:

```python
# ---------------------------------------------------------------------------
# Skills Manager page (human refinement path for skills/)
# ---------------------------------------------------------------------------
def render_skills_manager():
    from value_genie import skills as sk
    st.header("Skills Manager")
    st.caption(
        "Human refinement path: view and edit playbooks, promote or delete "
        "AI field notes. Agents append notes via "
        "`python -m value_genie skill note <id> \"lesson\"`.")
    skills, errors = sk.load_skills(str(config.SKILLS_DIR))
    for e in errors:
        st.error(f"skill load error: {e}")
    if not skills:
        st.info(f"no skills found under {config.SKILLS_DIR}")
        return
    labels = [f"{s.order:02d}  {s.title}" for s in skills]
    s = skills[st.selectbox("skill", labels)]

    notes = sk.field_notes(s)
    st.subheader(f"{s.id}  (v{s.version}, {len(notes)} notes, "
                 f"updated {s.updated_at})")

    with st.form("skill_editor"):
        title = st.text_input("title", s.title)
        triggers = st.text_area("triggers (one per line)",
                                "\n".join(s.triggers))
        body = st.text_area("playbook body (markdown)", s.body, height=360)
        if st.form_submit_button("save (bumps version)"):
            s.title = title.strip()
            s.triggers = [t.strip() for t in triggers.splitlines()
                          if t.strip()]
            s.body = body
            try:
                path = sk.save_skill(str(config.SKILLS_DIR), s)
                st.success(f"saved {path.name} (v{s.version})")
                st.cache_data.clear()
                st.rerun()
            except sk.SkillFormatError as exc:
                st.error(str(exc))

    st.markdown("#### Field notes")
    if not notes:
        st.caption("none yet — agents learn, notes appear here")
    for i, (stamp, author, text) in enumerate(notes):
        c1, c2, c3 = st.columns([6, 1, 1])
        c1.markdown(f"`[{stamp}]` **({author})** {text}")
        if c2.button("promote", key=f"promo_{s.id}_{i}",
                     help="move this lesson into the playbook body"):
            sk.promote_note(str(config.SKILLS_DIR), s.id, i)
            st.cache_data.clear()
            st.rerun()
        if c3.button("delete", key=f"del_{s.id}_{i}",
                     help="remove this note as noise"):
            sk.delete_note(str(config.SKILLS_DIR), s.id, i)
            st.cache_data.clear()
            st.rerun()


page = st.sidebar.radio("page", ["Dashboard", "Skills Manager"])
if page == "Skills Manager":
    render_skills_manager()
    st.stop()
```

Note: the router must come BEFORE the existing dashboard's sidebar widgets so "page" is the first sidebar control. `st.stop()` keeps the dashboard from rendering on the Skills page.

- [ ] **Step 2: Verify the app still imports and the dashboard path is intact**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -c "import app; print('app import OK')"`
Expected: `app import OK` (Streamlit bare mode executes module top level; the radio returns its default and the dashboard body is skipped by `st.stop()` only in interactive runs — import must not crash).

- [ ] **Step 3: Manual visual check (human step)**

Run: `streamlit run app.py` → sidebar shows "page" selector → Skills Manager lists 6 skills → edit a trigger → save → version bumps → promote/delete note buttons work. (If the sandbox blocks Streamlit AppTest, this counts as the verification.)

---

### Task 8: Real-data smoke + README update

**Files:**
- Modify: `README.md` (add AI-toolkit section, Chinese)
- No new code files

- [ ] **Step 1: Smoke the full toolkit against real data**

Run each command separately (sandbox kills long commands), redirecting output to `tmp\`, then inspect via the Read tool:

```powershell
$env:PYTHONPATH = "$PWD\libs;$PWD"
python -B -m value_genie doctor > tmp\smoke_doctor.txt 2>&1
python -B -m value_genie ask 茶百道 > tmp\smoke_ask_cn.txt 2>&1
python -B -m value_genie ask 摩尔线程 --evidence > tmp\smoke_ask_mt.txt 2>&1
python -B -m value_genie ask AAPL --evidence > tmp\smoke_ask_aapl.txt 2>&1
python -B -m value_genie compare 茶百道 古茗 > tmp\smoke_compare.txt 2>&1
python -B -m value_genie overview --top 5 > tmp\smoke_overview.txt 2>&1
python -B -m value_genie skill list > tmp\smoke_skill_list.txt 2>&1
python -B -m value_genie skill note single-stock-analysis "smoke test note: verified against 20260901 snapshot" > tmp\smoke_skill_note.txt 2>&1
```

Expected:
- doctor: PASS/WARN lines, exit 0 (snapshot 20260901 exists)
- ask 茶百道: resolves to HK/02555, live price prints, verdict band, PE percentile
- ask 摩尔线程: resolves to A/688795 (via snapshot fuzzy or smartbox), evidence table prints
- ask AAPL: resolves US/AAPL with SEC fundamentals percentiles
- compare: table with both names + cheapest/fastest takeaways
- overview: [A] [HK] [US] sections with medians and top tables
- skill list: 6 skills
- skill note: version bump; verify `skills/01-single-stock-analysis.md` Field Notes contains the note (Read tool)

If smartbox resolution fails (endpoint changed), the fallback is snapshot name search — for 茶百道/摩尔线程 both exist in snapshot quotes, so `ask` still resolves. Record any endpoint quirk with `skill note data-ops "..."`.

- [ ] **Step 2: Remove the smoke-test note**

Run: `$env:PYTHONPATH = "$PWD\libs;$PWD"; python -B -m value_genie skill edit single-stock-analysis` — no; instead delete the smoke note by hand: open `skills/01-single-stock-analysis.md`, remove the smoke-test note line, and decrement nothing (version stays; acceptable — or re-verify with `skill show`). Simplest: leave the note in place as a real demonstration of the loop, and mention it in the README section.

Decision: keep the smoke note (it demonstrates the feature) — README documents it.

- [ ] **Step 3: Update README.md (Chinese)**

Read `README.md` first, then insert after the quick-start commands block:

```markdown
## 面向 AI 的研究工具库

本仓库同时是一个 **AI 可自主使用的金融研究工具库**：任何 AI 助手（Claude Code / Trae / Cursor 等）
进入仓库后会自动读取 [`AGENTS.md`](AGENTS.md)，按其中的路由表把投资问题转化为工具调用：

| 命令 | 用途 |
|---|---|
| `python -m value_genie ask 茶百道` | 单股速览：实时报价 + 结论（verdict）+ 关键百分位 |
| `python -m value_genie ask 茶百道 --evidence` | 追问证据：全指标表 + 同行百分位 + 风险旗标 |
| `python -m value_genie compare 茶百道 古茗` | 多股对比：谁更便宜、谁增长更快 |
| `python -m value_genie overview --markets HK` | 市场概览：估值中位数、板块分布、Top 名单 |
| `python -m value_genie doctor` | 数据体检：快照年龄、K线新鲜度、数据源健康 |

### 技能（skills）与自我净化

`skills/` 目录收录 6 个剧本（单股分析、多股对比、市场概览、数据运维、宏观主题、投资哲学），
每个剧本带触发词与操作步骤。技能是**活文档**，有两条净化路径：

- **AI 自净化**：AI 回答问题后学到经验，执行
  `python -m value_genie skill note single-stock-analysis "经验内容"` 追加一行笔记，
  后续所有 AI 自动继承；
- **人工微调**：在 Streamlit 应用（`streamlit run app.py`）的 **Skills Manager** 页面
  可视化查看/编辑技能、把笔记晋升为正式步骤或删除噪音。

技能每次修改自动版本化并在 `skills/.backup/` 保留最近 10 版，可随时回滚。
```

Also update the README command list at the top (if it enumerates CLI commands) to include the new five commands.

- [ ] **Step 4: Full regression pass**

Run the whole suite file-by-file (sandbox-safe):

```powershell
$env:PYTHONPATH = "$PWD\libs;$PWD"
python -B -m pytest tests\test_skills.py tests\test_resolve.py -q --basetemp=tmp\reg1 > tmp\reg1.txt 2>&1
python -B -m pytest tests\test_analyze.py tests\test_overview.py -q --basetemp=tmp\reg2 > tmp\reg2.txt 2>&1
python -B -m pytest tests\test_cli.py tests\test_quotes.py -q --basetemp=tmp\reg3 > tmp\reg3.txt 2>&1
python -B -m pytest tests\test_pipeline.py tests\test_kline.py -q --basetemp=tmp\reg4 > tmp\reg4.txt 2>&1
python -B -m pytest tests\test_http.py tests\test_fundamentals.py tests\test_report.py -q --basetemp=tmp\reg5 > tmp\reg5.txt 2>&1
python -B -m pytest tests\test_composite.py tests\test_factors.py -q --basetemp=tmp\reg6 > tmp\reg6.txt 2>&1
```

Expected: all pass (app tests excluded — sandbox cannot run AppTest; covered by import smoke in Task 7).

---

## Self-Review Checklist (completed during planning)

- **Spec coverage:** resolve chain (Task 3), analyze + percentiles + verdict + risk flags + brief/evidence/json (Task 4), compare (Tasks 4-5), overview (Task 6), doctor (Task 6), skills store + evolution + guardrails (Task 1), 6 playbooks + AGENTS.md (Task 2), Skills Manager page (Task 7), real-data smoke + README (Task 8). Spec's "exit 2 on unresolvable" → cmd_ask returns 2. Spec's "compare/overview hard-fail without snapshot" → FileNotFoundError from resolve_snapshot propagates as SystemExit message.
- **Type consistency:** `Match(market, code, name, score, market_id)` used identically in resolve/analyze/CLI tests; `analyze_stock` returns the dict shape consumed by render_brief/render_evidence/to_json/fake_result; `run_checks` returns `(status, market, msg)` tuples consumed by render_checks/doctor_exit_code; skills API names match across Task 1 code, Task 5 CLI and Task 7 app.
- **Placeholders:** none — every step carries full code/content.
- **Known risks accepted:** smartbox endpoint may change (fallback = snapshot search; quirk recorded via skill note); AppTest for Skills Manager not automatable in sandbox (manual check + import smoke instead).


