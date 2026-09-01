"""Investment master strategies: weight profiles + hard gates + skill files.

Each master = an independent ``Strategy`` registered into the global
registry.  Adding a new master is one ``register_strategy`` call;
no existing code needs to change.

Built-in masters:
- buffett  (Warren Buffett): cash flow, quality, margin of safety
- duan     (Duan Yongping): calm mind, quality first, low volatility
- sheng    (Justin Sun): hot-spot sensitive, momentum follower
- livermore (Jesse Livermore): trend trading, discipline, momentum
"""

from .registry import Strategy, register_strategy


def _register_masters():
    """Register the four built-in investment masters."""

    # --- Buffett: cash flow, quality, margin of safety ---
    register_strategy(Strategy(
        id="buffett",
        name="Warren Buffett (cash flow + quality + margin of safety)",
        weights={
            "value": 0.30, "growth": 0.05, "quality": 0.40,
            "safety": 0.10, "momentum": 0, "cashflow": 0.15,
        },
        gates=[
            ("roe", ">=", 15.0),
            ("gross_margin", ">=", 40.0),
            ("debt_ratio", "<=", 60.0),
            ("ocf_yield", ">=", 5.0),
        ],
        kind="master",
        skill_file="07-master-buffett.md",
        triggers=["巴菲特", "buffett", "现金流", "能力圈", "安全边际"],
    ))

    # --- Duan Yongping: calm mind, quality first ---
    register_strategy(Strategy(
        id="duan",
        name="Duan Yongping (calm mind + quality first)",
        weights={
            "value": 0.20, "growth": 0.10, "quality": 0.45,
            "safety": 0.15, "momentum": 0, "cashflow": 0.10,
        },
        gates=[
            ("roe", ">=", 20.0),
            ("volatility", "pctl<=", 50),
        ],
        kind="master",
        skill_file="08-master-duan.md",
        triggers=["段永平", "duan", "平常心", "本分", "不懂不做"],
    ))

    # --- Justin Sun: hot-spot sensitive, momentum follower ---
    register_strategy(Strategy(
        id="sheng",
        name="Justin Sun (hot-spot sensitive + momentum)",
        weights={
            "value": 0.05, "growth": 0.35, "quality": 0.10,
            "safety": 0.05, "momentum": 0.45, "cashflow": 0,
        },
        gates=[
            ("ret_60d", ">=", 0.0),
        ],
        kind="master",
        skill_file="09-master-sheng.md",
        triggers=["孙宇晨", "sheng", "热点", "风口", "注意力经济"],
    ))

    # --- Livermore: trend trading, discipline ---
    register_strategy(Strategy(
        id="livermore",
        name="Jesse Livermore (trend + discipline + momentum)",
        weights={
            "value": 0, "growth": 0.15, "quality": 0.10,
            "safety": 0, "momentum": 0.60, "cashflow": 0.15,
        },
        gates=[
            ("ret_60d", ">=", 0.0),
            ("volatility", "pctl>=", 50),
        ],
        kind="master",
        skill_file="10-master-livermore.md",
        triggers=["利弗莫尔", "livermore", "趋势", "止损", "关键价位"],
    ))


_register_masters()
