"""Tests for value_genie.model.history parsers (network monkeypatched)."""

import pytest

from value_genie.model import history as mh


def _concept_payload(fy_vals, unit="USD"):
    """fy_vals: [(fy, val)] — builds a companyconcept-shaped dict."""
    return {"entityName": "Test Co", "units": {unit: [
        {"fy": fy, "fp": "FY", "form": "10-K", "filed": f"{fy+1}-02-01",
         "start": f"{fy}-01-01", "end": f"{fy}-12-31", "val": val}
        for fy, val in fy_vals]}}


class TestUS:
    def test_parse_multi_year(self, monkeypatch):
        payloads = {
            "Revenues": _concept_payload([(2022, 90e9), (2023, 100e9),
                                          (2024, 110e9)]),
            "OperatingIncomeLoss": _concept_payload(
                [(2022, 18e9), (2023, 20e9), (2024, 22e9)]),
            "NetIncomeLoss": _concept_payload([(2024, 15e9)]),
            "NetCashProvidedByUsedInOperatingActivities":
                _concept_payload([(2024, 19e9)]),
            "PaymentsToAcquirePropertyPlantAndEquipment":
                _concept_payload([(2024, 5e9)]),
            "DepreciationDepletionAndAmortization":
                _concept_payload([(2024, 3e9)]),
            "CashAndCashEquivalentsAtCarryingValue":
                _concept_payload([(2024, 30e9)]),
            "LongTermDebt": _concept_payload([(2024, 10e9)]),
            "CommonStockSharesOutstanding":
                _concept_payload([(2024, 1e9)]),
        }
        monkeypatch.setattr(mh, "_us_concept",
                            lambda cik, concept: payloads.get(concept))
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert h is not None
        assert h["source"] == "sec_companyconcept"
        assert h["currency"] == "USD"
        assert [y["fy"] for y in h["years"]] == [2022, 2023, 2024]
        y24 = h["years"][-1]
        assert y24["revenue"] == 110e9
        assert y24["ebit"] == 22e9
        assert y24["capex"] == 5e9
        assert y24["debt"] == 10e9
        assert y24["shares"] == 1e9

    def test_quarterly_forms_excluded(self, monkeypatch):
        p = _concept_payload([(2024, 100e9)])
        p["units"]["USD"].append(
            {"fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-05-01",
             "start": "2024-01-01", "end": "2024-03-31", "val": 25e9})
        monkeypatch.setattr(mh, "_us_concept",
                            lambda cik, concept:
                            p if concept == "Revenues" else None)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert len(h["years"]) == 1
        assert h["years"][0]["revenue"] == 100e9

    def test_fail_closed_when_no_revenue(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_concept", lambda cik, concept: None)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        assert mh.fetch_history_us("TEST") is None

    def test_no_cik_returns_none(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_cik", lambda code: None)
        assert mh.fetch_history_us("TEST") is None


class TestParseHelpers:
    def test_num_and_report_date(self):
        assert mh._num("1234.5") == 1234.5
        assert mh._num("-") is None
        assert mh._num(None) is None
