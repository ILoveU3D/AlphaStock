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

    def test_smartbox_fallback_without_snapshot(self, tmp_path, monkeypatch):
        d = {"QuotationCodeTable": {"Data": [
            {"Code": "02555", "Name": "茶百道", "MktNum": "116"}]}}
        monkeypatch.setattr(rs.SB, "get_json", lambda *a, **k: d)
        # empty snapshot dir: no frames on disk, smartbox is the only source
        snap = tmp_path / "empty"
        snap.mkdir()
        out = rs.resolve("茶百道", snapshot_dir=snap, live=True)
        assert out and out[0].code == "02555" and out[0].market_id == "116"
