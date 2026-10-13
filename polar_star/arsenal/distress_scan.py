"""distress-scan — Altman Z (1968) / Ohlson O (1980) distress lenses as
a COVERAGE-HONEST component table: when the canonical score is
uncomputable the weapon reports coverage, never a verdict.  No
component is ever averaged over or invented.

Component map against the snapshot:
- x1 = working_capital / assets     GAP everywhere (no current-asset
  fields in any of the three sources)
- x2 = retained_earnings / assets   GAP everywhere
- x3 = EBIT / assets                GAP everywhere
- x4 = market_cap / liabilities     US only (master.market_cap x
  us_financials.liabilities, both USD)
- x5 = sales / assets               US only (us_financials.rev / assets)

z_partial is computed only when >= 4 components are available —
currently never — so z is always None.  Coverage verdicts: US rows get
"partial (2/5) — no canonical verdict"; A/HK rows get "no
balance-sheet fields".  Ohlson O with the same honesty: log(assets) +
liabilities/assets are available for US -> equally partial, no
canonical O-score.
"""

from pathlib import Path

import pandas as pd

from .statsutil import num_or_none

MIN_COMPONENTS = 4
US_VERDICT = ("partial (2/5) — no canonical verdict; Ohlson: "
              "log-assets + liabilities/assets only (partial)")
AHK_VERDICT = "no balance-sheet fields"
X4 = "x4_market_cap_over_liabilities"
X5 = "x5_sales_over_assets"


def _us_financials(snap) -> pd.DataFrame | None:
    if snap is None:
        return None
    p = Path(snap) / "us_financials.csv"
    if not p.exists():
        return None
    try:
        return pd.read_csv(p, dtype={"ticker": str})
    except (OSError, pd.errors.ParserError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """dz_x4 / dz_x5 (US only) + components_available + coverage verdict."""
    out = df.copy()
    out["dz_x4"] = float("nan")
    out["dz_x5"] = float("nan")
    us = _us_financials(snap)
    if us is not None:
        # one row per ticker (rare source dupes: keep the last)
        usm = us.drop_duplicates(subset="ticker", keep="last")
        usm = usm.set_index(usm["ticker"].astype(str))
        is_us = out["market"].astype(str) == "US"
        mc = pd.to_numeric(out["market_cap"], errors="coerce")
        tick = out["code"].astype(str)
        liab = pd.to_numeric(
            tick.map(usm["liabilities"]), errors="coerce")
        assets = pd.to_numeric(
            tick.map(usm["assets"]), errors="coerce")
        rev = pd.to_numeric(tick.map(usm["rev"]), errors="coerce")
        out.loc[is_us, "dz_x4"] = (mc / liab.where(liab > 0))[is_us]
        out.loc[is_us, "dz_x5"] = (rev / assets.where(assets > 0))[is_us]

    comps, verdicts = [], []
    for _, r in out.iterrows():
        if str(r["market"]) != "US":
            comps.append("")
            verdicts.append(AHK_VERDICT)
            continue
        avail = ([X4] if pd.notna(r["dz_x4"]) else []) + \
                ([X5] if pd.notna(r["dz_x5"]) else [])
        comps.append(",".join(avail))
        verdicts.append(US_VERDICT if avail else AHK_VERDICT)
    out["dz_components_available"] = comps
    out["dz_coverage"] = verdicts
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Coverage census + the most-covered US rows + target reading."""
    master = scan_frame(ctx["master"], ctx.get("snap"))
    counts = master["dz_coverage"].value_counts().to_dict()
    covered = master[master["dz_components_available"] != ""]
    ranked = covered.sort_values("dz_x4").head(top)
    out = {
        "weapon": "distress-scan",
        "anchor": "困境透镜——组件不全时只报覆盖度不下判决; x1/x2/x3 "
                  "全市场 GAP; x4/x5 仅 US; z 需>=4 组件, 当前永为 None",
        "pool": int(len(ctx["master"])),
        "coverage_counts": {str(k): int(v) for k, v in counts.items()},
        "lowest_x4": _records(ranked),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "z_partial": None,
                "x4": num_or_none(h["dz_x4"]),
                "x5": num_or_none(h["dz_x5"]),
                "components_available": (
                    h["dz_components_available"].split(",")
                    if h["dz_components_available"] else []),
                "coverage": str(h["dz_coverage"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "x4": num_or_none(r["dz_x4"]),
            "x5": num_or_none(r["dz_x5"]),
            "components_available": (
                r["dz_components_available"].split(",")
                if r["dz_components_available"] else []),
            "coverage": str(r["dz_coverage"]),
        })
    return recs
