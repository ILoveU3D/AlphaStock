"""Three-core scoring tests (2026-09-29 redesign, v2 rulings).

Cores rank by ABSOLUTE anchors, never percentiles. D2: a missing core is
imputed with the per-market mean and loudly declared in core_gaps. D3:
without profile distillation the culture core is veto-only — NaN, never
in the ranking.
"""
import numpy as np
import pandas as pd
import pytest

from value_genie import config
from value_genie.strategy import cores


def _df(**cols):
    return pd.DataFrame({k: [v] for k, v in cols.items()})


# ---------------------------------------------------------------------------
# anchors
# ---------------------------------------------------------------------------
def test_anchor_boundaries():
    s = pd.Series([50.0, 150.0, 100.0, None])
    out = cores._anchor(s, *config.CORE_ANCHORS["cash_conversion"])
    assert out.iloc[0] == 0.0 and out.iloc[1] == 100.0
    assert out.iloc[2] == 50.0 and pd.isna(out.iloc[3])


def test_anchor_reversed_capex():
    # capex_to_ocf anchors are (heavy=1.0 -> 0, light=0.1 -> 100)
    s = pd.Series([1.0, 0.1, 0.55])
    out = cores._anchor(s, *config.CORE_ANCHORS["capex_to_ocf"])
    assert out.iloc[0] == 0.0 and out.iloc[1] == 100.0
    assert out.iloc[2] == pytest.approx(50.0)


def test_business_score_all_best():
    df = _df(cash_conversion=200.0, gross_margin=80.0, roe=40.0,
             capex_to_ocf=0.05, fcf_yield=12.0)
    assert cores.business_score(df).iloc[0] == 100.0


def test_business_score_missing_parts_renormalize():
    df = _df(gross_margin=60.0, roe=25.0)   # only two parts, both best
    assert cores.business_score(df).iloc[0] == 100.0


def test_business_score_all_missing():
    df = _df(price=10.0)
    assert pd.isna(cores.business_score(df).iloc[0])


# ---------------------------------------------------------------------------
# reverse DCF
# ---------------------------------------------------------------------------
def test_implied_growth_perpetuity_sanity():
    # y = r - tg  =>  implied g should land near the terminal rate
    y = (config.DCF_DISCOUNT - config.DCF_TERMINAL_G) * 100.0
    g = cores.implied_growth(y)
    assert g is not None
    assert g == pytest.approx(config.DCF_TERMINAL_G, abs=0.005)


def test_implied_growth_clamps():
    lo, hi = config.DCF_IMPLIED_G_RANGE
    assert cores.implied_growth(50.0) == lo    # huge yield -> below range
    assert cores.implied_growth(0.1) == hi     # tiny yield -> above range
    assert cores.implied_growth(0.0) is None
    assert cores.implied_growth(None) is None


def test_dcf_score_direction():
    df = pd.DataFrame({"fcf_yield": [12.0, 0.5, None]})
    out = cores.dcf_score(df)
    assert out["core_dcf"].iloc[0] > out["core_dcf"].iloc[1]
    assert pd.isna(out["core_dcf"].iloc[2])
    assert pd.isna(out["dcf_implied_g"].iloc[2])


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def test_add_core_scores_columns_and_renorm():
    df = _df(gross_margin=60.0, roe=25.0, borrowed_dividend=0)
    out = cores.add_core_scores(df)
    for c in cores.CORE_COLUMNS:
        assert c in out.columns
    row = out.iloc[0]
    # business 100; culture veto-only (D3) and dcf unimputable (no donor)
    # -> core = mean of business alone
    assert row["core_score"] == 100.0
    assert pd.isna(row["core_culture"])
    assert "no annual FCF" in row["core_gaps"]
    assert cores.CULTURE_UNSCORED in row["core_gaps"]


def test_add_core_scores_all_missing():
    df = _df(price=10.0)
    out = cores.add_core_scores(df)
    assert pd.isna(out.iloc[0]["core_score"])
    assert "business inputs missing" in out.iloc[0]["core_gaps"]


# ---------------------------------------------------------------------------
# D2: market-mean imputation of missing cores
# ---------------------------------------------------------------------------
def _pool():
    """Two A rows (one with FCF, one without) + one HK row without."""
    return pd.DataFrame([
        {"market": "A", "code": "000001", "gross_margin": 60.0,
         "roe": 25.0, "fcf_yield": 8.0},
        {"market": "A", "code": "000002", "gross_margin": 60.0,
         "roe": 25.0, "fcf_yield": None},
        {"market": "HK", "code": "00700", "gross_margin": 60.0,
         "roe": 25.0, "fcf_yield": None},
    ])


def test_missing_core_imputed_with_own_market_mean():
    out = cores.add_core_scores(_pool())
    a_dcf = out.loc[0, "core_dcf"]              # the only A donor
    assert pd.notna(a_dcf)
    # the FCF-less A row inherits the A market mean, loudly declared
    assert out.loc[1, "core_dcf"] == pytest.approx(a_dcf)
    assert "core_dcf imputed = A market mean (no annual FCF)" \
        in out.loc[1, "core_gaps"]
    # the donor row itself carries no imputation note
    assert "imputed" not in (out.loc[0, "core_gaps"] or "")


def test_no_donor_in_market_stays_nan():
    out = cores.add_core_scores(_pool())
    # HK has zero FCF donors -> the HK row is NOT patched across markets
    assert pd.isna(out.loc[2, "core_dcf"])
    assert "no annual FCF" in out.loc[2, "core_gaps"]
    assert "imputed" not in out.loc[2, "core_gaps"]
    # ... and its core_score is the mean of what remains (business only)
    assert out.loc[2, "core_score"] == pytest.approx(
        out.loc[2, "core_business"])


def test_imputation_feeds_core_score():
    out = cores.add_core_scores(_pool())
    # imputed row: mean(business 100, imputed dcf) — not business alone
    expected = (100.0 + out.loc[1, "core_dcf"]) / 2.0
    assert out.loc[1, "core_score"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# D3: culture core re-activates only via distilled scores
# ---------------------------------------------------------------------------
def test_culture_param_enters_ranking():
    pool = _pool()
    culture = pd.Series([80.0, 40.0, 60.0], index=pool.index)
    out = cores.add_core_scores(pool, culture=culture)
    assert out["core_culture"].tolist() == [80.0, 40.0, 60.0]
    # three cores now averaged: row 0 = mean(business 100, culture 80, dcf)
    expected = (100.0 + 80.0 + out.loc[0, "core_dcf"]) / 3.0
    assert out.loc[0, "core_score"] == pytest.approx(expected)
    gap0 = out.loc[0, "core_gaps"]
    assert pd.isna(gap0) or cores.CULTURE_UNSCORED not in gap0


def test_culture_param_partial_missing_imputed():
    pool = _pool()
    culture = pd.Series([80.0, None, None], index=pool.index)
    out = cores.add_core_scores(pool, culture=culture)
    # A row without a profile inherits the A culture mean (= 80, one donor)
    assert out.loc[1, "core_culture"] == pytest.approx(80.0)
    assert "core_culture imputed = A market mean (no profile)" \
        in out.loc[1, "core_gaps"]
    # HK has no culture donor at all
    assert pd.isna(out.loc[2, "core_culture"])
    assert "no culture profile" in out.loc[2, "core_gaps"]
