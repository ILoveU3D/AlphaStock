"""low-beta-bab — Frazzini & Pedersen (2014) Betting-Against-Beta:
low-beta stocks earn higher risk-adjusted returns, so LOW beta maps to
HIGH percentile here (ascending=False).

DECLARED PROXY: the snapshot carries no index klines, so the market
portfolio is proxied by the equal-weight mean daily return of ALL swept
stocks in the same market — each stock's daily-%-return series
inner-joined on dates (synchronous calendar), then averaged across
members per date.  Proxy membership requires >= PROXY_MIN_OBS daily
returns so short-history names cannot collapse the common calendar; a
poison-member guard (PROXY_MIN_COVER date-coverage floor, see
build_market_returns) keeps one sparse/odd-window series from
collapsing the strict inner join.  Per-stock beta = OLS slope of stock
daily %-returns on the proxy over the last <= MAX_OBS common trading
days (statsutil.ols, needs >=10 obs).

DECLARED SWEEP COST: the scan reads every swept stock's kline file once
(slow on a full-market sweep); klines are cached per market inside
scan_frame so the proxy build and the per-stock fits share the reads.
Rows without a kline or with <10 common observations -> NaN + data_gap.

The kline/proxy helpers (load_kline / close_series / daily_returns /
load_return_cache / build_market_returns / beta_vs_market) are the
single source for every same-market-proxy weapon (ivol-lottery-gate,
ah-premium-radar import them here).
"""

import math
from pathlib import Path

import pandas as pd

from .statsutil import num_or_none, ols, xsec_pctl

TRADING_DAYS_YEAR = 252
PROXY_MIN_OBS = 60          # min daily returns to join the market proxy
PROXY_MIN_COVER = 0.9       # poison-member guard: date-coverage floor
MAX_OBS = 250               # per-stock OLS window (common trading days)


# ---------------------------------------------------------------------------
# Kline helpers (shared with same-market-proxy weapons)
# ---------------------------------------------------------------------------
def load_kline(snap, market, code) -> pd.DataFrame | None:
    """Cached kline for one stock; None when absent/unreadable."""
    if snap is None:
        return None
    from ..fetch.kline import kline_cache_path, load_kline as _read
    p = kline_cache_path(Path(snap), str(market), str(code))
    return _read(p) if p.exists() else None


def close_series(kl: pd.DataFrame | None) -> pd.Series | None:
    """Date-indexed (ISO string) numeric close series, sorted, de-duped."""
    if kl is None or "close" not in kl.columns:
        return None
    c = pd.to_numeric(kl["close"], errors="coerce")
    idx = (kl["date"].astype(str) if "date" in kl.columns
           else kl.index.astype(str))
    s = pd.Series(c.to_numpy(), index=idx).dropna()
    if s.empty:
        return None
    return s[~s.index.duplicated(keep="last")].sort_index()


def daily_returns(kl: pd.DataFrame | None) -> pd.Series | None:
    """Daily %-returns (pct_change x 100) of the close series."""
    s = close_series(kl)
    if s is None or len(s) < 2:
        return None
    r = s.pct_change().dropna() * 100.0
    return r if len(r) else None


def load_return_cache(df: pd.DataFrame, snap) -> dict:
    """{market: {code: daily-%-return Series}} — each kline read once."""
    cache: dict[str, dict[str, pd.Series]] = {}
    if snap is None:
        return cache
    for mkt, sub in df.groupby(df["market"].astype(str)):
        d: dict[str, pd.Series] = {}
        for _, r in sub.iterrows():
            s = daily_returns(load_kline(snap, mkt, r["code"]))
            if s is not None:
                d[str(r["code"])] = s
        cache[str(mkt)] = d
    return cache


def build_market_returns(ret_cache: dict, min_obs: int = PROXY_MIN_OBS,
                         min_cover: float = PROXY_MIN_COVER) -> dict:
    """{market: equal-weight mean daily-%-return Series} — the DECLARED
    market-portfolio proxy.  Members: stocks with >= min_obs daily
    returns; member series inner-joined on dates so every proxy print is
    a synchronous cross-stock average.

    POISON-MEMBER GUARD (declared deviation from a naive inner join):
    one sparse or odd-window series (e.g. 320 bars stretched over 7
    years) would collapse the strict inner join to zero rows.  Dates
    covered by < min_cover of the members are dropped first, then
    members still gappy on the surviving calendar are dropped; the
    final panel is strictly synchronous."""
    proxies: dict[str, pd.Series] = {}
    for mkt, d in ret_cache.items():
        members = {c: s for c, s in d.items() if len(s) >= min_obs}
        if not members:
            continue
        panel = pd.DataFrame(members).sort_index()
        need = max(1, math.ceil(panel.shape[1] * min_cover))
        panel = panel.loc[panel.notna().sum(axis=1) >= need]
        panel = panel.dropna(axis=1, how="any").dropna()
        if panel.shape[1] == 0 or len(panel) < min_obs:
            continue
        proxies[mkt] = panel.mean(axis=1)
    return proxies


def beta_vs_market(stock_ret: pd.Series | None,
                   market_ret: pd.Series | None,
                   max_obs: int = MAX_OBS) -> dict:
    """OLS of stock daily %-ret on the market proxy, last <= max_obs
    common days -> statsutil.ols dict (beta/alpha/resid/r2/n)."""
    empty = {"beta": None, "alpha": None,
             "resid": pd.Series(dtype=float), "r2": None, "n": 0}
    if stock_ret is None or market_ret is None:
        return empty
    pair = pd.concat([stock_ret.rename("y"), market_ret.rename("x")],
                     axis=1, join="inner").dropna().tail(max_obs)
    if pair.empty:
        return empty
    return ols(pair["y"], pair["x"])


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """beta_bab + within-market percentile (LOW beta -> HIGH pctl) +
    data_gap flag.  Market proxy built once per market, cached."""
    out = df.copy()
    cache = load_return_cache(df, snap)
    proxies = build_market_returns(cache)
    betas, ns, gaps = [], [], []
    for _, r in out.iterrows():
        mkt, code = str(r["market"]), str(r["code"])
        fit = beta_vs_market(cache.get(mkt, {}).get(code),
                             proxies.get(mkt))
        betas.append(fit.get("beta"))
        ns.append(int(fit.get("n") or 0))
        gaps.append(fit.get("beta") is None)
    out["beta_bab"] = betas
    out["beta_bab_n"] = ns
    out["beta_bab_pctl"] = xsec_pctl(out["beta_bab"],
                                     out["market"].astype(str),
                                     ascending=False)
    out["bab_data_gap"] = gaps
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Lowest-beta rows (BAB long side) + the target row's reading."""
    master = scan_frame(ctx["master"], ctx.get("snap"))
    valid = master[~master["bab_data_gap"]]
    low = valid.sort_values("beta_bab").head(top)
    out = {
        "weapon": "low-beta-bab",
        "anchor": "低 beta 偏好 (BAB): beta vs 等权市场代理 (声明代理, "
                  "无指数 kline); 分位翻转——低 beta 得高分位; "
                  "无 kline/共同交易日<10 → data_gap",
        "pool": int(len(ctx["master"])),
        "valid": int(len(valid)),
        "data_gaps": int(master["bab_data_gap"].sum()),
        "lowest_beta": _records(low),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "beta_bab": num_or_none(h["beta_bab"]),
                "beta_bab_n": int(h["beta_bab_n"]),
                "beta_bab_pctl": num_or_none(h["beta_bab_pctl"]),
                "data_gap": bool(h["bab_data_gap"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "beta_bab": num_or_none(r["beta_bab"]),
            "beta_bab_n": int(r["beta_bab_n"]),
            "beta_bab_pctl": num_or_none(r["beta_bab_pctl"]),
        })
    return recs
