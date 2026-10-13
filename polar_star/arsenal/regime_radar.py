"""regime-radar — online change-point alarm: price only wakes you up.

On the context kline daily returns (last ``window`` bars):

(a) BOCPD — Adams & MacKay (2007) Bayesian online change-point
    detection with a constant hazard H=1/250 and Normal-gamma
    conjugate updates (closed-form Student-T predictive, numpy-only;
    prior mu0=0, kappa0=1, alpha0=1, beta0=1e-4 — beta0 sized to the
    daily-return scale, all declared params).  Outputs the current
    run-length MAP estimate, P(run_length < 10) as the change
    probability, and the last detected regime-change date (the most
    recent bar whose run-length MAP reset to 0; None + note when no
    reset occurred in the window).
(b) CUSUM confirmation: cumulative sum of standardized returns vs a
    +/-4 (threshold param) band on the |final level|.
(c) OU half-life: AR(1) on log close (rho via statsutil.ols);
    half_life = -ln2/ln|rho| — None when |rho| >= 1 (honest:
    non-mean-reverting, half-life undefined).

Needs >= 120 bars.  DECLARED limit: the Gaussian BOCPD predictive
understates fat tails — change_prob is optimistic around crashes.
Lineage: Adams & MacKay (2007); Page (1954) CUSUM; Ornstein-Uhlenbeck
AR(1) half-life.
"""
from __future__ import annotations

import math
from math import lgamma

import numpy as np
import pandas as pd

from .statsutil import num_or_none, ols

MIN_BARS = 120
WINDOW = 500
HAZARD = 1.0 / 250.0
CUSUM_THRESHOLD = 4.0
RUN_SHORT = 10


def bocpd(x: np.ndarray, hazard: float = HAZARD, mu0: float = 0.0,
          kappa0: float = 1.0, alpha0: float = 1.0,
          beta0: float = 1e-4) -> tuple[np.ndarray, np.ndarray]:
    """Run-length posterior recursion.

    Returns (R, maps): R[t, r] = P(run_length_t = r | x_1..t); maps[t]
    = argmax run length at t.  O(T^2), vectorized inner steps."""
    x = np.asarray(x, dtype=float)
    T = len(x)
    R = np.zeros((T + 1, T + 1))
    R[0, 0] = 1.0
    maps = np.zeros(T + 1, dtype=int)
    mu = np.array([mu0])
    kappa = np.array([kappa0])
    alpha = np.array([alpha0])
    beta = np.array([beta0])
    for t in range(1, T + 1):
        xt = x[t - 1]
        nu = 2.0 * alpha
        var = beta * (kappa + 1.0) / (alpha * kappa)
        # Student-T predictive log pdf (closed form, no scipy)
        lg1 = np.array([lgamma((v + 1.0) / 2.0) for v in nu])
        lg2 = np.array([lgamma(v / 2.0) for v in nu])
        logpdf = (lg1 - lg2
                  - 0.5 * np.log(math.pi * nu * var)
                  - (nu + 1.0) / 2.0
                  * np.log1p((xt - mu) ** 2 / (nu * var)))
        pred = np.exp(logpdf - logpdf.max())
        prev = R[t - 1, :t]
        R[t, 1:t + 1] = prev * pred * (1.0 - hazard)
        R[t, 0] = float(np.sum(prev * pred)) * hazard
        s = R[t, :t + 1].sum()
        if s > 0:
            R[t, :t + 1] /= s
        mu_new = (kappa * mu + xt) / (kappa + 1.0)
        beta_new = beta + kappa * (xt - mu) ** 2 / (2.0 * (kappa + 1.0))
        mu = np.concatenate([[mu0], mu_new])
        kappa = np.concatenate([[kappa0], kappa + 1.0])
        alpha = np.concatenate([[alpha0], alpha + 0.5])
        beta = np.concatenate([[beta0], beta_new])
        maps[t] = int(np.argmax(R[t, :t + 1]))
    return R, maps


def cusum(x: np.ndarray, threshold: float = CUSUM_THRESHOLD) -> dict:
    """Standardized-return CUSUM; alarm on |final level| >= threshold."""
    x = np.asarray(x, dtype=float)
    sd = x.std(ddof=1)
    z = (x - x.mean()) / (sd if sd > 0 else 1.0)
    cs = np.cumsum(z)
    level = float(cs[-1])
    return {"level": num_or_none(level),
            "max_abs": num_or_none(float(np.abs(cs).max())),
            "alarm": bool(abs(level) >= threshold),
            "threshold": float(threshold)}


def ou_half_life(close: pd.Series) -> float | None:
    """AR(1) half-life on log close; None when |rho| >= 1 OR the implied
    half-life exceeds the sample length (unidentifiable on this horizon
    — honest non-mean-reversion read)."""
    c = pd.to_numeric(pd.Series(close), errors="coerce").dropna()
    c = c[c > 0]
    if len(c) < 30:
        return None
    y = np.log(c.to_numpy(float))
    fit = ols(y[1:], y[:-1])
    rho = fit["beta"]
    if rho is None or abs(rho) >= 1.0:
        return None
    hl = -math.log(2.0) / math.log(abs(rho))
    if not math.isfinite(hl) or hl > len(y):
        return None
    return float(hl)


def run(ctx: dict, window: int = WINDOW, hazard: float = HAZARD,
        cusum_threshold: float = CUSUM_THRESHOLD) -> dict:
    """Regime read for the context kline (>= 120 bars required)."""
    out = {
        "weapon": "regime-radar",
        "anchor": "状态突变在线报警——价格只负责叫醒: run_length_map = "
                  "当前状态已持续的K线数(MAP), change_prob = P(游程<10), "
                  "cusum.alarm = 标准化收益累计越界, ou_half_life_days = "
                  "均值回复半衰期(|ρ|≥1 时诚实为 None)",
    }
    kl = ctx.get("kline")
    if kl is None or not len(kl):
        out["error"] = "kline required (pass with_kline=(market, code))"
        return out
    if len(kl) < MIN_BARS:
        out["error"] = f"kline required (>= {MIN_BARS} bars; got {len(kl)})"
        return out
    close = pd.to_numeric(kl["close"], errors="coerce").dropna()
    if len(close) > window:
        kl = kl.iloc[-window:]
        close = close.iloc[-window:]
    rets = close.pct_change().dropna().to_numpy(float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < MIN_BARS - 1:
        out["error"] = "not enough valid returns after cleaning"
        return out

    R, maps = bocpd(rets, hazard)
    T = len(rets)
    change_prob = float(R[T, :RUN_SHORT].sum())
    resets = np.nonzero(maps[1:] == 0)[0] + 1     # t index where MAP==0
    last_change = None
    if len(resets) and "date" in kl.columns:
        t = int(resets[-1])
        dates = kl["date"].astype(str).to_numpy()
        if 1 <= t < len(dates):
            last_change = str(dates[t])
    elif len(resets):
        last_change = f"bar_index_{int(resets[-1])}"
    out["bocpd"] = {
        "run_length_map": int(maps[T]),
        "change_prob": num_or_none(change_prob),
        "last_change_date": last_change,
        "last_change_note": (None if last_change is not None else
                             "no run-length reset detected in window"),
        "hazard": hazard,
    }
    out["cusum"] = cusum(rets, cusum_threshold)
    out["ou_half_life_days"] = num_or_none(ou_half_life(close))
    out["limits_note"] = "Gaussian BOCPD understates fat tails " \
                         "(declared); change_prob optimistic in crashes"
    return out
