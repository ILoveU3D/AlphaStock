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
