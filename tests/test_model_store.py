"""Tests for value_genie.model.store (local-only model persistence)."""

import pandas as pd
import pytest

from value_genie import config
from value_genie.model import store


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path


def _history(fy=(2022, 2023, 2024)):
    years = [{"fy": y, "revenue": 100e8 * (1.1 ** (y - 2022)),
              "ebit": 15e8, "net_income": 12e8, "da": 3e8, "capex": 5e8,
              "ocf": 14e8, "cash": 20e8, "debt": 10e8, "shares": 1e8}
             for y in fy]
    return store.new_history("A", "600900", name="长江电力",
                             source="test", currency="CNY", years=years)


class TestHistory:
    def test_roundtrip_and_hash(self, mdir):
        h = _history()
        p = store.save_history(h)
        assert p.exists()
        assert p.parent.name == "600900"
        assert p.parent.parent.name == "a"
        loaded = store.load_history("A", "600900")
        assert loaded["years"][-1]["fy"] == 2024
        assert loaded["history_hash"] == h["history_hash"]
        assert len(h["history_hash"]) == 12

    def test_load_missing_returns_none(self, mdir):
        assert store.load_history("A", "000001") is None
        assert store.load_assumptions("A", "000001") is None
        assert store.load_result("A", "000001") is None

    def test_corrupt_raises(self, mdir):
        p = store.history_path("A", "600900")
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            store.load_history("A", "600900")


class TestDefaults:
    def test_default_assumptions_from_history(self, mdir):
        store.save_history(_history())
        a = store.default_assumptions("A", "600900")
        assert a["version"] == 1
        assert set(a["scenarios"]) == {"bear", "base", "bull"}
        probs = [s["prob"] for s in a["scenarios"].values()]
        assert abs(sum(probs) - 1.0) < 1e-9
        base = a["scenarios"]["base"]
        assert len(base["revenue_growth"]) == a["horizon_years"]
        # 历史中位增速 ~10% → base 首年增速应接近 0.10
        assert base["revenue_growth"][0] == pytest.approx(0.10, abs=0.02)
        assert a["wacc"] == config.DCF_DISCOUNT
        assert a["terminal_g"] == config.DCF_TERMINAL_G
        assert a["net_debt"] == pytest.approx(10e8 - 20e8)
        assert a["shares"] == pytest.approx(1e8)

    def test_missing_fields_declared_in_gaps(self, mdir):
        h = _history()
        for y in h["years"]:
            y["da"] = None
            y["capex"] = None
        store.save_history(h)
        a = store.default_assumptions("A", "600900")
        assert any("da" in g or "capex" in g for g in a["gaps"])
        assert a["scenarios"]["base"]["capex_pct_rev"] == \
            config.MODEL_FALLBACK_CAPEX_PCT


class TestSetAndResult:
    def test_set_appends_changelog(self, mdir):
        store.save_history(_history())
        store.save_assumptions(store.default_assumptions("A", "600900"))
        a = store.set_assumptions(
            "A", "600900",
            {"base.revenue_growth": [0.2, 0.18, 0.15, 0.12, 0.10],
             "wacc": 0.11}, reason="年报读后上调")
        assert a["wacc"] == 0.11
        assert a["scenarios"]["base"]["revenue_growth"][0] == 0.2
        assert len(a["changelog"]) == 2
        assert a["changelog"][0]["reason"] == "年报读后上调"
        # 持久化
        assert store.load_assumptions("A", "600900")["wacc"] == 0.11

    def test_set_requires_reason(self, mdir):
        store.save_history(_history())
        store.save_assumptions(store.default_assumptions("A", "600900"))
        with pytest.raises(ValueError):
            store.set_assumptions("A", "600900", {"wacc": 0.11}, reason="")

    def test_set_unknown_key_raises(self, mdir):
        store.save_history(_history())
        store.save_assumptions(store.default_assumptions("A", "600900"))
        with pytest.raises(ValueError):
            store.set_assumptions("A", "600900", {"bogus": 1}, reason="x")

    def test_result_stale_on_history_change(self, mdir):
        store.save_history(_history())
        r = {"id": "A:600900", "market": "A", "code": "600900",
             "history_hash": store.load_history("A", "600900")
                             ["history_hash"],
             "weighted_per_share": 30.0, "upside_pct": 12.0}
        store.save_result(r)
        assert not store.is_stale(store.load_result("A", "600900"),
                                  store.load_history("A", "600900"))
        store.save_history(_history(fy=(2023, 2024, 2025)))
        assert store.is_stale(store.load_result("A", "600900"),
                              store.load_history("A", "600900"))


class TestDcfOverlay:
    def _frame(self):
        return pd.DataFrame({
            "market": ["A", "A"], "code": ["600900", "000001"],
            "core_business": [80.0, 60.0], "core_culture": [70.0, 60.0],
            "core_dcf": [50.0, 40.0],
            "core_gaps": ["culture unscored", None]})

    def test_overlay_replaces_core_dcf(self, mdir):
        df = self._frame()
        out, n = store.apply_modeled_dcf(
            df, scores={"A:600900": 25.0})   # upside 25%
        assert n == 1
        lo, hi = config.CORE_ANCHORS["model_upside"]
        expect = (25.0 - lo) / (hi - lo) * 100.0
        assert out.loc[0, "core_dcf"] == pytest.approx(expect)
        assert out.loc[0, "core_score"] == pytest.approx(
            (80.0 + 70.0 + expect) / 3)
        assert store.DCF_MODELED in out.loc[0, "core_gaps"]
        # 无模型行不动
        assert out.loc[1, "core_dcf"] == 40.0

    def test_load_dcf_scores_skips_stale(self, mdir):
        store.save_history(_history())
        h = store.load_history("A", "600900")
        store.save_result({"id": "A:600900", "market": "A", "code": "600900",
                           "history_hash": h["history_hash"],
                           "weighted_per_share": 30.0, "upside_pct": 25.0})
        assert store.load_dcf_scores() == {"A:600900": 25.0}
        store.save_history(_history(fy=(2023, 2024, 2025)))
        assert store.load_dcf_scores() == {}
