"""Tests for the time-horizon dimension (registry, scoring, CLI, ask)."""

import pandas as pd
import pytest

from value_genie.strategy.factors import kline_metrics
from value_genie.strategy import horizons  # noqa: F401 — registration
from value_genie.strategy import masters   # noqa: F401
from value_genie.strategy.registry import (
    get_horizon,
    get_strategy,
    list_horizons,
)


class TestShortWindowFactors:
    def test_ret_5d_ret_20d_vol_20d(self):
        closes = [100.0 * (1.01 ** t) for t in range(80)]
        m = kline_metrics(pd.DataFrame({"close": closes}))
        assert m["ret_5d"] == pytest.approx(((1.01 ** 5) - 1) * 100,
                                            rel=1e-9)
        assert m["ret_20d"] == pytest.approx(((1.01 ** 20) - 1) * 100,
                                             rel=1e-9)
        assert m["vol_20d"] > 0
        assert m["volatility"] > 0

    def test_flat_series_gives_zero_returns(self):
        m = kline_metrics(pd.DataFrame({"close": [100.0] * 80}))
        assert m["ret_5d"] == 0.0
        assert m["ret_20d"] == 0.0


class TestHorizonRegistry:
    def test_four_horizons_in_order(self):
        ids = [h.id for h in list_horizons()]
        assert ids[:4] == ["ultrashort", "short", "mid", "long"]

    def test_get_horizon_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown horizon"):
            get_horizon("nope")

    def test_ultrashort_shape(self):
        h = get_horizon("ultrashort")
        assert h.name == "超短线"
        assert h.momentum_cols == ("ret_5d", "ret_20d")
        assert h.weights["momentum"] == 0.70
        assert h.weights["value"] == 0
        ops = [(g[0], g[1]) for g in h.gates]
        assert ("volatility", "pctl>=") in ops
        assert ("ret_5d", ">=") in ops

    def test_short_shape(self):
        h = get_horizon("short")
        assert h.momentum_cols == ("ret_20d", "ret_60d")
        assert h.weights["momentum"] == 0.35
        assert ("ret_20d", ">=") in [(g[0], g[1]) for g in h.gates]

    def test_mid_shape(self):
        h = get_horizon("mid")
        assert h.gates == []
        assert h.weights["value"] == 0.30
        assert h.weights["growth"] == 0.30
        assert h.momentum_cols == ("ret_60d", "ret_250d")

    def test_long_shape(self):
        h = get_horizon("long")
        assert h.gates == []
        assert h.weights["quality"] == 0.35
        assert h.weights["cashflow"] == 0.20
        assert h.weights["momentum"] == 0
        assert h.momentum_cols == ("ret_60d", "ret_250d")

    def test_weights_sum_to_one(self):
        for h in list_horizons():
            assert sum(h.weights.values()) == pytest.approx(1.0)

    def test_masters_carry_natural_horizon(self):
        mapping = {"buffett": "long", "munger": "long", "graham": "mid",
                   "livermore": "short", "duan": "long",
                   "sheng": "ultrashort"}
        for mid, hz in mapping.items():
            assert get_strategy(mid).horizon == hz

    def test_presets_have_empty_horizon(self):
        assert get_strategy("balanced").horizon == ""
