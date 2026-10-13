"""ivol-lottery-gate — Ang, Hodrick, Xing & Zhang (2006) idiosyncratic
volatility + Bali, Cakici & Whitelaw (2011) MAX lottery-demand gauge,
as a VETO-LEANING cross-section: high ivol / lottery-shaped payoffs are
where retail overpays.

ivol = std of the OLS residuals of stock daily %-returns on the SAME
equal-weight market proxy as low-beta-bab (declared proxy — no index
klines in the snapshot; helpers imported from low_beta_bab, single
source), annualized: resid.std() x sqrt(252).  max_ret_21d = max daily
%-return over the last 21 bars of the stock's own kline (needs >= 21
daily returns, else NaN).  Veto flags (within-market percentiles):
ivol_pctl >= 80 -> ivol_veto; max_pctl >= 80 -> lottery_veto.

DECLARED SWEEP COST: the scan reads every swept stock's kline once
(shared per-market cache).  Rows without a kline, with <10 common OLS
observations, or with <21 daily returns -> the affected metric is NaN
and ``lottery_data_gap`` is set.
"""

import math

import pandas as pd

from .low_beta_bab import (beta_vs_market, build_market_returns,
                           daily_returns, load_kline, load_return_cache)
from .statsutil import num_or_none, xsec_pctl

IVOL_VETO_PCTL = 80.0
MAX_VETO_PCTL = 80.0
LOTTERY_WINDOW = 21
TRADING_DAYS_YEAR = 252


def ivol_annualized(fit: dict) -> float | None:
    """Annualized-% std of the OLS residuals (daily %-ret units)."""
    resid = fit.get("resid")
    if resid is None or len(resid) < 2:
        return None
    return float(resid.std()) * math.sqrt(TRADING_DAYS_YEAR)


def max_daily_return(rets: pd.Series | None,
                     bars: int = LOTTERY_WINDOW) -> float | None:
    """Max daily %-return over the last `bars` returns; None if fewer."""
    if rets is None or len(rets) < bars:
        return None
    return float(rets.tail(bars).max())


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """ivol + max_ret_21d + within-market percentiles + veto flags."""
    out = df.copy()
    cache = load_return_cache(df, snap)
    proxies = build_market_returns(cache)
    ivols, maxs, gaps = [], [], []
    for _, r in out.iterrows():
        mkt, code = str(r["market"]), str(r["code"])
        sret = cache.get(mkt, {}).get(code)
        if sret is None and snap is not None:
            sret = daily_returns(load_kline(snap, mkt, code))
        fit = beta_vs_market(sret, proxies.get(mkt))
        iv = ivol_annualized(fit)
        mx = max_daily_return(sret)
        ivols.append(iv)
        maxs.append(mx)
        gaps.append(iv is None or mx is None)
    out["ivol"] = ivols
    out["max_ret_21d"] = maxs
    mkt_col = out["market"].astype(str)
    out["ivol_pctl"] = xsec_pctl(out["ivol"], mkt_col)
    out["max_pctl"] = xsec_pctl(out["max_ret_21d"], mkt_col)
    out["ivol_veto"] = (out["ivol_pctl"] >= IVOL_VETO_PCTL).fillna(False)
    out["lottery_veto"] = (out["max_pctl"] >= MAX_VETO_PCTL).fillna(False)
    out["lottery_data_gap"] = gaps
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Veto counts, the wildest rows, and the target row's reading."""
    master = scan_frame(ctx["master"], ctx.get("snap"))
    valid = master[~master["lottery_data_gap"]]
    wild = valid.sort_values("ivol", ascending=False).head(top)
    out = {
        "weapon": "ivol-lottery-gate",
        "anchor": "彩票型收益与高特质波动是否决胜场; ivol = 残差波动"
                  "年化% (同一等权市场代理); ivol_pctl>=80 / max_pctl>="
                  "80 → 否决旗, 只否决不排名",
        "pool": int(len(ctx["master"])),
        "valid": int(len(valid)),
        "data_gaps": int(master["lottery_data_gap"].sum()),
        "ivol_vetoes": int(master["ivol_veto"].sum()),
        "lottery_vetoes": int(master["lottery_veto"].sum()),
        "highest_ivol": _records(wild),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "ivol": num_or_none(h["ivol"]),
                "ivol_pctl": num_or_none(h["ivol_pctl"]),
                "max_ret_21d": num_or_none(h["max_ret_21d"]),
                "max_pctl": num_or_none(h["max_pctl"]),
                "ivol_veto": bool(h["ivol_veto"]),
                "lottery_veto": bool(h["lottery_veto"]),
                "data_gap": bool(h["lottery_data_gap"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "ivol": num_or_none(r["ivol"]),
            "ivol_pctl": num_or_none(r["ivol_pctl"]),
            "max_ret_21d": num_or_none(r["max_ret_21d"]),
            "max_pctl": num_or_none(r["max_pctl"]),
            "ivol_veto": bool(r["ivol_veto"]),
            "lottery_veto": bool(r["lottery_veto"]),
        })
    return recs
