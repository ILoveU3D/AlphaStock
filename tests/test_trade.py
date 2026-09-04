"""Tests for the AI virtual-portfolio (trade) engine. Standalone."""

import json
from pathlib import Path

import pytest

from value_genie import config


@pytest.fixture
def trade_dir(tmp_path, monkeypatch):
    d = tmp_path / "trading"
    monkeypatch.setattr(config, "TRADING_DIR", d)
    return d


@pytest.fixture
def snap(tmp_path):
    d = tmp_path / "snapshots" / "20260905"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"fx_hkdcny": 0.92, "fx_usdcny": 7.2}), encoding="utf-8")
    for name, text in {
        "us_quotes.csv": "code,name,market_id,price\nAAPL,Apple,105,230.0\n",
        "a_quotes.csv": "code,name,market_id,price\n600519,Moutai,1,1500.0\n",
        "hk_quotes.csv": "code,name,market_id,price\n00700,Tencent,116,400.0\n",
    }.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def test_fetch_hk_lot_parses_trade_unit(monkeypatch):
    from value_genie.fetch import fundamentals as f
    monkeypatch.setattr(
        f.DC, "get_json",
        lambda url, params=None, **kw: {"result": {"data": [
            {"SECUCODE": "00005.HK", "TRADE_UNIT": 400}]}})
    assert f.fetch_hk_lot("00005") == 400


def test_fetch_hk_lot_none_on_empty(monkeypatch):
    from value_genie.fetch import fundamentals as f
    monkeypatch.setattr(f.DC, "get_json",
                        lambda url, params=None, **kw: {"result": {"data": []}})
    assert f.fetch_hk_lot("09999") is None


# ---------------------------------------------------------------------------
# Season CRUD
# ---------------------------------------------------------------------------
def test_new_season_defaults(trade_dir):
    from value_genie import trade as tr
    s = tr.new_season("s001", name="第一期", base="USD", capital=2000.0,
                      markets=["US", "HK"])
    assert s["status"] == "active"
    assert s["cash"] == {"CNY": 0.0, "HKD": 0.0, "USD": 2000.0}
    assert s["rules"]["markets"] == ["US", "HK"]
    assert s["rules"]["fx_spread"] == config.TRADE_FX_SPREAD
    assert s["totals"] == {"deposited": 0.0, "withdrawn": 0.0}
    assert tr.load_season("s001")["id"] == "s001"
    assert [x["id"] for x in tr.list_seasons()] == ["s001"]


def test_new_season_rejects_bad_input(trade_dir):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=100.0, markets=["US"])
    with pytest.raises(ValueError):
        tr.new_season("S001", base="USD", capital=100.0, markets=["US"])
    with pytest.raises(ValueError):
        tr.new_season("s001", base="USD", capital=100.0, markets=["US"])
    with pytest.raises(ValueError):
        tr.new_season("s002", base="EUR", capital=100.0, markets=["US"])
    with pytest.raises(ValueError):
        tr.new_season("s003", base="USD", capital=0.0, markets=["US"])
    with pytest.raises(ValueError):
        tr.new_season("s004", base="USD", capital=100.0, markets=[])


def test_season_rule_status_delete(trade_dir):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=100.0, markets=["US"])
    s = tr.update_rules("s001", markets=["A", "US"])
    assert s["rules"]["markets"] == ["A", "US"]
    s = tr.set_season_status("s001", "paused")
    assert s["status"] == "paused"
    s = tr.set_season_status("s001", "active")
    assert s["status"] == "active"
    tr.set_season_status("s001", "closed")
    tr.delete_season("s001")
    with pytest.raises(FileNotFoundError):
        tr.load_season("s001")
