"""Market overview digest from the latest snapshot master.

Per market: candidate count, median valuations, breadth, top sectors
among the top-50 and the top-N table — enough for an AI to answer
"what looks attractive in HK right now".
"""

from pathlib import Path

import pandas as pd

from . import config, report


def _med(df: pd.DataFrame, col: str):
    if col not in df.columns or df[col].isna().all():
        return None
    return round(float(df[col].median()), 2)


def market_overview(snapshot_dir=None, markets=None, top_n: int = 10,
                    data_dir=None) -> dict:
    """Digest dict for the requested markets of a snapshot."""
    snap = (Path(snapshot_dir) if snapshot_dir
            else report.resolve_snapshot(data_dir))
    master = report.load_master(snap)
    markets = markets or list(config.MARKETS)
    out = {"snapshot": snap.name, "markets": {}}
    for mk in markets:
        df = master[master["market"] == mk]
        if df.empty:
            continue
        top = report.screen(master, preset=config.DEFAULT_PRESET,
                            top_n=top_n, markets=[mk])
        top50 = report.screen(master, preset=config.DEFAULT_PRESET,
                              top_n=50, markets=[mk])
        entry = {
            "candidates": len(df),
            "median_pe": _med(df, "pe_ttm"),
            "median_pb": _med(df, "pb"),
            "median_rev_yoy": _med(df, "rev_yoy"),
            "top_sectors": {},
            "top": top,
        }
        if "pos_52w" in df.columns and df["pos_52w"].notna().any():
            entry["above_52w_mid"] = round(
                float((df["pos_52w"] > 50).mean() * 100.0), 1)
        if "industry" in top50.columns:
            entry["top_sectors"] = {
                str(k): int(v) for k, v in
                top50["industry"].fillna("(unknown)")
                .value_counts().head(5).items()}
        out["markets"][mk] = entry
    return out


def render_overview(ov_data: dict) -> str:
    lines = [f"== Value Genie market overview - "
             f"snapshot {ov_data['snapshot']} =="]
    for mk, d in ov_data["markets"].items():
        lines += ["",
                  f"[{mk}] candidates={d['candidates']}"
                  f"  median PE={d['median_pe']}"
                  f"  median PB={d['median_pb']}"
                  f"  median rev YoY={d['median_rev_yoy']}%"]
        if "above_52w_mid" in d:
            lines.append(f"    breadth: {d['above_52w_mid']}% of candidates "
                         f"above their 52w midpoint")
        if d["top_sectors"]:
            lines.append("    top sectors (of top-50): " + ", ".join(
                f"{k} ({v})" for k, v in d["top_sectors"].items()))
        t = d["top"]
        cols = [c for c in ("rank", "code", "name", "price", "pe_ttm",
                            "rev_yoy", "roe", "composite_score")
                if c in t.columns]
        lines.append(t[cols].to_string(
            index=False, float_format=lambda v: f"{v:.1f}"))
    return "\n".join(lines)
