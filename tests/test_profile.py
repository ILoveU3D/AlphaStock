"""Tests for value_genie.profile (Phase 5 local-only company profiles)."""

import json

import pandas as pd
import pytest

from value_genie import config, profile as prof


@pytest.fixture
def pdir(tmp_path, monkeypatch):
    """Isolated profiles/ + raw dirs (never touch the real local data)."""
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "PROFILE_RAW_DIR",
                        tmp_path / "data" / "profiles" / "raw")
    return tmp_path


def _raw(market="A", code="600900", name="长江电力", summary="水电龙头",
         main_business="大型水电运营", vision="清洁能源"):
    return prof.new_raw(market, code, name=name,
                        source="eastmoney_f10_org_basicinfo",
                        source_url="http://example",
                        summary=summary, main_business=main_business,
                        vision=vision, meta={"chairman": "刘伟平"})


class TestRaw:
    def test_raw_roundtrip_and_hash(self, pdir):
        raw = _raw()
        p = prof.save_raw(raw)
        assert p.exists()
        assert p.parent.name == "a"           # market-lowercase subdir
        loaded = prof.load_raw("A", "600900")
        assert loaded["summary"] == "水电龙头"
        assert loaded["content_hash"] == raw["content_hash"]
        assert len(raw["content_hash"]) == 12

    def test_hash_changes_with_content(self, pdir):
        assert _raw(summary="a")["content_hash"] != \
               _raw(summary="b")["content_hash"]
        assert _raw(summary="a")["content_hash"] == \
               _raw(summary="a")["content_hash"]

    def test_code_normalized(self, pdir):
        prof.save_raw(_raw(market="HK", code="998", name="中信银行"))
        assert (config.PROFILE_RAW_DIR / "hk" / "00998.json").exists()
        assert prof.load_raw("HK", "00998")["code"] == "00998"

    def test_load_missing_returns_none(self, pdir):
        assert prof.load_raw("A", "000001") is None
        assert prof.load_assessment("A", "000001") is None

    def test_corrupt_file_raises(self, pdir):
        p = prof.raw_path("A", "600900")
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            prof.load_raw("A", "600900")


class TestAssess:
    def test_assess_writes_and_pins_raw(self, pdir):
        raw = _raw()
        prof.save_raw(raw)
        a = prof.assess("A", "600900", business_score=86,
                        culture_score=72, moat_type="resource_rent",
                        machine_lifecycle="mature_cashcow",
                        benfen=["长年稳定高分红"], culture_arg="央企稳健",
                        business_arg="收租机器", verdict="分红舱原型",
                        agent="kimi-k3")
        assert a["raw_hash"] == raw["content_hash"]
        assert a["raw_fetched_at"] == raw["fetched_at"]
        loaded = prof.load_assessment("A", "600900")
        assert loaded["business"]["score"] == 86.0
        assert loaded["culture"]["benfen_evidence"] == ["长年稳定高分红"]
        assert loaded["verdict"] == "分红舱原型"

    def test_assess_without_raw_pins_none(self, pdir):
        a = prof.assess("US", "HRMY", culture_score=70)
        assert a["raw_hash"] is None
        assert a["raw_fetched_at"] is None

    def test_score_bounds(self, pdir):
        with pytest.raises(ValueError):
            prof.assess("A", "600900", culture_score=101)
        with pytest.raises(ValueError):
            prof.assess("A", "600900", business_score=-1)
        with pytest.raises(ValueError):
            prof.assess("A", "600900", culture_score="high")

    def test_at_least_one_score_required(self, pdir):
        with pytest.raises(ValueError):
            prof.assess("A", "600900", verdict="notes only")

    def test_name_falls_back_to_raw(self, pdir):
        prof.save_raw(_raw(name="长江电力"))
        a = prof.assess("A", "600900", culture_score=72)
        assert a["name"] == "长江电力"


class TestStaleness:
    def test_stale_when_raw_hash_changes(self, pdir):
        prof.save_raw(_raw(summary="v1"))
        a = prof.assess("A", "600900", culture_score=72)
        assert not prof.is_stale(a, prof.load_raw("A", "600900"))
        prof.save_raw(_raw(summary="v2 changed"))
        assert prof.is_stale(a, prof.load_raw("A", "600900"))

    def test_missing_raw_is_not_stale(self, pdir):
        a = prof.assess("A", "600900", culture_score=72)
        assert not prof.is_stale(a, None)

    def test_stale_excluded_from_culture_scores(self, pdir):
        prof.save_raw(_raw(summary="v1"))
        prof.assess("A", "600900", culture_score=72)
        assert prof.load_culture_scores() == {"A:600900": 72.0}
        prof.save_raw(_raw(summary="v2 changed"))
        assert prof.load_culture_scores() == {}
        assert prof.load_culture_scores(include_stale=True) == \
            {"A:600900": 72.0}


class TestCultureScores:
    def test_collects_and_normalizes(self, pdir):
        prof.assess("A", "600900", culture_score=72)
        prof.assess("HK", "998", culture_score=60)   # -> 00998
        prof.assess("US", "NVDA", business_score=95)  # no culture score
        assert prof.load_culture_scores() == {"A:600900": 72.0,
                                              "HK:00998": 60.0}

    def test_empty_dir(self, pdir):
        assert prof.load_culture_scores() == {}
        assert prof.list_assessments() == []


class TestApplyDistilledCulture:
    def _frame(self):
        return pd.DataFrame({
            "market": ["A", "A", "US"],
            "code": ["600900", "000001", "NVDA"],
            "core_business": [80.0, 60.0, 90.0],
            "core_culture": [float("nan")] * 3,
            "core_dcf": [50.0, 40.0, 20.0],
            "core_score": [65.0, 50.0, 55.0],
            "core_gaps": ["culture unscored (veto-only until profile "
                          "distillation, D3)"] * 3,
        })

    def test_overlay_recomputes_core_score(self, pdir):
        prof.assess("A", "600900", culture_score=90)
        out, n = prof.apply_distilled_culture(self._frame())
        assert n == 1
        row = out.iloc[0]
        assert row["core_culture"] == 90.0
        assert row["core_score"] == pytest.approx((80 + 90 + 50) / 3)
        assert prof.CULTURE_DISTILLED in row["core_gaps"]
        assert "veto-only" not in row["core_gaps"]
        # untouched rows stay veto-only
        assert pd.isna(out.iloc[1]["core_culture"])
        assert out.iloc[1]["core_score"] == 50.0
        assert "veto-only" in out.iloc[1]["core_gaps"]

    def test_no_scores_is_noop(self, pdir):
        df = self._frame()
        out, n = prof.apply_distilled_culture(df)
        assert n == 0
        assert out["core_score"].tolist() == df["core_score"].tolist()

    def test_missing_market_columns_safe(self, pdir):
        prof.assess("A", "600900", culture_score=90)
        out, n = prof.apply_distilled_culture(
            pd.DataFrame({"x": [1]}))
        assert n == 0


class TestImportLegacy:
    def _legacy(self, assessed=True):
        data = {"id": "A:600900", "market": "A", "code": "600900",
                "name": "长江电力", "version": 4,
                "raw": {"fetched_at": "2026-09-29T03:37:21",
                        "source": "eastmoney_f10_org_basicinfo",
                        "source_url": "http://dc",
                        "summary": "水电", "main_business": "大型水电运营",
                        "vision": "", "meta": {"chairman": "刘伟平"},
                        "content_hash": "05bc792a7034"}}
        if assessed:
            data["assessment"] = {
                "assessed_at": "2026-09-29T03:39:01",
                "raw_fetched_at": "2026-09-29T03:37:21",
                "raw_hash": "05bc792a7034", "agent": "kimi-k3",
                "business": {"score": 86.0, "moat_type": "resource_rent",
                             "machine_lifecycle": "mature_cashcow",
                             "argument": "收租机器"},
                "culture": {"score": 72.0,
                            "benfen_evidence": ["长年稳定高分红"],
                            "argument": "央企稳健"},
                "dcf": {"argument": "终值可靠"}, "verdict": "分红舱原型"}
        return data

    def test_split_migration(self, pdir, tmp_path):
        src = tmp_path / "legacy"
        (src / "a").mkdir(parents=True)
        (src / "a" / "600900.json").write_text(
            json.dumps(self._legacy(assessed=True)), encoding="utf-8")
        (src / "a" / "000001.json").write_text(
            json.dumps(self._legacy(assessed=False) | {"code": "000001",
                                                       "id": "A:000001"}),
            encoding="utf-8")
        counts = prof.import_legacy(src)
        assert counts == {"raw": 2, "assessments": 1, "skipped": 0}
        raw = prof.load_raw("A", "600900")
        assert raw["content_hash"] == "05bc792a7034"  # pinned hash kept
        a = prof.load_assessment("A", "600900")
        assert a["business"]["score"] == 86.0
        assert a["agent"] == "kimi-k3"
        assert a["raw_hash"] == "05bc792a7034"
        assert not prof.is_stale(a, raw)
        # raw-only legacy file migrated without an assessment
        assert prof.load_assessment("A", "000001") is None
        assert prof.load_raw("A", "000001") is not None
        assert prof.load_culture_scores() == {"A:600900": 72.0}


class TestGitignore:
    def test_profiles_dir_is_ignored(self):
        text = (config.BASE_DIR / ".gitignore").read_text(
            encoding="utf-8")
        ignored = {ln.strip() for ln in text.splitlines()
                   if ln.strip() and not ln.startswith("#")}
        assert "profiles/" in ignored


class TestFetchers:
    def test_a_share_payload(self, pdir, monkeypatch):
        from value_genie.fetch import profiles as pf
        payload = {"result": {"data": [{
            "SECUCODE": "600900.SH", "SECURITY_NAME_ABBR": "长江电力",
            "ORG_NAME": "中国长江电力股份有限公司",
            "ORG_PROFIE": "  中国长江电力股份有限公司是由…  ",
            "ORG_PROFILE": "领先的清洁能源供应商",
            "MAIN_BUSINESS": "大型水电运营",
            "CHAIRMAN": "刘伟平", "EM2016": "公用事业-电力-水电",
            "TOTAL_NUM": 8482, "BUSINESS_SCOPE": "电力生产…"}]}}
        monkeypatch.setattr(pf.DC, "get_json",
                            lambda *a, **k: payload)
        raw = pf.fetch_profile_a("600900")
        assert raw["name"] == "长江电力"
        assert raw["summary"].startswith("中国长江电力")
        assert raw["vision"] == "领先的清洁能源供应商"
        assert raw["main_business"] == "大型水电运营"
        assert raw["meta"]["chairman"] == "刘伟平"
        assert raw["meta"]["business_scope"] == "电力生产…"
        assert raw["source"] == "eastmoney_f10_org_basicinfo"

    def test_a_share_empty_fails_closed(self, pdir, monkeypatch):
        from value_genie.fetch import profiles as pf
        monkeypatch.setattr(pf.DC, "get_json", lambda *a, **k: None)
        assert pf.fetch_profile_a("600900") is None

    def test_hk_payload(self, pdir, monkeypatch):
        from value_genie.fetch import profiles as pf
        payload = {"result": {"data": [{
            "SECUCODE": "00998.HK", "SECURITY_NAME_ABBR": "中信银行",
            "ORG_NAME": "中信银行股份有限公司",
            "ORG_PROFILE": "  中信银行股份有限公司成立于1987年… ",
            "MAIN_BUSINESS": "向政府与机构客户…",
            "CHAIRMAN": "方合英", "EMP_NUM": 67674,
            "INDUSTRY_TYPE": "金融-银行-商业银行-综合性银行",
            "TRADE_UNIT": 1000}]}}
        monkeypatch.setattr(pf.DC, "get_json",
                            lambda *a, **k: payload)
        raw = pf.fetch_profile_hk("00998")
        assert raw["summary"].startswith("中信银行股份")
        assert raw["meta"]["trade_unit"] == "1000"  # meta is text-normalized
        assert raw["source"] == "eastmoney_hkf10_orgprofile"

    def test_us_payload(self, pdir, monkeypatch):
        from value_genie.fetch import profiles as pf
        import value_genie.fetch.fundamentals as fnd
        monkeypatch.setattr(fnd, "load_sec_cik_map",
                            lambda: {"NVDA": 1045810})
        monkeypatch.setattr(pf.SEC, "get_json", lambda *a, **k: {
            "name": "NVIDIA CORP", "sic": "3674",
            "sicDescription": "Semiconductors & Related Devices",
            "entityType": "operating", "cik": "0001045810",
            "exchanges": ["Nasdaq"]})
        monkeypatch.setattr(pf.SA, "get_text", lambda *a, **k:
                            'x description:"NVIDIA Corporation operates '
                            'as a \\"data center\\" scale AI company." y')
        raw = pf.fetch_profile_us("NVDA")
        assert raw["name"] == "NVIDIA CORP"
        assert '"data center"' in raw["summary"]   # escapes decoded
        assert raw["meta"]["sic"] == "3674"
        assert raw["source"] == "stockanalysis+sec_submissions"

    def test_us_both_sources_down_fails_closed(self, pdir, monkeypatch):
        from value_genie.fetch import profiles as pf
        import value_genie.fetch.fundamentals as fnd
        monkeypatch.setattr(fnd, "load_sec_cik_map", lambda: {})
        monkeypatch.setattr(pf.SA, "get_text", lambda *a, **k: None)
        assert pf.fetch_profile_us("NVDA") is None

    def test_update_raw_persists_and_keeps_old_on_failure(
            self, pdir, monkeypatch):
        from value_genie.fetch import profiles as pf
        prof.save_raw(_raw(summary="old"))
        monkeypatch.setattr(pf, "fetch_profile",
                            lambda m, c: None)
        assert pf.update_raw("A", "600900") is None
        assert prof.load_raw("A", "600900")["summary"] == "old"
