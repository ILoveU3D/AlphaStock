"""expectations-engine — what does the price already pay for?

Three fused modules:

(a) Reverse-DCF implied growth: reuses ``core_triad.implied_growth``
    (the house reverse-DCF bisection) on the row's FCF yield — the
    growth the market has already paid for.  When ``fcf_yield`` is
    absent (HK/US rows where FCF is imputed upstream) but PE is
    positive, the earnings yield 100/pe_ttm is used as a DECLARED
    proxy (``implied_g_proxy``) — earnings overstate FCF, so the
    implied growth is then a lower bound read.
(b) Monte-Carlo DCF: 10-year explicit FCFF + Gordon terminal.  Growth
    ~ PERT(g_lo, g_mode, g_hi) % (defaults from rev_yoy: lo =
    max(rev_yoy,-5)-5, mode = rev_yoy clamped to [-10,20], hi =
    mode+5 — declared heuristics, AI-overridable via params, or via
    ``models/<market>/<code>/assumptions.json`` keys g_lo/g_mode/
    g_hi when that local-only dossier exists); terminal growth ~
    PERT(0,2,3)%; discount ~ PERT(8,10,12)%.  Fade: growth fades
    LINEARLY from g to the drawn terminal growth over years 6-10
    (years 1-5 grow at g).  n=10000 draws, numpy default_rng(seed=42).
    Draws with r <= tg (only possible under overridden params) are
    dropped and counted in ``n_valid``.
(c) CAP (competitive advantage period, Rappaport): years of
    g_implied growth the price implies beyond a no-growth EPV base
    (EPV = fcf0 / discount).  Solve n in [0, 40] such that
    DCF(g_implied, n years, then a no-growth perpetuity) ~= price
    (bisection).  cap_years = 0 when the price sits below the
    no-growth EPV (market pays for decline); None when 40 years of
    implied growth still cannot reach the price.

Honest gaps: fcf0 = fcf_yield% x price per share (yield-based, not a
bottom-up FCFF build); HK/US rows with imputed/missing fcf_yield get
``data_gap`` on the MC + CAP layers unless the PE proxy is acceptable.
Lineage: DCF house axiom (tower brick dcf-universal-law) + Mauboussin,
Expectations Investing (2001) + Rappaport, Creating Shareholder Value
(CAP).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .core_triad import implied_growth
from .statsutil import num_or_none, pert_sample

N_DRAWS = 10_000
SEED = 42
CAP_MAX_YEARS = 40.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dossier_growth(market: str, code: str) -> dict:
    """Optional AI dossier growth overrides (models/<m>/<c>/
    assumptions.json keys g_lo/g_mode/g_hi); {} when absent."""
    p = _repo_root() / "models" / str(market) / str(code) / \
        "assumptions.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for k in ("g_lo", "g_mode", "g_hi"):
        v = num_or_none(d.get(k))
        if v is not None:
            out[k] = v
    return out


def monte_carlo_dcf(fcf0_ps: float, price: float,
                    g_lo: float, g_mode: float, g_hi: float,
                    tg_lo: float = 0.0, tg_mode: float = 2.0,
                    tg_hi: float = 3.0,
                    r_lo: float = 8.0, r_mode: float = 10.0,
                    r_hi: float = 12.0,
                    n: int = N_DRAWS, seed: int = SEED) -> dict:
    """PERT-drawn 10y DCF; growth/terminal/discount params in percent.

    Returns fair-value distribution + P(undervalued); all-NaN (e.g.
    r<=tg everywhere under overrides) -> data_gap."""
    rng = np.random.default_rng(seed)
    g = pert_sample(rng, g_lo, g_mode, g_hi, n) / 100.0
    tg = pert_sample(rng, tg_lo, tg_mode, tg_hi, n) / 100.0
    r = pert_sample(rng, r_lo, r_mode, r_hi, n) / 100.0
    fcf = np.full(n, float(fcf0_ps))
    pv = np.zeros(n)
    for t in range(1, 11):
        gt = g if t <= 5 else g + (tg - g) * (t - 5) / 5.0
        fcf = fcf * (1.0 + gt)
        pv = pv + fcf / (1.0 + r) ** t
    tv = fcf * (1.0 + tg) / (r - tg) / (1.0 + r) ** 10
    fv = pv + tv
    fv = np.where((r > tg) & np.isfinite(fv), fv, np.nan)
    valid = fv[np.isfinite(fv)]
    if len(valid) < 100:
        return {"data_gap": f"only {len(valid)} valid draws "
                            "(r<=tg under overridden params?)"}
    med = float(np.median(valid))
    return {
        "p10": float(np.percentile(valid, 10)),
        "p25": float(np.percentile(valid, 25)),
        "p50": med,
        "p75": float(np.percentile(valid, 75)),
        "p90": float(np.percentile(valid, 90)),
        "mean": float(valid.mean()),
        "p_undervalued": float((valid > price).mean()),
        "mc_vs_price": (None if price <= 0 else med / price),
        "n_valid": int(len(valid)),
    }


def cap_years(fcf0_ps: float, price: float, g_implied: float,
              r: float = 0.10) -> float | None:
    """Years of g_implied (fraction) growth embedded in price beyond the
    no-growth EPV; bisection on [0, CAP_MAX_YEARS]."""
    if fcf0_ps <= 0 or price <= 0:
        return None

    def value(n: float) -> float:
        fcf = fcf0_ps
        pv = 0.0
        t = 0
        while t < int(n):
            t += 1
            fcf *= (1.0 + g_implied)
            pv += fcf / (1.0 + r) ** t
        # fractional tail year (interp on the final partial year)
        frac = n - int(n)
        if frac > 0:
            fcf_next = fcf * (1.0 + g_implied)
            pv += frac * fcf_next / (1.0 + r) ** (t + 1)
            fcf = fcf * (1.0 + g_implied) ** frac
        return pv + fcf / r / (1.0 + r) ** n

    if price <= value(0.0):
        return 0.0
    if g_implied <= 0 or value(CAP_MAX_YEARS) < price:
        return None     # beyond the 40-year CAP bound — honest overflow
    lo, hi = 0.0, CAP_MAX_YEARS
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if value(mid) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _row_fcf_ps(row: pd.Series) -> tuple[float | None, str]:
    """FCF per share from the master row + source tag.

    Primary: fcf_yield% x price.  Proxy (declared): earnings yield
    100/pe_ttm x price when FCF is absent but PE positive."""
    price = num_or_none(row.get("price"))
    fy = num_or_none(row.get("fcf_yield"))
    if price is None or price <= 0:
        return None, "no price"
    if fy is not None and fy > 0:
        return fy / 100.0 * price, "fcf_yield"
    pe = num_or_none(row.get("pe_ttm"))
    if pe is not None and pe > 0:
        return 1.0 / pe * price, "earnings_yield_proxy"
    return None, "no fcf_yield and no positive pe_ttm"


def run(ctx: dict, g_lo: float | None = None, g_mode: float | None = None,
        g_hi: float | None = None, tg_lo: float = 0.0,
        tg_mode: float = 2.0, tg_hi: float = 3.0, r_lo: float = 8.0,
        r_mode: float = 10.0, r_hi: float = 12.0, n: int = N_DRAWS,
        seed: int = SEED, discount: float = 0.10) -> dict:
    """Expectations read for the context row (master row required)."""
    out = {
        "weapon": "expectations-engine",
        "anchor": "市场预期 vs 我的分布——P(低估) 与隐含竞争优势期: "
                  "implied_g = 价格已付的增长; p_undervalued = 我的分布"
                  "高于价格的比例; cap_years = 价格隐含的竞争优势期",
    }
    row = ctx.get("row")
    if row is None:
        out["error"] = "row required (pass with_kline=(market, code))"
        return out
    price = num_or_none(row.get("price"))
    fy = num_or_none(row.get("fcf_yield"))
    pe = num_or_none(row.get("pe_ttm"))

    # (a) reverse-DCF implied growth (house bisection, reused)
    imp = None
    proxy = None
    if fy is not None and fy > 0:
        imp = implied_growth(fy)
    elif pe is not None and pe > 0:
        imp = implied_growth(100.0 / pe)
        proxy = ("earnings_yield_proxy (fcf_yield absent; earnings "
                 "overstate FCF -> implied_g is a lower-bound read)")
    out["implied_g_pct"] = num_or_none(None if imp is None
                                       else imp * 100.0)
    if proxy:
        out["implied_g_proxy"] = proxy

    # shared fcf-per-share base for (b)/(c)
    fcf0_ps, fcf_src = _row_fcf_ps(row)
    out["fcf_per_share_src"] = fcf_src
    if fcf0_ps is None or price is None or price <= 0:
        out["monte_carlo"] = {"data_gap": fcf_src}
        out["cap_years"] = None
        out["cap_note"] = fcf_src
        return out

    # (b) Monte-Carlo DCF
    dossier = {} if g_lo is not None else _dossier_growth(
        row.get("market"), row.get("code"))
    rev = num_or_none(row.get("rev_yoy"))
    notes = []
    if g_mode is None:
        g_mode = dossier.get("g_mode")
        if g_mode is not None:
            notes.append("g_mode from models dossier assumptions.json")
    if g_mode is None:
        if rev is None:
            g_mode = 0.0
            notes.append("rev_yoy missing — flat-growth prior "
                         "(-5/0/+5)")
        else:
            g_mode = min(max(rev, -10.0), 20.0)
    if g_lo is None:
        g_lo = dossier.get("g_lo")
        if g_lo is None:
            g_lo = (max(rev, -5.0) - 5.0) if rev is not None else -5.0
    if g_hi is None:
        g_hi = dossier.get("g_hi")
        if g_hi is None:
            g_hi = g_mode + 5.0
    g_lo = min(g_lo, g_mode - 1.0)
    g_hi = max(g_hi, g_mode + 1.0)
    mc = monte_carlo_dcf(fcf0_ps, price, g_lo, g_mode, g_hi,
                         tg_lo, tg_mode, tg_hi, r_lo, r_mode, r_hi,
                         n=n, seed=seed)
    mc["params"] = {"g": [g_lo, g_mode, g_hi],
                    "tg": [tg_lo, tg_mode, tg_hi],
                    "r": [r_lo, r_mode, r_hi],
                    "fade": "linear g->tg over years 6-10",
                    "seed": seed}
    if notes:
        mc["notes"] = notes
    out["monte_carlo"] = mc

    # (c) CAP
    if imp is None:
        out["cap_years"] = None
        out["cap_note"] = "implied growth unsolvable (no fcf/pe base)"
    else:
        out["cap_years"] = num_or_none(
            cap_years(fcf0_ps, price, imp, r=discount))
        if out["cap_years"] is None:
            out["cap_note"] = "price beyond the 40y CAP bound at " \
                              "the implied growth"
    return out
