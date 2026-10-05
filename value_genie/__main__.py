"""Command-line interface: fetch market data, screen snapshots, analyze.

Usage:
    python -m value_genie fetch [--markets A,HK,US] [--refresh]
    python -m value_genie screen [--strategy balanced|buffett|garp|...]
                                 [--set value=0.4] [--top 20]
                                 [--markets A,HK] [--snapshot DATE]
    python -m value_genie masters-vote [--top 15] [--no-live]
    python -m value_genie strategy list
    python -m value_genie source list
    python -m value_genie ask 茶百道 [--evidence] [--json]
    python -m value_genie compare 茶百道 古茗
    python -m value_genie overview [--markets A,HK] [--top 10]
    python -m value_genie recommend [--user me] [--top 10]
    python -m value_genie user create|list|show|set-style ...
    python -m value_genie holding add|update|remove|list ...
    python -m value_genie doctor
    python -m value_genie skill list|show|note|edit ...
    python -m value_genie tower list|show|add|note|link|set|search|stats|seed ...

Every data command (ask / screen / compare / overview / recommend /
holding list / doctor) accepts ``--json``: stdout becomes pure JSON
with full float precision, for AI agents that re-parse output or cite
exact numbers. Console tables remain the default for prose.

Strategies are weight profiles over six pillars (value / growth /
quality / safety / momentum / cashflow).  ``--strategy`` covers both
presets (balanced, garp, ...) and masters (buffett, duan, sheng,
livermore).  ``--preset`` is kept as a backward-compatible alias.
``screen --set value=0.5 quality=0.5`` overrides with custom weights.
`ask` resolves any name/code to a stock and prints a brief verdict
(live quote + snapshot percentiles); `--evidence` adds the full table.
Users carry a style (registered as kind="user" strategies, so
`screen --strategy me` works) plus holdings; `recommend` screens under
the user's style, excludes held stocks and prints a holdings health
report. See AGENTS.md for the AI-facing playbook.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import config, report
from .fetch.pipeline import run_fetch


def _parse_markets(text, default=None):
    if not text:
        return default
    markets = [m.strip().upper() for m in text.split(",") if m.strip()]
    for m in markets:
        if m not in config.MARKETS:
            raise SystemExit(
                f"unknown market {m!r}; choose from "
                f"{', '.join(config.MARKETS)}")
    return markets


def _parse_weights(items):
    """Turn ['value=0.4', 'growth=0.2'] into {'value': 0.4, 'growth': 0.2}."""
    weights = {}
    for item in items or []:
        pillar, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"bad weight {item!r}; expected pillar=0.4")
        try:
            weights[pillar.strip().lower()] = float(value)
        except ValueError:
            raise SystemExit(f"bad weight {item!r}; value must be a number") \
                from None
    return weights


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
def cmd_fetch(args) -> int:
    markets = _parse_markets(args.markets, default=list(config.MARKETS))
    snap_dir = run_fetch(markets=markets, data_dir=args.data_dir,
                         refresh=args.refresh)
    print(f"\nsnapshot ready: {snap_dir}")
    return 0


def cmd_screen(args) -> int:
    weights = _parse_weights(args.set)
    markets = _parse_markets(args.markets)
    try:
        snap_dir = report.resolve_snapshot(args.data_dir, args.snapshot)
        master = report.load_master(snap_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None

    from .strategy.registry import get_horizon, get_strategy

    strategy = args.strategy or args.preset
    explicit_strategy = (bool(args.strategy)
                         or args.preset != config.DEFAULT_PRESET)
    horizon_only = bool(args.horizon) and not explicit_strategy \
        and not weights

    try:
        top = report.screen(
            master,
            strategy=None if (horizon_only or weights) else strategy,
            weights=weights or None,
            horizon=args.horizon,
            snap_dir=snap_dir,
            top_n=args.top,
            markets=markets)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if top.empty:
        raise SystemExit("no stocks passed the strategy; try another one")

    if weights:
        profile = report.normalize_weights(weights)
        label = "custom"
    elif horizon_only:
        profile = report.normalize_weights(
            get_horizon(args.horizon).weights)
        label = args.horizon
    else:
        s = get_strategy(strategy)
        profile = report.normalize_weights(s.weights)
        label = (f"{strategy}-{args.horizon}" if args.horizon
                 else strategy)

    if args.json:
        # Pure-JSON stdout contract: no banner, no CSV/Markdown exports.
        meta = {"snapshot": snap_dir.name, "strategy": label,
                "weights": {p: round(v, 4) for p, v in profile.items()},
                "markets": markets or list(config.MARKETS)}
        if args.horizon:
            meta["horizon"] = args.horizon
        print(report.to_json(top, meta))
        return 0

    print(f"== Value Genie screen ==")
    print(f"snapshot : {snap_dir.name}")
    print(f"strategy : {label} ({report.describe_weights(profile)})")
    if args.horizon:
        h = get_horizon(args.horizon)
        print(f"horizon  : {h.name} ({h.window}), momentum on "
              f"{'+'.join(h.momentum_cols)}")
    print(f"markets  : {', '.join(markets or config.MARKETS)}")
    print()
    print(report.format_console(top))

    out_dir = Path(args.out_dir) if args.out_dir else config.OUTPUT_DIR
    stem = f"{snap_dir.name}_{label}"
    csv_path = report.export_csv(top, out_dir / f"{stem}.csv")
    md_path = report.export_markdown(
        top, out_dir / f"{stem}.md",
        title=f"Value Genie - {snap_dir.name} - {label}",
        meta={"snapshot": snap_dir.name, "strategy": label,
              "weights": report.describe_weights(profile),
              "markets": ", ".join(markets or config.MARKETS),
              "stocks": len(top)})
    print(f"\nwrote {csv_path}")
    print(f"wrote {md_path}")
    return 0


def cmd_masters_vote(args) -> int:
    """QMF L1/L2: quant consensus pool + cycle-trap flags (code half)."""
    if not _check_freshness(args):
        return 1
    markets = _parse_markets(args.markets)
    try:
        snap_dir = report.resolve_snapshot(args.data_dir, args.snapshot)
        master = report.load_master(snap_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None

    from .strategy import consensus as cs
    from .strategy.registry import list_strategies

    # --thesis: tower-fed pool injection (thesis buys a seat, never a
    # vote — L2 flags and the master gates apply unchanged)
    thesis_infos = []
    if args.thesis:
        from . import thesis as th
        try:
            theses = [th.load_thesis(tid) for tid in args.thesis]
        except (ValueError, FileNotFoundError) as exc:
            raise SystemExit(str(exc)) from None
        retired = [t.id for t in theses if t.status != "active"]
        if retired:
            raise SystemExit(
                f"thesis {', '.join(retired)} is retired — its "
                f"falsification fired or the window closed; see "
                f"`thesis show <id>`")
        try:
            master, thesis_infos = th.build_pool(
                snap_dir, master, theses, live=not args.no_live)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None

    masters = [s.id for s in list_strategies(kind="master")]
    # three-core backfill for old snapshots (pure function, no IO) so
    # rank_consensus can order by core_score
    from .strategy import cores as _cores
    if "core_score" not in master.columns:
        master = _cores.add_core_scores(master)
    df = cs.add_snapshot_flags(cs.masters_vote(master, markets=markets))
    # D3 hook: distilled culture scores (Phase 5 profiles) re-activate
    # the culture core for those rows only; everything else stays
    # veto-only (no proxy scoring)
    from . import profile as _prof
    df, n_distilled = _prof.apply_distilled_culture(df)
    # DCF hook (D3-parallel, 2026-10-02): built models replace the
    # reverse-DCF anchor with modeled upside for those rows only
    from .model import store as _mstore
    df, n_modeled = _mstore.apply_modeled_dcf(df)
    if thesis_infos:
        tcol = df.get("thesis")
        for ti in thesis_infos:
            mask = tcol.astype(str).str.contains(ti["id"], na=False)
            ti["voted"] = int((df.loc[mask, "vote_count"] >= 1).sum())
    # L1 pool = passed >=1 master gate AND not hard-vetoed (2026-09-29
    # redesign: gates/red flags can only EXCLUDE, never rank)
    vetoed = df[(df["vote_count"] >= 1) & (df["veto_hard"])]
    veto_sources = {
        "intel_red": int((pd.to_numeric(vetoed.get("intel_red"),
                                        errors="coerce") == 1).sum()),
        "borrowed_dividend": int((pd.to_numeric(
            vetoed.get("borrowed_dividend"),
            errors="coerce") == 1).sum()),
        "profit_spike": int(vetoed["profit_spike"].sum()),
    }
    pool = df[(df["vote_count"] >= 1) & (~df["veto_hard"])]
    if pool.empty:
        raise SystemExit("no stocks passed any master's gates")

    # D4 tactical mode (short/ultrashort): floor verifies a REAL business
    # and an intact weekly uptrend, never the price; DCF display-only.
    horizon = getattr(args, "horizon", None)
    if horizon:
        pool = _annotate_short_floor(pool)

    # v2 (2026-09-29, D1): the pool itself is the deliverable — wide and
    # veto-annotated, never truncated by a quant ranking; selection is the
    # AI's job at L3.  --top N keeps the legacy ranked shortlist with the
    # live pass; --check runs the live pass on an AI-chosen shortlist.
    if args.check:
        return _masters_live_check(args, cs, pool)

    if args.top is not None:
        top = cs.rank_consensus(pool, top_n=args.top)
    elif horizon:
        keys = [c for c in ("short_floor", "pullback_sweet", "ret_60d")
                if c in pool.columns]
        top = pool.sort_values(
            keys, ascending=[False] * len(keys),
            na_position="last").reset_index(drop=True)
    else:
        top = pool.sort_values("core_score", ascending=False,
                               na_position="last").reset_index(drop=True)

    # L2 live pass: forward-PE divergence (A-shares only — the only
    # market with a consensus-EPS source; HK/US gaps declared)
    top["pe_divergence"] = None
    top["cycle_trap"] = False
    top["cycle_warn"] = False
    top["data_gap"] = ""
    for idx, row in top.iterrows():
        if str(row.get("market")) != "A":
            top.at[idx, "data_gap"] = "no consensus-EPS source (HK/US)"
            continue
        if args.no_live:
            continue
        if args.top is None:
            # wide mode: network pass deferred to the AI shortlist
            top.at[idx, "data_gap"] = "live pass pending (--check)"
            continue
        div = cs.forward_pe_divergence(row)
        if div is None:
            top.at[idx, "data_gap"] = "consensus EPS unavailable"
            continue
        top.at[idx, "pe_divergence"] = round(div, 2)
        if div >= cs.CYCLE_TRAP_RATIO:
            top.at[idx, "cycle_trap"] = True
        elif div >= cs.CYCLE_WARN_RATIO:
            top.at[idx, "cycle_warn"] = True

    # cycle_trap is a hard veto (2026-09-29 redesign): excluded after the
    # live pass; cycle_warn stays display-only.  Wide mode defers the live
    # pass, so nothing is excluded there — declared via data_gap instead.
    cycle_trapped = top[top["cycle_trap"]]
    if not cycle_trapped.empty:
        top = top[~top["cycle_trap"]].reset_index(drop=True)

    if args.json:
        meta = {"snapshot": snap_dir.name, "masters": masters,
                "markets": markets or list(config.MARKETS),
                "pool_mode": "legacy_top" if args.top is not None
                             else "wide",
                "rows": int(len(top)),
                "ranking": "none (wide pool; selection is L3 AI judgment) "
                           if args.top is None else
                           "core_score (three-core equal weight)",
                "veto_excluded": {"count": int(len(vetoed)),
                                  **veto_sources},
                "cycle_trap_excluded": [
                    f"{r.get('market')}/{r.get('code')}"
                    for _, r in cycle_trapped.iterrows()],
                "cycle_trap_ratio": cs.CYCLE_TRAP_RATIO,
                "cycle_warn_ratio": cs.CYCLE_WARN_RATIO,
                "profit_spike_pct": cs.PROFIT_SPIKE_PCT}
        if horizon:
            meta["horizon"] = horizon
            meta["ranking"] = ("tactical (short_floor > pullback_sweet > "
                               "ret_60d) — DCF display-only, NOT "
                               "investment merit")
            meta["short_floor"] = {
                "business_min": config.SHORT_FLOOR_BUSINESS,
                "weekly_uptrend_required": True,
                "pullback_sweet_pct": list(config.PULLBACK_SWEET)}
            meta["discipline"] = _horizon_discipline(horizon)
        if n_distilled:
            meta["culture_distilled"] = n_distilled
        if n_modeled:
            meta["dcf_modeled"] = n_modeled
        if thesis_infos:
            meta["theses"] = thesis_infos
        print(report.to_json(top, meta))
        return 0

    print("== Value Genie masters-vote (QMF L1/L2) ==")
    print(f"snapshot : {snap_dir.name}")
    print(f"masters  : {', '.join(masters)}")
    print(f"markets  : {', '.join(markets or config.MARKETS)}")
    for ti in thesis_infos:
        line = (f"thesis   : {ti['id']} — {ti['name']} "
                f"({ti['members']} members: {ti['funnel']} funnel, "
                f"{ti['injected']} injected, "
                f"{ti.get('voted', 0)} passed >=1 gate")
        if ti["excluded"]:
            line += ("; excluded: " + "; ".join(
                f"{lbl} ({why})" for lbl, why in ti["excluded"]))
        print(line + ")")
    print(f"vetoed   : {len(vetoed)} excluded by hard veto "
          f"(intel_red={veto_sources['intel_red']}, "
          f"borrowed_dividend={veto_sources['borrowed_dividend']}, "
          f"profit_spike={veto_sources['profit_spike']})"
          + (f"; cycle_trap: {len(cycle_trapped)}"
             if not cycle_trapped.empty else ""))
    if n_distilled:
        print(f"culture  : {n_distilled} row(s) carry a distilled "
              f"culture score (profiles; D3 hook active)")
    if n_modeled:
        print(f"  dcf core: {n_modeled} stock(s) modeled "
              f"(models/; DCF hook active)")
    print()
    print(f"{'rank':>4} {'market':>6} {'code':>8} {'name':<14} "
          f"{'price':>8} {'votes':>5} {'core':>5} {'dcf_g':>6} "
          f"{'mean_comp':>9} {'pe_div':>6}  flags")
    for i, (_, r) in enumerate(top.iterrows(), 1):
        flags = []
        if r.get("thesis"):
            flags.append(f"thesis:{r['thesis']}")
        if horizon:
            flags.append("floor" if r.get("short_floor") else "NO-floor")
            if r.get("pullback_sweet"):
                flags.append("sweet")
        if r.get("cycle_warn"):
            flags.append("cycle_warn")
        if r.get("data_gap"):
            flags.append(f"gap:{r['data_gap']}")
        div = r.get("pe_divergence")
        div_s = f"{div:g}" if div is not None else "-"
        core = r.get("core_score")
        core_s = f"{core:.0f}" if pd.notna(core) else "-"
        dcf_g = r.get("dcf_implied_g")
        dcf_g_s = f"{dcf_g:+.1f}" if pd.notna(dcf_g) else "-"
        name = str(r.get("name") or "")[:14]
        print(f"{i:>4} {str(r.get('market')):>6} {str(r.get('code')):>8} "
              f"{name:<14} {r.get('price', float('nan')):>8g} "
              f"{int(r['vote_count']):>5} {core_s:>5} {dcf_g_s:>6} "
              f"{r['mean_composite']:>9.1f} "
              f"{div_s:>6}  {', '.join(flags)}")
        print(f"{'':>4} masters: {r['masters_passed']}")
    if args.top is None:
        print(f"\nwide pool: {len(top)} rows (veto-annotated, NOT ranked — "
              f"selection is L3 AI judgment). Live cycle-trap pass: "
              f"`masters-vote --check MARKET:CODE ...` on your shortlist.")
    if horizon:
        d = _horizon_discipline(horizon)
        print(f"\n{d['warning']}")
        print(d["rules"])
    print("\nL1 = veto filter (gates + red flags can only EXCLUDE, never "
          "rank); ranking = three-core equal weight (core_score); "
          "L3/L4 (qualitative + fused verdict) run per "
          "skills/18-fused-quant-master.md")
    return 0


def _annotate_short_floor(pool: pd.DataFrame) -> pd.DataFrame:
    """D4 tactical floor for short/ultrashort: verifies a real business
    (core_business >= config.SHORT_FLOOR_BUSINESS) plus an intact weekly
    uptrend — never the price. Fails closed when kline factors are
    missing (old snapshots): no weekly data, no floor."""
    def _col(name):
        s = pool.get(name)
        if s is None:
            return pd.Series(float("nan"), index=pool.index)
        return pd.to_numeric(s, errors="coerce")

    out = pool.copy()
    cb, wu, pb = (_col("core_business"), _col("weekly_uptrend"),
                  _col("pullback_from_high"))
    lo, hi = config.PULLBACK_SWEET
    out["short_floor"] = (cb >= config.SHORT_FLOOR_BUSINESS) & (wu == 1)
    out["pullback_sweet"] = pb.between(lo, hi)
    return out


def _horizon_discipline(horizon: str) -> dict:
    """Mandatory caution block for tactical horizons (skills/14)."""
    time_stop = ("次日收盘前 (ultrashort: 不过夜到次日收盘)"
                 if horizon == "ultrashort"
                 else "1个月内兑现或止损 (short)")
    return {
        "warning": "短炒警示 (skills/14): 超短线/短线是战术仓，不是投资 — "
                   "floor = 真生意(core_business≥"
                   f"{config.SHORT_FLOOR_BUSINESS:g}) + 周K上升趋势 + "
                   "无否决；DCF 仅为'失败变持有'备注，不作买入论证",
        "rules": f"纪律: -7% 硬止损 | 时间止损 {time_stop} | "
                 "单票仓位 ≤ 5% NAV",
    }


def _masters_live_check(args, cs, pool) -> int:
    """Live cycle-trap pass on an AI-chosen shortlist (v2, D1).

    The wide pool carries no per-row network checks; once L3 picks the
    deep-review names, this runs the forward-PE divergence on exactly
    those (A-shares; HK/US gaps declared)."""
    rows = []
    for token in args.check:
        tok = str(token).strip().upper()
        mkt, _, code = tok.partition(":")
        hit = pool
        if code:
            hit = hit[hit["market"].astype(str).str.upper() == mkt]
            hit = hit[hit["code"].astype(str).str.upper() == code]
        else:
            hit = hit[hit["code"].astype(str).str.upper() == mkt]
        if hit.empty:
            rows.append({"query": token, "error": "not in pool"})
            continue
        r = hit.iloc[0]
        item = {"market": r.get("market"), "code": r.get("code"),
                "name": r.get("name"),
                "core_score": r.get("core_score"),
                "pe_divergence": None, "cycle_trap": False,
                "cycle_warn": False, "data_gap": ""}
        if str(r.get("market")) != "A":
            item["data_gap"] = "no consensus-EPS source (HK/US)"
        elif args.no_live:
            item["data_gap"] = "live pass skipped (--no-live)"
        else:
            div = cs.forward_pe_divergence(r)
            if div is None:
                item["data_gap"] = "consensus EPS unavailable"
            else:
                item["pe_divergence"] = round(div, 2)
                if div >= cs.CYCLE_TRAP_RATIO:
                    item["cycle_trap"] = True
                elif div >= cs.CYCLE_WARN_RATIO:
                    item["cycle_warn"] = True
        rows.append(item)
    if args.json:
        print(report.to_json(pd.DataFrame(rows),
                             {"mode": "live_check",
                              "cycle_trap_ratio": cs.CYCLE_TRAP_RATIO,
                              "cycle_warn_ratio": cs.CYCLE_WARN_RATIO}))
        return 0
    print("== masters-vote live check (cycle-trap pass) ==")
    for it in rows:
        if "error" in it:
            print(f"  {it['query']}: {it['error']}")
            continue
        flags = []
        if it["cycle_trap"]:
            flags.append("CYCLE_TRAP (hard veto)")
        if it["cycle_warn"]:
            flags.append("cycle_warn")
        if it["data_gap"]:
            flags.append(f"gap:{it['data_gap']}")
        div = it["pe_divergence"]
        print(f"  {it['market']}:{it['code']} {it['name']} — "
              f"pe_div={div if div is not None else '-'} "
              f"core={it['core_score'] if pd.notna(it['core_score']) else '-'}"
              f"  {', '.join(flags)}")
    return 0


def cmd_strategy_list(args) -> int:
    """List all registered strategies (presets + masters)."""
    from .strategy.registry import list_strategies
    from .strategy.factors import PILLARS
    items = list_strategies()
    if not items:
        print("no strategies registered")
        return 1
    print(f"{'id':<16} {'kind':<8} {'horizon':<11} {'name':<44} weights")
    print("-" * 110)
    for s in items:
        w = " / ".join(f"{p}={s.weights.get(p, 0):.2f}"
                       for p in PILLARS if s.weights.get(p, 0) > 0)
        gates = f"  gates: {len(s.gates)}" if s.gates else ""
        hz = s.horizon or "-"
        print(f"{s.id:<16} {s.kind:<8} {hz:<11} {s.name:<44} {w}{gates}")
    return 0


def cmd_horizon_list(args) -> int:
    """List all registered horizons."""
    from .strategy.factors import PILLARS
    from .strategy.registry import list_horizons
    items = list_horizons()
    if not items:
        print("no horizons registered")
        return 1
    print(f"{'id':<12} {'name':<8} {'window':<12} weights")
    print("-" * 96)
    for h in items:
        w = " / ".join(f"{p}={h.weights.get(p, 0):.2f}"
                       for p in PILLARS if h.weights.get(p, 0) > 0)
        mom = f"  momentum: {'+'.join(h.momentum_cols)}"
        gates = f"  gates: {len(h.gates)}" if h.gates else ""
        print(f"{h.id:<12} {h.name:<8} {h.window:<12} {w}{mom}{gates}")
    return 0


def cmd_source_list(args) -> int:
    """List all registered data sources."""
    from .strategy.registry import list_sources
    items = list_sources()
    if not items:
        print("no data sources registered")
        return 1
    print(f"{'id':<12} {'name':<32} capabilities")
    print("-" * 80)
    for ds in items:
        caps = ", ".join(ds.capabilities)
        print(f"{ds.id:<12} {ds.name:<32} {caps}")
    return 0


# ---------------------------------------------------------------------------
# User / holdings commands
# ---------------------------------------------------------------------------
def _load_user_or_exit(user_id):
    from . import users as usr
    try:
        return usr.load_user(user_id), usr
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def _resolve_user_id_or_exit(args, attr="user_id"):
    """Explicit --user/id wins; else the session's current user."""
    from . import users as usr
    uid = getattr(args, attr, None)
    if uid:
        return uid
    cur = usr.current_user()
    if cur is None:
        raise SystemExit(
            "no user specified and no active session; "
            "`user login <id>` / `user create <id>` first, "
            "or pass the user id explicitly")
    return cur


def cmd_user(args) -> int:
    from . import users as usr
    if args.user_cmd == "create":
        try:
            u = usr.create_user(args.user_id, name=args.name,
                                horizon=args.horizon or "")
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        usr.login(u.id)
        print(f"created user {u.id} ({u.name}) -> {usr.user_path(u.id)}; "
              f"logged in as {u.id}")
        return 0

    if args.user_cmd == "login":
        try:
            usr.login(args.user_id)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        print(f"logged in as {args.user_id}")
        return 0

    if args.user_cmd == "logout":
        usr.logout()
        print("logged out")
        return 0

    if args.user_cmd == "whoami":
        cur = usr.current_user()
        items = usr.list_users()
        if args.json:
            print(json.dumps({"current": cur,
                              "users": [u.id for u in items]},
                             ensure_ascii=False))
            return 0 if cur else 1
        if cur is None:
            print("no active session; `user login <id>` or "
                  "`user create <id>`")
        else:
            print(f"current user: {cur}")
        if items:
            print("users: " + ", ".join(u.id for u in items))
        return 0 if cur else 1

    if args.user_cmd == "list":
        items = usr.list_users()
        if not items:
            print(f"no users under {usr.users_dir()}; "
                  "create one with `user create <id>`")
            return 1
        print(f"{'id':<16} {'name':<16} {'holdings':>9}  style")
        print("-" * 72)
        for u in items:
            style = " / ".join(
                f"{p}={u.style['weights'][p]:.2f}"
                for p in u.style.get("weights", {})
                if u.style["weights"].get(p, 0) > 0) or "-"
            print(f"{u.id:<16} {u.name[:14]:<16} {len(u.holdings):>9}  "
                  f"{style}")
        return 0

    if args.user_cmd == "show":
        u, _ = _load_user_or_exit(_resolve_user_id_or_exit(args))
        print(f"== user {u.id} ==")
        print(f"name      : {u.name}")
        print(f"created   : {u.created_at}")
        if u.has_style():
            w = u.style.get("weights") or {}
            print("style     : " + " / ".join(
                f"{p}={w[p]:.2f}" for p in w if w.get(p, 0) > 0))
            gates = u.style.get("gates") or []
            if gates:
                print("gates     : " + ", ".join(
                    f"{c} {o} {v:g}" for c, o, v in gates))
            if u.style.get("horizon"):
                print(f"horizon   : {u.style['horizon']}")
        else:
            print("style     : (unset; screen/recommend fall back to "
                  f"{config.DEFAULT_PRESET})")
        print(f"holdings  : {len(u.holdings)}")
        for h in u.holdings:
            opened = f" opened {h.opened}" if h.opened else ""
            print(f"  - {h.market}/{h.code} {h.name}: "
                  f"{h.qty:,.0f} 股 @ {h.cost:,.2f} {h.currency}{opened}")
        return 0

    if args.user_cmd == "set-style":
        weights = _parse_weights(args.weight) if args.weight else None
        gates = None
        if args.gate:
            try:
                gates = [usr.parse_gate(g) for g in args.gate]
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        horizon = "" if getattr(args, "clear_horizon", False) else args.horizon
        try:
            u = usr.set_style(_resolve_user_id_or_exit(args),
                              weights=weights, gates=gates,
                              clear_gates=args.clear_gates,
                              horizon=horizon, base=args.base)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        w = u.style.get("weights") or {}
        print(f"style set for {u.id}: "
              + (" / ".join(f"{p}={w[p]:.2f}"
                            for p in w if w.get(p, 0) > 0) or "(no weights)"))
        gates = u.style.get("gates") or []
        if gates:
            print("gates: " + ", ".join(
                f"{c} {o} {v:g}" for c, o, v in gates))
        if u.style.get("horizon"):
            print(f"horizon: {u.style['horizon']}")
        return 0
    return 1


def _resolve_stock_or_exit(query):
    from .resolve import resolve as resolve_stock
    try:
        snap = report.resolve_snapshot()
    except FileNotFoundError:
        snap = None
    matches = resolve_stock(query, snapshot_dir=snap)
    if not matches:
        raise SystemExit(
            f"no match for {query!r}; try a full name or code "
            f"(e.g. 600519 / 00116 / AAPL)")
    m = matches[0]
    if len(matches) > 1:
        others = ", ".join(x.label() for x in matches[1:4])
        print(f"resolved: {m.label()} (also matched: {others})",
              file=sys.stderr)
    return m


def cmd_holding(args) -> int:
    from . import users as usr
    # `holding add [user] stock` — a single positional is the STOCK,
    # with the user coming from the session; two positionals keep the
    # legacy `<user> <stock>` order.
    if args.holding_cmd in ("add", "update", "remove"):
        if args.stock is None:
            args.user_id, args.stock = None, args.user_id
        if args.stock is None:
            raise SystemExit(
                f"missing stock; `holding {args.holding_cmd} "
                f"[user_id] <stock> ...`")
    if args.holding_cmd == "add":
        user_id = _resolve_user_id_or_exit(args)
        try:
            user = usr.load_user(user_id)
        except FileNotFoundError:
            try:
                user = usr.create_user(user_id, name=user_id)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
            usr.login(user.id)
            print(f"created user {user.id} ({usr.user_path(user.id)}); "
                  f"logged in as {user.id}")
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        m = _resolve_stock_or_exit(args.stock)
        try:
            h = usr.add_holding(user, m, qty=args.qty, cost=args.cost,
                                opened=args.opened or "")
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        usr.save_user(user)
        print(f"added {h.market}/{h.code} {h.name}: {h.qty:,.0f} 股 @ "
              f"{h.cost:,.2f} {h.currency}"
              + (f" (opened {h.opened})" if h.opened else ""))
        return 0

    if args.holding_cmd == "update":
        user, _ = _load_user_or_exit(_resolve_user_id_or_exit(args))
        m = _resolve_stock_or_exit(args.stock)
        try:
            h = usr.update_holding(user, m.market, m.code, qty=args.qty,
                                   cost=args.cost, opened=args.opened,
                                   name=args.name)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        usr.save_user(user)
        print(f"updated {h.market}/{h.code} {h.name}: {h.qty:,.0f} 股 @ "
              f"{h.cost:,.2f} {h.currency}"
              + (f" (opened {h.opened})" if h.opened else ""))
        return 0

    if args.holding_cmd == "remove":
        user, _ = _load_user_or_exit(_resolve_user_id_or_exit(args))
        m = _resolve_stock_or_exit(args.stock)
        try:
            h = usr.remove_holding(user, m.market, m.code)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        usr.save_user(user)
        print(f"removed {h.market}/{h.code} {h.name} "
              f"(was {h.qty:,.0f} 股 @ {h.cost:,.2f})")
        return 0

    if args.holding_cmd == "list":
        if not _check_freshness(args):
            return 1
        user, _ = _load_user_or_exit(_resolve_user_id_or_exit(args))
        from . import recommend as rec
        try:
            snap = report.resolve_snapshot(args.data_dir, args.snapshot)
        except FileNotFoundError as exc:
            snap = None
        health = rec.holdings_health(user, snap)
        if args.json:
            print(rec.health_to_json(health))
        else:
            print(f"== holdings: {user.id} ({user.name}) ==")
            print(rec.render_holdings(health))
        return 0
    return 1


def cmd_recommend(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import recommend as rec
    markets = _parse_markets(args.markets)
    try:
        result = rec.build_recommendation(
            _resolve_user_id_or_exit(args, "user"),
            data_dir=args.data_dir, snapshot=args.snapshot,
            strategy=args.strategy, horizon=args.horizon,
            top_n=args.top, markets=markets)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    if args.json:
        print(rec.to_json(result))
    else:
        print(rec.render_recommend(result))
    return 0


def cmd_trade(args) -> int:
    import sys
    from . import trade as tr

    def _snap():
        try:
            return report.resolve_snapshot(args.data_dir, args.snapshot)
        except FileNotFoundError:
            return None

    def _season_or_exit(sid):
        try:
            return tr.load_season(sid)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from None

    cmd = args.trade_cmd
    if cmd == "season":
        sub = args.season_cmd
        if sub == "new":
            markets = [m.strip().upper() for m in args.markets.split(",")
                       if m.strip()]
            try:
                s = tr.new_season(
                    args.season_id, name=args.name,
                    base=args.base.upper(), capital=args.capital,
                    markets=markets, fx_spread=args.fx_spread)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
            print(f"created season {s['id']} ({s['name']}): "
                  f"{s['initial_capital']:,.2f} {s['base_currency']}, "
                  f"markets {','.join(s['rules']['markets'])} -> "
                  f"{tr.season_path(s['id'])}")
            return 0
        if sub == "list":
            items = tr.list_seasons()
            if not items:
                print("no seasons; create one with `trade season new`")
                return 0
            for s in items:
                last = (s["nav_history"][-1]["nav"]
                        if s["nav_history"] else None)
                print(f"{s['id']:16} {s['status']:7} "
                      f"{s['name']} | initial "
                      f"{s['initial_capital']:,.2f} "
                      f"{s['base_currency']}"
                      + (f" | last NAV {last:,.2f}"
                         f" ({s['nav_history'][-1]['date']})"
                         if last is not None else ""))
            return 0
        if sub == "show":
            season = _season_or_exit(args.season_id)
            if args.json:
                print(tr.to_json(season))
            else:
                print(tr.render_season(season))
            return 0
        if sub == "rule":
            markets = [m.strip().upper() for m in args.markets.split(",")
                       if m.strip()]
            try:
                tr.update_rules(args.season_id, markets=markets)
            except (ValueError, FileNotFoundError) as exc:
                raise SystemExit(str(exc)) from None
            print(f"season {args.season_id} markets -> "
                  f"{','.join(markets)} (existing positions stay "
                  f"sellable, new buys follow the new rules)")
            return 0
        if sub in ("close", "pause", "resume"):
            status = {"close": "closed", "pause": "paused",
                      "resume": "active"}[sub]
            try:
                s = tr.set_season_status(args.season_id, status)
            except (ValueError, FileNotFoundError) as exc:
                raise SystemExit(str(exc)) from None
            print(f"season {s['id']} -> {s['status']}")
            return 0
        if sub == "delete":
            if not args.confirm:
                raise SystemExit(
                    f"deleting season {args.season_id!r} removes its "
                    f"entire fill/nav/journal history; prefer `trade "
                    f"season close`. Re-run with --confirm to delete.")
            try:
                tr.delete_season(args.season_id)
            except FileNotFoundError as exc:
                raise SystemExit(str(exc)) from None
            print(f"deleted season {args.season_id}")
            return 0
        return 1

    if cmd in ("buy", "sell"):
        if not _check_freshness(args):
            return 1
        m = _resolve_stock_or_exit(args.stock)
        try:
            if cmd == "buy":
                fill = tr.buy(args.season_id, m, qty=args.qty,
                              note=args.note or "",
                              lot_override=args.lot, snap_dir=_snap())
            else:
                fill = tr.sell(args.season_id, m, qty=args.qty,
                               note=args.note or "", snap_dir=_snap())
        except tr.TradeError as exc:
            print(f"[TRADE REJECTED] {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(tr.to_json(fill))
        else:
            print(tr.render_fill(fill))
        return 0

    if cmd == "fx":
        if not _check_freshness(args):
            return 1
        if "->" not in args.pair:
            raise SystemExit(
                f"pair must look like USD->HKD, got {args.pair!r}")
        src, dst = [x.strip().upper() for x in args.pair.split("->", 1)]
        try:
            fill = tr.fx(args.season_id, src, dst, args.amount,
                         snap_dir=_snap())
        except tr.TradeError as exc:
            print(f"[TRADE REJECTED] {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(tr.to_json(fill))
        else:
            print(tr.render_fill(fill))
        return 0

    if cmd == "cash":
        if not _check_freshness(args):
            return 1
        try:
            fill = tr.cash_move(args.season_id, args.action, args.amount,
                                args.currency.upper(),
                                note=args.note or "", snap_dir=_snap())
        except tr.TradeError as exc:
            print(f"[TRADE REJECTED] {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(tr.to_json(fill))
        else:
            print(tr.render_fill(fill))
        return 0

    if cmd == "nav":
        if not _check_freshness(args):
            return 1
        _season_or_exit(args.season_id)
        try:
            entry = tr.mark_nav(args.season_id, snap_dir=_snap())
        except tr.TradeError as exc:
            print(f"[NAV FAILED] {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(tr.to_json(entry))
        else:
            print(tr.render_nav(entry))
        return 0

    if cmd == "journal":
        if not _check_freshness(args):
            return 1
        if args.show:
            season = _season_or_exit(args.season_id)
            entries = season["journal"][-args.last:]
            if args.json:
                print(tr.to_json(entries))
            else:
                print(tr.render_journal(entries))
            return 0
        if not args.text:
            raise SystemExit("pass --text '...' to write, or --show")
        _season_or_exit(args.season_id)
        try:
            j = tr.write_journal(args.season_id, args.text,
                                 snap_dir=_snap())
        except tr.TradeError as exc:
            print(f"[JOURNAL FAILED] {exc}", file=sys.stderr)
            return 1
        print(f"journal [{j['date']}] nav {j['nav']:,.2f} day "
              f"{j['day_pnl']:+,.2f}: {j['text']}")
        return 0

    if cmd == "status":
        if not _check_freshness(args):
            return 1
        summaries = tr.status_all(snap_dir=_snap())
        if args.json:
            print(tr.to_json(summaries))
        else:
            print(tr.render_status(summaries))
        return 0
    return 1


# ---------------------------------------------------------------------------
# AI-toolkit commands (ask / compare / overview / doctor / skill)
# ---------------------------------------------------------------------------
def _check_freshness(args) -> bool:
    """Gate: return True if OK to proceed, False if blocked.

    FAIL → block (print reason, return False).
    WARN → warn to stderr, proceed.
    PASS → silent.
    --no-check → skip entirely (for automated pipelines).
    """
    if getattr(args, "no_check", False):
        return True
    from . import doctor as dr
    data_dir = getattr(args, "data_dir", None)
    status, msg = dr.freshness_gate(data_dir)
    if status == "FAIL":
        print(f"[FRESHNESS BLOCKED] {msg}", file=sys.stderr)
        print("run `python -m value_genie doctor` for details, "
              "or `python -m value_genie fetch` to refresh.",
              file=sys.stderr)
        return False
    if status == "WARN":
        print(f"[FRESHNESS WARN] {msg}", file=sys.stderr)
    return True


def cmd_ask(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import analyze as az
    from .resolve import resolve as resolve_stock
    try:
        snap = report.resolve_snapshot(args.data_dir)
    except FileNotFoundError:
        snap = None
    matches = resolve_stock(args.query, snapshot_dir=snap)
    if not matches:
        print(f"no match for {args.query!r}; try a full name or code",
              file=sys.stderr)
        return 2
    m = matches[0]
    if len(matches) > 1:
        others = ", ".join(x.label() for x in matches[1:4])
        print(f"resolved: {m.label()} (also matched: {others})",
              file=sys.stderr)
    result = az.analyze_stock(m, snapshot_dir=snap, horizon=args.horizon)
    if args.json:
        print(az.to_json(result))
    elif args.evidence:
        print(az.render_evidence(result))
    else:
        print(az.render_brief(result))
    return 0


def cmd_intel(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import resolve as rs
    from .intel import report as intel_report
    try:
        snap = report.resolve_snapshot(args.data_dir)
    except FileNotFoundError:
        snap = None
    matches = rs.resolve(args.query, snapshot_dir=snap)
    if not matches:
        print(f"no match for {args.query!r}; try a full name or code",
              file=sys.stderr)
        return 2
    m = matches[0]
    if len(matches) > 1:
        others = ", ".join(x.label() for x in matches[1:4])
        print(f"resolved: {m.label()} (also matched: {others})",
              file=sys.stderr)
    result = intel_report.build_intel_report(m, snapshot_dir=snap)
    if args.json:
        print(intel_report.to_json(result))
    else:
        print(intel_report.render_intel(result))
    return 0


def cmd_compare(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import analyze as az
    from .resolve import resolve as resolve_stock
    try:
        snap = report.resolve_snapshot(args.data_dir)
    except FileNotFoundError:
        snap = None
    matches = []
    for q in args.stocks:
        ms = resolve_stock(q, snapshot_dir=snap)
        if not ms:
            print(f"no match for {q!r}; try a full name or code",
                  file=sys.stderr)
            return 2
        matches.append(ms[0])
    # drop duplicate resolutions
    seen, uniq = set(), []
    for m in matches:
        if (m.market, m.code) not in seen:
            seen.add((m.market, m.code))
            uniq.append(m)
    df = az.compare_stocks(uniq, snapshot_dir=snap)
    if args.json:
        print(json.dumps({"stocks": report.df_records(df)},
                         ensure_ascii=False, indent=2))
        return 0
    print("== Value Genie compare ==")
    print(df.to_string(index=False, float_format=lambda v: f"{v:.1f}"))
    if len(df) >= 2:
        cheap = df.dropna(subset=["pe_pctile"])
        grow = df.dropna(subset=["rev_yoy"])
        if not cheap.empty:
            c = cheap.sort_values("pe_pctile").iloc[0]
            print(f"\ncheapest: {c['name']} "
                  f"(PE {c['pe_pctile']:.0f}th pctile)")
        if not grow.empty:
            g = grow.sort_values("rev_yoy", ascending=False).iloc[0]
            print(f"fastest growth: {g['name']} "
                  f"(rev YoY {g['rev_yoy']:.1f}%)")
    return 0


def cmd_overview(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import overview as ov
    markets = _parse_markets(args.markets)
    try:
        data = ov.market_overview(markets=markets, top_n=args.top,
                                  data_dir=args.data_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    if args.json:
        print(ov.to_json(data))
    else:
        print(ov.render_overview(data))
    return 0


def cmd_doctor(args) -> int:
    from . import doctor as dr
    checks = dr.run_checks(args.data_dir)
    if args.json:
        print(dr.to_json(checks))
    else:
        print(dr.render_checks(checks))
    return dr.doctor_exit_code(checks)


def cmd_skill(args) -> int:
    from . import skills as sk
    d = config.SKILLS_DIR
    if args.skill_cmd == "list":
        items, errors = sk.load_skills(d)
        for e in errors:
            print(f"ERROR {e}")
        if not items:
            print(f"no skills found under {d}")
            return 1
        for s in items:
            print(f"{s.id:<28} v{s.version:<4} notes="
                  f"{len(sk.field_notes(s)):<3} {s.title}")
        return 0
    try:
        if args.skill_cmd == "show":
            s = sk.find_skill(d, args.skill_id)
            print(s.path.read_text(encoding="utf-8"))
        elif args.skill_cmd == "note":
            s = sk.append_note(d, args.skill_id, args.text)
            print(f"noted on {s.id} (v{s.version}): {args.text}")
        elif args.skill_cmd == "edit":
            s = sk.edit_skill(d, args.skill_id,
                              add_triggers=args.add_trigger,
                              remove_triggers=args.remove_trigger)
            print(f"updated {s.id} -> v{s.version}; "
                  f"triggers: {', '.join(s.triggers)}")
    except sk.SkillFormatError as exc:
        print(exc)
        return 2
    return 0


def cmd_tower(args) -> int:
    """Cognitive tower (认知巴别塔): philosophy bricks.

    Not freshness-gated: the tower never depends on market snapshots.
    """
    import sys as _sys

    from . import tower as tw

    d = config.TOWER_DIR

    def _brick_dict(b):
        return {"id": b.id, "title": b.title, "statement": b.statement,
                "source": b.source, "status": b.status, "tags": b.tags,
                "links": b.links, "version": b.version,
                "created_at": b.created_at, "updated_at": b.updated_at,
                "notes": len(tw.field_notes(b))}

    def _read_body():
        if getattr(args, "stdin_body", False):
            return _sys.stdin.read()
        return None

    try:
        if args.tower_cmd == "list":
            bricks, errors = tw.load_bricks(d)
            for e in errors:
                print(f"ERROR {e}", file=_sys.stderr)
            if args.status:
                bricks = [b for b in bricks if b.status == args.status]
            if args.tag:
                bricks = [b for b in bricks if args.tag in b.tags]
            if args.kind:
                bricks = [b for b in bricks
                          if b.source.split(":", 1)[0] == args.kind]
            if args.json:
                print(json.dumps([_brick_dict(b) for b in bricks],
                                 ensure_ascii=False, indent=2))
                return 0
            if not bricks:
                print(f"no bricks found under {d}")
                return 1
            for b in bricks:
                print(f"{b.id:<36} {b.status:<12} v{b.version:<3} "
                      f"notes={len(tw.field_notes(b)):<3} {b.title}")
            return 0

        if args.tower_cmd == "show":
            b = tw.find_brick(d, args.brick_id)
            if args.json:
                out = _brick_dict(b)
                out["body"] = b.body
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                print(b.path.read_text(encoding="utf-8"))
            return 0

        if args.tower_cmd == "add":
            body = _read_body() or "## 论证\n（待论证）\n"
            b = tw.Brick(id=args.brick_id, title=args.title,
                         statement=args.statement, source=args.source,
                         status=args.status, tags=args.tag or [],
                         links=args.link or [], body=body)
            tw.add_brick(d, b)
            if args.json:
                print(json.dumps(_brick_dict(b), ensure_ascii=False))
            else:
                print(f"added {b.id} ({b.status}) v{b.version}")
            return 0

        if args.tower_cmd == "note":
            b = tw.append_note(d, args.brick_id, args.text)
            print(f"noted on {b.id} (v{b.version}): {args.text}")
            return 0

        if args.tower_cmd == "link":
            b = tw.add_link(d, args.brick_id, args.link)
            print(f"linked {b.id}: {args.link} (v{b.version})")
            return 0

        if args.tower_cmd == "set":
            b = tw.set_brick(d, args.brick_id, status=args.status,
                             reason=args.reason, add_tags=args.add_tag,
                             drop_tags=args.drop_tag, body=_read_body())
            print(f"updated {b.id} -> {b.status} v{b.version}")
            return 0

        if args.tower_cmd == "search":
            bricks = tw.search_bricks(d, args.query)
            if args.json:
                print(json.dumps([_brick_dict(b) for b in bricks],
                                 ensure_ascii=False, indent=2))
                return 0
            if not bricks:
                print(f"no bricks match {args.query!r}")
                return 1
            for b in bricks:
                print(f"{b.id:<36} {b.status:<12} {b.title}")
                print(f"    {b.statement}")
            return 0

        if args.tower_cmd == "stats":
            stats = tw.tower_stats(d)
            if args.json:
                print(json.dumps(stats, ensure_ascii=False, indent=2))
                return 0
            bs = stats["by_status"]
            print("== 认知巴别塔 (cognitive tower) ==")
            print(f"核心     axiom x{bs.get('axiom', 0)}: "
                  f"{', '.join(stats['axiom']) or 'MISSING'}")
            print(f"使命     mission x{bs.get('mission', 0)}: "
                  f"{'; '.join(stats['mission_titles'])}")
            print(f"定律     law x{bs.get('law', 0)} (经对话/生活验证)")
            print(f"吸收     principle x{bs.get('principle', 0)} "
                  f"(藏书+大师, 借来未验证)")
            print(f"待验     hypothesis x{bs.get('hypothesis', 0)} / "
                  f"observation x{bs.get('observation', 0)}")
            print(f"伤疤     refuted x{bs.get('refuted', 0)} (永久保留)")
            print(f"张力     tension links x{stats['tension_links']}")
            print(f"生长     近30天 +{stats['recent_bricks_30d']} 砖 "
                  f"+{stats['recent_notes_30d']} notes; "
                  f"塔龄 {stats['tower_age_days']} 天")
            print(f"总计     {stats['total_bricks']} 砖 / "
                  f"{stats['total_notes']} notes"
                  + (f" / {stats['load_errors']} load errors"
                     if stats["load_errors"] else ""))
            return 0

        if args.tower_cmd == "seed":
            from . import tower_seed as tseed
            result = tseed.seed_tower(d, dry_run=args.dry_run)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            verb = "would add" if args.dry_run else "added"
            print(f"{verb} {result['added']} bricks, "
                  f"skipped {result['skipped']} existing; "
                  f"tower now has {result['total']} bricks")
            return 0
    except tw.TowerFormatError as exc:
        print(exc, file=_sys.stderr)
        return 1
    return 0


def cmd_thesis(args) -> int:
    """Thesis registry (论点喂池): tower-brick-backed machine theses
    whose member lists feed the masters-vote L1 pool.

    Registry management is not freshness-gated; `show --discover`
    reads the snapshot read-only.
    """
    import sys as _sys
    from dataclasses import asdict

    from . import thesis as th

    def _dict(t):
        d = asdict(t)
        d["members_n"] = len(t.members)
        return d

    def _hints(pairs):
        out = {}
        for h in (pairs or []):
            parts = h.split(":", 1)
            if len(parts) != 2 or parts[0].strip().upper() \
                    not in config.MARKETS or not parts[1].strip():
                raise ValueError(
                    f"bad industry hint {h!r}; expected MARKET:关键词 "
                    f"(e.g. A:存储器)")
            out.setdefault(parts[0].strip().upper(), []).append(
                parts[1].strip())
        return out

    try:
        if args.thesis_cmd == "list":
            ts = th.list_theses(status=args.status)
            if args.json:
                print(json.dumps([_dict(t) for t in ts],
                                 ensure_ascii=False, indent=2))
                return 0
            if not ts:
                print(f"no theses under {th.theses_dir()}")
                return 1
            for t in ts:
                print(f"{t.id:<28} {t.status:<8} "
                      f"members={len(t.members):<3} "
                      f"brick={t.brick or '-':<32} {t.name}")
            return 0

        if args.thesis_cmd == "show":
            t = th.load_thesis(args.thesis_id)
            if args.discover:
                snap = report.resolve_snapshot(args.data_dir,
                                               args.snapshot)
                cands = th.discover(snap, t)
                if args.json:
                    print(report.to_json(
                        cands, {"thesis": t.id,
                                "members": len(t.members)}))
                    return 0
                if cands.empty:
                    print("no undiscovered industry-hint candidates")
                    return 0
                print(report.format_console(cands))
                print("\npromote deliberately: thesis amend "
                      f"{t.id} --add-member MARKET:CODE:名称")
                return 0
            if args.json:
                print(json.dumps(_dict(t), ensure_ascii=False, indent=2))
                return 0
            print(f"id        : {t.id}")
            print(f"name      : {t.name}")
            print(f"status    : {t.status}"
                  + (f" (retired: {t.retired_reason})"
                     if t.status == "retired" else ""))
            print(f"brick     : {t.brick or '-'}")
            print(f"statement : {t.statement}")
            print(f"reason    : {t.reason}")
            if t.features:
                print("features  :")
                for f_ in t.features:
                    print(f"  - {f_}")
            if t.falsification:
                print("falsification (kill set):")
                for f_ in t.falsification:
                    print(f"  - {f_}")
            if t.industry_hints:
                print("industry hints: " + "; ".join(
                    f"{k}: {', '.join(v)}"
                    for k, v in t.industry_hints.items()))
            print(f"members ({len(t.members)}):")
            for m in t.members:
                note = f" — {m.note}" if m.note else ""
                print(f"  {m.market:<3} {m.code:<8} {m.name}{note}")
            print(f"created   : {t.created_at}  "
                  f"updated: {t.updated_at}")
            return 0

        if args.thesis_cmd == "add":
            members = [th.parse_member(x) for x in (args.member or [])]
            t = th.create_thesis(
                args.thesis_id, name=args.name or "",
                brick=args.brick or "", statement=args.statement or "",
                reason=args.reason or "",
                features=args.feature or [],
                falsification=args.falsification or [],
                members=members,
                industry_hints=_hints(args.industry))
            if args.json:
                print(json.dumps(_dict(t), ensure_ascii=False))
            else:
                print(f"added thesis {t.id} "
                      f"({len(t.members)} members, "
                      f"brick={t.brick or '-'})")
            return 0

        if args.thesis_cmd == "amend":
            t = th.amend_thesis(
                args.thesis_id,
                add_members=[th.parse_member(x)
                             for x in (args.add_member or [])],
                drop_members=args.drop_member or [],
                add_features=args.feature or [],
                add_falsification=args.falsification or [],
                add_industry_hints=_hints(args.industry),
                reason=args.reason)
            if args.json:
                print(json.dumps(_dict(t), ensure_ascii=False))
            else:
                print(f"amended thesis {t.id} "
                      f"({len(t.members)} members)")
            return 0

        if args.thesis_cmd == "retire":
            t = th.retire_thesis(args.thesis_id, args.reason or "")
            print(f"retired thesis {t.id}: {t.retired_reason}")
            return 0

        if args.thesis_cmd == "remove":
            path = th.remove_thesis(args.thesis_id)
            print(f"removed {path.name} (a falsified thesis belongs to "
                  f"`thesis retire`, not deletion)")
            return 0
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=_sys.stderr)
        return 1
    return 0


def cmd_profile(args) -> int:
    """Company profiles (Phase 5): raw source text under data/ (cleanable)
    + AI-distilled assessments under profiles/ (LOCAL-ONLY, untracked).

    Not freshness-gated (same contract as tower/thesis): the registry
    depends on no market snapshot; `show/fetch/assess` resolve the stock
    through the normal chain (exact code forms need no snapshot).
    """
    import sys as _sys

    from . import profile as prof

    try:
        if args.profile_cmd == "list":
            rows = prof.list_assessments()
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2,
                                 default=str))
                return 0
            if not rows:
                print(f"no assessments under {prof.profiles_dir()}")
                return 1
            for a in rows:
                b = (a.get("business") or {}).get("score")
                c = (a.get("culture") or {}).get("score")
                stale = " STALE(raw changed)" if a.get("raw_stale") else ""
                print(f"{a['id']:<14} {str(a.get('name') or ''):<16} "
                      f"business={b if b is not None else '-':>5} "
                      f"culture={c if c is not None else '-':>5} "
                      f"{a.get('assessed_at', '')[:10]}{stale}")
            return 0

        if args.profile_cmd == "show":
            m = _resolve_stock_or_exit(args.stock)
            raw = prof.load_raw(m.market, m.code)
            a = prof.load_assessment(m.market, m.code)
            if args.json:
                print(json.dumps({
                    "id": f"{m.market}:{m.code}", "name": m.name,
                    "raw": raw, "assessment": a,
                    "raw_stale": prof.is_stale(a, raw)},
                    ensure_ascii=False, indent=2, default=str))
                return 0
            if raw is None and a is None:
                print(f"no profile for {m.label()} yet — fetch one with "
                      f"`profile fetch {m.market}:{m.code}`")
                return 1
            if raw:
                print(f"== raw ({raw.get('source')}, fetched "
                      f"{str(raw.get('fetched_at'))[:10]}, hash "
                      f"{raw.get('content_hash')}) ==")
                if raw.get("summary"):
                    print(raw["summary"][:600])
                if raw.get("main_business"):
                    print(f"\n主营业务: {raw['main_business']}")
                if raw.get("vision"):
                    print(f"愿景: {raw['vision']}")
            else:
                print("(no raw fetched)")
            print()
            if a:
                b, c = a.get("business") or {}, a.get("culture") or {}
                print(f"== assessment ({a.get('assessed_at', '')[:10]}, "
                      f"agent={a.get('agent')}"
                      + (" STALE" if prof.is_stale(a, raw) else "")
                      + ") ==")
                print(f"business {b.get('score')}: {b.get('argument')}")
                print(f"culture  {c.get('score')}: {c.get('argument')}")
                if (a.get("dcf") or {}).get("argument"):
                    print(f"dcf      : {a['dcf']['argument']}")
                if a.get("verdict"):
                    print(f"verdict  : {a['verdict']}")
            else:
                print("(not assessed yet — distill with `profile assess`)")
            return 0

        if args.profile_cmd == "fetch":
            m = _resolve_stock_or_exit(args.stock)
            from .fetch import profiles as pf
            raw = pf.update_raw(m.market, m.code)
            if raw is None:
                print(f"profile fetch failed for {m.label()} "
                      f"(source unavailable; existing raw untouched)",
                      file=_sys.stderr)
                return 1
            print(f"fetched {raw['id']} <- {raw['source']} "
                  f"(hash {raw['content_hash']}, "
                  f"summary {len(raw.get('summary') or '')} chars)")
            return 0

        if args.profile_cmd == "assess":
            m = _resolve_stock_or_exit(args.stock)
            founder_led = None
            if args.founder_led is not None:
                founder_led = args.founder_led == "yes"
            a = prof.assess(
                m.market, m.code, name=m.name,
                business_score=args.business_score,
                culture_score=args.culture_score,
                moat_type=args.moat_type or "",
                machine_lifecycle=args.lifecycle or "",
                founder_led=founder_led,
                benfen=args.benfen or [],
                business_arg=args.business_arg or "",
                culture_arg=args.culture_arg or "",
                dcf_arg=args.dcf_arg or "",
                verdict=args.verdict or "",
                agent=args.agent)
            if args.json:
                print(json.dumps(a, ensure_ascii=False, default=str))
            else:
                print(f"assessed {a['id']} "
                      f"(business={a['business']['score']}, "
                      f"culture={a['culture']['score']}; raw_hash "
                      f"{a.get('raw_hash') or 'none'})")
            return 0

        if args.profile_cmd == "status":
            rows = prof.list_assessments()
            stale = [a for a in rows if a.get("raw_stale")]
            out = {"assessments": len(rows), "stale": len(stale),
                   "stale_ids": [a["id"] for a in stale],
                   "profiles_dir": str(prof.profiles_dir()),
                   "raw_dir": str(prof.raw_dir())}
            if args.json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                print(f"assessments: {out['assessments']} "
                      f"(stale: {out['stale']}"
                      + (f" — {', '.join(out['stale_ids'])}"
                         if stale else "") + ")")
                print(f"dirs       : {out['profiles_dir']} (untracked) | "
                      f"{out['raw_dir']} (cleanable)")
            return 0
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=_sys.stderr)
        return 1
    return 0


def _model_master(args):
    """Latest snapshot master frame for comps; None when unavailable."""
    try:
        snap = report.resolve_snapshot(getattr(args, "data_dir", None))
    except FileNotFoundError:
        return None
    from .report import load_master
    try:
        return load_master(snap)
    except Exception:
        return None


def _model_price(m, args) -> float | None:
    """Live quote first, snapshot price fallback (same contract as ask)."""
    from . import analyze as az
    try:
        q = az.live_quote(m)
        if q and q.get("price"):
            return float(q["price"])
    except Exception:
        pass
    master = _model_master(args)
    if master is not None:
        row = master[(master["market"].astype(str) == m.market)
                     & (master["code"].astype(str) == str(m.code))]
        if len(row):
            from .fetch.http import num
            return num(row.iloc[0].get("price"))
    # last resort: snapshot quotes row (watchlist/funnel quotes cover
    # holdings and ex-funnel names that master.csv lacks, e.g. KO/ADBE)
    try:
        snap = report.resolve_snapshot(getattr(args, "data_dir", None))
        qf = snap / f"{m.market.lower()}_quotes.csv"
        if qf.exists():
            import pandas as pd
            qdf = pd.read_csv(qf, dtype={"code": str})
            qrow = qdf[qdf["code"].astype(str) == str(m.code)]
            if len(qrow):
                from .fetch.http import num
                return num(qrow.iloc[0].get("price"))
    except Exception:
        pass
    return None


def _model_campaign(args) -> int:
    """Full-market modeling campaign (user mandate 2026-10-04): the
    machine side — tiered queue, gather-ahead monitor, progress. The
    understanding layer stays the AI's (red line, skills/19)."""
    from .model import campaign as mc
    cmd = args.campaign_cmd

    if cmd == "init":
        try:
            mc.init(getattr(args, "data_dir", None))
        except FileNotFoundError as exc:
            print(f"campaign init failed: {exc}", file=sys.stderr)
            return 1
        p = mc.progress()
        if args.json:
            print(json.dumps(p, ensure_ascii=False, indent=2, default=str))
            return 0
        tiers = {t["tier"]: t for t in p["tiers"]}
        print(f"campaign queue -> {mc.campaign_path()}")
        print(f"  snapshot {p['snapshot']} | {p['queue_total']} targets "
              f"(holdings {tiers[1]['total']} / funnel {tiers[2]['total']} "
              f"/ market {tiers[3]['total']}) | {p['modeled']} already "
              f"modeled")
        for g in p["gaps"]:
            print(f"  gap: {g}")
        print("next: `model campaign gather -n 10` runs the machine side; "
              "`model campaign next` is the AI work queue")
        return 0

    if cmd == "status":
        p = mc.progress()
        if args.json:
            print(json.dumps(p, ensure_ascii=False, indent=2, default=str))
            return 0
        if not p.get("initialized"):
            print("no campaign under models/ — run `model campaign init`",
                  file=sys.stderr)
            return 1
        print(f"campaign @ {p['snapshot']} — {p['modeled']}/"
              f"{p['queue_total']} modeled ({p['modeled_pct']}%) | "
              f"{p['ready']} gathered-ready for the AI")
        for t in p["tiers"]:
            print(f"  tier {t['tier']} {t['label']:<9} {t['total']:>6} total"
                  f" | {t['modeled']:>5} modeled | {t['ready']:>4} ready"
                  f" | {t['pending']:>6} pending")
        if p["incomplete_dossiers"]:
            ids = p["incomplete_dossiers"]
            print(f"  incomplete dossiers: {', '.join(ids[:8])}"
                  + (" ..." if len(ids) > 8 else ""))
        if p["parked"]:
            print(f"  parked (gather failed x{mc.FAIL_MAX}): "
                  f"{', '.join(list(p['parked'])[:8])}")
        if p["next"]:
            print(f"  queue head: {', '.join(p['next'][:8])}")
        return 0

    if cmd == "next":
        rows = mc.next_targets(args.n)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        if not rows:
            print("campaign queue empty (or every target modeled)")
            return 0
        for i, r in enumerate(rows, 1):
            state = "ready" if r["gathered"] else "ungathered"
            print(f"{i:>3}. [{state:<9}] {r['id']:<12} "
                  f"{(r.get('name') or '')[:20]:<20} tier {r['tier']}")
        print("gather an ungathered target with `model gather <id>`; "
              "the dossier itself is the AI's to write")
        return 0

    if cmd == "gather":
        rep = mc.gather_batch(args.n)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        if "error" in rep:
            print(rep["error"], file=sys.stderr)
            return 1
        print(f"gathered {rep['ok']}/{rep['attempted']} "
              f"(backlog {rep['backlog']}/{rep['backlog_cap']})")
        for r in rep["results"]:
            if r["ok"]:
                detail = (f" | gaps: {'; '.join(r['gaps'])}"
                          if r.get("gaps") else "")
                print(f"  ok   {r['id']}{detail}")
            else:
                err = r.get("error") or "; ".join(r.get("gaps") or [])
                print(f"  FAIL {r['id']}: {err}")
        if rep["parked"]:
            print(f"  parked (failed x{mc.FAIL_MAX}): "
                  f"{', '.join(list(rep['parked'])[:8])}")
        return 0

    if cmd == "monitor":
        rep = mc.monitor_pass(args.n)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2,
                             default=str))
        else:
            print(rep.get("log") or rep.get("error", "monitor pass done"))
        return 0 if rep.get("ok") else 1

    raise SystemExit(f"unknown campaign subcommand {cmd}")


def cmd_model(args) -> int:
    """Financial models (2026-10-02 design): driver-based FCFF DCF +
    comps, AI-triggered at L3. models/ is LOCAL-ONLY (never pushed).
    `build` is price-sensitive -> freshness-gated like ask; fetch/show/
    set/list are not gated (historical statements / local registry)."""
    from .model import store as mst

    if args.model_cmd == "list":
        rows = mst.list_models()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        if not rows:
            print(f"no models under {mst.models_dir()}")
            return 1
        for r in rows:
            stale = " STALE(history changed)" if r["stale"] else ""
            print(f"{r['id']:<14} weighted={r['weighted_per_share']} "
                  f"upside={r['upside_pct']}% "
                  f"{str(r.get('built_at'))[:10]}{stale}")
        return 0

    if args.model_cmd == "status":
        from .model import archive as marc
        rows = marc.status()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        if not rows:
            print(f"no dossiers under {marc.store.models_dir()} — the "
                  f"modeling campaign starts with `model gather X`")
            return 1
        done = sum(1 for r in rows if r["complete"])
        print(f"dossiers: {len(rows)} | qualified (lint pass): {done}")
        for r in rows:
            mark = "OK" if r["complete"] else "INCOMPLETE"
            print(f"  {r['id']:<14} {mark:<10} {r.get('name') or ''} "
                  f"{str(r.get('updated_at'))[:10]}")
        return 0

    if args.model_cmd == "campaign":
        return _model_campaign(args)

    # build is price-sensitive -> freshness-gated BEFORE any resolution
    # (same order as cmd_ask: a FAIL gate emits nothing on stdout).
    if args.model_cmd == "build" and not _check_freshness(args):
        return 1

    m = _resolve_stock_or_exit(args.stock)

    if args.model_cmd == "gather":
        from .model import gather as mg
        peers = ([x.strip() for x in args.peers.split(",") if x.strip()]
                 if getattr(args, "peers", None) else None)
        try:
            rep = mg.gather(m.market, m.code,
                            force=getattr(args, "force", False),
                            peers=peers)
        except FileNotFoundError as exc:
            print(f"gather failed for {m.label()}: {exc}",
                  file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        print(f"{rep['id']} raw material -> {rep['raw_dir']}")
        for k, v in rep["gathered"].items():
            if v:
                print(f"  {k}: {v}")
        for g in rep["gaps"]:
            print(f"  gap: {g}")
        print(f"next: read the material, then `model write {m.label()} "
              f"...` — the understanding layer is yours, not the "
              f"machine's")
        return 0

    if args.model_cmd == "write":
        from .model import archive as marc
        updates = {}
        for pair in args.sets:
            if "=" not in pair:
                raise SystemExit(f"bad write pair {pair!r}; want "
                                 f"key=value")
            k, v = pair.split("=", 1)
            updates[k.strip()] = v.strip()
        try:
            a = marc.write_fields(m.market, m.code, updates,
                                  reason=args.reason or "")
        except (ValueError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(a, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        lint = marc.lint(a)
        if lint["complete"]:
            state = "QUALIFIED"
        else:
            state = ("INCOMPLETE — " + "; ".join(
                lint["missing"] + lint["weak_weights"]))
        print(f"dossier updated for {m.label()}: {', '.join(updates)} "
              f"({state})")
        return 0

    if args.model_cmd == "lint":
        from .model import archive as marc
        a = marc.load_archive(m.market, m.code)
        if a is None:
            print(f"no dossier for {m.label()} — `model gather` then "
                  f"`model write`", file=sys.stderr)
            return 1
        lint = marc.lint(a)
        if args.json:
            print(json.dumps(lint, ensure_ascii=False, indent=2,
                             default=str))
            return 0 if lint["complete"] else 1
        print(f"{m.label()} dossier quality bar "
              f"(info content >= annual report): "
              f"{'QUALIFIED' if lint['complete'] else 'INCOMPLETE'}")
        print(f"  text volume {lint['text_volume']} vs raw "
              f"{lint['raw_text_volume']} "
              f"(ratio {lint['text_ratio'] and round(lint['text_ratio'], 3)}"
              f", min {lint['min_ratio']})")
        for x in lint["missing"]:
            print(f"  missing: {x}")
        for x in lint["weak_weights"]:
            print(f"  weak: {x}")
        return 0 if lint["complete"] else 1

    if args.model_cmd == "fetch":
        from .model import history as mh
        if mst.load_history(m.market, m.code) and not args.force:
            print(f"history exists for {m.label()} (--force to refetch)")
            return 0
        h = mh.fetch_history(m.market, m.code)
        if h is None:
            print(f"history fetch failed for {m.label()} "
                  f"(source returned nothing; fail-closed)",
                  file=sys.stderr)
            return 1
        p = mst.save_history(h)
        if args.json:
            print(json.dumps(h, ensure_ascii=False, indent=2,
                             default=str))
        else:
            print(f"wrote {p}")
            print(f"{h['id']} {h.get('name')}: "
                  f"{len(h['years'])} years "
                  f"({h['years'][0]['fy']}..{h['years'][-1]['fy']}) "
                  f"{h['currency']}")
            for g in h.get("gaps") or []:
                print(f"  gap: {g}")
        return 0

    if args.model_cmd == "set":
        updates = {}
        for pair in args.sets:
            if "=" not in pair:
                raise SystemExit(f"bad set pair {pair!r}; want key=value")
            k, v = pair.split("=", 1)
            v = v.strip()
            updates[k.strip()] = (
                [float(x) for x in v.split(",")] if "," in v
                else float(v))
        try:
            a = mst.set_assumptions(m.market, m.code, updates,
                                    reason=args.reason or "")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(a, ensure_ascii=False, indent=2,
                             default=str))
        else:
            print(f"assumptions updated for {m.label()}: "
                  f"{', '.join(updates)}")
        return 0

    if args.model_cmd == "show":
        from .model import archive as marc
        a = marc.load_archive(m.market, m.code)
        r = mst.load_result(m.market, m.code)
        if a is None and r is None:
            print(f"no model for {m.label()} — `model gather` then "
                  f"`model write` (dossier) or `model build` (valuation)")
            return 1
        h = mst.load_history(m.market, m.code)
        stale = mst.is_stale(r, h) if r else False
        lint = marc.lint(a) if a else None
        if args.json:
            out = {"dossier": a, "lint": lint,
                   "valuation": dict(r, stale=stale) if r else None}
            print(json.dumps(out, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        if a is not None:
            mark = "QUALIFIED" if lint["complete"] else "INCOMPLETE"
            print(f"{a['id']} dossier ({str(a.get('updated_at'))[:10]}, "
                  f"{mark}) — {a.get('name') or ''}")
            fw = (a.get("business_flywheel") or {}).get("text") or ""
            print(f"  flywheel: {fw[:400] or '(empty)'}")
            cul = a.get("culture") or {}
            print(f"  culture vision: "
                  f"{(cul.get('vision') or '')[:200] or '(empty)'}")
            rd = a.get("reverse_dcf") or {}
            print(f"  reverse-DCF implied world: "
                  f"{(rd.get('implied_world') or '')[:200] or '(empty)'}")
            print(f"  my world: "
                  f"{(rd.get('my_world') or '')[:200] or '(empty)'}")
            for i, n in enumerate(a.get("world_narratives") or []):
                basis = str(n.get("weight_basis") or "")
                flag = "" if basis.strip() else " [weight NO BASIS]"
                print(f"  world[{i}] {n.get('name') or ''} "
                      f"w={n.get('weight')}: "
                      f"{str(n.get('world') or '')[:150]}{flag}")
            dims = a.get("dimensions") or {}
            if dims:
                print(f"  dimensions: {', '.join(dims)}")
            for mon in a.get("falsification_monitor") or []:
                print(f"  falsification [{mon.get('status', 'open')}]: "
                      f"{mon.get('condition')}")
            for x in lint["missing"] + lint["weak_weights"]:
                print(f"  lint: {x}")
        if r is not None:
            cur = r.get("currency") or ""
            print(f"valuation ({str(r.get('built_at'))[:10]}"
                  + (" STALE — history changed, rebuild" if stale else "")
                  + ")")
            print(f"  price {r.get('price')} {cur} | weighted "
                  f"{r.get('weighted_per_share')} {cur} | upside "
                  f"{r.get('upside_pct')}%")
            for name, s in (r.get("scenarios") or {}).items():
                print(f"    {name:<5} p={s.get('prob')}: "
                      f"{s.get('per_share')} {cur}")
            for g in r.get("gaps") or []:
                print(f"  gap: {g}")
        return 0

    if args.model_cmd == "build":
        h = mst.load_history(m.market, m.code)
        if h is None:
            print(f"no history for {m.label()} — run "
                  f"`model fetch {m.market}:{m.code}` first",
                  file=sys.stderr)
            return 1
        a = mst.load_assumptions(m.market, m.code)
        if a is None:
            a = mst.default_assumptions(m.market, m.code)
            mst.save_assumptions(a)
        from .model import engine, comps as mcomps
        price = _model_price(m, args)
        r = engine.run_model(h, a, price=price)
        r["comps"] = None
        master = _model_master(args)
        if master is not None:
            row = master[(master["market"].astype(str) == m.market)
                         & (master["code"].astype(str) == str(m.code))]
            # AI-explicit peers (gather --peers -> raw/peers.json) come
            # first: codes from the modeler's choice, values fresh from
            # the snapshot. Master.csv industry is often empty for US
            # rows, which silently degraded comps to market-cap
            # neighbors (PYPL 2026-10-05).
            peers = None
            explicit_empty = False
            pj = (mst._stock_dir(m.market, m.code) / "raw" / "peers.json")
            if pj.exists():
                try:
                    pdata = json.loads(pj.read_text(encoding="utf-8"))
                    pcodes = [str(p.get("code")) for p in
                              pdata.get("peers") or [] if p.get("code")]
                    if pdata.get("selection") == "ai-explicit" and not pcodes:
                        # the modeler looked for true comparables and the
                        # funnel universe lacks them — an empty comps table
                        # is the honest result, not a cap-neighbor fallback
                        explicit_empty = True
                    elif pcodes:
                        sel = master[(master["market"].astype(str)
                                      == m.market)
                                     & (master["code"].astype(str)
                                        .isin(pcodes))].copy()
                        if len(sel):
                            sel["_ord"] = sel["code"].astype(str).map(
                                {c: i for i, c in enumerate(pcodes)})
                            peers = sel.sort_values("_ord").drop(
                                columns=["_ord"])
                except (ValueError, OSError, KeyError):
                    peers = None
            if peers is None and not explicit_empty:
                industry = (row.iloc[0].get("industry")
                            if len(row) else None)
                peers = mcomps.select_peers(master, m.market, m.code,
                                            industry)
            if len(row) and peers is not None:
                table = mcomps.comps_table(peers)
                r["comps"] = {**table,
                              "implied": mcomps.implied_range(
                                  row.iloc[0], table["medians"])}
        mst.save_result(r)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2,
                             default=str))
            return 0
        cur = r.get("currency") or ""
        print(f"{r['id']} 模型 ({str(r.get('built_at'))[:10]}, "
              f"data-as-of history {h['years'][-1]['fy']})")
        print(f"加权内在价值 {r.get('weighted_per_share')} {cur} vs "
              f"现价 {price} {cur} -> upside {r.get('upside_pct')}%")
        for name, s in (r.get("scenarios") or {}).items():
            print(f"  {name:<5} p={s.get('prob')}: "
                  f"{s.get('per_share')} {cur}")
        if r.get("comps") and r["comps"].get("implied"):
            imp = r["comps"]["implied"]
            print(f"comps 隐含区间 [{imp.get('low')}, "
                  f"{imp.get('high')}] {cur} (中位 {imp.get('mid')})")
        for g in r.get("gaps") or []:
            print(f"  gap: {g}")
        return 0

    raise SystemExit(f"unknown model subcommand {args.model_cmd}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    # Ensure registry is populated before listing strategy choices
    from .strategy import registry, presets, masters, horizons  # noqa: F401
    from .strategy.registry import list_horizons, list_strategies
    from . import users as _users
    _users.register_user_strategies()  # kind="user" strategies from files
    strategy_ids = [s.id for s in list_strategies()]
    horizon_ids = [h.id for h in list_horizons()]

    parser = argparse.ArgumentParser(
        prog="value_genie", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("fetch", help="fetch market data into a snapshot")
    pf.add_argument("--markets", default="A,HK,US", metavar="A,HK,US",
                    help="comma-separated markets to fetch (default: all)")
    pf.add_argument("--refresh", action="store_true",
                    help="refetch everything, ignoring cached data")
    pf.add_argument("--data-dir", default=None, help="data directory")
    pf.set_defaults(func=cmd_fetch)

    ps = sub.add_parser("screen", help="screen a snapshot and rank stocks")
    ps.add_argument("--snapshot", default=None, metavar="YYYYMMDD",
                    help="snapshot date (default: latest)")
    ps.add_argument("--strategy", default=None,
                    choices=strategy_ids,
                    help="strategy id (presets + masters; "
                         "see `strategy list`)")
    ps.add_argument("--preset", default=config.DEFAULT_PRESET,
                    help="(legacy alias for --strategy; default: "
                         f"{config.DEFAULT_PRESET})")
    ps.add_argument("--horizon", default=None, choices=horizon_ids,
                    help="holding-period lens: ultrashort|short|mid|long "
                         "(see `horizon list`)")
    ps.add_argument("--set", nargs="*", metavar="PILLAR=W",
                    help="custom weights, e.g. value=0.4 growth=0.2"
                         " (overrides --strategy)")
    ps.add_argument("--top", type=int, default=config.DEFAULT_TOP_N,
                    help=f"result count (default: {config.DEFAULT_TOP_N})")
    ps.add_argument("--markets", default=None, metavar="A,HK,US",
                    help="markets to include (default: all)")
    ps.add_argument("--data-dir", default=None, help="data directory")
    ps.add_argument("--out-dir", default=None, help="output directory")
    ps.add_argument("--json", action="store_true",
                    help="pure-JSON stdout (full precision, no file "
                         "exports)")
    ps.set_defaults(func=cmd_screen)

    pmv = sub.add_parser(
        "masters-vote",
        help="QMF L1/L2: wide candidate pool + veto annotations (v2); "
             "quant vetoes, AI selects")
    pmv.add_argument("--snapshot", default=None, metavar="YYYYMMDD",
                     help="snapshot date (default: latest)")
    pmv.add_argument("--top", type=int, default=None, metavar="N",
                     help="legacy ranked shortlist of N with the live "
                          "consensus-EPS pass (default: wide pool, live "
                          "pass pending)")
    pmv.add_argument("--check", nargs="+", default=None,
                     metavar="MARKET:CODE",
                     help="run the live cycle-trap pass on an AI-chosen "
                          "shortlist (e.g. --check A:600519 HK:00998)")
    pmv.add_argument("--markets", default=None, metavar="A,HK,US",
                     help="markets to include (default: all)")
    pmv.add_argument("--no-live", action="store_true",
                     help="skip the live consensus-EPS divergence pass")
    pmv.add_argument("--thesis", action="append", metavar="THESIS_ID",
                     help="inject a thesis registry pool (repeatable); "
                          "members are marked thesis:<id>, gates "
                          "unchanged — see `thesis list`")
    pmv.add_argument("--horizon", choices=["short", "ultrashort"],
                     default=None,
                     help="tactical mode (D4): floor = real business "
                          "(core_business >= 50) + weekly uptrend + no "
                          "veto; pullback sweet spot annotated; DCF "
                          "display-only with mandatory discipline lines")
    pmv.add_argument("--data-dir", default=None, help="data directory")
    pmv.add_argument("--no-check", action="store_true",
                     help="skip the freshness gate (testing only)")
    pmv.add_argument("--json", action="store_true",
                     help="pure-JSON stdout (full precision, no banners)")
    pmv.set_defaults(func=cmd_masters_vote)

    psl = sub.add_parser("strategy", help="list registered strategies")
    # accept both bare `strategy` and the documented `strategy list`
    psl_sub = psl.add_subparsers(dest="cmd")
    psl_sub.add_parser("list", help="list all strategies (default)")
    psl.set_defaults(func=cmd_strategy_list)

    phz = sub.add_parser("horizon", help="list registered horizons")
    phz_sub = phz.add_subparsers(dest="cmd")
    phz_sub.add_parser("list", help="list all horizons (default)")
    phz.set_defaults(func=cmd_horizon_list)

    psrc = sub.add_parser("source", help="list registered data sources")
    psrc_sub = psrc.add_subparsers(dest="cmd")
    psrc_sub.add_parser("list", help="list all data sources (default)")
    psrc.set_defaults(func=cmd_source_list)

    # -- user / holdings / recommend -------------------------------
    pu = sub.add_parser("user", help="manage user profiles (style)")
    pu_sub = pu.add_subparsers(dest="user_cmd", required=True)
    pu_create = pu_sub.add_parser("create", help="create a user")
    pu_create.add_argument("user_id")
    pu_create.add_argument("--name", default="", help="display name")
    pu_create.add_argument("--horizon", default="",
                           choices=horizon_ids,
                           help="preferred holding period")
    pu_login = pu_sub.add_parser("login",
                                 help="point the session at a user")
    pu_login.add_argument("user_id")
    pu_sub.add_parser("logout", help="drop the session pointer")
    pu_whoami = pu_sub.add_parser(
        "whoami", help="current session user + all users")
    pu_whoami.add_argument("--json", action="store_true",
                           help="machine-readable JSON output")
    pu_sub.add_parser("list", help="list all users")
    pu_show = pu_sub.add_parser("show", help="show one user's profile")
    pu_show.add_argument("user_id", nargs="?", default=None,
                         help="default: session current user")
    pu_style = pu_sub.add_parser("set-style", help="set the user's style")
    pu_style.add_argument("user_id", nargs="?", default=None,
                          help="default: session current user")
    pu_style.add_argument("--weight", action="append", default=None,
                          metavar="PILLAR=W",
                          help="pillar weight, e.g. value=0.4 (repeatable; "
                               "overrides individual pillars, then "
                               "renormalizes)")
    pu_style.add_argument("--gate", action="append", default=None,
                          metavar="COL>=V",
                          help="hard gate, e.g. roe>=15 debt_ratio<=60 "
                               "volatility pctl>=60 (repeatable; replaces)")
    pu_style.add_argument("--clear-gates", action="store_true",
                          help="drop all gates")
    pu_style.add_argument("--base", default=None, metavar="STRATEGY",
                          help="start from an existing strategy's "
                               "weights/gates/horizon, then apply overrides")
    pu_style.add_argument("--horizon", default=None, choices=horizon_ids,
                          help="preferred holding period")
    pu_style.add_argument("--clear-horizon", action="store_true",
                          help="clear the preferred horizon (flexible)")
    pu.set_defaults(func=cmd_user)

    ph = sub.add_parser("holding", help="manage holdings for a user")
    ph_sub = ph.add_subparsers(dest="holding_cmd", required=True)
    ph_add = ph_sub.add_parser("add", help="add a position")
    ph_add.add_argument("user_id", nargs="?", default=None,
                        help="default: session current user")
    ph_add.add_argument("stock", nargs="?", default=None,
                        help="stock name/code/ticker to resolve")
    ph_add.add_argument("--qty", type=float, required=True)
    ph_add.add_argument("--cost", type=float, required=True,
                        help="per-share cost")
    ph_add.add_argument("--opened", default=None, metavar="YYYY-MM-DD")
    ph_upd = ph_sub.add_parser("update", help="update a position")
    ph_upd.add_argument("user_id", nargs="?", default=None,
                        help="default: session current user")
    ph_upd.add_argument("stock", nargs="?", default=None)
    ph_upd.add_argument("--qty", type=float, default=None)
    ph_upd.add_argument("--cost", type=float, default=None)
    ph_upd.add_argument("--name", default=None,
                        help="display name override (e.g. ETFs not in "
                             "snapshot name search)")
    ph_upd.add_argument("--opened", default=None, metavar="YYYY-MM-DD",
                        help="set/clear the opened date ('' clears)")
    ph_rm = ph_sub.add_parser("remove", help="remove a position")
    ph_rm.add_argument("user_id", nargs="?", default=None,
                       help="default: session current user")
    ph_rm.add_argument("stock", nargs="?", default=None)
    ph_ls = ph_sub.add_parser("list", help="holdings with live P&L")
    ph_ls.add_argument("user_id", nargs="?", default=None,
                       help="default: session current user")
    ph_ls.add_argument("--snapshot", default=None, metavar="YYYYMMDD")
    ph_ls.add_argument("--data-dir", default=None, help="data directory")
    ph_ls.add_argument("--no-check", action="store_true",
                       help="skip freshness gate (for automated pipelines)")
    ph_ls.add_argument("--json", action="store_true",
                       help="pure-JSON stdout (full precision)")
    ph.set_defaults(func=cmd_holding)

    pr = sub.add_parser(
        "recommend", help="daily picks under user style + holdings health")
    pr.add_argument("--user", default=None,
                    help="user id (default: session current user)")
    pr.add_argument("--strategy", default=None, choices=strategy_ids,
                    help="override the user's style (default: user style)")
    pr.add_argument("--horizon", default=None, choices=horizon_ids,
                    help="override the user's preferred horizon")
    pr.add_argument("--top", type=int, default=10,
                    help="candidate count (default: 10)")
    pr.add_argument("--markets", default=None, metavar="A,HK,US",
                    help="markets to include (default: all)")
    pr.add_argument("--snapshot", default=None, metavar="YYYYMMDD")
    pr.add_argument("--data-dir", default=None, help="data directory")
    pr.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    pr.add_argument("--json", action="store_true",
                    help="pure-JSON stdout (full precision)")
    pr.set_defaults(func=cmd_recommend)

    # -- trading (AI virtual portfolio) ------------------------------
    pt = sub.add_parser(
        "trade", help="AI virtual portfolio: multi-season paper trading")
    pt_sub = pt.add_subparsers(dest="trade_cmd", required=True)

    pt_se = pt_sub.add_parser("season", help="manage seasons")
    pt_se_sub = pt_se.add_subparsers(dest="season_cmd", required=True)
    pt_new = pt_se_sub.add_parser("new", help="create a season")
    pt_new.add_argument("season_id")
    pt_new.add_argument("--name", default="", help="display name")
    pt_new.add_argument("--base", default="USD", metavar="CNY|HKD|USD",
                        help="base currency (default: USD)")
    pt_new.add_argument("--capital", type=float, required=True,
                        help="initial capital in base currency")
    pt_new.add_argument("--markets", default="US,HK", metavar="A,HK,US",
                        help="allowed markets (default: US,HK)")
    pt_new.add_argument("--fx-spread", type=float, default=None,
                        help="FX spread, e.g. 0.003 (default: "
                             f"{config.TRADE_FX_SPREAD})")
    pt_se_sub.add_parser("list", help="list all seasons")
    pt_show = pt_se_sub.add_parser("show", help="show one season")
    pt_show.add_argument("season_id")
    pt_show.add_argument("--json", action="store_true")
    pt_rule = pt_se_sub.add_parser("rule", help="change allowed markets")
    pt_rule.add_argument("season_id")
    pt_rule.add_argument("--markets", required=True, metavar="A,HK,US")
    for act, help_txt in (
            ("close", "stop trading, keep history"),
            ("pause", "temporarily stop trading"),
            ("resume", "reactivate a paused season")):
        p_act = pt_se_sub.add_parser(act, help=help_txt)
        p_act.add_argument("season_id")
    p_del = pt_se_sub.add_parser("delete", help="delete a season + history")
    p_del.add_argument("season_id")
    p_del.add_argument("--confirm", action="store_true",
                       help="required: deleting removes all fills/nav/"
                            "journal history")
    pt_se.set_defaults(func=cmd_trade)

    def _trade_common(p):
        p.add_argument("--snapshot", default=None, metavar="YYYYMMDD")
        p.add_argument("--data-dir", default=None, help="data directory")
        p.add_argument("--no-check", action="store_true",
                       help="skip freshness gate (for automated pipelines)")
        p.add_argument("--json", action="store_true",
                       help="pure-JSON stdout (full precision)")

    pt_buy = pt_sub.add_parser("buy", help="market buy at live price")
    pt_buy.add_argument("season_id")
    pt_buy.add_argument("stock", help="name/code/ticker to resolve")
    pt_buy.add_argument("--qty", type=float, required=True)
    pt_buy.add_argument("--note", default=None,
                        help="AI's trade rationale (recorded in the fill)")
    pt_buy.add_argument("--lot", type=int, default=None,
                        help="HK board lot override when F10 is "
                             "unreachable")
    _trade_common(pt_buy)

    pt_sell = pt_sub.add_parser("sell", help="market sell at live price")
    pt_sell.add_argument("season_id")
    pt_sell.add_argument("stock")
    pt_sell.add_argument("--qty", type=float, required=True)
    pt_sell.add_argument("--note", default=None)
    _trade_common(pt_sell)

    pt_fx = pt_sub.add_parser("fx", help="convert settled cash")
    pt_fx.add_argument("season_id")
    pt_fx.add_argument("pair", metavar="FROM->TO",
                       help="e.g. USD->HKD")
    pt_fx.add_argument("--amount", type=float, required=True)
    _trade_common(pt_fx)

    pt_cash = pt_sub.add_parser("cash", help="deposit/withdraw")
    pt_cash.add_argument("season_id")
    pt_cash.add_argument("action", choices=["deposit", "withdraw"])
    pt_cash.add_argument("--amount", type=float, required=True)
    pt_cash.add_argument("--currency", required=True,
                         metavar="CNY|HKD|USD")
    pt_cash.add_argument("--note", default=None,
                         help="e.g. 'living costs' for withdrawals")
    _trade_common(pt_cash)

    pt_nav = pt_sub.add_parser("nav", help="mark-to-market snapshot")
    pt_nav.add_argument("season_id")
    _trade_common(pt_nav)

    pt_jr = pt_sub.add_parser("journal", help="write/show review journal")
    pt_jr.add_argument("season_id")
    pt_jr.add_argument("--text", default=None,
                       help="journal entry (why money was made/lost, "
                            "what to repeat/avoid)")
    pt_jr.add_argument("--show", action="store_true",
                       help="print recent entries instead of writing")
    pt_jr.add_argument("--last", type=int, default=5,
                       help="entries to show (default: 5)")
    _trade_common(pt_jr)

    pt_st = pt_sub.add_parser("status", help="all active seasons overview")
    _trade_common(pt_st)
    pt.set_defaults(func=cmd_trade)

    pa = sub.add_parser("ask", help="analyze one stock (verdict first)")
    pa.add_argument("query", help="stock name, code or ticker (Chinese ok)")
    pa.add_argument("--evidence", action="store_true",
                    help="print the full metric/percentile tables")
    pa.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    pa.add_argument("--horizon", default=None, choices=horizon_ids,
                    help="single-horizon view (default: all four)")
    pa.add_argument("--data-dir", default=None, help="data directory")
    pa.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    pa.set_defaults(func=cmd_ask)

    pi = sub.add_parser("intel", help="per-stock intelligence report (舆情)")
    pi.add_argument("query", help="stock name, code or ticker (Chinese ok)")
    pi.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    pi.add_argument("--data-dir", default=None, help="data directory")
    pi.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    pi.set_defaults(func=cmd_intel)

    pc = sub.add_parser("compare", help="compare 2+ stocks side by side")
    pc.add_argument("stocks", nargs="+", help="names/codes to compare")
    pc.add_argument("--data-dir", default=None, help="data directory")
    pc.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    pc.add_argument("--json", action="store_true",
                    help="pure-JSON stdout (full precision)")
    pc.set_defaults(func=cmd_compare)

    po = sub.add_parser("overview", help="market digest from latest snapshot")
    po.add_argument("--markets", default=None, metavar="A,HK,US",
                    help="markets to include (default: all)")
    po.add_argument("--top", type=int, default=10,
                    help="top names per market (default: 10)")
    po.add_argument("--data-dir", default=None, help="data directory")
    po.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    po.add_argument("--json", action="store_true",
                    help="pure-JSON stdout (full precision)")
    po.set_defaults(func=cmd_overview)

    pdoc = sub.add_parser("doctor", help="check snapshot health/freshness")
    pdoc.add_argument("--data-dir", default=None, help="data directory")
    pdoc.add_argument("--json", action="store_true",
                      help="pure-JSON stdout (status + checks + action)")
    pdoc.set_defaults(func=cmd_doctor)

    psk = sub.add_parser("skill", help="inspect / evolve AI skills")
    psk_sub = psk.add_subparsers(dest="skill_cmd", required=True)
    psk_sub.add_parser("list", help="list all skills")
    p_show = psk_sub.add_parser("show", help="print one skill file")
    p_show.add_argument("skill_id")
    p_note = psk_sub.add_parser(
        "note", help="append a field note (AI self-refinement)")
    p_note.add_argument("skill_id")
    p_note.add_argument("text", help="one concrete lesson line")
    p_edit = psk_sub.add_parser("edit", help="edit triggers (human path)")
    p_edit.add_argument("skill_id")
    p_edit.add_argument("--add-trigger", action="append", default=None,
                        metavar="T", help="trigger to add (repeatable)")
    p_edit.add_argument("--remove-trigger", action="append", default=None,
                        metavar="T", help="trigger to remove (repeatable)")
    psk.set_defaults(func=cmd_skill)

    ptw = sub.add_parser(
        "tower", help="cognitive tower (认知巴别塔): philosophy bricks")
    ptw_sub = ptw.add_subparsers(dest="tower_cmd", required=True)
    from . import tower as _tw
    ptw_list = ptw_sub.add_parser("list", help="list bricks")
    ptw_list.add_argument("--status", default=None, choices=_tw.STATUSES,
                          help="filter by cognitive status")
    ptw_list.add_argument("--tag", default=None,
                          help="filter by tag (exact match)")
    ptw_list.add_argument("--kind", default=None,
                          choices=["book", "master", "conversation", "ai"],
                          help="filter by source prefix")
    ptw_list.add_argument("--json", action="store_true",
                          help="pure-JSON stdout")
    ptw_show = ptw_sub.add_parser("show", help="print one brick file")
    ptw_show.add_argument("brick_id")
    ptw_show.add_argument("--json", action="store_true")
    ptw_add = ptw_sub.add_parser("add", help="add a new brick")
    ptw_add.add_argument("brick_id")
    ptw_add.add_argument("--title", required=True)
    ptw_add.add_argument("--statement", required=True,
                         help="one-sentence distillation")
    ptw_add.add_argument("--status", default="observation",
                         choices=_tw.STATUSES,
                         help="cognitive status (default: observation)")
    ptw_add.add_argument("--source", required=True,
                         help="book:书名 | master:名 | conversation:YYYY-MM-DD | ai")
    ptw_add.add_argument("--tag", action="append", default=None,
                         metavar="T", help="tag to add (repeatable)")
    ptw_add.add_argument("--link", action="append", default=None,
                         metavar="TYPE:ID",
                         help="link as type:target-id (repeatable)")
    ptw_add.add_argument("--stdin-body", action="store_true",
                         help="read the brick body from stdin")
    ptw_add.add_argument("--json", action="store_true")
    ptw_note = ptw_sub.add_parser("note", help="append a field note")
    ptw_note.add_argument("brick_id")
    ptw_note.add_argument("text", help="one concrete insight line")
    ptw_link = ptw_sub.add_parser("link", help="add a link to a brick")
    ptw_link.add_argument("brick_id")
    ptw_link.add_argument("link", metavar="TYPE:ID",
                          help="derives-from|refines|contradicts|"
                               "applies-to|tension :target-id")
    ptw_set = ptw_sub.add_parser("set", help="status migration / edits")
    ptw_set.add_argument("brick_id")
    ptw_set.add_argument("--status", default=None, choices=_tw.STATUSES,
                         help="new status (requires --reason)")
    ptw_set.add_argument("--reason", default=None,
                         help="promotion rationale / refutation evidence")
    ptw_set.add_argument("--add-tag", action="append", default=None,
                         metavar="T", help="tag to add (repeatable)")
    ptw_set.add_argument("--drop-tag", action="append", default=None,
                         metavar="T", help="tag to drop (repeatable)")
    ptw_set.add_argument("--stdin-body", action="store_true",
                         help="replace the body from stdin")
    ptw_set.add_argument("--json", action="store_true")
    ptw_search = ptw_sub.add_parser("search", help="substring search")
    ptw_search.add_argument("query")
    ptw_search.add_argument("--json", action="store_true")
    ptw_stats = ptw_sub.add_parser("stats",
                                   help="cognitive altitude report")
    ptw_stats.add_argument("--json", action="store_true")
    ptw_seed = ptw_sub.add_parser("seed", help="seed the tower (idempotent)")
    ptw_seed.add_argument("--dry-run", action="store_true",
                          help="preview without writing")
    ptw_seed.add_argument("--json", action="store_true")
    ptw.set_defaults(func=cmd_tower)

    pth = sub.add_parser(
        "thesis", help="thesis registry (论点喂池): tower-fed machine "
                       "pools for masters-vote --thesis")
    pth_sub = pth.add_subparsers(dest="thesis_cmd", required=True)
    from . import thesis as _th
    pth_list = pth_sub.add_parser("list", help="list theses")
    pth_list.add_argument("--status", default=None, choices=_th.STATUSES,
                          help="filter by status")
    pth_list.add_argument("--json", action="store_true",
                          help="pure-JSON stdout")
    pth_show = pth_sub.add_parser("show", help="show one thesis")
    pth_show.add_argument("thesis_id")
    pth_show.add_argument("--discover", action="store_true",
                          help="list industry-hint candidates not yet "
                               "members (from the snapshot, read-only)")
    pth_show.add_argument("--snapshot", default=None, metavar="YYYYMMDD",
                          help="snapshot date for --discover "
                               "(default: latest)")
    pth_show.add_argument("--data-dir", default=None)
    pth_show.add_argument("--json", action="store_true")
    pth_add = pth_sub.add_parser("add", help="add a new thesis")
    pth_add.add_argument("thesis_id")
    pth_add.add_argument("--name", default=None)
    pth_add.add_argument("--brick", default=None,
                         help="lineage: source tower brick id")
    pth_add.add_argument("--statement", default=None,
                         help="one-sentence machine assertion")
    pth_add.add_argument("--reason", default=None,
                         help="why the machine is in its issuance window")
    pth_add.add_argument("--feature", action="append", default=None,
                         metavar="F",
                         help="issuance-window feature (repeatable)")
    pth_add.add_argument("--falsification", action="append",
                         default=None, metavar="F",
                         help="kill-set item (repeatable)")
    pth_add.add_argument("--member", action="append", default=None,
                         metavar="MARKET:CODE[:NAME]",
                         help="machine component (repeatable)")
    pth_add.add_argument("--industry", action="append", default=None,
                         metavar="MARKET:关键词",
                         help="industry hint for --discover (repeatable)")
    pth_add.add_argument("--json", action="store_true")
    pth_amend = pth_sub.add_parser("amend", help="edit members/features")
    pth_amend.add_argument("thesis_id")
    pth_amend.add_argument("--add-member", action="append", default=None,
                           metavar="MARKET:CODE[:NAME]")
    pth_amend.add_argument("--drop-member", action="append",
                           default=None, metavar="MARKET:CODE")
    pth_amend.add_argument("--feature", action="append", default=None,
                           metavar="F")
    pth_amend.add_argument("--falsification", action="append",
                           default=None, metavar="F")
    pth_amend.add_argument("--industry", action="append", default=None,
                           metavar="MARKET:关键词")
    pth_amend.add_argument("--reason", default=None,
                           help="replace the issuance-window reason")
    pth_amend.add_argument("--json", action="store_true")
    pth_retire = pth_sub.add_parser(
        "retire", help="retire a thesis (falsifier fired / window "
                       "closed; never deleted)")
    pth_retire.add_argument("thesis_id")
    pth_retire.add_argument("--reason", required=True,
                            help="which falsifier fired, or why the "
                                 "window closed")
    pth_rm = pth_sub.add_parser("remove", help="delete a thesis file "
                                               "(typos only — falsified "
                                               "theses use `retire`)")
    pth_rm.add_argument("thesis_id")
    pth.set_defaults(func=cmd_thesis)

    ppf = sub.add_parser(
        "profile", help="company profiles (Phase 5): raw source text "
                        "(data/, cleanable) + AI-distilled assessments "
                        "(profiles/, LOCAL-ONLY — never pushed)")
    ppf_sub = ppf.add_subparsers(dest="profile_cmd", required=True)
    ppf_list = ppf_sub.add_parser("list", help="list distilled assessments")
    ppf_list.add_argument("--json", action="store_true")
    ppf_show = ppf_sub.add_parser(
        "show", help="show raw source text + assessment (L3 read entry)")
    ppf_show.add_argument("stock")
    ppf_show.add_argument("--json", action="store_true")
    ppf_fetch = ppf_sub.add_parser(
        "fetch", help="fetch the raw profile for one stock (on-demand)")
    ppf_fetch.add_argument("stock")
    ppf_assess = ppf_sub.add_parser(
        "assess", help="write the AI distillation (the only writer; "
                       "feeds the culture core via the D3 hook)")
    ppf_assess.add_argument("stock")
    ppf_assess.add_argument("--business-score", type=float, default=None)
    ppf_assess.add_argument("--culture-score", type=float, default=None)
    ppf_assess.add_argument("--moat-type", default=None)
    ppf_assess.add_argument("--lifecycle", default=None,
                            help="machine lifecycle stage")
    ppf_assess.add_argument("--founder-led", choices=["yes", "no"],
                            default=None)
    ppf_assess.add_argument("--benfen", action="append", default=None,
                            metavar="E", help="behavior-level 本分证据 "
                                              "(repeatable)")
    ppf_assess.add_argument("--business-arg", default=None)
    ppf_assess.add_argument("--culture-arg", default=None)
    ppf_assess.add_argument("--dcf-arg", default=None)
    ppf_assess.add_argument("--verdict", default=None)
    ppf_assess.add_argument("--agent", default=None,
                            help="distilling agent id (e.g. kimi-k3)")
    ppf_assess.add_argument("--json", action="store_true")
    ppf_status = ppf_sub.add_parser("status", help="coverage + staleness")
    ppf_status.add_argument("--json", action="store_true")
    ppf.set_defaults(func=cmd_profile)

    pmo = sub.add_parser(
        "model", help="financial models: driver-based FCFF DCF + comps "
                      "(models/, LOCAL-ONLY — never pushed; AI-triggered "
                      "at L3 per skills/19)")
    pmo_sub = pmo.add_subparsers(dest="model_cmd", required=True)
    pmo_fetch = pmo_sub.add_parser(
        "fetch", help="fetch multi-year statement history (on-demand)")
    pmo_fetch.add_argument("stock")
    pmo_fetch.add_argument("--force", action="store_true",
                           help="refetch even if history exists")
    pmo_fetch.add_argument("--json", action="store_true")
    pmo_build = pmo_sub.add_parser(
        "build", help="run the model: scenarios + sensitivity + comps "
                      "(freshness-gated, price-sensitive)")
    pmo_build.add_argument("stock")
    pmo_build.add_argument("--data-dir", default=None)
    pmo_build.add_argument("--no-check", action="store_true")
    pmo_build.add_argument("--json", action="store_true")
    pmo_show = pmo_sub.add_parser("show", help="show the last result")
    pmo_show.add_argument("stock")
    pmo_show.add_argument("--json", action="store_true")
    pmo_set = pmo_sub.add_parser(
        "set", help="adjust assumptions (dotted key=value, repeatable)")
    pmo_set.add_argument("stock")
    pmo_set.add_argument("sets", nargs="+", metavar="KEY=VALUE",
                         help="e.g. base.revenue_growth=0.2,0.18 wacc=0.11")
    pmo_set.add_argument("--reason", default=None,
                         help="mandatory: why this change (changelog)")
    pmo_set.add_argument("--json", action="store_true")
    pmo_list = pmo_sub.add_parser("list", help="coverage + staleness")
    pmo_list.add_argument("--json", action="store_true")
    # --- AI modeling workbench (2026-10-03): machine gathers, AI writes ---
    pmo_gather = pmo_sub.add_parser(
        "gather", help="gather raw material for one company into "
                       "models/<mkt>/<code>/raw/ (full-history statements "
                       "+ intel + profile text + peers)")
    pmo_gather.add_argument("stock")
    pmo_gather.add_argument("--force", action="store_true",
                            help="regather even if raw exists")
    pmo_gather.add_argument(
        "--peers", default=None, metavar="CODES",
        help="AI-chosen comparables, comma-separated (e.g. "
             "688256,688041) — for targets absent from master.csv or "
             "when the modeler knows the true peer set")
    pmo_gather.add_argument("--json", action="store_true")
    pmo_write = pmo_sub.add_parser(
        "write", help="write the understanding layer (model.json): "
                      "dotted key=value, repeatable; value '@file' loads a "
                      "file (.json parsed) — --reason mandatory")
    pmo_write.add_argument("stock")
    pmo_write.add_argument("sets", nargs="+", metavar="KEY=VALUE",
                           help="e.g. business_flywheel.text=@flywheel.md "
                                "world_narratives=@worlds.json")
    pmo_write.add_argument("--reason", default=None,
                           help="mandatory: why this write (changelog)")
    pmo_write.add_argument("--json", action="store_true")
    pmo_lint = pmo_sub.add_parser(
        "lint", help="quality bar: is the dossier's information content "
                     ">= the annual report's?")
    pmo_lint.add_argument("stock")
    pmo_lint.add_argument("--json", action="store_true")
    pmo_status = pmo_sub.add_parser(
        "status", help="modeling coverage across the whole market")
    pmo_status.add_argument("--json", action="store_true")
    # --- full-market campaign (2026-10-04): queue + gather-ahead monitor ---
    pmo_camp = pmo_sub.add_parser(
        "campaign", help="full-market modeling campaign: tiered queue, "
                         "gather-ahead monitor and progress — the machine "
                         "side only (the dossier stays the AI's)")
    pmo_camp_sub = pmo_camp.add_subparsers(dest="campaign_cmd",
                                           required=True)
    pc_init = pmo_camp_sub.add_parser(
        "init", help="(re)build the tiered queue: holdings -> funnel -> "
                     "market (industry by industry)")
    pc_init.add_argument("--data-dir", default=None)
    pc_init.add_argument("--json", action="store_true")
    pc_status = pmo_camp_sub.add_parser(
        "status", help="progress: modeled / gathered-ready / pending "
                       "per tier")
    pc_status.add_argument("--json", action="store_true")
    pc_next = pmo_camp_sub.add_parser(
        "next", help="the AI work queue: next N unmodeled targets")
    pc_next.add_argument("-n", type=int, default=10)
    pc_next.add_argument("--json", action="store_true")
    pc_gather = pmo_camp_sub.add_parser(
        "gather", help="batch-gather the next N unmodeled targets — the "
                       "hourly monitor's job (hands, never the modeler)")
    pc_gather.add_argument("-n", type=int, default=10)
    pc_gather.add_argument("--json", action="store_true")
    pc_monitor = pmo_camp_sub.add_parser(
        "monitor", help="one unattended hourly pass: gather top-up + "
                        "progress log + self-retire on completion (the "
                        "scheduled-task entry point; hands only)")
    pc_monitor.add_argument("-n", type=int, default=20)
    pc_monitor.add_argument("--json", action="store_true")
    pmo.set_defaults(func=cmd_model)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
