"""Data fetching layer: HTTP client, quotes, financials, klines, pipeline.

Importing the subpackage auto-registers all built-in data sources into
the global registry.
"""

from . import http    # noqa: F401
from . import sources  # noqa: F401 — registers eastmoney/tencent/sec_edgar
