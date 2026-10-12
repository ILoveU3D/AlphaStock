"""cycle-trap-guard (老兵) — live A-share pass: TTM EPS vs analyst
consensus current-year EPS.

Migrated from strategy/consensus.py (forward_pe_divergence) in the
2026-10-13 zero-algorithm move; behavior byte-identical.

eps_ttm / eps_fwd >= 1.5 means the market expects earnings to fall by a
third or more: the classic cycle-peak "cheap PE" signature (GSL:
TTM 4.30 vs forward 8.41).  HK/US have no consensus-EPS source in this
toolkit: divergence stays null and the gap is declared, never
fabricated.  This weapon touches the NETWORK (intel ratings source) —
the only veteran that does; keep it out of offline pipelines.
"""

import pandas as pd

# eps_ttm / eps_fwd at/above which the stock is flagged a cycle trap /
# warning (market prices earnings falling by >= 1/3, resp. >= 1/4)
CYCLE_TRAP_RATIO = 1.5
CYCLE_WARN_RATIO = 1.25


def forward_pe_divergence(row: pd.Series) -> float | None:
    """eps_ttm / consensus current-year EPS for one A-share row.

    Price cancels: pe_fwd / pe_ttm == eps_ttm / eps_fwd, so snapshot
    price is as good as live.  Returns None when the consensus source
    is unavailable or reports no EPS (fail-open, gap declared).
    """
    if str(row.get("market")) != "A":
        return None
    pe = pd.to_numeric(row.get("pe_ttm"), errors="coerce")
    price = pd.to_numeric(row.get("price"), errors="coerce")
    if pd.isna(pe) or pe <= 0 or pd.isna(price) or price <= 0:
        return None
    eps_ttm = price / pe

    from ..intel.ratings import fetch_stock_ratings
    items = fetch_stock_ratings(str(row.get("code")),
                                str(row.get("name") or ""))
    if not items:
        return None
    eps_fwd = [i.payload.get("eps_this_year") for i in items
               if i.payload.get("eps_this_year") is not None]
    if not eps_fwd:
        return None
    eps_fwd.sort()
    mid = eps_fwd[len(eps_fwd) // 2]
    if mid <= 0:
        return None
    return float(eps_ttm / mid)


def verdict(ratio: float | None) -> str | None:
    """trap / warn / None label for a divergence ratio."""
    if ratio is None:
        return None
    if ratio >= CYCLE_TRAP_RATIO:
        return "cycle_trap"
    if ratio >= CYCLE_WARN_RATIO:
        return "cycle_warn"
    return None


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict) -> dict:
    """Divergence for the context row (network: A-share ratings source)."""
    row = ctx.get("row")
    out = {
        "weapon": "cycle-trap-guard",
        "anchor": f"eps_ttm/eps_fwd >= {CYCLE_TRAP_RATIO} = trap "
                  f"(market prices >=1/3 earnings fall), "
                  f">= {CYCLE_WARN_RATIO} = warn; HK/US fail-open null",
    }
    if row is None:
        out["error"] = "no row in context (pass with_kline=(market, code))"
        return out
    ratio = forward_pe_divergence(row)
    out["row"] = {"market": str(row.get("market")),
                  "code": str(row.get("code")),
                  "pe_divergence": ratio,
                  "verdict": verdict(ratio)}
    return out
