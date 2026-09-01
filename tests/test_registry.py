"""Tests for the strategy and data-source registries."""

import pandas as pd
import pytest

from value_genie.strategy.registry import (
    DataSource,
    Strategy,
    evaluate_gates,
    get_sources,
    get_strategy,
    list_strategies,
    list_sources,
    register_source,
    register_strategy,
    set_source_order,
)


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------
class TestStrategyRegistry:
    def test_register_and_get(self):
        s = Strategy(id="test1", name="Test",
                     weights={"value": 1.0})
        register_strategy(s)
        got = get_strategy("test1")
        assert got is s
        assert got.weights == {"value": 1.0}

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown strategy"):
            get_strategy("nonexistent_strategy_xyz")

    def test_list_filters_by_kind(self):
        register_strategy(Strategy(id="p1", name="P1",
                                    weights={}, kind="preset"))
        register_strategy(Strategy(id="m1", name="M1",
                                    weights={}, kind="master"))
        all_s = list_strategies()
        ids = [s.id for s in all_s]
        assert "p1" in ids and "m1" in ids
        masters = list_strategies(kind="master")
        assert all(s.kind == "master" for s in masters)
        assert "m1" in [s.id for s in masters]

    def test_replace_on_reregister(self):
        register_strategy(Strategy(id="dup", name="A", weights={"value": 0.5}))
        register_strategy(Strategy(id="dup", name="B", weights={"value": 0.3}))
        assert get_strategy("dup").name == "B"


# ---------------------------------------------------------------------------
# DataSource registry
# ---------------------------------------------------------------------------
class TestDataSourceRegistry:
    def test_register_and_list(self):
        ds = DataSource(id="test_src", name="Test Source",
                        capabilities=["quotes:A"],
                        fetchers={"quotes": lambda: None})
        register_source(ds)
        assert ds in list_sources()

    def test_get_sources_by_order(self):
        register_source(DataSource(id="src_a", name="A",
                                    capabilities=["fin:A"]))
        register_source(DataSource(id="src_b", name="B",
                                    capabilities=["fin:A"]))
        set_source_order("fin", "A", ["src_b", "src_a"])
        sources = get_sources("fin", "A")
        assert len(sources) == 2
        assert sources[0].id == "src_b"  # primary first

    def test_get_sources_fallback_by_capability(self):
        register_source(DataSource(id="cap_src", name="Cap",
                                    capabilities=["kline:HK"]))
        sources = get_sources("kline", "HK")
        assert any(s.id == "cap_src" for s in sources)

    def test_get_sources_empty_when_nothing_matches(self):
        sources = get_sources("nonexistent", "XX")
        assert sources == []


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------
class TestEvaluateGates:
    def _df(self):
        return pd.DataFrame([
            {"market": "A", "code": "001", "roe": 20.0, "gross_margin": 50.0,
             "debt_ratio": 40.0, "volatility": 30.0, "ret_60d": 5.0},
            {"market": "A", "code": "002", "roe": 10.0, "gross_margin": 35.0,
             "debt_ratio": 70.0, "volatility": 60.0, "ret_60d": -2.0},
            {"market": "A", "code": "003", "roe": 30.0, "gross_margin": 60.0,
             "debt_ratio": 30.0, "volatility": 20.0, "ret_60d": 10.0},
        ])

    def test_no_gates_passes_all(self):
        mask = evaluate_gates(self._df(), [])
        assert mask.all()

    def test_absolute_gte(self):
        mask = evaluate_gates(self._df(), [("roe", ">=", 15.0)])
        assert mask.tolist() == [True, False, True]

    def test_absolute_lte(self):
        mask = evaluate_gates(self._df(), [("debt_ratio", "<=", 60.0)])
        assert mask.tolist() == [True, False, True]

    def test_multiple_gates_and_logic(self):
        mask = evaluate_gates(self._df(), [
            ("roe", ">=", 15.0),
            ("debt_ratio", "<=", 60.0),
        ])
        assert mask.tolist() == [True, False, True]

    def test_pctl_lte(self):
        # volatility pctl<=50: pass if in bottom 50% of market
        mask = evaluate_gates(self._df(), [("volatility", "pctl<=", 50)])
        # row 0: vol=30 (rank 2/3, pctl~67) -> fail
        # row 1: vol=60 (rank 3/3, pctl~100) -> fail
        # row 2: vol=20 (rank 1/3, pctl~33) -> pass
        assert mask.tolist() == [False, False, True]

    def test_pctl_gte(self):
        mask = evaluate_gates(self._df(), [("volatility", "pctl>=", 50)])
        # row 0: pctl~67 -> pass
        # row 1: pctl~100 -> pass
        # row 2: pctl~33 -> fail
        assert mask.tolist() == [True, True, False]

    def test_missing_column_skips_gate(self, capsys):
        # A gate referencing a column absent from the snapshot is skipped
        # (with a warning) rather than blocking every row — so old
        # snapshots lacking ocf_yield don't silently empty the result.
        mask = evaluate_gates(self._df(), [("nonexistent_col", ">=", 1.0)])
        assert mask.all()
        err = capsys.readouterr().err
        assert "nonexistent_col" in err and "WARN" in err
