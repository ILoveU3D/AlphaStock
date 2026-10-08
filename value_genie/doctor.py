"""Data health checks: snapshot age, coverage, kline freshness, failures.

Output: PASS / WARN / FAIL lines plus a recommended action. Exit code 1
on any FAIL so scripts and agents can gate on it.
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import calendar, config
from .report import resolve_snapshot


def _parse_day(name: str):
    try:
        return datetime.strptime(name, "%Y%m%d").date()
    except ValueError:
        return None


def _snapshot_hours(snap: Path, now: datetime | None = None):
    """Hours since the snapshot pipeline last wrote (manifest mtime)."""
    src = snap / "manifest.json"
    if not src.exists():
        src = snap
    try:
        mtime = datetime.fromtimestamp(src.stat().st_mtime)
        return ((now or datetime.now()) - mtime).total_seconds() / 3600.0
    except OSError:
        return None


def _kline_lag(path: Path, market: str):
    """Trading-day lag of the last bar (closed-market days do not advance
    the lag — a Golden-Week gap is not staleness)."""
    try:
        df = pd.read_csv(path, usecols=["date"])
        last = datetime.strptime(str(df["date"].iloc[-1]),
                                 "%Y-%m-%d").date()
        return calendar.trading_day_lag(market, last)
    except (OSError, ValueError, IndexError, KeyError):
        return None


def _read_manifest(snap: Path) -> dict:
    try:
        return json.loads((snap / "manifest.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _market_data_ts(manifest: dict, snap: Path, mk: str):
    """When market ``mk``'s data in this snapshot was fetched:
    per-market market_at (partial fetch) -> created_at -> mtime."""
    ma = (manifest.get("market_at") or {}).get(mk)
    for raw in (ma, manifest.get("created_at")):
        if raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                continue
    try:
        return datetime.fromtimestamp(
            (snap / "manifest.json").stat().st_mtime)
    except OSError:
        return None


def _market_age_row(manifest: dict, snap: Path, mk: str,
                    now: datetime) -> tuple | None:
    """Calendar-aware per-market data-age verdict. On closed days a
    snapshot as of the last completed session's close PASSes regardless
    of wall-clock age (user mandate 2026-10-08)."""
    ts = _market_data_ts(manifest, snap, mk)
    if ts is None:
        return None
    age_h = (now - ts).total_seconds() / 3600.0
    expected = calendar.last_completed_session(mk, now)
    close_dt = calendar.session_close_dt(mk, expected)
    carried = mk in (manifest.get("carried_markets") or [])
    tag = "carried, " if carried else ""
    if ts >= close_dt:
        return ("PASS", mk, f"data as of last close {expected} "
                            f"({tag}age {age_h:.1f}h)")
    # The last completed session is NOT reflected in the data.
    missed = calendar.trading_day_lag(mk, ts.date(), expected)
    msg = (f"stale vs last close {expected} ({tag}age {age_h:.1f}h, "
           f"{missed} session(s) behind)")
    if age_h > 7 * 24 or missed > 7:
        return ("FAIL", mk, msg)
    return ("WARN", mk, msg)


def agent_rule(snap: Path, manifest: dict,
               now: datetime | None = None) -> dict:
    """Machine form of the agent 1-hour iron rule (user mandate
    2026-10-08): per market, should the AI fetch before answering?
    - data older than the last completed session's close -> fetch
    - market in session and data >1h old -> fetch
    - closed market with data as of last close -> no fetch
    """
    now = now or datetime.now()
    out = {}
    for mk in config.MARKETS:
        ts = _market_data_ts(manifest, snap, mk)
        if ts is None:
            out[mk] = {"needs_fetch": True, "reason": "no timestamp",
                       "age_hours": None}
            continue
        age_h = round((now - ts).total_seconds() / 3600.0, 1)
        expected = calendar.last_completed_session(mk, now)
        close_dt = calendar.session_close_dt(mk, expected)
        if ts < close_dt:
            needs, reason = True, "stale_beyond_last_close"
        elif calendar.in_session(mk, now) and age_h > 1.0:
            needs, reason = True, "in_session&age>1h"
        else:
            needs, reason = False, "ok"
        out[mk] = {"needs_fetch": needs, "reason": reason,
                   "age_hours": age_h}
    return out


def run_checks(data_dir=None, now: datetime | None = None) -> list:
    """[(status, market, message)] with status PASS / WARN / FAIL."""
    now = now or datetime.now()
    try:
        snap = resolve_snapshot(data_dir)
    except FileNotFoundError:
        return [("FAIL", "-",
                 "no snapshots found; run: python -m value_genie fetch")]
    out = [("PASS", "-", f"latest snapshot: {snap.name}")]
    manifest = _read_manifest(snap)
    d = _parse_day(snap.name)
    # per-market calendar-aware age rows first; they decide whether the
    # global wall-clock age may soft-fail during long market closures.
    market_rows = [r for r in
                   (_market_age_row(manifest, snap, mk, now)
                    for mk in config.MARKETS) if r is not None]
    all_as_of_close = bool(market_rows) and all(
        r[0] == "PASS" and "as of last close" in r[2]
        for r in market_rows)
    if d:
        age_days = (now.date() - d).days
        hours = _snapshot_hours(snap, now)
        if hours is not None:
            # Hour-granularity contract: >24h is stale (WARN), >7d blocks
            # — unless every market is closed and data sits at the last
            # completed session's close (then age is meaningless).
            if (age_days > 7 or hours > 7 * 24) and not all_as_of_close:
                status = "FAIL"
            elif hours > 24 and not all_as_of_close:
                status = "WARN"
            else:
                status = "PASS"
            suffix = (" (all markets as of last close)"
                      if all_as_of_close else "")
            out.append((status, "-",
                        f"snapshot age: {hours:.1f} hour(s) "
                        f"({age_days} day(s) by name){suffix}"))
        else:
            status = ("PASS" if age_days <= 1 or all_as_of_close
                      else ("WARN" if age_days <= 7 else "FAIL"))
            out.append((status, "-", f"snapshot age: {age_days} day(s)"))
    out.extend(market_rows)
    # degraded quotes source: a market that ran on the Tencent fallback
    # carries no fundamentals in quotes — lane B / HK batch did the heavy
    # lifting or the market degraded (2026-09-30 EM outage semantics)
    for mk, ds in (manifest.get("datasets") or {}).items():
        if isinstance(ds, dict) and ds.get("source") == "tencent":
            out.append(("WARN", mk, "quotes source=tencent (degraded: "
                                   "EM outage, pe=idx39 basis, "
                                   "pb A-share only)"))
    # static holiday tables are yearly — warn before they silently lapse
    yr = str(now.year)
    for mk in config.MARKETS:
        if not any(h.startswith(yr) for h in
                   config.TRADING_HOLIDAYS.get(mk, ())):
            out.append(("WARN", mk, f"holiday table has no {yr} entries "
                                    f"— refresh config.TRADING_HOLIDAYS"))
    for mk in config.MARKETS:
        q = snap / f"{mk.lower()}_quotes.csv"
        if not q.exists():
            out.append(("WARN", mk, "quotes file missing (not fetched?)"))
            continue
        n = len(pd.read_csv(q, dtype={"code": str}))
        out.append(("PASS" if n >= 1000 else "WARN", mk,
                    f"quotes rows: {n}"))
        kdir = snap / "kline"
        if kdir.is_dir():
            files = list(kdir.glob(f"{mk}_*.csv"))
            lags = [x for x in (_kline_lag(f, mk) for f in files)
                    if x is not None]
            if lags:
                worst = max(lags)
                freshest = min(lags)
                tol = config.KLINE_FRESH_DAYS[mk] + 2
                # Gate on fetch freshness: a stale FETCH moves every
                # file back together, so the freshest file proves the
                # pipeline reached the market's latest session. The
                # worst file is a per-stock state (suspension, halted
                # microcap) — e.g. Lakala 300773 suspended over the
                # 8-day National-Day gap must not FAIL a trading-day
                # answer (2026-10-08). Mass partial staleness (>25%
                # of files beyond tol) still warns.
                beyond = [x for x in lags if x > tol]
                if freshest > 7:
                    status = "FAIL"
                elif freshest > tol or len(beyond) > max(2, len(lags) // 4):
                    status = "WARN"
                else:
                    status = "PASS"
                msg = (f"klines: {len(files)} files, freshest last-bar "
                       f"lag {freshest} day(s)")
                if beyond:
                    msg += (f", {len(beyond)} beyond tol (worst "
                            f"{worst} day(s), suspended or stale)")
                out.append((status, mk, msg))
    for name, min_rows in (("a_financials.csv", 1000),
                           ("us_financials.csv", 500),
                           ("hk_f10.csv", 50)):
        p = snap / name
        if not p.exists():
            out.append(("WARN", name.split("_")[0].upper(),
                        f"{name} missing"))
        else:
            n = len(pd.read_csv(p))
            out.append(("PASS" if n >= min_rows else "WARN",
                        name.split("_")[0].upper(), f"{name} rows: {n}"))
    wp = snap / "watchlist.csv"
    if not wp.exists():
        out.append(("WARN", "-",
                    "watchlist.csv missing (old snapshot or no holdings)"))
    else:
        try:
            n = len(pd.read_csv(wp))
            out.append(("PASS", "-", f"watchlist rows: {n}"))
        except (OSError, pd.errors.ParserError, ValueError):
            out.append(("WARN", "-", "watchlist.csv unreadable"))
    # three-core missing rates per market (D2, 2026-09-29): imputed cells
    # are still missing DATA — the market mean only patches the ranking,
    # so high rates here mean "go repair the source" (e.g. annual FCF
    # coverage), not that the problem is solved.
    mp_csv = snap / "master.csv"
    if mp_csv.exists():
        try:
            m = pd.read_csv(mp_csv, dtype={"code": str})
        except (OSError, pd.errors.ParserError, ValueError):
            m = None
        if m is not None and "core_gaps" in m.columns \
                and "market" in m.columns:
            gaps = m["core_gaps"].fillna("")
            biz_miss = gaps.str.contains(
                "core_business imputed|business inputs missing")
            dcf_miss = gaps.str.contains(
                "core_dcf imputed|no annual FCF")
            for mk, idx in m.groupby("market").groups.items():
                n = len(idx)
                if not n:
                    continue
                biz = biz_miss.loc[idx].mean() * 100.0
                dcf = dcf_miss.loc[idx].mean() * 100.0
                status = ("WARN" if max(biz, dcf) > 25.0 else "PASS")
                out.append((status, str(mk),
                            f"core gaps: business {biz:.0f}% / dcf "
                            f"{dcf:.0f}% missing (market-mean imputed)"))
    # intel radar: missing -> WARN (舆情缺失允许降级运行, design §8),
    # never FAIL — the screener stays usable, only intel-gated screens
    # degrade (their gates skip with a WARN, see evaluate_gates).
    er = snap / "event_radar.csv"
    if not er.exists():
        out.append(("WARN", "-",
                    "event_radar.csv missing (old snapshot or intel "
                    "fetch failed)"))
    else:
        try:
            n = len(pd.read_csv(er, dtype={"code": str}))
            out.append(("PASS", "-", f"event_radar rows: {n}"))
        except (OSError, pd.errors.ParserError, ValueError):
            out.append(("WARN", "-", "event_radar.csv unreadable"))
    fails = manifest.get("failures") or []
    # carry-forward is by design, not a failure — the market rows already
    # disclose it via their "carried" tag; listing it as a WARN here
    # would cry wolf on every ask after a partial fetch (WARN fatigue).
    fails = [f for f in fails if "carried forward from" not in f]
    if fails:
        out.append(("WARN", "-",
                    "manifest failures: " + "; ".join(fails)))
    return out


def _recommended_action(checks: list):
    """None or a fetch hint, mirroring the console renderer."""
    if any(c[0] == "FAIL" and "no snapshots" in c[2] for c in checks):
        return "python -m value_genie fetch"
    if (any(c[0] == "FAIL" for c in checks)
            or any(c[0] == "WARN" and "age" in c[2] for c in checks)):
        return "python -m value_genie fetch   (refresh stale data)"
    return None


def render_checks(checks: list) -> str:
    icon = {"PASS": "ok  ", "WARN": "warn", "FAIL": "FAIL"}
    lines = ["== Value Genie doctor =="]
    for status, market, msg in checks:
        lines.append(f"[{icon[status]}] {market:>3}  {msg}")
    action = _recommended_action(checks)
    if action:
        lines += ["", f"action: {action}"]
    return "\n".join(lines)


def to_json(checks: list, data_dir=None,
            now: datetime | None = None) -> str:
    """`doctor --json` payload: worst status, per-check rows, action, and
    the machine form of the agent 1-hour iron rule (`agent_rule`)."""
    worst = ("FAIL" if any(c[0] == "FAIL" for c in checks)
             else "WARN" if any(c[0] == "WARN" for c in checks)
             else "PASS")
    rule = None
    try:
        snap = resolve_snapshot(data_dir)
        rule = agent_rule(snap, _read_manifest(snap), now)
    except FileNotFoundError:
        rule = {mk: {"needs_fetch": True, "reason": "no snapshot",
                     "age_hours": None} for mk in config.MARKETS}
    payload = {
        "status": worst,
        "checks": [{"status": s, "market": m, "message": msg}
                   for s, m, msg in checks],
        "action": _recommended_action(checks),
        "agent_rule": rule,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def doctor_exit_code(checks: list) -> int:
    return 1 if any(c[0] == "FAIL" for c in checks) else 0


def freshness_gate(data_dir=None, market=None) -> tuple:
    """(status, summary) where status is PASS / WARN / FAIL.

    FAIL = no snapshot or ancient data — must block price-sensitive
    answers. WARN = stale but usable — warn and proceed. PASS = fresh.
    `market` scopes the per-market rows (klines, quotes, financials,
    core gaps) to that one market: a closed A-share market must not
    block an HK/US answer whose own data is fresh (National-Day
    holiday artifact, 2026-10-08). Global rows ("-": snapshot age,
    watchlist, radar, manifest) always apply.
    """
    checks = run_checks(data_dir)
    if market:
        checks = [c for c in checks if c[1] in ("-", str(market).upper())]
    if any(c[0] == "FAIL" for c in checks):
        fails = [c[2] for c in checks if c[0] == "FAIL"]
        return "FAIL", "; ".join(fails)
    if any(c[0] == "WARN" for c in checks):
        warns = [c[2] for c in checks if c[0] == "WARN"]
        return "WARN", "; ".join(warns)
    return "PASS", "data is fresh"
