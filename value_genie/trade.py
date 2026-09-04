"""AI virtual portfolio (multi-season paper trading).

The AI manages seasons of virtual capital across A/HK/US with real
broker fee models (CITIC for A-shares, ZA Bank for HK/US), T+1/T+2
settlement, board-lot validation and a multi-currency cash pool with
FX spread. Dual management goal: grow NAV and build a sustainable
"dividend-style" withdrawal stream (see the `trading` skill).

Season state is one JSON file per season under ``trading/seasons/``
(top-level, git-tracked, durable — never under the cleanable ``data/``).
All writes are atomic (tmp + rename), same contract as users.py.

Network boundaries are module-level functions (``live_price``,
``fx_rates``, ``hk_lot``) so tests can monkeypatch them, mirroring
recommend.py conventions.
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config

SEASON_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
SEASON_STATUSES = ("active", "paused", "closed")
EPS = 1e-9


class TradeError(Exception):
    """Rejection with a human-readable reason (shown by the CLI)."""


# ---------------------------------------------------------------------------
# Network boundaries (monkeypatched in tests)
# ---------------------------------------------------------------------------
def live_price(market, code, name, snap_dir=None):
    """(price, source) via recommend.live_price; None when unavailable."""
    from .recommend import _us_market_ids, live_price as _lp
    return _lp(market, code, name, snap_dir, _us_market_ids(snap_dir))


def fx_rates(snap_dir=None, need_usd=False):
    """{currency: CNY rate} from the snapshot manifest."""
    from .recommend import _fx_rates
    return _fx_rates(snap_dir, need_usd)


def hk_lot(code5):
    """HK board lot via Eastmoney F10; None on failure."""
    from .fetch.fundamentals import fetch_hk_lot
    return fetch_hk_lot(code5)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today(today=None) -> str:
    return today or date.today().isoformat()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def seasons_dir() -> Path:
    return Path(config.TRADING_DIR) / "seasons"


def season_path(sid: str) -> Path:
    if not SEASON_ID_RE.match(sid or ""):
        raise ValueError(
            f"bad season id {sid!r}; expected lowercase slug like 's001' "
            f"(a-z, 0-9, _, max 16 chars)")
    return seasons_dir() / f"{sid}.json"


def save_season(season: dict) -> Path:
    """Atomic write: dump to tmp file, then rename over the target."""
    path = season_path(season["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(season, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path


def load_season(sid: str) -> dict:
    path = season_path(sid)
    if not path.exists():
        raise FileNotFoundError(
            f"no season {sid!r}; create one with `python -m value_genie "
            f"trade season new {sid} --capital N --base USD --markets US,HK`")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt season file {path}: {exc}") from None


def list_seasons() -> list:
    """All seasons sorted by id; corrupt files are skipped with a warning."""
    d = seasons_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[WARN] skipping unreadable season file: {exc}",
                  file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Season CRUD
# ---------------------------------------------------------------------------
def new_season(sid, name="", base="USD", capital=2000.0, markets=None,
               fx_spread=None) -> dict:
    """New season file; ValueError on bad/duplicate id or bad arguments."""
    season_path(sid)  # validates the slug
    if season_path(sid).exists():
        raise ValueError(f"season {sid!r} already exists ({season_path(sid)})")
    if base not in config.TRADE_CURRENCIES:
        raise ValueError(f"base currency must be one of "
                         f"{config.TRADE_CURRENCIES}, got {base!r}")
    if capital <= 0:
        raise ValueError("capital must be positive")
    mkts = [str(m).strip().upper() for m in (markets or [])]
    if not mkts or any(m not in config.MARKETS for m in mkts):
        raise ValueError(f"markets must be a non-empty subset of "
                         f"{config.MARKETS}, got {markets!r}")
    season = {
        "id": sid,
        "name": name or sid,
        "status": "active",
        "created_at": _now(),
        "base_currency": base,
        "initial_capital": float(capital),
        "rules": {
            "markets": mkts,
            "fx_spread": (config.TRADE_FX_SPREAD if fx_spread is None
                          else float(fx_spread)),
        },
        "cash": {c: 0.0 for c in config.TRADE_CURRENCIES},
        "settling": [],
        "positions": [],
        "fills": [],
        "nav_history": [],
        "journal": [],
        "totals": {"deposited": 0.0, "withdrawn": 0.0},
    }
    season["cash"][base] = float(capital)
    save_season(season)
    return season


def update_rules(sid, markets) -> dict:
    """Change allowed markets; takes effect going forward (existing
    positions stay sellable, new buys in dropped markets are rejected)."""
    season = load_season(sid)
    mkts = [str(m).strip().upper() for m in (markets or [])]
    if not mkts or any(m not in config.MARKETS for m in mkts):
        raise ValueError(f"markets must be a non-empty subset of "
                         f"{config.MARKETS}, got {markets!r}")
    season["rules"]["markets"] = mkts
    save_season(season)
    return season


def set_season_status(sid, status) -> dict:
    if status not in SEASON_STATUSES:
        raise ValueError(f"status must be one of {SEASON_STATUSES}")
    season = load_season(sid)
    season["status"] = status
    save_season(season)
    return season


def delete_season(sid) -> Path:
    path = season_path(sid)
    if not path.exists():
        raise FileNotFoundError(f"no season {sid!r}")
    path.unlink()
    return path


def _require_active(season):
    if season["status"] != "active":
        raise TradeError(
            f"season {season['id']!r} is {season['status']}; "
            f"resume it with `trade season resume {season['id']}` first")


# ---------------------------------------------------------------------------
# Fees (CITIC for A-shares, ZA Bank for HK/US; see config docstrings)
# ---------------------------------------------------------------------------
def _is_a_fund(code: str) -> bool:
    """A-share ETF/LOF: SH 5xxxxx funds, SZ 15/16/18xxxx funds."""
    c = str(code)
    return c[:1] == "5" or c[:2] in ("15", "16", "18")


def calc_fees(market: str, code: str, qty: float, price: float,
              side: str) -> dict:
    """Fee breakdown for one fill. ``side`` is 'buy' or 'sell'."""
    gross = qty * price
    fees = {}
    if market == "A":
        fees["commission"] = max(gross * config.A_COMMISSION_RATE,
                                 config.A_COMMISSION_MIN)
        if not _is_a_fund(code):
            fees["transfer"] = gross * config.A_TRANSFER_FEE
            if side == "sell":
                fees["stamp"] = gross * config.A_STAMP_SELL
    elif market == "HK":
        fees["platform"] = max(gross * config.HK_PLATFORM_RATE,
                               config.HK_PLATFORM_MIN)
        fees["stamp"] = gross * config.HK_STAMP
    elif market == "US":
        fees["platform"] = min(
            max(qty * config.US_PLATFORM_PER_SHARE, config.US_PLATFORM_MIN),
            gross * config.US_PLATFORM_CAP)
    else:
        raise TradeError(f"unknown market {market!r}")
    return {k: round(v, 2) for k, v in fees.items()}


# ---------------------------------------------------------------------------
# Board lots (buy-side validation; sells only check qty <= holding)
# ---------------------------------------------------------------------------
def lot_rule(market: str, code: str):
    """(min_qty, step) for A/US; (None, None) for HK (per-stock TRADE_UNIT)."""
    c = str(code)
    if market == "US":
        return 1, 1
    if market == "HK":
        return None, None
    if c[:3] == "688":                      # STAR board
        return 200, 1
    if _is_a_fund(c):
        return 100, 100
    if c[:1] in ("8", "4") or c[:2] == "92":  # Beijing exchange
        return 100, 1
    return 100, 100                          # SH/SZ main + GEM


def resolve_lot(market: str, code: str, override=None) -> int:
    if override is not None:
        if int(override) < 1:
            raise TradeError(f"--lot must be >= 1, got {override}")
        return int(override)
    if market == "HK":
        lot = hk_lot(code)
        if not lot:
            raise TradeError(
                f"HK board lot unknown for {code} (F10 unreachable); "
                f"pass --lot N explicitly")
        return int(lot)
    lo, _ = lot_rule(market, code)
    return lo


def validate_qty(market: str, code: str, qty, lot_override=None) -> int:
    """Validate a buy quantity against board-lot rules; returns the lot."""
    if qty <= 0:
        raise TradeError(f"qty must be positive, got {qty}")
    qty = float(qty)
    if market == "HK":
        lot = resolve_lot(market, code, lot_override)
        lo = step = lot
    else:
        if lot_override is not None:
            raise TradeError("--lot only applies to HK stocks")
        lo, step = lot_rule(market, code)
    if qty < lo - EPS:
        raise TradeError(
            f"qty {qty:g} below board lot {lo} for {market}/{code}")
    if step and abs((qty - lo) % step) > EPS:
        raise TradeError(
            f"qty {qty:g} not a multiple of board lot {step} for "
            f"{market}/{code} (minimum {lo})")
    return lo


# ---------------------------------------------------------------------------
# Trading days and settlement
# ---------------------------------------------------------------------------
def next_trading_day(date_str: str, n: int = 1) -> str:
    """n-th next trading day (weekdays only; holidays not tracked —
    trades only happen when the user triggers them on real trading days,
    so the approximation is documented, not solved)."""
    d = date.fromisoformat(date_str)
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()


def settle_due(season: dict, today: str) -> list:
    """Move settling entries whose fx_date has matured into cash.
    Returns the settled entries (for reporting)."""
    settled, keep = [], []
    for e in season["settling"]:
        if e["fx_date"] <= today:
            cur = e["currency"]
            season["cash"][cur] = round(
                season["cash"].get(cur, 0.0) + e["amount"], 2)
            settled.append(e)
        else:
            keep.append(e)
    season["settling"] = keep
    return settled


def spendable_for_buy(season: dict, market: str, currency: str,
                      today: str) -> float:
    """Settled cash + same-market settling proceeds already available
    (HK T+1 rebuy rule: yesterday's HK sale can rebuy HK today, but is
    not yet usable for FX or other markets)."""
    total = season["cash"].get(currency, 0.0)
    for e in season["settling"]:
        if (e["currency"] == currency and e["origin_market"] == market
                and e["available_date"] <= today):
            total += e["amount"]
    return total


def _deduct_buy(season: dict, market: str, currency: str, today: str,
                amount: float) -> None:
    """Spend ``amount`` for a same-market buy: settled cash first, then
    same-market available settling entries. Caller must have checked
    spendable_for_buy >= amount."""
    cash = season["cash"].get(currency, 0.0)
    if cash >= amount - EPS:
        season["cash"][currency] = round(cash - amount, 2)
        return
    amount -= cash
    season["cash"][currency] = 0.0
    for e in season["settling"]:
        if amount <= EPS:
            break
        if (e["currency"] == currency and e["origin_market"] == market
                and e["available_date"] <= today):
            take = min(e["amount"], amount)
            e["amount"] = round(e["amount"] - take, 2)
            amount -= take
    season["settling"] = [e for e in season["settling"] if e["amount"] > EPS]


def _find_pos(season: dict, market: str, code: str):
    for p in season["positions"]:
        if p["market"] == market and p["code"] == code:
            return p
    return None


def _session_flag(market: str) -> str:
    """'in'/'out' — informational only (fills always execute at the
    live_price quote; out-of-session quotes are the latest close)."""
    now = datetime.now()
    t = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "out"
    if market == "A":
        return "in" if (570 <= t <= 690) or (780 <= t <= 900) else "out"
    if market == "HK":
        return "in" if (570 <= t <= 720) or (780 <= t <= 960) else "out"
    # US in Beijing time (DST not modeled): 21:30-04:00
    return "in" if (t >= 1290 or t <= 240) else "out"


def _append_fill(season: dict, fill: dict) -> dict:
    fill["seq"] = len(season["fills"]) + 1
    season["fills"].append(fill)
    return fill


# ---------------------------------------------------------------------------
# Buy / sell
# ---------------------------------------------------------------------------
def buy(sid, match, qty, note="", lot_override=None, snap_dir=None,
        today=None) -> dict:
    """Market buy at the live/snapshot quote. Returns the fill dict.
    Raises TradeError with the rejection reason."""
    season = load_season(sid)
    today = _today(today)
    _require_active(season)
    settle_due(season, today)
    market, code = match.market, match.code
    if market not in season["rules"]["markets"]:
        raise TradeError(
            f"market {market} not allowed in season {sid} "
            f"(rules: {','.join(season['rules']['markets'])})")
    cur = config.MARKET_CURRENCIES[market]
    price, source = live_price(market, code, match.name, snap_dir)
    if price is None:
        raise TradeError(
            f"no price for {market}/{code} (live and snapshot both failed)")
    lot = validate_qty(market, code, qty, lot_override)
    qty = float(qty)
    fees = calc_fees(market, code, qty, price, "buy")
    fees_total = round(sum(fees.values()), 2)
    gross = round(qty * price, 2)
    total = round(gross + fees_total, 2)
    spendable = spendable_for_buy(season, market, cur, today)
    if spendable < total - EPS:
        raise TradeError(
            f"insufficient {cur}: need {total:,.2f} (incl fees "
            f"{fees_total:,.2f}), spendable {spendable:,.2f}")
    _deduct_buy(season, market, cur, today, total)
    pos = _find_pos(season, market, code)
    if pos:
        new_qty = round(pos["qty"] + qty, 4)
        pos["avg_cost"] = round(
            (pos["avg_cost"] * pos["qty"] + total) / new_qty, 4)
        pos["qty"] = new_qty
        pos["last_buy_date"] = today
        pos["lot"] = lot
    else:
        season["positions"].append({
            "market": market, "code": code, "name": match.name,
            "qty": qty, "avg_cost": round(total / qty, 4),
            "currency": cur, "last_buy_date": today, "lot": lot})
    fill = _append_fill(season, {
        "ts": _now(), "date": today, "action": "buy",
        "market": market, "code": code, "name": match.name,
        "qty": qty, "price": float(price), "gross": gross,
        "fees": fees, "fees_total": fees_total,
        "cash_delta": -total, "currency": cur,
        "session": _session_flag(market), "note": note,
        "settle_amount": 0.0})
    save_season(season)
    return fill


def sell(sid, match, qty, note="", snap_dir=None, today=None) -> dict:
    """Market sell. A-share same-day round trips are rejected (T+1).
    Proceeds enter the settling queue: same-market rebuy at T+1,
    FX/cross-market use at T+1 (A/US) or T+2 (HK)."""
    season = load_season(sid)
    today = _today(today)
    _require_active(season)
    settle_due(season, today)
    market, code = match.market, match.code
    pos = _find_pos(season, market, code)
    if not pos:
        raise TradeError(f"no position in {market}/{code} in this season")
    qty = float(qty)
    if qty <= 0 or qty > pos["qty"] + EPS:
        raise TradeError(
            f"qty {qty:g} exceeds holding {pos['qty']:g} of "
            f"{market}/{code}")
    if market == "A" and pos.get("last_buy_date") == today:
        raise TradeError(
            f"A-share T+1: {code} bought {today} cannot be sold today")
    price, source = live_price(market, code, match.name, snap_dir)
    if price is None:
        raise TradeError(
            f"no price for {market}/{code} (live and snapshot both failed)")
    cur = config.MARKET_CURRENCIES[market]
    fees = calc_fees(market, code, qty, price, "sell")
    fees_total = round(sum(fees.values()), 2)
    gross = round(qty * price, 2)
    proceeds = round(gross - fees_total, 2)
    realized = round((price - pos["avg_cost"]) * qty - fees_total, 2)
    pos["qty"] = round(pos["qty"] - qty, 4)
    if pos["qty"] <= EPS:
        season["positions"].remove(pos)
    avail_d = next_trading_day(today, 1)
    fx_d = next_trading_day(today, 2 if market == "HK" else 1)
    season["settling"].append({
        "currency": cur, "amount": proceeds, "origin_market": market,
        "available_date": avail_d, "fx_date": fx_d})
    fill = _append_fill(season, {
        "ts": _now(), "date": today, "action": "sell",
        "market": market, "code": code, "name": match.name,
        "qty": qty, "price": float(price), "gross": gross,
        "fees": fees, "fees_total": fees_total,
        "cash_delta": 0.0, "settle_amount": proceeds,
        "available_date": avail_d, "fx_date": fx_d,
        "realized_pnl": realized, "currency": cur,
        "session": _session_flag(market), "note": note})
    save_season(season)
    return fill
