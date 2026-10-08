"""Tests for the value_genie CLI (python -m value_genie)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from value_genie import config
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
# masters-vote subcommand (QMF L1/L2; v2 wide pool, 2026-09-29)
# ---------------------------------------------------------------------------
def _mv_master() -> pd.DataFrame:
    """One clean compounder, one profit-spike veto, one all-fail."""
    def _scores():
        return {"value_score": 70.0, "growth_score": 80.0,
                "quality_score": 90.0, "safety_score": 70.0,
                "momentum_score": 50.0, "cashflow_score": 85.0}

    rows = [
        {"market": "A", "code": "000001", "name": "低波优质", "price": 10.0,
         "pe_ttm": 12.0, "pb": 1.2, "roe": 25.0, "gross_margin": 60.0,
         "debt_ratio": 30.0, "ocf_yield": 8.0, "fcf_yield": 7.0,
         "borrowed_dividend": 0, "dividend_yield": 3.0,
         "profit_yoy": 20.0, "ret_60d": 5.0,
         "volatility": 20.0, "pos_52w": 70.0, **_scores()},
        {"market": "A", "code": "000002", "name": "周期顶", "price": 5.0,
         "pe_ttm": 4.0, "pb": 0.8, "roe": 25.0, "gross_margin": 10.0,
         "debt_ratio": 40.0, "ocf_yield": 30.0, "fcf_yield": 20.0,
         "borrowed_dividend": 0, "dividend_yield": 2.0,
         "profit_yoy": 250.0, "ret_60d": 5.0,
         "volatility": 30.0, "pos_52w": 70.0, **_scores()},
        {"market": "A", "code": "000003", "name": "全挂", "price": 8.0,
         "pe_ttm": 60.0, "pb": 9.0, "roe": 2.0, "gross_margin": 5.0,
         "debt_ratio": 80.0, "ocf_yield": 0.5, "fcf_yield": 0.2,
         "borrowed_dividend": 1, "dividend_yield": 0.0,
         "profit_yoy": -30.0, "ret_60d": -20.0,
         "volatility": 80.0, "pos_52w": 5.0, **_scores()},
    ]
    return pd.DataFrame(rows)


@pytest.fixture()
def mv_snapshot(tmp_path, monkeypatch):
    # isolate the local-only profiles dir so real distillations can
    # never leak into the masters-vote overlay (Phase 5)
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "PROFILE_RAW_DIR",
                        tmp_path / "pdata" / "raw")
    snap = tmp_path / "snapshots" / "20260201"
    snap.mkdir(parents=True)
    _mv_master().to_csv(snap / "master.csv", index=False)
    return tmp_path


def test_masters_vote_wide_pool_is_default(mv_snapshot, capsys):
    # no --no-live: wide mode defers the network pass by design
    rc = main(["masters-vote", "--data-dir", str(mv_snapshot),
               "--no-check", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pool_mode"] == "wide"
    assert "NOT ranked" in data["ranking"] or "none" in data["ranking"]
    # 000001 in pool; 000002 vetoed by profit_spike; 000003 zero votes
    assert [r["code"] for r in data["rows"]] == ["000001"]
    assert data["veto_excluded"]["count"] == 1
    assert data["veto_excluded"]["profit_spike"] == 1
    # wide mode defers the live pass: the A-share row declares it
    assert data["rows"][0]["data_gap"] == "live pass pending (--check)"


def test_masters_vote_legacy_top_keeps_ranking(mv_snapshot, capsys):
    rc = main(["masters-vote", "--data-dir", str(mv_snapshot),
               "--no-check", "--no-live", "--top", "5", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pool_mode"] == "legacy_top"
    assert data["ranking"] == "core_score (three-core equal weight)"
    assert len(data["rows"]) == 1      # pool filter still applies


def test_masters_vote_check_live_pass(mv_snapshot, capsys):
    rc = main(["masters-vote", "--data-dir", str(mv_snapshot),
               "--no-check", "--no-live",
               "--check", "A:000001", "000003", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "live_check"
    ok, miss = data["rows"]
    assert ok["code"] == "000001"
    assert ok["data_gap"] == "live pass skipped (--no-live)"
    assert miss["error"] == "not in pool"   # 000003 passed zero gates


# ---------------------------------------------------------------------------
# masters-vote --horizon (D4 tactical mode, 2026-09-29)
# ---------------------------------------------------------------------------
def _write_tactical_snap(tmp_path):
    df = _mv_master()
    # 000001: uptrend + sweet-spot pullback; others don't matter (filtered)
    df["weekly_uptrend"] = [1.0, 1.0, 0.0]
    df["pullback_from_high"] = [-8.0, -1.0, -30.0]
    snap = tmp_path / "snapshots" / "20260201"
    snap.mkdir(parents=True)
    df.to_csv(snap / "master.csv", index=False)
    return tmp_path


def test_masters_vote_horizon_short(tmp_path, capsys):
    snap = _write_tactical_snap(tmp_path)
    rc = main(["masters-vote", "--data-dir", str(snap), "--no-check",
               "--horizon", "short", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["horizon"] == "short"
    assert "tactical" in data["ranking"]
    assert "DCF display-only" in data["ranking"]
    assert data["short_floor"]["business_min"] == 50.0
    assert data["short_floor"]["weekly_uptrend_required"] is True
    assert "-7%" in data["discipline"]["rules"]
    assert "1个月" in data["discipline"]["rules"]
    (row,) = data["rows"]
    assert row["code"] == "000001"
    assert row["short_floor"] is True       # real business + weekly trend
    assert row["pullback_sweet"] is True    # -8% sits in [-15, -5]


def test_masters_vote_horizon_floor_fails_closed(tmp_path, capsys):
    snap = _write_tactical_snap(tmp_path)
    m = pd.read_csv(snap / "snapshots" / "20260201" / "master.csv",
                    dtype={"code": str})
    m.loc[m["code"] == "000001", "weekly_uptrend"] = 0.0   # trend broken
    m.to_csv(snap / "snapshots" / "20260201" / "master.csv", index=False)
    rc = main(["masters-vote", "--data-dir", str(snap), "--no-check",
               "--horizon", "ultrashort", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    (row,) = data["rows"]
    assert row["short_floor"] is False      # no weekly trend, no floor
    assert "次日收盘" in data["discipline"]["rules"]


def test_masters_vote_horizon_text_discipline(tmp_path, capsys):
    snap = _write_tactical_snap(tmp_path)
    rc = main(["masters-vote", "--data-dir", str(snap), "--no-check",
               "--horizon", "short"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "短炒警示" in out
    assert "-7% 硬止损" in out
    assert "floor" in out                   # per-row floor flag


# ---------------------------------------------------------------------------
# profile subcommand + masters-vote culture overlay (Phase 5, 2026-09-29)
# ---------------------------------------------------------------------------
@pytest.fixture()
def pdirs(tmp_path, monkeypatch):
    """Redirect profiles/ + raw dirs into tmp (never touch local data)."""
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "PROFILE_RAW_DIR",
                        tmp_path / "data" / "profiles" / "raw")
    return tmp_path


def test_profile_assess_list_show(pdirs, capsys):
    rc = main(["profile", "assess", "600900", "--culture-score", "72",
               "--business-score", "86", "--moat-type", "resource_rent",
               "--benfen", "长年稳定高分红", "--verdict", "分红舱原型",
               "--agent", "kimi-k3", "--json"])
    assert rc == 0
    a = json.loads(capsys.readouterr().out)
    assert a["id"] == "A:600900"
    assert a["culture"]["score"] == 72.0
    assert a["raw_hash"] is None            # no raw fetched yet

    rc = main(["profile", "list", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["A:600900"]

    rc = main(["profile", "show", "600900", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["assessment"]["verdict"] == "分红舱原型"
    assert data["raw"] is None

    rc = main(["profile", "status", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["assessments"] == 1


def test_profile_assess_requires_a_score(pdirs, capsys):
    rc = main(["profile", "assess", "600900", "--verdict", "notes only"])
    assert rc == 1


def test_profile_assess_score_bounds(pdirs, capsys):
    rc = main(["profile", "assess", "600900", "--culture-score", "120"])
    assert rc == 1


def test_masters_vote_culture_distilled_overlay(
        mv_snapshot, pdirs, capsys):
    from value_genie import profile as prof
    prof.assess("A", "000001", culture_score=88, agent="kimi-k3")
    rc = main(["masters-vote", "--data-dir", str(mv_snapshot),
               "--no-check", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["culture_distilled"] == 1
    (row,) = data["rows"]
    assert row["code"] == "000001"
    assert row["core_culture"] == 88.0
    # core_score = skipna mean of the three cores (all present here)
    expected = (row["core_business"] + 88.0 + row["core_dcf"]) / 3
    assert row["core_score"] == pytest.approx(expected)
    assert prof.CULTURE_DISTILLED in row["core_gaps"]


def test_masters_vote_without_distillations_unchanged(
        mv_snapshot, pdirs, capsys):
    rc = main(["masters-vote", "--data-dir", str(mv_snapshot),
               "--no-check", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "culture_distilled" not in data
    (row,) = data["rows"]
    assert row["core_culture"] is None      # veto-only, NaN -> null




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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
        monkeypatch.setattr("value_genie.resolve.resolve",
                            lambda q, **k: [])
        assert main(["ask", "nonsense"]) == 2
        assert "no match" in capsys.readouterr().err

    def test_compare(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
            lambda d=None, market=None: ("FAIL", "no snapshots found"))
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
            lambda d=None, market=None: ("WARN", "snapshot age: 3 days"))
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

    def test_ask_scopes_gate_to_stock_market(self, capsys, monkeypatch):
        """ask resolves the stock first and passes its market into the
        gate, so a closed/stale A-share market never blocks a US answer
        (National-Day artifact, 2026-10-08)."""
        seen = {}

        def fake_gate(d=None, market=None):
            seen["market"] = market
            return ("PASS", "data is fresh")

        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate", fake_gate)
        monkeypatch.setattr(
            "value_genie.resolve.resolve",
            lambda q, **k: [Match("US", "AAPL", "Apple", 100.0, "105")])
        monkeypatch.setattr(
            "value_genie.analyze.analyze_stock",
            lambda m, snapshot_dir=None, horizon=None: fake_result(m))
        rc = main(["ask", "AAPL"])
        assert rc == 0
        assert seen["market"] == "US"

    def test_ask_no_check_skips_gate(self, capsys, monkeypatch):
        called = []
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None, market=None: called.append(d) or ("FAIL", "should not run"))
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
            lambda d=None, market=None: ("FAIL", "no snapshots"))
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
            lambda d=None, market=None: ("FAIL", "no snapshots"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
        monkeypatch.setattr("value_genie.resolve.resolve",
                            lambda q, **k: [])
        rc = main(["intel", "不存在股"])
        assert rc == 2

    def test_freshness_fail_blocks(self, capsys, monkeypatch):
        monkeypatch.setattr("value_genie.doctor.freshness_gate",
                            lambda d=None, market=None: ("FAIL", "no snapshot"))
        rc = main(["intel", "摩尔线程"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "[FRESHNESS BLOCKED]" in captured.err

    def test_no_check_skips_gate(self, capsys, monkeypatch):
        called = []
        monkeypatch.setattr(
            "value_genie.doctor.freshness_gate",
            lambda d=None, market=None: called.append(1) or ("FAIL", "x"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
                            lambda d=None, market=None: ("PASS", "ok"))
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
