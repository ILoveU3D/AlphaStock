"""owner-audit — Buffett's capital-allocation three questions.

(a) Owner earnings (Buffett 1986): OE = ocf - maintenance capex.
    HONEST DECLARATION: the D&A + Delta-WC split Buffett actually
    specifies is absent from every feed, so maintenance capex is
    DECLARED = full capex — conservative by construction (understates
    OE for asset-light compounders, said out loud in the output).
    oe_yield = OE / market_cap x 100; oe_vs_profit = OE / profit is the
    honest earnings-quality cross-check.
(b) $1-retained test (Buffett 1984): retained = profit - div_paid
    summed over the window; ratio = Delta-market-cap / retained — pass
    when each retained dollar minted more than a dollar of market cap.
    Delta-mcap needs a multi-year price series: kline first-vs-last
    close x shares, computed ONLY when the kline spans >= 3 years
    (current snapshot klines span ~1.3y, so the honest answer is
    usually None + gap note — never a fabricated window).  US modeled
    stocks carry multi-year net_income in models/<m>/<code>/raw/
    history.json (no dividend field there -> retained would be
    approximated by net_income, an overstatement, declared); A dividends
    join from a_dividends.csv by fy; HK div_paid from hk_cashflow.csv.
(c) convergence: OE/profit over time when model raw history carries
    >=3 fy with ocf+capex+net_income, else a single-point note.

Per-market sources: US us_financials (ocf, capex, profit, div_paid);
A a_cashflow_annual (ocf, capex) + a_financials.profit + a_dividends;
HK hk_f10.ocf + hk_cashflow (ocf/capex/div_paid).  A/HK cash-flow rows
are FY-annual while profit rows are latest interim — period mismatch
declared on oe_vs_profit.

Lineage: Buffett 1986 owner earnings + 1984 $1-retained yardstick.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .statsutil import num_or_none

ANCHOR = ("业主盈余+1美元留存审计——管理层每留1美元是否创出1美元市值;"
          "maintenance capex 声明=全额 capex(保守), 红灯可否决,"
          "绿灯不构成买入理由")

MIN_RETAINED_SPAN_YEARS = 3.0  # $1-retained needs a >=3y price window


# ---------------------------------------------------------------------------
# Pure cores (unit-testable, snapshot-free)
# ---------------------------------------------------------------------------
def owner_earnings(ocf, capex):
    """OE = ocf - capex (maintenance capex DECLARED = full capex)."""
    ocf, capex = num_or_none(ocf), num_or_none(capex)
    if ocf is None or capex is None:
        return None
    return ocf - capex


def dollar_retained_test(retained_by_fy: dict, mcap_start, mcap_end,
                         span_years,
                         min_span: float = MIN_RETAINED_SPAN_YEARS) -> dict:
    """$1-retained yardstick: Delta-mcap / retained over the window.

    ``retained_by_fy``: {fy: retained} (profit - div_paid per year).
    Returns ratio=None + gap note whenever the price window is shorter
    than ``min_span`` or inputs are missing — never a fabricated
    window.  pass = ratio > 1 (each retained $ minted > $1 of mcap).
    """
    retained_sum = sum(num_or_none(v) or 0.0
                       for v in (retained_by_fy or {}).values())
    mcap_start, mcap_end = num_or_none(mcap_start), num_or_none(mcap_end)
    span = num_or_none(span_years)
    out = {"years": (len(retained_by_fy) if retained_by_fy else 0),
           "span_years": span,
           "retained_sum": num_or_none(retained_sum),
           "mcap_start": mcap_start, "mcap_end": mcap_end,
           "ratio": None, "pass": None}
    if span is None or span < min_span:
        out["gap"] = (f"price window {span if span is not None else 'n/a'}y "
                      f"< {min_span}y — multi-year market-cap delta "
                      "unavailable; the test is not run on a short window")
        return out
    if mcap_start is None or mcap_end is None:
        out["gap"] = "market-cap endpoints missing"
        return out
    if not retained_by_fy or retained_sum <= 0:
        out["gap"] = ("retained <= 0 over the window — the yardstick is "
                      "meaningless when nothing (or negative) was retained")
        return out
    ratio = (mcap_end - mcap_start) / retained_sum
    out["ratio"] = num_or_none(ratio)
    out["pass"] = bool(ratio > 1.0)
    return out


# ---------------------------------------------------------------------------
# Snapshot loaders
# ---------------------------------------------------------------------------
def _load_owner_fin(snap: Path, market: str, code: str) -> dict:
    """ocf / capex / profit / div_paid for one stock, per-market feeds."""
    market = str(market).upper()
    fin: dict = {"market": market}
    if market == "US":
        us = pd.read_csv(snap / "us_financials.csv")
        hit = us[us["ticker"].astype(str) == str(code)]
        if not len(hit):
            fin["data_gap"] = "ticker absent from us_financials.csv"
            return fin
        h = hit.iloc[0]
        for k in ("ocf", "capex", "profit", "div_paid"):
            fin[k] = num_or_none(h.get(k))
    elif market == "A":
        ac = pd.read_csv(snap / "a_cashflow_annual.csv",
                         dtype={"code": str})
        hit = ac[ac["code"] == str(code)]
        if len(hit):
            h = hit.iloc[0]
            fin["ocf"] = num_or_none(h.get("ocf"))
            fin["capex"] = num_or_none(h.get("capex"))
            fin["ocf_report_date"] = str(h.get("report_date"))
        af = pd.read_csv(snap / "a_financials.csv", dtype={"code": str})
        hit = af[af["code"] == str(code)]
        if len(hit):
            fin["profit"] = num_or_none(hit.iloc[0].get("profit"))
            fin["profit_report_date"] = str(hit.iloc[0].get("report_date"))
        ad = pd.read_csv(snap / "a_dividends.csv", dtype={"code": str})
        hit = ad[ad["code"] == str(code)]
        if len(hit):
            latest = hit.sort_values("fy").iloc[-1]
            fin["div_paid"] = num_or_none(latest.get("div_paid"))
            fin["div_fy"] = int(latest["fy"])
        fin["period_mismatch"] = True  # FY-annual ocf vs interim profit
    elif market == "HK":
        zc = str(code).zfill(5)
        hk = pd.read_csv(snap / "hk_f10.csv", dtype={"code": str})
        hit = hk[hk["code"] == zc]
        if len(hit):
            h = hit.iloc[0]
            fin["profit"] = num_or_none(h.get("profit"))
            fin["ocf"] = num_or_none(h.get("ocf"))
        hc = pd.read_csv(snap / "hk_cashflow.csv", dtype={"code": str})
        hit = hc[hc["code"] == zc]
        if len(hit):
            h = hit.iloc[0]
            if fin.get("ocf") is None:
                fin["ocf"] = num_or_none(h.get("ocf"))
            fin["capex"] = num_or_none(h.get("capex"))
            fin["div_paid"] = num_or_none(h.get("div_paid"))
            fin["period_mismatch"] = True
    return fin


def _models_dir(snap: Path) -> Path:
    """<repo>/models — snap is <repo>/data/snapshots/YYYYMMDD."""
    return snap.parents[2] / "models"


def _history_years(snap: Path, market: str, code: str) -> list:
    """Model raw history years (when the stock has been modeled)."""
    p = (_models_dir(snap) / str(market).lower() / str(code)
         / "raw" / "history.json")
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("years", [])
    except (json.JSONDecodeError, OSError):
        return []


def _convergence(snap: Path, market: str, code: str,
                 oe_point, profit_point) -> dict:
    """OE/profit over time from model raw history (US years carry
    ocf+capex+net_income); else a single-point note."""
    years = _history_years(snap, market, code)
    ratios = []
    for y in years:
        ocf, capex, ni = (num_or_none(y.get(k))
                          for k in ("ocf", "capex", "net_income"))
        if ocf is not None and capex is not None and ni not in (None, 0):
            ratios.append({"fy": y.get("fy"),
                           "oe_vs_profit": num_or_none((ocf - capex) / ni)})
    if len(ratios) >= 3:
        vals = [r["oe_vs_profit"] for r in ratios]
        note = (f"OE/profit over {len(vals)} fy: mean "
                f"{sum(vals) / len(vals):.2f}, latest "
                f"{vals[-1]:.2f} — accrual gap "
                f"{'narrowing' if vals[-1] >= vals[0] else 'widening'} "
                "across the history")
        return {"status": "ok", "series": ratios, "note": note}
    point = None
    if oe_point is not None and profit_point not in (None, 0):
        point = num_or_none(oe_point / profit_point)
    return {"status": "single_point", "oe_vs_profit_now": point,
            "note": "no multi-year OE history (model raw absent or "
                    "<3 usable fy) — single point only, no trend verdict"}


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, **params) -> dict:
    """Owner-earnings + $1-retained + convergence for the target row."""
    out = {"weapon": "owner-audit", "anchor": ANCHOR}
    row = ctx.get("row")
    if row is None:
        out["status"] = "data_gap"
        out["reason"] = ("no target row — build the context with "
                         "with_kline=(market, code)")
        return out
    snap = ctx["snap"]
    market, code = str(row["market"]), str(row["code"])
    out.update(market=market, code=code)

    fin = _load_owner_fin(snap, market, code)
    ocf, capex = fin.get("ocf"), fin.get("capex")
    profit, div_paid = fin.get("profit"), fin.get("div_paid")
    mcap = num_or_none(row.get("market_cap"))

    # (a) owner earnings
    oe = owner_earnings(ocf, capex)
    oe_yield = (oe / mcap * 100.0
                if oe is not None and mcap not in (None, 0) else None)
    oe_vs_profit = (oe / profit
                    if oe is not None and profit not in (None, 0) else None)
    oe_note = None
    if oe_vs_profit is not None and (oe_vs_profit < 0 or oe_vs_profit > 3):
        oe_note = ("extreme OE/profit — financial-sector cash-flow "
                   "structure (investment flows inside ocf/capex) can "
                   "distort the yardstick; read the raw inputs, not "
                   "just the ratio")

    # (b) $1-retained — retained over the window vs Delta-mcap from the
    # kline (first-vs-last close x shares).  Snapshot klines span ~1.3y,
    # so the honest result is usually None + gap note.
    kline = ctx.get("kline")
    span = None
    mcap_start = mcap_end = None
    if kline is not None and len(kline) >= 2:
        dates = pd.to_datetime(kline["date"])
        span = (dates.max() - dates.min()).days / 365.25
        closes = pd.to_numeric(kline["close"], errors="coerce").dropna()
        price = num_or_none(row.get("price"))
        if len(closes) >= 2 and mcap is not None and price not in (None, 0):
            shares = mcap / price
            mcap_start = float(closes.iloc[0]) * shares
            mcap_end = float(closes.iloc[-1]) * shares
    retained_by_fy = {}
    if profit is not None and profit > 0:
        # single-year retained from the snapshot feeds (model-history
        # multi-year retained is moot while the price window < 3y)
        retained_by_fy = {"latest": profit - (div_paid or 0.0)}
    retained = dollar_retained_test(retained_by_fy, mcap_start,
                                    mcap_end, span)
    retained["dividend_note"] = (
        "retained = profit - div_paid; US div_paid single-year only, "
        "A dividends joined by latest fy, HK from hk_cashflow — "
        "model-history years lack dividend fields, so multi-year "
        "retained would overstate (declared)")

    # (c) convergence
    conv = _convergence(snap, market, code, oe, profit)

    out["owner_earnings"] = {
        "oe": num_or_none(oe),
        "oe_yield": num_or_none(oe_yield),
        "oe_vs_profit": num_or_none(oe_vs_profit),
        "maintenance_capex_note": "maintenance capex DECLARED = full "
                                  "capex (D&A + Delta-WC split absent) "
                                  "— conservative",
        "period_mismatch": bool(fin.get("period_mismatch", False)),
        "distortion_note": oe_note,
        "inputs": {"ocf": num_or_none(ocf), "capex": num_or_none(capex),
                   "profit": num_or_none(profit),
                   "div_paid": num_or_none(div_paid),
                   "market_cap": mcap},
    }
    out["retained_test"] = retained
    out["convergence"] = conv
    if fin.get("data_gap"):
        out["feed_note"] = fin["data_gap"]
    return out
