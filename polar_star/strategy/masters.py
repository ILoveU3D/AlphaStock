"""Investment master strategies: weight profiles + hard gates + skill files.

Each master = an independent ``Strategy`` registered into the global
registry.  Adding a new master is one ``register_strategy`` call;
no existing code needs to change.

Masters are ordered by fame (``order`` 1..N) so `strategy list` and
the skills directory (07..12) share one canonical ranking.

Built-in masters (calibrated to their *lifetime* style, not caricatures):
- buffett   (Warren Buffett): evolved from cigar-butts to franchises;
             owner earnings and cheap float are the engine
- munger    (Charlie Munger): invert, latticework, sit-on-your-ass
             investing; pay up for wonderful, never cheap-mediocre
- graham    (Benjamin Graham): margin of safety as arithmetic; the
             22.5 rule (PE x PB <= 22.5) plus balance-sheet sanity
- livermore (Jesse Livermore): pivotal points, sit with winners,
             mechanical 10% stops; pure price action, no fundamentals
- duan      (Duan Yongping): business model first, no stop-losses
             (position sizing happens before entry), hold 10 years
- sheng     (Justin Sun): attention is the scarcest asset; narrative
             is the leading indicator of flow; exit at attention climax
- sanhuyi   (散户乙, folk master added 2026-09-10): earn shares, not
            profit — accumulate fully-paid-for claims on future cash
            flows via dividend compounding and cost recovery
"""

from .registry import Strategy, register_strategy


def _register_masters():
    """Register the six built-in investment masters (fame order)."""

    # --- Buffett: franchises + owner earnings + cheap float (order 1) ---
    register_strategy(Strategy(
        id="buffett",
        name="Warren Buffett (franchise + owner earnings)",
        weights={
            "value": 0.25, "growth": 0.05, "quality": 0.40,
            "safety": 0.10, "momentum": 0, "cashflow": 0.20,
        },
        gates=[
            ("roe", ">=", 15.0),
            ("gross_margin", ">=", 40.0),
            ("debt_ratio", "<=", 60.0),
            ("ocf_yield", ">=", 5.0),
            ("fcf_yield", ">=", 4.0),
            ("borrowed_dividend", "<=", 0.0),
        ],
        kind="master",
        skill_file="07-master-buffett.md",
        triggers=["巴菲特", "buffett", "现金流", "能力圈", "安全边际"],
        order=1,
        horizon="long",        # buffett: "he can afford to wait years"
    ))

    # --- Munger: invert + latticework + wonderful at fair price (order 2) ---
    register_strategy(Strategy(
        id="munger",
        name="Charlie Munger (invert + latticework + wonderful business)",
        weights={
            "value": 0.15, "growth": 0.15, "quality": 0.50,
            "safety": 0.05, "momentum": 0, "cashflow": 0.15,
        },
        gates=[
            ("roe", ">=", 20.0),
            ("gross_margin", ">=", 40.0),
            ("debt_ratio", "<=", 50.0),
            ("borrowed_dividend", "<=", 0.0),
        ],
        kind="master",
        skill_file="08-master-munger.md",
        triggers=["芒格", "munger", "反过来想", "格栅思维", "坐等投资法"],
        order=2,
        horizon="long",        # munger: sit-on-your-ass investing
    ))

    # --- Graham: margin of safety as arithmetic (order 3) ---
    register_strategy(Strategy(
        id="graham",
        name="Benjamin Graham (statistical deep value + Mr. Market)",
        weights={
            "value": 0.50, "growth": 0.05, "quality": 0.15,
            "safety": 0.20, "momentum": 0, "cashflow": 0.10,
        },
        gates=[
            ("pe_pb", "<=", 22.5),
            ("debt_ratio", "<=", 50.0),
            ("roe", ">=", 10.0),
            ("borrowed_dividend", "<=", 0.0),
        ],
        kind="master",
        skill_file="09-master-graham.md",
        triggers=["格雷厄姆", "graham", "市场先生", "烟蒂股", "净流动资产"],
        order=3,
        horizon="mid",         # graham: statistical repair window ~1-2y
    ))

    # --- Livermore: pivotal points + discipline, pure price (order 4) ---
    register_strategy(Strategy(
        id="livermore",
        name="Jesse Livermore (pivotal points + risk discipline)",
        weights={
            "value": 0, "growth": 0.15, "quality": 0.10,
            "safety": 0.05, "momentum": 0.70, "cashflow": 0,
        },
        gates=[
            ("ret_60d", ">=", 0.0),
            ("volatility", "pctl>=", 50),
            ("pos_52w", ">=", 60.0),
        ],
        kind="master",
        skill_file="10-master-livermore.md",
        triggers=["利弗莫尔", "livermore", "趋势", "止损", "关键价位"],
        order=4,
        horizon="short",       # livermore: pivotal points, 10% stops
    ))

    # --- Duan: business model first, hold 10 years, no stops (order 5) ---
    register_strategy(Strategy(
        id="duan",
        name="Duan Yongping (business model first + calm mind)",
        weights={
            "value": 0.20, "growth": 0.10, "quality": 0.45,
            "safety": 0.10, "momentum": 0, "cashflow": 0.15,
        },
        gates=[
            ("roe", ">=", 20.0),
            ("gross_margin", ">=", 40.0),
            ("volatility", "pctl<=", 60),
            ("borrowed_dividend", "<=", 0.0),
        ],
        kind="master",
        skill_file="11-master-duan.md",
        triggers=["段永平", "duan", "平常心", "本分", "不懂不做"],
        order=5,
        horizon="long",        # duan: "这门生意十年后会是什么样"
    ))

    # --- Sun: attention economics + high-beta momentum (order 6) ---
    register_strategy(Strategy(
        id="sheng",
        name="Justin Sun (attention economics + narrative momentum)",
        weights={
            "value": 0, "growth": 0.35, "quality": 0.10,
            "safety": 0, "momentum": 0.55, "cashflow": 0,
        },
        gates=[
            ("ret_60d", ">=", 0.0),
            ("volatility", "pctl>=", 60),
        ],
        kind="master",
        skill_file="12-master-sheng.md",
        triggers=["孙宇晨", "sheng", "热点", "风口", "注意力经济"],
        order=6,
        horizon="ultrashort",  # sheng: "快进快出……never a hold"
    ))

    # --- 散户乙: free shares via dividends + cost recovery (order 7) ---
    # User-introduced folk master (2026-09-10).  The engine is real
    # cash return: dividends funded by operations, never borrowed
    # (借钱分红 = fake free shares — principal disguised as cash flow).
    # dividend_yield gate (>= 2.5) went live 2026-09-10: the pipeline
    # now derives it for ALL markets from annual div_paid / market cap
    # (A: 东财分红事件表, HK: F10, US: SEC frames) — the former HK-only
    # data gap is closed.  No-dividend compounders are excluded by
    # design: without a payout there is no dividend-recovery path.
    register_strategy(Strategy(
        id="sanhuyi",
        name="散户乙 (free shares: dividend compounding + cost recovery)",
        weights={
            "value": 0.20, "growth": 0.10, "quality": 0.30,
            "safety": 0.05, "momentum": 0, "cashflow": 0.35,
        },
        gates=[
            ("roe", ">=", 15.0),
            ("debt_ratio", "<=", 60.0),
            ("ocf_yield", ">=", 4.0),
            ("dividend_yield", ">=", 2.5),
            ("borrowed_dividend", "<=", 0.0),
        ],
        kind="master",
        skill_file="17-master-sanhuyi.md",
        triggers=["散户乙", "免费股票", "成本收回", "赚股票", "股息复利"],
        order=7,
        horizon="long",       # sanhuyi: free shares compound over decades
    ))


_register_masters()
