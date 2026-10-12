"""red-flag-battery (老兵) — the L2 snapshot-side veto battery.

Migrated from strategy/consensus.py (add_snapshot_flags half) in the
2026-10-13 zero-algorithm move; behavior byte-identical.

- ``profit_spike`` (profit_yoy >= +200, low-base / one-off rebound)
- ``expectation_overreach`` (Graham expectation audit: implied growth
  (pe-8.5)/2 >= 15% AND more than 15pp above realized growth — paying
  for unproven growth; one-directional, never fires on cheapness;
  FCF-free so it covers exactly the HK/US names where the reverse-DCF
  anchor is imputed — user mandate 2026-10-11)
- ``veto_hard`` = intel_red | borrowed_dividend | profit_spike |
  expectation_overreach — the only snapshot-side exclusion semantics.

Also carries the two L1 display columns of the Graham audit:
``graham_g`` (implied growth the price pays for) and
``expectation_gap`` (graham_g minus realized growth — revenue yoy
preferred as the steadier series, profit yoy fallback).  Both are
veto/display context only, never ranking keys.
"""

import pandas as pd

# profit_yoy at/above which growth is flagged as low-base / one-off
PROFIT_SPIKE_PCT = 200.0
# Graham expectation audit (user mandate 2026-10-11): the 1949 formula
# reversed — implied growth the price pays for = (pe - 8.5) / 2.  The
# veto flag is ONE-DIRECTIONAL: it only fires when the market pays for
# growth the company has not yet proven, never on cheapness.  FCF-free
# (needs only pe_ttm), so it covers exactly the HK/US names where the
# reverse-DCF anchor (dcf_implied_g) is imputed for lack of FCF data.
GRAHAM_BASE_PE = 8.5
GRAHAM_G_FLAG = 15.0        # implied g >= 15% (pe >= 38.5)
EXPECTATION_GAP_FLAG = 15.0  # implied g - realized growth > 15pp


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric column or an all-NaN series when the column is absent."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(float("nan"), index=df.index)


def add_snapshot_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Whole-pool flags computable from snapshot columns only.

    ``veto_hard`` is the only snapshot-side exclusion semantics left
    (2026-09-29 redesign): intel red flags, borrowed dividend, one-off
    profit spike, expectation overreach (Graham audit, 2026-10-11).
    cycle_trap belongs to the live pass (cycle-trap-guard).
    """
    out = df.copy()
    py = pd.to_numeric(out.get("profit_yoy"), errors="coerce")
    out["profit_spike"] = (py >= PROFIT_SPIKE_PCT).fillna(False)
    intel_red = pd.to_numeric(out.get("intel_red"), errors="coerce") == 1
    borrowed = pd.to_numeric(out.get("borrowed_dividend"),
                             errors="coerce") == 1
    graham_g = (_num(out, "pe_ttm") - GRAHAM_BASE_PE) / 2.0
    out["graham_g"] = graham_g
    realized = _num(out, "rev_yoy").fillna(_num(out, "profit_yoy"))
    out["expectation_gap"] = graham_g - realized
    out["expectation_overreach"] = (
        (graham_g >= GRAHAM_G_FLAG)
        & (out["expectation_gap"] > EXPECTATION_GAP_FLAG)
    ).fillna(False)
    out["veto_hard"] = (intel_red | borrowed | out["profit_spike"]
                        | out["expectation_overreach"])
    return out


# ---------------------------------------------------------------------------
# Weapon runner
# ---------------------------------------------------------------------------
def run(ctx: dict) -> dict:
    """Flag the pool; report veto counts + the target row's flags."""
    master = ctx["master"]
    flagged = add_snapshot_flags(master)
    counts = {}
    for col in ("profit_spike", "expectation_overreach", "veto_hard"):
        counts[col] = int(flagged[col].sum())
    counts["intel_red"] = int(
        (pd.to_numeric(flagged.get("intel_red"), errors="coerce")
         == 1).sum())
    counts["borrowed_dividend"] = int(
        (pd.to_numeric(flagged.get("borrowed_dividend"), errors="coerce")
         == 1).sum())
    out = {
        "weapon": "red-flag-battery",
        "anchor": "veto-only: intel_red | borrowed_dividend | "
                  "profit_spike(>=+200%) | expectation_overreach"
                  "(graham_g>=15% & gap>15pp); never ranks",
        "pool": int(len(master)),
        "counts": counts,
    }
    row = ctx.get("row")
    if row is not None:
        hit = flagged[(flagged["market"].astype(str) == str(row["market"]))
                      & (flagged["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "veto_hard": bool(h["veto_hard"]),
                "profit_spike": bool(h["profit_spike"]),
                "expectation_overreach": bool(h["expectation_overreach"]),
                "graham_g": (None if pd.isna(h["graham_g"])
                             else float(h["graham_g"])),
                "expectation_gap": (None if pd.isna(h["expectation_gap"])
                                    else float(h["expectation_gap"])),
            }
    return out
