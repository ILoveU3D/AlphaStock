"""Trading comps: same-industry peers from the snapshot master frame,
median multiples -> implied value range for the target.

Discipline (DCF-first, user mandate 2026-09-28): comps are a cross-check
reference, never a buy argument. EV/EBITDA is best-effort — inputs missing
means the multiple is declared absent, never fabricated.
"""

import numpy as np
import pandas as pd

MULTIPLES = ("pe_ttm", "pb", "ps")


def select_peers(master: pd.DataFrame, market: str, code: str,
                 industry: str | None, limit: int = 10) -> pd.DataFrame:
    """Same-market, same-industry (when given), self excluded, closest by
    market cap, capped at `limit`."""
    df = master[master["market"].astype(str) == market]
    df = df[df["code"].astype(str) != str(code)]
    if industry and "industry" in df.columns:
        same = df[df["industry"].astype(str) == str(industry)]
        df = same if not same.empty else df
    tgt_cap = pd.to_numeric(
        master.loc[(master["market"].astype(str) == market)
                   & (master["code"].astype(str) == str(code))
                   ]["market_cap"], errors="coerce")
    cap = pd.to_numeric(df["market_cap"], errors="coerce")
    if len(tgt_cap) and tgt_cap.iloc[0] and tgt_cap.iloc[0] > 0:
        prox = (np.log(cap / float(tgt_cap.iloc[0]))).abs()
    else:
        prox = pd.Series(0.0, index=df.index)
    return df.assign(_prox=prox).sort_values("_prox").head(limit) \
             .drop(columns=["_prox"]).reset_index(drop=True)


def comps_table(peers: pd.DataFrame) -> dict:
    """Peer multiple rows + medians (NaN skipped)."""
    rows = []
    for _, p in peers.iterrows():
        rows.append({
            "code": str(p.get("code")), "name": p.get("name"),
            "market_cap": _num(p.get("market_cap")),
            **{m: _num(p.get(m)) for m in MULTIPLES}})
    medians = {}
    for m in MULTIPLES:
        vals = [r[m] for r in rows if r[m] is not None]
        medians[m] = float(np.median(vals)) if vals else None
    return {"rows": rows, "medians": medians}


def implied_range(target: pd.Series, medians: dict) -> dict:
    """Median peer multiple x target per-share base -> implied price.
    low/mid/high = min/median/max of available implied values."""
    price = _num(target.get("price"))
    out, vals = {}, []
    for m, label in (("pe_ttm", "by_pe"), ("pb", "by_pb"),
                     ("ps", "by_ps")):
        tgt_m = _num(target.get(m))
        med = medians.get(m)
        v = (med * price / tgt_m
             if med and price and tgt_m and tgt_m > 0 else None)
        out[label] = v
        if v is not None:
            vals.append(v)
    out["low"] = min(vals) if vals else None
    out["mid"] = float(np.median(vals)) if vals else None
    out["high"] = max(vals) if vals else None
    return out


def _num(v):
    try:
        f = float(v)
        return f if f == f and np.isfinite(f) else None
    except (TypeError, ValueError):
        return None
