"""Tests for the full-market modeling campaign queue (network off)."""

import json

import pandas as pd
import pytest

from value_genie import config
from value_genie.model import campaign as mc


class _H:
    def __init__(self, market, code, name=""):
        self.market, self.code, self.name = market, code, name


class _U:
    def __init__(self, holdings):
        self.holdings = holdings


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(mc, "list_users",
                        lambda: [_U([_H("A", "688795", "摩尔线程-U"),
                                     _H("US", "KO", "可口可乐")])])
    snap = tmp_path / "data" / "snapshots" / "20261004"
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
    # the real batch fetcher returns HK_BATCH_MAP-renamed columns
    # (code/...), not the raw SECURITY_CODE field names
    monkeypatch.setattr(
        "value_genie.fetch.fundamentals.fetch_hk_mainindicator_batch",
        lambda report_date=None, quiet=False: pd.DataFrame(
            {"code": ["00700", "00991"],
             "report_date": ["2026-06-30"] * 2,
             "roe": [10.0, 5.0]}))
    return tmp_path


def _gathered(market, code):
    from value_genie.model import store
    d = store.raw_dir(market, code)
    d.mkdir(parents=True, exist_ok=True)
    (d / "history.json").write_text("{}", encoding="utf-8")


def test_init_builds_tiered_queue(env):
    c = mc.init(str(env / "data"))
    t1 = [q["id"] for q in c["queue"] if q["tier"] == 1]
    t2 = [q["id"] for q in c["queue"] if q["tier"] == 2]
    t3 = [q["id"] for q in c["queue"] if q["tier"] == 3]
    assert t1 == ["A:688795", "US:KO"]
    assert t2 == ["A:600519", "US:NVDA"]          # core_score 80 > 70
    # ST sinks to the A tail despite the biggest cap; HK from the batch
    assert t3 == ["A:000858", "A:600999", "HK:00700", "HK:00991"]
    assert c["snapshot"] == "20261004"


def test_progress_counts_ready_and_modeled(env):
    mc.init(str(env / "data"))
    _gathered("A", "000858")
    p = mc.progress()
    assert p["queue_total"] == 8
    t3 = [t for t in p["tiers"] if t["tier"] == 3][0]
    assert t3["ready"] == 1 and t3["modeled"] == 0
    assert p["ready"] == 1 and p["modeled"] == 0


def test_modeled_requires_complete_dossier(env):
    mc.init(str(env / "data"))
    from value_genie.model import archive as marc
    marc.save_archive(marc.new_archive("A", "600519", name="茅台"))
    p = mc.progress()
    assert p["modeled"] == 0
    assert "A:600519" in p["incomplete_dossiers"]


def test_next_targets_marks_gathered(env):
    mc.init(str(env / "data"))
    rows = mc.next_targets(3)
    assert [r["id"] for r in rows] == ["A:688795", "US:KO", "A:600519"]
    assert all(r["gathered"] is False for r in rows)
    _gathered("A", "688795")
    rows = mc.next_targets(1)
    assert rows[0]["gathered"] is True


def test_gather_batch_records_failures(env, monkeypatch):
    mc.init(str(env / "data"))
    calls = []

    def fake_gather(market, code, snap_dir=None, force=False, peers=None):
        calls.append(f"{market}:{code}")
        if code == "600519":
            raise RuntimeError("boom")
        return {"id": f"{market}:{code}", "raw_dir": "/x",
                "gathered": {"history": "/x/history.json"}, "gaps": []}

    monkeypatch.setattr("value_genie.model.gather.gather", fake_gather)
    rep = mc.gather_batch(3)
    assert rep["ok"] == 2 and rep["failed"] == 1
    assert calls == ["A:688795", "US:KO", "A:600519"]
    c = mc.load_campaign()
    assert c["failures"]["A:600519"]["count"] == 1


def test_gather_batch_backlog_cap(env, monkeypatch):
    mc.init(str(env / "data"))
    monkeypatch.setattr(
        "value_genie.model.gather.gather",
        lambda m, c, snap_dir=None, force=False, peers=None:
        {"id": f"{m}:{c}", "raw_dir": "/x",
         "gathered": {"history": "/x/history.json"}, "gaps": []})
    rep = mc.gather_batch(5, backlog_cap=0)
    assert rep["attempted"] == 0


def test_gather_parks_after_fail_max(env, monkeypatch):
    mc.init(str(env / "data"))

    def boom(market, code, snap_dir=None, force=False, peers=None):
        raise RuntimeError("no data")

    monkeypatch.setattr("value_genie.model.gather.gather", boom)
    for _ in range(mc.FAIL_MAX):
        mc.gather_batch(1)
    p = mc.progress()
    assert "A:688795" in p["parked"]
    rep = mc.gather_batch(1)
    assert rep["attempted"] == 1
    assert rep["results"][0]["id"] == "US:KO"   # parked A:688795 skipped


def test_cli_campaign_init_status_next(capsys, env):
    from value_genie import __main__ as cli
    rc = cli.main(["model", "campaign", "init", "--data-dir",
                   str(env / "data"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["initialized"] and out["queue_total"] == 8

    rc = cli.main(["model", "campaign", "status", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["queue_total"] == 8 and len(out["tiers"]) == 3

    rc = cli.main(["model", "campaign", "next", "-n", "3", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["id"] == "A:688795" and rows[0]["tier"] == 1


def test_cli_campaign_status_without_init(capsys, env):
    from value_genie import __main__ as cli
    assert cli.main(["model", "campaign", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"initialized": False}


def test_hk_batch_renamed_columns_and_names_join(env):
    """Regression (2026-10-04): fetch_hk_mainindicator_batch returns
    HK_BATCH_MAP-renamed columns (code, ...), not raw SECURITY_CODE —
    the old check silently dropped ~2,200 HK names; names join from
    snapshot hk_quotes."""
    mc.init(str(env / "data"))
    hk = {q["id"]: q for q in mc.load_campaign()["queue"]
          if q["id"].startswith("HK:")}
    assert set(hk) == {"HK:00700", "HK:00991"}
    assert hk["HK:00991"]["name"] == "大唐发电"   # joined from hk_quotes
    assert hk["HK:00700"]["name"] == ""           # batch carries no names


def test_holdings_from_user_profile_objects(env, monkeypatch):
    """Regression (2026-10-04): list_users() returns UserProfile objects,
    not ids — the old code fed profiles into load_user() and the
    swallowed exception emptied tier 1."""
    class _Prof:
        holdings = [_H("US", "ZM", "Zoom通讯")]
    monkeypatch.setattr(mc, "list_users", lambda: [_Prof()])
    t = mc.holdings_targets()
    assert [x["id"] for x in t] == ["US:ZM"]


# --- hourly monitor (scheduled-task entry point) -------------------------
def _hermetic(monkeypatch, env):
    monkeypatch.setattr(config, "DATA_DIR", env / "data")


def test_monitor_pass_logs_progress(env, monkeypatch):
    _hermetic(monkeypatch, env)
    mc.init(str(env / "data"))

    def fake(m, c, snap_dir=None, force=False, peers=None):
        _gathered(m, c)          # ready counts derive from disk
        return {"id": f"{m}:{c}", "raw_dir": "/x",
                "gathered": {"history": "/x/history.json"}, "gaps": []}

    monkeypatch.setattr("value_genie.model.gather.gather", fake)
    rep = mc.monitor_pass(gather_n=2, retire_task=False)
    assert rep["ok"] is True and rep["complete"] is False
    log = mc.monitor_log_path().read_text(encoding="utf-8")
    assert "monitor: modeled 0/8" in log
    assert "ready 2/300" in log
    assert "CAMPAIGN COMPLETE" not in log


def test_monitor_pass_without_campaign(env):
    rep = mc.monitor_pass(retire_task=False)
    assert rep["ok"] is False and rep["error"] == "no campaign"
    log = mc.monitor_log_path().read_text(encoding="utf-8")
    assert "no campaign under models/" in log


def test_monitor_retires_when_complete(env, monkeypatch):
    _hermetic(monkeypatch, env)
    mc.init(str(env / "data"))
    monkeypatch.setattr(mc, "_modeled_ids",
                        lambda: {q["id"]
                                 for q in mc.load_campaign()["queue"]})
    calls = []
    monkeypatch.setattr(mc, "_retire_scheduled_task",
                        lambda: calls.append(1) or True)
    rep = mc.monitor_pass(gather_n=0)
    assert rep["complete"] is True and rep["retired"] is True
    assert calls == [1]
    log = mc.monitor_log_path().read_text(encoding="utf-8")
    assert "CAMPAIGN COMPLETE — 8/8" in log


def test_cli_campaign_monitor(capsys, env, monkeypatch):
    _hermetic(monkeypatch, env)
    mc.init(str(env / "data"))
    monkeypatch.setattr(
        "value_genie.model.gather.gather",
        lambda m, c, snap_dir=None, force=False, peers=None:
        {"id": f"{m}:{c}", "raw_dir": "/x",
         "gathered": {"history": "/x/history.json"}, "gaps": []})
    from value_genie import __main__ as cli
    assert cli.main(["model", "campaign", "monitor", "-n", "1",
                     "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["complete"] is False
    assert out["progress"]["queue_total"] == 8
