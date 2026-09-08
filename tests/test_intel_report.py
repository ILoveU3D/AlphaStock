"""Tests for value_genie.intel.report (per-stock intelligence assembly)."""

import json
from datetime import date

import pandas as pd

from value_genie.fetch.http import DC
from value_genie.intel import report as ir
from value_genie.intel.model import IntelItem
from value_genie.resolve import Match


def _snap(tmp_path, files: dict):
    snap = tmp_path / "snapshots" / "20260909"
    snap.mkdir(parents=True)
    for name, df in files.items():
        df.to_csv(snap / name, index=False)
    return snap


def _match(market="A", code="688795", mid="1"):
    return Match(market, code, "摩尔线程-U", 100.0, mid)


def _kill_dc(monkeypatch):
    """缺失批表的单股兜底走 DC——测试中统一视为源失败（fail-closed），
    不发真实网络请求。"""
    monkeypatch.setattr(DC, "get_json",
                        lambda url, params=None, **kw: None)


class TestRadarRow:
    def test_reads_master_row(self, tmp_path):
        files = {"master.csv": pd.DataFrame([{
            "market": "A", "code": "688795", "name": "摩尔线程-U",
            "unlock_pct_30d": 12.0, "intel_red": 1.0,
            "holder_cut_flag": 0.0, "dilution_flag": 0.0,
            "buyback_active": 0.0, "report_due_days": 49.0,
            "forecast_flag": 0.0, "eq_flags": 0.0,
            "unlock_pct_90d": 12.0}])}
        snap = _snap(tmp_path, files)
        row = ir._radar_row(snap, "A", "688795")
        assert row["unlock_pct_30d"] == 12.0
        assert row["intel_red"] == 1.0

    def test_watchlist_fallback(self, tmp_path):
        files = {"watchlist.csv": pd.DataFrame([{
            "market": "A", "code": "688795", "intel_red": 1.0}])}
        snap = _snap(tmp_path, files)
        assert ir._radar_row(snap, "A", "688795")["intel_red"] == 1.0

    def test_missing_stock_returns_none(self, tmp_path):
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "A", "code": "600519", "intel_red": 0.0}])})
        assert ir._radar_row(snap, "A", "688795") is None

    def test_no_snapshot_returns_none(self, tmp_path):
        assert ir._radar_row(tmp_path, "A", "688795") is None


class TestBuildIntelReport:
    def test_full_assembly(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        files = {
            "master.csv": pd.DataFrame([{
                "market": "A", "code": "688795", "name": "摩尔线程-U",
                "unlock_pct_30d": 12.0, "unlock_pct_90d": 12.0,
                "holder_cut_flag": 0.0, "dilution_flag": 0.0,
                "buyback_active": 0.0, "report_due_days": 49.0,
                "forecast_flag": 0.0, "eq_flags": 2.0, "intel_red": 1.0}]),
            "a_unlocks.csv": pd.DataFrame([{
                "code": "688795", "name": "摩尔线程-U",
                "free_date": "2026-09-12", "unlock_pct": 12.0,
                "lift_cap_wan": 1070000.0}]),
            "a_financials.csv": pd.DataFrame([{
                "code": "688795", "report_date": "2026-06-30",
                "rev_yoy": 22.0, "profit": 1.0e9, "deduct_eps": 0.3,
                "basic_eps": 0.5}]),
            # _eq_records 喂 None balance 会返回 None → eq 板块报
            # missing；提供 a_balance.csv 让 eq 走明细列表路径。
            "a_balance.csv": pd.DataFrame([{
                "code": "688795", "rece_yoy": 10.0, "inv_yoy": 10.0}]),
        }
        snap = _snap(tmp_path, files)
        notice = IntelItem(market="A", code="688795", name="摩尔线程-U",
                           subsystem="announcements", kind="notice",
                           event_date=date(2026, 9, 7), title="投资者关系活动",
                           source="eastmoney", impact="neutral",
                           payload={})
        rating = IntelItem(market="A", code="688795", name="摩尔线程-U",
                           subsystem="ratings", kind="rating",
                           event_date=date(2026, 8, 22), title="国金证券 买入",
                           source="eastmoney", impact="positive",
                           payload={"org": "国金证券", "rating": "买入"})
        news = IntelItem(market="A", code="688795", name="摩尔线程-U",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="解禁报道",
                         source="eastmoney", impact="neutral",
                         payload={"media": "每经"})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": [notice])
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": [rating])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [news])
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        assert result["match"].code == "688795"
        assert result["radar"]["unlock_pct_30d"] == 12.0
        kinds = [i.kind for i in result["events"]]
        assert "unlock" in kinds
        assert len(result["notices"]) == 1
        assert len(result["ratings"]) == 1
        assert result["ratings"][0].impact == "positive"
        assert len(result["news"]) == 1
        assert "missing" not in result["eq"]      # eq is a detail list

    def test_section_failure_is_missing_not_error(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {})     # empty snapshot dir, no master
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)   # source failure
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": None)
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        assert result["notices"] == {"missing": "notice source failed"}
        assert result["ratings"] == {"missing": "ratings source failed"}
        assert result["news"] == {"missing": "news source failed"}
        assert result["radar"] == {}

    def test_hk_market_degrades(self, tmp_path, monkeypatch):
        snap = _snap(tmp_path, {})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="", **kw: None)
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="", **kw: None)
        result = ir.build_intel_report(
            Match("HK", "00700", "腾讯", 100.0, "116"),
            snapshot_dir=snap, asof=date(2026, 9, 9))
        assert result["events"] == {
            "missing": "雷达批表当前仅覆盖 A 股（HK/US 批量事件属后续阶段）"}
        assert result["eq"] == {
            "missing": "粉饰信号输入（应收/存货/OCF/扣非）为 A 股快照专属"}
        assert result["ratings"]["missing"].startswith("港股研报源缺失")
        assert result["notices"] == {"missing": "notice source failed"}
        assert result["news"] == {"missing": "news source failed"}


class TestBuildIntelReportHKUS:
    def _hk_match(self):
        return Match("HK", "00700", "腾讯控股", 100.0, "116")

    def _us_match(self):
        return Match("US", "AAPL", "Apple", 100.0, "105")

    def test_hk_assembly(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "HK", "code": "00700", "name": "腾讯控股",
              "intel_red": 0.0}])})
        notice = IntelItem(market="HK", code="00700", name="腾讯控股",
                           subsystem="announcements", kind="notice",
                           event_date=date(2026, 9, 8), title="翌日披露报表",
                           source="eastmoney", impact="neutral", payload={})
        news = IntelItem(market="HK", code="00700", name="腾讯控股",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="腾讯新闻",
                         source="eastmoney", impact="neutral", payload={})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda code, name="", **kw: [notice])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, code, name="", **kw: [news])
        res = ir.build_intel_report(self._hk_match(), snapshot_dir=snap)
        assert res["notices"] == [notice]
        assert res["news"] == [news]
        assert isinstance(res["ratings"], dict) and "missing" in res["ratings"]
        assert "missing" in res["events"] and "missing" in res["eq"]
        assert res["radar"]["intel_red"] == 0.0

    def test_us_assembly(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "US", "code": "AAPL", "name": "Apple",
              "intel_red": 0.0}])})
        filing = IntelItem(market="US", code="AAPL", name="Apple",
                           subsystem="announcements", kind="filing",
                           event_date=date(2026, 9, 8), title="8-K filing",
                           source="sec_edgar", impact="neutral",
                           payload={"form": "8-K"})
        cons = IntelItem(market="US", code="AAPL", name="Apple",
                         subsystem="ratings", kind="consensus",
                         event_date=date(2026, 9, 9), title="一致评级 Buy",
                         source="stockanalysis", impact="neutral", payload={})
        rating = IntelItem(market="US", code="AAPL", name="Apple",
                           subsystem="ratings", kind="rating",
                           event_date=date(2026, 9, 8), title="HSBC Buy",
                           source="stockanalysis", impact="neutral",
                           payload={"org": "HSBC", "rating": "Buy"})
        news = IntelItem(market="US", code="AAPL", name="Apple",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="Apple news",
                         source="eastmoney", impact="neutral", payload={})
        monkeypatch.setattr(ir, "fetch_us_filings",
                            lambda code, name="": [filing])
        monkeypatch.setattr(ir, "fetch_us_consensus",
                            lambda code, name="": [cons, rating])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, code, name="", **kw: [news])
        res = ir.build_intel_report(self._us_match(), snapshot_dir=snap)
        assert res["notices"] == [filing]
        assert res["ratings"] == [cons, rating]
        assert res["news"] == [news]
        assert "missing" in res["events"] and "missing" in res["eq"]

    def test_us_render_labels(self):
        res = {"match": self._us_match(), "snapshot": "20260909",
               "asof": "2026-09-09", "radar": {},
               "events": {"missing": "雷达批表当前仅覆盖 A 股"},
               "eq": {"missing": "A 股快照专属"},
               "notices": [], "ratings": [], "news": []}
        out = ir.render_intel(res)
        assert "披露文件时间线" in out
        assert "US/AAPL" in out

    def test_hk_render_keeps_notice_label(self):
        res = {"match": self._hk_match(), "snapshot": "20260909",
               "asof": "2026-09-09", "radar": {},
               "events": {"missing": "x"}, "eq": {"missing": "x"},
               "notices": [], "ratings": {"missing": "y"}, "news": []}
        out = ir.render_intel(res)
        assert "公告时间线" in out

    def test_us_consensus_render(self):
        cons = IntelItem(market="US", code="AAPL", name="Apple",
                         subsystem="ratings", kind="consensus",
                         event_date=date(2026, 9, 9),
                         title="一致评级 Buy · 44家覆盖 · 目标价 $324.53",
                         source="stockanalysis", impact="neutral",
                         payload={"consensus": "Buy", "count": 44})
        rate = IntelItem(market="US", code="AAPL", name="Apple",
                         subsystem="ratings", kind="rating",
                         event_date=date(2026, 9, 8), title="HSBC Buy",
                         source="stockanalysis", impact="neutral",
                         payload={"org": "HSBC", "rating": "Buy",
                                  "target_price": 366.0})
        res = {"match": self._us_match(), "snapshot": "20260909",
               "asof": "2026-09-09", "radar": {},
               "events": [], "eq": [], "notices": [],
               "ratings": [cons, rate], "news": []}
        out = ir.render_intel(res)
        assert "一致评级 Buy · 44家覆盖" in out
        assert "HSBC Buy" in out


# ---------------------------------------------------------------------------
# Rendering + JSON
# ---------------------------------------------------------------------------


def _full_result(tmp_path, monkeypatch):
    # 只有 master.csv（雷达行），没有 a_*.csv 批表 —— 事件明细的单股
    # 兜底会打 DC，测试里统一掐掉（fail-closed → 各表 None → events=[]）。
    _kill_dc(monkeypatch)
    files = {"master.csv": pd.DataFrame([{
        "market": "A", "code": "688795", "name": "摩尔线程-U",
        "unlock_pct_30d": 12.0, "unlock_pct_90d": 12.0,
        "holder_cut_flag": 0.0, "dilution_flag": 0.0,
        "buyback_active": 0.0, "report_due_days": 49.0,
        "forecast_flag": 0.0, "eq_flags": 2.0, "intel_red": 1.0}])}
    snap = _snap(tmp_path, files)
    notice = IntelItem(market="A", code="688795", name="摩尔线程-U",
                       subsystem="announcements", kind="notice",
                       event_date=date(2026, 9, 7), title="投资者关系活动",
                       url="http://d/1.html", source="eastmoney",
                       impact="neutral", payload={"category": "调研活动"})
    rating = IntelItem(market="A", code="688795", name="摩尔线程-U",
                       subsystem="ratings", kind="rating",
                       event_date=date(2026, 8, 22), title="国金证券 买入",
                       source="eastmoney", impact="positive",
                       payload={"org": "国金证券", "rating": "买入",
                                "last_rating": "增持"})
    news = IntelItem(market="A", code="688795", name="摩尔线程-U",
                     subsystem="news", kind="news",
                     event_date=date(2026, 9, 8), title="解禁报道",
                     source="eastmoney", impact="neutral",
                     payload={"media": "每经"})
    monkeypatch.setattr(ir, "fetch_stock_notices",
                        lambda c, name="": [notice])
    monkeypatch.setattr(ir, "fetch_stock_ratings",
                        lambda c, name="": [rating])
    monkeypatch.setattr(ir, "fetch_stock_news",
                        lambda mid, c, name="": [news])
    return ir.build_intel_report(_match(), snapshot_dir=snap,
                                 asof=date(2026, 9, 9))


class TestRenderIntel:
    def test_renders_all_sections(self, tmp_path, monkeypatch):
        result = _full_result(tmp_path, monkeypatch)
        text = ir.render_intel(result)
        assert "舆情情报: 摩尔线程-U (A/688795)" in text
        assert "[事件雷达]" in text and "intel_red=1" in text
        assert "解禁30天 12.0%" in text
        assert "[公告时间线]" in text and "投资者关系活动" in text
        assert "[投行评级]" in text and "国金证券 买入" in text
        assert "[新闻时间线]" in text and "解禁报道" in text
        assert "data as of:" in text

    def test_missing_section_says_so(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": None)
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        text = ir.render_intel(result)
        assert "数据缺失: notice source failed" in text
        assert "数据缺失: ratings source failed" in text
        assert "数据缺失: news source failed" in text


class TestIntelJson:
    def test_to_json_is_pure_and_parseable(self, tmp_path, monkeypatch):
        result = _full_result(tmp_path, monkeypatch)
        payload = json.loads(ir.to_json(result))
        assert payload["match"]["code"] == "688795"
        assert payload["radar"]["unlock_pct_30d"] == 12.0
        assert payload["notices"][0]["kind"] == "notice"
        assert payload["ratings"][0]["payload"]["rating"] == "买入"
        # fixture 无 a_financials.csv → eq 是缺失 dict → null
        assert payload["eq"] is None or isinstance(payload["eq"], list)

    def test_to_json_missing_section_null(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": None)
        monkeypatch.setattr(ir, "fetch_stock_ratings",
                            lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [])
        result = ir.build_intel_report(_match(), snapshot_dir=snap,
                                       asof=date(2026, 9, 9))
        payload = json.loads(ir.to_json(result))
        assert payload["notices"] is None      # missing -> null
        assert payload["ratings"] == []
