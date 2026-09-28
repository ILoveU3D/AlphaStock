"""Three-core scoring (user mandate 2026-09-29).

Business model / corporate culture / DCF cheapness are the ONLY ranking
dimensions, equally weighted. Every other signal (pillar scores,
composites, master votes) is veto/display-only.

Scores are ABSOLUTE anchor mappings (economic thresholds in
config.CORE_ANCHORS), never percentiles — ordinal percentile blending was
retired with the old funnel because it pretended to rank investment merit.
Missing inputs stay NaN and are declared in ``core_gaps`` — honesty over
fabrication.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

BUSINESS_PARTS = ("cash_conversion", "gross_margin", "roe",
                  "capex_to_ocf", "fcf_yield")


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _anchor(s: pd.Series, lo: float, hi: float) -> pd.Series:
    """Linear map lo->0, hi->100, clamped to [0, 100]; NaN preserved."""
    out = (s - lo) / (hi - lo) * 100.0
    return out.clip(0.0, 100.0)


def _mean_available(parts: list[pd.Series]) -> pd.Series:
    stacked = pd.concat(parts, axis=1)
    return stacked.mean(axis=1, skipna=True)


# ---------------------------------------------------------------------------
# Core 1: business model — does this machine convert revenue into cash?
# ---------------------------------------------------------------------------
def business_score(df: pd.DataFrame) -> pd.Series:
    parts = [_anchor(_num(df, c), *config.CORE_ANCHORS[c])
             for c in BUSINESS_PARTS]
    return _mean_available(parts)


# ---------------------------------------------------------------------------
# Core 2: culture — does management treat outside shareholders' cash as
# their own? Proxies only; A-share insider/buyback data, all markets get
# dividend honesty + book honesty. Gaps are declared per row.
# ---------------------------------------------------------------------------
def culture_score(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    # dividend honesty: borrowing to pay dividends is a confession
    bd = _num(df, "borrowed_dividend")
    s_div = (1.0 - bd) * 100.0

    # insider alignment (A-share radar columns only)
    hc = _num(df, "holder_cut_flag")
    dl = _num(df, "dilution_flag")
    bb = _num(df, "buyback_active")
    have_ins = hc.notna() | dl.notna() | bb.notna()
    cut = (hc == 1) | (dl == 1)
    s_ins = pd.Series(np.nan, index=df.index, dtype=float)
    s_ins[have_ins & cut] = 0.0
    s_ins[have_ins & ~cut & (bb == 1)] = 100.0
    s_ins[have_ins & ~cut & (bb != 1)] = 60.0   # no harm, no return

    # book honesty: earnings-quality flags; intel_red overrides to 0
    eq = _num(df, "eq_flags")
    red = _num(df, "intel_red")
    s_book = pd.Series(np.nan, index=df.index, dtype=float)
    s_book[eq == 0] = 100.0
    s_book[eq == 1] = 70.0
    s_book[eq == 2] = 40.0
    s_book[eq >= 3] = 0.0
    s_book[red == 1] = 0.0

    score = _mean_available([s_div, s_ins, s_book])

    gaps = []
    for idx in df.index:
        g = []
        if pd.isna(s_div.at[idx]):
            g.append("dividend-honesty unknown")
        if pd.isna(s_ins.at[idx]):
            g.append("insider/buyback data A-only")
        if pd.isna(s_book.at[idx]):
            g.append("eq data missing")
        gaps.append("; ".join(g))
    return score, pd.Series(gaps, index=df.index)


# ---------------------------------------------------------------------------
# Core 3: DCF — reverse-solve the FCF growth the current price implies,
# then score the expectation itself. Cheap = market asks for little.
# ---------------------------------------------------------------------------
def _value_multiple(g: float, r: float, tg: float, n: int) -> float:
    """PV per unit of current FCF: n years at growth g fading into a
    terminal Gordon stage at tg, all discounted at r."""
    pv = 0.0
    fcf = 1.0
    for t in range(1, n + 1):
        fcf *= (1.0 + g)
        pv += fcf / (1.0 + r) ** t
    pv += fcf * (1.0 + tg) / (r - tg) / (1.0 + r) ** n
    return pv


def implied_growth(fcf_yield_pct: float, r: float | None = None,
                   tg: float | None = None,
                   n: int | None = None) -> float | None:
    """Implied FCF growth (fraction, e.g. 0.03) given fcf_yield in percent.
    Clamped to config.DCF_IMPLIED_G_RANGE; None when unsolvable."""
    if fcf_yield_pct is None or not np.isfinite(fcf_yield_pct) \
            or fcf_yield_pct <= 0:
        return None
    r = config.DCF_DISCOUNT if r is None else r
    tg = config.DCF_TERMINAL_G if tg is None else tg
    n = config.DCF_FADE_YEARS if n is None else n
    lo, hi = config.DCF_IMPLIED_G_RANGE
    target = 100.0 / fcf_yield_pct            # price / FCF multiple
    if _value_multiple(lo, r, tg, n) >= target:
        return lo
    if _value_multiple(hi, r, tg, n) <= target:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _value_multiple(mid, r, tg, n) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def dcf_score(df: pd.DataFrame) -> pd.DataFrame:
    y = _num(df, "fcf_yield")
    lo, hi = config.DCF_IMPLIED_G_RANGE
    implied = y.map(implied_growth)
    # implied <= lo -> 100 (growth for free); implied >= hi -> 0 (no margin)
    score = ((hi - implied) / (hi - lo) * 100.0).clip(0.0, 100.0)
    return pd.DataFrame({
        "dcf_implied_g": implied * 100.0,     # percent, display convention
        "core_dcf": score,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
CORE_COLUMNS = ("core_business", "core_culture", "core_dcf",
                "dcf_implied_g", "core_score", "core_gaps")


def add_core_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Append the six core columns; pure function, no IO — safe to backfill
    old snapshots on demand."""
    out = df.copy()
    out["core_business"] = business_score(out)
    culture, culture_gaps = culture_score(out)
    out["core_culture"] = culture
    d = dcf_score(out)
    out["core_dcf"] = d["core_dcf"]
    out["dcf_implied_g"] = d["dcf_implied_g"]
    cores = out[["core_business", "core_culture", "core_dcf"]]
    out["core_score"] = cores.mean(axis=1, skipna=True)
    gaps = []
    for idx in out.index:
        g = []
        if pd.isna(out.at[idx, "core_business"]):
            g.append("business inputs missing")
        if culture_gaps.at[idx]:
            g.append(culture_gaps.at[idx])
        if pd.isna(out.at[idx, "core_dcf"]):
            g.append("no annual FCF")
        gaps.append("; ".join(g) or None)
    out["core_gaps"] = gaps
    return out
