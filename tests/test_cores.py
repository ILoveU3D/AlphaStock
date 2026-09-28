"""Three-core scoring tests (2026-09-29 redesign).

Cores rank by ABSOLUTE anchors, never percentiles; missing inputs stay
NaN and are declared in core_gaps.
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
# culture
# ---------------------------------------------------------------------------
def test_culture_a_share_insider_cut():
    df = _df(borrowed_dividend=0, holder_cut_flag=1, dilution_flag=0,
             buyback_active=0, eq_flags=0, intel_red=0)
    score, gaps = cores.culture_score(df)
    # (div 100 + insider 0 + book 100) / 3
    assert score.iloc[0] == pytest.approx(200.0 / 3, abs=0.01)
    assert gaps.iloc[0] == ""


def test_culture_intel_red_overrides_book():
    df = _df(borrowed_dividend=0, holder_cut_flag=0, dilution_flag=0,
             buyback_active=1, eq_flags=0, intel_red=1)
    score, _ = cores.culture_score(df)
    # (100 + 100 + 0) / 3
    assert score.iloc[0] == pytest.approx(200.0 / 3, abs=0.01)


def test_culture_hk_us_gap_declared():
    # no radar columns at all -> only dividend honesty measurable
    df = _df(borrowed_dividend=0)
    score, gaps = cores.culture_score(df)
    assert score.iloc[0] == 100.0
    assert "insider/buyback data A-only" in gaps.iloc[0]
    assert "eq data missing" in gaps.iloc[0]


def test_culture_borrowed_dividend_confession():
    df = _df(borrowed_dividend=1, eq_flags=0)
    score, _ = cores.culture_score(df)
    # (0 + 100) / 2
    assert score.iloc[0] == 50.0


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
    # business 100, culture 100 (div only), dcf NaN -> core = 100
    assert row["core_score"] == 100.0
    assert "no annual FCF" in row["core_gaps"]
    assert "insider/buyback data A-only" in row["core_gaps"]


def test_add_core_scores_all_missing():
    df = _df(price=10.0)
    out = cores.add_core_scores(df)
    assert pd.isna(out.iloc[0]["core_score"])
    assert "business inputs missing" in out.iloc[0]["core_gaps"]

# ---------------------------------------------------------------------------
# AI-assessment blend (profile registry bridge, 2026-09-29)
# ---------------------------------------------------------------------------
def _frame_for_blend():
    # one row whose quant business = 60 and quant culture = 40:
    # gm 50 -> (50-20)/(80-20)*100 = 50?  use single-part frames instead
    return pd.DataFrame({
        "market": ["A"], "code": ["600900"],
        "gross_margin": [50.0],          # -> 50.0
        "borrowed_dividend": [0.0],      # s_div 100
        "eq_flags": [2.0],               # s_book 40 -> culture mean 70
        "fcf_yield": [np.nan],
    })


def test_blend_math():
    df = _frame_for_blend()
    base = cores.add_core_scores(df)
    q_bus = base.iloc[0]["core_business"]          # 50.0
    q_cul = base.iloc[0]["core_culture"]           # 70.0
    a = pd.DataFrame({"market": ["A"], "code": ["600900"],
                      "a_business": [80.0], "a_culture": [20.0]})
    out = cores.add_core_scores(df, assessments=a)
    w = config.PROFILE_BLEND
    row = out.iloc[0]
    assert row["core_business"] == pytest.approx(
        w * q_bus + (1 - w) * 80.0)
    assert row["core_culture"] == pytest.approx(
        w * q_cul + (1 - w) * 20.0)


def test_blend_assessment_alone_when_quant_nan():
    df = pd.DataFrame({"market": ["US"], "code": ["MU"]})
    a = pd.DataFrame({"market": ["US"], "code": ["MU"],
                      "a_business": [75.0], "a_culture": [None]})
    out = cores.add_core_scores(df, assessments=a)
    assert out.iloc[0]["core_business"] == 75.0
    assert pd.isna(out.iloc[0]["core_culture"])


def test_no_assessments_regression_lock():
    df = _frame_for_blend()
    a = cores.add_core_scores(df)
    b = cores.add_core_scores(df, assessments=None, stale_keys=None)
    pd.testing.assert_frame_equal(a, b)


def test_stale_keys_declared_in_gaps():
    df = _frame_for_blend()
    out = cores.add_core_scores(df, stale_keys={("A", "600900")})
    assert "AI assessment stale (raw updated)" in out.iloc[0]["core_gaps"]
    out2 = cores.add_core_scores(df, stale_keys={("US", "MU")})
    assert "stale" not in (out2.iloc[0]["core_gaps"] or "")


def test_unmatched_assessment_ignored():
    df = _frame_for_blend()
    a = pd.DataFrame({"market": ["US"], "code": ["NVDA"],
                      "a_business": [99.0], "a_culture": [99.0]})
    out = cores.add_core_scores(df, assessments=a)
    base = cores.add_core_scores(df)
    assert out.iloc[0]["core_business"] == base.iloc[0]["core_business"]
