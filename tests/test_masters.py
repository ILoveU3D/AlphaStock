"""Tests for investment master strategies and preset registry integration."""

import pandas as pd
import pytest

from value_genie.strategy import masters  # noqa: F401 — triggers registration
from value_genie.strategy import presets   # noqa: F401
from value_genie.strategy.registry import (
    Strategy,
    evaluate_gates,
    get_strategy,
    list_strategies,
)


class TestMasterRegistration:
    def test_all_four_masters_registered(self):
        ids = {s.id for s in list_strategies(kind="master")}
        assert {"buffett", "duan", "sheng", "livermore"} <= ids

    def test_buffett_weights(self):
        s = get_strategy("buffett")
        assert s.kind == "master"
        assert s.weights["cashflow"] == 0.15
        assert s.weights["quality"] == 0.40
        assert s.weights["momentum"] == 0

    def test_duan_gates_include_volatility_percentile(self):
        s = get_strategy("duan")
        ops = [(g[0], g[1]) for g in s.gates]
        assert ("volatility", "pctl<=") in ops

    def test_sheng_momentum_dominant(self):
        s = get_strategy("sheng")
        assert s.weights["momentum"] == 0.45
        assert s.weights["growth"] == 0.35
        assert s.weights["value"] == 0.05

    def test_livermore_zero_value_zero_safety(self):
        s = get_strategy("livermore")
        assert s.weights["value"] == 0
        assert s.weights["safety"] == 0
        assert s.weights["momentum"] == 0.60

    def test_masters_have_skill_files(self):
        for mid in ("buffett", "duan", "sheng", "livermore"):
            s = get_strategy(mid)
            assert s.skill_file, f"{mid} missing skill_file"

    def test_masters_have_triggers(self):
        for mid in ("buffett", "duan", "sheng", "livermore"):
            s = get_strategy(mid)
            assert len(s.triggers) > 0, f"{mid} missing triggers"


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


class TestMasterGates:
    def _df(self):
        return pd.DataFrame([
            {"market": "A", "code": "001", "roe": 20.0,
             "gross_margin": 50.0, "debt_ratio": 40.0,
             "ocf_yield": 6.0, "volatility": 30.0, "ret_60d": 5.0},
            {"market": "A", "code": "002", "roe": 10.0,
             "gross_margin": 35.0, "debt_ratio": 70.0,
             "ocf_yield": 2.0, "volatility": 60.0, "ret_60d": -2.0},
            {"market": "A", "code": "003", "roe": 30.0,
             "gross_margin": 60.0, "debt_ratio": 30.0,
             "ocf_yield": 8.0, "volatility": 20.0, "ret_60d": 10.0},
        ])

    def test_buffett_gates(self):
        s = get_strategy("buffett")
        mask = evaluate_gates(self._df(), s.gates)
        assert mask.tolist() == [True, False, True]

    def test_sheng_gates(self):
        s = get_strategy("sheng")
        mask = evaluate_gates(self._df(), s.gates)
        # ret_60d >= 0: rows 0 (5.0) and 2 (10.0) pass; row 1 (-2.0) fails
        assert mask.tolist() == [True, False, True]

    def test_livermore_gates(self):
        s = get_strategy("livermore")
        mask = evaluate_gates(self._df(), s.gates)
        # ret_60d >= 0 AND volatility pctl >= 50
        # row 0: ret 5 pass, vol=30 pctl~67 pass -> True
        # row 1: ret -2 fail -> False
        # row 2: ret 10 pass, vol=20 pctl~33 fail -> False
        assert mask.tolist() == [True, False, False]
