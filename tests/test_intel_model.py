"""Tests for value_genie.intel.model (no network)."""

from datetime import date

from value_genie.intel import model


class TestIntelItem:
    def test_defaults(self):
        it = model.IntelItem(
            market="A", code="688795", name="摩尔线程-U",
            subsystem="announcements", kind="unlock",
            event_date=date(2026, 9, 12), title="限售解禁")
        assert it.impact == "neutral"
        assert it.payload == {}
        assert it.url == ""
        assert it.source == "eastmoney"

    def test_row_round_trip(self):
        it = model.IntelItem(
            market="A", code="688795", name="摩尔线程-U",
            subsystem="announcements", kind="unlock",
            event_date=date(2026, 9, 12), title="限售解禁 12% 总股本",
            source="eastmoney", impact="negative",
            payload={"unlock_pct": 12.0})
        row = model.item_to_row(it)
        assert row["event_date"] == "2026-09-12"
        back = model.row_to_item(row)
        assert back == it

    def test_impact_map_values(self):
        assert set(model.IMPACT_BY_KIND.values()) <= {
            "positive", "negative", "neutral"}
        assert model.IMPACT_BY_KIND["unlock"] == "negative"
        assert model.IMPACT_BY_KIND["buyback"] == "positive"
        assert model.IMPACT_BY_KIND["holder_add"] == "positive"

    def test_forecast_direction(self):
        assert model.FORECAST_DIRECTION["预增"] == 1
        assert model.FORECAST_DIRECTION["扭亏"] == 1
        assert model.FORECAST_DIRECTION["首亏"] == -1
        assert model.FORECAST_DIRECTION["续亏"] == -1
        # unknown PREDICT_TYPE -> neutral via .get default
        assert model.FORECAST_DIRECTION.get("预盈", 0) == 0


class TestEarningsQuality:
    def test_receivables_flag(self):
        assert model.earnings_quality(
            {"rev_yoy": 20.0, "rece_yoy": 35.0}) == ["eq_receivables"]
        # exactly at the pad (20+10) -> not a flag
        assert model.earnings_quality(
            {"rev_yoy": 20.0, "rece_yoy": 30.0}) == []

    def test_inventory_flag(self):
        assert model.earnings_quality(
            {"rev_yoy": 5.0, "inv_yoy": 20.0}) == ["eq_inventory"]

    def test_ocf_gap(self):
        assert model.earnings_quality(
            {"ocf": 40.0, "profit": 100.0}) == ["eq_ocf_gap"]
        assert model.earnings_quality(
            {"ocf": 50.0, "profit": 100.0}) == []      # boundary: not <
        assert model.earnings_quality(
            {"ocf": -10.0, "profit": 100.0}) == ["eq_ocf_gap"]
        # loss-maker: a negative-profit ratio is meaningless -> skip
        assert model.earnings_quality(
            {"ocf": 10.0, "profit": -100.0}) == []

    def test_nonrecurring(self):
        assert model.earnings_quality(
            {"deduct_eps": 0.5, "basic_eps": 1.0}) == ["eq_nonrecurring"]
        assert model.earnings_quality(
            {"deduct_eps": 0.6, "basic_eps": 1.0}) == []  # boundary
        assert model.earnings_quality(
            {"deduct_eps": 0.1, "basic_eps": -1.0}) == []  # negative base

    def test_all_four(self):
        rec = {"rev_yoy": 10.0, "rece_yoy": 30.0, "inv_yoy": 30.0,
               "ocf": 10.0, "profit": 100.0,
               "deduct_eps": 0.1, "basic_eps": 1.0}
        assert model.earnings_quality(rec) == [
            "eq_receivables", "eq_inventory", "eq_ocf_gap",
            "eq_nonrecurring"]

    def test_missing_inputs_never_flag(self):
        assert model.earnings_quality({}) == []
        assert model.earnings_quality(
            {"rev_yoy": None, "rece_yoy": float("nan")}) == []
        assert model.earnings_quality({"rece_yoy": 99.0}) == []
