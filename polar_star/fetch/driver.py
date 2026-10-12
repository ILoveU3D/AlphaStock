"""Registry-driven source ordering and failover.

The pipeline asks the registry which source to try first instead of
hardcoding "Eastmoney first, Tencent second" — a source accumulating
failures (health penalty) automatically yields its primary seat.

Adding a new source = one ``register_source`` call plus one entry in the
call site's ``attempts`` dict; no other code changes.
"""

from ..strategy.registry import ordered_sources
from .health import COOLDOWN_PENALTY, get_health


def source_order(data_type: str, market: str, health=None) -> list:
    """Source ids in current preference order (health-aware)."""
    h = health if health is not None else get_health()
    return [ds.id for ds in ordered_sources(data_type, market, h)]


def preferred(data_type: str, market: str, health=None) -> str | None:
    """The source id to try first, or None when nobody claims the pair."""
    order = source_order(data_type, market, health)
    return order[0] if order else None


def run_with_failover(data_type: str, market: str, attempts: dict,
                      health=None):
    """Try each source's callable in health-ordered preference.

    attempts: {source_id: callable() -> result|None}. Returns
    (result, source_id, errors); result is None on total failure.

    Health semantics: a raised exception records a graded failure; an
    empty/None result just moves to the next source — a per-entity miss
    (an ETF outside the clist universe, a delisted kline) is not a
    source outage. Success clears the source's failure count. A source
    in cooldown (penalty >= COOLDOWN_PENALTY) is not even tried — its
    IP block will not heal inside this call.
    """
    h = health if health is not None else get_health()
    errors = []
    for ds_id in source_order(data_type, market, h):
        fn = attempts.get(ds_id)
        if fn is None:
            continue
        if h.penalty(ds_id) >= COOLDOWN_PENALTY:
            errors.append(f"{ds_id}: in cooldown, skipped")
            continue
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001 — failover must not raise
            h.record_failure(ds_id, e)
            errors.append(f"{ds_id}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if res is None or (hasattr(res, "empty") and res.empty):
            continue
        h.record_success(ds_id)
        return res, ds_id, errors
    return None, None, errors
