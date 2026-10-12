"""Three-core scoring (user mandate 2026-09-29).

Business model / corporate culture / DCF cheapness are the ONLY ranking
dimensions, equally weighted. Every other signal (pillar scores,
composites, master votes) is veto/display-only.

Scores are ABSOLUTE anchor mappings (economic thresholds in
config.CORE_ANCHORS), never percentiles — ordinal percentile blending was
retired with the old funnel because it pretended to rank investment merit.

v2 rulings (2026-09-29):
- D2 (missing cores): a NaN core is filled with the per-market mean of
  that core and the imputation is declared loudly in ``core_gaps``
  (plus the doctor missing-rate report) — a stock must not top a ranking
  just because its missing core was skipped, nor vanish because of it.
  Rows with no donor in their market stay NaN.
- D3 (culture): without profile distillation (Phase 5), culture is
  VETO-ONLY — the proxies (borrowed dividend, intel red, insider cuts)
  live in the L2 veto flags (strategy/consensus.py); ``core_culture``
  stays NaN and never enters the ranking. Pass a distilled score series
  via ``add_core_scores(..., culture=...)`` to re-activate the third core.
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

CULTURE_UNSCORED = "culture unscored (veto-only until profile " \
                   "distillation, D3)"


def _impute_market_mean(df: pd.DataFrame, col: str) -> tuple:
    """D2: fill NaN values of `col` with the per-market mean (NaN donors
    excluded). Returns (filled series, imputed mask). Falls back to the
    whole-frame mean without a market column; NaN stays when no donor
    exists in the row's market."""
    s = df[col]
    if "market" in df.columns:
        means = s.groupby(df["market"]).transform("mean")
    else:
        means = pd.Series(s.mean(), index=df.index, dtype=float)
    mask = s.isna() & means.notna()
    return s.fillna(means), mask


def add_core_scores(df: pd.DataFrame,
                    culture: pd.Series | None = None) -> pd.DataFrame:
    """Append the six core columns; pure function, no IO — safe to backfill
    old snapshots on demand.

    `culture`: optional distilled culture scores (Phase 5 profiles)
    aligned to df.index; when omitted the culture core is veto-only (D3)
    and excluded from the ranking.
    """
    out = df.copy()
    out["core_business"] = business_score(out)
    if culture is not None:
        out["core_culture"] = pd.to_numeric(
            pd.Series(culture, index=out.index), errors="coerce")
    else:
        out["core_culture"] = np.nan
    d = dcf_score(out)
    out["core_dcf"] = d["core_dcf"]
    out["dcf_implied_g"] = d["dcf_implied_g"]

    # D2: impute missing cores with the per-market mean, keeping the raw
    # NaN pattern so every imputation is declared in core_gaps
    raw = {c: out[c].copy()
           for c in ("core_business", "core_culture", "core_dcf")}
    imputed = {}
    for c in raw:
        if c == "core_culture" and culture is None:
            imputed[c] = pd.Series(False, index=out.index)
            continue
        out[c], imputed[c] = _impute_market_mean(out, c)

    cols = ["core_business", "core_culture", "core_dcf"]
    out["core_score"] = out[cols].mean(axis=1, skipna=True)

    gaps = []
    for idx in out.index:
        mkt = (str(out.at[idx, "market"])
               if "market" in out.columns else "pool")
        g = []
        if pd.isna(raw["core_business"].at[idx]):
            g.append(f"core_business imputed = {mkt} market mean "
                     f"(inputs missing)" if imputed["core_business"].at[idx]
                     else "business inputs missing")
        if culture is None:
            g.append(CULTURE_UNSCORED)
        elif pd.isna(raw["core_culture"].at[idx]):
            g.append(f"core_culture imputed = {mkt} market mean "
                     f"(no profile)" if imputed["core_culture"].at[idx]
                     else "no culture profile")
        if pd.isna(raw["core_dcf"].at[idx]):
            g.append(f"core_dcf imputed = {mkt} market mean "
                     f"(no annual FCF)" if imputed["core_dcf"].at[idx]
                     else "no annual FCF")
        gaps.append("; ".join(g) or None)
    out["core_gaps"] = gaps
    return out
