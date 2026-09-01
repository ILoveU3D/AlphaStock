"""Time-horizon dimension: holding-period lenses over the six pillars.

Four horizons (windows are trading time, weights are registry data —
tunable without code changes):

- ultrashort 超短线 (1-10 交易日): attention-driven, short-window
  momentum is the asset, growth numbers are narrative fuel (Sun-style)
- short     短线   (10日-3月): trend confirmation + repair starting
  (Livermore-style "the market proves the trend first")
- mid       中线   (3月-3年): valuation repair + earnings delivery
  (Graham-style statistical window)
- long      长线   (3年+): business model + owner earnings
  (Buffett/Duan-style "这门生意十年后会是什么样")

Each horizon also fixes the momentum measurement window; combined with
a strategy (`--strategy X --horizon Y`) the master's weights and gates
stay, only the momentum window swaps.
"""

from .registry import Horizon, register_horizon


def _register_horizons():
    """Register the four built-in horizons (ultrashort -> long)."""

    register_horizon(Horizon(
        id="ultrashort", name="超短线", window="1-10 交易日",
        weights={"value": 0, "growth": 0.25, "quality": 0.05,
                 "safety": 0, "momentum": 0.70, "cashflow": 0},
        momentum_cols=("ret_5d", "ret_20d"),
        gates=[("volatility", "pctl>=", 50), ("ret_5d", ">=", 0.0)],
        order=1,
    ))

    register_horizon(Horizon(
        id="short", name="短线", window="10日-3月",
        weights={"value": 0.20, "growth": 0.20, "quality": 0.10,
                 "safety": 0.15, "momentum": 0.35, "cashflow": 0},
        momentum_cols=("ret_20d", "ret_60d"),
        gates=[("ret_20d", ">=", 0.0)],
        order=2,
    ))

    register_horizon(Horizon(
        id="mid", name="中线", window="3月-3年",
        weights={"value": 0.30, "growth": 0.30, "quality": 0.20,
                 "safety": 0.10, "momentum": 0.10, "cashflow": 0},
        momentum_cols=("ret_60d", "ret_250d"),
        gates=[],
        order=3,
    ))

    register_horizon(Horizon(
        id="long", name="长线", window="3年+",
        weights={"value": 0.15, "growth": 0.20, "quality": 0.35,
                 "safety": 0.10, "momentum": 0, "cashflow": 0.20},
        momentum_cols=("ret_60d", "ret_250d"),
        gates=[],
        order=4,
    ))


_register_horizons()
