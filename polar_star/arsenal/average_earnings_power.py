"""average-earnings-power — Graham's 7-10yr average-earnings PE: the
cyclicality-corrected denominator (周期股修分母).

A single TTM PE on a cyclical reads cheap at the peak and dear at the
trough; Graham's fix is to divide price by AVERAGE earnings over a
full cycle (7-10 years), not one year.  ae_pe = market_cap /
avg_profit; cycle_adjustment = ae_pe / pe_ttm (>1: TTM earnings are
above the cycle average — the PE flattered by the cycle).

Deep weapon (sweepable=false): the profit history comes from
models/<market>/<code>/raw/history.json (years[].net_income + the
dossier currency) — the only >=7yr series the toolkit holds.
us_financials profit_prev is ONE prior year: insufficient alone,
declared, never stretched into a fake cycle.  HK histories are CNY
while market_cap is HKD — converted via the snapshot manifest
fx_hkdcny.  Fewer than 7 usable years -> data_gap "needs >=7yr profit
history (run model gather or fetch expansion)", years_used reported
honestly.

Lineage: Graham (with Dodd), Security Analysis (1934) — earnings
power measured across the cycle, not at a point of it.
"""

import json
from pathlib import Path

import pandas as pd

from .. import config
from .statsutil import num_or_none

MIN_YEARS = 7
MAX_YEARS = 10
GAP = "needs ≥7yr profit history (run model gather or fetch expansion)"


def _fx_hkdcny(snap) -> float | None:
    """fx_hkdcny (CNY per HKD) from the snapshot manifest, or None."""
    if snap is None:
        return None
    try:
        man = json.loads(
            (Path(snap) / "manifest.json").read_text(encoding="utf-8"))
        fx = float(man.get("fx_hkdcny"))
    except (OSError, ValueError, TypeError):
        return None
    return fx if fx > 0 else None


def profit_history(models_dir, market: str,
                   code: str) -> tuple[list, str]:
    """(net_income series oldest->newest, currency) from the dossier's
    raw history.json; ([], '') when absent or unreadable."""
    path = (Path(models_dir) / market.lower() / code
            / "raw" / "history.json")
    try:
        h = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], ""
    years = h.get("years") or []
    vals = [(int(y.get("fy")), float(y["net_income"]))
            for y in years if isinstance(y, dict)
            and y.get("fy") is not None
            and y.get("net_income") is not None]
    vals.sort(key=lambda t: t[0])
    return [v for _fy, v in vals], str(h.get("currency") or "")


def run(ctx: dict, min_years: int = MIN_YEARS, max_years: int = MAX_YEARS,
        models_dir=None) -> dict:
    """Average-earnings PE for the context row (deep mode)."""
    out = {
        "weapon": "average-earnings-power",
        "anchor": "周期股修分母: ae_pe = 市值/7-10年平均盈利 vs pe_ttm"
                  "; cycle_adjustment = ae_pe/pe_ttm >1 说明 TTM 盈利"
                  "高于周期均值 (PE 被周期美化)",
        "min_years": int(min_years),
        "max_years": int(max_years),
    }
    row = ctx.get("row")
    if row is None:
        out["error"] = "no row in context (pass with_kline=(market, code))"
        return out
    market, code = str(row["market"]), str(row["code"])
    if market == "HK":
        code = code.zfill(5)
    mdir = Path(models_dir) if models_dir else Path(config.MODELS_DIR)
    series, ccy = profit_history(mdir, market, code)
    usable = series[-max_years:] if len(series) > max_years else series
    reading = {"market": market, "code": code,
               "years_used": int(len(usable)),
               "history_currency": ccy or None}
    if len(usable) < min_years:
        reading["data_gap"] = GAP
        out["row"] = reading
        return out
    avg_profit = sum(usable) / len(usable)
    if market == "HK" and ccy == "CNY":
        fx = _fx_hkdcny(ctx.get("snap"))
        if not fx:
            reading["data_gap"] = ("fx_hkdcny missing — HK history is "
                                   "CNY, market_cap is HKD")
            out["row"] = reading
            return out
        avg_profit = avg_profit / fx  # CNY -> HKD
    mcap = pd.to_numeric(pd.Series([row.get("market_cap")]),
                         errors="coerce").iloc[0]
    pe = pd.to_numeric(pd.Series([row.get("pe_ttm")]),
                       errors="coerce").iloc[0]
    if pd.isna(mcap) or mcap <= 0 or avg_profit <= 0:
        reading["data_gap"] = ("market_cap missing or avg_profit <= 0 "
                               "(loss-cycle average — Graham lens needs "
                               "positive earning power)")
        out["row"] = reading
        return out
    ae_pe = float(mcap) / avg_profit
    reading["avg_profit"] = num_or_none(avg_profit)
    reading["ae_pe"] = num_or_none(ae_pe)
    reading["pe_ttm"] = num_or_none(pe)
    reading["cycle_adjustment"] = (
        num_or_none(ae_pe / pe) if pd.notna(pe) and pe > 0 else None)
    out["row"] = reading
    return out
