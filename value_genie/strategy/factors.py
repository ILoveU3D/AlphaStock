"""Factor computation: kline-derived metrics and per-market pillar scores.

Pillars (each 0-100 percentile within the same market's candidate pool):
- value:     cheap PE / PB / PS and high dividend yield
- growth:   revenue and profit YoY growth
- quality:  ROE, gross/net margin, low leverage
- safety:   far from 52-week high, low volatility, deep drawdown
- momentum: 3-month and 12-month price return (trend following)
- cashflow: operating cash flow yield and cash conversion (Buffett focus)
"""

import math

import pandas as pd

# (column, sign) pairs per pillar; sign -1 = lower is better.
PILLAR_FACTORS = {
    "value": [("pe_ttm", -1), ("pb", -1), ("ps", -1),
              ("dividend_yield", 1)],
    "growth": [("rev_yoy", 1), ("profit_yoy", 1), ("rev_q_yoy", 1)],
    "quality": [("roe", 1), ("gross_margin", 1), ("net_margin", 1),
                ("debt_ratio", -1)],
    "safety": [("pos_52w", -1), ("volatility", -1), ("drawdown_52w", 1)],
    "momentum": [("ret_60d", 1), ("ret_250d", 1)],
    "cashflow": [("ocf_yield", 1), ("cash_conversion", 1)],
}

# Valuation ratios are only meaningful when positive (negative PE/PB/PS
# means losses or negative book; those rows get NaN for the sub-factor).
POSITIVE_ONLY = {"pe_ttm", "pb", "ps"}

PILLARS = ("value", "growth", "quality", "safety", "momentum", "cashflow")

TRADING_DAYS_YEAR = 252
WEEKS_52 = 252
MIN_BARS = 60


# ---------------------------------------------------------------------------
# Kline-derived metrics
# ---------------------------------------------------------------------------
def kline_metrics(kl: pd.DataFrame | None) -> dict:
    """Position/return/volatility metrics from a daily close series.

    Returns a possibly-empty dict; unavailable metrics are omitted.
    """
    if kl is None or "close" not in kl.columns:
        return {}
    close = pd.to_numeric(kl["close"], errors="coerce").dropna()
    n = len(close)
    if n < MIN_BARS:
        return {}
    last = float(close.iloc[-1])
    out = {}

    window = close.iloc[-WEEKS_52:] if n >= WEEKS_52 else close
    hi, lo = float(window.max()), float(window.min())
    if hi > lo:
        out["pos_52w"] = (last - lo) / (hi - lo) * 100.0
    else:
        out["pos_52w"] = 50.0  # flat series: middle of the range
    if hi > 0:
        out["drawdown_52w"] = (last - hi) / hi * 100.0

    ret_250 = _interval_return(close, 250)
    ret_60 = _interval_return(close, 60)
    if ret_250 is not None:
        out["ret_250d"] = ret_250
    if ret_60 is not None:
        out["ret_60d"] = ret_60

    if n >= MIN_BARS + 1:
        daily = close.pct_change().dropna()
        if len(daily) >= 20:
            out["volatility"] = float(daily.std()) * math.sqrt(
                TRADING_DAYS_YEAR) * 100.0
    return out


def _interval_return(close: pd.Series, bars: int) -> float | None:
    """Percent change over the last `bars` intervals (uses the available
    window when history is shorter)."""
    n = len(close)
    if n < 2:
        return None
    base = float(close.iloc[max(0, n - 1 - bars)])
    if base <= 0:
        return None
    return (float(close.iloc[-1]) / base - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Derived factors (gate inputs computed from existing columns)
# ---------------------------------------------------------------------------
def add_derived_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Add gate-ready columns derived from existing snapshot columns.

    Currently derives:
    - ``pe_pb``: PE(ttm) x PB — Benjamin Graham's defensive-investor
      rule (PE x PB <= 22.5) needs the product, not the two ratios
      separately. Only computed when both ratios are positive; loss
      makers / negative book get NaN, which fails `<=` gates (correct:
      they are outside Graham's universe by construction).
    """
    out = df
    if ("pe_ttm" in out.columns and "pb" in out.columns
            and "pe_pb" not in out.columns):
        out = out.copy()
        pe = pd.to_numeric(out["pe_ttm"], errors="coerce")
        pb = pd.to_numeric(out["pb"], errors="coerce")
        out["pe_pb"] = pe.where(pe > 0) * pb.where(pb > 0)
    return out


# ---------------------------------------------------------------------------
# Pillar scores
# ---------------------------------------------------------------------------
def add_pillar_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add {pillar}_score columns (0-100 percentile, per market, mean of
    available sub-factor ranks)."""
    out = df.copy()
    for pillar, factors in PILLAR_FACTORS.items():
        subs = []
        for col, sign in factors:
            if col not in out.columns:
                continue
            s = pd.to_numeric(out[col], errors="coerce")
            if col in POSITIVE_ONLY:
                s = s.where(s > 0)
            if sign < 0:
                s = -s
            # rank within each market -> 0-100 percentile
            ranked = s.groupby(out["market"]).rank(pct=True) * 100.0
            subs.append(ranked.rename(col))
        if subs:
            out[f"{pillar}_score"] = pd.concat(subs, axis=1).mean(axis=1)
        else:
            out[f"{pillar}_score"] = float("nan")
    return out


def pillar_columns() -> list:
    return [f"{p}_score" for p in PILLARS]
