"""gross-profitability — Novy-Marx (2013) gross profits to assets.

gp_ratio = gross_profit / assets — the single most powerful
profitability lens in Novy-Marx's horse race, priced gross profit
scaled by the asset base that produces it.

US ONLY: us_financials.csv carries gross_profit and assets (SEC
frames).  A-share snapshots carry no total-assets field and HK has no
balance-sheet source at all — those rows get NaN plus a data_gap
marker naming the missing field, never an improvised substitute.
Percentiles are computed within the US universe (the only rows with
data).

Lineage: Novy-Marx, "The Other Side of Value: The Gross Profitability
Premium" (JFE 2013).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl

GAP_A = "no total-assets field (A)"
GAP_HK = "no balance sheet (HK)"
GAP_US = "us_financials.csv absent"


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """gp_ratio / gp_pctl / data_gap columns for the pool."""
    out = df.copy()
    out["gp_ratio"] = np.nan
    if snap is not None:
        us_path = Path(snap) / "us_financials.csv"
        if us_path.exists():
            us = pd.read_csv(us_path, dtype={"ticker": str})
            if not us.empty:
                us = us.drop_duplicates(subset="ticker")
                gp = pd.to_numeric(us["gross_profit"], errors="coerce")
                assets = pd.to_numeric(us["assets"], errors="coerce")
                m = pd.DataFrame({
                    "market": "US", "code": us["ticker"].astype(str),
                    "_gp": gp / assets.where(assets > 0)})
                out = out.drop(columns=["gp_ratio"]).merge(
                    m.rename(columns={"_gp": "gp_ratio"}),
                    on=["market", "code"], how="left")
    gap = pd.Series(None, index=out.index, dtype=object)
    gap[out["market"] == "A"] = GAP_A
    gap[out["market"] == "HK"] = GAP_HK
    us_missing = (out["market"] == "US") & out["gp_ratio"].isna()
    gap[us_missing] = GAP_US
    out["data_gap"] = gap
    out["gp_pctl"] = xsec_pctl(out["gp_ratio"], out["market"],
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
    """Highest gp_ratio rows (US universe) + the target row's reading."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    ranked = (master.dropna(subset=["gp_ratio"])
              .sort_values("gp_ratio", ascending=False).head(top))
    cols = ["market", "code", "name", "gp_ratio", "gp_pctl"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "gross-profitability",
        "anchor": "毛利/总资产 (Novy-Marx 2013) 越高越好; 仅美股有资产"
                  "负债表, A/HK 行 data_gap 声明, 绝不编造替身",
        "pool": int(len(ctx["master"])),
        "scored": int(master["gp_ratio"].notna().sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "gp_ratio": num_or_none(h["gp_ratio"]),
                "gp_pctl": num_or_none(h["gp_pctl"]),
                "data_gap": (h["data_gap"]
                             if isinstance(h["data_gap"], str) else None),
            }
    return out
