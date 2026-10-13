"""asset-growth-gate — Cooper-Gulen-Schill (2008) asset growth as a
return contra-indicator, veto-leaning.

High total-asset growth is the single strongest negative cross-section
signal in CGS: firms expanding their asset base fast (especially via
debt) subsequently underperform.  Veto when asset_growth >= ag_veto_pct
(default 50%: the canonical top-quintile cut needs a full cross-section
the toolkit does not hold — the absolute threshold is a DECLARED
stand-in for the quintile break).

DATA HONESTY: the snapshot holds no assets_prev anywhere —
- A: no total-assets field (a_balance carries receivable/inventory
  only)
- HK: no balance-sheet source at all
- US: us_financials carries `assets` but no `assets_prev`
so the cross-section lens is data_gap by construction; each market's
gap names its missing field.  Deep mode (ctx row): if the dossier's
models/<market>/<code>/raw/history.json years carry an assets /
total_assets field for >=2 fiscal years, asset_growth = (last/prev -
1) x 100 and the veto applies.  Current history schema has no such
field — deep mode reports the same honest gap until the gather layer
learns balance sheets.

NEVER substitute equity growth for asset growth: debt-funded
expansion is exactly what this factor catches.

Lineage: Cooper, Gulen, Schill, "Asset Growth and the Cross-Section
of Stock Returns" (Journal of Finance 2008).
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config
from .statsutil import num_or_none

AG_VETO_PCT = 50.0
GAPS = {
    "A": "no total-assets field (a_balance carries receivable/inventory "
         "only)",
    "HK": "no balance-sheet source in snapshot",
    "US": "us_financials carries assets but no assets_prev",
}
DEEP_GAP = "dossier history.json carries no assets/total_assets series"


def asset_growth(models_dir, market: str,
                 code: str) -> tuple[float | None, int]:
    """(asset_growth %, years_used) from the dossier history, or
    (None, n) when the assets series is absent/short."""
    path = (Path(models_dir) / market.lower() / code
            / "raw" / "history.json")
    try:
        h = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0
    vals = []
    for y in h.get("years") or []:
        if not isinstance(y, dict) or y.get("fy") is None:
            continue
        a = y.get("assets", y.get("total_assets"))
        if a is not None:
            vals.append((int(y["fy"]), float(a)))
    vals.sort(key=lambda t: t[0])
    if len(vals) < 2:
        return None, len(vals)
    prev, last = vals[-2][1], vals[-1][1]
    if prev <= 0:
        return None, len(vals)
    return (last / prev - 1.0) * 100.0, len(vals)


def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """Cross-section columns: asset_growth NaN + per-market data_gap."""
    out = df.copy()
    out["asset_growth"] = np.nan
    out["asset_growth_veto"] = False
    out["data_gap"] = out["market"].map(GAPS).where(
        out["market"].isin(GAPS), "no asset-growth source")
    return out


def run(ctx: dict, ag_veto_pct: float = AG_VETO_PCT,
        models_dir=None) -> dict:
    """Pool-level gap declaration + the target row's deep reading."""
    master = scan_frame(ctx["master"])
    out = {
        "weapon": "asset-growth-gate",
        "anchor": f"总资产高增长 = 未来收益反向指标: ≥{ag_veto_pct:.0f}% "
                  "即否决 (绝对阈值为 top-quintile 的声明替身); 快照无 "
                  "assets_prev → 横截面恒 data_gap, 深模看 dossier 历史"
                  "; 绝不用股权增长替代 (债务扩张正是本因子要抓的)",
        "ag_veto_pct": float(ag_veto_pct),
        "pool": int(len(ctx["master"])),
        "cross_section_gaps": {m: int(((master["market"] == m)
                                       & master["data_gap"].notna()).sum())
                               for m in sorted(master["market"].unique())},
    }
    row = ctx.get("row")
    if row is None:
        out["error"] = "no row in context (pass with_kline=(market, code))"
        return out
    market, code = str(row["market"]), str(row["code"])
    if market == "HK":
        code = code.zfill(5)
    mdir = Path(models_dir) if models_dir else Path(config.MODELS_DIR)
    growth, years_used = asset_growth(mdir, market, code)
    reading = {"market": market, "code": code,
               "years_used": int(years_used),
               "asset_growth": num_or_none(growth)}
    if growth is None:
        reading["data_gap"] = (GAPS.get(market) + "; " + DEEP_GAP
                               if market in GAPS else DEEP_GAP)
        reading["asset_growth_veto"] = None
    else:
        reading["asset_growth_veto"] = bool(growth >= ag_veto_pct)
    out["row"] = reading
    return out
