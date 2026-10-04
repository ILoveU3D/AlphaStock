"""Driver-based FCFF DCF engine — pure functions, no IO.

FCFF_t = EBIT_t x (1 - tax) + D&A_t - capex_t - dNWC_t, driven by explicit
revenue-growth and ebit-margin paths. Three scenarios x probabilities ->
probability-weighted per-share value (user mandate 2026-09-28: scenarios
replace point estimates). Reverse-DCF implied growth stays the cross-check
display line, never a ranking input here.
"""

from .. import config


def fcff_path(last_revenue: float, scenario: dict, years: int,
              tax_rate: float) -> list:
    """Forecast rows [{year, revenue, ebit, fcff}] for one scenario."""
    g, m = scenario["revenue_growth"], scenario["ebit_margin"]
    da_pct = scenario.get("da_pct_rev") or 0.0
    capex_pct = scenario.get("capex_pct_rev") or 0.0
    nwc_pct = scenario.get("nwc_pct_drev") or 0.0
    rows, prev = [], last_revenue
    for t in range(years):
        gt = g[t] if t < len(g) else g[-1]
        mt = m[t] if t < len(m) else m[-1]
        rev = prev * (1.0 + gt)
        ebit = rev * mt
        fcff = (ebit * (1.0 - tax_rate) + rev * da_pct
                - rev * capex_pct - (rev - prev) * nwc_pct)
        rows.append({"year": t + 1, "revenue": rev, "ebit": ebit,
                     "fcff": fcff})
        prev = rev
    return rows


def dcf_value(fcffs: list, wacc: float, terminal_g: float) -> float | None:
    """EV = PV(explicit FCFFs) + PV(Gordon terminal). None when the
    discount rate cannot support the terminal growth."""
    if not fcffs or wacc <= terminal_g:
        return None
    n = len(fcffs)
    pv = sum(f / (1.0 + wacc) ** (t + 1) for t, f in enumerate(fcffs))
    tv = fcffs[-1] * (1.0 + terminal_g) / (wacc - terminal_g)
    return pv + tv / (1.0 + wacc) ** n


def _per_share(ev: float | None, net_debt, shares) -> float | None:
    if ev is None or shares in (None, 0):
        return None
    nd = net_debt if net_debt is not None else 0.0
    return (ev - nd) / shares


def _or_default(val, default):
    """Explicit None check — 0/0.0 are legitimate inputs, `or` eats them."""
    return default if val is None else val


def run_model(history: dict, assumptions: dict,
              price: float | None) -> dict:
    """Full model: scenarios + weighted value + sensitivity + gaps."""
    gaps = list(history.get("gaps") or []) + list(
        assumptions.get("gaps") or [])
    last_rev = history["years"][-1].get("revenue")
    years = int(_or_default(assumptions.get("horizon_years"),
                            config.MODEL_HISTORY_YEARS))
    wacc = float(_or_default(assumptions.get("wacc"),
                             config.DCF_DISCOUNT))
    tg = float(_or_default(assumptions.get("terminal_g"),
                           config.DCF_TERMINAL_G))
    tax_raw = assumptions.get("tax_rate")
    tax = 0.15 if tax_raw is None else float(tax_raw)
    net_debt = assumptions.get("net_debt")
    shares = assumptions.get("shares")
    if last_rev in (None, 0):
        raise ValueError("history has no revenue — cannot forecast")
    if shares in (None, 0):
        gaps.append("shares missing -> per-share value unavailable")

    scenarios, weighted, psum = {}, 0.0, 0.0
    for name, sc in (assumptions.get("scenarios") or {}).items():
        rows = fcff_path(last_rev, sc, years, tax)
        ev = dcf_value([r["fcff"] for r in rows], wacc, tg)
        ps = _per_share(ev, net_debt, shares)
        prob = float(sc.get("prob") or 0.0)
        scenarios[name] = {"prob": prob, "ev": ev, "per_share": ps,
                           "forecast": rows}
        if ps is not None:
            weighted += ps * prob
            psum += prob
    weighted_ps = weighted / psum if psum > 0 and shares else None
    if psum <= 0:
        gaps.append("scenario probabilities sum to zero")
    upside = ((weighted_ps - price) / price * 100.0
              if weighted_ps is not None and price else None)
    if price is None:
        gaps.append("no current price -> upside unavailable")

    base = (assumptions.get("scenarios") or {}).get("base")
    sens_vals = []
    for w in config.MODEL_SENSITIVITY_WACC:
        row = []
        for g in config.MODEL_SENSITIVITY_TG:
            if base is None:
                row.append(None)
                continue
            rows = fcff_path(last_rev, base, years, tax)
            row.append(_per_share(
                dcf_value([r["fcff"] for r in rows], w, g),
                net_debt, shares))
        sens_vals.append(row)

    return {
        "id": history["id"], "market": history["market"],
        "code": history["code"], "history_hash": history["history_hash"],
        "currency": assumptions.get("currency") or history.get("currency"),
        "price": price, "wacc": wacc, "terminal_g": tg, "tax_rate": tax,
        "scenarios": scenarios, "weighted_per_share": weighted_ps,
        "upside_pct": upside,
        "sensitivity": {"wacc": list(config.MODEL_SENSITIVITY_WACC),
                        "terminal_g": list(config.MODEL_SENSITIVITY_TG),
                        "values": sens_vals},
        "gaps": sorted(set(gaps)),
    }
