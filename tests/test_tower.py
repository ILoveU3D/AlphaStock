"""Tests for value_genie.tower (cognitive tower brick store)."""

from pathlib import Path

from value_genie import tower as tw

SAMPLE = """---
id: dcf-universal-law
title: DCF 普适法则
statement: 一切价值皆是未来现金流的折现——股票如此，职业如此，时间亦如此。
source: conversation:2026-09-08
status: axiom
tags:
  - epistemology
  - value
links: []
version: 1
created_at: 2026-09-08T00:00:00
updated_at: 2026-09-18T12:00:00
---
## 论证
Any value = future benefit stream discounted by uncertainty.

## Field Notes
- [2026-09-18 14:00] (ai) 首次成砖，自 06 号技能普世法则迁入
"""

BRICK = """---
id: compounding
title: 复利
statement: 判断力是否随时间复利增长，是唯一诚实的记分牌。
source: conversation:2026-09-08
status: law
tags:
  - value
links:
  - "derives-from:dcf-universal-law"
version: 1
created_at: 2026-09-08T00:00:00
updated_at: 2026-09-08T00:00:00
---
## 论证
append-only 知识是护城河。
"""


def make_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tower"
    d.mkdir()
    (d / "dcf-universal-law.md").write_text(SAMPLE, encoding="utf-8")
    return d


class TestParse:
    def test_parses_frontmatter_and_body(self):
        b = tw.parse_brick(SAMPLE)
        assert b.id == "dcf-universal-law"
        assert b.status == "axiom"
        assert b.tags == ["epistemology", "value"]
        assert b.links == []

    def test_render_roundtrip_preserves_escapes(self):
        # statements often carry quotes; render -> parse must not
        # accumulate backslash layers (silent brick corruption)
        b = tw.parse_brick(SAMPLE)
        b.statement = '巴菲特说"市场先生"是 \\ 寓言'
        for _ in range(3):
            b = tw.parse_brick(tw.render_brick(b))
        assert b.statement == '巴菲特说"市场先生"是 \\ 寓言'
        assert b.version == 1
        assert b.body.startswith("## 论证")

    def test_missing_required_field_raises(self):
        bad = SAMPLE.replace("statement: 一切价值皆是未来现金流的折现——股票如此，职业如此，时间亦如此。\n", "")
        try:
            tw.parse_brick(bad)
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "statement" in str(exc)

    def test_bad_status_raises(self):
        bad = SAMPLE.replace("status: axiom", "status: dogma")
        try:
            tw.parse_brick(bad)
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError:
            pass

    def test_axiom_id_is_fixed(self):
        bad = SAMPLE.replace("id: dcf-universal-law", "id: my-axiom")
        try:
            tw.parse_brick(bad)
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError:
            pass

    def test_bad_link_syntax_raises(self):
        bad = SAMPLE.replace("links: []", "links:\n  - sponsored-by:foo")
        try:
            tw.parse_brick(bad)
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError:
            pass

    def test_render_roundtrip(self):
        b = tw.parse_brick(SAMPLE)
        again = tw.parse_brick(tw.render_brick(b))
        assert again.id == b.id
        assert again.tags == b.tags
        assert again.links == b.links
        assert again.statement == b.statement
        assert again.version == b.version
        assert again.created_at == b.created_at
        assert again.body.strip() == b.body.strip()

    def test_render_roundtrip_empty_lists(self):
        b = tw.Brick(id="x-brick", title="X", statement="s", source="ai",
                     status="observation")
        again = tw.parse_brick(tw.render_brick(b))
        assert again.tags == []
        assert again.links == []


class TestLoad:
    def test_loads_good_reports_bad(self, tmp_path):
        d = make_dir(tmp_path)
        (d / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
        bricks, errors = tw.load_bricks(d)
        ids = [b.id for b in bricks]
        assert ids == ["dcf-universal-law"]
        assert len(errors) == 1
        assert "broken.md" in errors[0]

    def test_multiple_axioms_reported(self, tmp_path):
        d = make_dir(tmp_path)
        # a second axiom file violates the fixed-id rule -> parse error
        (d / "second-axiom.md").write_text(
            SAMPLE.replace("id: dcf-universal-law", "id: second-axiom"),
            encoding="utf-8")
        bricks, errors = tw.load_bricks(d)
        assert any("second-axiom" in e for e in errors)
        assert [b.id for b in bricks] == ["dcf-universal-law"]

    def test_find_brick(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.find_brick(d, "dcf-universal-law")
        assert b.title == "DCF 普适法则"
        try:
            tw.find_brick(d, "nope")
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "available" in str(exc)

    def test_field_notes(self, tmp_path):
        b = tw.parse_brick(SAMPLE)
        notes = tw.field_notes(b)
        assert len(notes) == 1
        assert notes[0][1] == "ai"
        assert "首次成砖" in notes[0][2]


class TestEvolution:
    def test_add_brick(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        loaded = tw.find_brick(d, "compounding")
        assert loaded.status == "law"
        assert loaded.links == ["derives-from:dcf-universal-law"]
        assert loaded.version == 1  # first save: no bump yet

    def test_add_duplicate_id_rejected(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        try:
            tw.add_brick(d, tw.parse_brick(BRICK))
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "already exists" in str(exc)

    def test_add_axiom_rejected(self, tmp_path):
        d = make_dir(tmp_path)
        fake_axiom = tw.Brick(id="another-axiom", title="A", statement="s",
                              source="ai", status="axiom")
        try:
            tw.add_brick(d, fake_axiom)
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "axiom" in str(exc)

    def test_add_unknown_link_target_rejected(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.Brick(id="orphan", title="O", statement="s", source="ai",
                     status="hypothesis",
                     links=["derives-from:not-seeded"])
        try:
            tw.add_brick(d, b)
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "not found" in str(exc)

    def test_note_bumps_version_and_backs_up(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        tw.append_note(d, "compounding", "first lesson")
        again = tw.find_brick(d, "compounding")
        assert again.version == 2
        notes = tw.field_notes(again)
        assert any("first lesson" in n[2] for n in notes)
        backups = list((d / ".backup" / "compounding").glob("*.md"))
        assert len(backups) == 1

    def test_link_add_and_validation(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        tw.add_link(d, "compounding", "applies-to:dcf-universal-law")
        again = tw.find_brick(d, "compounding")
        assert "applies-to:dcf-universal-law" in again.links
        try:
            tw.add_link(d, "compounding", "sponsored-by:foo")
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError:
            pass
        try:
            tw.add_link(d, "compounding", "tension:missing-target")
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "not found" in str(exc)

    def test_set_status_requires_reason(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        try:
            tw.set_brick(d, "compounding", status="principle")
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError as exc:
            assert "--reason" in str(exc)

    def test_set_status_archives_migration(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        tw.set_brick(d, "compounding", status="principle",
                     reason="demoted pending re-verification")
        again = tw.find_brick(d, "compounding")
        assert again.status == "principle"
        notes = tw.field_notes(again)
        assert any("law -> principle" in n[2] for n in notes)
        assert any("re-verification" in n[2] for n in notes)

    def test_set_cannot_grant_axiom(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        try:
            tw.set_brick(d, "compounding", status="axiom", reason="try")
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError:
            pass

    def test_set_refuted_requires_reason(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        try:
            tw.set_brick(d, "compounding", status="refuted")
            assert False, "expected TowerFormatError"
        except tw.TowerFormatError:
            pass
        tw.set_brick(d, "compounding", status="refuted",
                     reason="counter-evidence logged")
        again = tw.find_brick(d, "compounding")
        assert again.status == "refuted"
        # refuted bricks are never deleted
        assert (d / "compounding.md").exists()

    def test_set_tags_and_body(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.parse_brick(BRICK)
        tw.add_brick(d, b)
        tw.set_brick(d, "compounding", add_tags=["meta"],
                     drop_tags=["value"], body="## 论证\nrewritten\n")
        again = tw.find_brick(d, "compounding")
        assert again.tags == ["meta"]
        assert "rewritten" in again.body

    def test_created_at_set_once(self, tmp_path):
        d = make_dir(tmp_path)
        b = tw.Brick(id="fresh", title="F", statement="s", source="ai",
                     status="observation")
        tw.add_brick(d, b)
        first = tw.find_brick(d, "fresh")
        assert first.created_at != ""
        tw.append_note(d, "fresh", "note")
        again = tw.find_brick(d, "fresh")
        assert again.created_at == first.created_at
        assert again.updated_at >= first.updated_at


class TestSearchStats:
    def test_search_matches_id_title_statement_tags_body(self, tmp_path):
        d = make_dir(tmp_path)
        tw.add_brick(d, tw.parse_brick(BRICK))
        assert [b.id for b in tw.search_bricks(d, "compounding")] == ["compounding"]
        assert [b.id for b in tw.search_bricks(d, "复利")] == ["compounding"]
        assert "dcf-universal-law" in [b.id for b in tw.search_bricks(d, "DCF")]
        assert tw.search_bricks(d, "zzz-not-there") == []

    def test_stats_counts(self, tmp_path):
        d = make_dir(tmp_path)
        tw.add_brick(d, tw.parse_brick(BRICK))
        tw.append_note(d, "compounding", "lesson one")
        stats = tw.tower_stats(d)
        assert stats["total_bricks"] == 2
        assert stats["by_status"]["axiom"] == 1
        assert stats["by_status"]["law"] == 1
        assert stats["by_kind"]["conversation"] == 2
        assert stats["total_notes"] == 2  # seed note + appended one
        assert stats["tower_age_days"] >= 0
        assert stats["axiom"] == ["dcf-universal-law"]
