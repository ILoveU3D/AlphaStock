"""Tests for investment master strategies and preset registry integration."""

import pandas as pd
import pytest

from value_genie.strategy import masters  # noqa: F401 — triggers registration
from value_genie.strategy import presets   # noqa: F401
from value_genie.strategy.factors import add_derived_factors
from value_genie.strategy.registry import (
    Strategy,
    evaluate_gates,
    get_strategy,
    list_strategies,
)

SIX_MASTERS = ("buffett", "munger", "graham", "livermore", "duan", "sheng")


class TestMasterRegistration:
    def test_all_six_masters_registered(self):
        ids = {s.id for s in list_strategies(kind="master")}
        assert set(SIX_MASTERS) <= ids

    def test_masters_ordered_by_fame(self):
        ids = [s.id for s in list_strategies(kind="master")]
        ranks = [ids.index(m) for m in SIX_MASTERS if m in ids]
        assert ranks == sorted(ranks), f"expected fame order, got {ids}"
        assert ids[:6] == list(SIX_MASTERS)

    def test_buffett_weights(self):
        s = get_strategy("buffett")
        assert s.kind == "master"
        assert s.weights["cashflow"] == 0.20   # owner earnings emphasis
        assert s.weights["quality"] == 0.40
        assert s.weights["momentum"] == 0

    def test_munger_quality_dominant(self):
        s = get_strategy("munger")
        assert s.weights["quality"] == 0.50
        assert s.weights["momentum"] == 0
        # no cashflow gate by design — trusts franchise economics
        ops = [g[0] for g in s.gates]
        assert "ocf_yield" not in ops

    def test_graham_gates_include_pe_pb_rule(self):
        s = get_strategy("graham")
        assert ("pe_pb", "<=", 22.5) in s.gates
        assert s.weights["value"] == 0.50
        assert s.weights["momentum"] == 0

    def test_duan_gates_include_volatility_and_margin(self):
        s = get_strategy("duan")
        ops = [(g[0], g[1]) for g in s.gates]
        assert ("volatility", "pctl<=") in ops
        assert ("gross_margin", ">=") in ops

    def test_sheng_momentum_dominant(self):
        s = get_strategy("sheng")
        assert s.weights["momentum"] == 0.55
        assert s.weights["growth"] == 0.35
        assert s.weights["value"] == 0
        ops = [(g[0], g[1]) for g in s.gates]
        assert ("volatility", "pctl>=") in ops  # high beta is a feature

    def test_livermore_pure_price_action(self):
        s = get_strategy("livermore")
        assert s.weights["value"] == 0
        assert s.weights["cashflow"] == 0      # historical fidelity
        assert s.weights["momentum"] == 0.70
        assert ("pos_52w", ">=", 60.0) in s.gates  # pivotal point zone

    def test_masters_have_skill_files(self):
        for mid in SIX_MASTERS:
            s = get_strategy(mid)
            assert s.skill_file, f"{mid} missing skill_file"

    def test_masters_have_triggers(self):
        for mid in SIX_MASTERS:
            s = get_strategy(mid)
            assert len(s.triggers) > 0, f"{mid} missing triggers"


class TestDerivedFactors:
    def test_pe_pb_computed_from_pe_and_pb(self):
        df = pd.DataFrame({
            "pe_ttm": [15.0, 30.0, -10.0],
            "pb": [1.4, 3.0, 2.0],
        })
        out = add_derived_factors(df)
        assert out["pe_pb"].tolist()[0] == pytest.approx(21.0)
        assert out["pe_pb"].tolist()[1] == pytest.approx(90.0)
        # negative PE (loss maker) must be NaN — fails `<=` gates
        assert pd.isna(out["pe_pb"].tolist()[2])

    def test_pe_pb_idempotent_and_missing_cols(self):
        df = pd.DataFrame({"pe_ttm": [10.0], "pb": [1.0]})
        df = add_derived_factors(df)
        df2 = add_derived_factors(df)
        assert df2 is df or list(df2.columns) == list(df.columns)
        out = add_derived_factors(pd.DataFrame({"close": [1.0]}))
        assert "pe_pb" not in out.columns


class TestPresetRegistryIntegration:
    def test_presets_registered(self):
        ids = {s.id for s in list_strategies(kind="preset")}
        assert {"balanced", "magic_formula", "garp", "deep_value"} <= ids

    def test_preset_kind(self):
        s = get_strategy("balanced")
        assert s.kind == "preset"
        assert s.gates == []

    def test_preset_weights_include_six_pillars(self):
        s = get_strategy("garp")
        for pillar in ("value", "growth", "quality", "safety",
                       "momentum", "cashflow"):
            assert pillar in s.weights

    def test_presets_sorted_after_masters(self):
        all_ids = [s.id for s in list_strategies()]
        assert all_ids.index("sheng") < all_ids.index("balanced")


class TestMasterGates:
    def _df(self):
        return pd.DataFrame([
            {"market": "A", "code": "001", "roe": 20.0,
             "gross_margin": 50.0, "debt_ratio": 40.0,
             "ocf_yield": 6.0, "volatility": 30.0, "ret_60d": 5.0,
             "pe_ttm": 15.0, "pb": 1.4, "pos_52w": 70.0},
            {"market": "A", "code": "002", "roe": 10.0,
             "gross_margin": 35.0, "debt_ratio": 70.0,
             "ocf_yield": 2.0, "volatility": 60.0, "ret_60d": -2.0,
             "pe_ttm": 30.0, "pb": 3.0, "pos_52w": 30.0},
            {"market": "A", "code": "003", "roe": 30.0,
             "gross_margin": 60.0, "debt_ratio": 30.0,
             "ocf_yield": 8.0, "volatility": 20.0, "ret_60d": 10.0,
             "pe_ttm": 10.0, "pb": 1.0, "pos_52w": 50.0},
        ])

    def test_buffett_gates(self):
        s = get_strategy("buffett")
        mask = evaluate_gates(self._df(), s.gates)
        assert mask.tolist() == [True, False, True]

    def test_munger_gates(self):
        s = get_strategy("munger")
        mask = evaluate_gates(self._df(), s.gates)
        # roe>=20 AND gross_margin>=40 AND debt<=50
        assert mask.tolist() == [True, False, True]

    def test_graham_gates_with_derived_pe_pb(self):
        s = get_strategy("graham")
        df = add_derived_factors(self._df())  # pe_pb derived in screen()
        mask = evaluate_gates(df, s.gates)
        # pe_pb<=22.5 AND debt<=50 AND roe>=10
        assert mask.tolist() == [True, False, True]

    def test_duan_gates(self):
        s = get_strategy("duan")
        mask = evaluate_gates(self._df(), s.gates)
        # roe>=20 AND gross_margin>=40 AND vol pctl<=60
        # row 0: vol 30 -> pctl 66.7 > 60 -> False (too speculative)
        # row 2: vol 20 -> pctl 33.3 -> True
        assert mask.tolist() == [False, False, True]

    def test_sheng_gates(self):
        s = get_strategy("sheng")
        mask = evaluate_gates(self._df(), s.gates)
        # ret_60d >= 0 AND volatility pctl >= 60
        # row 0: ret 5 pass, vol pctl 66.7 pass -> True
        # row 1: ret -2 fail -> False
        # row 2: vol pctl 33.3 fail -> False
        assert mask.tolist() == [True, False, False]

    def test_livermore_gates(self):
        s = get_strategy("livermore")
        mask = evaluate_gates(self._df(), s.gates)
        # ret_60d >= 0 AND volatility pctl >= 50 AND pos_52w >= 60
        # row 0: all pass -> True
        # row 1: ret fail -> False
        # row 2: vol pctl 33.3 fail, pos_52w 50 < 60 fail -> False
        assert mask.tolist() == [True, False, False]
