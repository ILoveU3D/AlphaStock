"""Tests for value_genie.fetch.quotes (no network)."""

from value_genie.fetch.quotes import (_parse_clist_rows,
                                      exclude_non_operating_names,
                                      exclude_risk_names)


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
        monkeypatch.setattr(q.time, "sleep", lambda s: None)
        df = q.fetch_market_quotes("A")
        assert df.empty
        assert calls == [1] * (config.QUOTE_PAGE_RETRIES + 1)
