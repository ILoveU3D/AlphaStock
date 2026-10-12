"""tactical-compass (老兵) — kline-derived price-behavior metrics and the
D4 tactical floor pair (weekly_uptrend x pullback_from_high).

Migrated from strategy/factors.py (kline half) in the 2026-10-13
zero-algorithm move; behavior byte-identical.  Consumed by the snapshot
pipeline (per-stock kline factor columns), ``ask`` target metrics, and
the D4 short-floor CLI.
"""

import math

import pandas as pd

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
    ret_20 = _interval_return(close, 20)
    ret_5 = _interval_return(close, 5)
    if ret_250 is not None:
        out["ret_250d"] = ret_250
    if ret_60 is not None:
        out["ret_60d"] = ret_60
    if ret_20 is not None:
        out["ret_20d"] = ret_20
    if ret_5 is not None:
        out["ret_5d"] = ret_5

    if n >= MIN_BARS + 1:
        daily = close.pct_change().dropna()
        if len(daily) >= 20:
            out["volatility"] = float(daily.std()) * math.sqrt(
                TRADING_DAYS_YEAR) * 100.0
            out["vol_20d"] = float(daily.tail(20).std()) * math.sqrt(
                TRADING_DAYS_YEAR) * 100.0

    # Tactical pair (2026-09-29, tower brick weekly-trend-daily-pullback):
    # weekly_uptrend — macro trend intact (close > MA20W, MA10W > MA20W,
    # 26-week return > 0); pullback_from_high — micro drawdown vs the
    # 60-bar high (percent, <= 0). The short-horizon floor needs both.
    out.update(_weekly_trend(kl, close))
    hi60 = _window_high(kl, close, 60)
    if hi60 and hi60 > 0:
        out["pullback_from_high"] = (last / hi60 - 1.0) * 100.0
    return out


def _weekly_trend(kl: pd.DataFrame, close: pd.Series) -> dict:
    """1.0 when the weekly-resampled trend is unambiguously up."""
    if len(close) < 140:      # need ~28+ weeks for MA20W + 26w return
        return {}
    try:
        if "date" in kl.columns:
            idx = pd.to_datetime(kl["date"], errors="coerce")
            raw = pd.to_numeric(kl["close"], errors="coerce")
            w = pd.Series(raw.to_numpy(), index=idx).dropna()
            w = w[~w.index.isna()].resample("W-FRI").last().dropna()
        else:
            w = close.resample("W-FRI").last().dropna()
    except (TypeError, ValueError):
        return {}
    if len(w) < 27:
        return {}
    ma10 = float(w.tail(10).mean())
    ma20 = float(w.tail(20).mean())
    # Structure, not the latest print: in a steep ramp a tradeable -8%
    # dip routinely closes under MA20W — that dip IS the entry. Require
    # the medium trend to dominate the long trend plus a positive
    # half-year move; a real reversal flips MA10 below MA20 fast enough.
    ret_26w = float(w.iloc[-1]) / float(w.iloc[-27]) - 1.0
    up = (ma10 > ma20) and (ret_26w > 0)
    return {"weekly_uptrend": 1.0 if up else 0.0}


def _window_high(kl: pd.DataFrame, close: pd.Series, bars: int) -> float:
    """High over the last `bars` bars (high column preferred)."""
    if "high" in kl.columns:
        h = pd.to_numeric(kl["high"], errors="coerce").dropna().tail(bars)
        if len(h):
            return float(h.max())
    return float(close.tail(bars).max())


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
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict) -> dict:
    """Kline metrics for the context stock (+ tactical floor readings)."""
    kl = ctx.get("kline")
    out = {
        "weapon": "tactical-compass",
        "anchor": "weekly_uptrend (MA10W>MA20W & 26w ret>0) x "
                  "pullback_from_high (60-bar) — D4 floor pair; "
                  "pos_52w/returns/vol are behavior facts, never ranks",
    }
    if kl is None:
        out["error"] = "no kline in context "
        "(pass with_kline=(market, code))"
        return out
    m = kline_metrics(kl)
    out["metrics"] = m
    if "weekly_uptrend" in m and "pullback_from_high" in m:
        pb = m["pullback_from_high"]
        out["tactical_floor"] = {
            "structure_up": bool(m["weekly_uptrend"]),
            "pullback_pct": pb,
            "sweet_spot": bool(m["weekly_uptrend"])
            and -15.0 <= pb <= -5.0,
        }
    return out
