"""Tests for value_genie.intel source registration + datacenter
fetchers (all network mocked)."""

from value_genie.strategy.registry import get_sources, list_sources


def test_import_intel_alone_extends_eastmoney():
    """Importing intel must be order-safe: intel/__init__ imports fetch
    first so the eastmoney entry exists before capabilities extend."""
    import value_genie.intel  # noqa: F401 — deliberately no fetch import
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert "events:A" in ds.capabilities
    assert "announce:A" in ds.capabilities
    assert [s.id for s in get_sources("events", "A")] == ["eastmoney"]
    assert [s.id for s in get_sources("announce", "A")] == ["eastmoney"]


def test_registration_is_idempotent():
    import value_genie.intel  # noqa: F401
    import value_genie.intel.sources as src
    src._register_intel_sources()   # second call must not duplicate caps
    ds = {s.id: s for s in list_sources()}["eastmoney"]
    assert ds.capabilities.count("events:A") == 1
