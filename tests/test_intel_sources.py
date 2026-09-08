"""Tests for value_genie.intel source registration + datacenter
fetchers (all network mocked)."""

from value_genie.strategy.registry import get_sources, list_sources


def test_import_intel_alone_extends_eastmoney():
    """Importing intel must be order-safe: intel/__init__ imports fetch
    first so the eastmoney entry exists before capabilities extend."""
    import value_genie.intel  # noqa: F401 — deliberately no fetch import
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert "events:A" in ds.capabilities
    assert "announce:A" in ds.capabilities
    assert [s.id for s in get_sources("events", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("announce", "A")] == ["eastmoney"]


def test_registration_is_idempotent():
    import value_genie.intel  # noqa: F401
    import value_genie.intel.sources as src
    src._register_intel_sources()   # second call must not duplicate caps
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert ds.capabilities.count("events:A") == 1


# ---------------------------------------------------------------------------
# dc_report paging helper (network mocked at the DC singleton)
# ---------------------------------------------------------------------------
import pandas as pd
import pytest

from value_genie.intel import _dc


def _dc_json(rows, count=None, pages=1):
    return {"result": {"count": count if count is not None else len(rows),
                       "pages": pages, "data": rows}}


class TestDcReport:
    def test_pages_and_merges(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params)
            if params["pageNumber"] == 1:
                return _dc_json([{"SECURITY_CODE": "600519"}],
                                count=700, pages=2)
            return _dc_json([{"SECURITY_CODE": "601318"}],
                            count=700, pages=2)

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        df = _dc.dc_report("RPT_TEST", ['(FREE_DATE>="2026-09-08")'])
        assert len(df) == 2
        assert len(calls) == 2
        assert calls[0]["filter"] == '(FREE_DATE>="2026-09-08")'
        assert calls[0]["reportName"] == "RPT_TEST"
        assert calls[0]["sortColumns"] == "SECURITY_CODE"

    def test_empty_window_returns_empty_df(self, monkeypatch):
        monkeypatch.setattr(
            _dc.DC, "get_json",
            lambda url, params=None, **kw: _dc_json([]))
        assert _dc.dc_report("RPT_TEST", []).empty

    def test_transport_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            _dc.DC, "get_json", lambda url, params=None, **kw: None)
        assert _dc.dc_report("RPT_TEST", []) is None

    def test_report_error_returns_none(self, monkeypatch):
        # "报表配置不存在"-shaped: HTTP 200 + success:false + result null
        monkeypatch.setattr(
            _dc.DC, "get_json",
            lambda url, params=None, **kw: {"success": False,
                                            "result": None})
        assert _dc.dc_report("RPT_TEST", []) is None

    def test_sort_columns_omitted_when_none(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([{"SCODE": "600519"}])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        _dc.dc_report("RPTA_WEB_GPHG", [], sort_columns=None)
        assert "sortColumns" not in seen    # probe rule: GPHG breaks on sort

    def test_code_col_prefers_security_code(self):
        df = pd.DataFrame({"SECURITY_CODE": ["600519"], "SCODE": ["x"]})
        assert list(_dc.code_col(df)) == ["600519"]
        df2 = pd.DataFrame({"SCODE": ["600519"]})
        assert list(_dc.code_col(df2)) == ["600519"]

    def test_name_col_tolerates_missing(self):
        df = pd.DataFrame({"SNAME": ["茅台"]})
        assert list(_dc.name_col(df)) == ["茅台"]
        assert _dc.name_col(pd.DataFrame({"X": [1]})) == ""

    def test_norm_dates(self):
        df = pd.DataFrame({"d": ["2026-09-12 00:00:00"], "x": [1]})
        out = _dc.norm_dates(df, "d")
        assert out["d"].iloc[0] == "2026-09-12"


# ---------------------------------------------------------------------------
# A-share announcement fetchers (解禁/增减持/回购/定增)
# ---------------------------------------------------------------------------
from value_genie.intel import announcements as ann


class TestFetchAUnlocks:
    def test_normalizes_rows(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "688795", "SECURITY_NAME_ABBR": "摩尔线程-U",
                "FREE_DATE": "2026-09-12 00:00:00",
                "TOTAL_RATIO": 0.12, "FREE_SHARES": 12345.6,
                "LIFT_MARKET_CAP": 50000.0, "NEW": 40.55}]))
        df = ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        assert df.iloc[0]["code"] == "688795"
        assert df.iloc[0]["name"] == "摩尔线程-U"
        assert df.iloc[0]["unlock_pct"] == pytest.approx(12.0)  # decimal -> %
        assert df.iloc[0]["free_date"] == "2026-09-12"
        assert df.iloc[0]["lift_cap_wan"] == 50000.0

    def test_filter_double_quotes(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        assert seen["filter"] == ('(FREE_DATE>="2026-09-08")'
                                  '(FREE_DATE<="2026-12-07")')

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json",
                            lambda url, params=None, **kw: None)
        assert ann.fetch_a_unlocks("2026-09-08", "2026-12-07") is None


class TestFetchAHolderChanges:
    def test_normalizes_rows(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "DIRECTION": "减持", "CHANGE_NUM": 100.5,
                "NOTICE_DATE": "2026-08-01 00:00:00",
                "END_DATE": "2026-11-01 00:00:00",
                "HOLDER_NAME": "某国资"}]))
        df = ann.fetch_a_holder_changes("2026-08-01")
        assert df.iloc[0]["direction"] == "减持"
        assert df.iloc[0]["change_num_wan"] == 100.5
        assert df.iloc[0]["notice_date"] == "2026-08-01"
        assert df.iloc[0]["end_date"] == "2026-11-01"
        assert df.iloc[0]["holder_name"] == "某国资"


class TestFetchABuybacks:
    def test_uses_scode_and_no_sort(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([{
                "SCODE": "000858", "SNAME": "五粮液",
                "HGJE": 5.0e8, "HGSL": 2.0e7,
                "GGRQ": "2026-09-01 00:00:00",
                "TDATE": "2026-09-01 00:00:00"}])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        df = ann.fetch_a_buybacks("2026-08-01")
        assert "sortColumns" not in seen        # probe rule 2
        assert seen["filter"] == '(GGRQ>="2026-08-01")'
        assert df.iloc[0]["code"] == "000858"   # SCODE -> code
        assert df.iloc[0]["amount_yuan"] == 5.0e8
        assert df.iloc[0]["shares"] == 2.0e7
        assert df.iloc[0]["announce_date"] == "2026-09-01"


class TestFetchAPlacements:
    def test_dilution_pct(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "ISSUE_DATE": "2026-08-15 00:00:00", "ISSUE_NUM": 1.0e7,
                "ISSUE_SHARE_BEFORE": 1.0e9, "ISSUE_SHARE_AFTER": 1.01e9,
                "NET_RAISE_FUNDS": 2.0e9, "SEO_TYPE": "定向增发"}]))
        df = ann.fetch_a_placements("2026-08-01")
        assert df.iloc[0]["dilution_pct"] == pytest.approx(1.0)
        assert df.iloc[0]["issue_date"] == "2026-08-15"
        assert df.iloc[0]["net_raise"] == 2.0e9
