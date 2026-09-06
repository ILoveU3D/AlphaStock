"""Tests for value_genie.fetch.fundamentals (no network)."""

from datetime import date
from types import SimpleNamespace

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


class TestNormalizeUsTicker:
    def test_class_share_forms(self):
        # SEC ticker file uses hyphen/dot class separators; Eastmoney
        # quote codes use underscores — the join key must be normalized
        assert f.normalize_us_ticker("BRK-A") == "BRK_A"
        assert f.normalize_us_ticker("BRK.B") == "BRK_B"
        assert f.normalize_us_ticker("brk-b") == "BRK_B"

    def test_plain_ticker_unchanged(self):
        assert f.normalize_us_ticker("AAPL") == "AAPL"


class TestDeriveUsMetricsCostFallback:
    def test_gross_margin_from_cost(self):
        # PDD stopped tagging GrossProfit but keeps tagging CostOfRevenue
        out = f.derive_us_metrics({"rev": 100.0, "cost": 60.0})
        assert out["gross_margin"] == 40.0

    def test_gross_profit_preferred_over_cost(self):
        out = f.derive_us_metrics({"rev": 100.0, "cost": 60.0,
                                   "gross_profit": 50.0})
        assert out["gross_margin"] == 50.0

    def test_neither_present_no_margin(self):
        out = f.derive_us_metrics({"rev": 100.0})
        assert "gross_margin" not in out


class TestFetchUsFinancialsOne:
    """SEC companyconcept fallback for held tickers the frames
    aggregation misses (e.g. BRK_B)."""

    @pytest.fixture()
    def mock_sec(self, monkeypatch):
        ctx = f.frames_year_context()
        cy, cy_p = ctx["cy"], ctx["cy_prev"]

        def dur(year, val):
            return {"frame": f"CY{year}", "val": val,
                    "start": f"{year}-01-01", "end": f"{year}-12-31"}

        def inst(year, val):
            return {"frame": f"CY{year}Q4I", "val": val,
                    "end": f"{year}-12-31"}

        facts = {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                dur(cy, 300000.0), dur(cy_p, 250000.0)],
            "NetIncomeLoss": [dur(cy, 60000.0), dur(cy_p, 50000.0)],
            "GrossProfit": [],                       # not tagged (PDD case)
            "CostOfRevenue": [dur(cy, 180000.0)],
            "StockholdersEquity": [inst(cy, 500000.0), inst(cy_p, 450000.0)],
            "Liabilities": [inst(cy, 700000.0)],
            "Assets": [inst(cy, 1200000.0)],
            "NetCashProvidedByUsedInOperatingActivities": [dur(cy, 80000.0)],
        }

        def fake_get_json(url, **kw):
            for concept, fs in facts.items():
                if f"/{concept}.json" in url:
                    return {"units": {"USD": fs}}
            return None

        monkeypatch.setattr(f, "SEC", SimpleNamespace(get_json=fake_get_json))
        monkeypatch.setattr(f, "load_sec_cik_map",
                            lambda: {"BRK_B": 1067983})
        return {"cy": cy, "cy_p": cy_p}

    def test_resolves_financials(self, mock_sec):
        rec = f.fetch_us_financials_one("BRK_B", quiet=True)
        assert rec is not None
        assert rec["rev"] == 300000.0
        assert rec["profit"] == 60000.0
        assert rec["rev_yoy"] == 20.0
        assert rec["gross_margin"] == 40.0   # (300k-180k)/300k via cost
        assert rec["debt_ratio"] == pytest.approx(700000.0 / 1200000.0
                                                  * 100.0)
        assert rec["cash_conversion"] == pytest.approx(80.0 / 60.0 * 100.0)

    def test_unknown_ticker_returns_none(self, mock_sec, monkeypatch):
        # cik map has no entry -> nothing to query
        monkeypatch.setattr(f, "load_sec_cik_map", lambda: {})
        assert f.fetch_us_financials_one("GHOST", quiet=True) is None

    def test_no_data_returns_none(self, mock_sec, monkeypatch):
        # every concept request returns None -> rev/profit both None
        monkeypatch.setattr(f, "load_sec_cik_map", lambda: {"GHOST": 1})
        monkeypatch.setattr(f, "SEC",
                            SimpleNamespace(get_json=lambda url, **kw: None))
        assert f.fetch_us_financials_one("GHOST", quiet=True) is None


class TestFetchAFinancialsOne:
    def test_single_stock_filter(self, monkeypatch):
        payload = {"result": {"data": [{
            "SECURITY_CODE": "688795", "REPORTDATE": "2026-06-30 00:00:00",
            "TOTAL_OPERATE_INCOME": 5.0e8, "YSTZ": 60.0,
            "PARENT_NETPROFIT": -2.0e8, "SJLTZ": None,
            "WEIGHTAVG_ROE": -5.0, "XSMLL": 30.0, "BPS": 8.0,
        }]}}
        monkeypatch.setattr(f, "DC", SimpleNamespace(
            get_json=lambda url, params=None, **kw: payload))
        df = f.fetch_a_financials_one("688795")
        assert len(df) == 1
        row = df.iloc[0]
        assert row["code"] == "688795"
        assert row["report_date"] == "2026-06-30"
        assert row["revenue"] == 5.0e8
        assert row["rev_yoy"] == 60.0
        assert row["profit"] == -2.0e8
        assert row["gross_margin"] == 30.0

    def test_no_rows_empty(self, monkeypatch):
        monkeypatch.setattr(f, "DC", SimpleNamespace(
            get_json=lambda url, params=None, **kw: {}))
        df = f.fetch_a_financials_one("588060")    # ETF: no report rows
        assert df.empty


class TestAnnualReportDates:
    def test_newest_first(self):
        out = f.annual_report_dates(date(2026, 9, 5))
        assert out == [date(2025, 12, 31), date(2024, 12, 31)]


class TestParseCashflow:
    def test_keeps_capex_and_financing(self):
        d = {"result": {"data": [{
            "SECURITY_CODE": "600519",
            "REPORT_DATE": "2025-12-31 00:00:00",
            "NETCASH_OPERATE": "1000", "CONSTRUCT_LONG_ASSET": "200",
            "NETCASH_FINANCE": "-50"}]}}
        df = f._parse_cashflow(d)
        assert df.iloc[0]["ocf"] == 1000.0
        assert df.iloc[0]["capex"] == 200.0
        assert df.iloc[0]["net_fin_cf"] == -50.0


class TestFetchACashflowAnnual:
    def test_picks_latest_annual_period(self, monkeypatch):
        pages = {
            ("2025-12-31", 1): {"result": {"count": 1200, "data": [
                {"SECURITY_CODE": "600519", "REPORT_DATE": "2025-12-31",
                 "NETCASH_OPERATE": "100", "CONSTRUCT_LONG_ASSET": "10",
                 "NETCASH_FINANCE": "1"}]}},
            ("2024-12-31", 1): {"result": {"count": 1000, "data": []}},
        }

        def fake_page(rd, pn):
            return pages.get((rd, pn), {"result": {"count": 0}})

        monkeypatch.setattr(f, "_fetch_cashflow_page", fake_page)
        out = f.fetch_a_cashflow_annual(quiet=True)
        assert len(out) == 1
        assert out.iloc[0]["ocf"] == 100.0
        assert out.iloc[0]["capex"] == 10.0

    def test_falls_back_when_latest_missing(self, monkeypatch):
        pages = {
            ("2025-12-31", 1): {"result": {"count": 3, "data": []}},
            ("2024-12-31", 1): {"result": {"count": 1200, "data": [
                {"SECURITY_CODE": "000001", "REPORT_DATE": "2024-12-31",
                 "NETCASH_OPERATE": "7", "CONSTRUCT_LONG_ASSET": "2",
                 "NETCASH_FINANCE": "-1"}]}},
        }

        def fake_page(rd, pn):
            return pages.get((rd, pn), {"result": {"count": 0}})

        monkeypatch.setattr(f, "_fetch_cashflow_page", fake_page)
        out = f.fetch_a_cashflow_annual(quiet=True)
        assert len(out) == 1
        assert out.iloc[0]["code"] == "000001"


class TestFetchADividends:
    def test_aggregates_events_per_fy(self, monkeypatch):
        # two FY2025 events for 600519 (interim + annual), one bare
        # commitment row without amounts must be skipped
        def fake_page(year, pn):
            if year != "2025" or pn > 1:
                return {"result": {"count": 3, "data": []}}
            return {"result": {"count": 3, "data": [
                {"SECURITY_CODE": "600519", "REPORT_DATE": "2025-09-30",
                 "PRETAX_BONUS_RMB": "239.57", "TOTAL_SHARES": "1256197800"},
                {"SECURITY_CODE": "600519", "REPORT_DATE": "2025-12-31",
                 "PRETAX_BONUS_RMB": "280.2423", "TOTAL_SHARES": "1256197800"},
                {"SECURITY_CODE": "000002", "REPORT_DATE": "2026-06-30",
                 "PRETAX_BONUS_RMB": None, "TOTAL_SHARES": None},
            ]}}

        monkeypatch.setattr(f, "_fetch_dividend_page", fake_page)
        out = f.fetch_a_dividends(["2025"], quiet=True)
        assert len(out) == 1
        r = out.iloc[0]
        assert r["code"] == "600519" and r["fy"] == "2025"
        assert r["div_paid"] == pytest.approx(
            (239.57 + 280.2423) / 10.0 * 1256197800)

    def test_no_events_returns_empty(self, monkeypatch):
        monkeypatch.setattr(f, "_fetch_dividend_page",
                            lambda year, pn: {"result": {"count": 0}})
        assert f.fetch_a_dividends(["2025"], quiet=True).empty


def _hk_row(rd, sd, item, amt):
    return {"REPORT_DATE": rd, "START_DATE": sd, "STD_ITEM_CODE": item,
            "STD_ITEM_NAME": "x", "AMOUNT": amt}


class TestHkCashflow:
    def test_annual_row_selected_and_mapped(self, monkeypatch):
        # interim (H1) rows must lose to the FY2025 annual group
        data = [
            _hk_row("2026-06-30", "2026-01-01", "003999", "500"),
            _hk_row("2026-06-30", "2026-01-01", "005005", "100"),
            _hk_row("2025-12-31", "2025-01-01", "003999", "1000"),
            _hk_row("2025-12-31", "2025-01-01", "005005", "200"),
            _hk_row("2025-12-31", "2025-01-01", "005007", "50"),
            _hk_row("2025-12-31", "2025-01-01", "007004", "300"),
            _hk_row("2025-12-31", "2025-01-01", "007999", "80"),
        ]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        df = f.fetch_hk_cashflow("06831")
        r = df.iloc[0]
        assert r["code"] == "06831"
        assert r["report_date"] == "2025-12-31"
        assert r["ocf"] == 1000.0
        assert r["capex"] == 250.0
        assert r["div_paid"] == 300.0
        assert r["net_fin_cf"] == 80.0

    def test_march_year_end_is_annual(self, monkeypatch):
        # HK fiscal years end in Mar/Jun/Sep/Dec — span, not month,
        # marks the annual report
        data = [_hk_row("2026-03-31", "2025-04-01", "003999", "900")]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        df = f.fetch_hk_cashflow("00005")
        assert df.iloc[0]["ocf"] == 900.0

    def test_no_annual_period_returns_none(self, monkeypatch):
        data = [_hk_row("2026-06-30", "2026-01-01", "003999", "500")]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        assert f.fetch_hk_cashflow("06831") is None

    def test_missing_item_stays_absent(self, monkeypatch):
        data = [_hk_row("2025-12-31", "2025-01-01", "003999", "1000")]
        monkeypatch.setattr(
            f.DC, "get_json", lambda *a, **k: {"result": {"data": data}})
        r = f.fetch_hk_cashflow("06831").iloc[0]
        assert pd.isna(r.get("div_paid"))
