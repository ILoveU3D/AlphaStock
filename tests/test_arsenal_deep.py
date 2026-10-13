"""Tests for the deep-stage arsenal weapons (synthetic, no network)."""

import math

import numpy as np
import pandas as pd
import pytest

from polar_star.arsenal import barrier_forge as bf
from polar_star.arsenal import bayesian_log_odds as blo
from polar_star.arsenal import expectations_engine as ee
from polar_star.arsenal import regime_radar as rr
from polar_star.arsenal import sizing_compass as sc
from polar_star.arsenal import value_ladder as vl
from polar_star.arsenal import yield_compass as yc
from polar_star.arsenal.statsutil import pert_sample


class TestExpectationsEngine:
    def test_mc_degenerate_point_mass(self):
        # all PERT params lo==mode==hi -> distribution collapses
        out = ee.monte_carlo_dcf(5.0, 100.0, 5.0, 5.0, 5.0,
                                 tg_lo=2.0, tg_mode=2.0, tg_hi=2.0,
                                 r_lo=10.0, r_mode=10.0, r_hi=10.0,
                                 n=2000, seed=1)
        assert out["p10"] == pytest.approx(out["p90"])
        assert out["p50"] == pytest.approx(out["mean"])
        assert out["n_valid"] == 2000

    def test_mc_degenerate_exact_value(self):
        # hand-computed DCF: g=5% yrs1-5, linear fade 5->2% yrs6-10,
        # tg=2%, r=10%, fcf0=5
        g, tg, r, fcf0 = 0.05, 0.02, 0.10, 5.0
        pv, fcf = 0.0, fcf0
        for t in range(1, 11):
            gt = g if t <= 5 else g + (tg - g) * (t - 5) / 5.0
            fcf *= 1.0 + gt
            pv += fcf / (1.0 + r) ** t
        expected = pv + fcf * (1.0 + tg) / (r - tg) / (1.0 + r) ** 10
        out = ee.monte_carlo_dcf(fcf0, 100.0, 5.0, 5.0, 5.0,
                                 tg_lo=2.0, tg_mode=2.0, tg_hi=2.0,
                                 r_lo=10.0, r_mode=10.0, r_hi=10.0,
                                 n=2000, seed=1)
        assert out["p50"] == pytest.approx(expected)
        assert out["mc_vs_price"] == pytest.approx(expected / 100.0)

    def test_pert_sample_degenerate(self):
        draws = pert_sample(np.random.default_rng(0), 3.0, 3.0, 3.0, 50)
        assert np.all(draws == 3.0)

    def test_cap_years_zero_below_epv(self):
        # fcf0=10, r=10% -> EPV=100; price=80 < EPV -> cap 0
        assert ee.cap_years(10.0, 80.0, 0.05, r=0.10) == 0.0

    def test_cap_years_beyond_bound_none(self):
        # price above 40y of implied growth -> honest None
        assert ee.cap_years(1.0, 1e9, 0.05, r=0.10) is None

    def test_run_requires_row(self):
        out = ee.run({})
        assert out["weapon"] == "expectations-engine"
        assert "row required" in out["error"]


class TestValueLadder:
    def test_graham_number_exact(self):
        # price=100, pe=20 -> EPS=5; pb=2 -> BVPS=50
        # sqrt(22.5 * 5 * 50) = sqrt(5625) = 75
        assert vl.graham_number(100.0, 20.0, 2.0) == pytest.approx(75.0)

    def test_graham_number_loss_maker_none(self):
        assert vl.graham_number(100.0, -10.0, 2.0) is None
        assert vl.graham_number(100.0, 20.0, -2.0) is None

    def test_run_ncav_declared_gap(self):
        row = pd.Series({"market": "US", "code": "XXX", "price": 100.0,
                         "pe_ttm": 20.0, "pb": 2.0, "market_cap": 1e9})
        out = vl.run({"row": row, "snap": None})
        assert out["rungs"]["liquidation_ncav"] is None
        assert "current-assets" in out["ncav_gap"]
        assert out["rungs"]["graham_number"] == pytest.approx(75.0)
        # EPV needs a snapshot -> honest note, not a number
        assert out["rungs"]["epv_per_share"] is None


def _kl(closes, spread=0.5):
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "date": [f"2026-01-{i + 1:02d}" for i in range(len(c))],
        "open": c, "close": c,
        "high": c + spread, "low": c - spread,
        "volume": np.full(len(c), 1e6), "amount": c * 1e6,
    })


class TestBarrierForge:
    def test_chandelier_ratchet_never_decreases(self):
        closes = [100.0 + i for i in range(40)]
        kl = _kl(closes)
        stops, signal = bf.chandelier(kl, k=3.0, anchor_idx=0)
        valid = stops[np.isfinite(stops)]
        assert len(valid) > 0
        assert np.all(np.diff(valid) >= 0.0)

    def test_chandelier_fires_only_on_close(self):
        closes = [100.0 + i for i in range(40)]
        kl = _kl(closes)
        stop_now = bf.chandelier(kl, k=3.0)[0][-1]
        # bar with LOW below the stop but CLOSE above it -> no signal
        dip = pd.concat([kl, pd.DataFrame({
            "date": ["2026-02-10"], "open": [closes[-1]],
            "close": [closes[-1] + 1.0],
            "high": [closes[-1] + 2.0],
            "low": [stop_now - 5.0],
            "volume": [1e6], "amount": [1e8]})], ignore_index=True)
        _, signal_dip = bf.chandelier(dip, k=3.0)
        assert signal_dip is False
        # bar CLOSING below the stop -> signal
        brk = pd.concat([kl, pd.DataFrame({
            "date": ["2026-02-10"], "open": [closes[-1]],
            "close": [stop_now - 5.0],
            "high": [closes[-1] + 1.0],
            "low": [stop_now - 6.0],
            "volume": [1e6], "amount": [1e8]})], ignore_index=True)
        _, signal_brk = bf.chandelier(brk, k=3.0)
        assert signal_brk is True

    def test_yang_zhang_ge_close_close_on_gaps(self):
        # gapping toy series: +-3% overnight gaps, tiny intraday move
        n = 80
        o, c = [], []
        prev = 100.0
        for i in range(n):
            gap = 0.03 if i % 2 == 0 else -0.03
            op = prev * (1.0 + gap)
            o.append(op)
            c.append(op * 1.001)
            prev = c[-1]
        o, c = np.array(o), np.array(c)
        kl = pd.DataFrame({
            "open": o, "close": c,
            "high": np.maximum(o, c) * 1.001,
            "low": np.minimum(o, c) * 0.999})
        yz = bf.yang_zhang_vol(kl, window=60)
        cc = float(np.std(np.log(c[1:] / c[:-1])[-60:], ddof=1)) \
            * math.sqrt(252) * 100.0
        assert yz is not None
        assert yz >= cc - 1e-9

    def test_run_requires_kline(self):
        out = bf.run({})
        assert "kline required" in out["error"]


class TestSizingCompass:
    def test_kelly_exact(self):
        full, half = sc.kelly(0.55, 1.5)
        assert full == pytest.approx(0.25)
        assert half == pytest.approx(0.125)

    def test_amihud_cap(self):
        kl = _kl([100.0] * 30)
        kl["amount"] = 2e7      # ADV 20m
        cap = sc.amihud_cap(kl, nav=1e6, participation=0.10)
        assert cap == pytest.approx(0.10 * 2e7 / 1e6)   # = 2.0


class TestBayesianLogOdds:
    def test_bf10_is_plus10db(self):
        out = blo.log_odds(1.0, [{"name": "moat", "bf": 10.0}])
        assert out["total_db"] == pytest.approx(10.0)
        assert out["posterior_odds"] == pytest.approx(10.0)
        assert out["verdict"] == "strong-for"

    def test_product_and_bands(self):
        out = blo.log_odds(2.0, [{"name": "a", "bf": 10.0},
                                 {"name": "b", "bf": 0.1}])
        assert out["total_db"] == pytest.approx(0.0)
        assert out["posterior_odds"] == pytest.approx(2.0)
        assert out["verdict"] == "noise"

    def test_invalid_bf_skipped(self):
        out = blo.log_odds(1.0, [{"name": "bad", "bf": -1.0}])
        assert out["skipped"] == ["bad"]
        assert out["total_db"] == 0.0


class TestRegimeRadar:
    def test_ou_half_life_none_for_random_walk(self):
        # exact trend in log space -> AR(1) slope exactly 1 -> None
        t = np.arange(200)
        close = pd.Series(100.0 * np.exp(0.001 * t))
        assert rr.ou_half_life(close) is None

    def test_ou_half_life_finite_for_mean_reverting(self):
        rng = np.random.default_rng(0)
        n, x = 400, np.zeros(400)
        for i in range(1, n):
            x[i] = 0.95 * x[i - 1] + rng.normal()
        close = pd.Series(np.exp(x / 10.0 + 4.0))
        hl = rr.ou_half_life(close)
        assert hl is not None
        # theoretical half-life at rho=0.95: -ln2/ln0.95 ~ 13.5
        assert 5.0 < hl < 60.0

    def test_bocpd_detects_break(self):
        rng = np.random.default_rng(7)
        x = np.concatenate([rng.normal(0, 0.01, 60),
                            rng.normal(0.05, 0.01, 60)])
        R, maps = rr.bocpd(x)
        # break at t=60 -> final run-length MAP ~ the second segment's
        # length (60), far below the full 120 of an unbroken series
        assert 40 <= maps[-1] <= 70
        assert abs(R[-1, :].sum() - 1.0) < 1e-6

    def test_run_requires_kline(self):
        assert "kline required" in rr.run({})["error"]


class TestYieldCompass:
    def test_flat_payback_exact(self):
        assert yc.payback_years_flat(2.5) == pytest.approx(40.0)

    def test_growth_zero_falls_back_flat(self):
        assert yc.payback_years_growth(2.5, 0.0) == pytest.approx(40.0)

    def test_growth_closed_form(self):
        # d=0.025, g=0.02: n = ln(1 + 0.02/(0.025*1.02)) / ln(1.02)
        expected = math.log(1.0 + 0.02 / (0.025 * 1.02)) / math.log(1.02)
        assert yc.payback_years_growth(2.5, 0.02) == pytest.approx(expected)

    def test_no_dividend_none(self):
        assert yc.payback_years_flat(0.0) is None
        assert yc.payback_years_flat(None) is None

    def test_cash_return_and_loss_maker(self):
        cr, note = yc.cash_return(20.0, 2.5)
        assert cr == pytest.approx(5.0 + 2.5)
        cr2, note2 = yc.cash_return(-5.0, 2.5)
        assert cr2 is None and note2

    def test_scan_frame_columns(self):
        df = pd.DataFrame({"market": ["A", "A"], "code": ["1", "2"],
                           "pe_ttm": [20.0, -5.0],
                           "dividend_yield": [2.5, 1.0]})
        out = yc.scan_frame(df)
        assert out["cash_return"].iloc[0] == pytest.approx(7.5)
        assert out["payback_years_flat"].iloc[0] == pytest.approx(40.0)
        assert pd.isna(out["cash_return"].iloc[1])
