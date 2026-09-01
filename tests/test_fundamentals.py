"""Tests for value_genie.fetch.fundamentals (no network)."""

from datetime import date

import pandas as pd
import pytest

from value_genie.fetch import fundamentals as f


class TestCandidateReportDates:
    def test_orders_newest_first(self):
        out = f.candidate_report_dates(date(2026, 8, 31))
        assert out == sorted(out, reverse=True)
        assert out[0] == date(2026, 6, 30)

    def test_excludes_future_dates(self):
        out = f.candidate_report_dates(date(2026, 1, 15))
        assert all(d < date(2026, 1, 15) for d in out)
        assert out[0] == date(2025, 12, 31)

    def test_lookback_cap(self):
        assert len(f.candidate_report_dates(date(2026, 8, 31), lookback=2)) == 2


class TestMergeAPeriods:
    def _df(self, codes, revs):
        return pd.DataFrame({"code": codes, "revenue": revs,
                             "report_date": ["2026-06-30"] * len(codes)})

    def test_latest_wins(self):
        latest = self._df(["000001", "600519"], [100.0, 200.0])
        prev = self._df(["000001", "600519"], [50.0, 80.0])
        out = f.merge_a_periods(latest, prev)
        assert len(out) == 2
        assert dict(zip(out["code"], out["revenue"])) == {
            "000001": 100.0, "600519": 200.0}

    def test_late_filers_appended(self):
        latest = self._df(["600519"], [200.0])
        prev = self._df(["600519", "000001"], [80.0, 50.0])
        out = f.merge_a_periods(latest, prev)
        assert len(out) == 2
        assert set(out["code"]) == {"600519", "000001"}

    def test_empty_prev(self):
        latest = self._df(["600519"], [200.0])
        assert len(f.merge_a_periods(latest, pd.DataFrame())) == 1

    def test_empty_latest(self):
        prev = self._df(["000001"], [50.0])
        assert len(f.merge_a_periods(pd.DataFrame(), prev)) == 1


class TestFramesContext:
    def test_mid_year(self):
        ctx = f.frames_year_context(date(2026, 8, 31))
        assert ctx["cy"] == 2025
        assert ctx["cy_prev"] == 2024
        # latest quarter end >= 50 days before Aug 31 is Jun 30
        assert ctx["q"] == "2026Q2"
        assert ctx["q_prev"] == "2025Q2"

    def test_early_year(self):
        ctx = f.frames_year_context(date(2026, 2, 10))
        assert ctx["cy"] == 2025
        assert ctx["cy_prev"] == 2024
        # only Q3 2025 is >= 50 days old
        assert ctx["q"] == "2025Q3"
        assert ctx["q_prev"] == "2024Q3"


class TestFrameName:
    CTX = {"cy": 2025, "cy_prev": 2024, "q": "2026Q2", "q_prev": "2025Q2"}

    def test_duration_frames(self):
        assert f.frame_name("duration", "cy", self.CTX) == "CY2025"
        assert f.frame_name("duration", "cy_prev", self.CTX) == "CY2024"
        assert f.frame_name("duration", "q", self.CTX) == "CY2026Q2"
        assert f.frame_name("duration", "q_prev", self.CTX) == "CY2025Q2"

    def test_instant_frames(self):
        assert f.frame_name("instant", "cy", self.CTX) == "CY2025Q4I"
        assert f.frame_name("instant", "cy_prev", self.CTX) == "CY2024Q4I"


class TestParseFrame:
    def test_basic(self):
        d = {"data": [{"cik": 320193, "val": 123.5},
                      {"cik": 789019, "val": "-"},
                      {"cik": None, "val": 1.0},
                      {"cik": 111, "val": None}]}
        assert f.parse_frame(d) == {320193: 123.5}

    def test_empty(self):
        assert f.parse_frame(None) == {}
        assert f.parse_frame({}) == {}


class TestDeriveUsMetrics:
    def test_full_record(self):
        rec = {"rev": 110.0, "rev_prev": 100.0, "profit": 22.0,
               "profit_prev": 20.0, "rev_q": 30.0, "rev_q_prev": 25.0,
               "gross_profit": 44.0, "equity": 100.0, "equity_prev": 90.0,
               "liabilities": 60.0, "assets": 160.0}
        out = f.derive_us_metrics(rec)
        assert out["rev_yoy"] == 10.0
        assert out["profit_yoy"] == 10.0
        assert out["rev_q_yoy"] == 20.0
        assert out["net_margin"] == 20.0
        assert out["gross_margin"] == 40.0
        assert out["roe"] == 22.0 / 95.0 * 100.0
        assert out["debt_ratio"] == 37.5
        assert out["ps_revenue"] == 110.0

    def test_missing_prev_no_yoy(self):
        rec = {"rev": 110.0, "rev_prev": None, "profit": 22.0,
               "profit_prev": 0.0}
        out = f.derive_us_metrics(rec)
        assert "rev_yoy" not in out
        assert "profit_yoy" not in out  # zero prev is unsafe denominator
        assert out["net_margin"] == 20.0

    def test_negative_prev_profit(self):
        # turn-around: profit_yoy must still compute against abs(prev)
        rec = {"profit": 10.0, "profit_prev": -5.0}
        out = f.derive_us_metrics(rec)
        assert out["profit_yoy"] == 300.0

    def test_empty(self):
        assert f.derive_us_metrics({}) == {}


class TestDeriveUsMetricsOneOff:
    """Recurring-basis profit metrics: pre-tax one-off disposal gains and
    losses are stripped from net income before deriving growth/quality."""

    def test_disposal_gain_stripped_from_yoy(self):
        # WTM-shaped case: 2025 NI inflated by a business disposal gain
        rec = {"rev": 3735.0, "rev_prev": 2239.8, "profit": 1106.4,
               "profit_prev": 230.4, "oneoff": 849.3, "oneoff_prev": 0.0}
        out = f.derive_us_metrics(rec)
        assert out["profit_yoy"] == pytest.approx(
            (1106.4 - 849.3 - 230.4) / 230.4 * 100.0)

    def test_oneoff_stripped_from_margin_and_roe(self):
        rec = {"rev": 1000.0, "profit": 500.0, "oneoff": 400.0,
               "equity": 1000.0, "equity_prev": 1000.0}
        out = f.derive_us_metrics(rec)
        assert out["net_margin"] == pytest.approx(10.0)
        assert out["roe"] == pytest.approx(10.0)

    def test_prev_year_oneoff_stripped(self):
        rec = {"profit": 300.0, "profit_prev": 500.0,
               "oneoff": 0.0, "oneoff_prev": 400.0}
        out = f.derive_us_metrics(rec)
        assert out["profit_yoy"] == pytest.approx(200.0)  # 300 vs 100

    def test_oneoff_loss_added_back(self):
        # negative one-off (loss on disposal) raises recurring profit
        rec = {"profit": 100.0, "profit_prev": 100.0, "oneoff": -50.0}
        out = f.derive_us_metrics(rec)
        assert out["profit_yoy"] == pytest.approx(50.0)

    def test_missing_oneoff_unchanged(self):
        rec = {"rev": 110.0, "rev_prev": 100.0, "profit": 22.0,
               "profit_prev": 20.0, "oneoff": None, "oneoff_prev": None}
        out = f.derive_us_metrics(rec)
        assert out["profit_yoy"] == 10.0
        assert out["net_margin"] == pytest.approx(20.0)

    def test_stripped_prev_zero_skips_yoy(self):
        rec = {"profit": 100.0, "profit_prev": 400.0,
               "oneoff": 0.0, "oneoff_prev": 400.0}
        out = f.derive_us_metrics(rec)
        assert "profit_yoy" not in out  # unsafe denominator after stripping


class TestSumOneoffFrames:
    def test_sums_across_concepts_per_cik(self):
        frames = {("A", "cy"): {1: 100.0, 2: 50.0},
                  ("B", "cy"): {1: 25.0}}
        out = f.sum_oneoff_frames(frames, "cy", ["A", "B"])
        assert out == {1: 125.0, 2: 50.0}

    def test_missing_concept_ignored(self):
        frames = {("A", "cy"): {1: 100.0}}
        assert f.sum_oneoff_frames(frames, "cy", ["A", "B"]) == {1: 100.0}

    def test_empty(self):
        assert f.sum_oneoff_frames({}, "cy", ["A"]) == {}
