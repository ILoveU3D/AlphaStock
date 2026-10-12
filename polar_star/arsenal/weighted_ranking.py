"""weighted-ranking (老兵, 轨B本体) — six-pillar percentile scores blended
into the weight-renormalized composite that practice has verified as an
undervaluation finder.

Migrated from strategy/factors.py (pillar half) + strategy/composite.py
in the 2026-10-13 zero-algorithm move; behavior byte-identical.

Pillars (each 0-100 percentile within the same market's candidate pool):
- value:     cheap PE / PB / PS and high dividend yield
- growth:   revenue and profit YoY growth
- quality:  ROE, gross/net margin, low leverage
- safety:   far from 52-week high, low volatility, deep drawdown
- momentum: 3-month and 12-month price return (trend following)
- cashflow: operating cash flow yield and cash conversion (Buffett focus)
"""

import pandas as pd

# (column, sign) pairs per pillar; sign -1 = lower is better.
PILLAR_FACTORS = {
    "value": [("pe_ttm", -1), ("pb", -1), ("ps", -1),
              ("dividend_yield", 1)],
    "growth": [("rev_yoy", 1), ("profit_yoy", 1), ("rev_q_yoy", 1)],
    "quality": [("roe", 1), ("gross_margin", 1), ("net_margin", 1),
                ("debt_ratio", -1)],
    "safety": [("pos_52w", -1), ("volatility", -1), ("drawdown_52w", 1)],
    "momentum": [("ret_60d", 1), ("ret_250d", 1)],
    "cashflow": [("ocf_yield", 1), ("cash_conversion", 1),
                 ("fcf_yield", 1)],
}

# Valuation ratios are only meaningful when positive (negative PE/PB/PS
# means losses or negative book; those rows get NaN for the sub-factor).
POSITIVE_ONLY = {"pe_ttm", "pb", "ps"}

PILLARS = ("value", "growth", "quality", "safety", "momentum", "cashflow")


# ---------------------------------------------------------------------------
# Pillar scores
# ---------------------------------------------------------------------------
def add_pillar_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add {pillar}_score columns (0-100 percentile, per market, mean of
    available sub-factor ranks)."""
    out = df.copy()
    for pillar, factors in PILLAR_FACTORS.items():
        subs = []
        for col, sign in factors:
            if col not in out.columns:
                continue
            s = pd.to_numeric(out[col], errors="coerce")
            if col in POSITIVE_ONLY:
                s = s.where(s > 0)
            if sign < 0:
                s = -s
            # rank within each market -> 0-100 percentile; a factor with
            # <=1 valid value in a multi-stock pool ranks against itself
            # (phantom 100) — mask it (a genuine single-stock market
            # keeps its 100)
            grp = out["market"]
            valid = s.notna().groupby(grp).transform("sum")
            size = s.groupby(grp).transform("size")
            ranked = s.groupby(grp).rank(pct=True) * 100.0
            ranked = ranked.where((valid > 1) | (size == 1))
            subs.append(ranked.rename(col))
        if subs:
            out[f"{pillar}_score"] = pd.concat(subs, axis=1).mean(axis=1)
        else:
            out[f"{pillar}_score"] = float("nan")
    return out


def pillar_columns() -> list:
    return [f"{p}_score" for p in PILLARS]


# ---------------------------------------------------------------------------
# Composite scoring: blend pillar scores into one ranking number.
#
# The composite is a weight-renormalized average: for each stock the
# weights of pillars with a missing score are dropped and the rest
# rescaled, so a stock is never punished for a data gap. Stocks with
# fewer available pillars than `min_pillars` (capped by the number of
# positive weights) get NaN and drop out of the ranking.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, strategy: str = "", top: int = 15, markets=None,
        min_pillars: int = 3) -> dict:
    """轨B: pillar scores + composite under a strategy's weights.

    strategy: registry strategy id (default "balanced"); weights are the
    strategy declaration, the algorithm is here.
    """
    from ..strategy.presets import normalize_weights
    from ..strategy.registry import get_strategy

    master = ctx["master"]
    if markets:
        master = master[master["market"].isin(markets)]
    s = get_strategy(strategy or "balanced")
    scored = apply_composite(add_pillar_scores(master),
                             normalize_weights(s.weights),
                             min_pillars=min_pillars)
    ranked = rank_top(scored, top)
    cols = ["market", "code", "name", "composite_score",
            "data_completeness"] + pillar_columns()
    cols = [c for c in cols if c in ranked.columns]
    return {
        "weapon": "weighted-ranking",
        "strategy": s.id,
        "anchor": "composite = weight-renormalized pillar percentile "
                  "blend; percentile within each market universe",
        "pool": int(len(master)),
        "scored": int(scored["composite_score"].notna().sum()),
        "top": ranked[cols].to_dict("records"),
    }
