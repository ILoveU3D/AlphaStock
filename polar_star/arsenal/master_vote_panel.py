"""master-vote-panel (老兵) — vote each stock against every master's
hard gates.

Migrated from strategy/consensus.py (masters_vote half) in the
2026-10-13 zero-algorithm move; behavior byte-identical.

The GSL lesson (2026-09-15): a stock can be quantitatively cheapest on
every screen and still be a 6:1 master veto.  Per the 2026-09-29
three-core redesign votes and composites are DISPLAY-ONLY: they can
exclude (zero votes = out) but NEVER rank — ranking belongs to
core_score (arsenal/core_triad.py).
"""

import pandas as pd

from .graham_ceiling import add_derived_factors
from .statsutil import evaluate_gates
from .weighted_ranking import apply_composite
from ..strategy.registry import list_strategies


def _master_strategies():
    """Registered master strategies, fame order (registry sorts)."""
    return list_strategies(kind="master")


def masters_vote(master: pd.DataFrame, markets=None) -> pd.DataFrame:
    """Vote each stock against every master's hard gates.

    Adds per-master vote columns (``vote_<id>``), ``vote_count``,
    ``masters_passed`` and ``mean_composite`` (mean of the composites
    computed under each master's own pillar weights — context only,
    never ranks).  Gates whose column is missing from the snapshot are
    skipped by ``evaluate_gates`` with a stderr warning, matching
    ``screen``.
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


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict, markets=None) -> dict:
    """Master gate panel over the pool: vote distribution + panel columns."""
    master = ctx["master"]
    voted = masters_vote(master, markets=markets)
    masters = [s.id for s in _master_strategies()]
    dist = (voted["vote_count"].value_counts().sort_index()
            .to_dict() if len(voted) else {})
    out = {
        "weapon": "master-vote-panel",
        "anchor": "votes exclude (0 = out), NEVER rank; "
                  "mean_composite is display context only",
        "masters": masters,
        "pool": int(len(voted)),
        "vote_distribution": {int(k): int(v) for k, v in dist.items()},
    }
    row = ctx.get("row")
    if row is not None:
        hit = voted[(voted["market"].astype(str) == str(row["market"]))
                    & (voted["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "vote_count": int(h["vote_count"]),
                "masters_passed": h["masters_passed"],
                "mean_composite": (None if pd.isna(h["mean_composite"])
                                   else float(h["mean_composite"])),
                **{f"vote_{m}": int(h.get(f"vote_{m}", 0))
                   for m in masters},
            }
    return out
