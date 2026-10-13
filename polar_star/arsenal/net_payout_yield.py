"""net-payout-yield — Boudoukh et al. (2007) total payout yield,
LOWER BOUND form.

payout_yield_lb = dividend_yield + buyback_yield (%).  A-market
buyback_yield = sum(a_buybacks.amount_yuan, last 12m) / market_cap
x 100 — both sides are CNY (master A market_cap is yuan; amount_yuan
is yuan).  HK/US have no buyback-amount source in the snapshot:
dividend_yield only, flagged payout_basis='dividend_only_no_buyback_
source'.

Named payout_yield_lb on purpose: net issuance is NOT quantified
anywhere in the snapshot, so the true NET payout (dividends +
buybacks - issuance) can only be lower — this value is a LOWER BOUND,
declared, never dressed up as the full net number.

Missing dividend_yield is treated as 0 (no detected payout) — a
payout lens reads absence of payout as zero, not as missing data.

Lineage: Boudoukh, Michaely, Richardson, Roberts, "On the Importance
of Measuring Payout Yield" (Journal of Finance 2007).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl

BASIS_DIV_ONLY = "dividend_only_no_buyback_source"
BASIS_DIV_BB = "dividend+buyback_12m_announcements"


def _buyback_yields(snap) -> tuple[pd.Series, pd.Timestamp | None]:
    """code -> 12m buyback amount (yuan) from a_buybacks + ref date."""
    path = Path(snap) / "a_buybacks.csv"
    if not path.exists():
        return pd.Series(dtype=float), None
    bb = pd.read_csv(path, dtype={"code": str})
    if bb.empty:
        return pd.Series(dtype=float), None
    dates = pd.to_datetime(bb["announce_date"], errors="coerce")
    name = Path(snap).name
    try:
        ref = pd.Timestamp(name) if len(name) == 8 and name.isdigit() \
            else dates.max()
    except ValueError:
        ref = dates.max()
    if pd.isna(ref):
        return pd.Series(dtype=float), None
    last12 = bb[dates >= ref - pd.Timedelta(days=365)]
    if last12.empty:
        return pd.Series(dtype=float), ref
    amt = (pd.to_numeric(last12["amount_yuan"], errors="coerce")
           .groupby(last12["code"].astype(str)).sum())
    return amt, ref


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """buyback_yield / payout_yield_lb / payout_pctl columns."""
    out = df.copy()
    div = pd.to_numeric(out.get("dividend_yield"), errors="coerce")
    mcap = pd.to_numeric(out.get("market_cap"), errors="coerce")
    bb_yield = pd.Series(np.nan, index=out.index)
    basis = pd.Series(BASIS_DIV_ONLY, index=out.index, dtype=object)
    if snap is not None:
        amt, _ref = _buyback_yields(snap)
        if len(amt):
            is_a = out["market"] == "A"
            got = out.loc[is_a, "code"].astype(str).map(amt)
            yld = got / mcap.where(mcap > 0) * 100.0
            bb_yield[is_a] = yld.fillna(0.0)
            basis[is_a] = BASIS_DIV_BB
        else:
            bb_yield[out["market"] == "A"] = 0.0
    out["buyback_yield"] = bb_yield
    out["payout_basis"] = basis
    out["payout_yield_lb"] = (div.fillna(0.0)
                              + bb_yield.fillna(0.0))
    out["payout_pctl"] = xsec_pctl(out["payout_yield_lb"],
                                   out["market"], ascending=True)
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
    """Highest payout_yield_lb rows + the target row's reading."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"))
    ranked = (master.dropna(subset=["payout_yield_lb"])
              .sort_values("payout_yield_lb", ascending=False).head(top))
    cols = ["market", "code", "name", "dividend_yield", "buyback_yield",
            "payout_yield_lb", "payout_pctl", "payout_basis"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "net-payout-yield",
        "anchor": "分红+回购收益率下界 (lb): 净发行量快照无处可得, 真"
                  "净回报只会更低 — 下界已声明; HK/US 仅分红腿 "
                  "(无回购金额源)",
        "pool": int(len(ctx["master"])),
        "scored": int(master["payout_yield_lb"].notna().sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "dividend_yield": num_or_none(h["dividend_yield"]),
                "buyback_yield": num_or_none(h["buyback_yield"]),
                "payout_yield_lb": num_or_none(h["payout_yield_lb"]),
                "payout_pctl": num_or_none(h["payout_pctl"]),
                "payout_basis": (h["payout_basis"]
                                 if isinstance(h["payout_basis"], str)
                                 else None),
            }
    return out
