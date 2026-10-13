"""Tests for the price-behavior / forensic / relative-value arsenal
batch (momentum, BAB, ivol-lottery, amihud, distress, forensic-lite,
AH premium) — synthetic data only, no network, no real snapshot."""

import json

import pandas as pd
import pytest

from polar_star.arsenal import (acquirers_multiple, ah_premium_radar,
                                amihud_gate, distress_scan, forensic_lite,
                                ivol_lottery_gate, low_beta_bab,
                                momentum_12_2, momentum_52w_high,
                                ncav_scan, pead_drift, sue_peek,
                                vol_managed_momentum)


# ---------------------------------------------------------------------------
# Synthetic snapshot helpers
# ---------------------------------------------------------------------------
def write_kline(snap, market, code, closes, amounts=None):
    d = snap / "kline"
    d.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-01-05", periods=len(closes)) \
        .strftime("%Y-%m-%d")
    n = len(closes)
    df = pd.DataFrame({
        "date": dates, "open": closes, "close": closes,
        "high": closes, "low": closes, "volume": [1000.0] * n,
        "amount": (amounts if amounts is not None
                   else [1e8] * n)})
    df.to_csv(d / f"{market}_{code}.csv", index=False)


def closes_from_returns(rets, base=100.0):
    out, px = [], base
    for r in rets:
        px *= 1.0 + r / 100.0
        out.append(px)
    return out


BASE_RETS = [1.0 if t % 2 == 0 else -0.5 for t in range(80)]


# ---------------------------------------------------------------------------
# momentum-12-2
# ---------------------------------------------------------------------------
class TestMomentum122:
    def test_difference_exact(self):
        df = pd.DataFrame({"market": ["A"], "code": ["1"],
                           "ret_250d": [120.0], "ret_20d": [20.0]})
        out = momentum_12_2.scan_frame(df)
        assert out["mom_12_2"].iloc[0] == pytest.approx(100.0)

    def test_missing_leg_is_nan(self):
        df = pd.DataFrame({"market": ["A", "A"], "code": ["1", "2"],
                           "ret_250d": [None, 50.0],
                           "ret_20d": [5.0, None]})
        out = momentum_12_2.scan_frame(df)
        assert out["mom_12_2"].isna().all()

    def test_pctl_within_market_not_global(self):
        df = pd.DataFrame({
            "market": ["A", "A", "US"],
            "code": ["1", "2", "3"],
            "ret_250d": [15.0, 25.0, 5.0],
            "ret_20d": [5.0, 5.0, 0.0]})
        out = momentum_12_2.scan_frame(df)
        # A: mom 10 vs 20 -> 50th / 100th within A; US singleton -> 100
        assert out["mom_12_2_pctl"].iloc[0] == pytest.approx(50.0)
        assert out["mom_12_2_pctl"].iloc[1] == pytest.approx(100.0)
        assert out["mom_12_2_pctl"].iloc[2] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# momentum-52w-high
# ---------------------------------------------------------------------------
class TestMomentum52wHigh:
    def test_passthrough_and_pctl(self):
        df = pd.DataFrame({"market": ["HK", "HK"], "code": ["1", "2"],
                           "pos_52w": [90.0, 30.0]})
        out = momentum_52w_high.scan_frame(df)
        assert out["mom_52w_high"].iloc[0] == pytest.approx(90.0)
        assert out["mom_52w_high_pctl"].iloc[0] == pytest.approx(100.0)
        assert out["mom_52w_high_pctl"].iloc[1] == pytest.approx(50.0)

    def test_missing_is_nan(self):
        df = pd.DataFrame({"market": ["HK"], "code": ["1"],
                           "pos_52w": [None]})
        out = momentum_52w_high.scan_frame(df)
        assert pd.isna(out["mom_52w_high"].iloc[0])
        assert pd.isna(out["mom_52w_high_pctl"].iloc[0])


# ---------------------------------------------------------------------------
# vol-managed-momentum
# ---------------------------------------------------------------------------
class TestVolManagedMomentum:
    def test_vmm_exact(self):
        df = pd.DataFrame({"market": ["A"], "code": ["1"],
                           "ret_250d": [120.0], "ret_20d": [20.0],
                           "volatility": [25.0]})
        out = vol_managed_momentum.scan_frame(df)
        assert out["vmm"].iloc[0] == pytest.approx(4.0)

    def test_zero_or_missing_vol_is_nan(self):
        df = pd.DataFrame({
            "market": ["A", "A", "A"], "code": ["1", "2", "3"],
            "ret_250d": [120.0, 120.0, 120.0],
            "ret_20d": [20.0, 20.0, 20.0],
            "volatility": [0.0, -5.0, None]})
        out = vol_managed_momentum.scan_frame(df)
        assert out["vmm"].isna().all()


# ---------------------------------------------------------------------------
# low-beta-bab
# ---------------------------------------------------------------------------
class TestLowBetaBab:
    def _snap(self, tmp_path):
        # 4 stocks, 81 closes -> 80 returns.  Proxy = mean of member
        # returns = (r + r + 2r + 0)/4 = r exactly, so betas are exact.
        write_kline(tmp_path, "A", "S1", closes_from_returns(BASE_RETS))
        write_kline(tmp_path, "A", "S2", closes_from_returns(BASE_RETS))
        write_kline(tmp_path, "A", "TWOX",
                    closes_from_returns([2 * r for r in BASE_RETS]))
        write_kline(tmp_path, "A", "FLAT", [100.0] * 81)
        return pd.DataFrame({"market": ["A"] * 4,
                             "code": ["S1", "S2", "TWOX", "FLAT"]})

    def test_beta_exact_on_controlled_market(self, tmp_path):
        df = self._snap(tmp_path)
        out = low_beta_bab.scan_frame(df, tmp_path)
        beta = dict(zip(out["code"], out["beta_bab"]))
        assert beta["S1"] == pytest.approx(1.0, abs=1e-8)
        assert beta["S2"] == pytest.approx(1.0, abs=1e-8)
        assert beta["TWOX"] == pytest.approx(2.0, abs=1e-8)
        assert beta["FLAT"] == pytest.approx(0.0, abs=1e-8)

    def test_low_beta_gets_high_pctl(self, tmp_path):
        df = self._snap(tmp_path)
        out = low_beta_bab.scan_frame(df, tmp_path)
        pctl = dict(zip(out["code"], out["beta_bab_pctl"]))
        assert pctl["FLAT"] == pytest.approx(100.0)  # lowest beta
        assert pctl["TWOX"] == pytest.approx(25.0)   # highest beta

    def test_no_snap_is_data_gap(self):
        df = pd.DataFrame({"market": ["A"], "code": ["X"]})
        out = low_beta_bab.scan_frame(df)  # snap=None
        assert pd.isna(out["beta_bab"].iloc[0])
        assert bool(out["bab_data_gap"].iloc[0]) is True

    def test_missing_kline_is_data_gap(self, tmp_path):
        write_kline(tmp_path, "A", "S1", closes_from_returns(BASE_RETS))
        df = pd.DataFrame({"market": ["A", "A"], "code": ["S1", "GHOST"]})
        out = low_beta_bab.scan_frame(df, tmp_path)
        row = out[out["code"] == "GHOST"].iloc[0]
        assert pd.isna(row["beta_bab"])
        assert bool(row["bab_data_gap"]) is True


# ---------------------------------------------------------------------------
# ivol-lottery-gate
# ---------------------------------------------------------------------------
class TestIvolLotteryGate:
    def _snap(self, tmp_path):
        # 4 quiet clones of the base pattern + 1 noisy stock.  The noise
        # uses a period-3 cycle ([+6,-3,-3], mean 0) so it is NOT
        # collinear with the period-2 base pattern (period-2 noise would
        # be perfectly linear in r and OLS would absorb it entirely).
        # Plus a +20% spike inside the noisy stock's last 21 bars.
        for i in range(4):
            write_kline(tmp_path, "A", f"Q{i}",
                        closes_from_returns(BASE_RETS))
        cycle = [6.0, -3.0, -3.0]
        noisy = [r + cycle[t % 3] for t, r in enumerate(BASE_RETS)]
        noisy[70] = 20.0
        write_kline(tmp_path, "A", "NOISY", closes_from_returns(noisy))
        return pd.DataFrame({"market": ["A"] * 5,
                             "code": ["Q0", "Q1", "Q2", "Q3", "NOISY"]})

    def test_max_ret_21d_exact(self, tmp_path):
        self._snap(tmp_path)
        kl = pd.read_csv(tmp_path / "kline" / "A_NOISY.csv")
        rets = ivol_lottery_gate.daily_returns(kl)
        assert ivol_lottery_gate.max_daily_return(rets) == \
            pytest.approx(20.0)

    def test_quiet_stock_has_small_ivol(self, tmp_path):
        df = self._snap(tmp_path)
        out = ivol_lottery_gate.scan_frame(df, tmp_path)
        iv = dict(zip(out["code"], out["ivol"]))
        assert iv["Q0"] < 15.0        # quiet resid, annualized
        assert iv["NOISY"] > 25.0     # noisy resid, annualized
        assert iv["NOISY"] > 3.0 * iv["Q0"]

    def test_veto_flags_fire_at_pctl80(self, tmp_path):
        df = self._snap(tmp_path)
        out = ivol_lottery_gate.scan_frame(df, tmp_path)
        noisy = out[out["code"] == "NOISY"].iloc[0]
        quiet = out[out["code"] == "Q0"].iloc[0]
        assert noisy["ivol_pctl"] == pytest.approx(100.0)
        assert bool(noisy["ivol_veto"]) is True
        assert noisy["max_pctl"] == pytest.approx(100.0)
        assert bool(noisy["lottery_veto"]) is True
        assert bool(quiet["ivol_veto"]) is False
        assert bool(quiet["lottery_veto"]) is False

    def test_short_history_is_data_gap(self, tmp_path):
        write_kline(tmp_path, "A", "TINY", closes_from_returns(BASE_RETS[:9]))
        write_kline(tmp_path, "A", "FULL", closes_from_returns(BASE_RETS))
        df = pd.DataFrame({"market": ["A", "A"], "code": ["TINY", "FULL"]})
        out = ivol_lottery_gate.scan_frame(df, tmp_path)
        tiny = out[out["code"] == "TINY"].iloc[0]
        assert pd.isna(tiny["max_ret_21d"])     # < 21 daily returns
        assert bool(tiny["lottery_data_gap"]) is True


# ---------------------------------------------------------------------------
# amihud-gate
# ---------------------------------------------------------------------------
class TestAmihudGate:
    def test_exact_three_bar_toy(self):
        # rets: +10%, +5%, +10%; amounts 2e6 / 4e6 / 8e6 ->
        # mean(10/2, 5/4, 10/8) = 2.5
        kl = pd.DataFrame({
            "date": ["2026-01-05", "2026-01-06", "2026-01-07",
                     "2026-01-08"],
            "close": [10.0, 11.0, 11.55, 12.705],
            "amount": [1e6, 2e6, 4e6, 8e6]})
        assert amihud_gate.amihud_value(kl, bars=3) == pytest.approx(2.5)

    def test_insufficient_bars_is_none(self):
        kl = pd.DataFrame({"date": ["2026-01-05", "2026-01-06"],
                           "close": [10.0, 11.0], "amount": [1e6, 1e6]})
        assert amihud_gate.amihud_value(kl, bars=3) is None

    def test_nan_amount_is_none(self):
        kl = pd.DataFrame({"date": ["2026-01-05", "2026-01-06"],
                           "close": [10.0, 11.0],
                           "amount": [float("nan"), float("nan")]})
        assert amihud_gate.amihud_value(kl, bars=1) is None

    def test_scan_veto_and_gap(self, tmp_path):
        closes = closes_from_returns([1.0 if t % 2 == 0 else -1.0
                                      for t in range(22)])
        write_kline(tmp_path, "A", "ILLIQ", closes,
                    amounts=[1e6 + t * 1e4 for t in range(22)])
        write_kline(tmp_path, "A", "LIQ", closes,
                    amounts=[1e9 + t * 1e6 for t in range(22)])
        write_kline(tmp_path, "A", "NOAMT", closes,
                    amounts=[float("nan")] * 22)
        df = pd.DataFrame({"market": ["A"] * 3,
                           "code": ["ILLIQ", "LIQ", "NOAMT"]})
        out = amihud_gate.scan_frame(df, tmp_path)
        ill = out[out["code"] == "ILLIQ"].iloc[0]
        liq = out[out["code"] == "LIQ"].iloc[0]
        namt = out[out["code"] == "NOAMT"].iloc[0]
        assert ill["amihud"] > liq["amihud"]
        assert ill["amihud_pctl"] == pytest.approx(100.0)
        assert bool(ill["illiquid_veto"]) is True
        assert bool(liq["illiquid_veto"]) is False
        assert pd.isna(namt["amihud"])
        assert bool(namt["amihud_data_gap"]) is True


# ---------------------------------------------------------------------------
# distress-scan
# ---------------------------------------------------------------------------
class TestDistressScan:
    def _snap(self, tmp_path):
        pd.DataFrame({
            "ticker": ["ABC"], "liabilities": [500.0],
            "assets": [2000.0], "rev": [1000.0],
            "profit": [100.0], "ocf": [50.0]}) \
            .to_csv(tmp_path / "us_financials.csv", index=False)
        return pd.DataFrame({
            "market": ["US", "A"], "code": ["ABC", "600001"],
            "name": ["Abc Corp", "测试"], "market_cap": [1000.0, 5e9],
            "price": [10.0, 20.0]})

    def test_us_partial_coverage(self, tmp_path):
        df = self._snap(tmp_path)
        out = distress_scan.scan_frame(df, tmp_path)
        us = out[out["code"] == "ABC"].iloc[0]
        assert us["dz_x4"] == pytest.approx(2.0)     # 1000 / 500
        assert us["dz_x5"] == pytest.approx(0.5)     # 1000 / 2000
        assert us["dz_components_available"] == \
            "x4_market_cap_over_liabilities,x5_sales_over_assets"
        assert "partial (2/5)" in us["dz_coverage"]
        assert "no canonical verdict" in us["dz_coverage"]

    def test_a_share_no_fields(self, tmp_path):
        df = self._snap(tmp_path)
        out = distress_scan.scan_frame(df, tmp_path)
        a = out[out["code"] == "600001"].iloc[0]
        assert pd.isna(a["dz_x4"]) and pd.isna(a["dz_x5"])
        assert a["dz_components_available"] == ""
        assert a["dz_coverage"] == "no balance-sheet fields"

    def test_run_row_never_fabricates_z(self, tmp_path):
        df = self._snap(tmp_path)
        ctx = {"snap": tmp_path, "master": df, "row": df.iloc[0]}
        out = distress_scan.run(ctx)
        assert out["weapon"] == "distress-scan"
        assert out["row"]["z_partial"] is None
        assert "partial (2/5)" in out["row"]["coverage"]


# ---------------------------------------------------------------------------
# forensic-lite
# ---------------------------------------------------------------------------
class TestForensicLite:
    def _snap(self, tmp_path):
        pd.DataFrame({"code": ["600001"], "rece_yoy": [100.0],
                      "inv_yoy": [0.0], "receivable": [1.0],
                      "inventory": [1.0], "report_date": ["2026-06-30"]}
                     ).to_csv(tmp_path / "a_balance.csv", index=False)
        pd.DataFrame({"ticker": ["ABC"], "profit": [100.0], "ocf": [0.0],
                      "assets": [1000.0], "liabilities": [500.0],
                      "rev": [2000.0]}
                     ).to_csv(tmp_path / "us_financials.csv", index=False)
        return pd.DataFrame({
            "market": ["A", "US", "HK"],
            "code": ["600001", "ABC", "00700"],
            "name": ["测试A", "Abc Corp", "Test HK"],
            "rev_yoy": [0.0, 100.0, 10.0]})

    def test_constructed_flags_fire(self, tmp_path):
        df = self._snap(tmp_path)
        out = forensic_lite.scan_frame(df, tmp_path)
        a = out[out["code"] == "600001"].iloc[0]
        assert a["dsri"] == pytest.approx(2.0)        # 2.0 / 1.0
        assert a["sgi"] == pytest.approx(1.0)
        assert bool(a["dsri_flag"]) is True           # > 1.465
        assert bool(a["sgi_flag"]) is False
        assert a["forensic_verdict"] == \
            "1/2 indices dubious (subset ≠ canonical M-score)"
        us = out[out["code"] == "ABC"].iloc[0]
        assert us["sgi"] == pytest.approx(2.0)
        assert us["tata"] == pytest.approx(0.1)       # (100-0)/1000
        assert bool(us["sgi_flag"]) is True           # > 1.608
        assert bool(us["tata_flag"]) is True          # > 0.018
        assert us["forensic_flag_count"] == 2
        assert us["forensic_verdict"] == \
            "2/2 indices dubious (subset ≠ canonical M-score)"

    def test_single_index_is_data_gap(self, tmp_path):
        df = self._snap(tmp_path)
        out = forensic_lite.scan_frame(df, tmp_path)
        hk = out[out["code"] == "00700"].iloc[0]      # SGI only
        assert pd.isna(hk["dsri"]) and pd.isna(hk["tata"])
        assert hk["forensic_verdict"] == "data_gap (<2 indices available)"

    def test_dsri_bad_denominator_is_nan(self, tmp_path):
        df = self._snap(tmp_path)
        df.loc[df["code"] == "600001", "rev_yoy"] = -100.0
        out = forensic_lite.scan_frame(df, tmp_path)
        a = out[out["code"] == "600001"].iloc[0]
        assert pd.isna(a["dsri"])


# ---------------------------------------------------------------------------
# ah-premium-radar
# ---------------------------------------------------------------------------
class TestAhPremiumRadar:
    FX = 0.92

    def _snap(self, tmp_path):
        (tmp_path / "manifest.json").write_text(
            json.dumps({"fx_hkdcny": self.FX}), encoding="utf-8")
        prem_target = [t * 0.1 for t in range(60)]    # 0.0 .. 5.9
        a_closes = [10.0] * 60
        h_closes = [(10.0 / self.FX) / (1.0 + p / 100.0)
                    for p in prem_target]
        write_kline(tmp_path, "A", "600028", a_closes)
        write_kline(tmp_path, "HK", "00386", h_closes)
        master = pd.DataFrame({
            "market": ["A", "HK"], "code": ["600028", "00386"],
            "name": ["中国石油化工股份", "中国石油化工"],
            "price": [10.0, h_closes[-1]]})
        return master, prem_target

    def test_name_normalization_pairs(self):
        assert ah_premium_radar.normalize_name("中国石油化工股份") == \
            ah_premium_radar.normalize_name("中国石油化工")
        assert ah_premium_radar.normalize_name("测试集团有限公司")

    def test_premium_level_exact(self, tmp_path):
        master, prem_target = self._snap(tmp_path)
        ctx = {"snap": tmp_path, "master": master}
        out = ah_premium_radar.run(ctx)
        assert out["pairs_found"] == 1
        rec = out["pairs"][0]
        assert rec["a_code"] == "600028" and rec["hk_code"] == "00386"
        assert rec["premium_pct"] == pytest.approx(prem_target[-1],
                                                   abs=1e-9)

    def test_premium_z_exact(self, tmp_path):
        master, prem_target = self._snap(tmp_path)
        ctx = {"snap": tmp_path, "master": master}
        out = ah_premium_radar.run(ctx)
        s = pd.Series(prem_target, dtype=float)
        expected = (s.iloc[-1] - s.mean()) / s.std(ddof=0)
        assert out["pairs"][0]["premium_z"] == pytest.approx(expected)
        assert expected > 0     # premium rising into the last print

    def test_pairs_override_and_row_reading(self, tmp_path):
        master, _ = self._snap(tmp_path)
        ctx = {"snap": tmp_path, "master": master, "row": master.iloc[0]}
        out = ah_premium_radar.run(
            ctx, pairs=[("A:600028", "HK:00386")])
        assert out["pairs_found"] == 1
        assert out["row"]["a_code"] == "600028"

    def test_missing_leg_is_data_gap(self, tmp_path):
        master, _ = self._snap(tmp_path)
        ctx = {"snap": tmp_path, "master": master}
        out = ah_premium_radar.run(ctx, pairs=[("A:600028", "HK:99999")])
        rec = out["pairs"][0]
        assert rec["premium_pct"] is None and rec["premium_z"] is None
        assert rec["data_gap"] == "leg missing from master.csv"


# ---------------------------------------------------------------------------
# Dormant weapons
# ---------------------------------------------------------------------------
class TestDormant:
    @pytest.mark.parametrize("mod,wid", [
        (sue_peek, "sue-peek"),
        (pead_drift, "pead-drift"),
        (acquirers_multiple, "acquirers-multiple"),
        (ncav_scan, "ncav-scan"),
    ])
    def test_dormant_shape(self, mod, wid):
        out = mod.run({})
        assert out["weapon"] == wid
        assert out["status"] == "dormant"
        assert out["reason"]
        assert out["wake_condition"]
