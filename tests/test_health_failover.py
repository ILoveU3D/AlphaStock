"""Tests for fetch.health (dynamic source demotion) and fetch.driver
(health-ordered failover) — user mandate 2026-10-08: a source that keeps
refusing connections sinks automatically; backups are pluggable."""

import pandas as pd
import pytest
import requests

from value_genie.fetch import driver, health as hm
from value_genie.fetch import quotes as q
from value_genie.strategy import registry


@pytest.fixture()
def health(tmp_path):
    return hm.SourceHealth(tmp_path / "source_health.json")


class TestSourceHealth:
    def test_missing_file_is_all_healthy(self, health):
        assert health.penalty("eastmoney") == 0

    def test_failure_grading(self, health):
        # ConnectionError sinks fastest (3): two of them already park the
        # source (3+3 >= COOLDOWN_AFTER)
        health.record_failure("eastmoney", requests.ConnectionError("x"))
        assert health.penalty("eastmoney") == 3 * hm.FAIL_PENALTY
        # 5xx is grade 2
        err = requests.HTTPError("HTTP 503")
        err.response = requests.Response()
        err.response.status_code = 503
        health.record_failure("tencent", err)
        assert health.penalty("tencent") == 2 * hm.FAIL_PENALTY
        # empty data / parse issues are grade 1
        health.record_failure("sec_edgar", None)
        assert health.penalty("sec_edgar") == 1 * hm.FAIL_PENALTY

    def test_cooldown_after_accumulated_weight(self, health):
        health.record_failure("eastmoney", requests.ConnectionError("x"))
        health.record_failure("eastmoney", requests.ConnectionError("x"))
        # 3+3 = 6 >= 5 -> cooling down, penalty dominates any priority
        assert health.penalty("eastmoney") >= hm.COOLDOWN_PENALTY

    def test_success_clears_failures(self, health):
        health.record_failure("eastmoney", None)
        assert health.penalty("eastmoney") > 0
        health.record_success("eastmoney")
        assert health.penalty("eastmoney") == 0

    def test_save_load_roundtrip(self, health):
        health.record_failure("tencent", None)
        health.save()
        again = hm.SourceHealth(health.path)
        assert again.penalty("tencent") == hm.FAIL_PENALTY

    def test_save_noop_when_clean(self, health):
        health.save()                      # nothing recorded -> no file
        assert not health.path.exists()


class TestOrderedSources:
    def test_static_order_without_health(self):
        ids = [d.id for d in registry.ordered_sources("quotes", "HK")]
        assert ids == ["eastmoney", "tencent"]

    def test_penalty_flips_order(self, health):
        # three ConnectionErrors (grade 3 x3 = 9 >= 5) -> cooldown, EM
        # sinks below Tencent exactly as the user asked ("总是拒绝 IP
        # 请求 -> 优先级降低")
        for _ in range(3):
            health.record_failure("eastmoney",
                                  requests.ConnectionError("refused"))
        ids = [d.id for d in registry.ordered_sources(
            "quotes", "HK", health)]
        assert ids[0] == "tencent"

    def test_recovery_restores_order(self, health):
        health.record_failure("eastmoney", None)
        health.record_failure("eastmoney", None)
        assert [d.id for d in registry.ordered_sources(
            "quotes", "HK", health)][0] == "tencent"   # 2*50+10 > 20
        health.record_success("eastmoney")
        assert [d.id for d in registry.ordered_sources(
            "quotes", "HK", health)][0] == "eastmoney"


class TestRunWithFailover:
    def test_first_success_wins(self, health):
        res, src, errors = driver.run_with_failover(
            "quotes", "HK",
            {"eastmoney": lambda: {"price": 1.0},
             "tencent": lambda: {"price": 2.0}}, health)
        assert src == "eastmoney" and res["price"] == 1.0
        assert errors == []

    def test_empty_result_moves_on_without_penalty(self, health):
        res, src, _ = driver.run_with_failover(
            "kline", "A",
            {"eastmoney": lambda: None,
             "tencent": lambda: pd.DataFrame({"close": [1.0]})}, health)
        assert src == "tencent" and res is not None
        # a per-entity miss is not an outage: no failure recorded
        assert health.penalty("eastmoney") == 0

    def test_exception_records_failure_and_fails_over(self, health):
        def boom():
            raise requests.ConnectionError("refused")

        res, src, errors = driver.run_with_failover(
            "quotes", "A",
            {"eastmoney": boom,
             "tencent": lambda: {"price": 3.0}}, health)
        assert src == "tencent" and res["price"] == 3.0
        assert "ConnectionError" in errors[0]
        assert health.penalty("eastmoney") == 3 * hm.FAIL_PENALTY

    def test_cooling_source_is_not_tried(self, health):
        for _ in range(2):       # grade 3 x2 = 6 >= 5 -> cooldown
            health.record_failure("eastmoney",
                                  requests.ConnectionError("refused"))
        called = []
        # tencent misses (empty result) so iteration reaches the cooled
        # eastmoney entry — which must be skipped without being called.
        res, src, errors = driver.run_with_failover(
            "quotes", "A",
            {"eastmoney": lambda: called.append(1) or {"price": 1.0},
             "tencent": lambda: None}, health)
        assert called == []                     # never attempted
        assert res is None and src is None
        assert any("cooldown" in e for e in errors)

    def test_cooling_source_yields_primary_seat(self, health):
        for _ in range(2):
            health.record_failure("eastmoney",
                                  requests.ConnectionError("refused"))
        called = []
        res, src, _errors = driver.run_with_failover(
            "quotes", "A",
            {"eastmoney": lambda: called.append(1) or {"price": 1.0},
             "tencent": lambda: {"price": 2.0}}, health)
        assert called == []                     # cooled primary not tried
        assert src == "tencent" and res["price"] == 2.0

    def test_total_failure_returns_none_with_errors(self, health):
        res, src, errors = driver.run_with_failover(
            "quotes", "US",
            {"eastmoney": lambda: None, "tencent": lambda: None}, health)
        assert res is None and src is None


class TestQuotesFailoverWiring:
    """fetch_market_quotes consults the health-ordered registry."""

    def test_tx_fallback_frame_is_not_marked_partial(self, monkeypatch,
                                                     health):
        """EM outage -> Tencent-degraded universe is COMPLETE (never
        persisted as a partial market)."""
        monkeypatch.setattr(q, "em_push2_get", lambda *a, **k: None)
        tx = pd.DataFrame([{"market": "HK", "code": "00700",
                            "price": 300.0}])
        tx.attrs["fallback"] = "tencent"
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda market, universe=None: tx)
        df = q.fetch_market_quotes("HK", health=health)
        assert df.attrs.get("fallback") == "tencent"
        assert df.attrs.get("partial") is not True

    def test_tx_preferred_when_eastmoney_cooling(self, monkeypatch,
                                                 health):
        for _ in range(2):
            health.record_failure("eastmoney",
                                  requests.ConnectionError("refused"))
        em_called = []
        monkeypatch.setattr(q, "em_push2_get",
                            lambda *a, **k: em_called.append(1))
        tx = pd.DataFrame([{"market": "A", "code": "600519",
                            "price": 1500.0}])
        tx.attrs["fallback"] = "tencent"
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda market, universe=None: tx)
        df = q.fetch_market_quotes("A", health=health)
        assert em_called == []                    # EM never touched
        assert df.attrs.get("fallback") == "tencent"

    def test_em_first_when_healthy(self, monkeypatch, health):
        pages = {"n": 0}

        def fake_em(path, params=None, timeout=20):
            pages["n"] += 1
            if pages["n"] > 1:
                return {"data": {"diff": [], "total": 1}}
            return {"data": {"diff": [
                {"f12": "600519", "f2": 1500.0, "f13": 1,
                 "f14": "Moutai"}], "total": 1}}

        monkeypatch.setattr(q, "em_push2_get", fake_em)
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda market, universe=None:
                            pytest.fail("TX must not run when EM works"))
        df = q.fetch_market_quotes("A", health=health)
        assert len(df) == 1
        assert df.iloc[0]["code"] == "600519"
