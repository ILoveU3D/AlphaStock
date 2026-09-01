"""Tests for the time-horizon dimension (registry, scoring, CLI, ask)."""

import pandas as pd
import pytest

from value_genie.strategy.factors import kline_metrics


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
