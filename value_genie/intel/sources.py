"""Intel data source registration (design §4).

P1: eastmoney gains events:A + announce:A (A-share batch event tables
for the radar channel). P2: notice/news/ratings:A per-stock channels.
P3: eastmoney mirror covers HK notices/news + US news; sec_edgar adds
notice:US (submissions timeline); stockanalysis provides ratings:US.
HK research ratings have no source (probe-verified) — the report layer
degrades explicitly.
"""

from ..strategy.registry import (DataSource, list_sources,
                                 register_source, set_source_order)


def _register_intel_sources():
    """Extend existing entries in place + register new sources.

    Mutating the registered DataSource in place (register_source would
    need the whole entry duplicated); register_source replaces on
    duplicate id, so re-registration is idempotent either way.
    """
    for ds in list_sources():
        if ds.id == "eastmoney":
            for cap in ("events:A", "announce:A", "notice:A",
                        "notice:HK", "news:A", "news:HK", "news:US",
                        "ratings:A"):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
        elif ds.id == "sec_edgar":
            for cap in ("notice:US",):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
    register_source(DataSource(
        id="stockanalysis", name="StockAnalysis",
        capabilities=["ratings:US"]))
    set_source_order("events", "A", ["eastmoney"])
    set_source_order("announce", "A", ["eastmoney"])
    set_source_order("notice", "A", ["eastmoney"])
    set_source_order("notice", "HK", ["eastmoney"])
    set_source_order("notice", "US", ["sec_edgar"])
    set_source_order("news", "A", ["eastmoney"])
    set_source_order("news", "HK", ["eastmoney"])
    set_source_order("news", "US", ["eastmoney"])
    set_source_order("ratings", "A", ["eastmoney"])
    set_source_order("ratings", "US", ["stockanalysis"])


_register_intel_sources()
