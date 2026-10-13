"""amihud-gate — Amihud (2002) illiquidity ratio as a veto-leaning lens:
the price impact per unit of turnover; "进得去出不来" gets one careful
veto.

amihud = mean(|daily_ret_%| / amount_million) over the last 21 valid
bars of the stock's kline.  DECLARED RAW-UNIT CAVEAT: the kline
``amount`` column is in raw listing currency (A: yuan, HK: HKD, US:
USD), converted to millions for scale only — the ratio is comparable
WITHIN a market, never across (percentiles are within-market; a CNY
print and a USD print carry different units).  Bars with missing or
<= 0 amount are excluded; fewer than 21 valid bars -> NaN + data_gap.

SNAPSHOT GAP (declared 2026-10-13): the current snapshot's kline
``amount`` column is unpopulated (all-NaN) across all three markets —
the lens reports data_gap broadly until an amount-carrying kline source
fills it.  illiquid veto at within-market amihud_pctl >= 90.
"""

import pandas as pd

from .low_beta_bab import load_kline
from .statsutil import num_or_none, xsec_pctl

AMIHUD_WINDOW = 21
ILLIQUID_VETO_PCTL = 90.0


def amihud_value(kl: pd.DataFrame | None,
                 bars: int = AMIHUD_WINDOW) -> float | None:
    """mean(|ret_%| / amount_million) over the last `bars` valid bars.

    Valid = daily return computable AND amount > 0.  None when fewer
    than `bars` valid bars exist (or columns are missing).
    """
    if kl is None or "close" not in kl.columns or "amount" not in kl.columns:
        return None
    close = pd.to_numeric(kl["close"], errors="coerce")
    amount = pd.to_numeric(kl["amount"], errors="coerce")
    ret = close.pct_change() * 100.0
    d = pd.DataFrame({"r": ret, "a": amount}).dropna()
    d = d[d["a"] > 0].tail(bars)
    if len(d) < bars:
        return None
    return float((d["r"].abs() / (d["a"] / 1e6)).mean())


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """amihud + within-market percentile + illiquid veto flag."""
    out = df.copy()
    vals, gaps = [], []
    for _, r in out.iterrows():
        v = amihud_value(load_kline(snap, r["market"], r["code"]))
        vals.append(v)
        gaps.append(v is None)
    out["amihud"] = vals
    out["amihud_pctl"] = xsec_pctl(out["amihud"], out["market"].astype(str))
    out["illiquid_veto"] = (
        out["amihud_pctl"] >= ILLIQUID_VETO_PCTL).fillna(False)
    out["amihud_data_gap"] = gaps
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Most-illiquid rows + veto count + the target row's reading."""
    # status dormant (2026-10-13 acceptance review): the kline `amount`
    # column is all-NaN across ALL three markets, so the weapon can
    # never fire on real data — by the house rule (armed = data-ready)
    # it waits in the armory.  The formula + scan_frame below stay
    # synthetic-verified; wake when an amount-carrying kline source
    # lands and flip the registry back to armed.
    return {
        "weapon": "amihud-gate",
        "status": "dormant",
        "reason": "kline amount column all-NaN across all three markets "
                  "(snapshot 20261012) — Amihud illiquidity uncomputable "
                  "on every real row",
        "wake_condition": "amount-carrying kline source",
    }


def _run_armed(ctx: dict, top: int = 15) -> dict:
    master = scan_frame(ctx["master"], ctx.get("snap"))
    valid = master[~master["amihud_data_gap"]]
    ill = valid.sort_values("amihud", ascending=False).head(top)
    out = {
        "weapon": "amihud-gate",
        "anchor": "进得去出不来的一票谨慎; amihud = mean(|日收益%| / "
                  "成交额百万) 近 21 根; amount 原始币种单位 (A 元 / HK "
                  "港元 / US 美元), 跨市场不比; pctl>=90 → illiquid_veto",
        "pool": int(len(ctx["master"])),
        "valid": int(len(valid)),
        "data_gaps": int(master["amihud_data_gap"].sum()),
        "illiquid_vetoes": int(master["illiquid_veto"].sum()),
        "most_illiquid": _records(ill),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "amihud": num_or_none(h["amihud"]),
                "amihud_pctl": num_or_none(h["amihud_pctl"]),
                "illiquid_veto": bool(h["illiquid_veto"]),
                "data_gap": bool(h["amihud_data_gap"]),
            }
    return out


def _records(df: pd.DataFrame) -> list:
    recs = []
    for _, r in df.iterrows():
        recs.append({
            "market": str(r["market"]),
            "code": str(r["code"]),
            "name": (None if pd.isna(r.get("name")) else str(r["name"])),
            "amihud": num_or_none(r["amihud"]),
            "amihud_pctl": num_or_none(r["amihud_pctl"]),
            "illiquid_veto": bool(r["illiquid_veto"]),
        })
    return recs
