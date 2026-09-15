"""Tests for the QMF consensus layer (masters-vote L1/L2)."""

import pandas as pd

from value_genie.strategy import consensus as cs
from value_genie.strategy.registry import Strategy, list_strategies, \
    register_strategy


def _frame():
    """Synthetic master.csv-style frame covering pass/fail/veto cases.

    volatility percentiles (rank pct within market A, vols 20/30/80):
    row1 -> 33.3 (fails livermore>=50 and sheng>=60, passes duan<=60)
    row2 -> 66.7 (passes livermore and sheng, fails duan<=60)
    pillar scores are synthetic (composites need them, as in master.csv)
    """
    def _scores(v, g, q, s, m, c):
        return {"value_score": v, "growth_score": g, "quality_score": q,
                "safety_score": s, "momentum_score": m,
                "cashflow_score": c}

    rows = [
        # low-vol quality compounder: passes the 5 fundamental masters
        {"market": "A", "code": "000001", "name": "低波优质", "price": 10.0,
         "pe_ttm": 12.0, "pb": 1.2, "roe": 25.0, "gross_margin": 60.0,
         "debt_ratio": 30.0, "ocf_yield": 8.0, "fcf_yield": 7.0,
         "borrowed_dividend": 0, "dividend_yield": 3.0,
         "profit_yoy": 20.0, "ret_60d": 5.0,
         "volatility": 20.0, "pos_52w": 70.0, **_scores(70, 80, 90, 70, 50, 85)},
        # cyclical peak: graham arithmetic + the two momentum masters
        {"market": "A", "code": "000002", "name": "周期顶", "price": 5.0,
         "pe_ttm": 4.0, "pb": 0.8, "roe": 25.0, "gross_margin": 10.0,
         "debt_ratio": 40.0, "ocf_yield": 30.0, "fcf_yield": 20.0,
         "borrowed_dividend": 0, "dividend_yield": 2.0,
         "profit_yoy": 250.0, "ret_60d": 5.0,
         "volatility": 30.0, "pos_52w": 70.0, **_scores(75, 65, 45, 50, 70, 65)},
        # nothing passes (negative-ish quality across the board)
        {"market": "A", "code": "000003", "name": "全挂", "price": 8.0,
         "pe_ttm": 60.0, "pb": 9.0, "roe": 2.0, "gross_margin": 5.0,
         "debt_ratio": 80.0, "ocf_yield": 0.5, "fcf_yield": 0.2,
         "borrowed_dividend": 1, "dividend_yield": 0.0,
         "profit_yoy": -30.0, "ret_60d": -20.0,
         "volatility": 80.0, "pos_52w": 5.0, **_scores(20, 30, 15, 25, 10, 20)},
    ]
    return pd.DataFrame(rows)


class TestMastersVote:
    def test_votes_and_pool(self):
        df = cs.masters_vote(_frame())
        # a stock passing master gates must exist in the pool
        pool = df[df["vote_count"] >= 1]
        assert not pool.empty
        # the quality compounder has the max vote count: the 5
        # fundamental masters (livermore/sheng need top-half vol)
        top = pool.loc[pool["vote_count"].idxmax()]
        assert top["code"] == "000001"
        assert top["vote_count"] == 5
        passed = set(top["masters_passed"].split(","))
        assert {"buffett", "munger", "graham", "duan",
                "sanhuyi"} <= passed
        assert "livermore" not in passed and "sheng" not in passed
        # the cyclical peak passes the value + momentum trio
        cyc = df[df["code"] == "000002"].iloc[0]
        cyc_passed = set(cyc["masters_passed"].split(","))
        assert {"graham", "livermore", "sheng"} <= cyc_passed
        assert "sanhuyi" not in cyc_passed  # div 2.0 < 2.5 gate
        # vote_count == number of 1-valued vote_ columns
        # (exclude vote_count itself, which also starts with "vote_")
        vote_cols = [c for c in df.columns
                     if c.startswith("vote_") and c != "vote_count"]
        assert (df["vote_count"]
                == df[vote_cols].sum(axis=1)).all()
        # all-fail stock gets zero votes and empty master list
        fail = df[df["code"] == "000003"].iloc[0]
        assert fail["vote_count"] == 0
        assert fail["masters_passed"] == ""

    def test_mean_composite_and_ranking(self):
        df = cs.rank_consensus(
            cs.masters_vote(_frame()), top_n=3)
        # ranked by vote_count desc
        assert df["vote_count"].is_monotonic_decreasing
        # mean_composite present for pooled rows
        assert df["mean_composite"].notna().any()


class TestSnapshotFlags:
    def test_profit_spike(self):
        df = cs.add_snapshot_flags(_frame())
        assert bool(df.loc[df["code"] == "000002", "profit_spike"].iloc[0])
        assert not bool(df.loc[df["code"] == "000001",
                               "profit_spike"].iloc[0])


class TestForwardPEDivergence:
    def test_price_cancels(self):
        # divergence == eps_ttm / eps_fwd; price must cancel.
        # forward_pe_divergence imports fetch_stock_ratings lazily from
        # intel.ratings, so patch that module's attribute.
        import value_genie.intel.ratings as ratings_mod
        row = pd.Series({"market": "A", "code": "000009", "name": "x",
                         "price": 45.7, "pe_ttm": 4.3})
        eps_ttm = 45.7 / 4.3

        class _Item:
            def __init__(self, eps):
                self.payload = {"eps_this_year": eps}

        orig = ratings_mod.fetch_stock_ratings
        ratings_mod.fetch_stock_ratings = (
            lambda code, name="": [_Item(eps_ttm / 1.96)])
        try:
            div = cs.forward_pe_divergence(row)
        finally:
            ratings_mod.fetch_stock_ratings = orig
        assert div is not None
        assert abs(div - 1.96) < 0.01
        assert div >= cs.CYCLE_TRAP_RATIO

    def test_non_a_returns_none(self):
        row = pd.Series({"market": "US", "code": "GSL", "name": "x",
                         "price": 45.7, "pe_ttm": 4.3})
        assert cs.forward_pe_divergence(row) is None

    def test_no_ratings_returns_none(self):
        import value_genie.intel.ratings as ratings_mod
        row = pd.Series({"market": "A", "code": "000567", "name": "x",
                         "price": 5.8, "pe_ttm": 7.2})
        orig = ratings_mod.fetch_stock_ratings
        ratings_mod.fetch_stock_ratings = lambda code, name="": None
        try:
            assert cs.forward_pe_divergence(row) is None
        finally:
            ratings_mod.fetch_stock_ratings = orig


class TestMasterRegistryIntact:
    def test_seven_masters_registered(self):
        ids = {s.id for s in list_strategies(kind="master")}
        assert {"buffett", "munger", "graham", "livermore",
                "duan", "sheng", "sanhuyi"} <= ids

    def test_custom_master_joins_the_vote(self):
        register_strategy(Strategy(
            id="vote_test_m", name="VTM", kind="master",
            weights={"value": 1.0}, gates=[("roe", ">=", 15.0)]))
        try:
            df = cs.masters_vote(_frame())
            assert "vote_vote_test_m" in df.columns
        finally:
            # restore the global registry for the rest of the suite
            from value_genie.strategy.registry import _STRATEGIES
            _STRATEGIES.pop("vote_test_m", None)
