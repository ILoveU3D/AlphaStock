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

    def test_9201_empty_window_returns_empty_df(self, monkeypatch):
        # probe rule 4: valid empty window answers success:false +
        # code 9201 "返回数据为空" — that is empty data, not a failure
        monkeypatch.setattr(
            _dc.DC, "get_json",
            lambda url, params=None, **kw: {"success": False, "code": 9201,
                                            "message": "返回数据为空",
                                            "result": None})
        assert _dc.dc_report("RPT_TEST", []).empty

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

    def test_filter_date_single_quotes(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        # probe rule 1: dates single-quoted (double quotes trip
        # "filter字段中日期参数格式错误")
        assert seen["filter"] == ("(FREE_DATE>='2026-09-08')"
                                  "(FREE_DATE<='2026-12-07')")

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
        assert seen["filter"] == "(GGRQ>='2026-08-01')"
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


# ---------------------------------------------------------------------------
# A-share earnings fetchers (业绩预告/披露预约/资产负债表)
# ---------------------------------------------------------------------------
from value_genie.intel import earnings as ear


class TestFetchAForecasts:
    def test_normalizes_rows_and_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "PREDICT_TYPE": "首亏", "INCREASE_JZ": -120.0,
                "NOTICE_DATE": "2026-08-30 00:00:00"}])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        df = ear.fetch_a_forecasts("2026-08-01")
        # probe rule 1: date single-quoted, string/boolean double-quoted
        assert seen["filter"] == ("(NOTICE_DATE>='2026-08-01')"
                                  '(IS_LATEST="T")')
        assert df.iloc[0]["predict_type"] == "首亏"
        assert df.iloc[0]["change_pct"] == -120.0
        assert df.iloc[0]["notice_date"] == "2026-08-30"


class TestFetchAAppointments:
    def test_normalizes_rows(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                "APPOINT_PUBLISH_DATE": "2026-10-28 00:00:00",
                "IS_PUBLISH": "0", "REPORT_TYPE_NAME": "三季报"}]))
        df = ear.fetch_a_appointments("2026-09-08", "2026-12-07")
        assert df.iloc[0]["appoint_date"] == "2026-10-28"
        assert df.iloc[0]["is_published"] == "0"
        assert df.iloc[0]["report_type"] == "三季报"

    def test_empty_window_is_valid(self, monkeypatch):
        # 三季报预约 9 月末才挂出：未来窗口为空是正常时序，不是失败
        monkeypatch.setattr(_dc.DC, "get_json",
                            lambda url, params=None, **kw: _dc_json([]))
        assert ear.fetch_a_appointments("2026-09-08",
                                        "2026-12-07").empty


class TestFetchABalance:
    def test_normalizes_yoy_columns(self, monkeypatch):
        monkeypatch.setattr(_dc.DC, "get_json", lambda url, params=None, **kw:
            _dc_json([{
                "SECURITY_CODE": "600519",
                "ACCOUNTS_RECE_RATIO": 58.0, "INVENTORY_RATIO": 12.0,
                "ACCOUNTS_RECE": 1.0e9, "INVENTORY": 2.0e9}]))
        df = ear.fetch_a_balance("2026-06-30")
        assert df.iloc[0]["rece_yoy"] == 58.0   # YoY %, 非占比（已探针验证）
        assert df.iloc[0]["inv_yoy"] == 12.0
        assert df.iloc[0]["receivable"] == 1.0e9
        assert df.iloc[0]["report_date"] == "2026-06-30"


# ---------------------------------------------------------------------------
# P2: per-stock intel capabilities + EM_WEB singleton / URL constants
# ---------------------------------------------------------------------------
def test_import_intel_extends_news_ratings_capabilities():
    import value_genie.intel  # noqa: F401
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert "news:A" in ds.capabilities
    assert "ratings:A" in ds.capabilities
    assert "notice:A" in ds.capabilities
    assert [s.id for s in get_sources("news", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("ratings", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("notice", "A")] == ["eastmoney"]


def test_em_web_singleton_and_urls():
    from value_genie.fetch.http import EM_WEB
    from value_genie import config
    assert EM_WEB.name == "EM_WEB"
    assert config.EM_NOTICE_URL.startswith("https://np-anotice-stock")
    assert config.EM_NEWS_URL.startswith("https://np-listapi")
    assert config.EM_REPORT_URL.startswith("https://reportapi")
    assert config.INTEL_NOTICE_DAYS == 90
    assert config.INTEL_NEWS_DAYS == 30
    assert config.INTEL_RATING_DAYS == 365


# ---------------------------------------------------------------------------
# Per-stock news timeline (np-listapi)
# ---------------------------------------------------------------------------
from datetime import date, timedelta

from value_genie.intel import news as nws


def _news_json(rows):
    return {"code": 1, "message": "success",
            "data": {"page_index": 1, "list": rows}}


class TestFetchStockNews:
    def test_normalizes_items_and_window(self, monkeypatch):
        today = date.today()
        recent = (today - timedelta(days=2)).isoformat()
        stale = (today - timedelta(days=60)).isoformat()
        rows = [
            {"Art_ShowTime": f"{recent} 20:55:07",
             "Art_Title": "摩尔线程解禁", "Art_MediaName": "每日经济新闻",
             "Art_Url": "http://finance.eastmoney.com/a/1.html"},
            {"Art_ShowTime": f"{stale} 09:00:00",
             "Art_Title": "旧闻（窗口外，应被过滤）",
             "Art_MediaName": "x", "Art_Url": "http://x/2.html"},
        ]
        seen = {}

        def fake(url, params=None, **kw):
            seen.update({"url": url, "params": params})
            return _news_json(rows)

        monkeypatch.setattr(nws.EM_WEB, "get_json", fake)
        items = nws.fetch_stock_news("1", "688795", name="摩尔线程-U")
        assert seen["params"]["mTypeAndCode"] == "1.688795"
        assert len(items) == 1                     # stale row filtered
        it = items[0]
        assert it.subsystem == "news" and it.kind == "news"
        assert it.event_date.isoformat() == recent
        assert it.title == "摩尔线程解禁"
        assert it.url == "http://finance.eastmoney.com/a/1.html"
        assert it.payload["media"] == "每日经济新闻"
        assert it.impact == "neutral"

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(nws.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert nws.fetch_stock_news("1", "688795") is None

    def test_envelope_code_not_success_none(self, monkeypatch):
        # np-listapi success envelope is code==1; anything else is failure
        monkeypatch.setattr(
            nws.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"code": 0, "data": None})
        assert nws.fetch_stock_news("1", "688795") is None

    def test_empty_list_is_empty_not_none(self, monkeypatch):
        monkeypatch.setattr(
            nws.EM_WEB, "get_json",
            lambda url, params=None, **kw: _news_json([]))
        assert nws.fetch_stock_news("1", "688795") == []


class TestFetchStockNewsMultiMarket:
    def test_hk_market_tag(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params["mTypeAndCode"])
            return _news_json([{"Art_ShowTime": f"{date.today().isoformat()} 10:00:00",
                                "Art_Title": "腾讯新闻",
                                "Art_MediaName": "证券日报",
                                "Art_Url": "http://x/1.html"}])

        monkeypatch.setattr(nws.EM_WEB, "get_json", fake)
        items = nws.fetch_stock_news("116", "00700", "腾讯控股", market="HK")
        assert calls == ["116.00700"]
        assert items[0].market == "HK"
        assert items[0].code == "00700"

    def test_us_market_tag(self, monkeypatch):
        monkeypatch.setattr(
            nws.EM_WEB, "get_json",
            lambda url, params=None, **kw: _news_json([
                {"Art_ShowTime": f"{date.today().isoformat()} 10:00:00",
                 "Art_Title": "Apple news", "Art_MediaName": "证券时报",
                 "Art_Url": "http://x/1.html"}]))
        items = nws.fetch_stock_news("105", "AAPL", "Apple", market="US")
        assert items[0].market == "US"
        assert items[0].code == "AAPL"

    def test_us_blank_prefix_falls_back(self, monkeypatch):
        tried = []

        def fake(url, params=None, **kw):
            tried.append(params["mTypeAndCode"])
            if params["mTypeAndCode"].startswith("105."):
                return {"code": 1, "data": {}}   # wrong exchange: empty
            return _news_json([{
                "Art_ShowTime": f"{date.today().isoformat()} 10:00:00",
                "Art_Title": "NYSE story", "Art_MediaName": "证券日报",
                "Art_Url": "http://x/2.html"}])

        monkeypatch.setattr(nws.EM_WEB, "get_json", fake)
        items = nws.fetch_stock_news("", "IBM", "IBM", market="US")
        assert tried == ["105.IBM", "106.IBM"]
        assert items and items[0].title == "NYSE story"

    def test_us_all_prefixes_empty_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            nws.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"code": 1, "data": {}})
        assert nws.fetch_stock_news("", "XYZ", "XYZ", market="US") == []

    def test_us_all_sources_failed_returns_none(self, monkeypatch):
        monkeypatch.setattr(nws.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert nws.fetch_stock_news("", "XYZ", "XYZ", market="US") is None

    def test_hk_blank_prefix_defaults_116(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params["mTypeAndCode"])
            return _news_json([])

        monkeypatch.setattr(nws.EM_WEB, "get_json", fake)
        nws.fetch_stock_news("", "00700", market="HK")
        assert calls == ["116.00700"]


# ---------------------------------------------------------------------------
# Per-stock analyst ratings (reportapi)
# ---------------------------------------------------------------------------
from value_genie.intel import ratings as rtg


def _rating_row(**over):
    row = {
        "orgSName": "国金证券", "publishDate": "2026-08-22 00:00:00.000",
        "emRatingName": "买入", "lastEmRatingName": "增持",
        "ratingChange": 2, "predictThisYearEps": "3.544",
        "predictNextYearEps": "1.262", "indvAimPriceT": "",
        "indvAimPriceL": "", "infoCode": "AP202608221828313285",
        "title": "全功能GPU领军", "researcher": "刘高畅",
    }
    row.update(over)
    return row


class TestFetchStockRatings:
    def test_normalizes_items(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update({"url": url, "params": params})
            return {"hits": 1, "size": 1, "data": [_rating_row()]}

        monkeypatch.setattr(rtg.EM_WEB, "get_json", fake)
        items = rtg.fetch_stock_ratings("688795", name="摩尔线程-U")
        assert seen["params"]["code"] == "688795"
        assert len(items) == 1
        it = items[0]
        assert it.subsystem == "ratings" and it.kind == "rating"
        assert it.event_date.isoformat() == "2026-08-22"
        assert it.title == "国金证券 买入"
        assert it.url == ("https://data.eastmoney.com/report/info/"
                          "AP202608221828313285.html")
        assert it.impact == "positive"          # ratingChange 2 = upgrade
        assert it.payload["rating"] == "买入"
        assert it.payload["last_rating"] == "增持"
        assert it.payload["target_price"] is None   # blank stays None

    def test_downgrade_is_negative(self, monkeypatch):
        monkeypatch.setattr(
            rtg.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"hits": 1, "size": 1,
                                            "data": [_rating_row(
                                                ratingChange=1)]})
        items = rtg.fetch_stock_ratings("688795")
        assert items[0].impact == "negative"

    def test_maintain_is_neutral(self, monkeypatch):
        monkeypatch.setattr(
            rtg.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"hits": 1, "size": 1,
                                            "data": [_rating_row(
                                                ratingChange=3)]})
        items = rtg.fetch_stock_ratings("688795")
        assert items[0].impact == "neutral"

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(rtg.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert rtg.fetch_stock_ratings("688795") is None

    def test_empty_data_is_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            rtg.EM_WEB, "get_json",
            lambda url, params=None, **kw: {"hits": 0, "data": []})
        assert rtg.fetch_stock_ratings("688795") == []


# ---------------------------------------------------------------------------
# US consensus + rating history (stockanalysis.com, P3)
# ---------------------------------------------------------------------------
_SA_HTML = (
    '<!doctype html><html><body>'
    + 'x' * 50
    + 'widget:{all:{count:44,consensus:"Buy",price_target:324.53,'
    'currency:"USD"}},'
    'ratings:[{action_rt:"Maintains",pt_now:366,pt_old:null,firm:"HSBC",'
    'analyst:"Nicolas Cote Colisson",date:"2026-09-08",'
    'rating_new:"Buy",rating_old:"",time:"11:15:07",'
    'scores:{score:44.2,stars:.6,total:43},curr:"USD"},'
    '{action_rt:"Upgrades",pt_now:300,pt_old:270,firm:"Needham",'
    'analyst:"Laura Martin",date:"2026-09-07",rating_new:"Buy",'
    'rating_old:"Hold",time:"10:55:34",curr:"USD"}]}'
    'rest-of-page</body></html>'
)


class TestFetchUsConsensus:
    def test_parses_widget_and_ratings(self, monkeypatch):
        monkeypatch.setattr(rtg.SA, "get_text",
                            lambda url, **kw: _SA_HTML)
        items = rtg.fetch_us_consensus("AAPL", "Apple")
        assert items[0].kind == "consensus"
        assert items[0].market == "US"
        assert items[0].payload["consensus"] == "Buy"
        assert items[0].payload["count"] == 44
        assert items[0].payload["price_target"] == 324.53
        assert "44家覆盖" in items[0].title
        assert items[1].kind == "rating"
        assert items[1].subsystem == "ratings"
        assert items[1].payload["org"] == "HSBC"
        assert items[1].payload["target_price"] == 366
        assert items[1].payload["prev_target"] is None   # pt_old null
        assert items[1].impact == "neutral"              # Maintains
        assert items[2].payload["org"] == "Needham"
        assert items[2].impact == "positive"             # Upgrades
        assert items[2].payload["last_rating"] == "Hold"

    def test_slug_mapping_for_class_shares(self, monkeypatch):
        urls = []
        monkeypatch.setattr(rtg.SA, "get_text",
                            lambda url, **kw: urls.append(url)
                            or _SA_HTML)
        rtg.fetch_us_consensus("BRK_B")
        assert urls == ["https://stockanalysis.com/stocks/"
                        "brk-b/ratings/"]

    def test_source_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(rtg.SA, "get_text",
                            lambda url, **kw: None)
        assert rtg.fetch_us_consensus("AAPL") is None

    def test_blob_missing_returns_none(self, monkeypatch):
        monkeypatch.setattr(rtg.SA, "get_text",
                            lambda url, **kw: "<html>no data</html>")
        assert rtg.fetch_us_consensus("AAPL") is None

    def test_downgrade_is_negative(self, monkeypatch):
        html = _SA_HTML.replace('action_rt:"Upgrades"',
                                'action_rt:"Downgrades"')
        monkeypatch.setattr(rtg.SA, "get_text",
                            lambda url, **kw: html)
        items = rtg.fetch_us_consensus("AAPL")
        assert items[2].impact == "negative"

    def test_widget_missing_returns_none(self, monkeypatch):
        html = _SA_HTML.replace("widget:{all:{", "broken:{all:{")
        monkeypatch.setattr(rtg.SA, "get_text",
                            lambda url, **kw: html)
        assert rtg.fetch_us_consensus("AAPL") is None


# ---------------------------------------------------------------------------
# Per-stock notice list (np-anotice-stock) + batch fetcher code filters
# ---------------------------------------------------------------------------
from value_genie.intel import announcements as ann2  # ann already imported


def _notice_json(rows):
    return {"data": {"list": rows}}


class TestFetchStockNotices:
    def test_normalizes_items_with_category_and_url(self, monkeypatch):
        rows = [{
            "art_code": "AN202608281828639681",
            "title": "摩尔线程:关于限售股份上市流通的提示性公告",
            "notice_date": "2026-08-28 00:00:00",
            "columns": [{"column_code": "001002002003",
                         "column_name": "限售股份上市流通"}],
        }]
        seen = {}

        def fake(url, params=None, **kw):
            seen.update({"url": url, "params": params})
            return _notice_json(rows)

        monkeypatch.setattr(ann2.EM_WEB, "get_json", fake)
        items = ann2.fetch_stock_notices("688795", name="摩尔线程-U")
        assert seen["params"]["stock_list"] == "688795"
        assert len(items) == 1
        it = items[0]
        assert it.subsystem == "announcements" and it.kind == "notice"
        assert it.event_date.isoformat() == "2026-08-28"
        assert it.payload["category"] == "限售股份上市流通"
        assert it.url == ("https://data.eastmoney.com/notices/detail/"
                          "688795/AN202608281828639681.html")
        assert it.impact == "neutral"

    def test_window_filters_old_notices(self, monkeypatch):
        from datetime import date as _d, timedelta as _td
        old = (_d.today() - _td(days=120)).isoformat()
        rows = [{"art_code": "X", "title": "旧公告",
                 "notice_date": f"{old} 00:00:00", "columns": []}]
        monkeypatch.setattr(ann2.EM_WEB, "get_json",
                            lambda url, params=None, **kw: _notice_json(rows))
        assert ann2.fetch_stock_notices("688795") == []

    def test_source_failure_none(self, monkeypatch):
        monkeypatch.setattr(ann2.EM_WEB, "get_json",
                            lambda url, params=None, **kw: None)
        assert ann2.fetch_stock_notices("688795") is None


class TestFetchStockNoticesHK:
    def test_hk_ann_type_h_and_market_tag(self, monkeypatch):
        calls = []
        rows = [{
            "art_code": "AN202609081829135004",
            "title": "翌日披露报表 - 已发行股份变动及股份购回",
            "notice_date": f"{date.today().isoformat()} 00:00:00",
            "columns": [{"column_code": "011005001",
                         "column_name": "股份購回"}],
        }]

        def fake(url, params=None, **kw):
            calls.append(params["ann_type"])
            return _notice_json(rows)

        monkeypatch.setattr(ann2.EM_WEB, "get_json", fake)
        items = ann2.fetch_stock_notices("00700", "腾讯控股", market="HK")
        assert calls == ["H"]
        assert items[0].market == "HK"
        assert items[0].code == "00700"
        assert items[0].payload["category"] == "股份購回"
        assert "AN202609081829135004" in items[0].url

    def test_a_share_default_ann_type_a(self, monkeypatch):
        calls = []

        def fake(url, params=None, **kw):
            calls.append(params["ann_type"])
            return _notice_json([])

        monkeypatch.setattr(ann2.EM_WEB, "get_json", fake)
        ann2.fetch_stock_notices("688795")
        assert calls == ["A"]


class TestFetchUsFilings:
    def _submissions(self):
        return {
            "cik": "0000320193",
            "filings": {"recent": {
                "accessionNumber": ["0000320193-26-000018",
                                    "0000320193-26-000017",
                                    "0000320193-26-000016"],
                "filingDate": [f"{date.today().isoformat()}",
                               f"{date.today().isoformat()}",
                               f"{date.today().isoformat()}"],
                "form": ["8-K", "144", "10-Q"],
                "primaryDocument": ["a1.htm", "x144.htm", "a10q.htm"],
                "items": ["Item 2.02", "", "item 2"],
                "reportDate": [f"{date.today().isoformat()}", "", ""],
            }}}

    def test_filters_material_forms_and_marks_market(self, monkeypatch):
        monkeypatch.setattr(ann, "_load_cik_map",
                            lambda: {"AAPL": 320193})
        monkeypatch.setattr(ann.SEC, "get_json",
                            lambda url, params=None, **kw:
                            self._submissions())
        items = ann.fetch_us_filings("AAPL", "Apple")
        assert [i.payload["form"] for i in items] == ["8-K", "10-Q"]
        assert all(i.market == "US" for i in items)
        assert all(i.kind == "filing" for i in items)
        assert all(i.subsystem == "announcements" for i in items)
        assert items[0].url.startswith(
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000018/")
        assert items[0].payload["items"] == "Item 2.02"

    def test_days_window(self, monkeypatch):
        old = (date.today() - timedelta(days=80)).isoformat()
        sub = self._submissions()
        sub["filings"]["recent"]["filingDate"] = [
            f"{date.today().isoformat()}", old, old]
        monkeypatch.setattr(ann, "_load_cik_map",
                            lambda: {"AAPL": 320193})
        monkeypatch.setattr(ann.SEC, "get_json",
                            lambda url, params=None, **kw: sub)
        items = ann.fetch_us_filings("AAPL", "Apple", days=30)
        assert [i.payload["form"] for i in items] == ["8-K"]

    def test_unknown_ticker_returns_none(self, monkeypatch):
        monkeypatch.setattr(ann, "_load_cik_map", lambda: {})
        assert ann.fetch_us_filings("NOPE") is None

    def test_cik_map_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(ann, "_load_cik_map", lambda: {})
        assert ann.fetch_us_filings("AAPL") is None

    def test_edgar_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(ann, "_load_cik_map",
                            lambda: {"AAPL": 320193})
        monkeypatch.setattr(ann.SEC, "get_json",
                            lambda url, params=None, **kw: None)
        assert ann.fetch_us_filings("AAPL") is None

    def test_material_form_matcher(self):
        assert ann._is_material_form("4")
        assert ann._is_material_form("4/A")
        assert ann._is_material_form("8-K")
        assert ann._is_material_form("8-K/A")
        assert ann._is_material_form("10-Q")
        assert ann._is_material_form("SC 13G/A")
        assert ann._is_material_form("424B5")
        assert ann._is_material_form("DEF 14A")
        assert not ann._is_material_form("144")
        assert not ann._is_material_form("CERTNYS")   # boilerplate cert


class TestBatchFetcherCodeFilter:
    def test_unlocks_single_stock_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07", code="688795")
        assert '(SECURITY_CODE="688795")' in seen["filter"]

    def test_buybacks_single_stock_uses_scode(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_buybacks("2026-08-01", code="688795")
        assert '(SCODE="688795")' in seen["filter"]
        assert "sortColumns" not in seen

    def test_holder_changes_single_stock_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_holder_changes("2026-08-01", code="688795")
        assert '(SECURITY_CODE="688795")' in seen["filter"]

    def test_balance_single_stock_filter(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ear.fetch_a_balance("2026-06-30", code="688795")
        assert '(SECURITY_CODE="688795")' in seen["filter"]

    def test_no_code_keeps_batch_behavior(self, monkeypatch):
        seen = {}

        def fake(url, params=None, **kw):
            seen.update(params)
            return _dc_json([])

        monkeypatch.setattr(_dc.DC, "get_json", fake)
        ann.fetch_a_unlocks("2026-09-08", "2026-12-07")
        assert "SECURITY_CODE=" not in seen["filter"]
