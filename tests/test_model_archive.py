"""Tests for the model archive (AI-written dossier, lint quality bar)."""

import json

import pytest

from value_genie import config
from value_genie.model import archive as marc
from value_genie.model import store


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path


def _write_full(mdir, code="688795", market="A"):
    """Fill a dossier past the lint bar (three-piece minimum + narratives
    with weight bases + enough text vs a small raw)."""
    raw = store.raw_dir(market, code)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "history.json").write_text(json.dumps(
        {"years": [{"fy": 2024, "revenue": 100.0, "note": "x" * 200}]}),
        encoding="utf-8")
    big = "飞轮论证文本。" * 200          # well over 30% of raw volume
    a = marc.write_fields(market, code, {
        "business_flywheel.text": big,
        "culture.vision": big,
        "culture.current_state": "现状描述",
        "reverse_dcf.implied_world": big,
        "reverse_dcf.my_world": "我信的世界叙事",
    }, reason="首次建模")
    a = marc.write_fields(market, code, {
        "world_narratives": [
            {"name": "w1", "world": "世界发生X→飞轮接通",
             "weight": 0.6, "weight_basis": "证据Y支撑"}],
    }, reason="世界假设")
    return a


def test_new_archive_roundtrip(mdir):
    a = marc.new_archive("A", "688795", name="摩尔线程")
    marc.save_archive(a)
    b = marc.load_archive("A", "688795")
    assert b["id"] == "A:688795"
    assert b["business_flywheel"]["text"] == ""
    assert marc.load_archive("A", "999999") is None


def test_write_requires_reason(mdir):
    with pytest.raises(ValueError):
        marc.write_fields("A", "688795",
                          {"business_flywheel.text": "x"}, reason="")


def test_write_appends_changelog(mdir):
    marc.write_fields("A", "688795",
                      {"business_flywheel.text": "飞轮"}, reason="初稿")
    a = marc.write_fields("A", "688795",
                          {"culture.vision": "愿景"}, reason="补充")
    keys = [c["key"] for c in a["changelog"]]
    assert keys == ["business_flywheel.text", "culture.vision"]
    assert all(c["reason"] for c in a["changelog"])


def test_write_rejects_unknown_key(mdir):
    with pytest.raises(ValueError):
        marc.write_fields("A", "688795", {"wacc": "0.1"}, reason="r")


def test_write_at_file(mdir, tmp_path):
    worlds = tmp_path / "worlds.json"
    worlds.write_text(json.dumps(
        [{"name": "w", "world": "...", "weight": 1.0,
          "weight_basis": "b"}]), encoding="utf-8")
    a = marc.write_fields("A", "688795",
                          {"world_narratives": f"@{worlds}"},
                          reason="载入世界")
    assert a["world_narratives"][0]["name"] == "w"
    md = tmp_path / "flywheel.md"
    md.write_text("长文本飞轮", encoding="utf-8")
    a = marc.write_fields("A", "688795",
                          {"business_flywheel.text": f"@{md}"},
                          reason="载入飞轮")
    assert a["business_flywheel"]["text"] == "长文本飞轮"


def test_lint_incomplete_when_empty(mdir):
    a = marc.new_archive("A", "688795")
    marc.save_archive(a)
    lint = marc.lint(a)
    assert lint["complete"] is False
    assert any("business_flywheel" in m for m in lint["missing"])
    assert any("no raw material" in m for m in lint["missing"])
    assert any("no world_narratives" in w for w in lint["weak_weights"])


def test_lint_qualified_after_full_write(mdir):
    lint = marc.lint(_write_full(mdir))
    assert lint["complete"] is True
    assert lint["missing"] == [] and lint["weak_weights"] == []
    assert lint["text_ratio"] >= config.MODEL_LINT_MIN_TEXT_RATIO


def test_lint_flags_weight_without_basis(mdir):
    a = _write_full(mdir)
    a = marc.write_fields("A", "688795", {
        "world_narratives": [{"name": "w2", "world": "x", "weight": 1.0,
                              "weight_basis": ""}],
    }, reason="无依据权重")
    lint = marc.lint(a)
    assert lint["complete"] is False
    assert any("weight without basis" in w for w in lint["weak_weights"])


def test_lint_flags_thin_dossier(mdir):
    raw = store.raw_dir("A", "688795")
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "history.json").write_text(json.dumps({"big": "x" * 100000}),
                                      encoding="utf-8")
    a = marc.new_archive("A", "688795")
    marc.save_archive(a)
    lint = marc.lint(a)
    assert any("thinner than the annual report bar" in m
               for m in lint["missing"])


def test_status_lists_dossiers(mdir):
    assert marc.status() == []
    _write_full(mdir)
    marc.save_archive(marc.new_archive("US", "AAPL"))
    rows = marc.status()
    assert len(rows) == 2
    by_id = {r["id"]: r for r in rows}
    assert by_id["A:688795"]["complete"] is True
    assert by_id["US:AAPL"]["complete"] is False
