"""Strategy presets: named weight profiles over the six pillars.

Presets are registered into the strategy registry on import. The legacy
``get_preset`` and ``PRESETS`` dict remain for backward compatibility;
new code should use ``registry.get_strategy`` instead.
"""

from .registry import Strategy, register_strategy


def _register_presets():
    """Register the four built-in preset strategies."""
    register_strategy(Strategy(
        id="balanced",
        name="Balanced (value + growth + quality)",
        weights={"value": 0.35, "growth": 0.25, "quality": 0.30,
                 "safety": 0.10, "momentum": 0, "cashflow": 0},
        kind="preset",
    ))
    register_strategy(Strategy(
        id="magic_formula",
        name="Magic Formula (cheap + good)",
        weights={"value": 0.50, "growth": 0, "quality": 0.50,
                 "safety": 0, "momentum": 0, "cashflow": 0},
        kind="preset",
    ))
    register_strategy(Strategy(
        id="garp",
        name="GARP (growth at a reasonable price)",
        weights={"value": 0.25, "growth": 0.45, "quality": 0.30,
                 "safety": 0, "momentum": 0, "cashflow": 0},
        kind="preset",
    ))
    register_strategy(Strategy(
        id="deep_value",
        name="Deep Value (cheap + safe)",
        weights={"value": 0.55, "growth": 0, "quality": 0.25,
                 "safety": 0.20, "momentum": 0, "cashflow": 0},
        kind="preset",
    ))


_register_presets()

# Backward-compatible dict view (read-only snapshot)
PRESETS = {
    "balanced": {"value": 0.35, "growth": 0.25, "quality": 0.30,
                 "safety": 0.10},
    "magic_formula": {"value": 0.50, "growth": 0, "quality": 0.50,
                      "safety": 0},
    "garp": {"value": 0.25, "growth": 0.45, "quality": 0.30,
             "safety": 0},
    "deep_value": {"value": 0.55, "growth": 0, "quality": 0.25,
                   "safety": 0.20},
}

PRESET_LABELS = {
    "balanced": "Balanced (value + growth + quality)",
    "magic_formula": "Magic Formula (cheap + good)",
    "garp": "GARP (growth at a reasonable price)",
    "deep_value": "Deep Value (cheap + safe)",
}


def get_preset(name: str) -> dict:
    """Return a copy of a preset's pillar weights (4-pillar subset).

    New code should use ``registry.get_strategy(name).weights`` for
    the full 6-pillar profile.
    """
    try:
        return dict(PRESETS[name])
    except KeyError:
        known = ", ".join(sorted(PRESETS))
        raise ValueError(f"unknown preset {name!r}; available: {known}") \
            from None


def normalize_weights(weights: dict) -> dict:
    """Turn a partial/rough weight dict into a full 6-pillar profile.

    Unknown keys are dropped, missing pillars default to 0, and the result
    is scaled to sum to 1 (all-zero input falls back to uniform).
    """
    from .factors import PILLARS

    w = {p: max(0.0, float(weights.get(p, 0.0))) for p in PILLARS}
    total = sum(w.values())
    if total <= 0:
        return {p: 1.0 / len(PILLARS) for p in PILLARS}
    return {p: v / total for p, v in w.items()}
