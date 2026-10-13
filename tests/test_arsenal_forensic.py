"""Tests for the forensic/owner/dormant arsenal batch (synthetic only —
no network, no real snapshot)."""

import pandas as pd
import pytest

from polar_star.arsenal import forensic_audit as fa
from polar_star.arsenal import owner_audit as oa
from polar_star.arsenal import ic_self_audit as ic
from polar_star.arsenal import mae_mfe_audit as mm
from polar_star.arsenal import pendulum_gauges as pg
from polar_star.arsenal import short_interest_monitor as si


# ---------------------------------------------------------------------------
# forensic-audit: Beneish indices + coverage honesty
# ---------------------------------------------------------------------------
class TestBeneish:
    # handcrafted us_financials-style row: we control every field
    FIN = {"rev": 200.0, "rev_prev": 100.0, "profit": 100.0,
           "ocf": 20.0, "assets": 1000.0}

    def test_sgi_tata_exact(self):
        out = fa.beneish_indices(self.FIN)
        assert out["indices"]["sgi"]["value"] == pytest.approx(2.0)
        # TATA = (profit - ocf) / assets = 80 / 1000
        assert out["indices"]["tata"]["value"] == pytest.approx(0.08)

    def test_coverage_counted_honestly(self):
        out = fa.beneish_indices(self.FIN)
        # only SGI + TATA computable from US fields; the other six are
        # declared gaps, and the canonical M-score is never reported
        assert out["coverage"] == 2
        assert out["m_score"] is None
        gaps = [k for k, i in out["indices"].items() if i["value"] is None]
        assert sorted(gaps) == ["aqi", "depi", "dsri", "gmi", "lvgi",
                                "sgai"]

    def test_tata_flag_fires_and_verdict_red(self):
        out = fa.beneish_indices(self.FIN)
        assert out["indices"]["tata"]["dubious"] is True  # 0.08 > 0.018
        assert fa.beneish_flag(out) is True
        verdict = fa.combine_verdict([True, None, None], 3, 3)
        assert verdict == "red"

    def test_sgi_alone_not_enough_to_flag(self):
        # SGI dubious but TATA clean, coverage 2 -> no detector flag
        fin = dict(self.FIN, ocf=99.0)  # TATA = 1/1000 = 0.001 clean
        out = fa.beneish_indices(fin)
        assert out["indices"]["sgi"]["dubious"] is True   # 2.0 > 1.608
        assert out["indices"]["tata"]["dubious"] is False
        assert fa.beneish_flag(out) is False


# ---------------------------------------------------------------------------
# forensic-audit: Piotroski coverage honesty
# ---------------------------------------------------------------------------
class TestPiotroski:
    def test_us_three_of_nine(self):
        fin = {"profit": 100.0, "ocf": 150.0, "assets": 1000.0}
        out = fa.piotroski_signals(fin, "US")
        assert out["signals_available"] == 3
        assert out["signals_total"] == 9
        assert out["score"] == 3
        assert out["signals"]["roa_pos"] is True
        assert out["signals"]["ocf_pos"] is True
        assert out["signals"]["accrual"] is True        # 150 > 100
        assert out["signals"]["d_roa_pos"] is None      # assets_prev gap
        # thin coverage -> amber, never a rescaled pseudo-9
        assert fa.combine_verdict([None, None, None],
                                  out["score"],
                                  out["signals_available"]) == "amber"

    def test_a_share_named_proxies(self):
        fin = {"profit": 5.0, "ocf": 3.0, "profit_yoy_pct": 12.0,
               "period_mismatch": True}
        out = fa.piotroski_signals(fin, "A")
        assert out["signals_available"] == 4
        assert out["signals"]["accrual"] is False       # 3 < 5
        assert "roa_pos" in out["proxies"]
        assert "d_roa_pos" in out["proxies"]
        assert any("period mismatch" in n for n in out["notes"])

    def test_red_on_low_score_with_full_coverage(self):
        assert fa.combine_verdict([None], 2, 8) == "red"
        assert fa.combine_verdict([None], 3, 8) == "green"


# ---------------------------------------------------------------------------
# forensic-audit: modified-Jones lite outlier detection
# ---------------------------------------------------------------------------
class TestJonesLite:
    def _peers(self):
        # 24 clean peers: ta = 0.05 + 0.4 * drev exactly; one planted
        # manipulator with a huge positive accrual residual
        rows = [{"code": f"P{i:02d}",
                 "drev": -0.10 + i * 0.01,
                 "ta": 0.05 + 0.4 * (-0.10 + i * 0.01)}
                for i in range(24)]
        rows.append({"code": "BAD", "drev": 0.05,
                     "ta": 0.05 + 0.4 * 0.05 + 0.60})
        return pd.DataFrame(rows)

    def test_planted_outlier_flagged(self):
        res = fa.jones_lite(self._peers())
        assert res["status"] == "ok"
        assert res["n"] == 25
        tbl = res["table"].set_index("code")
        assert tbl.loc["BAD", "flag"] is True or bool(tbl.loc["BAD", "flag"])
        assert abs(tbl.loc["BAD", "z"]) > 2.0
        clean = tbl.drop(index="BAD")
        assert not clean["flag"].any()

    def test_target_extraction(self):
        res = fa.jones_lite(self._peers())
        tgt = fa._target_from(res, "BAD")
        assert tgt["status"] == "ok"
        assert tgt["flag"] is True
        assert abs(tgt["z"]) > 2.0

    def test_data_gap_below_min_peers(self):
        res = fa.jones_lite(self._peers().head(10))
        assert res["status"] == "data_gap"
        assert res["n"] == 10


# ---------------------------------------------------------------------------
# forensic-audit: degradation without a target row
# ---------------------------------------------------------------------------
class TestDegrade:
    def test_no_row_is_data_gap(self):
        out = fa.run({"snap": None, "master": None})
        assert out["weapon"] == "forensic-audit"
        assert out["status"] == "data_gap"


# ---------------------------------------------------------------------------
# owner-audit
# ---------------------------------------------------------------------------
class TestOwnerEarnings:
    def test_oe_exact(self):
        assert oa.owner_earnings(1000.0, 300.0) == pytest.approx(700.0)

    def test_oe_none_on_missing(self):
        assert oa.owner_earnings(None, 300.0) is None
        assert oa.owner_earnings(1000.0, None) is None


class TestDollarRetained:
    def test_ratio_exact(self):
        # 4 fy retaining 250 each = 1000 retained; mcap 1000 -> 2500
        # minted 1500 -> 1.5 dollars of mcap per retained dollar
        retained = {2021: 250.0, 2022: 250.0, 2023: 250.0, 2024: 250.0}
        out = oa.dollar_retained_test(retained, 1000.0, 2500.0, 4.0)
        assert out["ratio"] == pytest.approx(1.5)
        assert out["pass"] is True
        assert out["retained_sum"] == pytest.approx(1000.0)
        assert out["years"] == 4

    def test_fail_when_below_one(self):
        # retained 3x500 = 1500; mcap minted only 750 -> 0.5 per dollar
        retained = {2021: 500.0, 2022: 500.0, 2023: 500.0}
        out = oa.dollar_retained_test(retained, 1000.0, 1750.0, 3.5)
        assert out["ratio"] == pytest.approx(0.5)
        assert out["pass"] is False

    def test_none_when_history_short(self):
        retained = {2025: 300.0}
        out = oa.dollar_retained_test(retained, 1000.0, 1400.0, 1.3)
        assert out["ratio"] is None
        assert out["pass"] is None
        assert "gap" in out

    def test_none_when_retained_nonpositive(self):
        retained = {2022: -100.0, 2023: -50.0, 2024: -20.0, 2025: -10.0}
        out = oa.dollar_retained_test(retained, 1000.0, 2000.0, 4.0)
        assert out["ratio"] is None
        assert "gap" in out

    def test_no_row_is_data_gap(self):
        out = oa.run({"snap": None, "master": None})
        assert out["weapon"] == "owner-audit"
        assert out["status"] == "data_gap"


# ---------------------------------------------------------------------------
# dormant weapons
# ---------------------------------------------------------------------------
class TestDormant:
    @pytest.mark.parametrize("mod,wid", [
        (si, "short-interest-monitor"),
        (pg, "pendulum-gauges"),
        (mm, "mae-mfe-audit"),
        (ic, "ic-self-audit"),
    ])
    def test_dormant_envelope(self, mod, wid):
        out = mod.run({})
        assert out["weapon"] == wid
        assert out["status"] == "dormant"
        assert out["reason"]
        assert out["wake_condition"]
