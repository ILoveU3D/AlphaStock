"""magic-formula — Greenblatt's cheap-and-good double rank.

ey_rank  = within-market percentile of 100/pe_ttm (higher E/P = better);
roc_rank = within-market percentile of roe (higher = better);
mf_score = ey_rank + roc_rank;  mf_rank = within-market rank of
mf_score, 1 = best.

DECLARED SUBSTITUTES (honesty): E/P and ROE stand in for the canonical
EBIT/EV and EBIT/(net working capital + net fixed assets) — the
snapshot carries no EBIT, EV, NWC or fixed-asset fields.  The verified
mechanism (cheap + good double rank, neither leg sufficient alone) is
preserved; the inputs are declared stand-ins, never fabricated.

Loss-makers (pe_ttm <= 0/NaN) and non-positive ROE rows are outside
the lens -> NaN.

Lineage: Greenblatt, The Little Book That Beats the Market (2005).
"""

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """ey_rank / roc_rank / mf_score / mf_rank columns for the pool."""
    out = df.copy()
    pe = pd.to_numeric(out.get("pe_ttm"), errors="coerce")
    roe = pd.to_numeric(out.get("roe"), errors="coerce")
    out["mf_ey"] = 100.0 / pe.where(pe > 0)
    out["ey_rank"] = xsec_pctl(out["mf_ey"], out["market"],
                               ascending=True)
    out["roc_rank"] = xsec_pctl(roe.where(roe > 0), out["market"],
                                ascending=True)
    out["mf_score"] = out["ey_rank"] + out["roc_rank"]
    out["mf_rank"] = (out["mf_score"].groupby(out["market"])
                      .rank(ascending=False, method="min"))
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
    """Best mf_rank rows + the target row's reading."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    ranked = (master.dropna(subset=["mf_score"])
              .sort_values("mf_score", ascending=False).head(top))
    cols = ["market", "code", "name", "pe_ttm", "roe", "mf_ey",
            "ey_rank", "roc_rank", "mf_score", "mf_rank"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "magic-formula",
        "anchor": "便宜+好双排名: E/P 与 ROE 为 EBIT/EV 与 EBIT/(NWC+净"
                  "固定资产) 的声明替代品; mf_rank=1 最优; 亏损/负ROE "
                  "在镜头外",
        "pool": int(len(ctx["master"])),
        "scored": int(master["mf_score"].notna().sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "ey_rank": num_or_none(h["ey_rank"]),
                "roc_rank": num_or_none(h["roc_rank"]),
                "mf_score": num_or_none(h["mf_score"]),
                "mf_rank": num_or_none(h["mf_rank"]),
            }
    return out
