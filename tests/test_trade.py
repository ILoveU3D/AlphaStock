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
