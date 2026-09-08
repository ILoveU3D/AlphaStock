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
