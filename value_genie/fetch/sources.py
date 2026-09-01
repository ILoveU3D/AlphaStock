"""Data source registry: lightweight metadata layer over existing fetchers.

Registers Eastmoney (primary), Tencent (kline backup) and SEC EDGAR
(US financials) so the pipeline can discover sources declaratively.

Adding a new source = one ``register_source`` call; existing fetcher
functions do not change.
"""

from ..strategy.registry import DataSource, register_source, set_source_order


def _register_sources():
    """Register the three built-in data sources and their order."""

    # --- Eastmoney: quotes + A financials + HK F10 + klines ---
    register_source(DataSource(
        id="eastmoney",
        name="Eastmoney (东方财富)",
        capabilities=[
            "quotes:A", "quotes:HK", "quotes:US",
            "financials:A", "financials:HK",
            "kline:A", "kline:HK", "kline:US",
        ],
        fetchers={
            "quotes": "fetch_market_quotes",
            "financials": "fetch_a_financials / fetch_hk_f10",
            "kline": "fetch_kline_any (em primary)",
        },
    ))

    # --- SEC EDGAR: US financials ---
    register_source(DataSource(
        id="sec_edgar",
        name="SEC EDGAR (XBRL frames)",
        capabilities=["financials:US"],
        fetchers={"financials": "fetch_us_financials"},
    ))

    # --- Tencent: kline backup ---
    register_source(DataSource(
        id="tencent",
        name="Tencent (腾讯行情)",
        capabilities=["kline:A", "kline:HK", "kline:US"],
        fetchers={"kline": "fetch_kline_any (tx fallback)"},
    ))

    # Set lookup order: primary first, backup second
    set_source_order("quotes", "A", ["eastmoney"])
    set_source_order("quotes", "HK", ["eastmoney"])
    set_source_order("quotes", "US", ["eastmoney"])
    set_source_order("financials", "A", ["eastmoney"])
    set_source_order("financials", "HK", ["eastmoney"])
    set_source_order("financials", "US", ["sec_edgar"])
    set_source_order("kline", "A", ["eastmoney", "tencent"])
    set_source_order("kline", "HK", ["eastmoney", "tencent"])
    set_source_order("kline", "US", ["eastmoney", "tencent"])


_register_sources()
