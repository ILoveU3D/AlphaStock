"""Screening reports: load snapshots, apply strategies, export results.

The fetch pipeline writes date-stamped snapshots with a scored master.csv;
this module turns a snapshot into a ranked pick list under a chosen
strategy preset (or custom pillar weights) and exports CSV / Markdown.
"""

from pathlib import Path

import pandas as pd

from . import config
from .strategy.composite import apply_composite, rank_top
from .strategy.horizons import recompute_momentum_score
from .strategy.presets import normalize_weights

REPORT_COLUMNS = [
    "rank", "market", "code", "name", "industry", "price", "market_cap",
    "pe_ttm", "pb", "ps", "dividend_yield", "rev_yoy", "profit_yoy",
    "roe", "gross_margin", "net_margin", "report_date",
    "composite_score", "value_score", "growth_score", "quality_score",
    "safety_score", "momentum_score", "cashflow_score", "data_completeness",
]

CONSOLE_COLUMNS = [
    "rank", "market", "code", "name", "price", "pe_ttm", "pb", "rev_yoy",
    "profit_yoy", "roe", "composite_score", "value_score", "growth_score",
    "quality_score", "safety_score", "momentum_score", "cashflow_score",
]


# ---------------------------------------------------------------------------
# Snapshot discovery and loading
# ---------------------------------------------------------------------------
def find_snapshots(data_dir=None) -> list:
    """Available snapshot dates (YYYYMMDD, oldest first)."""
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    snaps = data_dir / "snapshots"
    if not snaps.is_dir():
        return []
    return sorted(d.name for d in snaps.iterdir()
                  if d.is_dir() and (d / "master.csv").exists())


def resolve_snapshot(data_dir=None, snapshot=None) -> Path:
    """Snapshot directory for a date string; latest when omitted."""
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    if snapshot:
        snap_dir = data_dir / "snapshots" / str(snapshot)
        if not (snap_dir / "master.csv").exists():
            raise FileNotFoundError(
                f"no master.csv in snapshot {snapshot!r}")
        return snap_dir
    dates = find_snapshots(data_dir)
    if not dates:
        raise FileNotFoundError("no snapshots found; run `fetch` first")
    return data_dir / "snapshots" / dates[-1]


def load_master(snapshot_dir) -> pd.DataFrame:
    """Read a snapshot's master.csv (code kept as zero-padded string)."""
    path = Path(snapshot_dir) / "master.csv"
    return pd.read_csv(path, dtype={"market": str, "code": str})


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
def screen(master: pd.DataFrame, strategy=None, preset=None, weights=None,
           horizon=None, snap_dir=None, top_n=None,
           markets=None) -> pd.DataFrame:
    """Apply a strategy/horizon to a master frame; return ranked rows.

    ``strategy`` is a registry id (presets + masters); ``preset`` is a
    backward-compatible alias. ``weights`` (custom pillar weights) takes
    precedence when given (gates are then skipped, as before).

    ``horizon`` adds the holding-period lens:
    - horizon alone (no strategy/preset/weights): the horizon IS the
      strategy — its weights and gates are used.
    - strategy + horizon: the strategy's weights and gates stay; only
      the momentum measurement window switches to the horizon's.
    - weights + horizon: custom weights (no gates), horizon window.
    ``snap_dir`` enables short-window factor backfill from the
    snapshot's kline cache for old snapshots.
    """
    from pathlib import Path as _Path

    from .strategy.factors import PILLARS, add_derived_factors, \
        add_pillar_scores
    from .strategy.registry import evaluate_gates, get_horizon, \
        get_strategy

    top_n = top_n or config.DEFAULT_TOP_N
    h = get_horizon(horizon) if horizon else None
    if weights:
        profile = normalize_weights(weights)
        gates = []
    elif h and not (strategy or preset):
        profile = normalize_weights(h.weights)
        gates = h.gates or []
    else:
        sid = strategy or preset or config.DEFAULT_PRESET
        s = get_strategy(sid)
        profile = normalize_weights(s.weights)
        gates = s.gates or []

    # Backfill missing pillar score columns from available raw factors
    # (old snapshots; see git history for the original 4-pillar case).
    missing_scores = [f"{p}_score" for p in PILLARS
                      if f"{p}_score" not in master.columns]
    if missing_scores:
        import sys
        recomputable = ("ret_60d" in master.columns
                        and "ret_250d" in master.columns)
        if recomputable:
            print(f"[WARN] backfilling pillar scores from raw factors "
                  f"(missing: {', '.join(missing_scores)})",
                  file=sys.stderr)
            master = add_pillar_scores(master)
        else:
            print(f"[WARN] snapshot missing score columns and raw kline "
                  f"factors; weights will normalize to available pillars "
                  f"(missing: {', '.join(missing_scores)})",
                  file=sys.stderr)

    # Old snapshots lack ret_5d/ret_20d/vol_20d; refill from kline cache
    # when screening on a horizon that needs them.
    if h is not None and snap_dir is not None:
        from .fetch.pipeline import backfill_kline_factors
        master = backfill_kline_factors(master, _Path(snap_dir))

    # Gate inputs derived from existing columns (e.g. Graham's pe_pb).
    master = add_derived_factors(master)

    if h is not None:
        master = master.copy()
        master["momentum_score"] = recompute_momentum_score(
            master, h.momentum_cols)

    if gates:
        master = master[evaluate_gates(master, gates)]

    scored = apply_composite(master, profile,
                             min_pillars=config.MIN_PILLARS)
    top = rank_top(scored, top_n, markets=markets)
    out = top.reset_index(drop=True).reindex(columns=REPORT_COLUMNS)
    out["rank"] = range(1, len(out) + 1)
    return out


def describe_weights(profile: dict) -> str:
    """Human-readable weight line, e.g. 'value 0.35 / growth 0.25'."""
    return " / ".join(f"{p} {profile[p]:.2f}" for p in profile
                      if profile[p] > 0)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def export_csv(df: pd.DataFrame, path) -> Path:
    """Write the ranked table to CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.reindex(columns=REPORT_COLUMNS).to_csv(path, index=False)
    return path


def _fmt_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _markdown_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(_fmt_cell(row[c]) for c in cols)
                     + " |")
    return "\n".join(lines)


def export_markdown(df: pd.DataFrame, path, title="Value Genie report",
                    meta: dict | None = None) -> Path:
    """Write the ranked table plus run metadata as a Markdown file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    for key, value in (meta or {}).items():
        lines.append(f"- **{key}**: {value}")
    if meta:
        lines.append("")
    lines.append(_markdown_table(df.reindex(columns=REPORT_COLUMNS)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def format_console(df: pd.DataFrame) -> str:
    """Compact table for terminal output."""
    cols = [c for c in CONSOLE_COLUMNS if c in df.columns]
    return df[cols].to_string(index=False, float_format=lambda v: f"{v:.1f}")
