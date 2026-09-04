"""Tests for value_genie.overview and value_genie.doctor (no network)."""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from value_genie import doctor as dr
from value_genie import overview as ov


def master_df():
    rows = []
    for i in range(6):
        rows.append({
            "market": "A", "code": f"60000{i}", "name": f"A{i}",
            "industry": "food" if i % 2 else "banks",
            "price": 10.0 + i, "pe_ttm": 10.0 + i, "pb": 1.0 + i / 10,
            "rev_yoy": 5.0 + i, "roe": 10.0 + i,
            "pos_52w": 30.0 + i * 8,
            "value_score": 50.0 + i, "growth_score": 50.0 + i,
            "quality_score": 50.0 + i, "safety_score": 50.0 + i,
        })
    for i in range(4):
        rows.append({
            "market": "HK", "code": f"0000{i}", "name": f"H{i}",
            "industry": "property",
            "price": 20.0 + i, "pe_ttm": 8.0 + i, "pb": 0.8 + i / 10,
            "rev_yoy": -2.0 + i, "roe": 12.0 + i,
            "pos_52w": 40.0 + i * 5,
            "value_score": 60.0 + i, "growth_score": 40.0 + i,
            "quality_score": 55.0 + i, "safety_score": 45.0 + i,
        })
    return pd.DataFrame(rows)


def make_snap(tmp_path: Path, stale_kline: bool = False) -> Path:
    """A genuinely healthy snapshot: fresh date, full quotes for all
    markets, deep-data files above doctor's min rows, fresh klines."""
    snap = tmp_path / "snapshots" / date.today().strftime("%Y%m%d")
    snap.mkdir(parents=True, exist_ok=True)
    master_df().to_csv(snap / "master.csv", index=False)
    for mk in ("A", "HK", "US"):
        pd.DataFrame({
            "code": [f"{i:06d}" for i in range(1200)],
            "name": [f"Name{i}" for i in range(1200)],
        }).to_csv(snap / f"{mk.lower()}_quotes.csv", index=False)
    pd.DataFrame({"code": [str(i) for i in range(1200)]}
                 ).to_csv(snap / "a_financials.csv", index=False)
    pd.DataFrame({"code": [str(i) for i in range(600)]}
                 ).to_csv(snap / "us_financials.csv", index=False)
    pd.DataFrame({"code": [str(i) for i in range(60)]}
                 ).to_csv(snap / "hk_f10.csv", index=False)
    pd.DataFrame({"market": ["A"], "code": ["688795"]}
                 ).to_csv(snap / "watchlist.csv", index=False)
    kdir = snap / "kline"
    kdir.mkdir(exist_ok=True)
    end = (pd.Timestamp.today() - (pd.Timedelta(days=30)
                                   if stale_kline else pd.Timedelta(0))
           ).normalize()
    dates = pd.bdate_range(end=end, periods=300).strftime("%Y-%m-%d")
    for mk in ("A", "HK"):
        pd.DataFrame({"date": dates, "close": range(300)}).to_csv(
            kdir / f"{mk}_X.csv", index=False)
    (snap / "manifest.json").write_text(
        json.dumps({"failures": []}), encoding="utf-8")
    return snap


class TestOverview:
    def test_market_overview_structure(self, tmp_path):
        snap = make_snap(tmp_path)
        data = ov.market_overview(snapshot_dir=snap)
        assert data["snapshot"] == snap.name
        assert set(data["markets"]) == {"A", "HK"}
        a = data["markets"]["A"]
        assert a["candidates"] == 6
        assert a["median_pe"] == 12.5     # median of 10..15
        assert "food" in a["top_sectors"]
        assert len(a["top"]) == 6         # fewer rows than top_n

    def test_market_filter(self, tmp_path):
        snap = make_snap(tmp_path)
        data = ov.market_overview(snapshot_dir=snap, markets=["HK"])
        assert set(data["markets"]) == {"HK"}

    def test_render_mentions_markets(self, tmp_path):
        snap = make_snap(tmp_path)
        text = ov.render_overview(
            ov.market_overview(snapshot_dir=snap))
        assert snap.name in text
        assert "[A]" in text and "[HK]" in text


class TestDoctor:
    def test_no_snapshots_fails(self, tmp_path):
        checks = dr.run_checks(data_dir=tmp_path)
        assert checks[0][0] == "FAIL"
        assert dr.doctor_exit_code(checks) == 1

    def test_healthy_snapshot_passes(self, tmp_path):
        make_snap(tmp_path)
        checks = dr.run_checks(data_dir=tmp_path)
        statuses = {c[0] for c in checks}
        assert "FAIL" not in statuses
        assert dr.doctor_exit_code(checks) == 0

    def test_watchlist_check(self, tmp_path):
        snap = make_snap(tmp_path)
        checks = dr.run_checks(data_dir=tmp_path)
        wl = [c for c in checks if "watchlist" in c[2]]
        assert wl and wl[0][0] == "PASS"
        assert "rows: 1" in wl[0][2]
        (snap / "watchlist.csv").unlink()
        checks = dr.run_checks(data_dir=tmp_path)
        wl = [c for c in checks if "watchlist" in c[2]]
        assert wl and wl[0][0] == "WARN" and "missing" in wl[0][2]

    def test_stale_kline_warns(self, tmp_path):
        make_snap(tmp_path, stale_kline=True)
        checks = dr.run_checks(data_dir=tmp_path)
        kline_checks = [c for c in checks if "klines" in c[2]]
        assert kline_checks and kline_checks[0][0] in ("WARN", "FAIL")

    def test_render_includes_action_line(self, tmp_path):
        checks = dr.run_checks(data_dir=tmp_path)
        text = dr.render_checks(checks)
        assert "doctor" in text or "==" in text
        assert "fetch" in text        # recommended action present

    def test_freshness_gate_no_snapshot_is_fail(self, tmp_path):
        status, msg = dr.freshness_gate(data_dir=tmp_path)
        assert status == "FAIL"
        assert "no snapshots" in msg

    def test_stale_snapshot_hours_warns(self, tmp_path):
        import os
        import time
        snap = make_snap(tmp_path)
        old = time.time() - 30 * 3600  # 30h ago: beyond 24h contract
        os.utime(snap / "manifest.json", (old, old))
        checks = dr.run_checks(data_dir=tmp_path)
        age_checks = [c for c in checks if "hour(s)" in c[2]]
        assert age_checks and age_checks[0][0] == "WARN"

    def test_freshness_gate_healthy_is_pass(self, tmp_path):
        make_snap(tmp_path)
        status, msg = dr.freshness_gate(data_dir=tmp_path)
        assert status == "PASS"
        assert "fresh" in msg
