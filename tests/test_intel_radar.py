"""Tests for value_genie.intel.radar (no network)."""

from datetime import date, timedelta

import pandas as pd

from value_genie.intel import radar


def _snap(tmp_path, fins=None, cfs=None):
    snap = tmp_path / "snapshots" / date.today().strftime("%Y%m%d")
    snap.mkdir(parents=True)
    pd.DataFrame(fins if fins is not None else [
        {"code": "600519", "report_date": "2026-06-30", "revenue": 1e10,
         "rev_yoy": 15.0, "profit": 1.5e9, "roe": 15.0,
         "gross_margin": 50.0},
        {"code": "000858", "report_date": "2026-06-30", "revenue": 5e9,
         "rev_yoy": 10.0, "profit": 8e8, "roe": 12.0,
         "gross_margin": 45.0},
    ]).to_csv(snap / "a_financials.csv", index=False)
    if cfs is not None:
        pd.DataFrame(cfs).to_csv(snap / "a_cashflow.csv", index=False)
    return snap


def _master(codes=("600519", "000858")):
    return pd.DataFrame({"market": "A", "code": list(codes),
                         "name": [f"N{c}" for c in codes]})


def _stub_empty(monkeypatch, **overrides):
    """Patch every radar fetcher to an empty table unless overridden."""
    def empty(*a, **k):
        return pd.DataFrame()

    for name in ("fetch_a_unlocks", "fetch_a_holder_changes",
                 "fetch_a_buybacks", "fetch_a_placements",
                 "fetch_a_forecasts", "fetch_a_appointments",
                 "fetch_a_balance"):
        if name not in overrides:
            monkeypatch.setattr(radar, name, empty)
    for name, fn in overrides.items():
        monkeypatch.setattr(radar, name, fn)


def test_unlock_windows_and_red_flag(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    d60 = (date.today() + timedelta(days=60)).isoformat()
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: pd.DataFrame([
        {"code": "600519", "name": "A", "free_date": d10,
         "unlock_pct": 8.0, "lift_cap_wan": 1e6},
        {"code": "600519", "name": "A", "free_date": d60,
         "unlock_pct": 4.0, "lift_cap_wan": 5e5},
    ]))
    out = radar.build_event_radar(snap, _master(), None)
    row = out[out["code"] == "600519"].iloc[0]
    assert row["unlock_pct_30d"] == 8.0
    assert row["unlock_pct_90d"] == 12.0           # 8 + 4 累加
    assert row["intel_red"] == 1.0                 # 30d >= 5%
    r858 = out[out["code"] == "000858"].iloc[0]
    assert r858["unlock_pct_30d"] == 0.0           # 无事件 = 正面确认 0
    assert r858["intel_red"] == 0.0


def test_source_failure_is_nan_fail_closed(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: None)
    out = radar.build_event_radar(snap, _master(), None)
    row = out.iloc[0]
    assert pd.isna(row["unlock_pct_30d"])
    assert pd.isna(row["unlock_pct_90d"])
    assert pd.isna(row["intel_red"])       # 无法确认无红旗 -> NaN
    assert row["holder_cut_flag"] == 0.0   # 其余源仍为正面确认


def test_holder_cut_ongoing_window(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_holder_changes=lambda s: pd.DataFrame([
        # 进行中减持（end_date 在未来）-> flag
        {"code": "600519", "name": "A", "direction": "减持",
         "change_num_wan": 10.0, "notice_date": "2026-08-01",
         "end_date": (date.today() + timedelta(days=5)).isoformat(),
         "holder_name": "H1"},
        # 已截止减持（end_date 在过去）-> 不 flag
        {"code": "000858", "name": "B", "direction": "减持",
         "change_num_wan": 10.0, "notice_date": "2026-08-01",
         "end_date": (date.today() - timedelta(days=1)).isoformat(),
         "holder_name": "H2"},
        # 增持永不 flag
        {"code": "600519", "name": "A", "direction": "增持",
         "change_num_wan": 10.0, "notice_date": "2026-08-01",
         "end_date": (date.today() + timedelta(days=5)).isoformat(),
         "holder_name": "H3"},
    ]))
    out = radar.build_event_radar(snap, _master(), None)
    assert out[out["code"] == "600519"].iloc[0]["holder_cut_flag"] == 1.0
    assert out[out["code"] == "000858"].iloc[0]["holder_cut_flag"] == 0.0
    assert out[out["code"] == "600519"].iloc[0]["intel_red"] == 1.0


def test_dilution_and_buyback_flags(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch,
        fetch_a_placements=lambda s: pd.DataFrame([
            {"code": "600519", "name": "A", "issue_date": "2026-08-15",
             "issue_num": 1e7, "net_raise": 2e9, "dilution_pct": 1.0,
             "seo_type": "定向增发"}]),
        fetch_a_buybacks=lambda s: pd.DataFrame([
            {"code": "000858", "name": "B", "amount_yuan": 5e8,
             "shares": 2e7, "announce_date": "2026-09-01"}]))
    out = radar.build_event_radar(snap, _master(), None)
    assert out[out["code"] == "600519"].iloc[0]["dilution_flag"] == 1.0
    assert out[out["code"] == "000858"].iloc[0]["buyback_active"] == 1.0
    # 回购是正面信号：不触发 intel_red
    assert out[out["code"] == "000858"].iloc[0]["intel_red"] == 0.0


def test_report_due_and_forecast_direction(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d20 = (date.today() + timedelta(days=20)).isoformat()
    _stub_empty(monkeypatch,
        fetch_a_appointments=lambda s, e: pd.DataFrame([
            {"code": "600519", "name": "A", "appoint_date": d20,
             "is_published": "0", "report_type": "三季报"},
            {"code": "000858", "name": "B", "appoint_date": d20,
             "is_published": "1", "report_type": "三季报"},  # 已披露->忽略
        ]),
        fetch_a_forecasts=lambda s: pd.DataFrame([
            {"code": "600519", "name": "A", "predict_type": "首亏",
             "change_pct": -120.0, "notice_date": "2026-08-30"}]))
    out = radar.build_event_radar(snap, _master(), None)
    assert out[out["code"] == "600519"].iloc[0]["report_due_days"] == 20
    assert out[out["code"] == "000858"].iloc[0]["report_due_days"] == 999
    assert out[out["code"] == "600519"].iloc[0]["forecast_flag"] == -1
    assert out[out["code"] == "000858"].iloc[0]["forecast_flag"] == 0.0


def test_eq_flags_from_snapshot_financials(tmp_path, monkeypatch):
    snap = _snap(tmp_path, cfs=[{"code": "600519", "ocf": 1e8},
                                {"code": "000858", "ocf": 9e8}])
    _stub_empty(monkeypatch, fetch_a_balance=lambda rd: pd.DataFrame([
        {"code": "600519", "rece_yoy": 40.0, "inv_yoy": 5.0,
         "receivable": 1e9, "inventory": 1e9, "report_date": rd},
        {"code": "000858", "rece_yoy": 12.0, "inv_yoy": 11.0,
         "receivable": 1e8, "inventory": 1e8, "report_date": rd},
    ]))
    out = radar.build_event_radar(snap, _master(), None)
    # 600519: 应收 40 > 15+10 -> eq_receivables; OCF/净利 0.067 < 0.5 -> eq_ocf_gap
    assert out[out["code"] == "600519"].iloc[0]["eq_flags"] == 2
    r858 = out[out["code"] == "000858"].iloc[0]
    assert r858["eq_flags"] == 0      # 12 < 20; OCF/净利 1.125
    assert r858["intel_red"] == 0.0   # eq 2 < EQ_FLAG_RED=3


def test_eq_nan_when_balance_fails(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_balance=lambda rd: None)
    out = radar.build_event_radar(snap, _master(), None)
    assert pd.isna(out.iloc[0]["eq_flags"])
    assert pd.isna(out.iloc[0]["intel_red"])
    assert out.iloc[0]["unlock_pct_30d"] == 0.0   # 其余列不受影响


def test_event_radar_detail_csv(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    _stub_empty(monkeypatch,
        fetch_a_unlocks=lambda s, e: pd.DataFrame([
            {"code": "600519", "name": "A", "free_date": d10,
             "unlock_pct": 8.0, "lift_cap_wan": 1e6}]),
        fetch_a_holder_changes=lambda s: pd.DataFrame([
            {"code": "000858", "name": "B", "direction": "减持",
             "change_num_wan": 100.0, "notice_date": "2026-08-01",
             "end_date": date.today().isoformat(), "holder_name": "H"}]))
    out = radar.build_event_radar(snap, _master(), None)
    detail = pd.read_csv(snap / "event_radar.csv", dtype={"code": str})
    kinds = dict(zip(detail["code"], detail["kind"]))
    assert kinds["600519"] == "unlock"
    assert kinds["000858"] == "holder_cut"
    u = detail[detail["kind"] == "unlock"].iloc[0]
    assert u["impact"] == "negative"
    assert u["subsystem"] == "announcements"
    import json
    assert json.loads(u["payload"])["unlock_pct"] == 8.0


def test_detail_rows_scoped_to_universe(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: pd.DataFrame([
        {"code": "600519", "name": "A", "free_date": d10,
         "unlock_pct": 8.0, "lift_cap_wan": 1e6},
        {"code": "601398", "name": "NotInUniverse", "free_date": d10,
         "unlock_pct": 3.0, "lift_cap_wan": 1e5}]))
    radar.build_event_radar(snap, _master(), None)
    detail = pd.read_csv(snap / "event_radar.csv", dtype={"code": str})
    assert set(detail["code"]) == {"600519"}   # 非候选股不进明细


def test_same_day_rerun_reuses_saved_tables(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    calls = []

    def unlock_fetch(s, e):
        calls.append(1)
        return pd.DataFrame([
            {"code": "600519", "name": "A", "free_date": d10,
             "unlock_pct": 8.0, "lift_cap_wan": 1e6}])

    _stub_empty(monkeypatch, fetch_a_unlocks=unlock_fetch)
    radar.build_event_radar(snap, _master(), None)
    out2 = radar.build_event_radar(snap, _master(), None)
    assert len(calls) == 1                      # 当日表落盘后被复用
    assert out2[out2["code"] == "600519"].iloc[0][
        "unlock_pct_30d"] == 8.0


def test_non_a_universe_writes_empty_detail(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    master = pd.DataFrame({"market": ["US"], "code": ["AAPL"]})
    called = []

    def unlock_fetch(s, e):
        called.append(1)
        return pd.DataFrame()

    _stub_empty(monkeypatch, fetch_a_unlocks=unlock_fetch)
    out = radar.build_event_radar(snap, master, None)
    assert out is None                       # 无 A 覆盖 -> 不合并
    assert not called                        # 不发起任何 A 股抓取
    assert (snap / "event_radar.csv").exists()


def test_watchlist_codes_join_the_universe(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    d10 = (date.today() + timedelta(days=10)).isoformat()
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: pd.DataFrame([
        {"code": "688795", "name": "摩尔线程-U", "free_date": d10,
         "unlock_pct": 12.0, "lift_cap_wan": 2e5}]))
    master = _master()                       # 漏斗内的 600519/000858
    watch = pd.DataFrame({"market": ["A"], "code": ["688795"],
                          "name": ["摩尔线程-U"]})
    out = radar.build_event_radar(snap, master, watch)
    row = out[out["code"] == "688795"].iloc[0]   # 持仓进雷达覆盖
    assert row["unlock_pct_30d"] == 12.0
    assert row["intel_red"] == 1.0


def test_merge_radar_no_duplicate_columns():
    master = pd.DataFrame({"market": ["A", "HK"],
                           "code": ["600519", "00700"],
                           "price": [10.0, 20.0]})
    # 模拟 build_master reindex 已经补出的 NaN 雷达列
    for c in radar.RADAR_COLUMNS:
        master[c] = float("nan")
    radar_df = pd.DataFrame(
        {"market": ["A"], "code": ["600519"],
         **{c: [0.0] for c in radar.RADAR_COLUMNS}})
    out = radar.merge_radar(master, radar_df)
    assert "unlock_pct_30d_x" not in out.columns     # 无 _x/_y 重复列
    assert out[out["code"] == "600519"].iloc[0][
        "unlock_pct_30d"] == 0.0
    assert pd.isna(out[out["code"] == "00700"].iloc[0][
        "unlock_pct_30d"])                          # 未覆盖市场 = NaN


def test_source_failures_recorded_in_manifest(tmp_path, monkeypatch):
    snap = _snap(tmp_path)
    _stub_empty(monkeypatch, fetch_a_unlocks=lambda s, e: None,
                fetch_a_buybacks=lambda s: None)
    manifest = {"datasets": {}, "failures": []}
    radar.build_event_radar(snap, _master(), None, manifest=manifest)
    assert any("A unlocks" in f for f in manifest["failures"])
    assert any("A buybacks" in f for f in manifest["failures"])
