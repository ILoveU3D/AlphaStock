"""cash-profitability — Ball et al. (2016) cash-based operating
profitability, practical form.

cop_ratio = ocf / assets — operating cash flow scaled by the asset
base.  DECLARED practical form: the canonical Ball et al. numerator
(operating profit + R&D - accruals, roughly CFO-based operating
profitability) needs income-statement lines the snapshot does not
carry; OCF is the honest cash anchor the snapshot does carry.

US ONLY: us_financials.csv carries ocf and assets (SEC frames).
A-share snapshots carry no total-assets field and HK has no
balance-sheet source — those rows get NaN plus a data_gap marker,
never an improvised substitute.  Percentiles within the US universe.

Lineage: Ball, Gerakos, Linnainmaa, Nikolaev, "Accruals, Cash Flows,
and Operating Profitability in the Cross Section of Stock Returns"
(JFE 2016).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl

GAP_A = "no total-assets field (A)"
GAP_HK = "no balance sheet (HK)"
GAP_US = "us_financials.csv absent"


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """cop_ratio / cop_pctl / data_gap columns for the pool."""
    out = df.copy()
    out["cop_ratio"] = np.nan
    if snap is not None:
        us_path = Path(snap) / "us_financials.csv"
        if us_path.exists():
            us = pd.read_csv(us_path, dtype={"ticker": str})
            if not us.empty:
                us = us.drop_duplicates(subset="ticker")
                ocf = pd.to_numeric(us["ocf"], errors="coerce")
                assets = pd.to_numeric(us["assets"], errors="coerce")
                m = pd.DataFrame({
                    "market": "US", "code": us["ticker"].astype(str),
                    "_cop": ocf / assets.where(assets > 0)})
                out = out.drop(columns=["cop_ratio"]).merge(
                    m.rename(columns={"_cop": "cop_ratio"}),
                    on=["market", "code"], how="left")
    gap = pd.Series(None, index=out.index, dtype=object)
    gap[out["market"] == "A"] = GAP_A
    gap[out["market"] == "HK"] = GAP_HK
    us_missing = (out["market"] == "US") & out["cop_ratio"].isna()
    gap[us_missing] = GAP_US
    out["data_gap"] = gap
    out["cop_pctl"] = xsec_pctl(out["cop_ratio"], out["market"],
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
    """Highest cop_ratio rows (US universe) + the target row."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    ranked = (master.dropna(subset=["cop_ratio"])
              .sort_values("cop_ratio", ascending=False).head(top))
    cols = ["market", "code", "name", "cop_ratio", "cop_pctl"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "cash-profitability",
        "anchor": "OCF/总资产 (Ball et al 2016 实用形, 声明替代) 越高越"
                  "好; 仅美股有资产负债表, A/HK 行 data_gap 声明",
        "pool": int(len(ctx["master"])),
        "scored": int(master["cop_ratio"].notna().sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "cop_ratio": num_or_none(h["cop_ratio"]),
                "cop_pctl": num_or_none(h["cop_pctl"]),
                "data_gap": (h["data_gap"]
                             if isinstance(h["data_gap"], str) else None),
            }
    return out
