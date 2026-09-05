"""Command-line interface: fetch market data, screen snapshots, analyze.

Usage:
    python -m value_genie fetch [--markets A,HK,US] [--refresh]
    python -m value_genie screen [--strategy balanced|buffett|garp|...]
                                 [--set value=0.4] [--top 20]
                                 [--markets A,HK] [--snapshot DATE]
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
from pathlib import Path

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


def cmd_user(args) -> int:
    from . import users as usr
    if args.user_cmd == "create":
        try:
            u = usr.create_user(args.user_id, name=args.name,
                                horizon=args.horizon or "")
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(f"created user {u.id} ({u.name}) -> {usr.user_path(u.id)}")
        return 0

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
        u, _ = _load_user_or_exit(args.user_id)
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
            u = usr.set_style(args.user_id, weights=weights, gates=gates,
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
        print(f"resolved: {m.label()} (also matched: {others})")
    return m


def cmd_holding(args) -> int:
    from . import users as usr
    if args.holding_cmd == "add":
        try:
            user = usr.load_user(args.user_id)
        except FileNotFoundError:
            try:
                user = usr.create_user(args.user_id, name=args.user_id)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
            print(f"created user {user.id} ({usr.user_path(user.id)})")
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
        user, _ = _load_user_or_exit(args.user_id)
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
        user, _ = _load_user_or_exit(args.user_id)
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
        user, _ = _load_user_or_exit(args.user_id)
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
            args.user, data_dir=args.data_dir, snapshot=args.snapshot,
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

    if cmd == "dashboard":
        if not _check_freshness(args):
            return 1
        _season_or_exit(args.season_id)
        try:
            path, text = tr.write_dashboard(args.season_id,
                                            snap_dir=_snap())
        except tr.TradeError as exc:
            print(f"[DASHBOARD FAILED] {exc}", file=sys.stderr)
            return 1
        if args.json:
            season = tr.load_season(args.season_id)
            entry = season["nav_history"][-1]
            print(tr.to_json(tr._summary_from(season, entry)))
        else:
            print(f"wrote {path}")
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
    import sys
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
    matches = resolve_stock(args.query)
    if not matches:
        print(f"no match for {args.query!r}; try a full name or code")
        return 2
    m = matches[0]
    if len(matches) > 1:
        others = ", ".join(x.label() for x in matches[1:4])
        print(f"resolved: {m.label()} (also matched: {others})")
    if args.horizon:
        result = az.analyze_stock(m, horizon=args.horizon)
    else:
        result = az.analyze_stock(m)
    if args.json:
        print(az.to_json(result))
    elif args.evidence:
        print(az.render_evidence(result))
    else:
        print(az.render_brief(result))
    return 0


def cmd_compare(args) -> int:
    if not _check_freshness(args):
        return 1
    from . import analyze as az
    from .resolve import resolve as resolve_stock
    matches = []
    for q in args.stocks:
        ms = resolve_stock(q)
        if not ms:
            print(f"no match for {q!r}; try a full name or code")
            return 2
        matches.append(ms[0])
    # drop duplicate resolutions
    seen, uniq = set(), []
    for m in matches:
        if (m.market, m.code) not in seen:
            seen.add((m.market, m.code))
            uniq.append(m)
    df = az.compare_stocks(uniq)
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
    pu_create.add_argument("--horizon", default=None, choices=horizon_ids,
                           help="preferred holding period")
    pu_sub.add_parser("list", help="list all users")
    pu_show = pu_sub.add_parser("show", help="show one user's profile")
    pu_show.add_argument("user_id")
    pu_style = pu_sub.add_parser("set-style", help="set the user's style")
    pu_style.add_argument("user_id")
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
    ph_add.add_argument("user_id")
    ph_add.add_argument("stock", help="stock name/code/ticker to resolve")
    ph_add.add_argument("--qty", type=float, required=True)
    ph_add.add_argument("--cost", type=float, required=True,
                        help="per-share cost")
    ph_add.add_argument("--opened", default=None, metavar="YYYY-MM-DD")
    ph_upd = ph_sub.add_parser("update", help="update a position")
    ph_upd.add_argument("user_id")
    ph_upd.add_argument("stock")
    ph_upd.add_argument("--qty", type=float, default=None)
    ph_upd.add_argument("--cost", type=float, default=None)
    ph_upd.add_argument("--name", default=None,
                        help="display name override (e.g. ETFs not in "
                             "snapshot name search)")
    ph_upd.add_argument("--opened", default=None, metavar="YYYY-MM-DD",
                        help="set/clear the opened date ('' clears)")
    ph_rm = ph_sub.add_parser("remove", help="remove a position")
    ph_rm.add_argument("user_id")
    ph_rm.add_argument("stock")
    ph_ls = ph_sub.add_parser("list", help="holdings with live P&L")
    ph_ls.add_argument("user_id", nargs="?", default="me")
    ph_ls.add_argument("--snapshot", default=None, metavar="YYYYMMDD")
    ph_ls.add_argument("--data-dir", default=None, help="data directory")
    ph_ls.add_argument("--no-check", action="store_true",
                       help="skip freshness gate (for automated pipelines)")
    ph_ls.add_argument("--json", action="store_true",
                       help="pure-JSON stdout (full precision)")
    ph.set_defaults(func=cmd_holding)

    pr = sub.add_parser(
        "recommend", help="daily picks under user style + holdings health")
    pr.add_argument("--user", default="me", help="user id (default: me)")
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

    pt_db = pt_sub.add_parser(
        "dashboard", help="write trading/dashboards/<id>.md "
                          "(positions + record + journal, for git)")
    pt_db.add_argument("season_id")
    _trade_common(pt_db)
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
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
