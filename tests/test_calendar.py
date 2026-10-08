"""Tests for value_genie.calendar (pure functions, no IO).

Pins the 2026 static tables: weekends, holidays, half days, US DST and
the cross-market cases the freshness gate depends on (a closed CN
market must not stall US answers — user mandate 2026-10-08).
"""

from datetime import date, datetime

from value_genie import calendar as cal


class TestIsTradingDay:
    def test_weekend_is_not_trading(self):
        assert not cal.is_trading_day("A", date(2026, 10, 10))   # Saturday
        assert not cal.is_trading_day("HK", date(2026, 10, 11))  # Sunday
        assert not cal.is_trading_day("US", date(2026, 10, 10))

    def test_weekday_is_trading(self):
        assert cal.is_trading_day("A", date(2026, 10, 8))    # Thursday
        assert cal.is_trading_day("HK", date(2026, 10, 8))
        assert cal.is_trading_day("US", date(2026, 10, 7))

    def test_holiday_table(self):
        assert not cal.is_trading_day("A", date(2026, 10, 1))   # 国庆
        assert not cal.is_trading_day("US", date(2026, 1, 19))  # MLK
        assert not cal.is_trading_day("HK", date(2026, 12, 25))

    def test_cross_market_independence(self):
        """2026-02-16 (Monday): A closed for CNY, US closed for
        Washington's Birthday, HK open on the LNY-eve HALF day — each
        market answers from its own calendar."""
        d = date(2026, 2, 16)
        assert not cal.is_trading_day("A", d)
        assert not cal.is_trading_day("US", d)
        assert cal.is_trading_day("HK", d)        # half days still count

    def test_unknown_year_falls_back_to_weekday(self):
        # no 2027 entries yet: weekday logic still applies (doctor warns
        # about the lapsed table separately)
        assert cal.is_trading_day("A", date(2027, 1, 4))      # Monday
        assert not cal.is_trading_day("A", date(2027, 1, 2))  # Saturday


class TestNextTradingDay:
    def test_skips_golden_week(self):
        assert cal.next_trading_day("A", date(2026, 9, 30)) == \
            date(2026, 10, 8)

    def test_skips_weekend_and_holiday(self):
        # HK: 12-24 (Thu, half) -> 12-25 holiday, 26/27 weekend -> 12-28
        assert cal.next_trading_day("HK", date(2026, 12, 24)) == \
            date(2026, 12, 28)

    def test_n_days(self):
        assert cal.next_trading_day("A", date(2026, 10, 8), n=2) == \
            date(2026, 10, 12)      # 10-09 Fri, 10-12 Mon


class TestTradingDayLag:
    def test_closed_days_do_not_advance_lag(self):
        """The National-Day case: a bar from 09-30 read on 10-08 is ONE
        trading day stale, not eight calendar days."""
        assert cal.trading_day_lag("A", date(2026, 9, 30),
                                   date(2026, 10, 8)) == 1

    def test_same_day_is_zero(self):
        assert cal.trading_day_lag("A", date(2026, 10, 8),
                                   date(2026, 10, 8)) == 0

    def test_future_bar_is_zero(self):
        assert cal.trading_day_lag("A", date(2026, 10, 9),
                                   date(2026, 10, 8)) == 0

    def test_full_closure_week_keeps_zero(self):
        # mid-Golden-Week: no A trading day has passed since 09-30
        assert cal.trading_day_lag("A", date(2026, 9, 30),
                                   date(2026, 10, 5)) == 0


class TestUsDst:
    def test_dst_window(self):
        assert cal.us_dst_active(date(2026, 7, 1))
        assert not cal.us_dst_active(date(2026, 1, 5))
        assert cal.us_dst_active(date(2026, 3, 8))    # window start
        assert cal.us_dst_active(date(2026, 11, 1))   # window end

    def test_session_open_shifts_one_hour(self):
        dst = cal.session_windows("US", date(2026, 7, 1))[0]
        std = cal.session_windows("US", date(2026, 1, 5))[0]
        assert dst[0] == 21 * 60 + 30       # 21:30 Beijing
        assert std[0] == 22 * 60 + 30       # 22:30 Beijing


class TestSessionWindows:
    def test_a_share_two_windows(self):
        assert cal.session_windows("A", date(2026, 10, 8)) == \
            [(570, 690), (780, 900)]

    def test_hk_full_vs_half_day(self):
        full = cal.session_windows("HK", date(2026, 10, 8))
        half = cal.session_windows("HK", date(2026, 2, 16))
        assert len(full) == 2 and len(half) == 1
        assert half[0][1] == 720            # closes 12:00 Beijing

    def test_us_close_wraps_past_midnight(self):
        # DST full session: 21:30 -> next-day 04:00 Beijing (1680 > 1440)
        w = cal.session_windows("US", date(2026, 10, 7))[0]
        assert w == (1290, 1680)

    def test_us_half_day(self):
        # after-Thanksgiving half: 13:00 ET close; DST already ended
        # (window ends 11-01) so shift=780 -> next-day 02:00 Beijing
        w = cal.session_windows("US", date(2026, 11, 27))[0]
        assert w[1] == 780 + 780            # 1560 = 26:00 = next-day 02:00


class TestSessionCloseDt:
    def test_a_close_same_day(self):
        assert cal.session_close_dt("A", date(2026, 10, 8)) == \
            datetime(2026, 10, 8, 15, 0)

    def test_us_close_next_morning(self):
        assert cal.session_close_dt("US", date(2026, 10, 7)) == \
            datetime(2026, 10, 8, 4, 0)


class TestInSession:
    def test_a_morning_and_afternoon(self):
        assert cal.in_session("A", datetime(2026, 10, 8, 10, 0))
        assert not cal.in_session("A", datetime(2026, 10, 8, 12, 0))
        assert cal.in_session("A", datetime(2026, 10, 8, 14, 0))
        assert not cal.in_session("A", datetime(2026, 10, 8, 15, 30))

    def test_hk_half_day_afternoon_closed(self):
        assert cal.in_session("HK", datetime(2026, 2, 16, 11, 0))
        assert not cal.in_session("HK", datetime(2026, 2, 16, 13, 30))

    def test_us_dst_vs_standard_open(self):
        assert cal.in_session("US", datetime(2026, 10, 7, 22, 0))   # DST
        assert not cal.in_session("US", datetime(2026, 1, 5, 22, 0))
        assert cal.in_session("US", datetime(2026, 1, 5, 23, 0))

    def test_us_wrap_leg_into_next_morning(self):
        # trade date 10-07's session spills into 10-08 early morning
        assert cal.in_session("US", datetime(2026, 10, 8, 2, 0))
        assert not cal.in_session("US", datetime(2026, 10, 8, 5, 0))

    def test_holiday_not_in_session(self):
        assert not cal.in_session("A", datetime(2026, 10, 5, 10, 0))


class TestLastCompletedSession:
    def test_a_during_session_points_to_previous_close(self):
        assert cal.last_completed_session(
            "A", datetime(2026, 10, 8, 14, 0)) == date(2026, 9, 30)

    def test_a_after_close_is_today(self):
        assert cal.last_completed_session(
            "A", datetime(2026, 10, 8, 16, 0)) == date(2026, 10, 8)

    def test_closed_week_returns_pre_holiday_close(self):
        assert cal.last_completed_session(
            "A", datetime(2026, 10, 3, 12, 0)) == date(2026, 9, 30)

    def test_us_morning_before_wrap_close(self):
        # 03:00 Beijing 10-08: the 10-07 session (closes 04:00) is still
        # running -> last COMPLETED is 10-06
        assert cal.last_completed_session(
            "US", datetime(2026, 10, 8, 3, 0)) == date(2026, 10, 6)

    def test_us_morning_after_wrap_close(self):
        assert cal.last_completed_session(
            "US", datetime(2026, 10, 8, 5, 0)) == date(2026, 10, 7)
