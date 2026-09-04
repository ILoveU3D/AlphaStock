"""Tests for the value_genie CLI (python -m value_genie)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from value_genie.__main__ import (_parse_markets, _parse_weights,
                                  build_parser, main)


def _master() -> pd.DataFrame:
    return pd.DataFrame([
        {"market": "A", "code": "600519", "name": "Moutai",
         "industry": "Liquor", "price": 1500.0, "market_cap": 1.9e12,
         "pe_ttm": 25.0, "pb": 8.0, "rev_yoy": 15.0, "profit_yoy": 18.0,
         "roe": 30.0, "gross_margin": 91.0, "net_margin": 50.0,
         "report_date": "2026-06-30", "value_score": 80.0,
         "growth_score": 70.0, "quality_score": 60.0, "safety_score": 50.0},
        {"market": "US", "code": "AAPL", "name": "Apple",
         "industry": "Electronics", "price": 220.0, "market_cap": 3.3e12,
         "pe_ttm": 30.0, "pb": 40.0, "rev_yoy": 8.0, "profit_yoy": 10.0,
         "roe": 90.0, "gross_margin": 46.0, "net_margin": 25.0,
         "report_date": "2025-12-31", "value_score": 50.0,
         "growth_score": 60.0, "quality_score": 70.0, "safety_score": 40.0},
    ])


@pytest.fixture()
def snapshot(tmp_path):
    snap = tmp_path / "snapshots" / "20260201"
    snap.mkdir(parents=True)
    _master().to_csv(snap / "master.csv", index=False)
    return tmp_path


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------
def test_parse_markets():
    assert _parse_markets("a, hk ,US") == ["A", "HK", "US"]
    assert _parse_markets(None, default=["A"]) == ["A"]
    with pytest.raises(SystemExit):
        _parse_markets("XX")


def test_parse_weights():
    assert _parse_weights(["value=0.4", "growth=0.2"]) == {
        "value": 0.4, "growth": 0.2}
    assert _parse_weights(None) == {}
    with pytest.raises(SystemExit):
        _parse_weights(["value"])          # missing '='
    with pytest.raises(SystemExit):
        _parse_weights(["value=abc"])      # not a number


# ---------------------------------------------------------------------------
# screen subcommand
# ---------------------------------------------------------------------------
def test_screen_writes_outputs(snapshot, tmp_path, capsys):
    out_dir = tmp_path / "out"
    rc = main(["screen", "--data-dir", str(snapshot),
               "--out-dir", str(out_dir), "--top", "2"])
    assert rc == 0
    csv_path = out_dir / "20260201_balanced.csv"
    md_path = out_dir / "20260201_balanced.md"
    assert csv_path.exists() and md_path.exists()

    df = pd.read_csv(csv_path, dtype={"code": str})
    assert len(df) == 2
    assert df.iloc[0]["code"] == "600519"       # highest balanced composite
    assert list(df["rank"]) == [1, 2]

    text = md_path.read_text(encoding="utf-8")
    assert "# Value Genie - 20260201 - balanced" in text
    assert "- **stocks**: 2" in text

    console = capsys.readouterr().out
    assert "Value Genie screen" in console
    assert "strategy : balanced" in console
    assert "600519" in console


def test_screen_custom_weights_and_markets(snapshot, tmp_path):
    out_dir = tmp_path / "out"
    rc = main(["screen", "--data-dir", str(snapshot),
               "--out-dir", str(out_dir), "--set", "value=1.0",
               "--markets", "US"])
    assert rc == 0
    assert (out_dir / "20260201_custom.csv").exists()
    df = pd.read_csv(out_dir / "20260201_custom.csv", dtype={"code": str})
    assert list(df["code"]) == ["AAPL"]        # US-only, ranked by value


def test_screen_explicit_snapshot_and_preset(snapshot, tmp_path):
    out_dir = tmp_path / "out"
    rc = main(["screen", "--data-dir", str(snapshot),
               "--out-dir", str(out_dir), "--snapshot", "20260201",
               "--preset", "magic_formula"])
    assert rc == 0
    assert (out_dir / "20260201_magic_formula.csv").exists()


def test_screen_no_snapshots(tmp_path):
    with pytest.raises(SystemExit, match="no snapshots found"):
        main(["screen", "--data-dir", str(tmp_path)])


def test_screen_no_qualified_stocks(tmp_path):
    snap = tmp_path / "snapshots" / "20260201"
    snap.mkdir(parents=True)
    # only two pillars present -> below the 3-pillar minimum
    pd.DataFrame([{"market": "A", "code": "600519", "name": "Moutai",
                   "value_score": 80.0, "growth_score": 70.0}]
                 ).to_csv(snap / "master.csv", index=False)
    with pytest.raises(SystemExit, match="no stocks passed"):
        main(["screen", "--data-dir", str(tmp_path)])


def test_screen_unknown_preset_rejected(snapshot):
    with pytest.raises(SystemExit):
        main(["screen", "--data-dir", str(snapshot),
              "--preset", "not_a_preset"])


def test_screen_json_pure_stdout(snapshot, tmp_path, capsys):
    out_dir = tmp_path / "out"
    rc = main(["screen", "--data-dir", str(snapshot),
               "--out-dir", str(out_dir), "--top", "2", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)               # stdout is pure JSON
    assert data["snapshot"] == "20260201"
    assert data["strategy"] == "balanced"
    assert data["count"] == 2
    assert [r["code"] for r in data["rows"]] == ["600519", "AAPL"]
    assert data["rows"][0]["pe_ttm"] == 25.0   # full precision kept
    assert "Value Genie screen" not in out     # no banner chatter
    assert not (out_dir / "20260201_balanced.csv").exists()  # no exports


# ---------------------------------------------------------------------------
# fetch subcommand
# ---------------------------------------------------------------------------
def test_fetch_calls_pipeline(snapshot, tmp_path, monkeypatch, capsys):
    from value_genie import __main__ as cli

    calls = []

    def fake_run_fetch(markets=None, data_dir=None, refresh=False,
                       quiet=False):
        calls.append({"markets": markets, "data_dir": data_dir,
                      "refresh": refresh})
        return Path(data_dir) / "snapshots" / "20260201"

    monkeypatch.setattr(cli, "run_fetch", fake_run_fetch)
    rc = main(["fetch", "--markets", "A,HK",
               "--data-dir", str(tmp_path)])
    assert rc == 0
    assert calls == [{"markets": ["A", "HK"], "data_dir": str(tmp_path),
                      "refresh": False}]
    assert "next:" not in capsys.readouterr().out   # no human coaching


def test_fetch_refresh_flag(snapshot, tmp_path, monkeypatch):
    from value_genie import __main__ as cli

    seen = {}

    def fake_run_fetch(markets=None, data_dir=None, refresh=False,
                       quiet=False):
        seen["refresh"] = refresh
        return Path(data_dir) / "snapshots" / "20260201"

    monkeypatch.setattr(cli, "run_fetch", fake_run_fetch)
    rc = main(["fetch", "--data-dir", str(tmp_path), "--refresh"])
    assert rc == 0
    assert seen["refresh"] is True


def test_fetch_bad_market(tmp_path):
    with pytest.raises(SystemExit):
        main(["fetch", "--markets", "XX", "--data-dir", str(tmp_path)])


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
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = main(["ask", "Alpha Co"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Alpha Co" in out
        assert "verdict" in out
        assert "also matched" not in out

    def test_ask_shows_alternatives(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1"),
                            Match("HK", "02555", "茶百道", 50.0, "116")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = main(["ask", "alpha"])
        assert rc == 0
        assert "also matched" in capsys.readouterr().out

    def test_ask_json(self, capsys, monkeypatch):
        import json
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = main(["ask", "Alpha Co", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["code"] == "600001"

    def test_ask_no_match_returns_2(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr("value_genie.resolve.resolve",
                            lambda q, **k: [])
        assert main(["ask", "nonsense"]) == 2
        assert "no match" in capsys.readouterr().out

    def test_compare(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
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
        rc = main(["compare", "Alpha Co"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Alpha Co" in out

    def test_compare_json(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
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
        rc = main(["compare", "Alpha Co", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["stocks"][0]["code"] == "600001"
        assert data["stocks"][0]["pe_pctile"] == 83.3


class TestOverviewCli:
    def test_overview(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.overview.market_overview",
            lambda markets=None, top_n=10, data_dir=None: {
                "snapshot": "20260901", "markets": {}})
        rc = main(["overview"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "20260901" in out

    def test_overview_json(self, capsys, monkeypatch):
        top = pd.DataFrame([
            {"rank": 1, "code": "600519", "name": "Moutai",
             "price": 1500.0, "pe_ttm": 25.0, "rev_yoy": 15.0,
             "roe": 30.0, "composite_score": 60.0,
             "drawdown_52w": float("nan")}])
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.overview.market_overview",
            lambda markets=None, top_n=10, data_dir=None: {
                "snapshot": "20260901",
                "markets": {"A": {"candidates": 100,
                                  "median_pe": 20.0, "median_pb": 2.0,
                                  "median_rev_yoy": 5.0,
                                  "top_sectors": {"Liquor": 1},
                                  "top": top}}})
        rc = main(["overview", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["snapshot"] == "20260901"
        row = data["markets"]["A"]["top"][0]
        assert row["code"] == "600519"
        assert row["pe_ttm"] == 25.0
        assert row["drawdown_52w"] is None    # NaN -> null
        assert data["markets"]["A"]["candidates"] == 100


class TestFreshnessGate:
    """The freshness gate is enforced on ask / compare / overview."""

    def test_ask_blocked_on_fail(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: ("FAIL", "no snapshots found"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "X", 100.0, "1")])
        rc = main(["ask", "X"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "BLOCKED" in err
        assert "fetch" in err

    def test_ask_warns_but_proceeds_on_warn(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: ("WARN", "snapshot age: 3 days"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = main(["ask", "Alpha Co"])
        err = capsys.readouterr().err
        assert rc == 0
        assert "WARN" in err

    def test_ask_no_check_skips_gate(self, capsys, monkeypatch):
        called = []
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: called.append(d) or ("FAIL", "should not run"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None: fake_result(m))
        rc = main(["ask", "Alpha Co", "--no-check"])
        assert rc == 0
        assert called == []

    def test_compare_blocked_on_fail(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: ("FAIL", "no snapshots"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "X", 100.0, "1")])
        rc = main(["compare", "X", "Y"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "BLOCKED" in err

    def test_overview_blocked_on_fail(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: ("FAIL", "no snapshots"))
        rc = main(["overview"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "BLOCKED" in err


class TestDoctorCli:
    def test_doctor_exit_zero_on_pass(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.run_checks",
                            lambda data_dir=None: [("PASS", "-", "ok")])
        rc = main(["doctor"])
        assert rc == 0
        assert "ok" in capsys.readouterr().out

    def test_doctor_exit_one_on_fail(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.run_checks",
            lambda data_dir=None: [("FAIL", "-", "no snapshots found")])
        rc = main(["doctor"])
        assert rc == 1
        assert "fetch" in capsys.readouterr().out

    def test_doctor_json(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "value_genie.doctor.run_checks",
            lambda data_dir=None: [("PASS", "-", "ok"),
                                   ("WARN", "A", "kline lag 3 day(s)")])
        rc = main(["doctor", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["status"] == "WARN"
        assert data["checks"][0]["message"] == "ok"
        assert data["checks"][1]["market"] == "A"


_HEALTH = {
    "rows": [{"market": "A", "code": "600519", "name": "Moutai",
              "qty": 100.0, "cost": 1500.0, "price": 1600.0,
              "price_src": "live", "currency": "CNY",
              "value": 160000.0, "pnl": 10000.0, "pnl_pct": 6.67,
              "value_cny": 160000.0, "industry": "Liquor",
              "composite_score": 60.0, "pe_ttm": 25.0, "ret_60d": 5.0,
              "drawdown_52w": -10.0, "weight": 100.0}],
    "total_cny": 160000.0, "fx": {"CNY": 1.0},
    "industries": {"Liquor": 160000.0},
    "market_dist": {"A": 160000.0}, "flags": [],
}


class TestRecommendJsonCli:
    def test_recommend_json(self, capsys, monkeypatch):
        fake = {"user": SimpleNamespace(id="u1", name="U1"),
                "snapshot": "20260201", "strategy": "u1",
                "horizon": None,
                "candidates": pd.DataFrame([
                    {"market": "A", "code": "600519", "name": "Moutai",
                     "composite_score": 60.0, "pe_ttm": 25.0}]),
                "health": _HEALTH}
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.recommend.build_recommendation",
            lambda *a, **k: fake)
        rc = main(["recommend", "--user", "u1", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["user"] == "u1"
        assert data["candidates"][0]["code"] == "600519"
        assert data["health"]["total_cny"] == 160000.0
        assert data["health"]["rows"][0]["pnl_pct"] == 6.67


class TestHoldingListJsonCli:
    def test_holding_list_json(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.users.load_user",
            lambda uid: SimpleNamespace(id="u1", name="U1", holdings=[],
                                        style={}))
        monkeypatch.setattr(
            "value_genie.recommend.holdings_health",
            lambda user, snap_dir=None: _HEALTH)
        rc = main(["holding", "list", "u1", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert rc == 0
        assert data["rows"][0]["code"] == "600519"
        assert data["rows"][0]["weight"] == 100.0
        assert not out.startswith("== holdings")   # pure JSON, no banner


class TestSkillCli:
    def test_skill_list_real_dir(self, capsys, monkeypatch):
        rc = main(["skill", "list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "single-stock-analysis" in out

    def test_skill_note_roundtrip(self, capsys, monkeypatch, tmp_path):
        import shutil as _sh
        from value_genie import config as cfg, skills as sk
        d = tmp_path / "skills"
        _sh.copytree(cfg.SKILLS_DIR, d)
        monkeypatch.setattr(cfg, "SKILLS_DIR", d)
        rc = main(["skill", "note", "single-stock-analysis",
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
        rc = main(["skill", "edit", "single-stock-analysis",
                   "--add-trigger", "X还能买吗"])
        assert rc == 0
        assert "X还能买吗" in sk.find_skill(d,
                                            "single-stock-analysis").triggers


class TestParserSurface:
    def test_parser_accepts_new_commands(self):
        p = build_parser()
        assert p.parse_args(["ask", "X", "--evidence"]).evidence
        assert p.parse_args(["ask", "X", "--json"]).json
        assert p.parse_args(["ask", "X", "--no-check"]).no_check
        assert p.parse_args(["compare", "X", "Y"]).stocks == ["X", "Y"]
        assert p.parse_args(["compare", "X", "--no-check"]).no_check
        assert p.parse_args(["overview", "--top", "5"]).top == 5
        assert p.parse_args(["overview", "--no-check"]).no_check
        assert p.parse_args(["skill", "note", "id", "text"]).text == "text"

    def test_parser_json_flags_everywhere(self):
        p = build_parser()
        for argv in (["screen"], ["compare", "X"], ["overview"],
                     ["recommend"], ["doctor"]):
            assert p.parse_args(argv + ["--json"]).json, argv
        assert p.parse_args(
            ["holding", "list", "me", "--json"]).json
