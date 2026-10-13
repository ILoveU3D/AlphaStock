"""barrier-forge — 止损v2 mechanics: three barriers + chandelier stop.

From the context kline (daily bars, raw listing-currency units):

(a) Yang-Zhang (2000) volatility — the canonical estimator:
    sigma2 = sigma2_overnight + k*sigma2_open_to_close
             + (1-k)*sigma2_rogers_satchell,
    k = 0.34/(1.34 + (n+1)/(n-1)) over the trailing ``window`` bars;
    annualized %% (x sqrt(252) x 100).
(b) ATR(14), Wilder smoothing (seed = SMA of the first 14 true
    ranges, then atr_t = (atr_{t-1}*13 + tr_t)/14).
(c) Chandelier trailing stop (Kaufman): highest_close_since_anchor -
    k_atr x ATR.  Anchor = ``entry_date`` param (first bar with
    date >= entry_date) or the first bar of the series.  RATCHET:
    the stop only moves UP, never down; the exit signal fires on a
    CLOSE below the stop (close-confirmed, intraday dips ignored).
(d) Three barriers summary: price barrier (the chandelier level),
    time barrier (max_holding_days vs bars held since entry; 0 = off),
    value floor (optional floor_price param).
(e) Risk-budget shares = (nav x risk_pct) / (entry - stop); entry
    defaults to the last close.  None when entry <= stop (no valid
    risk budget — declared, not zero-sized silently).

Needs >= 60 bars (YZ window); honest error otherwise.
Lineage: house stop-loss v2 + Yang & Zhang (2000), 'Drift-independent
volatility estimation' + Kaufman chandelier exit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .statsutil import num_or_none

TRADING_DAYS = 252
YZ_WINDOW = 60
ATR_LEN = 14
K_ATR = 3.0
MIN_BARS = 60


def yang_zhang_vol(kl: pd.DataFrame, window: int = YZ_WINDOW) -> float | None:
    """Annualized Yang-Zhang volatility (%) over the trailing window."""
    o = pd.to_numeric(kl["open"], errors="coerce").to_numpy(float)
    h = pd.to_numeric(kl["high"], errors="coerce").to_numpy(float)
    lo = pd.to_numeric(kl["low"], errors="coerce").to_numpy(float)
    c = pd.to_numeric(kl["close"], errors="coerce").to_numpy(float)
    m = np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(c)
    o, h, lo, c = o[m], h[m], lo[m], c[m]
    if len(c) < window + 1:
        return None
    o, h, lo, c = o[-window:], h[-window:], lo[-window:], c[-window:]
    c_prev = pd.to_numeric(kl["close"], errors="coerce").to_numpy(float)
    c_prev = c_prev[m][-window - 1:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        ro = np.log(o / c_prev)          # overnight
        rc = np.log(c / o)               # open-to-close
        rs = (np.log(h / c) * np.log(h / o)
              + np.log(lo / c) * np.log(lo / o))   # Rogers-Satchell
    n = len(ro)
    k = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))
    var = (np.var(ro, ddof=1) + k * np.var(rc, ddof=1)
           + (1.0 - k) * np.mean(rs))
    if var < 0 or not np.isfinite(var):
        return None
    return float(np.sqrt(var * TRADING_DAYS) * 100.0)


def atr(kl: pd.DataFrame, length: int = ATR_LEN) -> np.ndarray:
    """Wilder ATR series (NaN until the seed window completes)."""
    h = pd.to_numeric(kl["high"], errors="coerce").to_numpy(float)
    lo = pd.to_numeric(kl["low"], errors="coerce").to_numpy(float)
    c = pd.to_numeric(kl["close"], errors="coerce").to_numpy(float)
    n = len(c)
    tr = np.full(n, np.nan)
    for i in range(n):
        if not (np.isfinite(h[i]) and np.isfinite(lo[i])):
            continue
        if i == 0 or not np.isfinite(c[i - 1]):
            tr[i] = h[i] - lo[i]
        else:
            tr[i] = max(h[i] - lo[i], abs(h[i] - c[i - 1]),
                        abs(lo[i] - c[i - 1]))
    out = np.full(n, np.nan)
    if n >= length:
        out[length - 1] = np.nanmean(tr[:length])
        for i in range(length, n):
            seed = out[i - 1]
            out[i] = ((seed * (length - 1) + tr[i]) / length
                      if np.isfinite(tr[i]) else seed)
    return out


def chandelier(kl: pd.DataFrame, k: float = K_ATR,
               anchor_idx: int = 0) -> tuple[np.ndarray, bool]:
    """(stop series, signal): ratcheted highest-close - k*ATR; signal
    fires on the last CLOSE below the stop."""
    c = pd.to_numeric(kl["close"], errors="coerce").to_numpy(float)
    a = atr(kl)
    n = len(c)
    stops = np.full(n, np.nan)
    stop = None
    hh = -np.inf
    for i in range(max(anchor_idx, 0), n):
        if np.isfinite(c[i]):
            hh = max(hh, c[i])
        if not np.isfinite(a[i]) or hh == -np.inf:
            continue
        raw = hh - k * a[i]
        stop = raw if stop is None else max(stop, raw)   # ratchet: up only
        stops[i] = stop
    signal = (stop is not None and np.isfinite(c[-1])
              and c[-1] < stops[-1])
    return stops, bool(signal)


def _anchor_index(kl: pd.DataFrame, entry_date: str | None) -> tuple[int, str | None]:
    if not entry_date:
        return 0, None
    if "date" not in kl.columns:
        return 0, "kline has no date column — entry_date ignored"
    dates = kl["date"].astype(str).to_numpy()
    hit = np.nonzero(dates >= str(entry_date))[0]
    if not len(hit):
        return 0, "entry_date beyond last bar — anchored at first bar"
    return int(hit[0]), None


def run(ctx: dict, window: int = YZ_WINDOW, k_atr: float = K_ATR,
        entry_date: str | None = None, max_holding_days: int = 0,
        floor_price: float | None = None, nav: float = 1_000_000.0,
        risk_pct: float = 0.01, entry: float | None = None) -> dict:
    """Three barriers + chandelier + risk-budget sizing for the ctx kline."""
    out = {
        "weapon": "barrier-forge",
        "anchor": "三屏障+吊灯(收盘确认、只上不下)+风险预算反推股数: "
                  "chandelier_stop = 锚点以来最高收盘 - k×ATR, 收盘跌破"
                  "才触发; shares_by_risk = (nav×risk_pct)/(entry-stop)",
    }
    kl = ctx.get("kline")
    if kl is None or not len(kl):
        out["error"] = "kline required (pass with_kline=(market, code))"
        return out
    if len(kl) < MIN_BARS:
        out["error"] = f"kline required (>= {MIN_BARS} bars; got {len(kl)})"
        return out

    anchor_idx, anchor_note = _anchor_index(kl, entry_date)
    yz = yang_zhang_vol(kl, window)
    a = atr(kl)
    stops, signal = chandelier(kl, k_atr, anchor_idx)
    close = pd.to_numeric(kl["close"], errors="coerce")
    last_close = num_or_none(close.iloc[-1])
    stop = num_or_none(stops[-1])
    out["yang_zhang_vol"] = yz
    out["atr"] = num_or_none(a[-1])
    out["chandelier_stop"] = stop
    out["chandelier_signal"] = signal
    out["stop_distance_pct"] = num_or_none(
        None if stop is None or last_close in (None, 0)
        else (last_close - stop) / last_close * 100.0)
    if anchor_note:
        out["anchor_note"] = anchor_note

    barriers = {"price": {"stop": stop, "hit": signal,
                          "confirm": "close-confirmed"}}
    if max_holding_days and max_holding_days > 0:
        if entry_date:
            held = int(len(kl) - 1 - anchor_idx)
            barriers["time"] = {"days_held": held,
                                "max_holding_days": int(max_holding_days),
                                "hit": bool(held >= max_holding_days)}
        else:
            barriers["time"] = {"data_gap": "entry_date required for "
                                            "the time barrier"}
    if floor_price is not None:
        barriers["value_floor"] = {
            "floor_price": float(floor_price),
            "hit": (None if last_close is None
                    else bool(last_close < floor_price))}
    out["barriers"] = barriers

    ent = entry if entry is not None else last_close
    if ent is None or stop is None or ent <= stop:
        out["shares_by_risk"] = None
        out["shares_note"] = ("entry <= stop — no valid risk budget"
                              if ent is not None and stop is not None
                              else "entry/stop unavailable")
    else:
        out["shares_by_risk"] = num_or_none(
            (nav * risk_pct) / (ent - stop))
    out["risk_params"] = {"nav": nav, "risk_pct": risk_pct,
                          "entry": num_or_none(ent)}
    return out
