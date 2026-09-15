"""Quant consensus layer: the L1/L2 machinery of the QMF pipeline.

The GSL lesson (2026-09-15): a stock can be quantitatively cheapest on
every screen and still be a 6:1 master veto.  This module makes the
quant half of the fusion code-enforced:

- ``masters_vote``: how many of the registered master strategies' hard
  gates each stock passes (vote_count 0..N) plus the mean composite
  under each master's own weights — the quant consensus pool.
- snapshot flags: ``profit_spike`` (profit_yoy >= +200, low-base /
  one-off rebound) for the whole pool.
- ``forward_pe_divergence``: live A-share pass — TTM EPS vs the
  analyst-consensus current-year EPS.  eps_ttm / eps_fwd >= 1.5 means
  the market expects earnings to fall by a third or more: the classic
  cycle-peak "cheap PE" signature (GSL: TTM 4.30 vs forward 8.41).

HK/US have no consensus-EPS source in this toolkit: divergence stays
null and the gap is declared, never fabricated.

The qualitative layers (L3 master judgment, L4 fused verdict) belong to
the calling AI per skills/18-fused-quant-master.md — no LLM here.
"""

import pandas as pd

from .composite import apply_composite
from .factors import add_derived_factors
from .registry import evaluate_gates, list_strategies

# profit_yoy at/above which growth is flagged as low-base / one-off
PROFIT_SPIKE_PCT = 200.0
# eps_ttm / eps_fwd at/above which the stock is flagged a cycle trap /
# warning (market prices earnings falling by >= 1/3, resp. >= 1/4)
CYCLE_TRAP_RATIO = 1.5
CYCLE_WARN_RATIO = 1.25


def _master_strategies():
    """Registered master strategies, fame order (registry sorts)."""
    return list_strategies(kind="master")


def masters_vote(master: pd.DataFrame, markets=None) -> pd.DataFrame:
    """Vote each stock against every master's hard gates.

    Adds per-master vote columns (``vote_<id>``), ``vote_count``,
    ``masters_passed`` and ``mean_composite`` (mean of the composites
    computed under each master's own pillar weights).  Gates whose
    column is missing from the snapshot are skipped by
    ``evaluate_gates`` with a stderr warning, matching ``screen``.
    """
    out = add_derived_factors(master.copy())
    if markets:
        out = out[out["market"].isin(markets)]

    masters = _master_strategies()
    comps = []
    for s in masters:
        mask = evaluate_gates(out, s.gates or [])
        out[f"vote_{s.id}"] = mask.astype(int)
        scored = apply_composite(out, s.weights)
        comps.append(pd.to_numeric(scored["composite_score"],
                                   errors="coerce"))
        out = scored
    if not masters:
        out["vote_count"] = 0
        out["masters_passed"] = ""
        out["mean_composite"] = float("nan")
        return out

    vote_cols = [f"vote_{s.id}" for s in masters]
    out["vote_count"] = out[vote_cols].sum(axis=1).astype(int)
    out["masters_passed"] = out[vote_cols].apply(
        lambda row: ",".join(masters[i].id for i, v in enumerate(row)
                             if v), axis=1)
    out["mean_composite"] = pd.concat(comps, axis=1).mean(axis=1)
    return out


def add_snapshot_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Whole-pool flags computable from snapshot columns only."""
    out = df.copy()
    py = pd.to_numeric(out.get("profit_yoy"), errors="coerce")
    out["profit_spike"] = (py >= PROFIT_SPIKE_PCT).fillna(False)
    return out


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


def rank_consensus(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """Sort the consensus pool: vote_count desc, mean_composite desc."""
    out = df.sort_values(["vote_count", "mean_composite"],
                         ascending=[False, False],
                         na_position="last").head(top_n)
    return out.reset_index(drop=True)
