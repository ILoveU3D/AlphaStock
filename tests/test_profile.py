"""Tests for value_genie.profile (three-core knowledge base) and
value_genie.fetch.profiles (raw-text fetchers, all sources mocked)."""

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from value_genie import config
from value_genie import profile as pf
from value_genie.fetch import profiles as fp


@pytest.fixture
def pdir(tmp_path, monkeypatch):
    d = tmp_path / "profiles"
    monkeypatch.setattr(config, "PROFILES_DIR", d)
    return d


def make_profile(market="A", code="600900", name="长江电力",
                 with_raw=True):
    p = pf.Profile(id=f"{market}:{code}", market=market, code=code,
                   name=name)
    if with_raw:
        pf.set_raw(p, {"summary": "大型水电运营商，三峡集团旗下。",
                       "main_business": "大型水电运营",
                       "vision": "",
                       "meta": {"chairman": "刘伟平"},
                       "source": "test", "source_url": "http://x"})
    return p


# ---------------------------------------------------------------------------
class TestCRUD:
    def test_save_load_roundtrip(self, pdir):
        p = make_profile()
        pf.save_profile(p)
        q = pf.load_profile("A", "600900")
        assert q.id == "A:600900"
        assert q.raw.summary.startswith("大型水电")
        assert q.raw.meta["chairman"] == "刘伟平"
        assert q.version == 1

    def test_version_bumps(self, pdir):
        p = make_profile()
        pf.save_profile(p)
        pf.save_profile(p)
        assert pf.load_profile("A", "600900").version == 2

    def test_code_normalized(self, pdir):
        p = make_profile(market="HK", code="00998", name="中信银行")
        pf.save_profile(p)
        assert (pdir / "hk" / "00998.json").exists()
        assert pf.load_profile("HK", "998").code == "00998"

    def test_bad_market(self, pdir):
        with pytest.raises(ValueError):
            pf.profile_path("XX", "600900")

    def test_missing_file(self, pdir):
        with pytest.raises(FileNotFoundError):
            pf.load_profile("A", "600900")

    def test_corrupt_json(self, pdir):
        sub = pdir / "a"
        sub.mkdir(parents=True)
        (sub / "600900.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            pf.load_profile("A", "600900")

    def test_schema_drift_drops_unknown(self, pdir):
        p = make_profile()
        path = pf.save_profile(p)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["future_field"] = 1
        data["raw"]["future_raw_field"] = 2
        path.write_text(json.dumps(data, ensure_ascii=False),
                        encoding="utf-8")
        q = pf.load_profile("A", "600900")   # warns, does not raise
        assert q.raw.summary.startswith("大型水电")
        assert not hasattr(q, "future_field")

    def test_list_profiles(self, pdir):
        pf.save_profile(make_profile("A", "600900"))
        pf.save_profile(make_profile("HK", "00998", "中信银行"))
        pf.save_profile(make_profile("US", "MU", "Micron"))
        assert len(pf.list_profiles()) == 3
        assert len(pf.list_profiles(market="HK")) == 1


# ---------------------------------------------------------------------------
class TestFreshness:
    def test_raw_fresh_window(self, pdir):
        p = make_profile()
        assert pf.raw_is_fresh(p)
        p.raw.fetched_at = (datetime.now() - timedelta(
            days=config.PROFILE_FRESH_DAYS + 1)).isoformat(
                timespec="seconds")
        assert not pf.raw_is_fresh(p)

    def test_raw_empty_never_fresh(self, pdir):
        assert not pf.raw_is_fresh(pf.Profile(
            id="A:1", market="A", code="1"))

    def test_set_raw_unchanged_bumps_only(self, pdir):
        p = make_profile()
        pf.set_assessment(p, business={"score": 80.0})
        old_hash = p.raw.content_hash
        old_assess_at = p.assessment.assessed_at
        changed = pf.set_raw(p, {"summary": "大型水电运营商，三峡集团旗下。",
                                 "main_business": "大型水电运营",
                                 "vision": "", "meta": {},
                                 "source": "test"})
        assert changed is False
        assert p.raw.content_hash == old_hash
        assert not pf.assessment_is_stale(p)
        assert p.assessment.assessed_at == old_assess_at

    def test_set_raw_changed_stales_assessment(self, pdir):
        p = make_profile()
        pf.set_assessment(p, business={"score": 80.0})
        assert not pf.assessment_is_stale(p)
        changed = pf.set_raw(p, {"summary": "新的简介：战略转型抽水蓄能。",
                                 "main_business": "大型水电运营",
                                 "vision": "", "meta": {},
                                 "source": "test"})
        assert changed is True
        assert pf.assessment_is_stale(p)


# ---------------------------------------------------------------------------
class TestAssessment:
    def test_requires_raw(self, pdir):
        p = pf.Profile(id="A:600900", market="A", code="600900")
        with pytest.raises(ValueError, match="raw zone is empty"):
            pf.set_assessment(p, business={"score": 80.0})

    def test_score_range(self, pdir):
        p = make_profile()
        with pytest.raises(ValueError):
            pf.set_assessment(p, business={"score": 101})
        with pytest.raises(ValueError):
            pf.set_assessment(p, culture={"score": -1})
        with pytest.raises(ValueError):
            pf.set_assessment(p, business={"score": "high"})

    def test_links_raw_version(self, pdir):
        p = make_profile()
        pf.set_assessment(p, business={"score": 80.0},
                          culture={"score": 70.0}, verdict="收租机器")
        assert p.assessment.raw_fetched_at == p.raw.fetched_at
        assert p.assessment.raw_hash == p.raw.content_hash
        assert p.assessment.business["score"] == 80.0
        assert p.assessment.verdict == "收租机器"

    def test_merge_keeps_prior_zones(self, pdir):
        p = make_profile()
        pf.set_assessment(p, business={"score": 80.0})
        pf.set_assessment(p, culture={"score": 70.0})
        assert p.assessment.business["score"] == 80.0
        assert p.assessment.culture["score"] == 70.0


# ---------------------------------------------------------------------------
class TestAssessmentFrame:
    def test_only_assessed_non_stale(self, pdir):
        p1 = make_profile("A", "600900")
        pf.set_assessment(p1, business={"score": 80.0},
                          culture={"score": 70.0})
        pf.save_profile(p1)
        pf.save_profile(make_profile("HK", "00998", "中信银行"))  # unassessed
        p3 = make_profile("US", "MU", "Micron")
        pf.set_assessment(p3, business={"score": 60.0})
        pf.set_raw(p3, {"summary": "changed text", "main_business": "",
                        "vision": "", "meta": {}, "source": "test"})
        pf.save_profile(p3)                      # stale assessment
        df = pf.load_assessment_frame()
        assert len(df) == 1
        row = df.iloc[0]
        assert (row["market"], row["code"]) == ("A", "600900")
        assert row["a_business"] == 80.0 and row["a_culture"] == 70.0

    def test_empty_dir(self, pdir):
        df = pf.load_assessment_frame()
        assert list(df.columns) == ["market", "code",
                                    "a_business", "a_culture"]
        assert df.empty


# ---------------------------------------------------------------------------
class TestPoolMembers:
    def test_master_plus_watchlist_dedup(self, pdir, tmp_path):
        snap = tmp_path / "snap"
        snap.mkdir()
        pd.DataFrame([
            {"market": "A", "code": "600900", "name": "长江电力"},
            {"market": "US", "code": "MU", "name": "Micron"},
        ]).to_csv(snap / "master.csv", index=False)
        pd.DataFrame([
            {"market": "HK", "code": "998", "name": "中信银行"},
            {"market": "A", "code": "600900", "name": "长江电力"},
        ]).to_csv(snap / "watchlist.csv", index=False)
        members = pf.pool_members(snap)
        assert members == [("A", "600900", "长江电力"),
                           ("HK", "00998", "中信银行"),
                           ("US", "MU", "Micron")]

    def test_missing_files(self, pdir, tmp_path):
        assert pf.pool_members(tmp_path) == []


# ---------------------------------------------------------------------------
# fetch.profiles (all sources mocked at module level)
# ---------------------------------------------------------------------------
class TestFetchers:
    def test_a_parse(self, monkeypatch):
        payload = {"result": {"data": [{
            "ORG_PROFILE": "  一句话口号  ",
            "ORG_PROFIE": "  公司简介长文本 " * 20,
            "MAIN_BUSINESS": "大型水电运营",
            "BUSINESS_SCOPE": "电力生产、经营和投资",
            "CHAIRMAN": "刘伟平", "FOUND_DATE": "2002-11-04",
            "BLGAINIAN": "绿色电力,储能概念",
            "CONTROL_HOLDER": "中国长江三峡集团有限公司"}]}}
        monkeypatch.setattr(fp.DC, "get_json", lambda *a, **k: payload)
        raw = fp.fetch_profile_a("600900")
        # the typo'd ORG_PROFIE column (long form) wins over the slogan
        assert raw["summary"].startswith("公司简介长文本")
        assert len(raw["summary"]) > 100
        assert raw["main_business"] == "大型水电运营"
        assert raw["meta"]["chairman"] == "刘伟平"
        assert raw["meta"]["concepts"] == "绿色电力,储能概念"
        assert raw["meta"]["business_scope"].startswith("电力生产")
        assert raw["source"] == "eastmoney_f10_org_basicinfo"

    def test_a_slogan_fallback(self, monkeypatch):
        """No ORG_PROFIE -> the one-line ORG_PROFILE slogan is used."""
        payload = {"result": {"data": [{
            "ORG_PROFILE": "  一句话口号  ",
            "MAIN_BUSINESS": "大型水电运营"}]}}
        monkeypatch.setattr(fp.DC, "get_json", lambda *a, **k: payload)
        raw = fp.fetch_profile_a("600900")
        assert raw["summary"] == "一句话口号"

    def test_a_empty_rows(self, monkeypatch):
        monkeypatch.setattr(fp.DC, "get_json", lambda *a, **k: None)
        assert fp.fetch_profile_a("600900") is None

    def test_hk_parse(self, monkeypatch):
        payload = {"result": {"data": [{
            "ORG_PROFILE": "  中信银行成立于1987年 ",
            "MAIN_BUSINESS": "综合金融解决方案",
            "CHAIRMAN": "方合英", "EMP_NUM": 67674}]}}
        monkeypatch.setattr(fp.DC, "get_json", lambda *a, **k: payload)
        raw = fp.fetch_profile_hk("00998")
        assert raw["summary"].startswith("中信银行")
        assert raw["meta"]["employees"] == "67674"

    def test_us_parse(self, monkeypatch):
        html = 'x info:{symbol:"mu"} description:"Micron \\"designs\\" memory." y'
        monkeypatch.setattr(fp.SA, "get_text", lambda url: html)
        monkeypatch.setattr(fp, "_load_cik_map", lambda: {"MU": 723125})
        monkeypatch.setattr(fp.SEC, "get_json", lambda *a, **k: {
            "name": "MICRON TECHNOLOGY INC", "sic": "3674",
            "sicDescription": "Semiconductors & Related Devices",
            "entityType": "operating", "category": "Large accelerated filer",
            "fiscalYearEnd": "0903", "stateOfIncorporation": "DE"})
        raw = fp.fetch_profile_us("MU")
        assert raw["summary"] == 'Micron "designs" memory.'
        assert raw["meta"]["sic"] == "3674"
        assert raw["meta"]["cik"] == "723125"

    def test_us_no_description_fails_closed(self, monkeypatch):
        monkeypatch.setattr(fp.SA, "get_text", lambda url: "no payload")
        monkeypatch.setattr(fp, "_load_cik_map", lambda: {})
        assert fp.fetch_profile_us("MU") is None


# ---------------------------------------------------------------------------
class TestUpdateProfiles:
    def _fetcher_ok(self, text="简介"):
        def f(code):
            return {"summary": f"{text}-{code}", "main_business": "主业",
                    "vision": "", "meta": {}, "source": "test",
                    "source_url": ""}
        return f

    def test_fetch_then_skip_fresh(self, pdir, monkeypatch):
        monkeypatch.setitem(fp.FETCHERS, "A", self._fetcher_ok())
        symbols = [("A", "600900", "长江电力")]
        stats = fp.update_profiles(symbols)
        assert stats["fetched"] == 1 and stats["changed"] == 1
        stats = fp.update_profiles(symbols)
        assert stats["skipped_fresh"] == 1 and stats["fetched"] == 0

    def test_force_refetches(self, pdir, monkeypatch):
        monkeypatch.setitem(fp.FETCHERS, "A", self._fetcher_ok())
        symbols = [("A", "600900", "长江电力")]
        fp.update_profiles(symbols)
        stats = fp.update_profiles(symbols, force=True)
        assert stats["fetched"] == 1 and stats["changed"] == 0

    def test_none_source_keeps_old_file(self, pdir, monkeypatch):
        monkeypatch.setitem(fp.FETCHERS, "A", self._fetcher_ok())
        symbols = [("A", "600900", "长江电力")]
        fp.update_profiles(symbols)
        old = pf.load_profile("A", "600900").raw.summary
        monkeypatch.setitem(fp.FETCHERS, "A", lambda code: None)
        stats = fp.update_profiles(symbols, force=True)
        assert stats["failed"] == 1
        assert pf.load_profile("A", "600900").raw.summary == old

    def test_exception_counted_not_raised(self, pdir, monkeypatch):
        def boom(code):
            raise RuntimeError("source down")
        monkeypatch.setitem(fp.FETCHERS, "US", boom)
        stats = fp.update_profiles([("US", "MU", "Micron")])
        assert stats["failed"] == 1
        assert "source down" in stats["errors"][0]
