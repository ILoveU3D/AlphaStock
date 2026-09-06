"""Tests for annual-basis cashflow factors (fcf_yield /
borrowed_dividend / capex_to_ocf) and their pipeline integration."""

import numpy as np
import pandas as pd
import pytest

from value_genie.fetch import pipeline as pl
from value_genie.strategy.factors import PILLAR_FACTORS


def _master():
    return pd.DataFrame({
        "market": ["A", "HK", "US"],
        "code": ["600519", "06831", "PDD"],
        "market_cap": [100.0, 100.0, 100.0],
        "ocf_yield": [5.0, 5.0, 5.0],
    })


def _annual():
    return pd.DataFrame({
        "market": ["A", "HK", "US"],
        "code": ["600519", "06831", "PDD"],
        "ocf": [20.0, 20.0, 20.0],
        "capex": [5.0, 5.0, 5.0],
        "div_paid": [16.0, 16.0, 16.0],
        "net_fin_cf": [10.0, 10.0, 10.0],
    })


class TestAddCashflowFactors:
    def test_fcf_yield_same_currency_and_hk_fx(self):
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert out.loc[out["market"] == "A", "fcf_yield"].iloc[0] \
            == pytest.approx(15.0)
        assert out.loc[out["market"] == "HK", "fcf_yield"].iloc[0] \
            == pytest.approx(15.0 / 0.8)
        assert out.loc[out["market"] == "US", "fcf_yield"].iloc[0] \
            == pytest.approx(15.0)

    def test_ocf_yield_rebased_annual(self):
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert out.loc[out["market"] == "A", "ocf_yield"].iloc[0] \
            == pytest.approx(20.0)
        assert out.loc[out["market"] == "HK", "ocf_yield"].iloc[0] \
            == pytest.approx(25.0)

    def test_borrowed_dividend_true_positive(self):
        # div 16 > fcf 15, > ocf*0.5 = 10, net_fin 10 > 0
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert (out["borrowed_dividend"] == 1).all()

    def test_capex_borrower_not_flagged(self):
        # borrowing for capex with a small dividend stays clean
        ann = _annual()
        ann.loc[ann["market"] == "A", "capex"] = 18.0   # fcf = 2
        ann.loc[ann["market"] == "A", "div_paid"] = 4.0  # < ocf*0.5
        ann.loc[ann["market"] == "A", "net_fin_cf"] = 50.0
        out = pl.add_cashflow_factors(_master(), 0.8, ann)
        assert out.loc[out["market"] == "A", "borrowed_dividend"].iloc[0] == 0

    def test_negative_financing_not_flagged(self):
        ann = _annual()
        ann.loc[ann["market"] == "US", "net_fin_cf"] = -10.0
        out = pl.add_cashflow_factors(_master(), 0.8, ann)
        assert out.loc[out["market"] == "US", "borrowed_dividend"].iloc[0] == 0

    def test_missing_data_is_innocent(self):
        ann = _annual()
        ann.loc[ann["market"] == "US",
                ["capex", "div_paid", "net_fin_cf"]] = np.nan
        out = pl.add_cashflow_factors(_master(), 0.8, ann)
        assert out.loc[out["market"] == "US", "borrowed_dividend"].iloc[0] == 0
        assert pd.isna(out.loc[out["market"] == "US", "fcf_yield"].iloc[0])

    def test_empty_annual_passes_through(self):
        out = pl.add_cashflow_factors(_master(), 0.8, pd.DataFrame())
        assert (out["borrowed_dividend"] == 0).all()
        assert pd.isna(out["fcf_yield"]).all()
        assert (out["ocf_yield"] == 5.0).all()  # interim untouched

    def test_capex_to_ocf(self):
        out = pl.add_cashflow_factors(_master(), 0.8, _annual())
        assert out.loc[0, "capex_to_ocf"] == pytest.approx(0.25)


class TestLoadAnnualCashflows:
    def test_joins_all_three_sources(self, tmp_path):
        pd.DataFrame({"code": ["600519"], "report_date": ["2025-12-31"],
                      "ocf": [100.0], "capex": [20.0],
                      "net_fin_cf": [-5.0]}
                     ).to_csv(tmp_path / "a_cashflow_annual.csv", index=False)
        pd.DataFrame({"code": ["600519"], "fy": ["2025"], "div_paid": [65.0]}
                     ).to_csv(tmp_path / "a_dividends.csv", index=False)
        pd.DataFrame({"code": ["06831"], "report_date": ["2025-12-31"],
                      "ocf": [50.0], "capex": [10.0], "div_paid": [8.0],
                      "net_fin_cf": [2.0]}
                     ).to_csv(tmp_path / "hk_cashflow.csv", index=False)
        pd.DataFrame({"ticker": ["PDD"], "rev": [1.0], "ocf": [200.0],
                      "capex": [40.0], "div_paid": [0.0],
                      "net_fin_cf": [30.0]}
                     ).to_csv(tmp_path / "us_financials.csv", index=False)
        out = pl.load_annual_cashflows(tmp_path)
        a = out[out["market"] == "A"].iloc[0]
        assert a["code"] == "600519" and a["div_paid"] == 65.0
        hk = out[out["market"] == "HK"].iloc[0]
        assert hk["code"] == "06831" and hk["div_paid"] == 8.0
        us = out[out["market"] == "US"].iloc[0]
        assert us["code"] == "PDD" and us["capex"] == 40.0

    def test_empty_when_no_files(self, tmp_path):
        assert pl.load_annual_cashflows(tmp_path).empty


class TestMasterIntegration:
    def test_columns_registered(self):
        assert {"fcf_yield", "borrowed_dividend", "capex_to_ocf"} \
            <= set(pl.MASTER_COLUMNS)
        assert ("fcf_yield", 1) in PILLAR_FACTORS["cashflow"]

    def test_build_master_carries_factors(self, tmp_path):
        pd.DataFrame({"code": ["600519"], "fy": ["2025"],
                      "div_paid": [16.0]}
                     ).to_csv(tmp_path / "a_dividends.csv", index=False)
        pd.DataFrame({"code": ["600519"], "report_date": ["2025-12-31"],
                      "ocf": [20.0], "capex": [5.0], "net_fin_cf": [10.0]}
                     ).to_csv(tmp_path / "a_cashflow_annual.csv", index=False)
        cands = {"A": pd.DataFrame({
            "market": ["A"], "code": ["600519"], "name": ["贵州茅台"],
            "price": [1500.0], "market_cap": [100.0], "pe_ttm": [20.0],
        })}
        master = pl.build_master(cands, tmp_path, None, None)
        row = master.iloc[0]
        assert row["fcf_yield"] == pytest.approx(15.0)
        assert row["borrowed_dividend"] == 1
        assert row["capex_to_ocf"] == pytest.approx(0.25)
