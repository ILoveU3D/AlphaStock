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
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
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
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
        rc = main(["ask", "alpha"])
        cap = capsys.readouterr()
        assert rc == 0
        # resolution hints are diagnostics: stderr, never the data channel
        assert "also matched" in cap.err
        assert "also matched" not in cap.out

    def test_ask_json_pure_with_alternatives(self, capsys, monkeypatch):
        """--json stdout must stay pure JSON even when the resolution
        hint fires (hint goes to stderr)."""
        import json
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1"),
                            Match("HK", "02555", "茶百道", 50.0, "116")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
        rc = main(["ask", "alpha", "--json"])
        cap = capsys.readouterr()
        assert rc == 0
        data = json.loads(cap.out)  # raises if stdout is not pure JSON
        assert data["code"] == "600001"
        assert "resolved:" in cap.err

    def test_ask_data_dir_selects_snapshot(self, capsys, monkeypatch,
                                           tmp_path):
        """--data-dir must reach resolve/analyze, not be silently ignored."""
        snap = tmp_path / "snapshots" / "20260905"
        snap.mkdir(parents=True)
        (snap / "master.csv").write_text(
            "market,code,name\nA,600001,Alpha Co\n", encoding="utf-8")
        seen = {}
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])

        def _fake_analyze(m, snapshot_dir=None, horizon=None):
            seen["snapshot_dir"] = snapshot_dir
            return fake_result(m)

        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock", _fake_analyze)
        rc = main(["ask", "Alpha Co", "--data-dir", str(tmp_path),
                   "--json"])
        assert rc == 0
        assert seen["snapshot_dir"] is not None
        assert str(seen["snapshot_dir"]).endswith("20260905")

    def test_ask_json(self, capsys, monkeypatch):
        import json
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "600001", "Alpha Co", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
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
        assert "no match" in capsys.readouterr().err

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
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
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
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
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


class TestIntelCmd:
    def _patch(self, monkeypatch, report_result):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "688795", "摩尔线程-U", 100.0, "1")])
        monkeypatch.setattr(
            "value_genie.intel.report.build_intel_report",
            lambda m, snapshot_dir=None, asof=None: report_result)

    def _result(self):
        return {"match": Match("A", "688795", "摩尔线程-U", 100.0, "1"),
                "snapshot": "20260909", "asof": "2026-09-09",
                "radar": {"unlock_pct_30d": 12.0, "intel_red": 1.0},
                "events": [], "eq": [],
                "notices": [], "ratings": [], "news": []}

    def test_renders_report(self, capsys, monkeypatch):
        self._patch(monkeypatch, self._result())
        rc = main(["intel", "摩尔线程"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "舆情情报: 摩尔线程-U (A/688795)" in out
        assert "[事件雷达]" in out

    def test_json_pure_stdout(self, capsys, monkeypatch):
        self._patch(monkeypatch, self._result())
        rc = main(["intel", "摩尔线程", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["match"]["code"] == "688795"

    def test_no_match_returns_2(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr("value_genie.resolve.resolve",
                            lambda q, **k: [])
        rc = main(["intel", "不存在股"])
        assert rc == 2

    def test_freshness_fail_blocks(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("FAIL", "no snapshot"))
        rc = main(["intel", "摩尔线程"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "[FRESHNESS BLOCKED]" in captured.err

    def test_no_check_skips_gate(self, capsys, monkeypatch):
        called = []
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None: called.append(1) or ("FAIL", "x"))
        self._patch(monkeypatch, self._result())
        rc = main(["intel", "摩尔线程", "--no-check"])
        assert rc == 0
        assert called == []


# ---------------------------------------------------------------------------
# ask intel integration (P2 Task 8)
# ---------------------------------------------------------------------------
from value_genie.analyze import risk_flags


class TestAskIntelIntegration:
    def _fake_result(self, intel=None):
        base = fake_result(Match("A", "688795", "摩尔线程-U", 100.0, "1"))
        base["intel"] = intel or {}
        # fake_result stubs risk_flags as a static list; re-run the real
        # function so the intel key is evaluated
        base["risk_flags"] = risk_flags(base)
        return base

    def test_risk_flag_when_intel_red(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "688795", "摩尔线程-U", 100.0, "1")])
        result = self._fake_result(intel={
            "unlock_pct_30d": 12.0, "unlock_pct_90d": 12.0,
            "holder_cut_flag": 1.0, "dilution_flag": 0.0,
            "eq_flags": 2.0, "intel_red": 1.0})
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: result)
        rc = main(["ask", "摩尔线程"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "intel red" in out
        assert "解禁" in out and "减持" in out

    def test_no_flag_when_clean(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None: ("PASS", "ok"))
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("A", "688795", "摩尔线程-U", 100.0, "1")])
        result = self._fake_result(intel={
            "unlock_pct_30d": 0.0, "holder_cut_flag": 0.0,
            "dilution_flag": 0.0, "eq_flags": 0.0, "intel_red": 0.0})
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: result)
        rc = main(["ask", "摩尔线程"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "intel red" not in out


# ---------------------------------------------------------------------------
# profile subcommand (公司档案库)
# ---------------------------------------------------------------------------
@pytest.fixture()
def preg(tmp_path, monkeypatch):
    """Isolated profile registry rooted at tmp_path."""
    from value_genie import config as _cfg
    from value_genie import profile as pm
    monkeypatch.setattr(_cfg, "PROFILES_DIR", tmp_path / "profiles")
    return pm


def _make_profile(pm, market="A", code="600519", name="Moutai",
                  assess=False, restale=False):
    p = pm.Profile(id=f"{market}:{code}", market=market, code=code,
                   name=name)
    pm.set_raw(p, {"summary": "白酒龙头，赤水河畔", "main_business":
                   "茅台酒及系列酒的生产与销售",
                   "source": "test", "meta": {"chairman": "丁雄军"}})
    if assess:
        pm.set_assessment(
            p, business={"score": 85.0, "moat_type": "brand"},
            culture={"score": 70.0, "founder_led": False},
            verdict="复利机器")
        if restale:        # raw changes after assessing -> stale
            pm.set_raw(p, {"summary": "白酒龙头（年报更新）",
                           "main_business": "茅台酒及系列酒",
                           "source": "test"})
    pm.save_profile(p)
    return p


def _stub_resolve(monkeypatch, market="A", code="600519", name="Moutai"):
    from value_genie.resolve import Match
    monkeypatch.setattr("value_genie.resolve.resolve",
                        lambda q, **k: [Match(market, code, name, 100.0)])


class TestProfileCLI:
    def test_list_json_pure(self, preg, capsys):
        _make_profile(preg)
        _make_profile(preg, code="000858", name="Wuliangye")
        rc = main(["profile", "list", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2
        assert {d["id"] for d in data} == {"A:000858", "A:600519"}
        assert "raw_fresh" in data[0] and "assessment_stale" in data[0]

    def test_list_stale_filter(self, preg, capsys):
        _make_profile(preg, assess=True, restale=True)      # stale
        _make_profile(preg, code="000858", name="Wuliangye",
                      assess=True)                          # valid
        rc = main(["profile", "list", "--stale"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "A:600519" in out and "STALE" in out
        assert "A:000858" not in out

    def test_list_empty_registry(self, preg, capsys):
        rc = main(["profile", "list"])
        assert rc == 1
        assert "no profiles" in capsys.readouterr().out

    def test_show_json(self, preg, capsys, monkeypatch):
        _make_profile(preg, assess=True)
        _stub_resolve(monkeypatch)
        rc = main(["profile", "show", "600519", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["raw"]["summary"].startswith("白酒龙头")
        assert data["assessment"]["business"]["score"] == 85.0
        assert data["assessment_stale"] is False

    def test_show_missing_profile(self, preg, capsys, monkeypatch):
        _stub_resolve(monkeypatch)
        rc = main(["profile", "show", "600519"])
        assert rc == 1
        assert "no profile" in capsys.readouterr().err

    def test_assess_writeback(self, preg, capsys, monkeypatch):
        _make_profile(preg)
        _stub_resolve(monkeypatch)
        rc = main(["profile", "assess", "600519",
                   "--business-score", "80", "--culture-score", "65",
                   "--moat-type", "brand", "--founder-led",
                   "--benfen", "十年不提价", "--verdict", "复利机器"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "business=80" in out and "culture=65" in out
        p = preg.load_profile("A", "600519")
        a = p.assessment
        assert a.business["score"] == 80.0
        assert a.business["moat_type"] == "brand"
        assert a.culture["founder_led"] is True
        assert a.culture["benfen_evidence"] == ["十年不提价"]
        assert a.verdict == "复利机器"
        assert a.raw_hash == p.raw.content_hash

    def test_assess_invalid_score_fails(self, preg, capsys, monkeypatch):
        _make_profile(preg)
        _stub_resolve(monkeypatch)
        rc = main(["profile", "assess", "600519",
                   "--business-score", "150"])
        assert rc == 1
        assert "0-100" in capsys.readouterr().err

    def test_assess_empty_raw_fails(self, preg, capsys, monkeypatch):
        preg.save_profile(preg.Profile(id="A:600519", market="A",
                                       code="600519", name="Moutai"))
        _stub_resolve(monkeypatch)
        rc = main(["profile", "assess", "600519",
                   "--business-score", "80"])
        assert rc == 1
        assert "raw zone is empty" in capsys.readouterr().err

    def test_assess_nothing_given_fails(self, preg, capsys, monkeypatch):
        _make_profile(preg)
        _stub_resolve(monkeypatch)
        rc = main(["profile", "assess", "600519"])
        assert rc == 1
        assert "nothing to assess" in capsys.readouterr().err

    def test_update_and_incremental_skip(self, snapshot, preg, capsys,
                                         monkeypatch):
        from value_genie.fetch import profiles as pf
        payload = {"summary": "源文", "main_business": "主业",
                   "source": "test", "meta": {}}
        monkeypatch.setitem(pf.FETCHERS, "A", lambda code: dict(payload))
        monkeypatch.setitem(pf.FETCHERS, "US", lambda code: dict(payload))
        monkeypatch.setattr(pf.time, "sleep", lambda s: None)
        rc = main(["profile", "update", "--data-dir", str(snapshot)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "fetched=2" in out
        assert preg.load_profile("A", "600519").raw.summary == "源文"
        # second run: everything inside the freshness window -> skipped
        rc = main(["profile", "update", "--data-dir", str(snapshot)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "skipped_fresh=2" in out and "fetched=0" in out

    def test_update_failed_fetcher_rc1(self, snapshot, preg, capsys,
                                       monkeypatch):
        from value_genie.fetch import profiles as pf
        monkeypatch.setitem(pf.FETCHERS, "A", lambda code: None)
        monkeypatch.setitem(pf.FETCHERS, "US", lambda code: None)
        monkeypatch.setattr(pf.time, "sleep", lambda s: None)
        rc = main(["profile", "update", "--data-dir", str(snapshot)])
        assert rc == 1
        # failed fetch leaves no file behind
        with pytest.raises(FileNotFoundError):
            preg.load_profile("A", "600519")

    def test_fetch_one(self, preg, capsys, monkeypatch):
        from value_genie.fetch import profiles as pf
        _stub_resolve(monkeypatch)
        monkeypatch.setitem(
            pf.FETCHERS, "A",
            lambda code: {"summary": "简介", "main_business": "主业",
                          "source": "test", "meta": {}})
        monkeypatch.setattr(pf.time, "sleep", lambda s: None)
        rc = main(["profile", "fetch", "600519"])
        assert rc == 0
        assert preg.load_profile("A", "600519").raw.summary == "简介"

    def test_status_json(self, snapshot, preg, capsys):
        _make_profile(preg, assess=True)          # 600519 covered+assessed
        rc = main(["profile", "status", "--data-dir", str(snapshot),
                   "--json"])
        assert rc == 0
        stats = json.loads(capsys.readouterr().out)
        assert stats["pool"] == 2                 # master has 600519+AAPL
        assert stats["pool_covered"] == 1
        assert stats["pool_missing"] == 1
        assert stats["profiles"] == 1
        assert stats["assessed"] == 1
        assert stats["assessment_stale"] == 0
        assert stats["blend_weight"] == 0.5
