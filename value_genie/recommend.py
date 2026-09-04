"""Daily recommendation: user-style screening + holdings health.

``recommend`` is a freshness-gated, price-sensitive command. It
(1) screens the latest snapshot under the user's style (falling back
to ``--strategy`` or the balanced preset when the user has no style),
excluding stocks already held, and (2) reports portfolio health: live
P&L, position weights, industry concentration and hard risk
observations.

This module supplies facts; the calling AI writes the prose. Weights
are computed in CNY using the snapshot manifest FX rate; US positions
without a USD rate are excluded from the total and the gap is stated
explicitly.
"""

import json
import pandas as pd
from pathlib import Path

from . import config, report, users
from .analyze import live_quote
from .resolve import Match

SINGLE_WEIGHT_WARN = 30.0    # % of portfolio value in one stock
INDUSTRY_WEIGHT_WARN = 40.0  # % of portfolio value in one industry

CANDIDATE_COLUMNS = [
    "rank", "market", "code", "name", "industry", "price", "pe_ttm",
    "pb", "roe", "rev_yoy", "profit_yoy", "composite_score",
]


# ---------------------------------------------------------------------------
# Price lookup (the only network boundary; monkeypatched in tests)
# ---------------------------------------------------------------------------
def _us_market_ids(snap_dir) -> dict:
    """{ticker: market_id} from the snapshot's US quotes (push2 needs
    the exchange prefix, e.g. 105.AAPL)."""
    if snap_dir is None:
        return {}
    p = Path(snap_dir) / "us_quotes.csv"
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p, dtype={"code": str})
    except Exception:
        return {}
    if "market_id" not in df.columns:
        return {}
    return dict(zip(df["code"].astype(str),
                    df["market_id"].astype(str)))


def _quotes_industries(snap_dir) -> dict:
    """{(market, code): industry} from the snapshot quotes CSVs —
    full-market coverage, wider than the master candidate pool."""
    out = {}
    if snap_dir is None:
        return out
    for market in ("A", "HK", "US"):
        p = Path(snap_dir) / f"{market.lower()}_quotes.csv"
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except Exception:
            continue
        if "industry" not in df.columns:
            continue
        for code, ind in zip(df["code"].astype(str),
                             df["industry"]):
            if pd.notna(ind) and str(ind).strip():
                out[(market, str(code))] = str(ind)
    return out


def _snapshot_price(snap_dir, market: str, code: str):
    if snap_dir is None:
        return None
    p = Path(snap_dir) / f"{market.lower()}_quotes.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, dtype={"code": str})
        hit = df[df["code"] == code]
        if hit.empty:
            return None
        return float(hit.iloc[0]["price"])
    except Exception:
        return None


def live_price(market: str, code: str, name: str, snap_dir=None,
               us_market_ids=None):
    """(price, source) — live via push2, snapshot fallback, else None."""
    mid = ""
    if market == "A":
        # 6xxxxx stocks + 5xxxxx funds (ETF) are Shanghai; rest SZ/BJ
        mid = "1" if str(code)[:1] in ("5", "6") else "0"
    elif market == "HK":
        mid = "116"
    elif market == "US":
        mid = (us_market_ids or {}).get(code, "")
    if mid:
        q = live_quote(Match(market, code, name, 100.0, mid))
        if q and q.get("price") is not None:
            try:
                return float(q["price"]), "live"
            except (TypeError, ValueError):
                pass
    price = _snapshot_price(snap_dir, market, code)
    if price is not None:
        return price, "snapshot"
    return None, ""


# ---------------------------------------------------------------------------
# Holdings health
# ---------------------------------------------------------------------------
def _fetch_fx_usdcny_live():
    """USD/CNY live rate; None on failure (module-level for tests)."""
    try:
        from .fetch.fundamentals import fetch_fx_usdcny
        return fetch_fx_usdcny()
    except Exception:
        return None


def _fx_rates(snap_dir, need_usd=False) -> dict:
    """{currency: CNY rate} from the snapshot manifest; USD falls back
    to a live fetch only when USD holdings exist (old snapshots have
    no fx_usdcny key)."""
    rates = {"CNY": 1.0}
    if snap_dir is None:
        return rates
    p = Path(snap_dir) / "manifest.json"
    if p.exists():
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            m = {}
        if m.get("fx_hkdcny"):
            rates["HKD"] = float(m["fx_hkdcny"])
        if m.get("fx_usdcny"):
            rates["USD"] = float(m["fx_usdcny"])
    if "USD" not in rates and need_usd:
        live = _fetch_fx_usdcny_live()
        if live:
            rates["USD"] = float(live)
    return rates


def _row_value(mrow, col):
    """Column value from a master row, None when absent/NaN."""
    if mrow is None or col not in mrow.index or pd.isna(mrow[col]):
        return None
    try:
        return float(mrow[col])
    except (TypeError, ValueError):
        return None


def _composite_for(mrow, weights):
    """Composite score under the given weights (raw master stores only
    pillar scores; composite is computed at screen time). None when too
    few pillar scores are available."""
    if mrow is None:
        return None
    num = den = 0.0
    for pillar, w in (weights or {}).items():
        if w <= 0:
            continue
        s = _row_value(mrow, f"{pillar}_score")
        if s is None:
            continue
        num += s * w
        den += w
    if den <= 0:
        return None
    return num / den


def holdings_health(user, snap_dir=None) -> dict:
    """Portfolio snapshot: per-holding P&L + weights + observations."""
    master = None
    if snap_dir is not None:
        try:
            master = report.load_master(snap_dir)
        except (FileNotFoundError, OSError):
            master = None
    style_weights = (user.style or {}).get("weights") or {}
    if not style_weights:  # styleless users still get a composite
        from .strategy.registry import get_strategy
        try:
            style_weights = get_strategy(config.DEFAULT_PRESET).weights
        except ValueError:
            style_weights = {}
    us_ids = _us_market_ids(snap_dir)
    quotes_ind = _quotes_industries(snap_dir)
    need_usd = any(h.currency == "USD" for h in user.holdings)
    fx = _fx_rates(snap_dir, need_usd=need_usd)

    rows = []
    for h in user.holdings:
        mrow = None
        if master is not None:
            hit = master[(master["market"] == h.market)
                         & (master["code"] == h.code)]
            mrow = hit.iloc[0] if not hit.empty else None
        price, src = live_price(h.market, h.code, h.name, snap_dir, us_ids)
        value = None
        pnl = None
        pnl_pct = None
        if price is not None:
            value = h.qty * price
            pnl = (price - h.cost) * h.qty
            pnl_pct = (price / h.cost - 1.0) * 100.0
        industry = None
        if mrow is not None and "industry" in mrow.index \
                and pd.notna(mrow["industry"]):
            industry = str(mrow["industry"])
        if industry is None:  # wider quotes coverage (not in master pool)
            industry = quotes_ind.get((h.market, h.code))
        rows.append({
            "market": h.market, "code": h.code, "name": h.name,
            "qty": h.qty, "cost": h.cost, "price": price,
            "price_src": src, "currency": h.currency,
            "value": value, "pnl": pnl, "pnl_pct": pnl_pct,
            "value_cny": value * fx.get(h.currency, 0) if value is not None
            and h.currency in fx else None,
            "industry": industry,
            "composite_score": _composite_for(mrow, style_weights),
            "pe_ttm": _row_value(mrow, "pe_ttm"),
            "ret_60d": _row_value(mrow, "ret_60d"),
            "drawdown_52w": _row_value(mrow, "drawdown_52w"),
        })

    # totals in CNY; markets without an FX rate are excluded (stated)
    values_cny = [r["value_cny"] for r in rows if r["value_cny"]]
    total = sum(values_cny) if values_cny else None
    for r in rows:
        r["weight"] = (
            r["value_cny"] / total * 100.0
            if total and r["value_cny"] else None)

    industries = {}
    for r in rows:
        if r["value_cny"]:
            key = r["industry"] or "未知行业"
            industries[key] = industries.get(key, 0.0) + r["value_cny"]
    market_dist = {}
    for r in rows:
        if r["value_cny"]:
            market_dist[r["market"]] = (market_dist.get(r["market"], 0.0)
                                        + r["value_cny"])

    flags = []
    if total:
        for r in rows:
            if r["weight"] and r["weight"] > SINGLE_WEIGHT_WARN:
                flags.append(
                    f"单一持仓仓位 {r['weight']:.1f}% "
                    f"(>{SINGLE_WEIGHT_WARN:.0f}%): {r['name']}")
        for ind, val in industries.items():
            w = val / total * 100.0
            if w > INDUSTRY_WEIGHT_WARN:
                flags.append(
                    f"行业集中 {w:.1f}% (>{INDUSTRY_WEIGHT_WARN:.0f}%): {ind}")
    # per-holding hard observations, verbatim
    for r in rows:
        if r["price"] is None:
            flags.append(f"现价缺失: {r['name']} ({r['market']}/{r['code']})")
        if r["composite_score"] is None:
            flags.append(
                f"不在快照候选池: {r['name']} "
                f"({r['market']}/{r['code']})")
        if r["drawdown_52w"] is not None and r["drawdown_52w"] < -40:
            flags.append(
                f"深度回撤: {r['name']} "
                f"{r['drawdown_52w']:.0f}% 自52周高点")
        if r["ret_60d"] is not None and r["ret_60d"] < 0:
            flags.append(
                f"近3月动量为负: {r['name']} {r['ret_60d']:.1f}%")
    no_fx = sorted({r["currency"] for r in rows
                    if r["value"] is not None
                    and r["currency"] not in fx})
    if no_fx:
        flags.append(
            f"组合权重未计入 {','.join(no_fx)} 持仓（快照缺该币种汇率）")

    return {"rows": rows, "total_cny": total, "fx": fx,
            "industries": industries, "market_dist": market_dist,
            "flags": flags}


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------
def build_recommendation(user_id: str, snap_dir=None, data_dir=None,
                         snapshot=None, strategy=None, horizon=None,
                         top_n=None, markets=None) -> dict:
    """Screen under the user's style (minus holdings) + health report."""
    user = users.load_user(user_id)  # FileNotFoundError with hint
    users.register_user_strategies()  # idempotent; ensures style usable

    if snap_dir is None:
        snap_dir = report.resolve_snapshot(data_dir, snapshot)
    snap_dir = Path(snap_dir)
    top_n = top_n or 10

    sid = strategy or (user.id if user.has_style()
                       else config.DEFAULT_PRESET)
    hz = horizon or (user.style.get("horizon") or None)

    master = report.load_master(snap_dir)
    held = {h.key() for h in user.holdings}
    pool = report.screen(
        master, strategy=sid, horizon=hz, snap_dir=snap_dir,
        top_n=top_n + len(held), markets=markets)
    if held and not pool.empty:
        keep = ~pool.apply(
            lambda r: (r["market"], str(r["code"])) in held, axis=1)
        pool = pool[keep]
    candidates = pool.head(top_n).reset_index(drop=True)
    candidates["rank"] = range(1, len(candidates) + 1)

    health = holdings_health(user, snap_dir)
    return {"user": user, "snapshot": snap_dir.name, "strategy": sid,
            "horizon": hz, "candidates": candidates, "health": health}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _fmt(v, dash="-"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def render_holdings(health: dict) -> str:
    """持仓体检 table + 组合观察 block."""
    rows = health["rows"]
    lines = []
    if not rows:
        return "-- 持仓体检 --\n(空仓)"
    lines.append("-- 持仓体检 --")
    header = (f"{'股票':<14} {'市场':<5} {'代码':<9} {'数量':>8} "
              f"{'成本':>9} {'现价':>9} {'盈亏%':>9} {'仓位%':>7} {'综合分':>7}")
    lines.append(header)
    lines.append("-" * 78)
    for r in rows:
        lines.append(
            f"{r['name'][:12]:<14} {r['market']:<5} {r['code']:<9} "
            f"{r['qty']:>8,.0f} {r['cost']:>9,.2f} "
            f"{_fmt(r['price']):>9} {_fmt(r['pnl_pct']):>9} "
            f"{_fmt(r['weight']):>7} {_fmt(r['composite_score']):>7}")
        if r["price_src"] == "snapshot":
            lines.append(f"    (现价为快照价，实时报价不可用: {r['code']})")
    total = health["total_cny"]
    lines.append(
        f"组合总市值 (CNY): {total:,.0f}" if total
        else "组合总市值 (CNY): - (缺价格或汇率)")
    lines.append("")
    lines.append("-- 组合观察 --")
    ind = health["industries"]
    if ind and total:
        parts = [f"{k} {v / total * 100.0:.0f}%"
                 for k, v in sorted(ind.items(), key=lambda kv: -kv[1])]
        lines.append("行业分布: " + " / ".join(parts))
    md = health["market_dist"]
    if md and total:
        parts = [f"{k} {v / total * 100.0:.0f}%"
                 for k, v in sorted(md.items(), key=lambda kv: -kv[1])]
        lines.append("市场分布: " + " / ".join(parts))
    flags = health["flags"]
    if flags:
        for f in flags:
            lines.append(f"- [观察] {f}")
    else:
        lines.append("- 无集中度/数据观察")
    return "\n".join(lines)


def render_recommend(result: dict) -> str:
    """Full console report: header + holdings + candidates."""
    user = result["user"]
    health = result["health"]
    cands = result["candidates"]
    lines = [f"== Value Genie recommend — 用户 {user.id} ({user.name}) =="]
    lines.append(f"snapshot : {result['snapshot']}")
    style_bits = []
    if user.has_style():
        w = user.style.get("weights") or {}
        style_bits.append(" / ".join(f"{p}={w[p]:.2f}"
                                     for p in w if w.get(p, 0) > 0))
        gates = user.style.get("gates") or []
        if gates:
            style_bits.append("gates: " + ", ".join(
                f"{c} {o} {v:g}" for c, o, v in gates))
        if user.style.get("horizon"):
            style_bits.append(f"horizon: {user.style['horizon']}")
    else:
        style_bits.append("(未设置风格，使用默认 balanced)")
    lines.append(f"风格     : {result['strategy']} — " + " | ".join(style_bits))
    if result["horizon"]:
        lines.append(f"周期     : {result['horizon']}")
    live_any = any(r.get("price_src") == "live" for r in health["rows"])
    lines.append(f"quote    : {'live' if live_any else 'snapshot/无'}")
    lines.append("")
    lines.append(render_holdings(health))
    lines.append("")
    lines.append(f"-- 推荐候选 (按 {result['strategy']} 筛选, 已排除持仓) --")
    if cands is None or cands.empty:
        lines.append("(无候选通过风格筛选; 尝试调整风格或门槛)")
    else:
        cols = [c for c in CANDIDATE_COLUMNS if c in cands.columns]
        lines.append(cands[cols].to_string(
            index=False, float_format=lambda v: f"{v:.1f}"))
    lines.append("")
    lines.append("注: 以上为结构化事实; 买卖判断需结合 AI 的政策/情绪/地缘评估。")
    return "\n".join(lines)


def health_to_json(health: dict) -> str:
    """`holding list --json` payload (rows/totals/flags, full precision)."""
    return json.dumps(health, ensure_ascii=False, indent=2)


def to_json(result: dict) -> str:
    """`recommend --json` payload: header + candidates + holdings health."""
    user = result["user"]
    payload = {
        "user": user.id, "user_name": user.name,
        "snapshot": result["snapshot"], "strategy": result["strategy"],
        "horizon": result["horizon"],
        "candidates": report.df_records(result["candidates"]),
        "health": result["health"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
