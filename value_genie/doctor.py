"""Data health checks: snapshot age, coverage, kline freshness, failures.

Output: PASS / WARN / FAIL lines plus a recommended action. Exit code 1
on any FAIL so scripts and agents can gate on it.
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import config
from .report import resolve_snapshot


def _parse_day(name: str):
    try:
        return datetime.strptime(name, "%Y%m%d").date()
    except ValueError:
        return None


def _snapshot_hours(snap: Path):
    """Hours since the snapshot pipeline last wrote (manifest mtime)."""
    src = snap / "manifest.json"
    if not src.exists():
        src = snap
    try:
        mtime = datetime.fromtimestamp(src.stat().st_mtime)
        return (datetime.now() - mtime).total_seconds() / 3600.0
    except OSError:
        return None


def _kline_lag(path: Path):
    try:
        df = pd.read_csv(path, usecols=["date"])
        last = datetime.strptime(str(df["date"].iloc[-1]),
                                 "%Y-%m-%d").date()
        return (date.today() - last).days
    except (OSError, ValueError, IndexError, KeyError):
        return None


def run_checks(data_dir=None) -> list:
    """[(status, market, message)] with status PASS / WARN / FAIL."""
    try:
        snap = resolve_snapshot(data_dir)
    except FileNotFoundError:
        return [("FAIL", "-",
                 "no snapshots found; run: python -m value_genie fetch")]
    out = [("PASS", "-", f"latest snapshot: {snap.name}")]
    d = _parse_day(snap.name)
    if d:
        age_days = (date.today() - d).days
        hours = _snapshot_hours(snap)
        if hours is not None:
            # Hour-granularity contract: >24h is stale (WARN), >7d blocks.
            # Name-based day age stays as the FAIL ceiling.
            if age_days > 7 or hours > 7 * 24:
                status = "FAIL"
            elif hours > 24:
                status = "WARN"
            else:
                status = "PASS"
            out.append((status, "-",
                        f"snapshot age: {hours:.1f} hour(s) "
                        f"({age_days} day(s) by name)"))
        else:
            status = ("PASS" if age_days <= 1
                      else ("WARN" if age_days <= 7 else "FAIL"))
            out.append((status, "-", f"snapshot age: {age_days} day(s)"))
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
            lags = [x for x in (_kline_lag(f) for f in files)
                    if x is not None]
            if lags:
                worst = max(lags)
                tol = config.KLINE_FRESH_DAYS[mk] + 2
                status = ("PASS" if worst <= tol
                          else ("WARN" if worst <= 7 else "FAIL"))
                out.append((status, mk,
                            f"klines: {len(files)} files, worst last-bar "
                            f"lag {worst} day(s)"))
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
    mp = snap / "manifest.json"
    if mp.exists():
        try:
            fails = (json.loads(mp.read_text(encoding="utf-8"))
                     .get("failures") or [])
            if fails:
                out.append(("WARN", "-",
                            "manifest failures: " + "; ".join(fails)))
        except ValueError:
            out.append(("WARN", "-", "manifest.json unreadable"))
    return out


def render_checks(checks: list) -> str:
    icon = {"PASS": "ok  ", "WARN": "warn", "FAIL": "FAIL"}
    lines = ["== Value Genie doctor =="]
    for status, market, msg in checks:
        lines.append(f"[{icon[status]}] {market:>3}  {msg}")
    if any(c[0] == "FAIL" and "no snapshots" in c[2] for c in checks):
        lines += ["", "action: python -m value_genie fetch"]
    elif (any(c[0] == "FAIL" for c in checks)
          or any(c[0] == "WARN" and "age" in c[2] for c in checks)):
        lines += ["",
                  "action: python -m value_genie fetch   (refresh stale data)"]
    return "\n".join(lines)


def doctor_exit_code(checks: list) -> int:
    return 1 if any(c[0] == "FAIL" for c in checks) else 0


def freshness_gate(data_dir=None) -> tuple:
    """(status, summary) where status is PASS / WARN / FAIL.

    FAIL = no snapshot or ancient data — must block price-sensitive
    answers. WARN = stale but usable — warn and proceed. PASS = fresh.
    """
    checks = run_checks(data_dir)
    if any(c[0] == "FAIL" for c in checks):
        fails = [c[2] for c in checks if c[0] == "FAIL"]
        return "FAIL", "; ".join(fails)
    if any(c[0] == "WARN" for c in checks):
        warns = [c[2] for c in checks if c[0] == "WARN"]
        return "WARN", "; ".join(warns)
    return "PASS", "data is fresh"
