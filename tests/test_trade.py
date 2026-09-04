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
    # master.csv makes the dir a valid snapshot for report.resolve_snapshot
    # (used by the CLI's --data-dir path)
    (d / "master.csv").write_text(
        "market,code,name,price\nUS,AAPL,Apple,230.0\n", encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Trading days and settlement
# ---------------------------------------------------------------------------
def test_next_trading_day_skips_weekend():
    from value_genie import trade as tr
    # Fri 2026-09-04 -> +1 trading day = Mon 2026-09-07
    assert tr.next_trading_day("2026-09-04", 1) == "2026-09-07"
    # Sat 2026-09-05 -> +2 trading days = Tue 2026-09-08
    assert tr.next_trading_day("2026-09-05", 2) == "2026-09-08"


def _season_with_settling(trade_dir):
    from value_genie import trade as tr
    s = tr.new_season("s001", base="HKD", capital=10000.0, markets=["HK"])
    s["cash"]["HKD"] = 0.0  # all funds are in the settling queue
    s["settling"] = [{
        "currency": "HKD", "amount": 5000.0, "origin_market": "HK",
        "available_date": "2026-09-08", "fx_date": "2026-09-09"}]
    tr.save_season(s)
    return s


def test_settle_due_moves_only_matured(trade_dir):
    from value_genie import trade as tr
    _season_with_settling(trade_dir)
    s = tr.load_season("s001")
    settled = tr.settle_due(s, "2026-09-08")
    assert settled == [] and s["cash"]["HKD"] == 0.0
    settled = tr.settle_due(s, "2026-09-09")
    assert s["cash"]["HKD"] == 5000.0 and s["settling"] == []
    assert len(settled) == 1


def test_spendable_and_deduct_for_buy(trade_dir):
    from value_genie import trade as tr
    _season_with_settling(trade_dir)
    s = tr.load_season("s001")
    s["cash"]["HKD"] = 1000.0
    assert tr.spendable_for_buy(s, "HK", "HKD", "2026-09-07") == 1000.0
    assert tr.spendable_for_buy(s, "HK", "HKD", "2026-09-08") == 6000.0
    assert tr.spendable_for_buy(s, "US", "USD", "2026-09-08") == 0.0
    tr._deduct_buy(s, "HK", "HKD", "2026-09-08", 4500.0)
    assert s["cash"]["HKD"] == 0.0
    assert s["settling"][0]["amount"] == 1500.0


# ---------------------------------------------------------------------------
# Buy / sell
# ---------------------------------------------------------------------------
PRICES = {("US", "AAPL"): 230.0, ("A", "600519"): 1500.0,
          ("HK", "00700"): 400.0}


@pytest.fixture
def prices(monkeypatch):
    from value_genie import trade as tr
    def fake(market, code, name, snap_dir=None):
        p = PRICES.get((market, code))
        return (p, "live") if p is not None else (None, "")
    monkeypatch.setattr(tr, "live_price", fake)


@pytest.fixture
def hk_lot_100(monkeypatch):
    from value_genie import trade as tr
    monkeypatch.setattr(tr, "hk_lot", lambda code: 100)


def _match(market, code, name):
    from value_genie.resolve import Match
    return Match(market, code, name, 100.0, "")


def test_buy_us_full_flow(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US"])
    fill = tr.buy("s001", _match("US", "AAPL", "Apple"), qty=5,
                  note="franchise at fair price",
                  snap_dir=snap, today="2026-09-04")
    assert fill["action"] == "buy"
    assert fill["gross"] == 1150.0
    assert fill["fees"] == {"platform": 1.99}
    assert fill["cash_delta"] == -1151.99
    s = tr.load_season("s001")
    assert s["cash"]["USD"] == round(2000.0 - 1151.99, 2)
    pos = s["positions"][0]
    assert pos["qty"] == 5.0
    assert pos["avg_cost"] == round(1151.99 / 5, 4)
    assert pos["last_buy_date"] == "2026-09-04"
    assert s["fills"][0]["note"] == "franchise at fair price"


def test_buy_rejects_market_outside_rules(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=20000.0, markets=["US"])
    with pytest.raises(tr.TradeError, match="not allowed"):
        tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
               snap_dir=snap, today="2026-09-04")


def test_buy_insufficient_cash(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=100.0, markets=["US"])
    with pytest.raises(tr.TradeError, match="insufficient"):
        tr.buy("s001", _match("US", "AAPL", "Apple"), qty=5,
               snap_dir=snap, today="2026-09-04")


def test_buy_no_price_rejected(trade_dir, snap, monkeypatch):
    from value_genie import trade as tr
    monkeypatch.setattr(tr, "live_price",
                        lambda m, c, n, snap_dir=None: (None, ""))
    tr.new_season("s001", base="USD", capital=10000.0, markets=["US"])
    with pytest.raises(tr.TradeError, match="no price"):
        tr.buy("s001", _match("US", "AAPL", "Apple"), qty=1,
               snap_dir=snap, today="2026-09-04")


def test_buy_paused_season_rejected(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=10000.0, markets=["US"])
    tr.set_season_status("s001", "paused")
    with pytest.raises(tr.TradeError, match="paused"):
        tr.buy("s001", _match("US", "AAPL", "Apple"), qty=1,
               snap_dir=snap, today="2026-09-04")


def test_buy_hk_uses_board_lot(trade_dir, snap, prices, hk_lot_100):
    from value_genie import trade as tr
    tr.new_season("s001", base="HKD", capital=100000.0, markets=["HK"])
    with pytest.raises(tr.TradeError, match="board lot"):
        tr.buy("s001", _match("HK", "00700", "Tencent"), qty=50,
               snap_dir=snap, today="2026-09-04")
    fill = tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
                  snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    assert s["positions"][0]["lot"] == 100
    assert fill["fees"] == {"platform": 20.0, "stamp": 40.0}


# ---------------------------------------------------------------------------
# Sell
# ---------------------------------------------------------------------------
def test_sell_a_share_t_plus_1(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="CNY", capital=200000.0, markets=["A"])
    tr.buy("s001", _match("A", "600519", "Moutai"), qty=100,
           snap_dir=snap, today="2026-09-04")
    with pytest.raises(tr.TradeError, match=r"T\+1"):
        tr.sell("s001", _match("A", "600519", "Moutai"), qty=100,
                snap_dir=snap, today="2026-09-04")
    fill = tr.sell("s001", _match("A", "600519", "Moutai"), qty=100,
                   snap_dir=snap, today="2026-09-07")
    assert fill["realized_pnl"] is not None
    s = tr.load_season("s001")
    assert s["positions"] == []
    e = s["settling"][0]
    assert e["currency"] == "CNY"
    assert e["available_date"] == "2026-09-08"
    assert e["fx_date"] == "2026-09-08"
    # gross 150000 - fees (comm 37.5 + transfer 1.5 + stamp 75)
    assert e["amount"] == round(150000.0 - 114.0, 2)


def test_sell_hk_t1_rebuy_t2_fx(trade_dir, snap, prices, hk_lot_100):
    from value_genie import trade as tr
    tr.new_season("s001", base="HKD", capital=100000.0, markets=["HK"])
    tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
           snap_dir=snap, today="2026-09-04")
    tr.sell("s001", _match("HK", "00700", "Tencent"), qty=100,
            snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    e = s["settling"][0]
    assert e["available_date"] == "2026-09-07"   # T+1 same-market rebuy
    assert e["fx_date"] == "2026-09-08"          # T+2 cross-market/fx
    # T+1: can rebuy HK with the settling proceeds
    fill2 = tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
                   snap_dir=snap, today="2026-09-07")
    assert fill2["action"] == "buy"
    s = tr.load_season("s001")
    assert s["settling"][0]["amount"] > 0        # partially consumed


def test_sell_rejects_over_selling_and_unknown(trade_dir, snap, prices,
                                               hk_lot_100):
    from value_genie import trade as tr
    tr.new_season("s001", base="HKD", capital=100000.0, markets=["HK"])
    tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
           snap_dir=snap, today="2026-09-04")
    with pytest.raises(tr.TradeError, match="exceeds"):
        tr.sell("s001", _match("HK", "00700", "Tencent"), qty=200,
                snap_dir=snap, today="2026-09-07")
    with pytest.raises(tr.TradeError, match="no position"):
        tr.sell("s001", _match("US", "AAPL", "Apple"), qty=1,
                snap_dir=snap, today="2026-09-07")


def test_sell_market_dropped_from_rules_still_allowed(trade_dir, snap,
                                                      prices, hk_lot_100):
    from value_genie import trade as tr
    tr.new_season("s001", base="HKD", capital=100000.0, markets=["HK"])
    tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
           snap_dir=snap, today="2026-09-04")
    tr.update_rules("s001", markets=["US"])
    fill = tr.sell("s001", _match("HK", "00700", "Tencent"), qty=100,
                   snap_dir=snap, today="2026-09-05")
    assert fill["action"] == "sell"


# ---------------------------------------------------------------------------
# FX and cash movements
# ---------------------------------------------------------------------------
def test_fx_exchange_with_spread(trade_dir, snap):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US", "HK"])
    fill = tr.fx("s001", "USD", "HKD", 100.0,
                 snap_dir=snap, today="2026-09-04")
    rate = 7.2 / 0.92
    expected = round(100.0 * rate * (1 - config.TRADE_FX_SPREAD), 2)
    assert fill["received"] == expected
    s = tr.load_season("s001")
    assert s["cash"]["USD"] == 1900.0
    assert s["cash"]["HKD"] == expected


def test_fx_rejects_bad_requests(trade_dir, snap):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=100.0, markets=["US"])
    with pytest.raises(tr.TradeError, match="insufficient"):
        tr.fx("s001", "USD", "HKD", 500.0, snap_dir=snap, today="2026-09-04")
    with pytest.raises(tr.TradeError, match="must be one of"):
        tr.fx("s001", "USD", "EUR", 10.0, snap_dir=snap, today="2026-09-04")
    with pytest.raises(tr.TradeError, match="from == to"):
        tr.fx("s001", "USD", "USD", 10.0, snap_dir=snap, today="2026-09-04")


def test_fx_blocked_while_hk_proceeds_unsettled(trade_dir, snap, prices,
                                                hk_lot_100):
    from value_genie import trade as tr
    tr.new_season("s001", base="HKD", capital=50000.0, markets=["HK"])
    tr.buy("s001", _match("HK", "00700", "Tencent"), qty=100,
           snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    s["cash"]["HKD"] = 0.0        # force reliance on settling proceeds
    tr.save_season(s)
    tr.sell("s001", _match("HK", "00700", "Tencent"), qty=100,
            snap_dir=snap, today="2026-09-04")
    with pytest.raises(tr.TradeError, match="insufficient HKD"):
        tr.fx("s001", "HKD", "USD", 1000.0,
              snap_dir=snap, today="2026-09-07")
    tr.fx("s001", "HKD", "USD", 1000.0, snap_dir=snap, today="2026-09-08")


def test_cash_deposit_withdraw_totals(trade_dir, snap):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US"])
    tr.cash_move("s001", "deposit", 500.0, "USD",
                 snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    assert s["cash"]["USD"] == 2500.0
    assert s["totals"]["deposited"] == 500.0
    tr.cash_move("s001", "withdraw", 200.0, "USD", note="living costs",
                 snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    assert s["cash"]["USD"] == 2300.0
    assert s["totals"]["withdrawn"] == 200.0
    with pytest.raises(tr.TradeError, match="insufficient"):
        tr.cash_move("s001", "withdraw", 99999.0, "USD",
                     snap_dir=snap, today="2026-09-04")


# ---------------------------------------------------------------------------
# NAV / status / journal
# ---------------------------------------------------------------------------
def test_mark_nav_multi_currency(trade_dir, snap, prices, hk_lot_100):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US", "HK"])
    tr.buy("s001", _match("US", "AAPL", "Apple"), qty=5,
           snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    s["cash"]["HKD"] = 100.0
    tr.save_season(s)
    entry = tr.mark_nav("s001", snap_dir=snap, today="2026-09-04")
    expected = round(848.01 + 100 * 0.92 / 7.2 + 1150.0, 2)
    assert entry["nav"] == expected
    assert entry["cash_total"] == round(848.01 + 100 * 0.92 / 7.2, 2)
    assert entry["positions"][0]["code"] == "AAPL"
    tr.mark_nav("s001", snap_dir=snap, today="2026-09-04")
    s = tr.load_season("s001")
    assert len(s["nav_history"]) == 1


def test_status_dual_goal_metrics(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US"])
    tr.buy("s001", _match("US", "AAPL", "Apple"), qty=5,
           snap_dir=snap, today="2026-09-04")
    tr.cash_move("s001", "withdraw", 50.0, "USD", snap_dir=snap,
                 today="2026-09-04")
    summaries = tr.status_all(snap_dir=snap, today="2026-09-04")
    assert len(summaries) == 1
    sm = summaries[0]
    assert sm["nav"] == 1948.01            # 2000 - 1.99 fees - 50 withdrawn
    assert sm["withdrawal_pct"] == 2.5     # 50/2000
    assert sm["net_return_pct"] == round(
        (1948.01 + 50.0) / 2000.0 * 100 - 100, 2)


def test_journal_day_pnl(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US"])
    tr.mark_nav("s001", snap_dir=snap, today="2026-09-04")
    j = tr.write_journal("s001", "day one: no positions yet",
                         snap_dir=snap, today="2026-09-04")
    assert j["day_pnl"] == 0.0
    j2 = tr.write_journal("s001", "still flat",
                          snap_dir=snap, today="2026-09-07")
    assert j2["day_pnl"] == 0.0
    s = tr.load_season("s001")
    assert len(s["journal"]) == 2
    assert [e["date"] for e in s["nav_history"]] == [
        "2026-09-04", "2026-09-07"]


# ---------------------------------------------------------------------------
# Rendering / JSON
# ---------------------------------------------------------------------------
def test_render_smoke(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", name="港美练手", base="USD", capital=2000.0,
                  markets=["US"])
    fill = tr.buy("s001", _match("US", "AAPL", "Apple"), qty=5,
                  note="test", snap_dir=snap, today="2026-09-04")
    txt = tr.render_fill(fill)
    assert "BUY" in txt and "AAPL" in txt and "1,151.99" in txt
    summaries = tr.status_all(snap_dir=snap, today="2026-09-04")
    st = tr.render_status(summaries)
    assert "s001" in st and "港美练手" in st
    j = tr.render_journal([{"date": "2026-09-04", "nav": 1998.01,
                            "day_pnl": -1.99, "text": "first day"}])
    assert "first day" in j
    season_txt = tr.render_season(tr.load_season("s001"))
    assert "s001" in season_txt


def test_to_json_pure(trade_dir, snap, prices):
    from value_genie import trade as tr
    tr.new_season("s001", base="USD", capital=2000.0, markets=["US"])
    tr.buy("s001", _match("US", "AAPL", "Apple"), qty=5,
           snap_dir=snap, today="2026-09-04")
    payload = json.loads(tr.to_json(tr.load_season("s001")))
    assert payload["id"] == "s001"
    assert payload["positions"][0]["code"] == "AAPL"
    summaries = tr.status_all(snap_dir=snap, today="2026-09-04")
    parsed = json.loads(tr.to_json(summaries))
    assert parsed[0]["nav"] == 1998.01


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_season_new_and_buy(trade_dir, snap, prices, hk_lot_100,
                                monkeypatch, capsys):
    from value_genie.__main__ import main
    from value_genie import trade as tr
    monkeypatch.setattr(
        "value_genie.__main__._resolve_stock_or_exit",
        lambda q: _match("US", "AAPL", "Apple"))
    rc = main(["trade", "season", "new", "s001", "--name", "练手",
               "--base", "USD", "--capital", "2000", "--markets", "US"])
    assert rc == 0
    rc = main(["trade", "buy", "s001", "AAPL", "--qty", "5",
               "--note", "first trade", "--no-check",
               "--data-dir", str(snap.parent.parent)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AAPL" in out
    s = tr.load_season("s001")
    assert s["cash"]["USD"] == round(2000.0 - 1151.99, 2)


def test_cli_status_json_pure(trade_dir, snap, prices, monkeypatch, capsys):
    from value_genie.__main__ import main
    monkeypatch.setattr(
        "value_genie.__main__._resolve_stock_or_exit",
        lambda q: _match("US", "AAPL", "Apple"))
    main(["trade", "season", "new", "s001", "--base", "USD",
          "--capital", "2000", "--markets", "US"])
    capsys.readouterr()          # flush the "created season" banner
    rc = main(["trade", "status", "--no-check",
               "--data-dir", str(snap.parent.parent), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "s001"
    assert payload[0]["nav"] == 2000.0


def test_cli_rejection_message(trade_dir, snap, prices, monkeypatch, capsys):
    from value_genie.__main__ import main
    monkeypatch.setattr(
        "value_genie.__main__._resolve_stock_or_exit",
        lambda q: _match("US", "AAPL", "Apple"))
    main(["trade", "season", "new", "s001", "--base", "USD",
          "--capital", "100", "--markets", "US"])
    rc = main(["trade", "buy", "s001", "AAPL", "--qty", "5",
               "--no-check", "--data-dir", str(snap.parent.parent)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "TRADE REJECTED" in err


def test_cli_season_rule_close_delete(trade_dir, monkeypatch, capsys):
    from value_genie.__main__ import main
    from value_genie import trade as tr
    main(["trade", "season", "new", "s001", "--base", "USD",
          "--capital", "100", "--markets", "US"])
    main(["trade", "season", "rule", "s001", "--markets", "A,HK,US"])
    assert tr.load_season("s001")["rules"]["markets"] == ["A", "HK", "US"]
    main(["trade", "season", "close", "s001"])
    assert tr.load_season("s001")["status"] == "closed"
    main(["trade", "season", "resume", "s001"])
    assert tr.load_season("s001")["status"] == "active"
    main(["trade", "season", "delete", "s001", "--confirm"])
    assert tr.list_seasons() == []


def test_cli_journal_write_and_show(trade_dir, snap, prices, monkeypatch,
                                     capsys):
    from value_genie.__main__ import main
    monkeypatch.setattr(
        "value_genie.__main__._resolve_stock_or_exit",
        lambda q: _match("US", "AAPL", "Apple"))
    main(["trade", "season", "new", "s001", "--base", "USD",
          "--capital", "2000", "--markets", "US"])
    rc = main(["trade", "journal", "s001", "--text", "开学第一天",
               "--no-check", "--data-dir", str(snap.parent.parent)])
    assert rc == 0
    rc = main(["trade", "journal", "s001", "--show", "--no-check",
               "--data-dir", str(snap.parent.parent)])
    assert rc == 0
    assert "开学第一天" in capsys.readouterr().out
