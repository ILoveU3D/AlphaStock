"""Tests for value_genie.thesis (tower-fed pool registry, 论点喂池)."""

import json

import pandas as pd
import pytest

from value_genie import config
from value_genie import thesis as th


@pytest.fixture
def tdir(tmp_path, monkeypatch):
    d = tmp_path / "theses"
    monkeypatch.setattr(config, "THESES_DIR", d)
    twd = tmp_path / "tower"
    twd.mkdir()
    (twd / "test-brick.md").write_text("---\nid: test-brick\n---\n",
                                       encoding="utf-8")
    monkeypatch.setattr(config, "TOWER_DIR", twd)
    return d


def make_thesis(tid="memory-supercycle", members=None, **kw):
    return th.create_thesis(
        tid, name="存储超级周期", brick="test-brick",
        statement="AI 推理把存储从周期品重估为算力粮食",
        reason="周期底回升 + HBM/DDR5 需求结构性上移",
        features=["新到没被完全定价", "被技术周期需要", "技能套利"],
        falsification=["存储价格连续两季环比转负"],
        members=members or [], **kw)


# ---------------------------------------------------------------------------
class TestParseMember:
    def test_basic_forms(self):
        m = th.parse_member("A:600900")
        assert (m.market, m.code, m.name) == ("A", "600900", "")
        m = th.parse_member("HK:998:腾讯控股")
        assert (m.market, m.code, m.name) == ("HK", "00998", "腾讯控股")
        m = th.parse_member("US:mu:Micron")
        assert (m.market, m.code, m.name) == ("US", "MU", "Micron")

    def test_bad_forms(self):
        for bad in ("600900", "A:", "XX:600900", "A:600900:x:y", ":600900"):
            with pytest.raises(ValueError):
                th.parse_member(bad)


# ---------------------------------------------------------------------------
class TestRegistry:
    def test_create_load_list(self, tdir):
        t = make_thesis(members=[th.parse_member("A:603986:兆易创新"),
                                 th.parse_member("US:MU:Micron")])
        assert (tdir / "memory-supercycle.json").exists()
        got = th.load_thesis("memory-supercycle")
        assert got.brick == "test-brick"
        assert len(got.members) == 2
        assert got.members[0].code == "603986"
        assert got.features[0].startswith("新到")
        assert [x.id for x in th.list_theses()] == ["memory-supercycle"]

    def test_duplicate_and_bad_id(self, tdir):
        make_thesis()
        with pytest.raises(ValueError):
            make_thesis()
        with pytest.raises(ValueError):
            make_thesis("BAD ID!!")

    def test_duplicate_member_rejected(self, tdir):
        with pytest.raises(ValueError):
            make_thesis(members=[th.parse_member("A:603986"),
                                 th.parse_member("A:603986")])

    def test_amend_members_and_fields(self, tdir):
        make_thesis(members=[th.parse_member("A:603986")])
        t = th.amend_thesis(
            "memory-supercycle",
            add_members=[th.parse_member("US:MU:Micron")],
            add_features=["追加特征"],
            add_falsification=["追加证伪"],
            add_industry_hints={"A": ["存储器"]})
        assert len(t.members) == 2
        assert t.features[-1] == "追加特征"
        assert t.industry_hints["A"] == ["存储器"]
        with pytest.raises(ValueError):
            th.amend_thesis("memory-supercycle",
                            add_members=[th.parse_member("US:MU")])
        t = th.amend_thesis("memory-supercycle",
                            drop_members=["US:MU"])
        assert len(t.members) == 1
        with pytest.raises(ValueError):
            th.amend_thesis("memory-supercycle",
                            drop_members=["US:MU"])

    def test_retire_requires_reason_and_is_terminal(self, tdir):
        make_thesis()
        with pytest.raises(ValueError):
            th.retire_thesis("memory-supercycle", "  ")
        t = th.retire_thesis("memory-supercycle", "存储价格两季环比转负")
        assert t.status == "retired"
        assert t.retired_reason.startswith("存储价格")
        assert th.list_theses(status="active") == []
        assert len(th.list_theses(status="retired")) == 1
        with pytest.raises(ValueError):
            th.retire_thesis("memory-supercycle", "again")

    def test_remove_deletes_file(self, tdir):
        make_thesis()
        th.remove_thesis("memory-supercycle")
        assert th.list_theses() == []
        with pytest.raises(FileNotFoundError):
            th.remove_thesis("memory-supercycle")

    def test_corrupt_file_raises_value_error(self, tdir):
        make_thesis()
        p = tdir / "memory-supercycle.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            th.load_thesis("memory-supercycle")

    def test_unknown_fields_dropped_with_warning(self, tdir):
        make_thesis(members=[th.parse_member("A:603986")])
        p = tdir / "memory-supercycle.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["future_field"] = 1
        data["members"][0]["alien"] = True
        p.write_text(json.dumps(data, ensure_ascii=False),
                     encoding="utf-8")
        t = th.load_thesis("memory-supercycle")
        assert not hasattr(t, "future_field")
        assert not hasattr(t.members[0], "alien")


# ---------------------------------------------------------------------------
def make_snapshot(tmp_path):
    """Synthetic A-share snapshot: 2 gated names (1 in master, 1 to
    inject), 1 gated out by size, 1 excluded by risk name."""
    snap = tmp_path / "snap"
    snap.mkdir()
    quotes = pd.DataFrame([
        {"market": "A", "code": "600900", "name": "长江电力",
         "price": 25.0, "pe_ttm": 20.0, "pb": 2.5, "ps": 3.0,
         "market_cap": 6e11, "amount": 1e9, "industry": "电力",
         "market_id": "1"},
        {"market": "A", "code": "603986", "name": "兆易创新",
         "price": 100.0, "pe_ttm": 50.0, "pb": 5.0, "ps": 8.0,
         "market_cap": 8e10, "amount": 2e9, "industry": "半导体",
         "market_id": "1"},
        {"market": "A", "code": "300001", "name": "小盘半导体",
         "price": 5.0, "pe_ttm": 10.0, "pb": 1.0, "ps": 1.0,
         "market_cap": 1e9, "amount": 1e8, "industry": "半导体",
         "market_id": "0"},
        {"market": "A", "code": "600999", "name": "ST测试",
         "price": 3.0, "pe_ttm": 8.0, "pb": 0.8, "ps": 1.0,
         "market_cap": 5e9, "amount": 1e8, "industry": "半导体",
         "market_id": "1"},
    ])
    quotes.to_csv(snap / "a_quotes.csv", index=False)
    fin = pd.DataFrame([
        {"code": "600900", "report_date": "2026-06-30",
         "revenue": 5e10, "rev_yoy": 5.0, "profit_yoy": 6.0,
         "roe": 15.0, "gross_margin": 60.0},
        {"code": "603986", "report_date": "2026-06-30",
         "revenue": 8e9, "rev_yoy": 20.0, "profit_yoy": 30.0,
         "roe": 10.0, "gross_margin": 38.0},
        {"code": "300001", "report_date": "2026-06-30",
         "revenue": 1e9, "rev_yoy": 10.0, "profit_yoy": 10.0,
         "roe": 8.0, "gross_margin": 25.0},
        {"code": "600999", "report_date": "2026-06-30",
         "revenue": 2e9, "rev_yoy": 1.0, "profit_yoy": 1.0,
         "roe": 5.0, "gross_margin": 15.0},
    ])
    fin.to_csv(snap / "a_financials.csv", index=False)
    master = pd.DataFrame([
        {"market": "A", "code": "600900", "name": "长江电力",
         "price": 25.0, "pe_ttm": 20.0, "pb": 2.5, "roe": 15.0,
         "gross_margin": 60.0},
    ])
    return snap, master


class TestBuildPool:
    def _pool(self, tmp_path, tdir, members, live=False):
        snap, master = make_snapshot(tmp_path)
        t = make_thesis(members=members)
        return th.build_pool(snap, master, [t], live=live)

    def test_mark_inject_and_exclusions(self, tmp_path, tdir):
        members = [th.parse_member("A:600900"),      # funnel member
                   th.parse_member("A:603986:兆易创新"),  # inject
                   th.parse_member("A:300001"),      # gated out by size
                   th.parse_member("A:600000"),      # absent from quotes
                   th.parse_member("HK:00700")]      # no HK quotes file
        pool, infos = self._pool(tmp_path, tdir, members)
        info = infos[0]
        assert info["funnel"] == 1
        assert info["injected"] == 1
        reasons = {lbl: why for lbl, why in info["excluded"]}
        assert "gated" in reasons["A/300001"] or \
            "universe gates" in reasons["A/300001"]
        assert "not found" in reasons["A/600000"]
        assert "no snapshot quotes" in reasons["HK/00700"]

        funnel_row = pool[pool["code"] == "600900"].iloc[0]
        assert funnel_row["thesis"] == "memory-supercycle"
        injected = pool[pool["code"] == "603986"].iloc[0]
        assert injected["thesis"] == "memory-supercycle"
        # injected rows are pillar-scored against their market universe
        assert pd.notna(injected["value_score"])
        assert pd.notna(injected["quality_score"])
        assert injected["roe"] == 10.0
        # ST risk name is excluded by universe gates, never injected
        assert "600999" not in set(pool["code"])

    def test_thesis_max_cap(self, tmp_path, tdir, monkeypatch):
        monkeypatch.setattr(config, "THESIS_MAX", 1)
        members = [th.parse_member("A:600900"), th.parse_member("A:603986")]
        with pytest.raises(ValueError, match="THESIS_MAX"):
            self._pool(tmp_path, tdir, members)


# ---------------------------------------------------------------------------
class TestDiscover:
    def test_industry_hints_exclude_members(self, tmp_path, tdir):
        snap, _ = make_snapshot(tmp_path)
        t = make_thesis(members=[th.parse_member("A:603986:兆易创新")],
                        industry_hints={"A": ["半导体"]})
        out = th.discover(snap, t)
        codes = set(out["code"])
        assert "300001" in codes          # quotes-level, not gated here
        assert "603986" not in codes      # already a member
        assert "600900" not in codes      # different industry
        assert list(out["market"].unique()) == ["A"]

    def test_no_hints_empty(self, tmp_path, tdir):
        snap, _ = make_snapshot(tmp_path)
        t = make_thesis(members=[th.parse_member("A:603986")])
        assert th.discover(snap, t).empty
