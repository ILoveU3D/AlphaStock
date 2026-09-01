"""Tests for value_genie.fetch.kline (no network)."""

from datetime import datetime
from unittest.mock import patch

import pandas as pd

from value_genie.fetch import kline as k


def _em_payload(lines):
    return {"data": {"klines": lines}}


class TestFetchKline:
    def test_parses_em_payload(self):
        d = _em_payload(["2026-08-28,10.0,10.5,10.8,9.9,1000,10500.0",
                         "2026-08-31,10.5,11.0,11.2,10.4,1200,13100.0"])
        with patch.object(k, "em_push2_get", return_value=d):
            df = k.fetch_kline("1.600519")
        assert list(df.columns) == k.KLINE_COLS
        assert len(df) == 2
        assert df["close"].iloc[-1] == 11.0
        assert df["amount"].iloc[-1] == 13100.0
        assert df["date"].iloc[0] == "2026-08-28"

    def test_none_on_no_data(self):
        with patch.object(k, "em_push2_get", return_value=None):
            assert k.fetch_kline("1.600519") is None
        with patch.object(k, "em_push2_get", return_value={"data": None}):
            assert k.fetch_kline("1.600519") is None
        with patch.object(k, "em_push2_get",
                          return_value=_em_payload(["bad-line"])):
            assert k.fetch_kline("1.600519") is None

    def test_tolerates_short_rows(self):
        d = _em_payload(["2026-08-28,10.0,10.5,10.8,9.9,1000",
                         "2026-08-31,10.5,11.0,11.2,10.4,1200,13100.0"])
        with patch.object(k, "em_push2_get", return_value=d):
            df = k.fetch_kline("1.600519")
        # 6-field rows are kept; only `amount` is missing
        assert len(df) == 2
        assert pd.isna(df["amount"].iloc[0])
        assert df["amount"].iloc[1] == 13100.0


class TestFetchKlineTx:
    def test_parses_qfqday(self):
        d = {"data": {"sh600519": {"qfqday": [
            ["2026-08-28", "10.0", "10.5", "10.8", "9.9", "1000", "10500"],
            ["2026-08-31", "10.5", "11.0", "11.2", "10.4", "1200"],
        ]}}}
        with patch.object(k.TX, "get_json", return_value=d):
            df = k.fetch_kline_tx("sh600519")
        assert len(df) == 2
        assert df["close"].iloc[-1] == 11.0
        assert pd.isna(df["amount"].iloc[-1])

    def test_falls_back_to_day_key(self):
        d = {"data": {"hk00700": {"day": [
            ["2026-08-29", "300.0", "310.0", "315.0", "299.0", "9e6",
             "2.8e9"]]}}}
        with patch.object(k.TX, "get_json", return_value=d):
            df = k.fetch_kline_tx("hk00700")
        assert len(df) == 1
        assert df["close"].iloc[0] == 310.0

    def test_parses_newfqkline_rows_with_dict_element(self):
        """newfqkline rows carry a dividend dict at index 6 plus extras."""
        d = {"data": {"sh600519": {"qfqday": [
            ["2026-08-31", "1297.99", "1299.52", "1305.00", "1286.00",
             "23248.00", {"cqr": "2026-08-31"}, "0.19", "300303.37", ""]]} }}
        with patch.object(k.TX, "get_json", return_value=d):
            df = k.fetch_kline_tx("sh600519")
        assert len(df) == 1
        assert df["close"].iloc[0] == 1299.52
        assert pd.isna(df["amount"].iloc[0])

    def test_iterates_urls_until_data(self):
        """First endpoint empty -> second endpoint serves the rows."""
        empty = {"data": {"hk00700": {}}}
        good = {"data": {"hk00700": {"day": [
            ["2026-08-31", "440.0", "453.0", "456.2", "446.0", "2e7"]]}}}
        with patch.object(k.TX, "get_json",
                          side_effect=[empty, good]) as tx:
            df = k.fetch_kline_tx("hk00700")
        assert df is not None and df["close"].iloc[0] == 453.0
        assert tx.call_count == 2

    def test_none_on_no_data(self):
        with patch.object(k.TX, "get_json", return_value=None):
            assert k.fetch_kline_tx("hk00700") is None
        with patch.object(k.TX, "get_json", return_value={"data": {}}):
            assert k.fetch_kline_tx("hk00700") is None


class TestTxSymbolCandidates:
    def test_a_shanghai(self):
        assert k.tx_symbol_candidates("A", "600519", "1") == ["sh600519"]

    def test_a_shenzhen(self):
        assert k.tx_symbol_candidates("A", "000001", "0") == ["sz000001"]
        assert k.tx_symbol_candidates("A", "300750", "0") == ["sz300750"]

    def test_a_beijing(self):
        out = k.tx_symbol_candidates("A", "430047", "0")
        assert out[0] == "bj430047"

    def test_hk(self):
        assert k.tx_symbol_candidates("HK", "00700", "116") == ["hk00700"]

    def test_us_market_id_first(self):
        out = k.tx_symbol_candidates("US", "AAPL", "105")
        assert out[0] == "usAAPL.OQ"
        assert len(out) == len(config_us_suffixes())

    def test_us_unknown_market_id(self):
        out = k.tx_symbol_candidates("US", "BRK.B", "")
        assert len(out) == len(config_us_suffixes())
        assert all(s.startswith("usBRK.B") for s in out)


def config_us_suffixes():
    from value_genie import config
    return set(config.US_TX_SUFFIX.values())


class TestFetchKlineAny:
    def test_em_success_skips_tx(self):
        d = _em_payload(["2026-08-31,10.5,11.0,11.2,10.4,1200,13100.0"])
        with patch.object(k, "em_push2_get", return_value=d) as em, \
                patch.object(k.TX, "get_json") as tx:
            df = k.fetch_kline_any("A", "600519", "1")
        assert df is not None and len(df) == 1
        em.assert_called_once()
        tx.assert_not_called()

    def test_hk_clist_market_id_maps_to_secid_116(self):
        """clist quotes say HK market_id=128 but kline secid needs 116."""
        d = _em_payload(["2026-08-31,440.0,442.0,444.6,438.0,9e6,4e9"])
        with patch.object(k, "em_push2_get", return_value=d) as em, \
                patch.object(k.TX, "get_json") as tx:
            df = k.fetch_kline_any("HK", "00700", "128")
        assert df is not None and len(df) == 1
        assert em.call_args[1]["params"]["secid"] == "116.00700"
        tx.assert_not_called()

    def test_falls_back_to_tx(self):
        tx_d = {"data": {"sz000001": {"day": [
            ["2026-08-31", "10.5", "11.0", "11.2", "10.4", "1200"]]}}}
        with patch.object(k, "em_push2_get", return_value=None), \
                patch.object(k.TX, "get_json", return_value=tx_d) as tx:
            df = k.fetch_kline_any("A", "000001", "0")
        assert df is not None and len(df) == 1
        assert tx.call_count == 1

    def test_all_fail(self):
        with patch.object(k, "em_push2_get", return_value=None), \
                patch.object(k.TX, "get_json", return_value=None):
            assert k.fetch_kline_any("HK", "00700", "116") is None


class TestCacheHelpers:
    def test_save_load_roundtrip(self, tmp_path):
        df = pd.DataFrame({"date": ["2026-08-31"], "open": [10.0],
                           "close": [11.0], "high": [11.2], "low": [9.9],
                           "volume": [1200.0], "amount": [13100.0]})
        p = tmp_path / "kline" / "A_600519.csv"
        k.save_kline(df, p)
        assert p.exists()
        out = k.load_kline(p)
        assert out["date"].iloc[0] == "2026-08-31"
        assert out["close"].iloc[0] == 11.0

    def test_load_missing(self, tmp_path):
        assert k.load_kline(tmp_path / "nope.csv") is None

    def test_cache_path(self, tmp_path):
        p = k.kline_cache_path(tmp_path, "HK", "00700")
        assert p == tmp_path / "kline" / "HK_00700.csv"


class TestFreshness:
    def _write(self, tmp_path, last_date, market="A", code="600519"):
        df = pd.DataFrame({"date": [last_date], "open": [1.0],
                           "close": [1.0], "high": [1.0], "low": [1.0],
                           "volume": [1.0], "amount": [1.0]})
        p = tmp_path / "kline" / f"{market}_{code}.csv"
        k.save_kline(df, p)
        return p

    def test_fresh_on_latest_trading_day(self, tmp_path):
        # Monday 2026-08-31 20:00 -> expected A trading day = Mon 08-31
        p = self._write(tmp_path, "2026-08-31")
        assert k.kline_is_fresh(p, "A", datetime(2026, 8, 31, 20, 0))

    def test_stale_on_old_bar(self, tmp_path):
        p = self._write(tmp_path, "2026-08-28")  # Friday
        assert not k.kline_is_fresh(p, "A", datetime(2026, 8, 31, 20, 0))

    def test_weekend_run_uses_friday(self, tmp_path):
        # Saturday run: expected trading day is Friday 08-28
        p = self._write(tmp_path, "2026-08-28")
        assert k.kline_is_fresh(p, "A", datetime(2026, 8, 29, 10, 0))

    def test_sunday_run_uses_friday(self, tmp_path):
        p = self._write(tmp_path, "2026-08-28")
        assert k.kline_is_fresh(p, "A", datetime(2026, 8, 30, 10, 0))

    def test_before_close_uses_previous_day(self, tmp_path):
        # Monday 10:00 (market open): yesterday Friday is the freshest
        # completed session
        p = self._write(tmp_path, "2026-08-28")
        assert k.kline_is_fresh(p, "A", datetime(2026, 8, 31, 10, 0))

    def test_us_tolerates_three_days(self, tmp_path):
        # Monday run for US: expected Fri 08-29 -> Sun? No: US expected =
        # 08-30 (Sun) -> Fri 08-28. Last bar Thu 08-27 -> 1 day lag, fresh.
        p = self._write(tmp_path, "2026-08-27")
        assert k.kline_is_fresh(p, "US", datetime(2026, 8, 31, 10, 0))

    def test_us_stale_beyond_tolerance(self, tmp_path):
        # expected Fri 08-28; last bar Mon 08-24 -> 4 days lag > 3 tolerance
        p = self._write(tmp_path, "2026-08-24")
        assert not k.kline_is_fresh(p, "US", datetime(2026, 8, 31, 10, 0))

    def test_missing_file(self, tmp_path):
        assert not k.kline_is_fresh(tmp_path / "nope.csv", "A")

    def test_corrupt_file(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("not,a,valid\nkline,file\n", encoding="utf-8")
        # header exists but date column is unparseable -> not fresh
        assert not k.kline_is_fresh(p, "A")
