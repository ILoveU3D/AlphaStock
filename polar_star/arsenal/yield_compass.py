"""yield-compass — cross-market cash-return ruler + sanhuyi payback years.

cash_return = 100/pe_ttm + dividend_yield — the house unified
benchmark (现金回报复合分: earnings yield + dividend yield, both in %).

散户乙 payback years (赚免费股票, cost recovery from dividends):
- flat: 100 / dividend_yield (dy in %; dps held constant).
- growth-adjusted: solve n in Sum_{t=1..n} dps*(1+g)^t = price with
  g param (fraction, default 0).  With d = dy/100 = dps/price:
  d*(1+g)*((1+g)^n - 1)/g = 1  =>  n = ln(1 + g/(d*(1+g))) / ln(1+g).
  g=0 falls back to the flat form (its limit).  For g<0 the dividend
  stream decays; when the infinite sum d*(1+g)/|g| <= 1 the price is
  never recovered -> None with note (honest, no extrapolation).

Loss-makers (pe_ttm <= 0) -> cash_return None + note; no-dividend
rows (dy <= 0 or NaN) -> payback None + note; a NaN dividend leg is
treated as 0 INSIDE cash_return only, with the note declared.

sweepable: scan_frame adds cash_return + payback_years_flat columns
to a master frame.  Lineage: house cash-return rule + 散户乙 免费股票
(skill 17).
"""
from __future__ import annotations

import math

import pandas as pd

from .statsutil import num_or_none


def cash_return(pe_ttm: float, dividend_yield: float) -> tuple[float | None, str | None]:
    """100/pe + dy (%); None + note for loss-makers; NaN dy -> 0 leg."""
    pe = num_or_none(pe_ttm)
    if pe is None or pe <= 0:
        return None, "loss-maker or PE missing — earnings-yield leg " \
                     "undefined"
    dy = num_or_none(dividend_yield)
    note = None
    if dy is None:
        dy = 0.0
        note = "dividend leg absent — treated as 0 (declared)"
    return 100.0 / pe + dy, note


def payback_years_flat(dividend_yield: float) -> float | None:
    """100/dy years at a constant dividend; None without a dividend."""
    dy = num_or_none(dividend_yield)
    if dy is None or dy <= 0:
        return None
    return 100.0 / dy


def payback_years_growth(dividend_yield: float, g: float = 0.0) -> float | None:
    """Years to recover the price from dividends growing at g (fraction).

    Geometric-series closed form; g=0 -> flat; unrecoverable -> None."""
    dy = num_or_none(dividend_yield)
    if dy is None or dy <= 0:
        return None
    d = dy / 100.0
    if g == 0:
        return 1.0 / d
    if g <= -1.0:
        return None
    inner = 1.0 + g / (d * (1.0 + g))
    if inner <= 0:
        return None          # decaying stream never covers the price
    return math.log(inner) / math.log(1.0 + g)


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """Add cash_return + payback_years_flat columns (sweep lens).

    This lens is master-pure and ignores ``snap``; the parameter keeps
    the uniform scanner call signature.
    """
    out = df.copy()
    pe = pd.to_numeric(out.get("pe_ttm"), errors="coerce")
    dy = pd.to_numeric(out.get("dividend_yield"), errors="coerce")
    out["cash_return"] = [
        cash_return(p, d)[0] for p, d in zip(pe, dy)]
    out["payback_years_flat"] = [
        payback_years_flat(d) for d in dy]
    return out


def run(ctx: dict, g: float = 0.0, top: int = 15) -> dict:
    """Row reading + growth-adjusted payback (+ sweep top when master)."""
    out = {
        "weapon": "yield-compass",
        "anchor": "跨市场回报标尺 + 散户乙回本年数: cash_return = "
                  "100/PE + 股息率(%); payback_years = 股息收回成本"
                  "的年数(平价/增长调整)",
    }
    row = ctx.get("row")
    if row is None:
        out["error"] = "row required (pass with_kline=(market, code))"
        return out
    pe = num_or_none(row.get("pe_ttm"))
    dy = num_or_none(row.get("dividend_yield"))
    cr, note = cash_return(pe, dy)
    out["cash_return"] = num_or_none(cr)
    if note:
        out["cash_return_note"] = note
    flat = payback_years_flat(dy)
    out["payback_years_flat"] = num_or_none(flat)
    if flat is None:
        out["payback_note"] = "no dividend — payback undefined " \
                              "(散户乙 universe excludes non-payers)"
    out["payback_years_growth"] = num_or_none(
        payback_years_growth(dy, g))
    out["growth_param"] = g
    master = ctx.get("master")
    if master is not None and len(master):
        swept = scan_frame(master)
        ranked = swept.dropna(subset=["cash_return"]).sort_values(
            "cash_return", ascending=False).head(top)
        cols = [c for c in ("market", "code", "name", "pe_ttm",
                            "dividend_yield", "cash_return",
                            "payback_years_flat") if c in ranked.columns]
        out["top"] = ranked[cols].to_dict("records")
    return out
