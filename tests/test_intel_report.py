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


# ---------------------------------------------------------------------------
# Interpretation layer (user mandate 2026-09-09: 财报能看懂 / 公告知
# 含义 / 新闻时效 / 研报全面权威)
# ---------------------------------------------------------------------------
from value_genie.intel import interpret as ip  # noqa: E402


class TestNoticeMeaning:
    def test_category_keyword_hit(self):
        meaning, hint = ip.notice_meaning("股东减持", "某公告")
        assert "内部人信心" in meaning
        assert hint == "negative"

    def test_title_fallback(self):
        meaning, hint = ip.notice_meaning("公司公告", "关于回购股份的公告")
        assert "护盘" in meaning
        assert hint == "positive"

    def test_traditional_hk_variant(self):
        meaning, hint = ip.notice_meaning("股份購回", "")
        assert hint == "positive"

    def test_no_hit_is_neutral(self):
        assert ip.notice_meaning("其他公告", "日常事务") == ("", "neutral")


class TestFormMeaning:
    def test_exact_and_prefix(self):
        assert "重大事项" in ip.form_meaning("8-K")
        assert "内部人交易" in ip.form_meaning("4/A")
        assert ip.form_meaning("999X") == ""


class TestEarningsDigest:
    def test_full_row(self):
        row = {"report_date": "2026-06-30", "rev_yoy": 22.0,
               "profit_yoy": 35.0, "roe": 12.0, "gross_margin": 58.0,
               "net_margin": 21.0}
        extras = {"revenue": 5e9, "profit": 1e9, "deduct_eps": 0.8,
                  "basic_eps": 1.0, "ocf": 1.2e9}
        d = ip.earnings_digest(row, extras)
        assert d["period"] == "2026中报"
        assert "双增" in d["growth"]
        assert "扣非占80%" in d["read"]
        assert "OCF/净利 1.20" in d["read"]
        assert "营收 50.0 亿" in d["read"]

    def test_growth_tags(self):
        base = {"report_date": "2026-03-31"}
        assert "增收不增利" in ip.earnings_digest(
            {"report_date": "2026-03-31", "rev_yoy": 10.0,
             "profit_yoy": -5.0})["growth"]
        assert "双降" in ip.earnings_digest(
            {"report_date": "2026-03-31", "rev_yoy": -10.0,
             "profit_yoy": -5.0})["growth"]
        assert ip.earnings_digest(base) is None
        assert ip.earnings_digest({}) is None

    def test_low_cash_quality_flag(self):
        d = ip.earnings_digest({"report_date": "2026-06-30",
                                "rev_yoy": 5.0, "profit_yoy": 5.0},
                               {"profit": 1e9, "ocf": 0.2e9})
        assert "利润现金含量低" in d["quality"]

    def test_loss_maker_ratios_not_meaningless(self):
        # 亏损期：扣非占比与 OCF/净利 都是负除负的无意义比值，
        # 换成绝对值 + "不适用"标注（摩尔线程 2026 中报实跑发现）。
        d = ip.earnings_digest({"report_date": "2026-06-30",
                                "rev_yoy": 147.0, "profit_yoy": 95.0},
                               {"revenue": 1.74e9, "profit": -0.1e8,
                                "deduct_eps": -0.32, "basic_eps": -0.02,
                                "ocf": -18.8e8})
        joined = "；".join(d["quality"])
        assert "占比不适用" in joined
        assert "经营现金流 -18.8 亿" in joined
        assert "1600%" not in joined and "OCF/净利 1" not in joined


class TestNewsHeat:
    def _items(self, *dates, with_time=False):
        out = []
        for d in dates:
            payload = ({"show_time": f"{d} 09:00:00"}
                       if with_time else {})
            out.append(IntelItem(
                market="A", code="688795", name="x", subsystem="news",
                kind="news", event_date=date.fromisoformat(d),
                title="t", payload=payload))
        return out

    def test_counts_and_verdict(self):
        asof = date(2026, 9, 9)
        # 4 条落在 7 天窗（09-03 距 asof 6 天，含），前 7 天窗 1 条
        items = self._items("2026-09-09", "2026-09-08", "2026-09-07",
                            "2026-09-03", "2026-09-02", "2026-08-20")
        h = ip.news_heat(items, asof)
        assert h["today"] == 1
        assert h["d3"] == 3
        assert h["d7"] == 4
        assert h["prior7"] == 1
        assert h["verdict"] == "升温"

    def test_cooling(self):
        asof = date(2026, 9, 9)
        items = self._items("2026-09-09", "2026-09-01", "2026-09-01",
                           "2026-09-01", "2026-09-01", "2026-09-01")
        h = ip.news_heat(items, asof)
        assert h["verdict"] == "降温"

    def test_empty_and_hours(self):
        assert ip.news_heat([]) is None
        h = ip.news_heat(
            self._items("2026-09-09", with_time=True), date(2026, 9, 9))
        assert h["latest_hours"] is not None


class TestRatingsSummary:
    def _item(self, org, rating, change="", eps=None, tp=None,
              when="2026-09-01"):
        return IntelItem(
            market="A", code="688795", name="x", subsystem="ratings",
            kind="rating", event_date=date.fromisoformat(when),
            title=f"{org} {rating}",
            payload={"org": org, "rating": rating,
                     "rating_change": change, "eps_this_year": eps,
                     "target_price": tp})

    def test_aggregates(self):
        # 列表新→旧：中金的“增持”是被“买入”取代的旧评级——分布只计
        # 每家机构最新一份，旧评级只进上/下调计数。
        items = [
            self._item("中金", "买入", "2", eps=2.0, tp=60.0),
            self._item("中金", "增持", "3"),
            self._item("中信", "买入", "4", eps=2.4, tp=55.0),
            self._item("国金", "中性", "1", eps=2.6, tp=45.0),
        ]
        s = ip.ratings_summary(items)
        assert s["total"] == 4 and s["orgs"] == 3
        assert s["distribution"] == {"买入": 2, "中性": 1}
        assert s["upgrades"] == 1 and s["initiations"] == 1
        assert s["downgrades"] == 1
        assert s["eps_this_year_avg"] == round((2.0 + 2.4 + 2.6) / 3, 3)
        assert s["target_price_high"] == 60.0
        assert s["target_price_low"] == 45.0
        assert "中金" in s["top_orgs"]

    def test_empty(self):
        assert ip.ratings_summary([]) is None


class TestInterpretInReport:
    def test_digest_and_heat_assembled(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        files = {
            "master.csv": pd.DataFrame([{
                "market": "A", "code": "688795", "name": "摩尔线程-U",
                "report_date": "2026-06-30", "rev_yoy": 22.0,
                "profit_yoy": 35.0, "roe": 12.0, "gross_margin": 58.0,
                "intel_red": 0.0}]),
            "a_financials.csv": pd.DataFrame([{
                "code": "688795", "report_date": "2026-06-30",
                "revenue": 5e9, "profit": 1e9, "deduct_eps": 0.8,
                "basic_eps": 1.0}]),
        }
        snap = _snap(tmp_path, files)
        news = IntelItem(market="A", code="688795", name="摩尔线程-U",
                         subsystem="news", kind="news",
                         event_date=date(2026, 9, 8), title="t",
                         payload={})
        monkeypatch.setattr(ir, "fetch_stock_notices", lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_ratings", lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [news])
        res = ir.build_intel_report(_match(), snapshot_dir=snap,
                                    asof=date(2026, 9, 9))
        assert res["digest"]["period"] == "2026中报"
        assert res["digest"]["levels"] == ["营收 50.0 亿", "归母净利 10.0 亿"]
        assert res["news_heat"]["d7"] == 1
        assert res["ratings_summary"] is None      # 空评级列表
        text = ir.render_intel(res)
        assert "[财报速读] 2026中报" in text
        assert "[新闻热度]" in text

    def test_digest_missing_without_snapshot_row(self, tmp_path,
                                                 monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {"master.csv": pd.DataFrame(
            [{"market": "A", "code": "600519", "intel_red": 0.0}])})
        monkeypatch.setattr(ir, "fetch_stock_notices", lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_ratings", lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [])
        res = ir.build_intel_report(_match(), snapshot_dir=snap,
                                    asof=date(2026, 9, 9))
        assert "missing" in res["digest"]
        assert "[财报速读] 数据缺失" in ir.render_intel(res)

    def test_notice_meaning_rendered(self, tmp_path, monkeypatch):
        _kill_dc(monkeypatch)
        snap = _snap(tmp_path, {})
        notice = IntelItem(market="A", code="688795", name="摩尔线程-U",
                           subsystem="announcements", kind="notice",
                           event_date=date(2026, 9, 7), title="关于回购股份",
                           impact="positive",
                           payload={"category": "公司公告",
                                    "meaning": "公司买入自家股票（护盘或注销）"})
        monkeypatch.setattr(ir, "fetch_stock_notices",
                            lambda c, name="": [notice])
        monkeypatch.setattr(ir, "fetch_stock_ratings", lambda c, name="": [])
        monkeypatch.setattr(ir, "fetch_stock_news",
                            lambda mid, c, name="": [])
        res = ir.build_intel_report(_match(), snapshot_dir=snap,
                                    asof=date(2026, 9, 9))
        assert "〔公司买入自家股票（护盘或注销）〕" in ir.render_intel(res)

    def test_us_filing_meaning_rendered(self):
        filing = IntelItem(market="US", code="AAPL", name="Apple",
                           subsystem="announcements", kind="filing",
                           event_date=date(2026, 9, 8),
                           title="Form 8-K filing",
                           payload={"form": "8-K",
                                    "form_meaning": "重大事项临时披露"})
        res = {"match": Match("US", "AAPL", "Apple", 100.0, "105"),
               "snapshot": "20260909", "asof": "2026-09-09",
               "radar": {}, "digest": None,
               "events": {"missing": "x"}, "eq": {"missing": "x"},
               "notices": [filing], "ratings": [], "news": [],
               "news_heat": None, "ratings_summary": None}
        out = ir.render_intel(res)
        assert "〔重大事项临时披露〕" in out
