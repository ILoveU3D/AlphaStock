"""Intel subsystem: event radar + per-stock intelligence.

Importing the subpackage auto-registers intel data source capabilities
(extending the base sources registered by ``value_genie.fetch``).
"""

from .. import fetch  # noqa: F401 — base sources must register first
from . import sources  # noqa: F401 — extends them (events/announce)
