"""momentum-52w-high — George & Hwang (2004): closeness to the 52-week
high is the anchoring vehicle that carries momentum information.

One-lens weapon: the migrated kline factor ``pos_52w`` (0-100, position
of the last close inside the 52-week low-high range) IS the George-Hwang
gauge, so the lens is a passthrough plus the within-market percentile
(higher = closer to the high).  NaN when the snapshot lacks the factor
(short kline history) — never imputed.  Master-only lens: ``snap`` is
accepted for the sweepable contract and never used.
"""

import pandas as pd

from .statsutil import num_or_none, xsec_pctl


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """mom_52w_high (= pos_52w) + within-market percentile."""
    out = df.copy()
    pos = pd.to_numeric(out.get("pos_52w"), errors="coerce")
    out["mom_52w_high"] = pos
    out["mom_52w_high_pctl"] = xsec_pctl(pos, out["market"].astype(str))
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Closest-to-52w-high rows + the target row's reading."""
    master = scan_frame(ctx["master"])
    valid = master.dropna(subset=["mom_52w_high"])
    ranked = valid.sort_values("mom_52w_high", ascending=False).head(top)
    out = {
        "weapon": "momentum-52w-high",
        "anchor": "52 周高点贴近度 (pos_52w) 即 George-Hwang 锚定载体; "
                  "市场内分位越高越贴近高点; 短历史 NaN 不填补",
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
                "mom_52w_high": num_or_none(h["mom_52w_high"]),
                "mom_52w_high_pctl": num_or_none(h["mom_52w_high_pctl"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "mom_52w_high": num_or_none(r["mom_52w_high"]),
            "mom_52w_high_pctl": num_or_none(r["mom_52w_high_pctl"]),
        })
    return recs
