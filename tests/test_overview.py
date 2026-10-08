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
    pd.DataFrame(columns=["market", "code", "name", "subsystem", "kind",
                          "event_date", "impact", "title", "url",
                          "source", "payload"]).to_csv(
        snap / "event_radar.csv", index=False)
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

    def test_event_radar_check(self, tmp_path):
        snap = make_snap(tmp_path)
        checks = dr.run_checks(data_dir=tmp_path)
        er = [c for c in checks if "event_radar" in c[2]]
        assert er and er[0][0] == "PASS"       # 0 rows is valid (P1)
        (snap / "event_radar.csv").unlink()
        checks = dr.run_checks(data_dir=tmp_path)
        er = [c for c in checks if "event_radar" in c[2]]
        assert er and er[0][0] == "WARN" and "missing" in er[0][2]

    def test_stale_kline_warns(self, tmp_path):
        make_snap(tmp_path, stale_kline=True)
        checks = dr.run_checks(data_dir=tmp_path)
        kline_checks = [c for c in checks if "klines" in c[2]]
        assert kline_checks and kline_checks[0][0] in ("WARN", "FAIL")

    def test_core_gap_rates_reported(self, tmp_path):
        """D2: per-market three-core missing rates; >25% warns so the
        source gets repaired (imputation patches rankings, not data)."""
        snap = make_snap(tmp_path)
        m = pd.read_csv(snap / "master.csv")
        gaps = ["core_dcf imputed = A market mean (no annual FCF)"
                if i < 2 else None for i in range(6)] + [None] * 4
        m["core_gaps"] = gaps
        m.to_csv(snap / "master.csv", index=False)
        checks = dr.run_checks(data_dir=tmp_path)
        cg = [c for c in checks if "core gaps" in c[2]]
        assert len(cg) == 2                       # A and HK only
        a = next(c for c in cg if c[1] == "A")
        hk = next(c for c in cg if c[1] == "HK")
        assert a[0] == "WARN" and "dcf 33%" in a[2]      # 2/6 = 33%
        assert hk[0] == "PASS" and "dcf 0%" in hk[2]

    def test_core_gaps_skipped_without_columns(self, tmp_path):
        make_snap(tmp_path)      # master.csv has no core_gaps column
        checks = dr.run_checks(data_dir=tmp_path)
        assert not [c for c in checks if "core gaps" in c[2]]

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

    # ------------------------------------------------------------------
    # Calendar-aware age rows (user mandate 2026-10-08): a closed-market
    # day only requires data as of the last completed session's close.
    # ------------------------------------------------------------------
    @staticmethod
    def _close_ts_map(now):
        from value_genie import calendar
        return {mk: calendar.session_close_dt(
                    mk, calendar.last_completed_session(mk, now))
                .isoformat()
                for mk in ("A", "HK", "US")}

    def test_closed_day_as_of_last_close_passes(self, tmp_path):
        """Sunday mid-Golden-Week: every market's data pinned at its last
        session close -> market rows PASS, global age row exempted."""
        import os
        from datetime import datetime
        snap = make_snap(tmp_path)
        now = datetime(2026, 10, 4, 12, 0)          # Sunday, A+HK closed
        manifest = {"failures": [],
                    "market_at": self._close_ts_map(now),
                    "carried_markets": ["HK"]}
        (snap / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        old = datetime(2026, 10, 2, 12, 0).timestamp()  # 48h before `now`
        os.utime(snap / "manifest.json", (old, old))
        checks = dr.run_checks(data_dir=tmp_path, now=now)
        close_rows = [c for c in checks if "data as of last close" in c[2]]
        assert len(close_rows) == 3
        assert all(c[0] == "PASS" for c in close_rows)
        hk = next(c for c in close_rows if c[1] == "HK")
        assert "carried" in hk[2]
        age = [c for c in checks if "hour(s)" in c[2]]
        assert age and age[0][0] == "PASS"        # exempted, not WARN
        assert "as of last close" in age[0][2]
        assert not [c for c in checks if c[0] == "FAIL"]

    def test_trading_day_30h_snapshot_warns(self, tmp_path):
        """On a trading day the 24h wall-clock contract still applies."""
        import os
        from datetime import datetime
        snap = make_snap(tmp_path)
        now = datetime(2026, 10, 9, 18, 0)          # Friday, after close
        ts = datetime(2026, 10, 8, 12, 0)           # 30h old, pre-close
        manifest = {"failures": [],
                    "market_at": {mk: ts.isoformat()
                                  for mk in ("A", "HK", "US")}}
        (snap / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        old = ts.timestamp()
        os.utime(snap / "manifest.json", (old, old))
        checks = dr.run_checks(data_dir=tmp_path, now=now)
        age = [c for c in checks if "hour(s)" in c[2]]
        assert age and age[0][0] == "WARN"
        stale = [c for c in checks if "stale vs last close" in c[2]]
        assert stale and all(c[0] == "WARN" for c in stale)

    def test_market_at_ages_are_per_market(self, tmp_path):
        """A partial fetch refreshes only its own market's timestamp."""
        from datetime import datetime
        from value_genie import calendar
        snap = make_snap(tmp_path)
        now = datetime(2026, 10, 9, 18, 0)          # Friday, after close
        fresh = calendar.session_close_dt(
            "US", calendar.last_completed_session("US", now)).isoformat()
        manifest = {"failures": [],
                    "market_at": {"A": "2026-10-08T12:00:00",
                                  "HK": "2026-10-08T12:00:00",
                                  "US": fresh}}
        (snap / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        checks = dr.run_checks(data_dir=tmp_path, now=now)
        us = next(c for c in checks
                  if c[1] == "US" and "last close" in c[2])
        a = next(c for c in checks
                 if c[1] == "A" and "last close" in c[2])
        assert us[0] == "PASS" and "as of last close" in us[2]
        assert a[0] == "WARN" and "stale vs last close" in a[2]

    def test_agent_rule_machine_form(self, tmp_path):
        """agent_rule: closed + as-of-close -> no fetch; in-session with
        >1h data -> fetch (the 1-hour iron rule, machine-readable)."""
        from datetime import datetime, timedelta
        from value_genie import calendar
        snap = make_snap(tmp_path)
        closed_now = datetime(2026, 10, 4, 12, 0)   # Sunday
        manifest = {"market_at": self._close_ts_map(closed_now)}
        rule = dr.agent_rule(snap, manifest, closed_now)
        assert set(rule) == {"A", "HK", "US"}
        assert all(not r["needs_fetch"] for r in rule.values())
        assert all(r["reason"] == "ok" for r in rule.values())
        # in-session, 2h-old data -> must fetch (trading-day iron rule)
        open_now = datetime(2026, 10, 9, 10, 30)    # Friday A session
        assert calendar.in_session("A", open_now)
        old = (open_now - timedelta(hours=2)).isoformat()
        rule = dr.agent_rule(snap, {"market_at": {"A": old}}, open_now)
        assert rule["A"]["needs_fetch"]
        assert rule["A"]["reason"] == "in_session&age>1h"
        assert rule["A"]["age_hours"] == 2.0
        # stale beyond the last completed session's close -> fetch
        rule = dr.agent_rule(
            snap, {"market_at": {"A": "2026-09-30T12:00:00"}}, open_now)
        assert rule["A"]["needs_fetch"]
        assert rule["A"]["reason"] == "stale_beyond_last_close"

    def test_doctor_json_contains_agent_rule(self, tmp_path):
        make_snap(tmp_path)
        checks = dr.run_checks(data_dir=tmp_path)
        payload = json.loads(dr.to_json(checks, data_dir=tmp_path))
        assert "agent_rule" in payload
        assert set(payload["agent_rule"]) == {"A", "HK", "US"}
        a = payload["agent_rule"]["A"]
        assert {"needs_fetch", "reason", "age_hours"} <= set(a)

    def test_degraded_quotes_source_warns(self, tmp_path):
        snap = make_snap(tmp_path)
        manifest = {"failures": [],
                    "datasets": {"A": {"source": "tencent"}}}
        (snap / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        checks = dr.run_checks(data_dir=tmp_path)
        deg = [c for c in checks if "source=tencent" in c[2]]
        assert deg and deg[0][0] == "WARN" and deg[0][1] == "A"

    def test_freshness_gate_market_scope(self, tmp_path):
        """A-share holiday kline lag must not block a US answer: scoping
        the gate to US drops the A/HK per-market FAIL rows while global
        rows still apply (National-Day artifact, 2026-10-08)."""
        from datetime import datetime
        snap = make_snap(tmp_path, stale_kline=True)
        # pretend the fetch happened just now: per-market age rows PASS
        now_iso = datetime.now().isoformat(timespec="seconds")
        (snap / "manifest.json").write_text(json.dumps(
            {"failures": [],
             "market_at": {mk: now_iso for mk in ("A", "HK", "US")}}),
            encoding="utf-8")
        status_all, _ = dr.freshness_gate(data_dir=tmp_path)
        assert status_all == "FAIL"               # A klines are ancient
        status_us, msg = dr.freshness_gate(data_dir=tmp_path, market="US")
        assert status_us == "PASS", msg
