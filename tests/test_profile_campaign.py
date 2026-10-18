"""Tests for the full-market profile distillation campaign (network off)."""

import json

import pandas as pd
import pytest

from polar_star import config, profile as prof
from polar_star import profile_campaign as pc


class _H:
    def __init__(self, market, code, name=""):
        self.market, self.code, self.name = market, code, name


class _U:
    def __init__(self, holdings):
        self.holdings = holdings


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated profiles/ + raw dirs + fixture snapshot (never touch the
    real local data). Tier builders are the modeling campaign's own —
    patch its list_users the same way its tests do."""
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(config, "PROFILE_RAW_DIR",
                        tmp_path / "data" / "profiles" / "raw")
    monkeypatch.setattr("polar_star.model.campaign.list_users",
                        lambda: [_U([_H("A", "688795", "摩尔线程-U"),
                                     _H("US", "KO", "可口可乐")])])
    snap = tmp_path / "data" / "snapshots" / "20261018"
    snap.mkdir(parents=True)
    pd.DataFrame({"market": ["A", "A", "US"],
                  "code": ["600519", "688795", "NVDA"],
                  "name": ["贵州茅台", "摩尔线程-U", "英伟达"],
                  "core_score": [80.0, 60.0, 70.0]}
                 ).to_csv(snap / "master.csv", index=False)
    pd.DataFrame({"market": ["A"] * 4,
                  "code": ["600519", "000858", "688795", "600999"],
                  "name": ["贵州茅台", "五粮液", "摩尔线程-U", "*ST大坑"],
                  "market_cap": [2e12, 5e11, 1.8e11, 9e12],
                  "industry": ["白酒", "白酒", "半导体", "白酒"]}
                 ).to_csv(snap / "a_quotes.csv", index=False)
    pd.DataFrame({"market": ["US", "US"],
                  "code": ["NVDA", "KO"],
                  "name": ["英伟达", "可口可乐"],
                  "market_cap": [3e12, 2.6e11],
                  "industry": ["芯片", "饮料"]}
                 ).to_csv(snap / "us_quotes.csv", index=False)
    pd.DataFrame({"market": ["HK"], "code": ["00991"],
                  "name": ["大唐发电"], "market_cap": [1e10],
                  "industry": ["电力"]}
                 ).to_csv(snap / "hk_quotes.csv", index=False)
    monkeypatch.setattr(
        "polar_star.fetch.fundamentals.fetch_hk_mainindicator_batch",
        lambda report_date=None, quiet=False: pd.DataFrame(
            {"code": ["00700", "00991"],
             "report_date": ["2026-06-30"] * 2,
             "roe": [10.0, 5.0]}))
    return tmp_path


def _raw(market, code, name="测试公司", summary="一段简介"):
    return prof.new_raw(market, code, name=name, source="test",
                        source_url="http://example", summary=summary)


def _assessed(market, code, **kw):
    args = dict(business_score=70.0, business_arg="论证")
    args.update(kw)
    return prof.assess(market, code, **args)


def test_init_builds_tiered_queue(env):
    c = pc.init(str(env / "data"))
    t1 = [q["id"] for q in c["queue"] if q["tier"] == 1]
    t2 = [q["id"] for q in c["queue"] if q["tier"] == 2]
    t3 = [q["id"] for q in c["queue"] if q["tier"] == 3]
    assert t1 == ["A:688795", "US:KO"]
    assert t2 == ["A:600519", "US:NVDA"]          # core_score 80 > 70
    assert t3 == ["A:000858", "A:600999", "HK:00700", "HK:00991"]
    assert c["snapshot"] == "20261018"


def test_progress_counts_fetched_and_distilled(env):
    pc.init(str(env / "data"))
    prof.save_raw(_raw("A", "000858"))
    _assessed("A", "688795")
    p = pc.progress()
    assert p["queue_total"] == 8
    assert p["distilled"] == 1 and p["fetched"] == 1
    t3 = [t for t in p["tiers"] if t["tier"] == 3][0]
    assert t3["fetched"] == 1 and t3["distilled"] == 0
    assert p["next"][0] == "US:KO"     # A:688795 distilled, drops out


def test_stale_assessment_reenters_queue(env):
    """A distillation pinning an old raw hash is not 'done' — it comes
    back onto the work queue (re-distill before any verdict)."""
    pc.init(str(env / "data"))
    prof.save_raw(_raw("US", "KO"))
    _assessed("A", "688795")
    _assessed("US", "KO")
    assert pc.progress()["distilled"] == 2
    prof.save_raw(_raw("US", "KO", summary="改动后的简介"))  # hash moves
    p = pc.progress()
    assert p["distilled"] == 1
    rows = pc.next_targets(5)
    assert rows[0]["id"] == "US:KO"
    assert all(r["id"] != "A:688795" for r in rows)


def test_next_targets_marks_fetched(env):
    pc.init(str(env / "data"))
    rows = pc.next_targets(2)
    assert [r["id"] for r in rows] == ["A:688795", "US:KO"]
    assert all(r["fetched"] is False for r in rows)
    prof.save_raw(_raw("A", "688795"))
    assert pc.next_targets(1)[0]["fetched"] is True


def test_status_without_init(env):
    assert pc.progress() == {"initialized": False}
    assert pc.next_targets(5) == []


# --- CLI: campaign + batch assess ------------------------------------------
def test_cli_campaign_init_status_next(capsys, env):
    from polar_star import __main__ as cli
    rc = cli.main(["profile", "campaign", "init", "--data-dir",
                   str(env / "data"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["initialized"] and out["queue_total"] == 8

    rc = cli.main(["profile", "campaign", "status", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["queue_total"] == 8 and len(out["tiers"]) == 3

    rc = cli.main(["profile", "campaign", "next", "-n", "2", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["A:688795", "US:KO"]


def test_cli_assess_from_json_batch(capsys, env, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", env / "data")
    batch = [
        {"stock": "A:600519", "business_score": 88, "culture_score": 75,
         "moat_type": "品牌", "lifecycle": "成熟",
         "business_arg": "高端白酒定价权", "agent": "kimi-k3"},
        {"stock": "US:NVDA", "business_score": 82,
         "business_arg": "加速计算平台"},          # culture omitted: ok
        {"stock": "不存在公司某某某", "business_score": 50,
         "business_arg": "查无此票"},                  # resolve fails
        {"business_score": 50},                      # no stock field
        {"stock": "US:KO"},                          # no score at all
    ]
    f = env / "batch.json"
    f.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    from polar_star import __main__ as cli
    rc = cli.main(["profile", "assess", "--from-json", str(f), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1                       # partial failure -> exit 1
    assert out["ok"] == 2 and out["failed"] == 3
    a = prof.load_assessment("A", "600519")
    assert a["business"]["score"] == 88 and a["agent"] == "kimi-k3"
    a = prof.load_assessment("US", "NVDA")
    assert a["culture"]["score"] is None


# --- bulk fetch (paged fast path + fallback) --------------------------------
@pytest.fixture
def denv(tmp_path, monkeypatch):
    """Isolated raw dir for fetch-layer tests."""
    monkeypatch.setattr(config, "PROFILE_RAW_DIR",
                        tmp_path / "data" / "profiles" / "raw")
    return tmp_path


_A_ROW = {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台",
          "ORG_PROFIE": "白酒龙头简介", "MAIN_BUSINESS": "茅台酒产销",
          "ORG_PROFILE": "国酒愿景", "ORG_NAME": "贵州茅台股份有限公司"}


def _paged(rows_by_page):
    """Fake DC.get_json returning result.data per pageNumber."""
    def fake(url, params=None, **kw):
        page = int((params or {}).get("pageNumber") or 1)
        rows = rows_by_page.get(page, [])
        return {"result": {"data": rows, "pages": max(rows_by_page)}}
    return fake


def test_paged_rows_stops_at_short_page(denv, monkeypatch):
    from polar_star.fetch import profiles as pf
    monkeypatch.setattr(pf.DC, "get_json",
                        _paged({1: [_A_ROW] * 500, 2: [_A_ROW] * 37}))
    rows = pf._paged_rows(config.A_ORG_BASICINFO_REPORT)
    assert len(rows) == 537


def test_paged_rows_none_when_refused(denv, monkeypatch):
    from polar_star.fetch import profiles as pf
    monkeypatch.setattr(pf.DC, "get_json", lambda *a, **kw: None)
    assert pf._paged_rows(config.A_ORG_BASICINFO_REPORT) is None


def test_fetch_all_a_bulk_then_skip(denv, monkeypatch):
    from polar_star.fetch import profiles as pf
    monkeypatch.setattr(pf.DC, "get_json", _paged({1: [_A_ROW]}))
    rep = pf.fetch_all(markets=("A",), targets={"A": ["600519"]})
    assert rep["A"]["saved"] == 1 and rep["A"]["failed"] == 0
    assert prof.load_raw("A", "600519")["summary"] == "白酒龙头简介"
    rep = pf.fetch_all(markets=("A",), targets={"A": ["600519"]})
    assert rep["A"]["skipped"] == 1 and rep["A"]["saved"] == 0


def test_fetch_all_fallback_when_bulk_refused(denv, monkeypatch):
    from polar_star.fetch import profiles as pf
    monkeypatch.setattr(pf.DC, "get_json", lambda *a, **kw: None)
    # FETCHERS binds fetcher functions at module load — patch the dict
    monkeypatch.setitem(pf.FETCHERS, "A", lambda code: _raw("A", code))
    rep = pf.fetch_all(markets=("A",), targets={"A": ["600519"]})
    assert rep["A"]["saved"] == 1


def test_fetch_all_failure_never_clobbers(denv, monkeypatch):
    from polar_star.fetch import profiles as pf
    prof.save_raw(_raw("US", "KO", summary="旧简介"))
    monkeypatch.setitem(pf.FETCHERS, "US", lambda t: None)
    rep = pf.fetch_all(markets=("US",), targets={"US": ["KO"]},
                       force=True)
    assert rep["US"]["failed"] == 1
    assert prof.load_raw("US", "KO")["summary"] == "旧简介"
