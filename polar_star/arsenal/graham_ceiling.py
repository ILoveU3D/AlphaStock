"""graham-ceiling — Benjamin Graham's defensive-investor ceiling:
PE x PB <= 22.5 as a computable derived column + scan lens.

Carries ``add_derived_factors`` (the pe_pb product), migrated from
strategy/factors.py in the 2026-10-13 zero-algorithm move; behavior
byte-identical.  Lineage: Graham, The Intelligent Investor (1949) —
the ceiling admits only prices whose earnings-yield and book cover
compound to the defensive bound.
"""

import pandas as pd

GRAHAM_PE_PB = 22.5


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
# Weapon runner
# ---------------------------------------------------------------------------
def scan_frame(df: pd.DataFrame, snap=None) -> pd.DataFrame:
    """pe_pb + within-market percentile + pass flag, for scan/screen.

    ``snap`` is part of the weapon scan contract (kline-backed lenses
    need the snapshot dir); this lens is master-pure and ignores it.
    """
    out = add_derived_factors(df.copy())
    pe_pb = pd.to_numeric(out.get("pe_pb"), errors="coerce")
    out["graham_pass"] = pe_pb <= GRAHAM_PE_PB
    out["pe_pb_pctl"] = pe_pb.groupby(out["market"]).rank(pct=True) * 100.0
    return out


def run(ctx: dict, top: int = 15) -> dict:
    """Cheapest-by-ceiling rows (pe_pb asc) + the target row's reading."""
    master = scan_frame(ctx["master"])
    passed = master[master["graham_pass"].fillna(False)]
    ranked = passed.sort_values("pe_pb").head(top)
    cols = ["market", "code", "name", "pe_ttm", "pb", "pe_pb",
            "pe_pb_pctl"]
    cols = [c for c in cols if c in ranked.columns]
    out = {
        "weapon": "graham-ceiling",
        "anchor": f"PE×PB ≤ {GRAHAM_PE_PB} defensive ceiling; "
                  "loss-makers/negative book are outside the universe "
                  "by construction (NaN fails)",
        "pool": int(len(ctx["master"])),
        "passing": int(len(passed)),
        "top": ranked[cols].to_dict("records"),
    }
    row = ctx.get("row")
    if row is not None:
        hit = master[(master["market"].astype(str) == str(row["market"]))
                     & (master["code"].astype(str) == str(row["code"]))]
        if len(hit):
            h = hit.iloc[0]
            out["row"] = {
                "pe_pb": (None if pd.isna(h["pe_pb"])
                          else float(h["pe_pb"])),
                "graham_pass": (bool(h["graham_pass"])
                                if pd.notna(h["pe_pb"]) else None),
                "pe_pb_pctl": (None if pd.isna(h["pe_pb_pctl"])
                               else float(h["pe_pb_pctl"])),
            }
    return out
