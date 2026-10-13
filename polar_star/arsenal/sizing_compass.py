"""sizing-compass — how much to buy: three caps, take the minimum.

(a) Kelly cap: f* = p - (1-p)/b with params win_rate p=0.55, odds
    b=1.5; the cap is HALF-Kelly (f*/2) — the declared conservative
    default of the house (full Kelly is reported for reference).
(b) Risk-contribution cap: positions param = list of
    {market, code, weight} (default: just the target at 100%).
    Daily return series per position from snap/kline/<M>_<C>.csv
    (last 120 bars, common dates), covariance shrunk via
    ledoit_wolf_shrink; the target's weight is bisected on [0,1] so
    its risk-contribution SHARE <= risk_budget (0.25).  With a single
    position the share is 100% at any weight — the cap is honestly
    None + data_gap (needs >= 2 positions), never invented.
(c) Amihud exit cap: max weight = participation(0.10) x
    ADV_amount_21d / nav, ADV = mean of the kline ``amount`` column
    over the last 21 bars.  Currency: kline amount is raw listing
    currency — nav must match (declared).

final_cap = min of the available caps; ``binding`` names the binding
one.  Missing kline -> that cap is None + data_gap, never invented.
Lineage: Kelly (1956); Ledoit-Wolf shrinkage for the covariance;
Amihud (2002) liquidity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..fetch.kline import kline_cache_path, load_kline
from .statsutil import ledoit_wolf_shrink, num_or_none

RC_BARS = 120
ADV_BARS = 21
PARTICIPATION = 0.10


def kelly(win_rate: float = 0.55, odds: float = 1.5) -> tuple[float, float]:
    """(full Kelly f*, half-Kelly cap)."""
    f = win_rate - (1.0 - win_rate) / odds
    return f, f / 2.0


def _position_returns(ctx: dict, positions: list) -> tuple[pd.DataFrame | None, str | None]:
    """Aligned daily returns (last RC_BARS common dates); None + note
    when any position's kline is missing."""
    snap = ctx.get("snap")
    series = []
    for pos in positions:
        kl = ctx.get("kline")
        if kl is None or str(pos.get("market")) != str(ctx.get("_target_market")) \
                or str(pos.get("code")) != str(ctx.get("_target_code")):
            if snap is None:
                return None, "no snapshot dir in context"
            p = kline_cache_path(snap, str(pos["market"]), str(pos["code"]))
            kl = load_kline(p) if p.exists() else None
        if kl is None or "close" not in kl.columns:
            return None, f"kline missing for {pos.get('market')}_" \
                         f"{pos.get('code')}"
        s = pd.to_numeric(kl["close"], errors="coerce")
        if "date" in kl.columns:
            s.index = kl["date"].astype(str)
        series.append(s.pct_change().dropna().rename(
            f"{pos['market']}_{pos['code']}"))
    df = pd.concat(series, axis=1, join="inner").dropna().tail(RC_BARS)
    if len(df) < 30:
        return None, f"only {len(df)} common return observations (<30)"
    return df, None


def risk_contribution_cap(returns: pd.DataFrame, target_col: str,
                          weights: np.ndarray, risk_budget: float = 0.25) -> float | None:
    """Bisect the target weight in [0,1] so its risk-contribution share
    of the portfolio <= risk_budget; None when a single position makes
    the share degenerate (always 100%)."""
    if returns is None or returns.shape[1] < 2:
        return None
    cov = np.cov(returns.to_numpy(float), rowvar=False)
    cov, _delta = ledoit_wolf_shrink(cov, len(returns))
    ti = list(returns.columns).index(target_col)
    others = weights.copy()

    def rc_share(x: float) -> float:
        w = others.copy()
        w[ti] = x
        port_var = float(w @ cov @ w)
        if port_var <= 0:
            return 1.0
        return float(x * (cov @ w)[ti] / port_var)

    if rc_share(1.0) <= risk_budget:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if rc_share(mid) <= risk_budget:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def amihud_cap(kl: pd.DataFrame | None, nav: float = 1_000_000.0,
               participation: float = PARTICIPATION,
               bars: int = ADV_BARS) -> float | None:
    """participation x ADV(amount) / nav; None without the amount column."""
    if kl is None or "amount" not in kl.columns:
        return None
    amt = pd.to_numeric(kl["amount"], errors="coerce").dropna().tail(bars)
    if not len(amt) or amt.mean() <= 0 or nav <= 0:
        return None
    return float(participation * amt.mean() / nav)


def run(ctx: dict, win_rate: float = 0.55, odds: float = 1.5,
        positions: list | None = None, risk_budget: float = 0.25,
        nav: float = 1_000_000.0, participation: float = PARTICIPATION) -> dict:
    """Three caps, take the min (master row + kline in context)."""
    out = {
        "weapon": "sizing-compass",
        "anchor": "买多少——三数取最小: kelly_cap(半凯利) / risk_cap"
                  "(风险贡献份额≤预算) / liquidity_cap(Amihud退出上限), "
                  "final_cap = min, binding = 收紧的那一道",
    }
    row = ctx.get("row")
    kl = ctx.get("kline")
    if row is None:
        out["error"] = "row required (pass with_kline=(market, code))"
        return out

    full, half = kelly(win_rate, odds)
    out["kelly_full"] = num_or_none(full)
    out["kelly_cap"] = num_or_none(half)
    out["kelly_note"] = "half-Kelly is the conservative house default"

    # (b) risk-contribution cap
    if positions is None:
        positions = [{"market": row.get("market"), "code": row.get("code"),
                      "weight": 1.0}]
    positions = [dict(p) for p in positions]
    target_key = f"{row.get('market')}_{row.get('code')}"
    if not any(f"{p.get('market')}_{p.get('code')}" == target_key
               for p in positions):
        positions.append({"market": row.get("market"),
                          "code": row.get("code"), "weight": 1.0})
    risk_cap = None
    risk_note = None
    if len(positions) < 2:
        risk_note = "data_gap: risk-contribution cap needs >= 2 " \
                    "positions (single position contributes 100% of " \
                    "risk at any weight)"
    else:
        ctx2 = dict(ctx)
        ctx2["_target_market"] = row.get("market")
        ctx2["_target_code"] = row.get("code")
        rets, note = _position_returns(ctx2, positions)
        if rets is None:
            risk_note = f"data_gap: {note}"
        else:
            w = np.array([float(p.get("weight", 0.0)) for p in positions])
            w = w / w.sum() if w.sum() > 0 else w
            risk_cap = risk_contribution_cap(rets, target_key, w,
                                             risk_budget)
            if risk_cap is None:
                risk_note = "data_gap: degenerate covariance"
    out["risk_cap"] = num_or_none(risk_cap)
    if risk_note:
        out["risk_cap_note"] = risk_note

    # (c) Amihud exit cap
    liq = amihud_cap(kl, nav, participation)
    out["liquidity_cap"] = num_or_none(liq)
    if liq is None:
        out["liquidity_cap_note"] = "data_gap: kline amount column " \
                                    "required for ADV"

    caps = {"kelly_cap": out["kelly_cap"], "risk_cap": out["risk_cap"],
            "liquidity_cap": out["liquidity_cap"]}
    avail = {k: v for k, v in caps.items() if v is not None}
    out["final_cap"] = num_or_none(min(avail.values()) if avail else None)
    out["binding"] = (min(avail, key=avail.get) if avail else None)
    return out
