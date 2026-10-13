"""momentum-12-2 — Jegadeesh & Titman (1993) 12-month-skip-1-month price
momentum, as a cross-sectional lens.

mom_12_2 = ret_250d − ret_20d.  DECLARED APPROXIMATION: the snapshot
carries cumulative %-returns over fixed windows, so the difference of
the two cumulative returns stands in for the canonical compounded
window of months t-12..t-2 (exact for log returns, a close
approximation in %-space).  NaN when either leg is missing (short
history) — the stock is outside the momentum universe, never imputed.

Percentiles are within-market (xsec_pctl), higher = stronger momentum.
Master-only lens: scan_frame's ``snap`` parameter is accepted for the
sweepable-weapon contract and never used.
"""

import pandas as pd

from .statsutil import num_or_none, xsec_pctl


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """mom_12_2 + within-market percentile, for scan/screen."""
    out = df.copy()
    r250 = pd.to_numeric(out.get("ret_250d"), errors="coerce")
    r20 = pd.to_numeric(out.get("ret_20d"), errors="coerce")
    out["mom_12_2"] = r250 - r20
    out["mom_12_2_pctl"] = xsec_pctl(out["mom_12_2"],
                                     out["market"].astype(str))
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Strongest-momentum rows + the target row's reading."""
    master = scan_frame(ctx["master"])
    valid = master.dropna(subset=["mom_12_2"])
    ranked = valid.sort_values("mom_12_2", ascending=False).head(top)
    out = {
        "weapon": "momentum-12-2",
        "anchor": "mom_12_2 = ret_250d − ret_20d (%差近似 12-2 跳过近月"
                  "的复合窗口); 市场内分位越高动量越强; 任一脚缺失 "
                  "(短历史) → NaN 出池, 不填补",
        "pool": int(len(ctx["master"])),
        "valid": int(len(valid)),
        "top": _records(ranked),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "mom_12_2": num_or_none(h["mom_12_2"]),
                "mom_12_2_pctl": num_or_none(h["mom_12_2_pctl"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "ret_250d": num_or_none(r.get("ret_250d")),
            "ret_20d": num_or_none(r.get("ret_20d")),
            "mom_12_2": num_or_none(r["mom_12_2"]),
            "mom_12_2_pctl": num_or_none(r["mom_12_2_pctl"]),
        })
    return recs
