"""Tests for value_genie.model.engine (pure driver-based FCFF DCF)."""

import pytest

from value_genie.model import engine


def _scenario(g=0.10, m=0.20, da=0.03, capex=0.05, nwc=0.10):
    return {"prob": 1.0, "revenue_growth": [g] * 5, "ebit_margin": [m] * 5,
            "da_pct_rev": da, "capex_pct_rev": capex, "nwc_pct_drev": nwc}


class TestFcffPath:
    def test_hand_computed_first_year(self):
        # rev0=100, g=10% -> rev1=110; ebit=22; nopat(税15%)=18.7
        # da=3.3; capex=5.5; dnwc=(110-100)*0.10=1.0 -> fcff=15.5
        rows = engine.fcff_path(100.0, _scenario(), 5, 0.15)
        r1 = rows[0]
        assert r1["revenue"] == pytest.approx(110.0)
        assert r1["ebit"] == pytest.approx(22.0)
        assert r1["fcff"] == pytest.approx(18.7 + 3.3 - 5.5 - 1.0)

    def test_growth_path_fades_with_short_lists(self):
        s = _scenario()
        s["revenue_growth"] = [0.20, 0.10]   # 之后沿用最后值
        rows = engine.fcff_path(100.0, s, 4, 0.15)
        assert rows[0]["revenue"] == pytest.approx(120.0)
        assert rows[1]["revenue"] == pytest.approx(132.0)
        assert rows[2]["revenue"] == pytest.approx(145.2)


class TestDcfValue:
    def test_hand_computed(self):
        # fcff=[10,10], wacc=10%, tg=2%:
        # pv = 10/1.1 + 10/1.21 = 17.3554
        # tv = 10*1.02/0.08 = 127.5; pv_tv = 127.5/1.21 = 105.372
        ev = engine.dcf_value([10.0, 10.0], 0.10, 0.02)
        assert ev == pytest.approx(17.3554 + 105.372, abs=1e-2)

    def test_invalid_when_wacc_le_terminal_g(self):
        assert engine.dcf_value([10.0], 0.02, 0.025) is None


class TestRunModel:
    def _history(self):
        return {"id": "A:600900", "market": "A", "code": "600900",
                "currency": "CNY", "history_hash": "abc123",
                "years": [{"fy": 2024, "revenue": 100.0, "ebit": 20.0,
                           "net_income": 15.0, "da": 3.0, "capex": 5.0,
                           "ocf": 18.0, "cash": 20.0, "debt": 10.0,
                           "shares": 10.0}]}

    def _assumptions(self):
        return {"id": "A:600900", "market": "A", "code": "600900",
                "horizon_years": 5, "wacc": 0.10, "terminal_g": 0.025,
                "tax_rate": 0.15, "net_debt": -10.0, "shares": 10.0,
                "currency": "CNY",
                "scenarios": {
                    "bear": {** _scenario(0.05, 0.15), "prob": 0.25},
                    "base": {** _scenario(0.10, 0.20), "prob": 0.50},
                    "bull": {** _scenario(0.15, 0.25), "prob": 0.25}}}

    def test_scenario_weighting_and_bridge(self):
        r = engine.run_model(self._history(), self._assumptions(),
                             price=20.0)
        s = r["scenarios"]
        for k in ("bear", "base", "bull"):
            assert s[k]["per_share"] is not None
        # bull 增速/利润率更高 → 价值单调
        assert s["bull"]["per_share"] > s["base"]["per_share"] > \
            s["bear"]["per_share"]
        w = r["weighted_per_share"]
        expect = sum(s[k]["per_share"] * s[k]["prob"] for k in s)
        assert w == pytest.approx(expect)
        # upside 与加权价一致
        assert r["upside_pct"] == pytest.approx((w - 20.0) / 20.0 * 100.0)
        assert r["history_hash"] == "abc123"
        # equity bridge: net_debt=-10（净现金）→ equity = EV + 10
        base_rows = engine.fcff_path(100.0, _scenario(0.10, 0.20), 5, 0.15)
        ev = engine.dcf_value([x["fcff"] for x in base_rows], 0.10, 0.025)
        assert s["base"]["per_share"] == pytest.approx((ev + 10.0) / 10.0)

    def test_missing_shares_declares_gap(self):
        a = self._assumptions()
        a["shares"] = None
        r = engine.run_model(self._history(), a, price=20.0)
        assert r["weighted_per_share"] is None
        assert any("shares" in g for g in r["gaps"])

    def test_missing_price_gives_no_upside(self):
        r = engine.run_model(self._history(), self._assumptions(),
                             price=None)
        assert r["weighted_per_share"] is not None
        assert r["upside_pct"] is None

    def test_sensitivity_monotonic_in_wacc(self):
        r = engine.run_model(self._history(), self._assumptions(),
                             price=20.0)
        vals = r["sensitivity"]["values"]   # rows=wacc, cols=terminal_g
        for row in vals:
            assert all(v is not None for v in row)
        col0 = [row[0] for row in vals]
        assert col0 == sorted(col0, reverse=True)   # wacc 升 → 价值降

    def test_tax_rate_zero_is_respected(self):
        # 股息贴现翻译：tax=0（现金流已税后）。`or` 默认值曾把 0 静默
        # 替换成 0.15，导致全线 0.85 缩放——0 是合法税率输入。
        a = self._assumptions()
        a["tax_rate"] = 0.0
        r = engine.run_model(self._history(), a, price=20.0)
        base_rows = engine.fcff_path(100.0, _scenario(0.10, 0.20), 5, 0.0)
        ev = engine.dcf_value([x["fcff"] for x in base_rows], 0.10, 0.025)
        assert r["scenarios"]["base"]["per_share"] == \
            pytest.approx((ev + 10.0) / 10.0)

    def test_terminal_g_zero_is_respected(self):
        # BKE 校准案：档案论点是 g≈0 带宽震荡，`or` 默认值曾把 0.0 静默
        # 替换成 0.025，终值虚增——0 是合法终值增速输入。
        a = self._assumptions()
        a["terminal_g"] = 0.0
        r = engine.run_model(self._history(), a, price=20.0)
        assert r["terminal_g"] == 0.0
        base_rows = engine.fcff_path(100.0, _scenario(0.10, 0.20), 5, 0.15)
        ev = engine.dcf_value([x["fcff"] for x in base_rows], 0.10, 0.0)
        assert r["scenarios"]["base"]["per_share"] == \
            pytest.approx((ev + 10.0) / 10.0)
