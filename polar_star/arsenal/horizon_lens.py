"""horizon-lens (老兵) — holding-period momentum windows over the six
pillars.

Migrated from strategy/horizons.py (scoring half) in the 2026-10-13
zero-algorithm move; behavior byte-identical.  The four horizon
DECLARATIONS (weights/gates/windows) stay in strategy/horizons.py —
this module is the measurement algorithm only.
"""

import sys

import pandas as pd

from .weighted_ranking import apply_composite

DEFAULT_MOMENTUM_COLS = ("ret_60d", "ret_250d")


def recompute_momentum_score(df: pd.DataFrame, cols) -> pd.Series:
    """Momentum pillar score from the given return columns.

    Same recipe as ``add_pillar_scores``: per-market percentile rank,
    mean of available sub-factors. When none of ``cols`` exist in the
    frame (old snapshots), falls back to the default window with a
    WARN; when no return column exists at all, returns all-NaN (the
    momentum weight then renormalizes away inside apply_composite).
    """
    available = [c for c in cols if c in df.columns]
    if not available:
        available = [c for c in DEFAULT_MOMENTUM_COLS if c in df.columns]
        if available:
            print(f"[WARN] horizon momentum columns missing; falling "
                  f"back to {'+'.join(available)}", file=sys.stderr)
    if not available:
        return pd.Series(float("nan"), index=df.index)
    subs = []
    for col in available:
        s = pd.to_numeric(df[col], errors="coerce")
        subs.append(s.groupby(df["market"]).rank(pct=True) * 100.0)
    return pd.concat(subs, axis=1).mean(axis=1)


def apply_horizon_score(df: pd.DataFrame, horizon, base_weights=None,
                        min_pillars: int = 3) -> pd.DataFrame:
    """Composite under a horizon lens.

    Momentum is measured on the horizon's window; weights come from the
    horizon itself, or from ``base_weights`` when combined with a
    strategy (the master's taste measured at the horizon's clock).
    Gates are NOT applied here — screening callers filter separately
    before calling this; the ask horizon profile is descriptive.
    """
    out = df.copy()
    out["momentum_score"] = recompute_momentum_score(
        out, horizon.momentum_cols)
    weights = (dict(base_weights) if base_weights is not None
               else dict(horizon.weights))
    return apply_composite(out, weights, min_pillars=min_pillars)


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, horizon: str = "mid", strategy: str = "",
        top: int = 15) -> dict:
    """Composite under a horizon lens over the pool."""
    from ..strategy.registry import get_horizon, get_strategy

    h = get_horizon(horizon)
    base = get_strategy(strategy).weights if strategy else None
    scored = apply_horizon_score(ctx["master"], h, base_weights=base)
    ranked = (scored.dropna(subset=["composite_score"])
              .sort_values("composite_score", ascending=False).head(top))
    cols = ["market", "code", "name", "composite_score", "momentum_score"]
    cols = [c for c in cols if c in ranked.columns]
    return {
        "weapon": "horizon-lens",
        "anchor": f"momentum window = {h.id} {h.momentum_cols}; "
                  "ultrashort/short answers carry the caution discipline",
        "horizon": h.id,
        "strategy": strategy or None,
        "pool": int(len(ctx["master"])),
        "top": ranked[cols].to_dict("records"),
    }
