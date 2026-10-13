"""epv-scan — Greenwald's Earnings Power Value: normalized profit
capitalized at WACC, compared against the market price.

EPV_total = profit_adj / wacc;  shares = market_cap / price;
epv_per_share = EPV_total / shares;  epv_ratio = epv_per_share / price
(= profit_adj / (wacc x market_cap) — price cancels in the ratio).

Normalized profit by market (declared substitutes, never fabricated):
- US: us_financials.profit - oneoff (one-off stripping; NaN oneoff = 0).
- A:  a_financials.profit at the latest report_date per code — NO
  one-off stripping (the snapshot income report carries no one-off
  field; declared gap).  Rows are cumulative YTD for the quarter
  ending at report_date (one row per code, no report_type), so the
  profit is annualized as profit x 12/month — H1 x2, Q1 x4,
  Q3 x4/3, FY x1 — a zero-seasonality DECLARED proxy mirroring the
  HK branch (epv_basis='interim_xN_proxy'; seasonal names
  over/understate).  Non-quarter-end/unparsable dates -> NaN +
  'data_gap' basis, never fabricated.
- HK: hk_f10.profit — amounts are CNY, converted to HKD via the
  manifest fx_hkdcny.  When a code carries multiple report rows the
  annual one (report_type contains '年报') wins; a code with only an
  interim row (中报) is annualized as profit x 2 — a DECLARED proxy,
  flagged epv_basis='interim_x2_proxy'.

Honest limits: net profit stands in for EBIT x (1 - t) — a
conservative understatement for levered names, declared; the
maintenance-capex refinement is absent.  Loss-makers (profit_adj <= 0)
-> NaN.  WACC is flat (default 0.10): no per-stock beta — WACC is the
user's knob.

Lineage: Greenwald, Value Investing: From Graham to Buffett and Beyond
(2001) — the no-growth reproduction-value anchor.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .statsutil import num_or_none, xsec_pctl

WACC = 0.10


def _fx_hkdcny(snap) -> float | None:
    """fx_hkdcny (CNY per HKD) from the snapshot manifest, or None."""
    try:
        man = json.loads(
            (Path(snap) / "manifest.json").read_text(encoding="utf-8"))
        fx = float(man.get("fx_hkdcny"))
    except (OSError, ValueError, TypeError):
        return None
    return fx if fx > 0 else None


def _normalized_profits(snap) -> pd.DataFrame:
    """Long frame market/code/profit_adj/epv_basis (market currency)."""
    snap = Path(snap)
    frames = []

    us_path = snap / "us_financials.csv"
    if us_path.exists():
        us = pd.read_csv(us_path, dtype={"ticker": str})
        if not us.empty:
            us = us.drop_duplicates(subset="ticker")
            profit = pd.to_numeric(us["profit"], errors="coerce")
            oneoff = pd.to_numeric(us["oneoff"], errors="coerce")
            frames.append(pd.DataFrame({
                "market": "US", "code": us["ticker"].astype(str),
                "profit_adj": profit - oneoff.fillna(0.0),
                "epv_basis": "net_minus_oneoff",
            }))

    a_path = snap / "a_financials.csv"
    if a_path.exists():
        a = pd.read_csv(a_path, dtype={"code": str})
        if not a.empty:
            a = a.assign(_rd=pd.to_datetime(a["report_date"],
                                            errors="coerce"))
            a = (a.sort_values("_rd")
                 .drop_duplicates(subset="code", keep="last"))
            profit = pd.to_numeric(a["profit"], errors="coerce")
            # Rows are cumulative YTD for the quarter ending at
            # report_date: annualize as profit x 12/month (H1 x2,
            # Q1 x4, Q3 x4/3, FY x1) — zero-seasonality declared
            # proxy, same caliber as the HK branch.  Snapshot
            # 20261012: 11447/11451 rows are H1 -> x2.
            month = a["_rd"].dt.month
            factor = month.map({3: 4.0, 6: 2.0, 9: 4.0 / 3.0, 12: 1.0})
            basis = month.map({3: "interim_x4_proxy",
                               6: "interim_x2_proxy",
                               9: "interim_x1.33_proxy",
                               12: "annual"})
            basis = basis.where(
                factor.notna(), "data_gap: report_date not quarter-end")
            frames.append(pd.DataFrame({
                "market": "A", "code": a["code"].astype(str),
                "profit_adj": profit * factor,
                "epv_basis": basis,
            }))

    hk_path = snap / "hk_f10.csv"
    if hk_path.exists():
        hk = pd.read_csv(hk_path, dtype={"code": str})
        if not hk.empty:
            hk["code"] = hk["code"].astype(str).str.zfill(5)
            hk = hk.assign(
                _annual=hk["report_type"].astype(str).str.contains("年报"),
                _rd=pd.to_datetime(hk["report_date"], errors="coerce"))
            hk = (hk.sort_values(["_annual", "_rd"])
                  .drop_duplicates(subset="code", keep="last"))
            profit = pd.to_numeric(hk["profit"], errors="coerce")
            annual = hk["_annual"]
            profit_ann = profit * annual.map({True: 1.0, False: 2.0})
            basis = annual.map({True: "annual",
                                False: "interim_x2_proxy"})
            fx = _fx_hkdcny(snap)
            if fx:
                profit_hkd = profit_ann / fx  # CNY amount -> HKD
            else:
                profit_hkd = pd.Series(np.nan, index=hk.index)
                basis = "data_gap: fx_hkdcny missing"
            frames.append(pd.DataFrame({
                "market": "HK", "code": hk["code"],
                "profit_adj": profit_hkd, "epv_basis": basis,
            }))

    if not frames:
        return pd.DataFrame(
            columns=["market", "code", "profit_adj", "epv_basis"])
    return pd.concat(frames, ignore_index=True)


def scan_frame(df: pd.DataFrame, snap=None,
               wacc: float = WACC) -> pd.DataFrame:
    """epv_ratio / epv_per_share / epv_pctl / epv_basis columns."""
    out = df.copy()
    if snap is not None:
        prof = _normalized_profits(snap)
        out = out.merge(prof, on=["market", "code"], how="left")
    else:
        out["profit_adj"] = np.nan
        out["epv_basis"] = "data_gap: no snap (profits unreadable)"
    price = pd.to_numeric(out.get("price"), errors="coerce")
    mcap = pd.to_numeric(out.get("market_cap"), errors="coerce")
    profit = pd.to_numeric(out["profit_adj"], errors="coerce")
    profit = profit.where(profit > 0)  # loss-makers outside the lens
    shares = (mcap / price.where(price > 0)).where(mcap > 0)
    out["epv_total"] = profit / float(wacc)
    out["epv_per_share"] = out["epv_total"] / shares.where(shares > 0)
    out["epv_ratio"] = out["epv_per_share"] / price.where(price > 0)
    out["epv_pctl"] = xsec_pctl(out["epv_ratio"], out["market"],
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


def run(ctx: dict, top: int = 15, wacc: float = WACC) -> dict:
    """Highest epv_ratio rows + the target row's reading."""
    master = scan_frame(ctx["master"], snap=ctx.get("snap"), wacc=wacc)
    ranked = (master.dropna(subset=["epv_ratio"])
              .sort_values("epv_ratio", ascending=False).head(top))
    cols = ["market", "code", "name", "price", "market_cap",
            "epv_per_share", "epv_ratio", "epv_pctl", "epv_basis"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "epv-scan",
        "anchor": f"EPV/价格 ≥1 才说明盈利能力本身值回票价 (wacc={wacc}, "
                  "用户的旋钮); 净利替代 EBIT×(1−t) 属保守低估; "
                  "A/HK 中期利润按报告期年化(×12/月份, 零季节性声明代理)、"
                  "HK CNY→HKD 均已声明",
        "wacc": float(wacc),
        "pool": int(len(ctx["master"])),
        "scored": int(master["epv_ratio"].notna().sum()),
        "top": _records(ranked, cols),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "profit_adj": num_or_none(h["profit_adj"]),
                "epv_per_share": num_or_none(h["epv_per_share"]),
                "epv_ratio": num_or_none(h["epv_ratio"]),
                "epv_pctl": num_or_none(h["epv_pctl"]),
                "epv_basis": (h["epv_basis"]
                              if isinstance(h["epv_basis"], str) else None),
            }
    return out
