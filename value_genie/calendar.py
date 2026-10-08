"""Trading-calendar primitives (user mandate 2026-10-08).

Pure functions, no IO. Holiday/half-day/DST tables live in config.py
(static yearly tables — refresh annually). All times are Beijing time;
the US session is mapped into Beijing hours and shifts one hour with
config.US_DST.

Note: this module shadows nothing — stdlib ``calendar`` is unaffected
(Python 3 absolute imports); always import as ``from . import calendar``
or ``from value_genie import calendar``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import config


def is_trading_day(market: str, d: date) -> bool:
    """Weekdays minus the static holiday table (half days still count)."""
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in config.TRADING_HOLIDAYS.get(market, set())


def next_trading_day(market: str, d: date, n: int = 1) -> date:
    """n-th trading day after ``d`` (holidays and weekends skipped)."""
    added = 0
    while added < n:
        d += timedelta(days=1)
        if is_trading_day(market, d):
            added += 1
    return d


def last_trading_day(market: str, d: date | None = None) -> date:
    """Most recent trading day on or before ``d`` (default: today)."""
    d = d or date.today()
    while not is_trading_day(market, d):
        d -= timedelta(days=1)
    return d


def trading_day_lag(market: str, last_bar: date,
                    today: date | None = None) -> int:
    """Trading days between ``last_bar`` and ``today`` (closed days do not
    advance the lag — a market shut for Golden Week stays at lag 0)."""
    today = today or date.today()
    if last_bar >= today:
        return 0
    n, d = 0, last_bar
    while d < today:
        d += timedelta(days=1)
        if is_trading_day(market, d):
            n += 1
    return n


def us_dst_active(d: date) -> bool:
    start, end = config.US_DST
    return date.fromisoformat(start) <= d <= date.fromisoformat(end)


def session_windows(market: str, d: date) -> list[tuple[int, int]]:
    """Session windows as Beijing minute-of-day pairs for trade date ``d``.

    The US evening session wraps past midnight: the close leg is returned
    as minutes beyond 24:00 (e.g. (1290, 1680) = 21:30 -> next-day 04:00).
    """
    iso = d.isoformat()
    half = iso in config.HALF_DAYS.get(market, set())
    if market == "A":
        return [(570, 690), (780, 900)]
    if market == "HK":
        return [(570, 720)] if half else [(570, 720), (780, 960)]
    # US: 9:30 ET -> Beijing 21:30 (DST) / 22:30 (standard)
    open_m = 1290 if us_dst_active(d) else 1350
    close_et = 780 if half else 960          # 13:00 / 16:00 ET
    shift = 720 if us_dst_active(d) else 780  # ET -> Beijing minutes
    return [(open_m, close_et + shift)]


def session_close_dt(market: str, d: date) -> datetime:
    """Beijing-time moment when trade date ``d``'s session closes."""
    close_m = max(w[1] for w in session_windows(market, d))
    base = datetime.combine(d, datetime.min.time())
    return base + timedelta(minutes=close_m)


def in_session(market: str, now: datetime | None = None) -> bool:
    """True when ``market`` is actively trading at ``now`` (Beijing time)."""
    now = now or datetime.now()
    minute = now.hour * 60 + now.minute
    today = now.date()
    # Today's session (and, for wrap-around markets, yesterday's session
    # whose close leg spills into this morning).
    for d in (today, today - timedelta(days=1)):
        if not is_trading_day(market, d):
            continue
        for open_m, close_m in session_windows(market, d):
            start = datetime.combine(d, datetime.min.time()) + \
                timedelta(minutes=open_m)
            end = datetime.combine(d, datetime.min.time()) + \
                timedelta(minutes=close_m)
            if start <= now <= end:
                return True
    return False


def last_completed_session(market: str,
                           now: datetime | None = None) -> date:
    """Latest trade date whose session has fully closed by ``now``."""
    now = now or datetime.now()
    d = last_trading_day(market, now.date())
    while now < session_close_dt(market, d):
        d = last_trading_day(market, d - timedelta(days=1))
    return d
