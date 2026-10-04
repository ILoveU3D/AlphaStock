"""Tests for value_genie.model.history parsers (network monkeypatched)."""

import pytest

from value_genie.model import history as mh


def _tag(rows, unit="USD"):
    """rows: [(fy, val)] — builds one companyfacts tag entry."""
    return {"units": {unit: [
        {"fy": fy, "fp": "FY", "form": "10-K", "filed": f"{fy+1}-02-01",
         "start": f"{fy}-01-01", "end": f"{fy}-12-31", "val": val}
        for fy, val in rows]}}


def _facts_payload(gaap_tags, dei_tags=None):
    """companyfacts-shaped dict: {facts: {us-gaap: {...}, dei: {...}}}."""
    facts = {"us-gaap": gaap_tags}
    if dei_tags:
        facts["dei"] = dei_tags
    return {"entityName": "Test Co", "facts": facts}


class TestUS:
    def test_parse_multi_year(self, monkeypatch):
        payload = _facts_payload({
            "Revenues": _tag([(2022, 90e9), (2023, 100e9), (2024, 110e9)]),
            "OperatingIncomeLoss": _tag([(2022, 18e9), (2023, 20e9),
                                         (2024, 22e9)]),
            "NetIncomeLoss": _tag([(2024, 15e9)]),
            "NetCashProvidedByUsedInOperatingActivities":
                _tag([(2024, 19e9)]),
            "PaymentsToAcquirePropertyPlantAndEquipment":
                _tag([(2024, 5e9)]),
            "DepreciationDepletionAndAmortization": _tag([(2024, 3e9)]),
            "CashAndCashEquivalentsAtCarryingValue": _tag([(2024, 30e9)]),
            "LongTermDebt": _tag([(2024, 10e9)]),
        }, dei_tags={
            # shares fallback tag lives in the dei namespace, unit "shares"
            "EntityCommonStockSharesOutstanding":
                _tag([(2024, 1e9)], unit="shares"),
        })
        monkeypatch.setattr(mh, "_us_facts", lambda cik: payload)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert h is not None
        assert h["source"] == "sec_companyfacts"
        assert h["currency"] == "USD"
        assert h["name"] == "Test Co"
        assert [y["fy"] for y in h["years"]] == [2022, 2023, 2024]
        y24 = h["years"][-1]
        assert y24["revenue"] == 110e9
        assert y24["ebit"] == 22e9
        assert y24["capex"] == 5e9
        assert y24["debt"] == 10e9
        assert y24["shares"] == 1e9

    def test_quarterly_forms_excluded(self, monkeypatch):
        rev = _tag([(2024, 100e9)])
        rev["units"]["USD"].append(
            {"fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-05-01",
             "start": "2024-01-01", "end": "2024-03-31", "val": 25e9})
        monkeypatch.setattr(mh, "_us_facts",
                            lambda cik: _facts_payload({"Revenues": rev}))
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert len(h["years"]) == 1
        assert h["years"][0]["revenue"] == 100e9

    def test_fail_closed_when_no_revenue(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_facts",
                            lambda cik: _facts_payload({"Assets": _tag(
                                [(2024, 1e9)])}))
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        assert mh.fetch_history_us("TEST") is None

    def test_fail_closed_when_facts_request_fails(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_facts", lambda cik: None)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        assert mh.fetch_history_us("TEST") is None

    def test_no_cik_returns_none(self, monkeypatch):
        monkeypatch.setattr(mh, "_us_cik", lambda code: None)
        assert mh.fetch_history_us("TEST") is None

    def test_fallback_tags_merged_across_years(self, monkeypatch):
        # PYPL case (2026-10-02): "Revenues" stops at 2019, the modern
        # contract tag covers 2020+ — first-hit-wins would truncate the
        # history to old years. Merge must cover both.
        payload = _facts_payload({
            "Revenues": _tag([(2018, 15e9), (2019, 17e9)]),
            "RevenueFromContractWithCustomerExcludingAssessedTax":
                _tag([(2023, 28e9), (2024, 31e9)]),
        })
        monkeypatch.setattr(mh, "_us_facts", lambda cik: payload)
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert h is not None
        assert [y["fy"] for y in h["years"]] == [2018, 2019, 2023, 2024]
        assert h["years"][-1]["revenue"] == 31e9

    def test_same_fy_same_filed_latest_period_wins(self, monkeypatch):
        # ZM case (2026-10-04): within one 10-K the primary year and its
        # comparatives all carry the filing's fy + filed date; the units
        # array serves them oldest-period-first. First-wins on filed ties
        # resolved every fy to the OLDEST comparative, so the latest
        # fiscal year went missing (history stuck at FYE 2024-01 while
        # the FY2026 10-K was already filed). The later period end must
        # win the tie.
        rev = {"units": {"USD": [
            {"fy": 2026, "fp": "FY", "form": "10-K",
             "filed": "2026-02-27", "start": "2023-02-01",
             "end": "2024-01-31", "val": 4527.2e6},
            {"fy": 2026, "fp": "FY", "form": "10-K",
             "filed": "2026-02-27", "start": "2024-02-01",
             "end": "2025-01-31", "val": 4665.4e6},
            {"fy": 2026, "fp": "FY", "form": "10-K",
             "filed": "2026-02-27", "start": "2025-02-01",
             "end": "2026-01-31", "val": 4868.8e6},
        ]}}
        monkeypatch.setattr(mh, "_us_facts",
                            lambda cik: _facts_payload({"Revenues": rev}))
        monkeypatch.setattr(mh, "_us_cik", lambda code: 12345)
        h = mh.fetch_history_us("TEST")
        assert h is not None
        assert len(h["years"]) == 1
        assert h["years"][-1]["revenue"] == 4868.8e6


class TestParseHelpers:
    def test_num_and_report_date(self):
        assert mh._num("1234.5") == 1234.5
        assert mh._num("-") is None
        assert mh._num(None) is None


class TestA:
    def test_parse_from_rows(self, monkeypatch):
        # 字段名以探针定稿为准; fixture 用映射常量的值构造, 不硬编码
        income = [{"REPORTDATE": "2024-12-31",
                   "SECURITY_NAME_ABBR": "测试电力",
                   mh.A_INCOME_FIELDS["revenue"]: 8.0e10,
                   mh.A_INCOME_FIELDS["net_income"]: 2.6e10}]
        cashflow = [{"REPORT_DATE": "2024-12-31",
                     mh.A_CASHFLOW_FIELDS["ocf"]: 4.0e10,
                     mh.A_CASHFLOW_FIELDS["capex"]: 6.0e9}]
        balance = [{"REPORT_DATE": "2024-12-31",
                    mh.A_BALANCE_FIELDS["cash"]: 5.0e10,
                    mh.A_BALANCE_FIELDS["debt"]: 1.0e10}]
        monkeypatch.setattr(mh, "_a_report",
                            lambda report, secucode, rd:
                            {"RPT_LICO_FN_CPD": income,
                             "RPT_DMSK_FN_CASHFLOW": cashflow,
                             "RPT_DMSK_FN_BALANCE": balance}.get(report))
        h = mh.fetch_history_a("600900")
        assert h is not None and h["currency"] == "CNY"
        assert h["source"] == "eastmoney_datacenter_f10"
        y = h["years"][-1]
        assert y["revenue"] == 8.0e10
        assert y["net_income"] == 2.6e10
        assert y["ocf"] == 4.0e10
        assert y["capex"] == 6.0e9
        assert y["cash"] == 5.0e10
        assert y["debt"] == 1.0e10
        assert any("ebit" in g or "shares" in g for g in h["gaps"])

    def test_empty_report_is_legal(self, monkeypatch):
        monkeypatch.setattr(mh, "_a_report",
                            lambda report, secucode, rd: None)
        assert mh.fetch_history_a("600900") is None


class TestHK:
    def test_parse_mainindicator_dec_fy(self, monkeypatch):
        rows = [{"REPORT_DATE": "2024-12-31 00:00:00",
                 "REPORT_TYPE": "2024年年报",
                 "FISCAL_YEAR": "12-31",
                 "SECURITY_NAME_ABBR": "测试银行",
                 mh.HK_MAIN_FIELDS["revenue"]: 2.0e11,
                 mh.HK_MAIN_FIELDS["net_income"]: 7.0e10},
                {"REPORT_DATE": "2024-06-30 00:00:00",  # 中报必须被跳过
                 "REPORT_TYPE": "2024年中报",
                 mh.HK_MAIN_FIELDS["revenue"]: 9.0e10}]
        monkeypatch.setattr(mh, "_hk_main", lambda secucode: rows)
        h = mh.fetch_history_hk("00998")
        assert h is not None and h["currency"] == "CNY"
        assert h["source"] == "eastmoney_hkf10_mainindicator"
        assert len(h["years"]) == 1
        assert h["years"][-1]["revenue"] == 2.0e11
        assert h["years"][-1]["net_income"] == 7.0e10
        assert any("capex" in g for g in h["gaps"])

    def test_jun_fy_interim_is_not_annual(self, monkeypatch):
        # 03306 case (2026-10-04): 6-30 财年公司的 12-31 行是中报 —
        # 旧 "只留 12-31" 过滤把它们当年报吞入。年报行必须按
        # REPORT_TYPE 选出, fy 取年报期止年份。
        rows = [{"REPORT_DATE": "2025-12-31 00:00:00",
                 "REPORT_TYPE": "2025年中报",
                 mh.HK_MAIN_FIELDS["revenue"]: 3.4e9},
                {"REPORT_DATE": "2026-06-30 00:00:00",
                 "REPORT_TYPE": "2025年年报",
                 "FISCAL_YEAR": "6-30",
                 mh.HK_MAIN_FIELDS["revenue"]: 6.0e9,
                 mh.HK_MAIN_FIELDS["net_income"]: 1.0e9}]
        monkeypatch.setattr(mh, "_hk_main", lambda secucode: rows)
        h = mh.fetch_history_hk("03306")
        assert h is not None
        assert [y["fy"] for y in h["years"]] == [2026]
        assert h["years"][-1]["revenue"] == 6.0e9
        assert any("6-30" in g for g in h["gaps"])

    def test_mar_fy_not_starved(self, monkeypatch):
        # 03998 case (2026-10-04): 3-31 财年公司没有 12-31 行 —
        # 旧过滤返回空史 (fail-closed 假阴性)。按 REPORT_TYPE 选行后可取。
        rows = [{"REPORT_DATE": "2025-09-30 00:00:00",
                 "REPORT_TYPE": "2025年中报",
                 mh.HK_MAIN_FIELDS["revenue"]: 1.0e10},
                {"REPORT_DATE": "2026-03-31 00:00:00",
                 "REPORT_TYPE": "2025年年报",
                 "FISCAL_YEAR": "3-31",
                 mh.HK_MAIN_FIELDS["revenue"]: 2.3e10,
                 mh.HK_MAIN_FIELDS["net_income"]: 3.0e9}]
        monkeypatch.setattr(mh, "_hk_main", lambda secucode: rows)
        h = mh.fetch_history_hk("03998")
        assert h is not None
        assert [y["fy"] for y in h["years"]] == [2026]
        assert h["years"][-1]["revenue"] == 2.3e10

    def test_empty_is_fail_closed(self, monkeypatch):
        monkeypatch.setattr(mh, "_hk_main", lambda secucode: None)
        assert mh.fetch_history_hk("00998") is None
