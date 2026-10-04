"""Tests for the model gather workbench (raw material aggregation)."""

import json

import pandas as pd
import pytest

from value_genie import config
from value_genie.model import gather as mg
from value_genie.model import store


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path


@pytest.fixture
def snap(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    pd.DataFrame([
        {"market": "A", "code": "688795", "name": "摩尔线程",
         "subsystem": "news", "kind": "news", "event_date": "2026-09-30",
         "impact": "neutral", "title": "MUSA 生态进展", "url": "",
         "source": "eastmoney", "payload": "{}"},
        {"market": "A", "code": "600900", "name": "长江电力",
         "subsystem": "news", "kind": "news", "event_date": "2026-09-30",
         "impact": "neutral", "title": "other", "url": "",
         "source": "eastmoney", "payload": "{}"},
    ]).to_csv(d / "event_radar.csv", index=False)
    return d


def _fake_history(market, code, limit=None):
    assert limit == mg.FULL_HISTORY_LIMIT   # gather asks full history
    return store.new_history(market, code, name="T", source="test",
                             currency="CNY",
                             years=[{"fy": y, "revenue": 100.0 + y}
                                    for y in (2023, 2024, 2025)])


def test_gather_aggregates_all_sources(mdir, snap, monkeypatch):
    monkeypatch.setattr(mg.mh, "fetch_history", _fake_history)
    from value_genie.fetch import profiles as fp
    monkeypatch.setattr(fp, "update_raw",
                        lambda m, c: {"id": f"{m}:{c}", "summary": "自述"})
    monkeypatch.setattr(mg, "gather_annual",
                        lambda m, c: ("/tmp/annual.json", None))
    monkeypatch.setattr(mg, "gather_filings",
                        lambda m, c: ("/tmp/filings.json", None))
    monkeypatch.setattr(mg, "gather_peers",
                        lambda m, c, s, explicit=None:
                        ("/tmp/peers.json", None))
    rep = mg.gather("A", "688795", snap_dir=snap)
    assert rep["gaps"] == []
    assert rep["gathered"]["annual"] == "/tmp/annual.json"
    assert rep["gathered"]["filings"] == "/tmp/filings.json"
    raw = store.raw_dir("A", "688795")
    h = json.loads((raw / "history.json").read_text(encoding="utf-8"))
    assert len(h["years"]) == 3
    p = json.loads((raw / "profile_raw.json").read_text(encoding="utf-8"))
    assert p["summary"] == "自述"
    ev = json.loads((raw / "intel.json").read_text(encoding="utf-8"))
    assert len(ev) == 1 and ev[0]["code"] == "688795"


def test_gather_fail_closed_per_source(mdir, snap, monkeypatch):
    monkeypatch.setattr(mg.mh, "fetch_history",
                        lambda m, c, limit=None: None)
    from value_genie.fetch import profiles as fp
    monkeypatch.setattr(fp, "update_raw", lambda m, c: None)
    monkeypatch.setattr(mg, "gather_annual",
                        lambda m, c: (None, "annual down"))
    monkeypatch.setattr(mg, "gather_filings",
                        lambda m, c: (None, "filings down"))
    monkeypatch.setattr(mg, "gather_peers",
                        lambda m, c, s, explicit=None:
                        (None, "not in master"))
    rep = mg.gather("A", "688795", snap_dir=snap)
    assert rep["gathered"]["history"] is None
    assert rep["gathered"]["profile_raw"] is None
    assert rep["gathered"]["annual"] is None
    assert len(rep["gaps"]) == 5
    # intel still gathered — one failure never blocks the others
    assert rep["gathered"]["intel"] is not None


def test_gather_skips_existing_unless_force(mdir, snap, monkeypatch):
    monkeypatch.setattr(mg.mh, "fetch_history", _fake_history)
    from value_genie.fetch import profiles as fp
    monkeypatch.setattr(fp, "update_raw",
                        lambda m, c: {"id": "x", "summary": "s"})
    monkeypatch.setattr(mg, "gather_annual",
                        lambda m, c: ("/tmp/a.json", None))
    monkeypatch.setattr(mg, "gather_filings",
                        lambda m, c: ("/tmp/f.json", None))
    monkeypatch.setattr(mg, "gather_peers",
                        lambda m, c, s, explicit=None:
                        ("/tmp/p.json", None))
    mg.gather("A", "688795", snap_dir=snap)
    calls = []
    monkeypatch.setattr(mg.mh, "fetch_history",
                        lambda m, c, limit=None: calls.append(1) or None)
    mg.gather("A", "688795", snap_dir=snap)
    assert calls == []                       # existing raw untouched
    rep = mg.gather("A", "688795", snap_dir=snap, force=True)
    assert calls == [1]                      # force regathers


def test_gather_peers_ai_explicit(mdir, snap, monkeypatch):
    """AI-chosen peer set works even when the target is absent from
    master.csv (new listings, out-of-universe holdings)."""
    import pandas as pd
    master = pd.DataFrame([
        {"market": "A", "code": "688256", "name": "寒武纪",
         "industry": "半导体", "market_cap": 1e11, "price": 600.0,
         "pe_ttm": None, "pb": 20.0},
        {"market": "A", "code": "688041", "name": "海光信息",
         "industry": "半导体", "market_cap": 8e10, "price": 100.0,
         "pe_ttm": 80.0, "pb": 8.0},
    ])
    from value_genie import report as rep_mod
    monkeypatch.setattr(rep_mod, "load_master", lambda s: master)
    p, gap = mg.gather_peers("A", "688795", snap,
                             explicit=["688256", "688041", "999999"])
    payload = __import__("json").loads(
        open(p, encoding="utf-8").read())
    assert payload["selection"] == "ai-explicit"
    assert len(payload["peers"]) == 2
    assert payload["target"]["note"].startswith("target absent")
    assert "999999" in gap


def test_gather_intel_missing_radar_is_gap(mdir, tmp_path, monkeypatch):
    monkeypatch.setattr(mg.mh, "fetch_history", _fake_history)
    from value_genie.fetch import profiles as fp
    monkeypatch.setattr(fp, "update_raw",
                        lambda m, c: {"id": "x", "summary": "s"})
    monkeypatch.setattr(mg, "gather_annual",
                        lambda m, c: ("/tmp/a.json", None))
    monkeypatch.setattr(mg, "gather_filings",
                        lambda m, c: ("/tmp/f.json", None))
    monkeypatch.setattr(mg, "gather_peers",
                        lambda m, c, s, explicit=None:
                        ("/tmp/p.json", None))
    empty_snap = tmp_path / "empty"
    empty_snap.mkdir()
    rep = mg.gather("A", "688795", snap_dir=empty_snap)
    assert any("event_radar.csv missing" in g for g in rep["gaps"])
