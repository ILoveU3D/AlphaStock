"""Composite scoring: blend pillar scores into one ranking number.

The composite is a weight-renormalized average: for each stock the weights
of pillars with a missing score are dropped and the rest rescaled, so a
stock is never punished for a data gap. Stocks with fewer available
pillars than `min_pillars` (capped by the number of positive weights) get
NaN and drop out of the ranking.
"""

import pandas as pd

from .factors import PILLARS


def apply_composite(df: pd.DataFrame, weights: dict,
                    min_pillars: int = 3) -> pd.DataFrame:
    """Add composite_score and data_completeness columns.

    weights: {pillar: weight}; pillars with weight <= 0 are ignored.
    """
    out = df.copy()
    w = {p: float(weights.get(p, 0.0)) for p in PILLARS}
    positive = [p for p in PILLARS if w[p] > 0]
    required = min(min_pillars, len(positive))

    score_cols = [f"{p}_score" for p in PILLARS]
    for col in score_cols:
        if col not in out.columns:
            out[col] = float("nan")

    # data completeness: share of all pillar scores present
    out["data_completeness"] = (
        out[score_cols].notna().sum(axis=1) / len(PILLARS))

    num = pd.Series(0.0, index=out.index)
    den = pd.Series(0.0, index=out.index)
    avail = pd.Series(0, index=out.index)
    for p in positive:
        s = pd.to_numeric(out[f"{p}_score"], errors="coerce")
        valid = s.notna()
        num = num + s.fillna(0.0) * w[p]
        den = den + w[p] * valid.astype(float)
        avail = avail + valid.astype(int)

    composite = num / den.where(den > 0)
    out["composite_score"] = composite.where(avail >= required)
    return out


def rank_top(df: pd.DataFrame, n: int, markets=None) -> pd.DataFrame:
    """Top-N rows by composite_score (optionally filtered by market)."""
    out = df
    if markets:
        out = df[df["market"].isin(markets)]
    out = out.dropna(subset=["composite_score"])
    return out.sort_values("composite_score", ascending=False).head(n)
