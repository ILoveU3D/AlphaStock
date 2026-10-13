"""earnings-yield-scan — E/P earnings yield + the house unified
cash-return benchmark.

earnings_yield = 100 / pe_ttm (%) — the reciprocal of the price paid
for one currency unit of TTM earnings, comparable against bond yields.
cash_return = earnings_yield + dividend_yield — the house unified
benchmark (现金回报复合分 = 100/PE + 股息率): what the business earns
plus what it pays out, in one number.

Loss-makers (pe_ttm <= 0 or NaN) are outside the lens -> NaN, never
zero-filled.  Percentiles are within-market only.

Lineage: Graham (earnings yield as the bond-comparable yardstick, The
Intelligent Investor 1949) + the house DCF rule ranking on cash the
owner actually receives.
"""

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """earnings_yield / cash_return / ey_pctl columns for the pool."""
    out = df.copy()
    pe = pd.to_numeric(out.get("pe_ttm"), errors="coerce")
    div = pd.to_numeric(out.get("dividend_yield"), errors="coerce")
    out["earnings_yield"] = 100.0 / pe.where(pe > 0)
    out["cash_return"] = out["earnings_yield"] + div.fillna(0.0)
    out["ey_pctl"] = xsec_pctl(out["cash_return"], out["market"],
                               ascending=True)
    return out


def _records(df: pd.DataFrame, cols) -> list[dict]:
    """JSON-safe records: numpy/pandas scalars -> py, NaN/inf -> None."""
    recs = []
    for row in df[cols].itertuples(index=False):
        rec = {}
        for c, v in zip(cols, row):
            if isinstance(v, str) or v is None:
                rec[c] = v
            elif isinstance(v, (bool, np.bool_)):
                rec[c] = bool(v)
            else:
                rec[c] = num_or_none(v)
        recs.append(rec)
    return recs


def run(ctx: dict, top: int = 15) -> dict:
    """Highest cash_return rows + the target row's reading."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    ranked = (master.dropna(subset=["cash_return"])
              .sort_values("cash_return", ascending=False).head(top))
    cols = ["market", "code", "name", "pe_ttm", "dividend_yield",
            "earnings_yield", "cash_return", "ey_pctl"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "earnings-yield-scan",
        "anchor": "现金回报复合分 = 100/PE + 股息率 (%), 市场内分位越高越"
                  "便宜; 亏损股在镜头外 (NaN, 绝不填零)",
        "pool": int(len(ctx["master"])),
        "scored": int(master["cash_return"].notna().sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "earnings_yield": num_or_none(h["earnings_yield"]),
                "cash_return": num_or_none(h["cash_return"]),
                "ey_pctl": num_or_none(h["ey_pctl"]),
            }
    return out
