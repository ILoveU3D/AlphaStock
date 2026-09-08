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
