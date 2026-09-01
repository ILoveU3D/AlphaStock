"""Headless smoke tests for the Streamlit dashboard (app.py).

Exercises the full render path plus the interactive sidebar controls
(custom weight sliders, market toggles) against a synthetic snapshot.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")

from streamlit.testing.v1 import AppTest

from value_genie import config

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _write_snapshot(data_dir: Path) -> None:
    rows = []
    for market, codes in (("A", ["600519", "000858"]),
                          ("HK", ["00700"]),
                          ("US", ["AAPL", "MSFT"])):
        currency = {"A": "CNY", "HK": "HKD", "US": "USD"}[market]
        for i, code in enumerate(codes):
            rows.append({
                "market": market, "code": code, "name": f"Stock {code}",
                "industry": "Misc", "currency": currency,
                "price": 100.0 + i, "market_cap": 1e11 * (i + 1),
                "pe_ttm": 10.0 + i, "pb": 1.0 + i, "ps": 2.0 + i,
                "dividend_yield": 1.0 + i, "rev_yoy": 5.0 + i,
                "profit_yoy": 6.0 + i, "rev_q_yoy": 4.0 + i,
                "roe": 12.0 + i, "gross_margin": 30.0 + i,
                "net_margin": 10.0 + i, "debt_ratio": 40.0 + i,
                "pos_52w": 40.0 + i, "drawdown_52w": -20.0 + i,
                "ret_250d": 10.0 + i, "ret_60d": 3.0 + i,
                "volatility": 20.0 + i, "report_date": "2026-06-30",
                "value_score": 50.0 + 5 * i, "growth_score": 45.0 + 5 * i,
                "quality_score": 55.0 + 5 * i, "safety_score": 35.0 + 5 * i,
                "data_completeness": 1.0,
            })
    snap = data_dir / "snapshots" / "20260201"
    snap.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(snap / "master.csv", index=False)
    (snap / "manifest.json").write_text(json.dumps({
        "created_at": "2026-02-01T16:00:00", "markets": ["A", "HK", "US"],
        "failures": []}), encoding="utf-8")

    kline_dir = snap / "kline"
    kline_dir.mkdir()
    dates = pd.date_range(end="2026-02-01", periods=300, freq="B")
    closes = pd.Series(range(300), dtype=float) * 0.05 + 50.0
    kline = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": closes, "close": closes,
        "high": closes * 1.01, "low": closes * 0.99,
        "volume": 1e6, "amount": 1e8})
    for row in rows:
        kline.to_csv(kline_dir / f"{row['market']}_{row['code']}.csv",
                     index=False)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    _write_snapshot(tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path


def test_app_renders(app_env):
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Value Genie :genie:"
    # banner + detail metrics rendered
    assert len(at.metric) >= 3


def test_app_custom_strategy(app_env):
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    at.sidebar.selectbox[1].set_value("custom")
    at.run()
    assert not at.exception


def test_app_market_toggle(app_env):
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    us_box = at.sidebar.checkbox[2]
    assert us_box.label == "US"
    us_box.uncheck()
    at.run()
    assert not at.exception
