"""Tests for value_genie.analyze (no network)."""

from pathlib import Path

import pandas as pd

from value_genie import analyze as az
from value_genie.resolve import Match


class TestPercentile:
    def test_higher_is_better(self):
        s = pd.Series([1, 2, 3, 4, 5])
        assert az.percentile(5, s) == 90.0
        assert az.percentile(1, s) == 10.0

    def test_lower_is_better_inverted(self):
        s = pd.Series([10, 20, 30, 40, 50])
        assert az.percentile(10, s, lower_is_better=True) == 90.0
        assert az.percentile(50, s, lower_is_better=True) == 10.0

    def test_nan_value_returns_none(self):
        assert az.percentile(float("nan"), pd.Series([1, 2])) is None


class TestVerdictBand:
    def test_bands(self):
        assert az.verdict_band(90) == "outstanding opportunity"
        assert az.verdict_band(75) == "attractive"
        assert az.verdict_band(50) == "reasonable"
        assert az.verdict_band(25) == "unattractive"
        assert az.verdict_band(5) == "poor"
        assert "inconclusive" in az.verdict_band(None)


class TestRiskFlags:
    def _result(self, **over):
        r = {"quote": {}, "fundamentals": {}, "kline": {}, "warnings": []}
        r.update(over)
        return r

    def test_flags_fire_on_thresholds(self):
        flags = az.risk_flags(self._result(
            fundamentals={"debt_ratio": 80.0, "rev_yoy": -4.0,
                          "profit_yoy": -10.0},
            kline={"drawdown_52w": -55.0, "volatility": 70.0}))
        joined = " | ".join(flags)
        assert "leverage" in joined
        assert "revenue contracting" in joined
        assert "profit contracting" in joined
        assert "drawdown" in joined
        assert "volatility" in joined

    def test_clean_profile_has_no_flags(self):
        assert az.risk_flags(self._result(
            fundamentals={"debt_ratio": 40.0, "rev_yoy": 10.0,
                          "profit_yoy": 15.0},
            kline={"drawdown_52w": -10.0, "volatility": 25.0})) == []


# ---------------------------------------------------------------------------
# Fixture snapshot
# ---------------------------------------------------------------------------
def make_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "20260901"
    snap.mkdir(exist_ok=True)
    codes = ["600001", "600002", "600003"]
    quotes = pd.DataFrame({
        "market": "A", "code": codes,
        "name": ["Alpha Co", "Beta Co", "Gamma Co"],
        "market_id": "1", "industry": "food",
        "price": [10.0, 20.0, 30.0],
        "pe_ttm": [10.0, 20.0, 30.0], "pb": [1.0, 2.0, 3.0],
        "market_cap": [5e10, 6e10, 7e10],
    })
    quotes.to_csv(snap / "a_quotes.csv", index=False)
    fins = pd.DataFrame({
        "code": codes,
        "report_date": ["2026-06-30"] * 3,
        "revenue": [1e10, 2e10, 3e10],
        "rev_yoy": [10.0, 20.0, 5.0],
        "profit": [1e9, 2e9, 3e9],
        "profit_yoy": [15.0, 25.0, -5.0],
        "roe": [15.0, 20.0, 10.0],
        "gross_margin": [30.0, 40.0, 20.0],
    })
    fins.to_csv(snap / "a_financials.csv", index=False)
    kdir = snap / "kline"
    kdir.mkdir()
    for i, code in enumerate(codes):
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(),
                               periods=300)
        close = pd.Series(range(100, 100 + 300)) * (1.0 + i * 0.1)
        pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": close, "close": close,
            "high": close * 1.01, "low": close * 0.99,
            "volume": [1e6] * 300, "amount": [1e8] * 300,
        }).to_csv(kdir / f"A_{code}.csv", index=False)
    return snap


def live_quote_df(secids=(), pe=10.0):
    return pd.DataFrame([{
        "market": "A", "code": "600001", "name": "Alpha Co",
        "market_id": "1", "price": 10.5, "pct_chg": 1.2,
        "pe_ttm": pe, "pb": 1.1, "market_cap": 5.2e10,
    }])


class TestAnalyzeStock:
    def test_full_flow_a_share(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", live_quote_df)
        monkeypatch.setattr(az, "fetch_kline_any",
                            lambda *a, **k: None)
        m = Match("A", "600001", "Alpha Co", 100.0, "1")
        r = az.analyze_stock(m, snapshot_dir=snap)
        assert r["quote"]["price"] == 10.5
        assert r["fundamentals"]["rev_yoy"] == 10.0
        assert r["kline"]["ret_250d"] is not None
        assert 0 <= r["composite_percentile"] <= 100
        assert r["verdict"] in ("outstanding opportunity", "attractive",
                                "reasonable", "unattractive", "poor")
        # Alpha is the cheapest of 3 -> oriented PE percentile is high
        assert r["percentiles"]["pe_ttm"] > 50
        assert r["risk_flags"] == []

    def test_live_quote_failure_degrades(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids",
                            lambda s: pd.DataFrame())
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        r = az.analyze_stock(Match("A", "600001", "Alpha Co", 100.0, "1"),
                             snapshot_dir=snap)
        assert r["quote"] is None
        assert any("live quote" in w for w in r["warnings"])

    def test_hk_live_quote_zfills_code(self, monkeypatch):
        seen = {}

        def fake(secids):
            seen["secids"] = secids
            return pd.DataFrame([{"market": "HK", "code": "2555",
                                  "name": "茶百道", "market_id": "116",
                                  "price": 9.9, "pe_ttm": 12.0}])

        monkeypatch.setattr(az, "fetch_quotes_by_secids", fake)
        row = az.live_quote(Match("HK", "02555", "茶百道", 100.0, "116"))
        assert seen["secids"] == ["116.02555"]
        assert row["code"] == "02555"


class TestRender:
    def _result(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", live_quote_df)
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        return az.analyze_stock(Match("A", "600001", "Alpha Co", 100.0, "1"),
                                snapshot_dir=snap)

    def test_brief_mentions_name_verdict_price(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_brief(r)
        assert "Alpha Co" in text
        assert "verdict" in text
        assert "10.50" in text
        assert "PE" in text

    def test_evidence_has_table_and_flags(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_evidence(r)
        assert "evidence" in text
        assert "peer pctile" in text
        assert "risk flags" in text
        assert "data as of" in text

    def test_to_json_roundtrip(self, tmp_path, monkeypatch):
        import json
        r = self._result(tmp_path, monkeypatch)
        data = json.loads(az.to_json(r))
        assert data["code"] == "600001"
        assert data["verdict"] == r["verdict"]


class TestCompare:
    def test_compare_two(self, tmp_path, monkeypatch):
        snap = make_snapshot(tmp_path)

        def quotes(secids):
            pe = 15.0 if "600002" in secids[0] else 10.0
            return pd.DataFrame([{"market": "A", "code": "60000X",
                                  "name": "X", "market_id": "1",
                                  "price": 10.0, "pe_ttm": pe,
                                  "pb": 1.0, "market_cap": 5e10}])

        monkeypatch.setattr(az, "fetch_quotes_by_secids", quotes)
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        df = az.compare_stocks(
            [Match("A", "600001", "Alpha Co", 100.0, "1"),
             Match("A", "600002", "Beta Co", 100.0, "1")],
            snapshot_dir=snap)
        assert len(df) == 2
        assert set(df.columns) >= {"name", "pe_ttm", "verdict",
                                   "composite_pctile", "risks"}
