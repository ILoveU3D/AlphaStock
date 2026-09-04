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


# ---------------------------------------------------------------------------
# Fees and board lots
# ---------------------------------------------------------------------------
def test_calc_fees_a_stock_min_commission():
    from value_genie import trade as tr
    # 100 shares @ 10 = 1000 gross: commission hits the 5 CNY floor
    f = tr.calc_fees("A", "600519", 100, 10.0, "buy")
    assert f["commission"] == 5.0
    assert f["transfer"] == round(1000 * config.A_TRANSFER_FEE, 2)
    assert "stamp" not in f
    f_sell = tr.calc_fees("A", "600519", 100, 10.0, "sell")
    assert f_sell["stamp"] == round(1000 * config.A_STAMP_SELL, 2)


def test_calc_fees_a_etf_no_stamp_no_transfer():
    from value_genie import trade as tr
    f = tr.calc_fees("A", "510300", 10000, 4.0, "sell")
    assert set(f) == {"commission"}
    assert f["commission"] == round(40000 * config.A_COMMISSION_RATE, 2)


def test_calc_fees_hk_platform_and_stamp():
    from value_genie import trade as tr
    # 100 shares @ 400 = 40000 gross: platform = max(20, 18) = 20
    f = tr.calc_fees("HK", "00700", 100, 400.0, "buy")
    assert f["platform"] == 20.0
    assert f["stamp"] == round(40000 * config.HK_STAMP, 2)
    small = tr.calc_fees("HK", "00700", 10, 20.0, "buy")
    assert small["platform"] == 18.0


def test_calc_fees_us_min_and_cap():
    from value_genie import trade as tr
    f = tr.calc_fees("US", "AAPL", 5, 230.0, "buy")
    assert f["platform"] == 1.99
    # 200000 shares @ 0.5 = 100000 gross; per-share 1980 > cap 1500
    big = tr.calc_fees("US", "AAPL", 200000, 0.5, "buy")
    assert big["platform"] == round(100000 * config.US_PLATFORM_CAP, 2)


def test_lot_rule_a_share_classes():
    from value_genie import trade as tr
    assert tr.lot_rule("A", "688795") == (200, 1)    # STAR board
    assert tr.lot_rule("A", "600519") == (100, 100)  # SH main
    assert tr.lot_rule("A", "000001") == (100, 100)  # SZ main
    assert tr.lot_rule("A", "510300") == (100, 100)  # SH ETF
    assert tr.lot_rule("A", "159915") == (100, 100)  # SZ ETF
    assert tr.lot_rule("A", "830000") == (100, 1)    # Beijing
    assert tr.lot_rule("US", "AAPL") == (1, 1)


def test_validate_qty_hk_lot(monkeypatch, trade_dir):
    from value_genie import trade as tr
    monkeypatch.setattr(tr, "hk_lot", lambda code: 100)
    assert tr.validate_qty("HK", "00700", 200) == 100
    with pytest.raises(tr.TradeError):
        tr.validate_qty("HK", "00700", 150)
    with pytest.raises(tr.TradeError):
        tr.validate_qty("HK", "00700", 50)
    monkeypatch.setattr(tr, "hk_lot", lambda code: None)
    assert tr.validate_qty("HK", "00700", 200, lot_override=200) == 200
    with pytest.raises(tr.TradeError):
        tr.validate_qty("HK", "00700", 200)


def test_validate_qty_a_and_us():
    from value_genie import trade as tr
    assert tr.validate_qty("A", "600519", 100) == 100
    with pytest.raises(tr.TradeError):
        tr.validate_qty("A", "600519", 150)
    assert tr.validate_qty("A", "688795", 201) == 200
    assert tr.validate_qty("US", "AAPL", 1) == 1
    with pytest.raises(tr.TradeError):
        tr.validate_qty("US", "AAPL", 0)
