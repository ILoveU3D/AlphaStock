"""Tests for value_genie.fetch.quotes (no network)."""

from types import SimpleNamespace

import pandas as pd
import pytest

from value_genie.fetch.quotes import (_parse_clist_rows,
                                      exclude_non_operating_names,
                                      exclude_risk_names,
                                      fetch_quote_any, fetch_quote_tx)


def _row(code="600519", price="1500.5", name="Kweichow Moutai", **kw):
    base = {"f12": code, "f2": price, "f13": "1", "f14": name,
            "f100": "Liquor", "f3": "1.2", "f5": "1000", "f6": "2e8",
            "f8": "0.5", "f9": "25", "f20": "1.9e12", "f21": "1.9e12",
            "f23": "8.5", "f114": "26", "f115": "24"}
    base.update(kw)
    return base


class TestParseClistRows:
    def test_basic_mapping(self):
        out = _parse_clist_rows([_row()])
        assert len(out) == 1
        r = out[0]
        assert r["code"] == "600519"
        assert r["price"] == 1500.5
        assert r["pe_ttm"] == 24.0
        assert r["pb"] == 8.5
        assert r["market_id"] == "1"
        assert r["industry"] == "Liquor"

    def test_drops_null_price(self):
        out = _parse_clist_rows([_row(price="-"), _row(price="")])
        assert out == []

    def test_drops_missing_code(self):
        out = _parse_clist_rows([_row(code="")])
        assert out == []

    def test_negative_price_fields_kept(self):
        # negative PE (loss-making) must be preserved, not filtered
        out = _parse_clist_rows([_row(f115="-12.3")])
        assert out[0]["pe_ttm"] == -12.3

    def test_empty(self):
        assert _parse_clist_rows(None) == []
        assert _parse_clist_rows([]) == []


class TestExcludeRiskNames:
    def test_excludes_st(self):
        import pandas as pd
        df = pd.DataFrame({"name": ["Normal Co", "ST Bad", "*ST Worse",
                                    "Retiring退", "Fine"]})
        out = exclude_risk_names(df)
        assert list(out["name"]) == ["Normal Co", "Fine"]


class TestExcludeNonOperatingNames:
    def test_excludes_leveraged_and_preferred(self):
        import pandas as pd
        df = pd.DataFrame({"name": [
            "Apple Inc",
            "MicroSectors U.S. Big Oil Index -3X Inverse Le",
            "MAX Airlines -3X Inverse Leveraged ETN",
            "二倍做多AAL ETF-Leverage",
            "Oracle Corp Series D Pfd",
            "AT&T Inc Series C Pfd",
            "Wells Fargo & Co Series Z Pfd",
            "Vaneck Bitcoin Strategy Etf",
            "Coinbase Global Inc",        # legit, must stay
            "American Assets Trust Inc",  # legit REIT, must stay
        ]})
        out = exclude_non_operating_names(df)
        assert list(out["name"]) == ["Apple Inc", "Coinbase Global Inc",
                                     "American Assets Trust Inc"]

    def test_empty_or_missing_name_column(self):
        import pandas as pd
        assert exclude_non_operating_names(
            pd.DataFrame(columns=["code"])).empty


class TestFetchMarketQuotes:
    def test_retries_failed_page(self, monkeypatch):
        from value_genie.fetch import quotes as q

        pages = [None, {"data": {"total": 1, "diff": [_row()]}}]
        calls = []

        def fake_get(path, params=None, **kw):
            calls.append(params["pn"])
            return pages[min(len(calls) - 1, len(pages) - 1)]

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert len(df) == 1
        assert calls == [1, 1]  # page 1 failed once, then retried OK

    def test_gives_up_after_retry_cap(self, monkeypatch):
        from value_genie import config
        from value_genie.fetch import quotes as q

        calls = []

        def fake_get(path, params=None, **kw):
            calls.append(params["pn"])
            return None  # every page fails

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda m: pd.DataFrame())  # isolate EM layer
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert df.empty
        assert calls == [1] * (config.QUOTE_PAGE_RETRIES + 1)

    def test_mid_pagination_failure_retries_same_page(self, monkeypatch):
        """A failed page N>1 must be retried, not silently truncated."""
        from value_genie.fetch import quotes as q

        pages = {
            1: [{"data": {"total": 3, "diff": [_row("600001"),
                                               _row("600002")]}}],
            2: [None, {"data": {"total": 3, "diff": [_row("600003")]}}],
        }
        calls = []

        def fake_get(path, params=None, **kw):
            pn = params["pn"]
            calls.append(pn)
            hist = pages.setdefault(pn, [None])
            return hist.pop(0) if len(hist) > 1 else hist[0]

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert len(df) == 3
        assert calls == [1, 2, 2]  # page 2 failed once, retried, succeeded

    def test_mid_pagination_failure_warns_on_partial(self, monkeypatch,
                                                     capsys):
        """Exhausted retries mid-universe must WARN, not break silently."""
        from value_genie import config
        from value_genie.fetch import quotes as q

        calls = []

        def fake_get(path, params=None, **kw):
            pn = params["pn"]
            calls.append(pn)
            if pn == 1:
                return {"data": {"total": 3, "diff": [_row("600001"),
                                                      _row("600002")]}}
            return None  # page 2 always fails

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda m: pd.DataFrame())  # isolate EM layer
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert len(df) == 2  # partial universe kept
        assert calls == [1] + [2] * (config.QUOTE_PAGE_RETRIES + 1)
        assert "WARN" in capsys.readouterr().out

    def test_partial_universe_is_flagged(self, monkeypatch):
        """Retry-exhausted mid-universe pages must flag the frame partial
        so the pipeline never persists half a market as complete."""
        from value_genie.fetch import quotes as q

        def fake_get(path, params=None, **kw):
            if params["pn"] == 1:
                return {"data": {"total": 3, "diff": [_row("600001"),
                                                      _row("600002")]}}
            return None  # page 2 always fails

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda m: pd.DataFrame())  # isolate EM layer
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert len(df) == 2
        assert df.attrs.get("partial") is True

    def test_complete_universe_not_flagged(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "em_push2_get", lambda *a, **k: {
            "data": {"total": 1, "diff": [_row()]}})
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert len(df) == 1
        assert df.attrs.get("partial") in (None, False)


# ---------------------------------------------------------------------------
# Tencent realtime fallback + fetch_quote_any (price redundancy)
# ---------------------------------------------------------------------------
def _tx_session(payload: bytes, status: int = 200):
    class FakeResp:
        pass

    resp = FakeResp()
    resp.status_code = status
    resp.content = payload

    class FakeSession:
        @staticmethod
        def get(url, timeout=10):
            return resp

    return SimpleNamespace(session=FakeSession())


class TestFetchQuoteTx:
    def test_parses_gbk_payload(self, monkeypatch):
        from value_genie.fetch import quotes as q

        # layout: idx1 name, idx2 code, idx3 price, idx4 prev close
        raw = 'v_sh588060="1~上证科创ETF~588060~1.05~1.04~1.06~1.03~...~";'
        monkeypatch.setattr(q, "TX", _tx_session(raw.encode("gbk")))
        out = q.fetch_quote_tx("sh588060")
        assert out["name"] == "上证科创ETF"
        assert out["code"] == "588060"
        assert out["price"] == 1.05
        assert out["prev_close"] == 1.04
        assert out["pct_chg"] == pytest.approx(
            (1.05 / 1.04 - 1.0) * 100.0)

    def test_garbage_returns_none(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "TX", _tx_session(b"pv_none=1;"))
        assert q.fetch_quote_tx("sh000000") is None

    def test_http_error_returns_none(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "TX", _tx_session(b"", status=502))
        assert q.fetch_quote_tx("sh588060") is None


class TestFetchQuoteAny:
    def test_em_ulist_preferred(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(
            q, "fetch_quotes_by_secids",
            lambda s: pd.DataFrame([{"code": "600519", "name": "Moutai",
                                     "price": 1500.0, "pe_ttm": 25.0}]))
        out = q.fetch_quote_any("A", "600519")
        assert out["price"] == 1500.0

    def test_tencent_fallback_for_out_of_universe_etf(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "fetch_quotes_by_secids",
                            lambda s: pd.DataFrame())
        # EM cannot serve the ETF; Tencent serves it under sh (5-prefix)
        monkeypatch.setattr(
            q, "fetch_quote_tx",
            lambda sym: {"code": "588060", "name": "上证科创ETF",
                         "price": 1.05, "prev_close": 1.04,
                         "pct_chg": 0.96} if sym == "sh588060" else None)
        out = q.fetch_quote_any("A", "588060")
        assert out["price"] == 1.05
        assert out["market_id"] == ""

    def test_all_sources_fail_returns_none(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "fetch_quotes_by_secids",
                            lambda s: pd.DataFrame())
        monkeypatch.setattr(q, "fetch_quote_tx", lambda sym: None)
        assert q.fetch_quote_any("HK", "00700") is None


# ---------------------------------------------------------------------------
# Tencent full-market batch fallback (EM push2 outage)
# ---------------------------------------------------------------------------
def _tx_market_tx(lines):
    text = "\n".join('v_%s="%s";' % (s, p) for s, p in lines)
    return _tx_session(text.encode("gbk"))


def _tx_parts(nfields=88, **over):
    parts = ["x"] * nfields
    parts[1], parts[2], parts[3], parts[4], parts[6] = (
        "Name", "CODE", "10.0", "9.0", "1000")
    parts[37], parts[38], parts[39] = "5000", "1.5", "12.5"
    parts[44], parts[45], parts[46] = "80.0", "100.0", "2.5"
    for k, v in over.items():
        parts[int(k)] = v
    return "~".join(parts)


class TestFetchMarketQuotesTx:
    def _universe(self):
        return pd.DataFrame({
            "code": ["600519", "000807"],
            "industry": ["Liquor", "Aluminum"],
            "market_id": ["1", "0"],
        })

    def test_a_share_batch_mapping(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "TX", _tx_market_tx([
            ("sh600519", _tx_parts(**{"1": "贵州茅台", "2": "600519"})),
            ("sz000807", _tx_parts(**{"1": "云铝股份", "2": "000807",
                                      "3": "25.35"})),
        ]))
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes_tx("A", universe=self._universe())
        assert len(df) == 2
        r = df[df["code"] == "600519"].iloc[0]
        assert r["price"] == 10.0
        assert r["pct_chg"] == pytest.approx((10.0 / 9.0 - 1.0) * 100.0)
        assert r["pe_ttm"] == 12.5
        assert r["pe_dyn"] is None or pd.isna(r["pe_dyn"])
        assert r["pb"] == 2.5
        assert r["market_cap"] == 100.0 * 1e8
        assert r["float_cap"] == 80.0 * 1e8
        assert r["amount"] == 5000 * 1e4
        assert r["turnover"] == 1.5
        assert r["industry"] == "Liquor"      # inherited from universe
        assert r["market_id"] == "1"
        assert df.attrs["fallback"] == "tencent"

    def test_hk_no_pb(self, monkeypatch):
        from value_genie.fetch import quotes as q

        uni = pd.DataFrame({"code": ["01258"], "industry": ["Metals"],
                            "market_id": ["116"]})
        hk = _tx_parts(78, **{"1": "中国有色矿业", "2": "01258",
                              "46": "CHINFMINING"})
        monkeypatch.setattr(q, "TX", _tx_market_tx([("hk01258", hk)]))
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes_tx("HK", universe=uni)
        assert pd.isna(df.iloc[0]["pb"])
        assert df.iloc[0]["industry"] == "Metals"
        assert df.iloc[0]["market_id"] == "116"

    def test_us_code_from_request_symbol_map(self, monkeypatch):
        from value_genie.fetch import quotes as q

        uni = pd.DataFrame({"code": ["AAPL"], "industry": ["Tech"],
                            "market_id": ["105"]})
        us = _tx_parts(73, **{"1": "苹果", "2": "AAPL.OQ",
                              "46": "Apple Inc."})
        monkeypatch.setattr(q, "TX", _tx_market_tx([("usAAPL", us)]))
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes_tx("US", universe=uni)
        assert df.iloc[0]["code"] == "AAPL"   # not the '.OQ' payload form

    def test_skips_none_and_short_rows(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "TX", _tx_session(
            b'v_sh600519="none";\nv_sz000001="1~short";\n'))
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        assert q.fetch_market_quotes_tx("A", universe=self._universe()).empty

    def test_empty_universe_returns_empty(self):
        from value_genie.fetch import quotes as q

        assert q.fetch_market_quotes_tx("A", universe=pd.DataFrame()).empty

    def test_em_outage_triggers_tx_fallback(self, monkeypatch):
        from value_genie.fetch import quotes as q

        monkeypatch.setattr(q, "em_push2_get", lambda *a, **k: None)
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        tx_df = pd.DataFrame({"market": ["A"], "code": ["600519"],
                              "price": [1.0]})
        monkeypatch.setattr(q, "fetch_market_quotes_tx", lambda m: tx_df)
        df = q.fetch_market_quotes("A")
        assert len(df) == 1 and df.iloc[0]["code"] == "600519"

    def test_partial_em_prefers_complete_tx(self, monkeypatch):
        """A complete Tencent-degraded universe beats a partial EM one."""
        from value_genie.fetch import quotes as q

        def fake_get(path, params=None, **kw):
            if params["pn"] == 1:
                return {"data": {"total": 3, "diff": [_row("600001"),
                                                      _row("600002")]}}
            return None

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        tx_df = pd.DataFrame({"market": ["A"] * 3,
                              "code": ["600001", "600002", "600003"],
                              "price": [1.0] * 3})
        monkeypatch.setattr(q, "fetch_market_quotes_tx", lambda m: tx_df)
        df = q.fetch_market_quotes("A")
        assert len(df) == 3
        assert df.attrs.get("partial") in (None, False)

    def test_tx_failure_keeps_partial_em(self, monkeypatch):
        """When Tencent also fails the partial EM frame survives, flagged."""
        from value_genie.fetch import quotes as q

        def fake_get(path, params=None, **kw):
            if params["pn"] == 1:
                return {"data": {"total": 3, "diff": [_row("600001"),
                                                      _row("600002")]}}
            return None

        monkeypatch.setattr(q, "em_push2_get", fake_get)
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        monkeypatch.setattr(q, "fetch_market_quotes_tx",
                            lambda m: pd.DataFrame())
        df = q.fetch_market_quotes("A")
        assert len(df) == 2
        assert df.attrs.get("partial") is True
