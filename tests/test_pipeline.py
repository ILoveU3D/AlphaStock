"""Tests for value_genie.fetch.pipeline (all network fetchers mocked)."""

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from value_genie import config
from value_genie.fetch import pipeline as pl


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------
def _kline_df(days: int = 300) -> pd.DataFrame:
    dates = [date.today() - timedelta(days=i) for i in range(days)][::-1]
    closes = [10.0 + i * 0.03 for i in range(days)]
    return pd.DataFrame({
        "date": [d.isoformat() for d in dates],
        "open": closes, "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "volume": [1e6] * days, "amount": [1e7] * days,
    })


def _quotes(rows):
    df = pd.DataFrame(rows)
    for col in ("price", "pct_chg", "volume", "amount", "turnover", "pe_dyn",
                "pe_static", "pe_ttm", "pb", "market_cap", "float_cap"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def a_quotes():
    return _quotes([
        {"market": "A", "code": "600519", "name": "Kweichow Moutai",
         "industry": "Liquor", "market_id": "1", "price": 1500.0,
         "pe_ttm": 25.0, "pb": 8.0, "market_cap": 1.9e12},
        {"market": "A", "code": "000858", "name": "Wuliangye",
         "industry": "Liquor", "market_id": "0", "price": 130.0,
         "pe_ttm": 20.0, "pb": 5.0, "market_cap": 5.0e11},
        {"market": "A", "code": "601318", "name": "Ping An Insurance",
         "industry": "Insurance", "market_id": "1", "price": 50.0,
         "pe_ttm": 8.0, "pb": 1.0, "market_cap": 9.0e11},
        {"market": "A", "code": "300750", "name": "CATL",
         "industry": "Battery", "market_id": "0", "price": 200.0,
         "pe_ttm": 30.0, "pb": 6.0, "market_cap": 8.8e11},
        {"market": "A", "code": "600000", "name": "SPD Bank",
         "industry": "Bank", "market_id": "1", "price": 8.0,
         "pe_ttm": 5.0, "pb": 0.5, "market_cap": 2.3e11},
        {"market": "A", "code": "600999", "name": "ST Bad",
         "industry": "Misc", "market_id": "1", "price": 3.0,
         "pe_ttm": 40.0, "pb": 2.0, "market_cap": 5.0e9},
    ])


def a_fins():
    base = {"report_date": "2026-06-30", "revenue": 1.0e10,
            "profit": 1.5e9, "roe": 15.0, "gross_margin": 50.0,
            "bps": 30.0}
    return pd.DataFrame([
        {"code": "600519", "rev_yoy": 15.0, "profit_yoy": 18.0, **base},
        {"code": "000858", "rev_yoy": 10.0, "profit_yoy": 12.0, **base},
        {"code": "601318", "rev_yoy": 6.0, "profit_yoy": 5.0, **base},
        {"code": "300750", "rev_yoy": 20.0, "profit_yoy": -10.0, **base},
        {"code": "600000", "rev_yoy": -5.0, "profit_yoy": -8.0, **base},
    ])


def hk_quotes():
    return _quotes([
        {"market": "HK", "code": "00700", "name": "Tencent",
         "industry": "Internet", "market_id": "116", "price": 300.0,
         "pe_ttm": 22.0, "pb": 4.0, "market_cap": 2.8e12,
         "amount": 2.0e9},
        {"market": "HK", "code": "01810", "name": "Xiaomi",
         "industry": "Electronics", "market_id": "116", "price": 20.0,
         "pe_ttm": 25.0, "pb": 3.0, "market_cap": 5.0e11,
         "amount": 1.0e9},
        {"market": "HK", "code": "00388", "name": "HKEX",
         "industry": "Exchange", "market_id": "116", "price": 250.0,
         "pe_ttm": 30.0, "pb": 7.0, "market_cap": 3.0e11,
         "amount": 8.0e8},
        {"market": "HK", "code": "00005", "name": "HSBC",
         "industry": "Bank", "market_id": "116", "price": 70.0,
         "pe_ttm": 9.0, "pb": 1.0, "market_cap": 1.3e12,
         "amount": 1.5e9},
        {"market": "HK", "code": "08436", "name": "Tiny Illiquid",
         "industry": "Misc", "market_id": "116", "price": 1.0,
         "pe_ttm": 15.0, "pb": 2.0, "market_cap": 3.0e9,
         "amount": 1.0e5},   # below liquidity gate
    ])


def hk_f10(code):
    base = {"secucode": f"{code}.HK", "report_date": "2026-06-30",
            "report_type": "Interim", "revenue": 5.0e11, "profit": 1.0e11,
            "gross_margin": 45.0, "net_margin": 20.0, "roe": 18.0,
            "debt_ratio": 40.0, "dps_hkd": 2.0, "dividend_yield": 2.5}
    data = {
        "00700": {"rev_yoy": 12.0, "profit_yoy": 15.0},
        "01810": {"rev_yoy": 25.0, "profit_yoy": 30.0},
        "00388": {"rev_yoy": 5.0, "profit_yoy": -6.0},   # final gate drop
        "00005": {"rev_yoy": 3.0, "profit_yoy": 2.0},
    }.get(code, {"rev_yoy": 5.0, "profit_yoy": 5.0})
    return pd.DataFrame([{**base, **data}])


def us_quotes():
    return _quotes([
        {"market": "US", "code": "AAPL", "name": "Apple",
         "industry": "Electronics", "market_id": "105", "price": 220.0,
         "pe_ttm": 30.0, "pb": 40.0, "market_cap": 3.3e12},
        {"market": "US", "code": "MSFT", "name": "Microsoft",
         "industry": "Software", "market_id": "105", "price": 400.0,
         "pe_ttm": 33.0, "pb": 35.0, "market_cap": 3.0e12},
        {"market": "US", "code": "JPM", "name": "JPMorgan",
         "industry": "Bank", "market_id": "106", "price": 200.0,
         "pe_ttm": 12.0, "pb": 2.0, "market_cap": 6.0e11},
    ])


def us_fins():
    return pd.DataFrame([
        {"ticker": "AAPL", "rev": 3.9e11, "rev_yoy": 8.0, "profit_yoy": 10.0,
         "rev_q_yoy": 6.0, "roe": 90.0, "gross_margin": 46.0,
         "net_margin": 25.0, "debt_ratio": 80.0},
        {"ticker": "MSFT", "rev": 2.6e11, "rev_yoy": 15.0,
         "profit_yoy": 20.0, "rev_q_yoy": 14.0, "roe": 35.0,
         "gross_margin": 70.0, "net_margin": 35.0, "debt_ratio": 55.0},
    ])


@pytest.fixture()
def counters():
    return {"kline": 0, "f10": 0}


@pytest.fixture()
def patched_fetchers(monkeypatch, counters):
    def fake_quotes(market):
        return {"A": a_quotes(), "HK": hk_quotes(), "US": us_quotes()}[market]

    def fake_kline(market, code, market_id="", lmt=300):
        counters["kline"] += 1
        return _kline_df(300)

    def fake_f10(code):
        counters["f10"] += 1
        return hk_f10(code)

    monkeypatch.setattr(pl, "fetch_market_quotes", fake_quotes)
    monkeypatch.setattr(pl, "fetch_a_financials", lambda quiet=False: a_fins())
    monkeypatch.setattr(pl, "fetch_us_financials", lambda quiet=False: us_fins())
    monkeypatch.setattr(pl, "fetch_hk_f10", fake_f10)
    monkeypatch.setattr(pl, "fetch_fx_hkdcny", lambda: 0.92)
    monkeypatch.setattr(pl, "fetch_kline_any", fake_kline)
    return counters


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_run_fetch_full_flow(patched_fetchers, tmp_path):
    snap = pl.run_fetch(data_dir=tmp_path, quiet=True)
    assert snap == tmp_path / "snapshots" / date.today().strftime("%Y%m%d")

    for name in ("master.csv", "manifest.json", "a_quotes.csv",
                 "hk_quotes.csv", "us_quotes.csv", "a_financials.csv",
                 "us_financials.csv", "hk_f10.csv",
                 "kline/A_600519.csv", "kline/HK_00700.csv",
                 "kline/US_AAPL.csv"):
        assert (snap / name).exists(), name
    assert json.loads((tmp_path / "latest.json").read_text())[
        "snapshot"] == snap.name

    master = pd.read_csv(snap / "master.csv", dtype={"code": str})
    assert list(master.columns) == pl.MASTER_COLUMNS
    # ST name + negative rev_yoy + negative profit_yoy all filtered
    assert set(master[master["market"] == "A"]["code"]) == {
        "600519", "000858", "601318"}
    # illiquid HK + negative F10 profit_yoy filtered
    assert set(master[master["market"] == "HK"]["code"]) == {
        "00700", "01810", "00005"}
    # JPM dropped: US candidates must carry SEC frames data
    assert set(master[master["market"] == "US"]["code"]) == {"AAPL", "MSFT"}

    hk = master[master["code"] == "00700"].iloc[0]
    assert hk["ps"] == pytest.approx(2.8e12 * 0.92 / 5.0e11)
    assert hk["dividend_yield"] == pytest.approx(2.5)
    assert hk["report_date"] == "2026-06-30"

    a = master[master["code"] == "600519"].iloc[0]
    assert a["currency"] == "CNY"
    assert a["ps"] == pytest.approx(1.9e12 / 1.0e10)
    assert a["net_margin"] == pytest.approx(15.0)
    assert a["pos_52w"] == pytest.approx(100.0)

    us = master[master["code"] == "AAPL"].iloc[0]
    assert us["currency"] == "USD"
    assert us["ps"] == pytest.approx(3.3e12 / 3.9e11)

    for col in ("value_score", "growth_score", "quality_score",
                "safety_score"):
        s = master[col].dropna()
        assert len(s) > 0
        assert s.between(0, 100).all(), col

    manifest = json.loads((snap / "manifest.json").read_text())
    assert manifest["markets"] == ["A", "HK", "US"]
    assert manifest["datasets"]["master"] == len(master)
    assert manifest["fx_hkdcny"] == 0.92


def test_incremental_reuse(patched_fetchers, tmp_path):
    pl.run_fetch(data_dir=tmp_path, quiet=True)
    fetched_once = patched_fetchers["kline"]
    f10_once = patched_fetchers["f10"]
    assert fetched_once > 0

    # same-day rerun reuses klines and HK F10 without refetching
    pl.run_fetch(data_dir=tmp_path, quiet=True)
    assert patched_fetchers["kline"] == fetched_once
    assert patched_fetchers["f10"] == f10_once

    # refresh forces a full refetch
    pl.run_fetch(data_dir=tmp_path, refresh=True, quiet=True)
    assert patched_fetchers["kline"] > fetched_once


def test_reuses_prior_snapshot_klines(patched_fetchers, tmp_path,
                                      monkeypatch):
    today = date.today().strftime("%Y%m%d")
    prior = tmp_path / "snapshots" / "20200101"
    (prior / "kline").mkdir(parents=True)
    pl.save_kline(_kline_df(300), prior / "kline" / "A_600519.csv")

    snap = pl.run_fetch(markets=["A"], data_dir=tmp_path, quiet=True)
    assert snap.name == today
    # 600519 was reused from the prior snapshot; the other three fetched
    assert patched_fetchers["kline"] == 3


def test_candidate_cap(patched_fetchers, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CANDIDATES_PER_MARKET", 2)
    snap = pl.run_fetch(markets=["A", "US"], data_dir=tmp_path, quiet=True)
    master = pd.read_csv(snap / "master.csv", dtype={"code": str})
    assert (master["market"] == "A").sum() <= 2
    assert (master["market"] == "US").sum() <= 2


def test_unknown_market_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown market"):
        pl.run_fetch(markets=["XX"], data_dir=tmp_path, quiet=True)


def test_apply_gates_drops_st_and_small_cap():
    df = pl.merge_a_financials(a_quotes(), a_fins())
    out = pl.apply_gates(df, "A")
    assert "600999" not in set(out["code"])       # ST name
    assert "600000" not in set(out["code"])       # negative rev_yoy gated
    assert "600519" in set(out["code"])


def test_apply_gates_hk_liquidity():
    out = pl.apply_gates(hk_quotes(), "HK")
    assert "08436" not in set(out["code"])        # below amount floor
    assert "00700" in set(out["code"])


def test_apply_gates_us_drops_non_operating():
    quotes = _quotes([
        {"market": "US", "code": "AAPL", "name": "Apple", "market_id": "105",
         "price": 220.0, "pe_ttm": 30.0, "market_cap": 3.3e12},
        {"market": "US", "code": "NRGD", "name": "MicroSectors Big Oil -3x",
         "market_id": "107", "price": 12.0, "pe_ttm": 1.6,
         "market_cap": 5e9},
        {"market": "US", "code": "WTID", "name": "二倍做多能源ETF-Leverage",
         "market_id": "107", "price": 8.0, "pe_ttm": 0.3,
         "market_cap": 5e9},
        {"market": "US", "code": "ORCLD", "name": "Oracle Corp Series D Pfd",
         "market_id": "106", "price": 40.0, "pe_ttm": 0.3,
         "market_cap": 5e9},
        {"market": "US", "code": "T_C", "name": "AT&T Inc Series C Pfd",
         "market_id": "106", "price": 25.0, "pe_ttm": 0.05,
         "market_cap": 5e9},
    ])
    fins = pd.DataFrame([
        {"ticker": "AAPL", "rev": 3.9e11, "rev_yoy": 8.0, "profit_yoy": 10.0,
         "rev_q_yoy": 6.0, "roe": 90.0, "gross_margin": 46.0,
         "net_margin": 25.0, "debt_ratio": 80.0},
        {"ticker": "NRGD", "rev": None, "rev_yoy": None, "profit_yoy": None,
         "rev_q_yoy": None, "roe": None, "gross_margin": None,
         "net_margin": None, "debt_ratio": None},
    ])
    out = pl.apply_gates(pl.merge_us_financials(quotes, fins), "US")
    # leveraged ETPs / preferreds dropped by name; NRGD (name passes but
    # no SEC frames data) dropped by the operating-company check
    assert set(out["code"]) == {"AAPL"}


def test_run_fetch_skips_us_without_sec_financials(monkeypatch, tmp_path):
    def fake_quotes(market):
        assert market != "US", "US quotes must not be fetched when skipped"
        return {"A": a_quotes(), "HK": hk_quotes()}[market]

    monkeypatch.setattr(pl, "fetch_market_quotes", fake_quotes)
    monkeypatch.setattr(pl, "fetch_a_financials", lambda quiet=False: a_fins())
    monkeypatch.setattr(pl, "fetch_us_financials", lambda quiet=False: None)
    monkeypatch.setattr(pl, "fetch_kline_any",
                        lambda market, code, mid="", lmt=300: _kline_df(300))
    snap = pl.run_fetch(markets=["A", "US"], data_dir=tmp_path, quiet=True)
    master = pd.read_csv(snap / "master.csv", dtype={"code": str})
    assert (master["market"] == "US").sum() == 0
    manifest = json.loads((snap / "manifest.json").read_text())
    assert "US: no SEC financials fetched" in manifest["failures"]
    assert not (snap / "us_quotes.csv").exists()


def test_stage1_blend_ranks():
    df = pl.merge_a_financials(a_quotes(), a_fins())
    df = pl.apply_gates(df, "A")
    out = pl.stage1_blend(df, "A")
    assert out["stage1_score"].notna().all()
    assert out["stage1_score"].between(0, 100).all()
