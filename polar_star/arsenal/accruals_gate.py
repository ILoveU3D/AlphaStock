"""accruals-gate — Sloan (1996) accruals anomaly, veto-leaning.

Primary lens, all markets: accrual_gap = 1 - cash_conversion / 100
= (NI - OCF) / NI — the share of earnings that is accrual, not cash.
UNITS DECLARED: master.csv cash_conversion is ocf/profit x 100 (in
percent), hence the /100.  The Sloan numerator (NI - OCF) is preserved;
the DENOMINATOR is profit, not total assets — declared stand-in,
because A/HK snapshots carry no total-assets field.

US adds the canonical tata = (profit - ocf) / assets from
us_financials.csv (Sloan's total-accruals-to-assets form) where the
balance sheet exists.

Veto: within-market percentile of accrual_gap >= 80 ->
accruals_veto=True.  High accruals = low earnings quality; this weapon
vetoes, it never ranks for admission.  Loss-makers flip the (NI-OCF)/NI
denominator sign — their gap is arithmetically reported but the lens
is designed for profit-carrying rows (the funnel's universe).

Lineage: Sloan, "Do Stock Prices Fully Reflect Information in Accruals
and Cash Flows About Future Earnings?" (The Accounting Review 1996).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl

ACCRUAL_VETO_PCTL = 80.0


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """accrual_gap / accrual_pctl / accruals_veto (+ US tata) columns."""
    out = df.copy()
    cc = pd.to_numeric(out.get("cash_conversion"), errors="coerce")
    out["accrual_gap"] = 1.0 - cc / 100.0
    out["accrual_pctl"] = xsec_pctl(out["accrual_gap"], out["market"],
                                    ascending=True)
    out["accruals_veto"] = out["accrual_pctl"] >= ACCRUAL_VETO_PCTL
    out["tata"] = np.nan
    if snap is not None:
        us_path = Path(snap) / "us_financials.csv"
        if us_path.exists():
            us = pd.read_csv(us_path, dtype={"ticker": str})
            if not us.empty:
                us = us.drop_duplicates(subset="ticker")
                profit = pd.to_numeric(us["profit"], errors="coerce")
                ocf = pd.to_numeric(us["ocf"], errors="coerce")
                assets = pd.to_numeric(us["assets"], errors="coerce")
                m = pd.DataFrame({
                    "market": "US", "code": us["ticker"].astype(str),
                    "_tata": (profit - ocf) / assets.where(assets > 0)})
                out = out.drop(columns=["tata"]).merge(
                    m.rename(columns={"_tata": "tata"}),
                    on=["market", "code"], how="left")
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
    """Worst accrual_gap rows (the veto bench) + the target row."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    ranked = (master.dropna(subset=["accrual_gap"])
              .sort_values("accrual_gap", ascending=False).head(top))
    cols = ["market", "code", "name", "cash_conversion", "accrual_gap",
            "accrual_pctl", "accruals_veto", "tata"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "accruals-gate",
        "anchor": f"高应计 = 利润含金量低 (否决胜场): accrual_gap 市场内 "
                  f"分位 ≥{ACCRUAL_VETO_PCTL:.0f} 即否决; 分母是利润而非"
                  "总资产 (声明替代), 美股另报 Sloan 原版 tata",
        "pool": int(len(ctx["master"])),
        "scored": int(master["accrual_gap"].notna().sum()),
        "vetoed": int(master["accruals_veto"].sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "accrual_gap": num_or_none(h["accrual_gap"]),
                "accrual_pctl": num_or_none(h["accrual_pctl"]),
                "accruals_veto": bool(h["accruals_veto"]),
                "tata": num_or_none(h["tata"]),
            }
    return out
