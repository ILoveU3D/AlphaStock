"""vol-managed-momentum — Barroso & Santa-Clara (2015): momentum scaled
by its own realized volatility dodges momentum crashes.

vmm = mom_12_2 / volatility, where mom_12_2 = ret_250d − ret_20d (the
declared 12-2 difference approximation, see momentum-12-2) and
``volatility`` is the snapshot's annualized-% realized vol.  NaN when
mom is missing or vol is <= 0 / missing — a zero-vol print is a data
artifact, never a signal.  Percentiles within-market, higher = more
momentum per unit of own vol.  Master-only lens: ``snap`` unused.
"""

import pandas as pd

from .statsutil import num_or_none, xsec_pctl


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """vmm + within-market percentile, for scan/screen."""
    out = df.copy()
    r250 = pd.to_numeric(out.get("ret_250d"), errors="coerce")
    r20 = pd.to_numeric(out.get("ret_20d"), errors="coerce")
    vol = pd.to_numeric(out.get("volatility"), errors="coerce")
    out["mom_12_2"] = r250 - r20
    out["vmm"] = out["mom_12_2"] / vol.where(vol > 0)
    out["vmm_pctl"] = xsec_pctl(out["vmm"], out["market"].astype(str))
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Strongest vol-managed-momentum rows + the target row's reading."""
    master = scan_frame(ctx["master"])
    valid = master.dropna(subset=["vmm"])
    ranked = valid.sort_values("vmm", ascending=False).head(top)
    out = {
        "weapon": "vol-managed-momentum",
        "anchor": "按自身波动定档动量, 躲动量崩盘; vmm = mom_12_2 / "
                  "volatility (年化%); vol<=0 或缺失 → NaN, 不是信号",
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
                "volatility": num_or_none(h.get("volatility")),
                "vmm": num_or_none(h["vmm"]),
                "vmm_pctl": num_or_none(h["vmm_pctl"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "mom_12_2": num_or_none(r["mom_12_2"]),
            "volatility": num_or_none(r.get("volatility")),
            "vmm": num_or_none(r["vmm"]),
            "vmm_pctl": num_or_none(r["vmm_pctl"]),
        })
    return recs
