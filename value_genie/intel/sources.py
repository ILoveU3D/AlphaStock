"""Intel data source registration (design §4).

P1: eastmoney gains events:A + announce:A (A-share batch event tables
for the radar channel). P3 will register cninfo / hkexnews / yahoo /
stockanalysis as new entries for HK/US coverage.
"""

from ..strategy.registry import list_sources, set_source_order


def _register_intel_sources():
    """Extend the existing eastmoney entry with intel capabilities.

    Mutates the registered DataSource in place (register_source would
    need the whole entry duplicated); idempotent by construction.
    """
    for ds in list_sources():
        if ds.id == "eastmoney":
            for cap in ("events:A", "announce:A"):
                if cap not in ds.capabilities:
                    ds.capabilities.append(cap)
    set_source_order("events", "A", ["eastmoney"])
    set_source_order("announce", "A", ["eastmoney"])


_register_intel_sources()
