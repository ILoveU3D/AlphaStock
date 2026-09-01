"""Tests for the time-horizon dimension (registry, scoring, CLI, ask)."""

from pathlib import Path

import pandas as pd
import pytest

from value_genie import analyze as az
from value_genie import report
from value_genie.__main__ import main
from value_genie.fetch.pipeline import backfill_kline_factors
from value_genie.resolve import Match
from value_genie.strategy.factors import kline_metrics
from value_genie.strategy import horizons  # noqa: F401 — registration
from value_genie.strategy import masters   # noqa: F401
from value_genie.strategy.registry import (
    get_horizon,
    get_strategy,
    list_horizons,
)


class TestShortWindowFactors:
    def test_ret_5d_ret_20d_vol_20d(self):
        closes = [100.0 * (1.01 ** t) for t in range(80)]
        m = kline_metrics(pd.DataFrame({"close": closes}))
        assert m["ret_5d"] == pytest.approx(((1.01 ** 5) - 1) * 100,
                                            rel=1e-9)
        assert m["ret_20d"] == pytest.approx(((1.01 ** 20) - 1) * 100,
                                             rel=1e-9)
        assert m["vol_20d"] > 0
        assert m["volatility"] > 0

    def test_flat_series_gives_zero_returns(self):
        m = kline_metrics(pd.DataFrame({"close": [100.0] * 80}))
        assert m["ret_5d"] == 0.0
        assert m["ret_20d"] == 0.0


class TestHorizonRegistry:
    def test_four_horizons_in_order(self):
        ids = [h.id for h in list_horizons()]
        assert ids[:4] == ["ultrashort", "short", "mid", "long"]

    def test_get_horizon_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown horizon"):
            get_horizon("nope")

    def test_ultrashort_shape(self):
        h = get_horizon("ultrashort")
        assert h.name == "超短线"
        assert h.momentum_cols == ("ret_5d", "ret_20d")
        assert h.weights["momentum"] == 0.70
        assert h.weights["value"] == 0
        ops = [(g[0], g[1]) for g in h.gates]
        assert ("volatility", "pctl>=") in ops
        assert ("ret_5d", ">=") in ops

    def test_short_shape(self):
        h = get_horizon("short")
        assert h.momentum_cols == ("ret_20d", "ret_60d")
        assert h.weights["momentum"] == 0.35
        assert ("ret_20d", ">=") in [(g[0], g[1]) for g in h.gates]

    def test_mid_shape(self):
        h = get_horizon("mid")
        assert h.gates == []
        assert h.weights["value"] == 0.30
        assert h.weights["growth"] == 0.30
        assert h.momentum_cols == ("ret_60d", "ret_250d")

    def test_long_shape(self):
        h = get_horizon("long")
        assert h.gates == []
        assert h.weights["quality"] == 0.35
        assert h.weights["cashflow"] == 0.20
        assert h.weights["momentum"] == 0
        assert h.momentum_cols == ("ret_60d", "ret_250d")

    def test_weights_sum_to_one(self):
        for h in list_horizons():
            assert sum(h.weights.values()) == pytest.approx(1.0)

    def test_masters_carry_natural_horizon(self):
        mapping = {"buffett": "long", "munger": "long", "graham": "mid",
                   "livermore": "short", "duan": "long",
                   "sheng": "ultrashort"}
        for mid, hz in mapping.items():
            assert get_strategy(mid).horizon == hz

    def test_presets_have_empty_horizon(self):
        assert get_strategy("balanced").horizon == ""


from value_genie.strategy.horizons import (apply_horizon_score,
                                           recompute_momentum_score)


class TestMomentumWindow:
    def _frame(self):
        # ret_60d/ret_250d deliberately run OPPOSITE to ret_5d/ret_20d,
        # so a window switch must flip the ranking
        return pd.DataFrame({
            "market": ["A"] * 4,
            "ret_5d": [10.0, 5.0, 0.0, -5.0],
            "ret_20d": [20.0, 10.0, 0.0, -10.0],
            "ret_60d": [-5.0, 0.0, 5.0, 10.0],
            "ret_250d": [-10.0, 0.0, 10.0, 20.0],
            "value_score": [50.0] * 4, "growth_score": [50.0] * 4,
            "quality_score": [50.0] * 4, "safety_score": [50.0] * 4,
            "cashflow_score": [50.0] * 4,
        })

    def test_ultrashort_ranks_short_window(self):
        scored = apply_horizon_score(self._frame(),
                                     get_horizon("ultrashort"),
                                     min_pillars=1)
        cs = scored["composite_score"]
        assert cs.iloc[0] == cs.max()      # best short-window momentum
        assert cs.iloc[3] == cs.min()

    def test_mid_keeps_default_window(self):
        scored = apply_horizon_score(self._frame(), get_horizon("mid"),
                                     min_pillars=1)
        cs = scored["composite_score"]
        assert cs.iloc[3] == cs.max()      # best ret_60d/ret_250d wins

    def test_base_weights_override(self):
        scored = apply_horizon_score(
            self._frame(), get_horizon("long"),
            base_weights={"value": 0, "growth": 0, "quality": 1.0,
                          "safety": 0, "momentum": 0, "cashflow": 0},
            min_pillars=1)
        # quality-only weights: all rows equal, momentum window is noise
        assert scored["composite_score"].nunique() == 1

    def test_missing_cols_fall_back_with_warn(self, capsys):
        df = self._frame().drop(columns=["ret_5d", "ret_20d"])
        s = recompute_momentum_score(df, ("ret_5d", "ret_20d"))
        assert "falling back" in capsys.readouterr().err
        assert s.notna().all()

    def test_all_cols_missing_gives_nan(self):
        df = self._frame().drop(columns=["ret_5d", "ret_20d", "ret_60d",
                                         "ret_250d"])
        s = recompute_momentum_score(df, ("ret_5d", "ret_20d"))
        assert s.isna().all()


# ---------------------------------------------------------------------------
# Varied-slope snapshot: three peers with clearly different kline trends
# ---------------------------------------------------------------------------
def _write_kline(snap: Path, market: str, code: str, slope: float):
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(),
                           periods=300)
    close = pd.Series([100.0 * ((1.0 + slope) ** t) for t in range(300)])
    pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "close": close,
        "high": close * 1.01, "low": close * 0.99,
        "volume": [1e6] * 300, "amount": [1e8] * 300,
    }).to_csv(snap / "kline" / f"{market}_{code}.csv", index=False)


def make_varied_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "20260901"
    (snap / "kline").mkdir(parents=True)
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
    for code, slope in [("600001", 0.000),   # flat: worst momentum
                        ("600002", 0.002), ("600003", 0.004)]:
        _write_kline(snap, "A", code, slope)
    return snap


class TestPeerBackfill:
    def test_build_peer_set_carries_kline_factors(self, tmp_path):
        snap = make_varied_snapshot(tmp_path)
        peers = az.build_peer_set(snap, "A")
        for col in ("ret_5d", "ret_20d", "vol_20d", "ret_60d",
                    "ret_250d", "volatility"):
            assert col in peers.columns
        assert peers["ret_5d"].notna().all()

    def test_missing_kline_stays_nan(self, tmp_path):
        snap = make_varied_snapshot(tmp_path)
        (snap / "kline" / "A_600003.csv").unlink()
        peers = az.build_peer_set(snap, "A")
        flat = peers["code"].astype(str) == "600003"
        assert peers.loc[flat, "ret_5d"].isna().all()
        assert peers.loc[~flat, "ret_5d"].notna().all()

    def test_backfill_unit(self, tmp_path):
        snap = make_varied_snapshot(tmp_path)
        df = pd.DataFrame({"market": ["A", "A"],
                           "code": ["600001", "600002"]})
        out = backfill_kline_factors(df, snap)
        assert out["ret_60d"].notna().all()
        assert "vol_20d" in out.columns

    def test_flat_target_not_100th_pctile_momentum(self, tmp_path,
                                                   monkeypatch):
        """Regression: peers now carry kline factors, so a flat target
        must NOT rank itself 100th percentile on momentum."""
        snap = make_varied_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", lambda s: pd.DataFrame(
            [{"market": "A", "code": "600001", "name": "Alpha Co",
              "market_id": "1", "price": 10.5, "pct_chg": 1.2,
              "pe_ttm": 10.0, "pb": 1.1, "market_cap": 5.2e10}]))
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        r = az.analyze_stock(Match("A", "600001", "Alpha Co", 100.0, "1"),
                             snapshot_dir=snap)
        mom = r["scores"]["momentum"]
        assert mom is None or mom < 100.0


# ---------------------------------------------------------------------------
# screen --horizon
# ---------------------------------------------------------------------------
def _horizon_master() -> pd.DataFrame:
    """Three A-shares; value scores and short-window momentum are
    deliberately anti-correlated so weight choices flip the ranking."""
    rows = []
    for i, code in enumerate(["600001", "600002", "600003"]):
        rows.append({
            "market": "A", "code": code, "name": f"S{i}", "industry": "x",
            "price": 10.0, "market_cap": 1e11, "pe_ttm": 10.0 + i,
            "pb": 1.0, "ps": 1.0, "dividend_yield": 1.0,
            "rev_yoy": 10.0, "profit_yoy": 10.0, "roe": 15.0,
            "gross_margin": 40.0, "net_margin": 10.0, "debt_ratio": 40.0,
            "ret_5d": [10.0, 2.0, -3.0][i],
            "ret_20d": [20.0, 5.0, -8.0][i],
            "ret_60d": [30.0, 10.0, -5.0][i],
            "ret_250d": [40.0, 15.0, -10.0][i],
            "volatility": [50.0, 30.0, 20.0][i],
            "pos_52w": [80.0, 50.0, 20.0][i],
            "drawdown_52w": [-5.0, -15.0, -40.0][i],
            "report_date": "2026-06-30",
            "value_score": [40.0, 60.0, 50.0][i],
            "growth_score": [50.0, 50.0, 50.0][i],
            "quality_score": [50.0, 50.0, 50.0][i],
            "safety_score": [50.0, 50.0, 50.0][i],
            "momentum_score": [50.0, 50.0, 50.0][i],
            "cashflow_score": float("nan"),
            "data_completeness": 1.0,
        })
    return pd.DataFrame(rows)


class TestScreenHorizon:
    def test_horizon_alone_weights_and_gates(self):
        # ultrashort gates: vol pctl>=50 (rows 0,1) and ret_5d>=0
        # (rows 0,1) -> 600003 excluded; momentum 0.70 ranks 600001 first
        top = report.screen(_horizon_master(), horizon="ultrashort",
                            top_n=5)
        assert list(top["code"]) == ["600001", "600002"]

    def test_horizon_recomputes_momentum(self):
        # momentum-only weights on the ultrashort window: order follows
        # ret_5d/ret_20d (600001 best), NOT the stored momentum_score tie
        top = report.screen(_horizon_master(), weights={"momentum": 1.0},
                            horizon="ultrashort", top_n=5)
        assert list(top["code"])[0] == "600001"

    def test_strategy_plus_horizon_keeps_strategy_weights(self):
        # buffett has momentum weight 0 -> ranking driven by value_score
        # (600002 has 60) even though momentum is measured on short window
        top = report.screen(_horizon_master(), strategy="buffett",
                            horizon="short", top_n=5)
        assert list(top["code"])[0] == "600002"

    def test_no_horizon_unchanged(self):
        top = report.screen(_horizon_master(), top_n=5)
        assert list(top["code"])[0] == "600002"   # balanced: value-heavy


class TestScreenCliHorizon:
    def _snap(self, tmp_path):
        snap = tmp_path / "snapshots" / "20260201"
        snap.mkdir(parents=True)
        _horizon_master().to_csv(snap / "master.csv", index=False)
        return tmp_path

    def test_screen_horizon_flag(self, tmp_path):
        data_dir = self._snap(tmp_path)
        out_dir = tmp_path / "out"
        rc = main(["screen", "--data-dir", str(data_dir),
                   "--out-dir", str(out_dir), "--horizon", "short",
                   "--top", "5"])
        assert rc == 0
        assert (out_dir / "20260201_short.csv").exists()

    def test_screen_strategy_horizon_combo(self, tmp_path):
        data_dir = self._snap(tmp_path)
        out_dir = tmp_path / "out"
        rc = main(["screen", "--data-dir", str(data_dir),
                   "--out-dir", str(out_dir), "--strategy", "buffett",
                   "--horizon", "short", "--top", "5"])
        assert rc == 0
        assert (out_dir / "20260201_buffett-short.csv").exists()

    def test_screen_rejects_unknown_horizon(self, tmp_path):
        data_dir = self._snap(tmp_path)
        with pytest.raises(SystemExit):
            main(["screen", "--data-dir", str(data_dir),
                  "--horizon", "decade"])


class TestAskHorizonProfile:
    def _result(self, tmp_path, monkeypatch, horizon=None):
        snap = make_varied_snapshot(tmp_path)
        monkeypatch.setattr(az, "fetch_quotes_by_secids", lambda s: pd.DataFrame(
            [{"market": "A", "code": "600001", "name": "Alpha Co",
              "market_id": "1", "price": 10.5, "pct_chg": 1.2,
              "pe_ttm": 10.0, "pb": 1.1, "market_cap": 5.2e10}]))
        monkeypatch.setattr(az, "fetch_kline_any", lambda *a, **k: None)
        return az.analyze_stock(
            Match("A", "600001", "Alpha Co", 100.0, "1"),
            snapshot_dir=snap, horizon=horizon)

    def test_profile_has_four_horizons(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        assert set(r["horizon_profile"]) == {"ultrashort", "short",
                                             "mid", "long"}
        for v in r["horizon_profile"].values():
            assert 0 <= v["score"] <= 100
            assert 0 <= v["percentile"] <= 100

    def test_flat_stock_scores_low_on_momentum_horizons(self, tmp_path,
                                                        monkeypatch):
        # Alpha's flat kline is the worst of three -> ultrashort (0.70
        # momentum) must rank it lower than long (momentum weight 0)
        r = self._result(tmp_path, monkeypatch)
        assert (r["horizon_profile"]["ultrashort"]["percentile"]
                < r["horizon_profile"]["long"]["percentile"])

    def test_brief_contains_profile(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_brief(r)
        assert "horizon profile" in text
        assert "ultrashort" in text and "long" in text

    def test_single_horizon_view(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch, horizon="mid")
        assert r["horizon"] == "mid"
        text = az.render_brief(r)
        assert "horizon lens" in text and "中线" in text
        assert "ultrashort" not in text

    def test_json_contains_profile(self, tmp_path, monkeypatch):
        import json
        r = self._result(tmp_path, monkeypatch, horizon="short")
        data = json.loads(az.to_json(r))
        assert data["horizon"] == "short"
        assert "mid" in data["horizon_profile"]
        assert "ultrashort" in data["horizon_profile"]

    def test_evidence_contains_profile(self, tmp_path, monkeypatch):
        r = self._result(tmp_path, monkeypatch)
        text = az.render_evidence(r)
        assert "horizon profile" in text
