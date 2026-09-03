"""User profiles and holdings stored as per-user JSON files.

A user = investment style (six-pillar weights + optional hard gates +
preferred horizon) + holdings (full positions: qty / cost / opened
date). User styles are registered into the strategy registry as
kind="user" (see ``register_user_strategies``), so ``screen --strategy
<user_id>``, gate evaluation and horizon combination all work with
zero extra plumbing.

Files live under ``users/<user_id>.json`` (top-level, git-tracked,
durable — deliberately NOT under the cleanable ``data/`` tree) and
stay human-readable; all writes are atomic (tmp file + rename), the
same contract as skills persistence.
"""

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import config
from .strategy.registry import Strategy, register_strategy

USER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GATE_OPS = ("pctl>=", "pctl<=", ">=", "<=")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Holding:
    """One open position. ``code`` follows the master.csv form
    (A: 6 digits, HK: zero-padded 5, US: uppercase ticker)."""

    market: str            # "A" | "HK" | "US"
    code: str
    name: str
    qty: float
    cost: float            # per-share cost, in ``currency``
    currency: str
    opened: str = ""       # ISO date, optional

    def key(self) -> tuple:
        return (self.market, self.code)


@dataclass
class UserProfile:
    id: str
    name: str
    created_at: str
    style: dict = field(default_factory=dict)
    # style = {"name": str, "weights": {pillar: float},
    #          "gates": [[col, op, val], ...], "horizon": "long"}
    holdings: list = field(default_factory=list)   # list[Holding]

    def has_style(self) -> bool:
        return bool((self.style or {}).get("weights"))

    def holding(self, market: str, code: str):
        code = normalize_code(market, code)
        for h in self.holdings:
            if h.market == market and h.code == code:
                return h
        return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def users_dir() -> Path:
    return Path(config.USERS_DIR)


def user_path(user_id: str) -> Path:
    if not USER_ID_RE.match(user_id or ""):
        raise ValueError(
            f"bad user id {user_id!r}; expected lowercase slug like "
            f"'me' or 'john_doe' (a-z, 0-9, _, max 16 chars)")
    return users_dir() / f"{user_id}.json"


def load_user(user_id: str) -> UserProfile:
    """Load one user; FileNotFoundError carries a create hint."""
    path = user_path(user_id)
    if not path.exists():
        raise FileNotFoundError(
            f"no user {user_id!r}; create one with "
            f"`python -m value_genie user create {user_id}`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt user file {path}: {exc}") from None
    holdings = [Holding(**h) for h in data.get("holdings", [])]
    return UserProfile(
        id=data["id"], name=data.get("name") or data["id"],
        created_at=data.get("created_at") or "",
        style=data.get("style") or {}, holdings=holdings)


def list_users() -> list:
    """All user profiles, sorted by id."""
    d = users_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(load_user(p.stem))
        except ValueError as exc:
            print(f"[WARN] skipping unreadable user file: {exc}",
                  file=sys.stderr)
    return out


def save_user(profile: UserProfile) -> Path:
    """Atomic write: dump to tmp file, then rename over the target."""
    path = user_path(profile.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(profile)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path


def create_user(user_id: str, name: str = "", horizon: str = "") -> UserProfile:
    """New user file; ValueError on bad/duplicate id."""
    from .strategy.registry import list_strategies

    user_path(user_id)  # validates the slug
    path = users_dir() / f"{user_id}.json"
    if path.exists():
        raise ValueError(
            f"user {user_id!r} already exists ({path}); "
            f"use `user set-style` / `holding add` to modify")
    # only static ids matter: kind="user" entries are file-backed and
    # replaceable (a stale registry entry from a previous registration
    # in this process must not block recreating the file)
    taken = {s.id for s in list_strategies() if s.kind != "user"}
    if user_id in taken:
        raise ValueError(
            f"user id {user_id!r} collides with a registered strategy id")
    if horizon:
        from .strategy.registry import get_horizon
        get_horizon(horizon)  # raises ValueError if unknown
    profile = UserProfile(
        id=user_id, name=name or user_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        style={"weights": {}, "gates": [], "horizon": horizon or ""})
    save_user(profile)
    return profile


# ---------------------------------------------------------------------------
# Style management
# ---------------------------------------------------------------------------
def parse_gate(text: str) -> tuple:
    """'roe>=15' / 'debt_ratio<=60' / 'volatility pctl>=60' ->
    (column, op, value). Ops follow the registry gate DSL."""
    for op in GATE_OPS:
        idx = text.find(op)
        if idx > 0:
            col = text[:idx].strip()
            try:
                val = float(text[idx + len(op):].strip())
            except ValueError:
                raise ValueError(
                    f"bad gate {text!r}; value must be a number") from None
            if not col:
                raise ValueError(f"bad gate {text!r}; empty column")
            return (col, op, val)
    raise ValueError(
        f"bad gate {text!r}; expected COL>=V or COL<=V "
        f"(ops: {', '.join(GATE_OPS)})")


def set_style(user_id: str, weights=None, gates=None, clear_gates=False,
              horizon=None, base="") -> UserProfile:
    """Update a user's style in place and persist.

    ``base`` copies weights/gates/horizon from an existing strategy id
    first (e.g. '--base buffett'). Explicit ``weights`` then override
    individual pillars (merge, then renormalize to sum 1); ``gates``
    REPLACE the previous list (also replaced when ``clear_gates`` is
    set); ``horizon`` validates against the horizon registry.
    """
    from .strategy.presets import normalize_weights
    from .strategy.registry import get_horizon, get_strategy

    profile = load_user(user_id)
    st = profile.style
    if base:
        s = get_strategy(base)  # ValueError if unknown
        st["weights"] = normalize_weights(s.weights)
        st["gates"] = [list(g) for g in (s.gates or [])]
        if s.horizon:
            st["horizon"] = s.horizon
    if weights is not None:
        merged = dict(st.get("weights") or {})
        merged.update(weights)
        st["weights"] = normalize_weights(merged)
    if gates is not None:
        st["gates"] = [list(g) for g in gates]
    if clear_gates:
        st["gates"] = []
    if horizon is not None:
        if horizon == "":
            st["horizon"] = ""
        else:
            get_horizon(horizon)  # ValueError if unknown
            st["horizon"] = horizon
    profile.style = st
    save_user(profile)
    return profile


def style_to_strategy(profile: UserProfile):
    """User style -> Strategy(kind='user'); None when no weights set."""
    st = profile.style or {}
    weights = st.get("weights") or {}
    if not weights:
        return None
    return Strategy(
        id=profile.id,
        name=st.get("name") or f"{profile.name}的投资风格",
        weights=weights,
        gates=[tuple(g) for g in (st.get("gates") or [])],
        kind="user",
        order=50,
        horizon=st.get("horizon") or "")


def register_user_strategies() -> list:
    """Register every user's style as a kind='user' strategy.

    Called at CLI startup (before strategy choices are collected) so
    ``screen --strategy <user_id>`` and ``strategy list`` pick user
    styles up automatically. Replace-if-exists semantics; safe to
    call repeatedly.
    """
    out = []
    for u in list_users():
        s = style_to_strategy(u)
        if s is not None:
            register_strategy(s)
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Holdings management
# ---------------------------------------------------------------------------
def normalize_code(market: str, code: str) -> str:
    """User input -> master.csv code form for a known market."""
    code = str(code).strip()
    if market == "HK" and code.isdigit():
        return code.zfill(5)
    if market == "US":
        return code.upper()
    return code


def add_holding(profile: UserProfile, match, qty: float, cost: float,
                opened: str = "") -> Holding:
    """Append a resolved position; ValueError on duplicates/bad input."""
    if qty is None or qty <= 0:
        raise ValueError(f"qty must be positive, got {qty!r}")
    if cost is None or cost <= 0:
        raise ValueError(f"cost must be positive, got {cost!r}")
    if opened and not DATE_RE.match(opened):
        raise ValueError(f"bad opened date {opened!r}; expected YYYY-MM-DD")
    code = normalize_code(match.market, match.code)
    if profile.holding(match.market, code) is not None:
        raise ValueError(
            f"{match.name} ({match.market}/{code}) already held; "
            f"use `holding update` instead")
    h = Holding(
        market=match.market, code=code, name=match.name,
        qty=float(qty), cost=float(cost),
        currency=config.MARKET_CURRENCIES[match.market],
        opened=opened or "")
    profile.holdings.append(h)
    return h


def update_holding(profile: UserProfile, market: str, code: str,
                   qty=None, cost=None, opened=None, name=None) -> Holding:
    h = profile.holding(market, normalize_code(market, code))
    if h is None:
        held = ", ".join(f"{x.market}/{x.code} {x.name}"
                         for x in profile.holdings) or "(none)"
        raise ValueError(
            f"no holding {market}/{code}; current: {held}")
    if qty is not None:
        if qty <= 0:
            raise ValueError(f"qty must be positive, got {qty!r}")
        h.qty = float(qty)
    if cost is not None:
        if cost <= 0:
            raise ValueError(f"cost must be positive, got {cost!r}")
        h.cost = float(cost)
    if opened is not None:
        if opened and not DATE_RE.match(opened):
            raise ValueError(
                f"bad opened date {opened!r}; expected YYYY-MM-DD")
        h.opened = opened
    if name is not None:
        if not name.strip():
            raise ValueError("name must not be empty")
        h.name = name.strip()
    return h


def remove_holding(profile: UserProfile, market: str, code: str) -> Holding:
    h = profile.holding(market, normalize_code(market, code))
    if h is None:
        held = ", ".join(f"{x.market}/{x.code} {x.name}"
                         for x in profile.holdings) or "(none)"
        raise ValueError(
            f"no holding {market}/{code}; current: {held}")
    profile.holdings.remove(h)
    return h
