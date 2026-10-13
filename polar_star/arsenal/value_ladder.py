"""value-ladder — four price rungs: what are you actually paying for?

Rungs for the context row:
1. Liquidation floor (NCAV) — NOT computable from the snapshot: the
   current-assets / total-liabilities split is absent from
   master.csv, so the rung is honestly None with a declared gap
   (never improvised).
2. Graham number = sqrt(22.5 x EPS x BVPS), with EPS = price/pe_ttm
   and BVPS = price/pb — Graham's own defensive formula (The
   Intelligent Investor).  None for loss-makers / negative book.
3. EPV = normalized profit / WACC (Greenwald).  Profit source per
   market (declared): US = us_financials.csv profit - oneoff (oneoff
   NaN treated as 0); A = a_financials.csv latest report_date profit;
   HK = hk_f10.csv latest report profit.  Per share via shares =
   market_cap/price.  Loss-makers -> None.  Currencies: profit and
   price share the listing currency per source (USD/HKD/CNY) — no FX
   mixing.
4. PVGO% = (1 - EPV_per_share/price) x 100 — the share of the price
   paying for growth options.

Lineage: Graham (1949); Greenwald et al., Value Investing (EPV);
PVGO decomposition (Myers/Brealey).
"""
from __future__ import annotations

import math

import pandas as pd

from .statsutil import num_or_none

WACC = 0.10
NCAV_GAP = "current-assets fields absent from snapshot (NCAV not " \
           "computable — no current_assets/total_liabilities split)"


def graham_number(price: float, pe_ttm: float, pb: float) -> float | None:
    """sqrt(22.5 x EPS x BVPS) with EPS=price/pe, BVPS=price/pb."""
    if price is None or pe_ttm is None or pb is None:
        return None
    if price <= 0 or pe_ttm <= 0 or pb <= 0:
        return None
    eps = price / pe_ttm
    bvps = price / pb
    return math.sqrt(22.5 * eps * bvps)


def _latest_by_date(df: pd.DataFrame, date_col: str) -> pd.Series | None:
    if df is None or not len(df):
        return None
    if date_col in df.columns:
        df = df.sort_values(date_col)
    return df.iloc[-1]


def _match_code(df: pd.DataFrame, col: str, code: str) -> pd.DataFrame:
    """Zero-padding-insensitive code match (hk_f10/a_financials store
    codes unpadded, master.csv zero-pads)."""
    target = code.lstrip("0") or "0"
    return df[df[col].astype(str).str.lstrip("0") == target]


def normalized_profit(ctx: dict, row: pd.Series) -> tuple[float | None, str]:
    """Normalized annual profit in listing currency + source note."""
    snap = ctx.get("snap")
    market = str(row.get("market", "")).upper()
    code = str(row.get("code", ""))
    if snap is None:
        return None, "no snapshot dir in context"
    try:
        if market == "US":
            df = pd.read_csv(snap / "us_financials.csv")
            hit = df[df["ticker"].astype(str) == code]
            r = _latest_by_date(hit, "report_date")
            if r is None:
                return None, "ticker absent from us_financials.csv"
            profit = num_or_none(r.get("profit"))
            oneoff = num_or_none(r.get("oneoff")) or 0.0
            if profit is None:
                return None, "us_financials profit missing"
            return profit - oneoff, "us_financials profit-oneoff (USD)"
        if market == "HK":
            df = pd.read_csv(snap / "hk_f10.csv")
            hit = _match_code(df, "code", code)
            r = _latest_by_date(hit, "report_date")
            if r is None:
                return None, "code absent from hk_f10.csv"
            profit = num_or_none(r.get("profit"))
            if profit is None:
                return None, "hk_f10 profit missing"
            return profit, "hk_f10 latest profit (HKD)"
        # A shares
        df = pd.read_csv(snap / "a_financials.csv")
        hit = _match_code(df, "code", code)
        r = _latest_by_date(hit, "report_date")
        if r is None:
            return None, "code absent from a_financials.csv"
        profit = num_or_none(r.get("profit"))
        if profit is None:
            return None, "a_financials profit missing"
        return profit, "a_financials latest profit (CNY)"
    except (OSError, pd.errors.ParserError, ValueError) as e:
        return None, f"financials unreadable: {e}"


def run(ctx: dict, wacc: float = WACC) -> dict:
    """The four rungs for the context row (master row required)."""
    out = {
        "weapon": "value-ladder",
        "anchor": "你在为什么付钱——价格中百分之几是增长期权: "
                  "rung1 清算地板(缺口) < rung2 格雷厄姆数 < rung3 "
                  "EPV(零增长价值) ; pvgo_pct = 价格里为增长期权付的"
                  "百分比",
    }
    row = ctx.get("row")
    if row is None:
        out["error"] = "row required (pass with_kline=(market, code))"
        return out
    price = num_or_none(row.get("price"))
    pe = num_or_none(row.get("pe_ttm"))
    pb = num_or_none(row.get("pb"))
    mc = num_or_none(row.get("market_cap"))

    rungs = {"liquidation_ncav": None}
    out["ncav_gap"] = NCAV_GAP
    rungs["graham_number"] = num_or_none(graham_number(price, pe, pb))

    epv_ps = None
    profit_note = None
    if price is None or price <= 0 or mc is None or mc <= 0:
        profit_note = "price/market_cap missing"
    else:
        profit, src = normalized_profit(ctx, row)
        profit_note = src
        if profit is not None:
            if profit <= 0:
                profit_note = src + " — loss-maker, EPV undefined"
            else:
                shares = mc / price
                epv_ps = profit / wacc / shares
    rungs["epv_per_share"] = num_or_none(epv_ps)
    out["epv_profit_src"] = profit_note
    out["epv_wacc"] = wacc
    rungs["pvgo_pct"] = num_or_none(
        None if epv_ps is None or not price or price <= 0
        else (1.0 - epv_ps / price) * 100.0)
    out["rungs"] = rungs
    return out
