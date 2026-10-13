"""Tests for the value/quality/capital-discipline arsenal weapons.

Synthetic frames only — no network, no real snapshot.  Aux-CSV
weapons read tiny handcrafted CSVs from tmp_path; deep weapons read a
synthetic models/ tree via the models_dir parameter.
"""

import json

import pandas as pd
import pytest

from polar_star.arsenal import (accruals_gate, asset_growth_gate,
                                average_earnings_power,
                                cash_profitability, earnings_yield_scan,
                                epv_scan, gross_profitability,
                                magic_formula, net_issuance_gate,
                                net_payout_yield)


def _hist(dossier, entries, currency="CNY"):
    """Write a synthetic models/<m>/<c>/raw/history.json."""
    raw = dossier / "raw"
    raw.mkdir(parents=True)
    (raw / "history.json").write_text(json.dumps({
        "id": "t", "market": "A", "code": "t", "currency": currency,
        "years": entries}), encoding="utf-8")


class TestEarningsYieldScan:
    def _df(self):
        return pd.DataFrame({
            "market": ["A", "A", "A"],
            "code": ["1", "2", "3"],
            "name": ["x", "y", "z"],
            "pe_ttm": [10.0, 20.0, -5.0],
            "dividend_yield": [1.0, None, 2.0],
        })

    def test_yields_and_pctl(self):
        out = earnings_yield_scan.scan_frame(self._df())
        assert out["earnings_yield"].iloc[0] == pytest.approx(10.0)
        assert out["earnings_yield"].iloc[1] == pytest.approx(5.0)
        assert pd.isna(out["earnings_yield"].iloc[2])  # loss-maker out
        assert out["cash_return"].iloc[0] == pytest.approx(11.0)
        assert out["cash_return"].iloc[1] == pytest.approx(5.0)  # NaN div=0
        assert out["ey_pctl"].iloc[0] == pytest.approx(100.0)
        assert out["ey_pctl"].iloc[1] == pytest.approx(50.0)
        assert pd.isna(out["ey_pctl"].iloc[2])

    def test_run_top_and_row(self):
        df = self._df()
        ctx = {"master": df, "snap": None, "row": df.iloc[1]}
        out = earnings_yield_scan.run(ctx, top=1)
        assert out["weapon"] == "earnings-yield-scan"
        assert "anchor" in out
        assert len(out["top"]) == 1
        assert out["top"][0]["code"] == "1"
        assert out["row"]["cash_return"] == pytest.approx(5.0)
        assert out["row"]["ey_pctl"] == pytest.approx(50.0)


class TestMagicFormula:
    def _df(self):
        return pd.DataFrame({
            "market": ["A", "A", "A", "A"],
            "code": ["1", "2", "3", "4"],
            "name": ["a", "b", "c", "d"],
            "pe_ttm": [10.0, 25.0, 20.0, -3.0],
            "roe": [25.0, 30.0, 5.0, 40.0],
        })

    def test_double_rank_order(self):
        out = magic_formula.scan_frame(self._df())
        # ey: 10/4/5/NaN -> ey_rank: 100, 33.3, 66.7, NaN
        # roe(+): 25/30/5/40 -> roc_rank: 50, 75, 25, 100
        # mf_score: 150, 108.3, 91.7, NaN -> the BALANCED row wins:
        # row2 has the best ROE, row1 the best E/P; neither leg alone
        # is sufficient — that is the Greenblatt mechanism.
        assert out["mf_rank"].iloc[0] == 1.0
        assert out["mf_rank"].iloc[1] == 2.0
        assert out["mf_rank"].iloc[2] == 3.0
        assert pd.isna(out["mf_score"].iloc[3])   # loss-maker outside
        assert pd.isna(out["mf_rank"].iloc[3])

    def test_negative_roe_outside(self):
        df = self._df()
        df.loc[1, "roe"] = -2.0
        out = magic_formula.scan_frame(df)
        assert pd.isna(out["mf_score"].iloc[1])


def _epv_snap(tmp_path):
    pd.DataFrame({
        "ticker": ["X", "Y"],
        "profit": [1.0e8, -5.0e6],
        "oneoff": [1.0e7, None],
    }).to_csv(tmp_path / "us_financials.csv", index=False)
    pd.DataFrame({
        "code": ["600000"],
        "report_date": ["2026-06-30"],
        "profit": [2.0e8],
    }).to_csv(tmp_path / "a_financials.csv", index=False)
    pd.DataFrame({
        "code": ["700"],
        "report_date": ["2026-06-30"],
        "report_type": ["2026年中报"],
        "profit": [1.0e10],
    }).to_csv(tmp_path / "hk_f10.csv", index=False)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"fx_hkdcny": 0.9}), encoding="utf-8")


class TestEpvScan:
    def _df(self):
        return pd.DataFrame({
            "market": ["US", "US", "A", "HK"],
            "code": ["X", "Y", "600000", "00700"],
            "name": ["x", "y", "a", "h"],
            "price": [90.0, 10.0, 20.0, 500.0],
            "market_cap": [1.8e9, 1.0e8, 4.0e9, 9.0e11],
        })

    def test_epv_math_exact(self, tmp_path):
        _epv_snap(tmp_path)
        out = epv_scan.scan_frame(self._df(), snap=tmp_path)
        us = out[out["code"] == "X"].iloc[0]
        # profit_adj = 1e8-1e7 = 9e7; EPV = 9e8; shares = 1.8e9/90 = 2e7
        # epv/share = 45; ratio = 45/90 = 0.5
        assert us["profit_adj"] == pytest.approx(9.0e7)
        assert us["epv_per_share"] == pytest.approx(45.0)
        assert us["epv_ratio"] == pytest.approx(0.5)
        a = out[out["code"] == "600000"].iloc[0]
        # H1 YTD annualized x2: 4e8/(0.1*4e9) = 1.0
        assert a["epv_ratio"] == pytest.approx(1.0)
        assert a["epv_basis"] == "interim_x2_proxy"
        hk = out[out["code"] == "00700"].iloc[0]
        # interim x2: 2e10 CNY -> /0.9 HKD; ratio = (2e10/0.9)/(0.1*9e11)
        assert hk["epv_ratio"] == pytest.approx(
            (2.0e10 / 0.9) / (0.1 * 9.0e11))
        assert hk["epv_basis"] == "interim_x2_proxy"
        y = out[out["code"] == "Y"].iloc[0]
        assert pd.isna(y["epv_ratio"])  # loss-maker outside

    def test_hk_annual_row_preferred(self, tmp_path):
        _epv_snap(tmp_path)
        pd.DataFrame({
            "code": ["700", "700"],
            "report_date": ["2026-06-30", "2026-03-31"],
            "report_type": ["2026年中报", "2025年年报"],
            "profit": [6.0e9, 1.0e10],
        }).to_csv(tmp_path / "hk_f10.csv", index=False)
        out = epv_scan.scan_frame(self._df(), snap=tmp_path)
        hk = out[out["code"] == "00700"].iloc[0]
        # annual wins, no x2: ratio = (1e10/0.9)/(0.1*9e11)
        assert hk["epv_basis"] == "annual"
        assert hk["epv_ratio"] == pytest.approx(
            (1.0e10 / 0.9) / (0.1 * 9.0e11))

    def test_wacc_is_a_knob(self, tmp_path):
        _epv_snap(tmp_path)
        out = epv_scan.scan_frame(self._df(), snap=tmp_path, wacc=0.05)
        us = out[out["code"] == "X"].iloc[0]
        assert us["epv_ratio"] == pytest.approx(1.0)  # halves the hurdle

    def test_a_share_ytd_annualization(self, tmp_path):
        """A rows are cumulative YTD: factor = 12/report month."""
        _epv_snap(tmp_path)
        pd.DataFrame({
            "code": ["600000", "600001", "600002", "600003"],
            "report_date": ["2026-06-30", "2026-03-31",
                            "2025-12-31", "2026-05-15"],
            "profit": [2.0e8, 5.0e7, 3.0e8, 1.0e8],
        }).to_csv(tmp_path / "a_financials.csv", index=False)
        df = pd.DataFrame({
            "market": ["A"] * 4,
            "code": ["600000", "600001", "600002", "600003"],
            "name": list("abcd"),
            "price": [10.0] * 4,
            "market_cap": [4.0e9] * 4,
        })
        out = epv_scan.scan_frame(df, snap=tmp_path)
        got = {r["code"]: r for r in out.to_dict("records")}
        # H1 x2: 4e8/(0.1*4e9) = 1.0
        assert got["600000"]["epv_ratio"] == pytest.approx(1.0)
        assert got["600000"]["epv_basis"] == "interim_x2_proxy"
        # Q1 x4: 2e8/(0.1*4e9) = 0.5
        assert got["600001"]["epv_ratio"] == pytest.approx(0.5)
        assert got["600001"]["epv_basis"] == "interim_x4_proxy"
        # FY x1: 3e8/(0.1*4e9) = 0.75
        assert got["600002"]["epv_ratio"] == pytest.approx(0.75)
        assert got["600002"]["epv_basis"] == "annual"
        # non-quarter-end -> gap, never fabricated
        assert pd.isna(got["600003"]["epv_ratio"])
        assert got["600003"]["epv_basis"].startswith("data_gap")


class TestGrossProfitability:
    def _df(self):
        return pd.DataFrame({
            "market": ["US", "US", "A", "HK"],
            "code": ["X", "Y", "600000", "00700"],
            "name": ["x", "y", "a", "h"],
        })

    def test_us_only_with_declared_gaps(self, tmp_path):
        pd.DataFrame({
            "ticker": ["X", "Y"],
            "gross_profit": [4.0e8, 1.0e8],
            "assets": [1.0e9, 2.0e9],
        }).to_csv(tmp_path / "us_financials.csv", index=False)
        out = gross_profitability.scan_frame(self._df(), snap=tmp_path)
        assert out["gp_ratio"].iloc[0] == pytest.approx(0.4)
        assert out["gp_ratio"].iloc[1] == pytest.approx(0.05)
        assert out["gp_pctl"].iloc[0] == pytest.approx(100.0)
        assert out["gp_pctl"].iloc[1] == pytest.approx(50.0)
        assert pd.isna(out["gp_ratio"].iloc[2])
        assert out["data_gap"].iloc[2] == "no total-assets field (A)"
        assert out["data_gap"].iloc[3] == "no balance sheet (HK)"


class TestCashProfitability:
    def test_us_only_with_declared_gaps(self, tmp_path):
        pd.DataFrame({
            "ticker": ["X", "Y"],
            "ocf": [2.0e8, 5.0e7],
            "assets": [1.0e9, 2.0e9],
        }).to_csv(tmp_path / "us_financials.csv", index=False)
        df = pd.DataFrame({
            "market": ["US", "US", "A"],
            "code": ["X", "Y", "600000"],
            "name": ["x", "y", "a"],
        })
        out = cash_profitability.scan_frame(df, snap=tmp_path)
        assert out["cop_ratio"].iloc[0] == pytest.approx(0.2)
        assert out["cop_ratio"].iloc[1] == pytest.approx(0.025)
        assert out["cop_pctl"].iloc[0] == pytest.approx(100.0)
        assert pd.isna(out["cop_ratio"].iloc[2])
        assert out["data_gap"].iloc[2] == "no total-assets field (A)"


class TestAccrualsGate:
    def _df(self):
        return pd.DataFrame({
            "market": ["A", "A", "A", "A", "A", "US"],
            "code": ["1", "2", "3", "4", "5", "X"],
            "name": ["a", "b", "c", "d", "e", "x"],
            "cash_conversion": [120.0, 110.0, 100.0, 90.0, 80.0, None],
        })

    def test_gap_pctl_and_veto(self, tmp_path):
        pd.DataFrame({
            "ticker": ["X"],
            "profit": [1.0e8], "ocf": [8.0e7], "assets": [5.0e8],
        }).to_csv(tmp_path / "us_financials.csv", index=False)
        out = accruals_gate.scan_frame(self._df(), snap=tmp_path)
        # accrual_gap = 1 - cc/100: -0.2, -0.1, 0, 0.1, 0.2
        assert out["accrual_gap"].iloc[0] == pytest.approx(-0.2)
        assert out["accrual_gap"].iloc[4] == pytest.approx(0.2)
        # within-A pctl 20/40/60/80/100 -> veto at >=80: rows 4 and 5
        assert not out["accruals_veto"].iloc[0]
        assert not out["accruals_veto"].iloc[2]
        assert out["accruals_veto"].iloc[3]
        assert out["accruals_veto"].iloc[4]
        # US canonical tata = (1e8-8e7)/5e8 = 0.04
        x = out[out["code"] == "X"].iloc[0]
        assert x["tata"] == pytest.approx(0.04)
        assert pd.isna(x["accrual_gap"])   # no cash_conversion
        assert not x["accruals_veto"]      # NaN pctl never vetoes

    def test_run_counts(self, tmp_path):
        pd.DataFrame({
            "ticker": ["X"],
            "profit": [1.0e8], "ocf": [8.0e7], "assets": [5.0e8],
        }).to_csv(tmp_path / "us_financials.csv", index=False)
        out = accruals_gate.run({"master": self._df(), "snap": tmp_path})
        assert out["vetoed"] == 2
        assert out["scored"] == 5


class TestNetIssuanceGate:
    def _df(self):
        return pd.DataFrame({
            "market": ["A", "A", "A", "US"],
            "code": ["1", "2", "3", "X"],
            "name": ["a", "b", "c", "x"],
            "dilution_flag": [1.0, 0.0, 0.0, None],
            "buyback_active": [0.0, 1.0, 0.0, None],
        })

    def test_veto_bonus_gap(self):
        out = net_issuance_gate.scan_frame(self._df())
        assert out["net_issuer"].iloc[0]
        assert out["net_issuance_veto"].iloc[0]
        assert out["repurchaser"].iloc[1]
        assert out["issuance_score"].iloc[0] == -1.0
        assert out["issuance_score"].iloc[1] == 1.0
        assert out["issuance_score"].iloc[2] == 0.0
        assert out["issuance_pctl"].iloc[1] == pytest.approx(100.0)
        assert pd.isna(out["issuance_score"].iloc[3])
        assert out["data_gap"].iloc[3] == "no issuance events"
        assert out["data_gap"].iloc[0] is None

    def test_run_counts(self):
        out = net_issuance_gate.run({"master": self._df(), "snap": None})
        assert out["net_issuers"] == 1
        assert out["repurchasers"] == 1
        assert out["scored"] == 3


class TestNetPayoutYield:
    def _df(self):
        return pd.DataFrame({
            "market": ["A", "A", "HK"],
            "code": ["600000", "600001", "00700"],
            "name": ["a", "b", "h"],
            "dividend_yield": [2.0, 1.0, 4.0],
            "market_cap": [1.0e10, 2.0e10, 9.0e11],
        })

    def test_lower_bound_sums(self, tmp_path):
        snap = tmp_path / "20261012"
        snap.mkdir()
        pd.DataFrame({
            "code": ["600000", "600000", "600001"],
            "name": ["a", "a", "b"],
            "amount_yuan": [6.0e7, 4.0e7, 5.0e8],
            "shares": [1, 1, 1],
            "announce_date": ["2026-05-01", "2026-08-01", "2024-01-01"],
        }).to_csv(snap / "a_buybacks.csv", index=False)
        out = net_payout_yield.scan_frame(self._df(), snap=snap)
        # 600000: (6e7+4e7)/1e10*100 = 1.0 -> payout_lb = 3.0
        assert out["buyback_yield"].iloc[0] == pytest.approx(1.0)
        assert out["payout_yield_lb"].iloc[0] == pytest.approx(3.0)
        # 600001: 2024-01-01 outside the 12m window -> 0 -> payout 1.0
        assert out["buyback_yield"].iloc[1] == pytest.approx(0.0)
        assert out["payout_yield_lb"].iloc[1] == pytest.approx(1.0)
        # HK: dividend leg only, lower-bound basis declared
        assert pd.isna(out["buyback_yield"].iloc[2])
        assert out["payout_yield_lb"].iloc[2] == pytest.approx(4.0)
        assert (out["payout_basis"].iloc[2]
                == "dividend_only_no_buyback_source")
        assert (out["payout_basis"].iloc[0]
                == "dividend+buyback_12m_announcements")


class TestAverageEarningsPower:
    def test_exact_math(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2018 + i, "net_income": 1.0e8}
                   for i in range(8)]
        _hist(mdir / "a" / "600000", entries)
        row = pd.Series({"market": "A", "code": "600000",
                         "market_cap": 2.1e9, "pe_ttm": 15.0})
        out = average_earnings_power.run({"row": row, "snap": None},
                                         models_dir=mdir)
        r = out["row"]
        assert r["years_used"] == 8
        assert r["avg_profit"] == pytest.approx(1.0e8)
        assert r["ae_pe"] == pytest.approx(21.0)  # 2.1e9 / 1e8
        assert r["cycle_adjustment"] == pytest.approx(21.0 / 15.0)

    def test_window_caps_at_10_years(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2014 + i, "net_income": float(i) * 1e8}
                   for i in range(12)]  # 0..11e8; last 10 = 2e8..11e8
        _hist(mdir / "a" / "600000", entries)
        row = pd.Series({"market": "A", "code": "600000",
                         "market_cap": 6.5e9, "pe_ttm": 10.0})
        out = average_earnings_power.run({"row": row, "snap": None},
                                         models_dir=mdir)
        r = out["row"]
        avg = sum(range(2, 12)) / 10 * 1e8  # 6.5e8
        assert r["years_used"] == 10
        assert r["avg_profit"] == pytest.approx(avg)
        assert r["ae_pe"] == pytest.approx(6.5e9 / avg)

    def test_insufficient_history_is_gap(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2023 + i, "net_income": 1.0e8}
                   for i in range(3)]
        _hist(mdir / "a" / "600000", entries)
        row = pd.Series({"market": "A", "code": "600000",
                         "market_cap": 1.0e9, "pe_ttm": 10.0})
        out = average_earnings_power.run({"row": row, "snap": None},
                                         models_dir=mdir)
        assert "data_gap" in out["row"]
        assert out["row"]["years_used"] == 3

    def test_missing_dossier_is_gap(self, tmp_path):
        row = pd.Series({"market": "A", "code": "999999",
                         "market_cap": 1.0e9, "pe_ttm": 10.0})
        out = average_earnings_power.run(
            {"row": row, "snap": None}, models_dir=tmp_path / "nope")
        assert "data_gap" in out["row"]

    def test_hk_currency_conversion(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2019 + i, "net_income": 1.0e10}
                   for i in range(7)]
        _hist(mdir / "hk" / "00700", entries, currency="CNY")
        snap = tmp_path / "20261012"
        snap.mkdir()
        (snap / "manifest.json").write_text(
            json.dumps({"fx_hkdcny": 0.9}), encoding="utf-8")
        row = pd.Series({"market": "HK", "code": "00700",
                         "market_cap": 9.0e10, "pe_ttm": 9.0})
        out = average_earnings_power.run({"row": row, "snap": snap},
                                         models_dir=mdir)
        r = out["row"]
        # avg 1e10 CNY -> 1e10/0.9 HKD; ae_pe = 9e10 / (1e10/0.9) = 8.1
        assert r["ae_pe"] == pytest.approx(8.1)
        assert r["cycle_adjustment"] == pytest.approx(0.9)


class TestAssetGrowthGate:
    def test_cross_section_is_declared_gap(self):
        df = pd.DataFrame({"market": ["A", "HK", "US"],
                           "code": ["1", "00700", "X"]})
        out = asset_growth_gate.scan_frame(df)
        assert out["asset_growth"].isna().all()
        assert out["data_gap"].iloc[0].startswith("no total-assets field")
        assert out["data_gap"].iloc[1] == ("no balance-sheet source "
                                           "in snapshot")
        assert out["data_gap"].iloc[2].endswith("no assets_prev")

    def test_deep_gap_when_no_assets_series(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2023 + i, "net_income": 1.0e8}
                   for i in range(3)]
        _hist(mdir / "a" / "600000", entries)
        ctx = {"master": pd.DataFrame({"market": ["A"],
                                       "code": ["600000"]}),
               "row": pd.Series({"market": "A", "code": "600000"})}
        out = asset_growth_gate.run(ctx, models_dir=mdir)
        assert out["row"]["asset_growth"] is None
        assert out["row"]["asset_growth_veto"] is None
        assert "data_gap" in out["row"]

    def test_deep_growth_uses_last_two_years(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2023, "assets": 1.0e9},
                   {"fy": 2024, "assets": 1.6e9},
                   {"fy": 2025, "assets": 1.7e9}]
        _hist(mdir / "us" / "XYZ", entries)
        ctx = {"master": pd.DataFrame({"market": ["US"], "code": ["XYZ"]}),
               "row": pd.Series({"market": "US", "code": "XYZ"})}
        out = asset_growth_gate.run(ctx, models_dir=mdir)
        r = out["row"]
        # last two years: 1.6e9 -> 1.7e9 = +6.25% < 50% -> no veto
        assert r["asset_growth"] == pytest.approx(6.25)
        assert r["asset_growth_veto"] is False
        assert r["years_used"] == 3

    def test_deep_veto_threshold(self, tmp_path):
        mdir = tmp_path / "models"
        entries = [{"fy": 2024, "assets": 1.0e9},
                   {"fy": 2025, "assets": 1.6e9}]
        _hist(mdir / "us" / "XYZ", entries)
        ctx = {"master": pd.DataFrame({"market": ["US"], "code": ["XYZ"]}),
               "row": pd.Series({"market": "US", "code": "XYZ"})}
        out = asset_growth_gate.run(ctx, models_dir=mdir)
        assert out["row"]["asset_growth"] == pytest.approx(60.0)
        assert out["row"]["asset_growth_veto"] is True
        out70 = asset_growth_gate.run(ctx, ag_veto_pct=70.0,
                                      models_dir=mdir)
        assert out70["row"]["asset_growth_veto"] is False
