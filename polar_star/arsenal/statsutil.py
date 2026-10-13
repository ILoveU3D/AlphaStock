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


# ---------------------------------------------------------------------------
# Cross-section helpers (weapons rank within the market universe, never
# globally — the percentile contract from the pillar machinery)
# ---------------------------------------------------------------------------
def winsorize(s, lo: float = 0.01, hi: float = 0.99):
    """Clip a Series to its [lo, hi] quantiles (outlier guard for
    ratio lenses whose tails are data errors, not signal)."""
    q_lo, q_hi = s.quantile(lo), s.quantile(hi)
    return s.clip(lower=q_lo, upper=q_hi)


def xsec_pctl(s, market, ascending: bool = True):
    """Within-market percentile rank (0-100). ``ascending=False`` flips
    so that *lower* raw values get *higher* percentiles (cheapness
    lenses: lowest PE -> 100th pctl)."""
    r = s.groupby(market).rank(pct=True, ascending=ascending) * 100.0
    return r


def zscore(s, market=None):
    """Cross-sectional z-score (within market when ``market`` given)."""
    if market is None:
        mu, sd = s.mean(), s.std(ddof=0)
        return (s - mu) / (sd if sd else 1.0)
    g = s.groupby(market)
    mu, sd = g.transform("mean"), g.transform("std")
    sd = sd.where(sd > 0, 1.0)
    return (s - mu) / sd


def decile(s, market=None):
    """1..10 bucket of the within-universe rank (1 = smallest values)."""
    if market is None:
        p = s.rank(pct=True)
    else:
        p = s.groupby(market).rank(pct=True)
    import numpy as np
    return np.ceil(p * 10.0).clip(1, 10)


# ---------------------------------------------------------------------------
# Time-series helpers
# ---------------------------------------------------------------------------
def ewma(s, halflife: float):
    """Exponentially weighted mean (pandas ewm under the hood)."""
    return s.ewm(halflife=halflife, adjust=False).mean()


def ols(y, x, with_const: bool = True):
    """Single-regressor OLS -> dict(beta, alpha, resid, r2).

    numpy-only; ``resid`` is the residual Series aligned with the
    intersection of non-NaN indices (weapons need the residuals for
    idiosyncratic-vol / Jones-model lenses)."""
    import numpy as np
    import pandas as pd

    yy = pd.to_numeric(pd.Series(y), errors="coerce")
    xx = pd.to_numeric(pd.Series(x), errors="coerce")
    df = pd.concat([yy, xx], axis=1).dropna()
    if len(df) < 10:
        return {"beta": None, "alpha": None,
                "resid": pd.Series(dtype=float), "r2": None,
                "n": int(len(df))}
    Y = df.iloc[:, 0].to_numpy(float)
    X = df.iloc[:, 1].to_numpy(float)
    A = np.column_stack([X, np.ones_like(X)]) if with_const else \
        X.reshape(-1, 1)
    coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
    yhat = A @ coef
    resid = pd.Series(Y - yhat, index=df.index)
    ss_res = float(((Y - yhat) ** 2).sum())
    ss_tot = float(((Y - Y.mean()) ** 2).sum())
    r2 = None if ss_tot == 0 else 1.0 - ss_res / ss_tot
    return {"beta": float(coef[0]),
            "alpha": (float(coef[1]) if with_const else 0.0),
            "resid": resid, "r2": r2, "n": int(len(df))}


def ledoit_wolf_shrink(cov, n_obs: int):
    """Ledoit-Wolf-style shrinkage of a covariance matrix toward its
    scaled identity (constant-correlation target simplified to the
    diagonal) — numpy-only closed form.

    Returns (shrunk_cov, delta) with delta in [0,1] the shrinkage
    intensity.  Reference: Ledoit & Wolf (2004) 'A well-conditioned
    estimator for large-dimensional covariance matrices'.  We use the
    identity-target variant: stable for the small asset counts of a
    portfolio lens; the constant-correlation refinement is a future
    upgrade if the matrix grows."""
    import numpy as np

    C = np.asarray(cov, dtype=float)
    k = C.shape[0]
    if k == 0:
        return C, 0.0
    # shrinkage target: scaled identity (mu * I), mu = average variance
    mu = float(np.trace(C) / k)
    T = mu * np.eye(k)
    # intensity heuristics: delta = k / (n * ||C - T||_F^2 + k) bounded
    # — a conservative closed form (LW's exact estimator needs the
    # sample tensor; this keeps the honest conditioning property).
    diff_norm2 = float(((C - T) ** 2).sum())
    delta = k / max(n_obs, 1) / (diff_norm2 + k / max(n_obs, 1)) \
        if diff_norm2 > 0 else 0.0
    delta = min(max(delta, 0.0), 1.0)
    return (1.0 - delta) * C + delta * T, delta


def pert_sample(rng, lo: float, mode: float, hi: float, size: int,
                lamb: float = 4.0):
    """PERT (modified beta) draws — the Monte-Carlo workhorse for
    three-point estimates (bear/base/bull) in DCF-style engines.

    PERT mean = (lo + lamb*mode + hi) / (lamb + 2); alpha/beta derived
    from that mean.  Reference: Malcolm et al. (1959) PERT; Vose's
    modified-PERT parameterisation."""
    import numpy as np

    lo, mode, hi = float(lo), float(mode), float(hi)
    if not lo < mode < hi:
        # degenerate triangle -> point mass at the mode (honest, no
        # fabricated dispersion)
        return np.full(size, mode, dtype=float)
    mean = (lo + lamb * mode + hi) / (lamb + 2.0)
    a = 1.0 + lamb * (mean - lo) / (hi - lo)
    b = 1.0 + lamb * (hi - mean) / (hi - lo)
    x = rng.beta(a, b, size=size)
    return lo + x * (hi - lo)
