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
    python -m value_genie doctor
    python -m value_genie skill list|show|note|edit ...

Strategies are weight profiles over six pillars (value / growth /
quality / safety / momentum / cashflow).  ``--strategy`` covers both
presets (balanced, garp, ...) and masters (buffett, duan, sheng,
livermore).  ``--preset`` is kept as a backward-compatible alias.
``screen --set value=0.5 quality=0.5`` overrides with custom weights.
`ask` resolves any name/code to a stock and prints a brief verdict
(live quote + snapshot percentiles); `--evidence` adds the full table.
See AGENTS.md for the AI-facing playbook.
"""

import argparse
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
    print("next: python -m value_genie screen")
    return 0


def cmd_screen(args) -> int:
    weights = _parse_weights(args.set)
    markets = _parse_markets(args.markets)
    try:
        snap_dir = report.resolve_snapshot(args.data_dir, args.snapshot)
        master = report.load_master(snap_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None

    strategy = args.strategy or args.preset
    try:
        top = report.screen(master, strategy=strategy if not weights else None,
                            weights=weights, top_n=args.top, markets=markets)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if top.empty:
        raise SystemExit("no stocks passed the strategy; try another one")

    from .strategy.registry import get_strategy
    if weights:
        profile = report.normalize_weights(weights)
        label = "custom"
    else:
        s = get_strategy(strategy)
        profile = report.normalize_weights(s.weights)
        label = strategy
    print(f"== Value Genie screen ==")
    print(f"snapshot : {snap_dir.name}")
    print(f"strategy : {label} ({report.describe_weights(profile)})")
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
    print(f"{'id':<16} {'kind':<8} {'name':<48} weights")
    print("-" * 100)
    for s in items:
        w = " / ".join(f"{p}={s.weights.get(p, 0):.2f}"
                       for p in PILLARS if s.weights.get(p, 0) > 0)
        gates = f"  gates: {len(s.gates)}" if s.gates else ""
        print(f"{s.id:<16} {s.kind:<8} {s.name:<48} {w}{gates}")
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
    print(ov.render_overview(data))
    return 0


def cmd_doctor(args) -> int:
    from . import doctor as dr
    checks = dr.run_checks(args.data_dir)
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
    from .strategy import registry, presets, masters  # noqa: F401
    from .strategy.registry import list_strategies
    strategy_ids = [s.id for s in list_strategies()]

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
    ps.add_argument("--set", nargs="*", metavar="PILLAR=W",
                    help="custom weights, e.g. value=0.4 growth=0.2"
                         " (overrides --strategy)")
    ps.add_argument("--top", type=int, default=config.DEFAULT_TOP_N,
                    help=f"result count (default: {config.DEFAULT_TOP_N})")
    ps.add_argument("--markets", default=None, metavar="A,HK,US",
                    help="markets to include (default: all)")
    ps.add_argument("--data-dir", default=None, help="data directory")
    ps.add_argument("--out-dir", default=None, help="output directory")
    ps.set_defaults(func=cmd_screen)

    psl = sub.add_parser("strategy", help="list registered strategies")
    # accept both bare `strategy` and the documented `strategy list`
    psl_sub = psl.add_subparsers(dest="cmd")
    psl_sub.add_parser("list", help="list all strategies (default)")
    psl.set_defaults(func=cmd_strategy_list)

    psrc = sub.add_parser("source", help="list registered data sources")
    psrc_sub = psrc.add_subparsers(dest="cmd")
    psrc_sub.add_parser("list", help="list all data sources (default)")
    psrc.set_defaults(func=cmd_source_list)

    pa = sub.add_parser("ask", help="analyze one stock (verdict first)")
    pa.add_argument("query", help="stock name, code or ticker (Chinese ok)")
    pa.add_argument("--evidence", action="store_true",
                    help="print the full metric/percentile tables")
    pa.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    pa.add_argument("--data-dir", default=None, help="data directory")
    pa.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    pa.set_defaults(func=cmd_ask)

    pc = sub.add_parser("compare", help="compare 2+ stocks side by side")
    pc.add_argument("stocks", nargs="+", help="names/codes to compare")
    pc.add_argument("--data-dir", default=None, help="data directory")
    pc.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    pc.set_defaults(func=cmd_compare)

    po = sub.add_parser("overview", help="market digest from latest snapshot")
    po.add_argument("--markets", default=None, metavar="A,HK,US",
                    help="markets to include (default: all)")
    po.add_argument("--top", type=int, default=10,
                    help="top names per market (default: 10)")
    po.add_argument("--data-dir", default=None, help="data directory")
    po.add_argument("--no-check", action="store_true",
                    help="skip freshness gate (for automated pipelines)")
    po.set_defaults(func=cmd_overview)

    pdoc = sub.add_parser("doctor", help="check snapshot health/freshness")
    pdoc.add_argument("--data-dir", default=None, help="data directory")
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
