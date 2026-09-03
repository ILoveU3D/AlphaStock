"""Tests for value_genie.recommend (screening + holdings health)."""

import json

import pandas as pd
import pytest

from value_genie import recommend as rec
from value_genie import users as usr
from value_genie.resolve import Match


def _master() -> pd.DataFrame:
    return pd.DataFrame([
        {"market": "A", "code": "600519", "name": "Moutai",
         "industry": "Liquor", "price": 1500.0, "market_cap": 1.9e12,
         "pe_ttm": 25.0, "pb": 8.0, "ps": 10.0, "rev_yoy": 15.0,
         "profit_yoy": 18.0, "roe": 30.0, "gross_margin": 91.0,
         "net_margin": 50.0, "drawdown_52w": -10.0, "ret_60d": 5.0,
         "report_date": "2026-06-30", "value_score": 80.0,
         "growth_score": 70.0, "quality_score": 60.0,
         "safety_score": 50.0, "composite_score": 72.0},
        {"market": "A", "code": "000858", "name": "Wuliangye",
         "industry": "Liquor", "price": 130.0, "market_cap": 5.0e11,
         "pe_ttm": 15.0, "pb": 4.0, "ps": 5.0, "rev_yoy": 10.0,
         "profit_yoy": 12.0, "roe": 25.0, "gross_margin": 75.0,
         "net_margin": 37.0, "drawdown_52w": -5.0, "ret_60d": 3.0,
         "report_date": "2026-06-30", "value_score": 90.0,
         "growth_score": 60.0, "quality_score": 55.0,
         "safety_score": 60.0, "composite_score": 76.0},
        {"market": "US", "code": "AAPL", "name": "Apple",
         "industry": "Electronics", "price": 220.0, "market_cap": 3.3e12,
         "pe_ttm": 30.0, "pb": 40.0, "ps": 8.0, "rev_yoy": 8.0,
         "profit_yoy": 10.0, "roe": 90.0, "gross_margin": 46.0,
         "net_margin": 25.0, "drawdown_52w": -12.0, "ret_60d": -2.0,
         "report_date": "2025-12-31", "value_score": 50.0,
         "growth_score": 60.0, "quality_score": 70.0,
         "safety_score": 40.0, "composite_score": 58.0},
    ])


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Fake data dir: snapshots/20260201 + users dir."""
    snap = tmp_path / "snapshots" / "20260201"
    snap.mkdir(parents=True)
    _master().to_csv(snap / "master.csv", index=False)
    pd.DataFrame([
        {"market": "US", "price": 220.0, "code": "AAPL",
         "market_id": "106", "name": "Apple"},
    ]).to_csv(snap / "us_quotes.csv", index=False)
    pd.DataFrame([
        {"market": "A", "price": 1500.0, "code": "600519",
         "market_id": "1", "name": "Moutai"},
    ]).to_csv(snap / "a_quotes.csv", index=False)
    (snap / "manifest.json").write_text(
        json.dumps({"created_at": "2026-02-01T09:00:00",
                    "fx_hkdcny": 0.85}), encoding="utf-8")
    monkeypatch.setattr(usr.config, "USERS_DIR", tmp_path / "users")
    return tmp_path


@pytest.fixture()
def fake_live(monkeypatch):
    """Deterministic live quotes keyed by secid market_id+code."""
    quotes = {"1.600519": 1600.0, "116.00116": 10.0, "106.AAPL": 230.0}

    def _fake(match):
        price = quotes.get(f"{match.market_id}.{match.code}")
        if price is None:
            return None
        return {"price": price, "name": match.name, "code": match.code}

    monkeypatch.setattr(rec, "live_quote", _fake)
    return quotes


def _user_with_holdings(style=True):
    usr.create_user("me", name="tester")
    if style:
        usr.set_style("me", weights={"value": 0.6, "quality": 0.4})
    # reload: set_style persisted its own copy
    u = usr.load_user("me")
    usr.add_holding(u, Match("A", "600519", "Moutai", 100.0, "1"),
                    qty=100, cost=1500.0, opened="2025-03-15")
    usr.save_user(u)
    return u


# ---------------------------------------------------------------------------
# Holdings health
# ---------------------------------------------------------------------------
def test_holdings_health_pnl_and_weights(data_dir, fake_live):
    snap = data_dir / "snapshots" / "20260201"
    u = _user_with_holdings()
    health = rec.holdings_health(u, snap)

    r = health["rows"][0]
    assert r["price"] == 1600.0 and r["price_src"] == "live"
    assert r["pnl"] == pytest.approx(10000.0)
    assert r["pnl_pct"] == pytest.approx(100 / 15)     # 6.67%
    assert r["composite_score"] is not None            # in master
    assert health["total_cny"] == pytest.approx(160000.0)

    # single holding -> weight 100% -> concentration observation
    assert any("单一持仓仓位" in f for f in health["flags"])
    assert any("行业集中" in f for f in health["flags"])


def test_holdings_health_off_master_and_snapshot_fallback(
        data_dir, fake_live, monkeypatch):
    snap = data_dir / "snapshots" / "20260201"
    u = usr.create_user("me")
    usr.add_holding(u, Match("HK", "00116", "Chow Sang Sang", 100.0, "116"),
                    qty=200, cost=9.5)
    # kill live for HK -> fallback to snapshot price (none for HK) -> None
    monkeypatch.setattr(rec, "live_quote", lambda m: None)
    health = rec.holdings_health(u, snap)
    r = health["rows"][0]
    assert r["price"] is None
    assert any("现价缺失" in f for f in health["flags"])
    assert any("不在快照候选池" in f for f in health["flags"])


def test_holdings_health_us_excluded_without_fx(data_dir, fake_live,
                                                monkeypatch):
    snap = data_dir / "snapshots" / "20260201"
    monkeypatch.setattr(rec, "_fetch_fx_usdcny_live", lambda: None)
    u = usr.create_user("me")
    usr.add_holding(u, Match("US", "AAPL", "Apple", 100.0, "106"),
                    qty=10, cost=180.0)
    health = rec.holdings_health(u, snap)
    r = health["rows"][0]
    # live quote resolves via us_quotes market_id 106
    assert r["price"] == 230.0
    # but USD has no FX rate -> excluded from weights, stated verbatim
    assert r["weight"] is None
    assert health["total_cny"] is None
    assert any("USD" in f and "汇率" in f for f in health["flags"])


def test_holdings_health_us_with_live_fx_fallback(data_dir, fake_live,
                                                  monkeypatch):
    snap = data_dir / "snapshots" / "20260201"
    monkeypatch.setattr(rec, "_fetch_fx_usdcny_live", lambda: 7.25)
    u = usr.create_user("me")
    usr.add_holding(u, Match("US", "AAPL", "Apple", 100.0, "106"),
                    qty=10, cost=180.0)
    health = rec.holdings_health(u, snap)
    r = health["rows"][0]
    assert r["value_cny"] == pytest.approx(230.0 * 10 * 7.25)
    assert health["total_cny"] == pytest.approx(230.0 * 10 * 7.25)
    assert r["weight"] == pytest.approx(100.0)
    assert not any("USD" in f and "汇率" in f for f in health["flags"])


def test_holdings_health_snapshot_price_fallback(data_dir, fake_live,
                                                 monkeypatch):
    snap = data_dir / "snapshots" / "20260201"
    u = _user_with_holdings()
    monkeypatch.setattr(rec, "live_quote", lambda m: None)
    health = rec.holdings_health(u, snap)
    r = health["rows"][0]
    assert r["price"] == 1500.0 and r["price_src"] == "snapshot"


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------
def test_build_recommendation_excludes_holdings(data_dir, fake_live):
    snap = str(data_dir / "snapshots" / "20260201")
    _user_with_holdings()
    result = rec.build_recommendation("me", snap_dir=snap, top_n=5)
    assert result["strategy"] == "me"                 # user style used
    codes = list(result["candidates"]["code"])
    assert "600519" not in codes                      # holding excluded
    assert "000858" in codes
    assert result["snapshot"] == "20260201"
    assert result["health"]["total_cny"] == pytest.approx(160000.0)


def test_build_recommendation_falls_back_to_balanced(data_dir, fake_live):
    snap = str(data_dir / "snapshots" / "20260201")
    _user_with_holdings(style=False)                  # no style set
    result = rec.build_recommendation("me", snap_dir=snap, top_n=5)
    assert result["strategy"] == "balanced"


def test_render_recommend_contains_sections(data_dir, fake_live):
    snap = str(data_dir / "snapshots" / "20260201")
    _user_with_holdings()
    result = rec.build_recommendation("me", snap_dir=snap, top_n=5)
    text = rec.render_recommend(result)
    assert "Value Genie recommend" in text
    assert "持仓体检" in text
    assert "组合观察" in text
    assert "推荐候选" in text
    assert "Moutai" in text
    assert "结构化事实" in text


def test_render_holdings_empty_portfolio(data_dir):
    u = usr.create_user("me")
    health = rec.holdings_health(u, None)
    assert rec.render_holdings(health) == "-- 持仓体检 --\n(空仓)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_recommend(data_dir, fake_live, capsys):
    from value_genie.__main__ import main
    _user_with_holdings()
    rc = main(["recommend", "--user", "me",
               "--data-dir", str(data_dir), "--no-check", "--top", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "recommend" in out
    # holdings section shows the position; candidate section excludes it
    assert "Moutai" in out
    candidates = out.split("推荐候选")[1]
    assert "000858" in candidates
    assert "600519" not in candidates


def test_cli_recommend_unknown_user(data_dir, fake_live):
    from value_genie.__main__ import main
    with pytest.raises(SystemExit):
        main(["recommend", "--user", "ghost",
              "--data-dir", str(data_dir), "--no-check"])


def test_cli_holding_list(data_dir, fake_live, capsys):
    from value_genie.__main__ import main
    _user_with_holdings()
    rc = main(["holding", "list", "me", "--data-dir", str(data_dir),
               "--no-check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Moutai" in out and "持仓体检" in out
