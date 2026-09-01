"""Tests for value_genie.strategy.factors."""

import numpy as np
import pandas as pd
import pytest

from value_genie.strategy import factors as f


def _kline(closes):
    n = len(closes)
    return pd.DataFrame({
        "date": [f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)],
        "open": closes, "close": closes,
        "high": [c * 1.01 for c in closes], "low": [c * 0.99 for c in closes],
        "volume": [1e6] * n, "amount": [1e7] * n,
    })


class TestKlineMetrics:
    def test_uptrend(self):
        closes = list(np.linspace(10.0, 20.0, 300))
        m = f.kline_metrics(_kline(closes))
        assert m["pos_52w"] == 100.0          # last close is the high
        assert m["drawdown_52w"] == 0.0
        assert m["ret_250d"] > 0
        assert m["ret_60d"] > 0
        assert 0 < m["volatility"] < 5        # smooth ramp -> tiny vol

    def test_downtrend(self):
        # 100 flat bars at 20 (outside the 52w window), then decline to 10:
        # the 252-bar window still contains the 20 high, last close is 10
        closes = [20.0] * 100 + list(np.linspace(20.0, 10.0, 200))
        m = f.kline_metrics(_kline(closes))
        assert m["pos_52w"] == 0.0            # last close is the low
        assert m["drawdown_52w"] == pytest.approx(-50.0)
        assert m["ret_250d"] < 0

    def test_flat_series(self):
        m = f.kline_metrics(_kline([100.0] * 300))
        assert m["pos_52w"] == 50.0
        assert m["drawdown_52w"] == 0.0
        assert m["volatility"] == 0.0
        assert m["ret_250d"] == 0.0

    def test_partial_history_uses_full_window(self):
        closes = list(np.linspace(10.0, 15.0, 80))
        m = f.kline_metrics(_kline(closes))
        # 80 bars: ret_60d computed over 60 intervals, ret_250d over all 79
        assert m["ret_60d"] > 0
        assert "ret_250d" in m

    def test_too_short_returns_empty(self):
        assert f.kline_metrics(_kline([1.0] * 59)) == {}
        assert f.kline_metrics(None) == {}
        assert f.kline_metrics(pd.DataFrame()) == {}

    def test_interval_return_math(self):
        closes = pd.Series([100.0] + [100.0] * 249 + [110.0])
        assert f._interval_return(closes, 250) == pytest.approx(10.0)
        assert f._interval_return(closes, 60) == pytest.approx(10.0)


class TestAddPillarScores:
    def _frame(self):
        return pd.DataFrame({
            "market": ["A", "A", "A", "US", "US", "US"],
            "code": ["1", "2", "3", "4", "5", "6"],
            "pe_ttm": [10.0, 20.0, 40.0, 5.0, 50.0, 10.0],
            "pb": [1.0, 2.0, 4.0, 0.5, 5.0, 1.5],
            "ps": [1.0, 3.0, 9.0, 0.8, 8.0, 2.0],
            "dividend_yield": [1.0, 2.0, 3.0, 0.5, 4.0, 1.5],
            "rev_yoy": [5.0, 10.0, 30.0, 2.0, 40.0, 8.0],
            "profit_yoy": [4.0, 12.0, 25.0, 1.0, 35.0, 6.0],
            "roe": [8.0, 15.0, 25.0, 6.0, 30.0, 12.0],
            "debt_ratio": [60.0, 40.0, 20.0, 70.0, 10.0, 50.0],
            "pos_52w": [90.0, 50.0, 10.0, 95.0, 5.0, 40.0],
            "volatility": [30.0, 20.0, 10.0, 40.0, 8.0, 25.0],
            "drawdown_52w": [-2.0, -20.0, -50.0, -1.0, -60.0, -15.0],
            "ret_60d": [5.0, 10.0, 20.0, 2.0, 25.0, 8.0],
            "ret_250d": [10.0, 20.0, 40.0, 5.0, 50.0, 15.0],
            "ocf_yield": [4.0, 6.0, 8.0, 3.0, 9.0, 5.0],
            "cash_conversion": [80.0, 100.0, 120.0, 70.0, 130.0, 90.0],
        })

    def test_value_scores_ordered(self):
        df = f.add_pillar_scores(self._frame())
        # stock 1 (cheapest in A) must out-value stock 3 (priciest in A)
        v = df.set_index("code")["value_score"]
        assert v["1"] > v["2"] > v["3"]
        # per-market pools are independent: US stock 4 is cheapest in US
        vu = df[df["market"] == "US"].set_index("code")["value_score"]
        assert vu["4"] > vu["6"] > vu["5"]

    def test_growth_scores_ordered(self):
        df = f.add_pillar_scores(self._frame())
        g = df.set_index("code")["growth_score"]
        assert g["3"] > g["2"] > g["1"]

    def test_quality_prefers_low_debt(self):
        df = f.add_pillar_scores(self._frame())
        q = df.set_index("code")["quality_score"]
        assert q["3"] > q["1"]  # high ROE + low debt wins

    def test_safety_prefers_deep_drawdown(self):
        df = f.add_pillar_scores(self._frame())
        s = df.set_index("code")["safety_score"]
        assert s["3"] > s["1"]  # far from high, low vol, deep drawdown

    def test_missing_subfactor_renorms(self):
        df = self._frame().drop(columns=["ps", "dividend_yield"])
        out = f.add_pillar_scores(df)
        v = out.set_index("code")["value_score"]
        assert v["1"] > v["3"]
        assert out["growth_score"].notna().all()

    def test_scores_in_range(self):
        df = f.add_pillar_scores(self._frame())
        for col in f.pillar_columns():
            assert df[col].between(0, 100).all()

    def test_negative_pe_lowers_value_score(self):
        df = self._frame()
        before = f.add_pillar_scores(df).set_index("code")["value_score"]
        # stock 1 has the cheapest PE in A; making it loss-making must
        # remove that advantage and lower its value score
        df.loc[df["code"] == "1", "pe_ttm"] = -20.0
        after = f.add_pillar_scores(df).set_index("code")["value_score"]
        assert after["1"] < before["1"]

    def test_no_factor_columns_gives_nan(self):
        df = pd.DataFrame({"market": ["A", "A"], "code": ["1", "2"]})
        out = f.add_pillar_scores(df)
        assert out["value_score"].isna().all()

    def test_single_stock_market_gets_full_percentile(self):
        df = pd.DataFrame({"market": ["A"], "code": ["1"], "pe_ttm": [15.0],
                           "pb": [2.0], "rev_yoy": [10.0]})
        out = f.add_pillar_scores(df)
        # rank(pct) of a single value is 1.0 -> 100
        assert out["value_score"].iloc[0] == 100.0
