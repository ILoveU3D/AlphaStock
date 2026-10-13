"""net-issuance-gate — Fama-French (2008) net stock issuance,
veto-leaning.

Companies that habitually issue shares (net issuers) underperform;
repurchasers outperform.  The snapshot lens uses the master's event
flags: dilution_flag == 1 -> net_issuer (veto); buyback_active == 1
-> repurchaser (bonus, pctl display only).  Rows where both flags are
NaN (HK/US in the current snapshot) get data_gap "no issuance events".

DECLARED STAND-IN (honesty): the event flags stand in for the
canonical split-adjusted share-count change over 12 months — the
snapshot carries no share-count history.  The mechanism (issuance
discipline predicts returns) is preserved; the input is a declared
event-level proxy.

Lineage: Fama-French, "Dissecting Anomalies" (Journal of Finance
2008) — net stock issuance as a cross-section return predictor.
"""

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl

GAP = "no issuance events"


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """net_issuer / repurchaser / issuance_score / veto / gap columns."""
    out = df.copy()
    dil = pd.to_numeric(out.get("dilution_flag"), errors="coerce")
    bb = pd.to_numeric(out.get("buyback_active"), errors="coerce")
    out["net_issuer"] = dil == 1
    out["repurchaser"] = bb == 1
    out["net_issuance_veto"] = out["net_issuer"]
    both_na = dil.isna() & bb.isna()
    score = pd.Series(np.nan, index=out.index)
    score[~both_na] = 0.0
    score[bb == 1] = 1.0
    score[dil == 1] = -1.0
    out["issuance_score"] = score
    out["issuance_pctl"] = xsec_pctl(score, out["market"],
                                     ascending=True)
    out["data_gap"] = pd.Series(
        np.where(both_na, GAP, None), index=out.index, dtype=object)
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
    """Net-issuers (veto bench) + repurchaser counts + target row."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    issuers = master[master["net_issuer"]].head(top)
    cols = ["market", "code", "name", "net_issuer", "repurchaser",
            "issuance_score", "issuance_pctl", "data_gap"]
    cols = [c for c in cols if c in issuers.columns]
    out = {
        "weapon": "net-issuance-gate",
        "anchor": "增发 = 向股东伸手 (否决); 回购 = 返还股东 (加分仅展示)"
                  "; 事件标志替代股本变动 (声明替代); HK/US 无事件源 "
                  "-> data_gap",
        "pool": int(len(ctx["master"])),
        "scored": int(master["issuance_score"].notna().sum()),
        "net_issuers": int(master["net_issuer"].sum()),
        "repurchasers": int(master["repurchaser"].sum()),
        "top": _records(issuers, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "net_issuer": bool(h["net_issuer"]),
                "repurchaser": bool(h["repurchaser"]),
                "net_issuance_veto": bool(h["net_issuance_veto"]),
                "issuance_score": num_or_none(h["issuance_score"]),
                "issuance_pctl": num_or_none(h["issuance_pctl"]),
                "data_gap": (h["data_gap"]
                             if isinstance(h["data_gap"], str) else None),
            }
    return out
