"""Tests for value_genie.strategy.presets and composite."""

import pandas as pd
import pytest

from value_genie.strategy import composite as c
from value_genie.strategy import presets as p


class TestPresets:
    def test_preset_weights_sum_to_one(self):
        for name, w in p.PRESETS.items():
            assert sum(w.values()) == pytest.approx(1.0), name

    def test_get_preset_returns_copy(self):
        w1 = p.get_preset("balanced")
        w1["value"] = 0.0
        assert p.PRESETS["balanced"]["value"] == 0.35

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="unknown preset"):
            p.get_preset("momentum")

    def test_normalize_weights_scales(self):
        w = p.normalize_weights({"value": 2.0, "growth": 1.0, "quality": 1.0})
        assert sum(w.values()) == pytest.approx(1.0)
        assert w["value"] == pytest.approx(0.5)
        assert w["safety"] == 0.0

    def test_normalize_weights_negative_clamped(self):
        w = p.normalize_weights({"value": -5.0, "growth": 1.0})
        assert w["value"] == 0.0
        assert w["growth"] == pytest.approx(1.0)

    def test_normalize_weights_all_zero_uniform(self):
        w = p.normalize_weights({})
        assert sum(w.values()) == pytest.approx(1.0)
        assert set(w) == {"value", "growth", "quality", "safety",
                          "momentum", "cashflow"}


_ALL_PILLARS = ("value", "growth", "quality", "safety",
                "momentum", "cashflow")


def _df(scores):
    """scores: list of dicts pillar->score or None."""
    rows = []
    for i, s in enumerate(scores):
        row = {"market": "A", "code": str(i)}
        for pillar in _ALL_PILLARS:
            row[f"{pillar}_score"] = s.get(pillar)
        rows.append(row)
    return pd.DataFrame(rows)


class TestApplyComposite:
    W = {"value": 0.4, "growth": 0.3, "quality": 0.2, "safety": 0.1,
         "momentum": 0, "cashflow": 0}

    def test_full_weights(self):
        df = _df([{"value": 80, "growth": 60, "quality": 40,
                   "safety": 20, "momentum": 30, "cashflow": 50}])
        out = c.apply_composite(df, self.W)
        expected = 0.4 * 80 + 0.3 * 60 + 0.2 * 40 + 0.1 * 20
        assert out["composite_score"].iloc[0] == pytest.approx(expected)
        assert out["data_completeness"].iloc[0] == 1.0

    def test_missing_pillar_renorms(self):
        df = _df([{"value": 80, "growth": 60, "quality": 40,
                   "safety": None, "momentum": 30, "cashflow": 50}])
        out = c.apply_composite(df, self.W)
        # weights renormalize over value/growth/quality: .4/.3/.2 -> .8/.6/.4...
        # i.e. composite = (0.4*80 + 0.3*60 + 0.2*40) / (0.4+0.3+0.2)
        expected = (0.4 * 80 + 0.3 * 60 + 0.2 * 40) / 0.9
        assert out["composite_score"].iloc[0] == pytest.approx(expected)
        assert out["data_completeness"].iloc[0] == pytest.approx(5 / 6)

    def test_below_min_pillars_is_nan(self):
        # only 4 of 6 pillars available (quality+safety missing)
        # with default min_pillars=3, and W having 4 positive weights,
        # required = min(3, 4) = 3; available = 2 (value+growth) -> NaN
        df = _df([{"value": 80, "growth": 60, "quality": None,
                   "safety": None, "momentum": 30, "cashflow": 50}])
        out = c.apply_composite(df, self.W)
        assert pd.isna(out["composite_score"].iloc[0])
        assert out["data_completeness"].iloc[0] == pytest.approx(4 / 6)

    def test_min_pillars_capped_by_positive_weights(self):
        # magic-style weights: only value+quality positive; both available
        # must be enough even with min_pillars=3
        w = {"value": 0.5, "growth": 0.0, "quality": 0.5, "safety": 0.0,
             "momentum": 0, "cashflow": 0}
        df = _df([{"value": 80, "growth": 60, "quality": 40,
                   "safety": 20, "momentum": 30, "cashflow": 50}])
        out = c.apply_composite(df, w)
        assert out["composite_score"].iloc[0] == pytest.approx(60.0)

    def test_all_missing_is_nan(self):
        df = _df([{}])
        out = c.apply_composite(df, self.W)
        assert pd.isna(out["composite_score"].iloc[0])
        assert out["data_completeness"].iloc[0] == 0.0

    def test_missing_score_columns_treated_as_nan(self):
        df = pd.DataFrame({"market": ["A"], "code": ["1"]})
        out = c.apply_composite(df, self.W)
        assert pd.isna(out["composite_score"].iloc[0])

    def test_two_pillar_preset_with_one_missing(self):
        # value+quality weights; quality missing -> only value -> below the
        # capped requirement of 2 -> NaN
        w = {"value": 0.5, "growth": 0.0, "quality": 0.5, "safety": 0.0,
             "momentum": 0, "cashflow": 0}
        df = _df([{"value": 80, "growth": 60, "quality": None,
                   "safety": 20, "momentum": 30, "cashflow": 50}])
        out = c.apply_composite(df, w)
        assert pd.isna(out["composite_score"].iloc[0])


class TestRankTop:
    def _frame(self):
        return pd.DataFrame({
            "market": ["A", "A", "US", "US"],
            "code": ["1", "2", "3", "4"],
            "composite_score": [50.0, 70.0, 60.0, float("nan")],
        })

    def test_ranking(self):
        top = c.rank_top(self._frame(), 3)
        assert list(top["code"]) == ["2", "3", "1"]

    def test_market_filter(self):
        top = c.rank_top(self._frame(), 5, markets=["US"])
        assert list(top["code"]) == ["3"]

    def test_top_n(self):
        top = c.rank_top(self._frame(), 1)
        assert len(top) == 1
        assert top["code"].iloc[0] == "2"
