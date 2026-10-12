"""Shared arsenal math: the gate-DSL evaluator and numeric helpers.

Every weapon consumes these primitives instead of re-implementing them
(single source).  ``evaluate_gates`` was migrated from
strategy/registry.py in the 2026-10-13 zero-algorithm move — gate
*declarations* stay in strategy/, gate *evaluation* is an algorithm and
lives in the arsenal.
"""

from __future__ import annotations


def evaluate_gates(df, gates: list, market_col: str = "market"):
    """Return a boolean mask: True if row passes all gates.

    Ops:
    - ">=", "<=" : absolute value comparison
    - "pctl>=", "pctl<=" : within-market percentile comparison
    """
    import pandas as pd

    if not gates:
        return pd.Series(True, index=df.index)
    mask = pd.Series(True, index=df.index)
    for col, op, val in gates:
        if col not in df.columns:
            # skip gates whose column is unavailable (e.g. old snapshot
            # lacking ocf_yield); warn so the user knows a filter was
            # dropped rather than silently blocking every row.
            import sys
            print(f"[WARN] gate skipped: column {col!r} not in snapshot "
                  f"(op={op}, val={val})", file=sys.stderr)
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if op == ">=":
            mask &= s >= val
        elif op == "<=":
            mask &= s <= val
        elif op == "pctl>=":
            # val is a percentile threshold; pass if stock's percentile
            # within its market is >= val
            pct = s.groupby(df[market_col]).rank(pct=True) * 100
            mask &= pct >= val
        elif op == "pctl<=":
            pct = s.groupby(df[market_col]).rank(pct=True) * 100
            mask &= pct <= val
    return mask


def num_or_none(v):
    """float(v) or None for NaN/inf/unparseable — registry-safe cast."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f
