"""Strategy layer: factor computation, pillar scoring, presets, masters.

Importing the subpackage auto-registers all built-in presets and masters
into the global registry.
"""

# Import order matters: registry first, then registrants.
from . import registry  # noqa: F401
from . import presets    # noqa: F401 — registers 4 presets
from . import masters    # noqa: F401 — registers 4 masters
