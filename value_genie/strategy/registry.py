"""Pluggable registries for strategies and data sources.

Strategy unifies the old "preset" (weight-only profiles) and the new
"master" (weights + hard gates + AI skill file) concepts.  DataSource
maps (data_type, market) to an ordered list of fetcher callables so
the pipeline can query sources without hardcoding them.

Adding a new strategy or source = one ``register_*`` call; existing
code does not change.
"""

from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------
@dataclass
class Strategy:
    """A named, weight-profiled screening strategy.

    kind="preset" → pure weight profile (balanced, garp, ...).
    kind="master" → weight profile + hard gates + skill file + AI
    triggers (buffett, duan, ...).
    """

    id: str
    name: str
    weights: dict                     # {pillar: float}
    gates: list = field(default_factory=list)
    # [(column, op, value), ...] e.g. ("roe", ">=", 15)
    kind: str = "preset"
    skill_file: str = ""              # "07-master-buffett.md"
    triggers: list = field(default_factory=list)
    order: int = 99                   # display rank (masters: by fame)


_STRATEGIES: dict[str, Strategy] = {}


def register_strategy(s: Strategy) -> Strategy:
    """Register a strategy; replaces if id exists."""
    _STRATEGIES[s.id] = s
    return s


def get_strategy(strategy_id: str) -> Strategy:
    """Fetch a registered strategy; KeyError if unknown."""
    try:
        return _STRATEGIES[strategy_id]
    except KeyError:
        known = ", ".join(sorted(_STRATEGIES))
        raise ValueError(
            f"unknown strategy {strategy_id!r}; available: {known}") from None


def list_strategies(kind: str = "") -> list[Strategy]:
    """All registered strategies, sorted by (kind, order, id).

    Masters carry an explicit ``order`` (fame rank), so `strategy list`
    shows Buffett before Munger before Graham, etc. Presets keep their
    alphabetical order via the default order of 99.
    """
    items = [s for s in _STRATEGIES.values() if not kind or s.kind == kind]
    return sorted(items, key=lambda s: (s.kind, s.order, s.id))


# ---------------------------------------------------------------------------
# DataSource registry
# ---------------------------------------------------------------------------
@dataclass
class DataSource:
    """A data source provides fetchers for one or more (type, market) pairs.

    capabilities: ["quotes:A", "quotes:HK", "financials:A", "kline:A", ...]
    fetchers: {"quotes": callable, "financials": callable, "kline": callable}
    """

    id: str
    name: str
    capabilities: list = field(default_factory=list)
    fetchers: dict = field(default_factory=dict)


_SOURCES: dict[str, DataSource] = {}
_SOURCE_ORDER: dict[str, list[str]] = {}  # "data_type:market" -> [source_id, ...]


def register_source(ds: DataSource) -> DataSource:
    """Register a data source; replaces if id exists."""
    _SOURCES[ds.id] = ds
    return ds


def set_source_order(data_type: str, market: str, source_ids: list[str]):
    """Set the lookup order (primary + fallbacks) for a (type, market)."""
    _SOURCE_ORDER[f"{data_type}:{market}"] = list(source_ids)


def get_sources(data_type: str, market: str) -> list[DataSource]:
    """Ordered data sources for (data_type, market): primary first.

    Sources registered with a matching capability but not listed in the
    explicit order are appended as last-resort fallbacks, so a new
    source needs only ``register_source`` to become discoverable.
    """
    key = f"{data_type}:{market}"
    order = _SOURCE_ORDER.get(key, [])
    out = [_SOURCES[sid] for sid in order if sid in _SOURCES]
    have = {ds.id for ds in out}
    for ds in _SOURCES.values():
        if ds.id not in have and key in ds.capabilities:
            out.append(ds)
    return out


def list_sources() -> list[DataSource]:
    """All registered data sources."""
    return list(_SOURCES.values())


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------
def evaluate_gates(df, gates: list, market_col: str = "market") -> "pd.Series":
    """Return a boolean mask: True if row passes all gates.

    Ops:
    - ">=", "<=" : absolute value comparison
    - "pctl>=", "pctl<=" : within-market percentile comparison
    """
    import pandas as pd

    if not gates:
        return pd.Series(True, index=df.index)
    mask = pd.Series(True, index=df.index)
    for col, op, val in gates:
        if col not in df.columns:
            # skip gates whose column is unavailable (e.g. old snapshot
            # lacking ocf_yield); warn so the user knows a filter was
            # dropped rather than silently blocking every row.
            import sys
            print(f"[WARN] gate skipped: column {col!r} not in snapshot "
                  f"(op={op}, val={val})", file=sys.stderr)
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if op == ">=":
            mask &= s >= val
        elif op == "<=":
            mask &= s <= val
        elif op == "pctl>=":
            # val is a percentile threshold; pass if stock's percentile
            # within its market is >= val
            pct = s.groupby(df[market_col]).rank(pct=True) * 100
            mask &= pct >= val
        elif op == "pctl<=":
            pct = s.groupby(df[market_col]).rank(pct=True) * 100
            mask &= pct <= val
    return mask
