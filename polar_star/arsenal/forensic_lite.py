"""forensic-lite — Beneish (1999) M-score SUBSET: the batch-computable
indices first ("可批量字段先行, 全量归纵深").  This is NOT the canonical
8-index M-score — no pseudo M-score is ever computed from the subset
with the original weights.  Instead each available index is compared to
its own Beneish dubious threshold and reported as a per-index flag.

- DSRI (A only) = (1 + rece_yoy/100) / (1 + rev_yoy/100) — DECLARED
  APPROXIMATION: yoy growth ratios stand in for the index's
  receivables/sales ratio-of-ratios (a_balance.rece_yoy x
  master.rev_yoy); dubious when > 1.465.  NaN when the revenue leg
  would divide by <= 0 (rev_yoy <= -100).
- SGI (all markets) = 1 + rev_yoy/100; dubious when > 1.608.
- TATA (US only) = (profit - ocf) / assets (us_financials); dubious
  when > 0.018.  NaN when assets <= 0 / missing.

Verdict only when >= 2 indices are available: "N/M indices dubious
(subset ≠ canonical M-score)"; otherwise data_gap.
"""

from pathlib import Path

import pandas as pd

from .statsutil import num_or_none

DSRI_DUBIOUS = 1.465
SGI_DUBIOUS = 1.608
TATA_DUBIOUS = 0.018
MIN_INDICES = 2
NOTE = "subset ≠ canonical M-score"
GAP = "data_gap (<2 indices available)"


def _read_csv(snap, name, key) -> pd.DataFrame | None:
    if snap is None:
        return None
    p = Path(snap) / name
    if not p.exists():
        return None
    try:
        return pd.read_csv(p, dtype={key: str})
    except (OSError, pd.errors.ParserError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """dsri/sgi/tata + per-index dubious flags + coverage verdict."""
    out = df.copy()
    rev_yoy = pd.to_numeric(out.get("rev_yoy"), errors="coerce")
    out["sgi"] = 1.0 + rev_yoy / 100.0

    # DSRI — A only (a_balance.rece_yoy x master.rev_yoy)
    out["dsri"] = float("nan")
    bal = _read_csv(snap, "a_balance.csv", "code")
    if bal is not None:
        bal = bal.drop_duplicates(subset="code", keep="last")
        rece = pd.to_numeric(
            out["code"].astype(str).map(
                bal.set_index(bal["code"].astype(str))["rece_yoy"]),
            errors="coerce")
        denom = 1.0 + rev_yoy / 100.0
        dsri = (1.0 + rece / 100.0) / denom.where(denom > 0)
        out.loc[out["market"].astype(str) == "A", "dsri"] = \
            dsri[out["market"].astype(str) == "A"]

    # TATA — US only (us_financials)
    out["tata"] = float("nan")
    us = _read_csv(snap, "us_financials.csv", "ticker")
    if us is not None:
        us = us.drop_duplicates(subset="ticker", keep="last")
        usm = us.set_index(us["ticker"].astype(str))
        tick = out["code"].astype(str)
        profit = pd.to_numeric(tick.map(usm["profit"]), errors="coerce")
        ocf = pd.to_numeric(tick.map(usm["ocf"]), errors="coerce")
        assets = pd.to_numeric(tick.map(usm["assets"]), errors="coerce")
        tata = (profit - ocf) / assets.where(assets > 0)
        out.loc[out["market"].astype(str) == "US", "tata"] = \
            tata[out["market"].astype(str) == "US"]

    out["dsri_flag"] = (out["dsri"] > DSRI_DUBIOUS).fillna(False)
    out["sgi_flag"] = (out["sgi"] > SGI_DUBIOUS).fillna(False)
    out["tata_flag"] = (out["tata"] > TATA_DUBIOUS).fillna(False)

    n_avail = out[["dsri", "sgi", "tata"]].notna().sum(axis=1)
    out["forensic_flag_count"] = (
        out[["dsri_flag", "sgi_flag", "tata_flag"]].sum(axis=1))
    out["forensic_indices"] = n_avail
    out["forensic_verdict"] = [
        (f"{int(f)}/{int(n)} indices dubious ({NOTE})"
         if n >= MIN_INDICES else GAP)
        for f, n in zip(out["forensic_flag_count"], n_avail)
    ]
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Most-flagged rows + verdict census + the target row's reading."""
    master = scan_frame(ctx["master"], ctx.get("snap"))
    flagged = master[master["forensic_flag_count"] > 0].sort_values(
        ["forensic_flag_count", "forensic_indices"],
        ascending=False).head(top)
    out = {
        "weapon": "forensic-lite",
        "anchor": "可批量字段先行, 全量归纵深; 逐指数对照 Beneish 阈值 "
                  "(DSRI>1.465 / SGI>1.608 / TATA>0.018); 子集 ≠ 规范 "
                  "M-score, 永不拼伪分",
        "pool": int(len(ctx["master"])),
        "rows_with_flags": int((master["forensic_flag_count"] > 0).sum()),
        "data_gaps": int((master["forensic_verdict"] == GAP).sum()),
        "most_flagged": _records(flagged),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "dsri": num_or_none(h["dsri"]),
                "sgi": num_or_none(h["sgi"]),
                "tata": num_or_none(h["tata"]),
                "dsri_flag": bool(h["dsri_flag"]),
                "sgi_flag": bool(h["sgi_flag"]),
                "tata_flag": bool(h["tata_flag"]),
                "flag_count": int(h["forensic_flag_count"]),
                "verdict": str(h["forensic_verdict"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "dsri": num_or_none(r["dsri"]),
            "sgi": num_or_none(r["sgi"]),
            "tata": num_or_none(r["tata"]),
            "dsri_flag": bool(r["dsri_flag"]),
            "sgi_flag": bool(r["sgi_flag"]),
            "tata_flag": bool(r["tata_flag"]),
            "flag_count": int(r["forensic_flag_count"]),
            "verdict": str(r["forensic_verdict"]),
        })
    return recs
