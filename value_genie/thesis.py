"""Thesis registry: tower-fed candidate pools for the QMF L1 layer.

Origin (2026-09-26 conversation, tower brick cognition-terminal-value
note v4): the tower could influence *how* the pool is ranked (L3/L4)
but never *what the pool contains* — L1's universe was frozen by the
funnel's trailing gates, which law brick trailing-gates-are-procyclical
shows systematically exclude issuance-phase machines at cycle bottoms
(the 2025 memory-chip miss).  The thesis registry closes path (4):
a tower-brick-backed assertion "machine X is in its issuance window"
becomes an explicit member list that ``masters-vote --thesis <id>``
injects into the L1 pool on equal footing with funnel candidates.

Pool semantics: the pool is funnel ∪ thesis members (never thesis-only —
the machine's names must prove themselves against the whole pool).
Members already in the funnel are marked; members outside it are
rebuilt from the snapshot's gated universe (same machinery as
``analyze.build_peer_set``) with live kline / HK-F10 backfill when
enabled.  L2 flags and L3/L4 judgment apply unchanged — the thesis
buys a seat at the table, never a vote.

Lineage is structural: every thesis carries ``brick`` (source tower
brick), ``features`` (the three issuance-window features: unpriced /
needed-by-cycle / skill-or-attention arbitrage) and ``falsification``
(the kill set).  A thesis whose falsifier triggers is retired
(``thesis retire``), never silently deleted — errors are assets.

Files live under ``theses/<id>.json`` (top-level, git-tracked — never
inside the cleanable ``data/`` tree), one file per thesis, atomic
writes; same persistence contract as ``users.py``.
"""

import json
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .users import normalize_code

THESIS_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
STATUSES = ("active", "retired")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ThesisMember:
    """One machine component. ``code`` follows the master.csv form
    (A: 6 digits, HK: zero-padded 5, US: uppercase ticker); ``note`` is
    the one-line justification for this name's seat (per-name argument,
    not adjectives)."""

    market: str          # "A" | "HK" | "US"
    code: str
    name: str = ""
    note: str = ""


@dataclass
class Thesis:
    id: str
    name: str
    brick: str           # lineage: source tower brick id
    statement: str       # one-sentence machine assertion
    reason: str          # why the machine is in its issuance window
    features: list = field(default_factory=list)        # window features
    falsification: list = field(default_factory=list)   # kill set
    members: list = field(default_factory=list)         # list[ThesisMember]
    industry_hints: dict = field(default_factory=dict)  # market -> [kw]
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    retired_reason: str = ""

    def member(self, market: str, code: str):
        code = normalize_code(market, code)
        for m in self.members:
            if m.market == market and m.code == code:
                return m
        return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def theses_dir() -> Path:
    return Path(config.THESES_DIR)


def thesis_path(thesis_id: str) -> Path:
    if not THESIS_ID_RE.match(thesis_id or ""):
        raise ValueError(
            f"bad thesis id {thesis_id!r}; expected lowercase slug like "
            f"'memory-supercycle' (a-z, 0-9, _, -, max 32 chars)")
    return theses_dir() / f"{thesis_id}.json"


def load_thesis(thesis_id: str) -> Thesis:
    """Load one thesis; schema-drift tolerant like ``users.load_user``:
    unknown member/top-level fields are dropped with a stderr warning,
    structurally broken files raise ValueError."""
    path = thesis_path(thesis_id)
    if not path.exists():
        raise FileNotFoundError(
            f"no thesis {thesis_id!r}; create one with "
            f"`python -m value_genie thesis add {thesis_id} ...`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt thesis file {path}: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(
            f"corrupt thesis file {path}: top level must be an object")
    if not data.get("id"):
        raise ValueError(f"corrupt thesis file {path}: missing 'id'")
    raw_members = data.get("members", [])
    if not isinstance(raw_members, list):
        raise ValueError(
            f"corrupt thesis file {path}: 'members' must be a list")
    known_m = {f.name for f in fields(ThesisMember)}
    members = []
    for m in raw_members:
        if not isinstance(m, dict):
            raise ValueError(
                f"corrupt thesis file {path}: member entries must be "
                f"objects")
        unknown = set(m) - known_m
        if unknown:
            print(f"[WARN] {path}: ignoring unknown member fields "
                  f"{sorted(unknown)}", file=sys.stderr)
        try:
            members.append(ThesisMember(
                **{k: v for k, v in m.items() if k in known_m}))
        except TypeError as exc:
            raise ValueError(
                f"corrupt thesis file {path}: bad member entry: {exc}") \
                from None
    known_t = {f.name for f in fields(Thesis)}
    unknown_t = set(data) - known_t
    if unknown_t:
        print(f"[WARN] {path}: ignoring unknown thesis fields "
              f"{sorted(unknown_t)}", file=sys.stderr)
    return Thesis(
        **{k: v for k, v in data.items()
           if k in known_t and k != "members"},
        members=members)


def list_theses(status=None) -> list:
    """All theses sorted by id; ``status`` filters ('active'/'retired')."""
    d = theses_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            t = load_thesis(p.stem)
        except (ValueError, OSError) as exc:
            print(f"[WARN] skipping unreadable thesis file: {exc}",
                  file=sys.stderr)
            continue
        if status and t.status != status:
            continue
        out.append(t)
    return out


def save_thesis(t: Thesis) -> Path:
    """Atomic write: dump to tmp file, then rename over the target."""
    path = thesis_path(t.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    t.updated_at = datetime.now().isoformat(timespec="seconds")
    data = asdict(t)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------------------
# Registry operations
# ---------------------------------------------------------------------------
def _check_brick(brick: str, thesis_id: str) -> None:
    """Lineage discipline: the source brick should exist in the tower.
    Warn (never block) — the tower may legitimately lag."""
    if not brick:
        print(f"[WARN] thesis {thesis_id!r} has no brick lineage; "
              f"assertions without a tower brick are narratives",
              file=sys.stderr)
        return
    if not (Path(config.TOWER_DIR) / f"{brick}.md").exists():
        print(f"[WARN] brick {brick!r} not found in tower/ — lineage "
              f"declared but target missing", file=sys.stderr)


def parse_member(text: str) -> ThesisMember:
    """'A:600900' / 'A:600900:长江电力' / 'US:MU:Micron' -> ThesisMember.
    Code is normalized to the master.csv form (HK zero-padded to 5)."""
    parts = str(text).split(":")
    if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
        raise ValueError(
            f"bad member {text!r}; expected MARKET:CODE[:NAME] "
            f"(e.g. A:600900 or US:MU:Micron)")
    market = parts[0].strip().upper()
    if market not in config.MARKETS:
        raise ValueError(
            f"bad member {text!r}; market must be one of "
            f"{', '.join(config.MARKETS)}")
    code = normalize_code(market, parts[1].strip())
    if not code:
        raise ValueError(f"bad member {text!r}; empty code")
    name = parts[2].strip() if len(parts) == 3 else ""
    return ThesisMember(market=market, code=code, name=name)


def create_thesis(thesis_id: str, name: str = "", brick: str = "",
                  statement: str = "", reason: str = "",
                  features=None, falsification=None, members=None,
                  industry_hints=None) -> Thesis:
    """New thesis file; ValueError on bad/duplicate id."""
    thesis_path(thesis_id)  # validates the slug
    if (theses_dir() / f"{thesis_id}.json").exists():
        raise ValueError(
            f"thesis {thesis_id!r} already exists; "
            f"use `thesis amend` to modify")
    t = Thesis(
        id=thesis_id, name=name or thesis_id, brick=brick,
        statement=statement, reason=reason,
        features=list(features or []),
        falsification=list(falsification or []),
        members=list(members or []),
        industry_hints=dict(industry_hints or {}),
        created_at=datetime.now().isoformat(timespec="seconds"))
    if t.status not in STATUSES:
        raise ValueError(f"bad status {t.status!r}")
    seen = set()
    for m in t.members:
        key = (m.market, m.code)
        if key in seen:
            raise ValueError(f"duplicate member {m.market}/{m.code}")
        seen.add(key)
    _check_brick(t.brick, t.id)
    save_thesis(t)
    return t


def amend_thesis(thesis_id: str, add_members=None, drop_members=None,
                 add_features=None, add_falsification=None,
                 add_industry_hints=None, reason=None) -> Thesis:
    """In-place edits; members keyed by (market, normalized code)."""
    t = load_thesis(thesis_id)
    for text in (drop_members or []):
        m = parse_member(text)
        found = t.member(m.market, m.code)
        if found is None:
            raise ValueError(
                f"no member {m.market}/{m.code} in thesis {thesis_id!r}")
        t.members.remove(found)
    for m in (add_members or []):
        if t.member(m.market, m.code) is not None:
            raise ValueError(
                f"{m.market}/{m.code} already a member of "
                f"{thesis_id!r}")
        t.members.append(m)
    if add_features:
        t.features.extend(add_features)
    if add_falsification:
        t.falsification.extend(add_falsification)
    if add_industry_hints:
        for market, kws in add_industry_hints.items():
            cur = t.industry_hints.setdefault(market, [])
            for kw in kws:
                if kw not in cur:
                    cur.append(kw)
    if reason is not None:
        t.reason = reason
    save_thesis(t)
    return t


def retire_thesis(thesis_id: str, reason: str) -> Thesis:
    """Mark retired (falsifier fired or window closed). Retired theses
    are never deleted: the wrong ones are calibration assets."""
    t = load_thesis(thesis_id)
    if t.status == "retired":
        raise ValueError(f"thesis {thesis_id!r} is already retired")
    if not reason.strip():
        raise ValueError("retire requires a --reason (which falsifier "
                         "fired, or why the window closed)")
    t.status = "retired"
    t.retired_reason = reason.strip()
    save_thesis(t)
    return t


def remove_thesis(thesis_id: str) -> Path:
    """Delete the file. For typos only — a falsified thesis belongs to
    ``retire``, not deletion (errors are assets)."""
    path = thesis_path(thesis_id)
    if not path.exists():
        raise FileNotFoundError(f"no thesis {thesis_id!r}")
    path.unlink()
    return path


# ---------------------------------------------------------------------------
# Pool building (masters-vote --thesis)
# ---------------------------------------------------------------------------
def _scored_peers(snap_dir: Path, market: str, live: bool,
                  wanted_codes: set) -> pd.DataFrame:
    """Gated universe for one market, pillar-scored, with live backfill
    of kline factors / HK F10 fundamentals for the wanted codes only
    (bounded — never the whole universe)."""
    from .analyze import build_peer_set
    from .fetch.kline import fetch_kline_any
    from .strategy.factors import add_pillar_scores, kline_metrics

    peers = build_peer_set(snap_dir, market)
    if live and not peers.empty:
        codes = peers["code"].astype(str)
        for code in sorted(wanted_codes):
            hit = peers.index[codes == code]
            if hit.empty:
                continue
            idx = hit[0]
            row = peers.loc[idx]
            if "ret_60d" in peers.columns and pd.notna(row.get("ret_60d")):
                pass  # cached kline factors already present
            else:
                kl = fetch_kline_any(market, code,
                                     str(row.get("market_id") or ""),
                                     lmt=config.KLINE_DAYS)
                for k, v in kline_metrics(kl).items():
                    peers.at[idx, k] = v
            if market == "HK":
                _fill_hk_fundamentals(peers, idx, code)
    return add_pillar_scores(peers)


def _fill_hk_fundamentals(peers: pd.DataFrame, idx, code: str) -> None:
    """HK names outside the funnel carry no hk_f10.csv row; fetch it
    live (same fallback as analyze.target_fundamentals)."""
    from .fetch.fundamentals import fetch_hk_f10

    row = peers.loc[idx]
    if pd.notna(row.get("roe")) and pd.notna(row.get("rev_yoy")):
        return
    f10 = fetch_hk_f10(code)
    if f10 is None or f10.empty:
        return
    r = f10.iloc[0]
    for k in ("revenue", "rev_yoy", "profit_yoy", "roe", "gross_margin",
              "net_margin", "debt_ratio", "dividend_yield"):
        if k in f10.columns and pd.isna(row.get(k)):
            v = r.get(k)
            if v is not None and pd.notna(v):
                peers.at[idx, k] = v


def build_pool(snap_dir, master: pd.DataFrame, theses: list,
               live: bool = True):
    """Funnel pool ∪ thesis members, thesis names marked in ``thesis``.

    Returns (pool_df, infos): infos is one dict per thesis —
    {id, members, funnel, injected, voted, excluded:[(label, reason)]}.
    Injected rows are rebuilt from the snapshot's gated universe and
    pillar-scored against their own market (same percentile contract as
    ``ask``); names missing from quotes or failing universe gates are
    reported in ``excluded``, never silently dropped.
    """
    snap_dir = Path(snap_dir)
    total = sum(len(t.members) for t in theses)
    if total > config.THESIS_MAX:
        raise ValueError(
            f"{total} thesis members exceeds THESIS_MAX "
            f"({config.THESIS_MAX}); split the run or trim members")

    out = master.copy()
    out["thesis"] = ""
    master_keys = (out["market"].astype(str) + "/" +
                   out["code"].astype(str))
    injected = []
    infos = []

    for t in theses:
        info = {"id": t.id, "name": t.name, "members": len(t.members),
                "funnel": 0, "injected": 0, "excluded": []}
        member_keys = {f"{m.market}/{m.code}" for m in t.members}
        mark = master_keys.isin(member_keys)
        info["funnel"] = int(mark.sum())
        out.loc[mark, "thesis"] = [
            f"{x},{t.id}" if x else t.id for x in out.loc[mark, "thesis"]]

        missing = [m for m in t.members
                   if f"{m.market}/{m.code}" not in set(master_keys[mark])]
        by_market: dict = {}
        for m in missing:
            by_market.setdefault(m.market, []).append(m)
        for market, members in by_market.items():
            quotes_path = snap_dir / f"{market.lower()}_quotes.csv"
            if not quotes_path.exists():
                info["excluded"] += [(f"{market}/{m.code}",
                                      "no snapshot quotes")
                                     for m in members]
                continue
            quotes = pd.read_csv(quotes_path, dtype={"code": str})
            qcodes = set(quotes["code"].astype(str))
            present = [m for m in members if m.code in qcodes]
            info["excluded"] += [(f"{market}/{m.code}",
                                  "not found in snapshot quotes")
                                 for m in members if m.code not in qcodes]
            if not present:
                continue
            peers = _scored_peers(snap_dir, market, live,
                                  {m.code for m in present})
            pcodes = peers["code"].astype(str) if not peers.empty \
                else pd.Series(dtype=str)
            for m in present:
                hit = peers.index[pcodes == m.code]
                if hit.empty:
                    info["excluded"].append(
                        (f"{market}/{m.code}",
                         "excluded by universe gates"))
                    continue
                r = peers.loc[hit[0]].to_dict()
                r["thesis"] = t.id
                if not r.get("name"):
                    r["name"] = m.name
                injected.append(r)
                info["injected"] += 1
        infos.append(info)

    if injected:
        add = pd.DataFrame(injected)
        out = pd.concat([out, add], ignore_index=True, sort=False)
    return out, infos


def discover(snap_dir, thesis: Thesis, limit: int = 30) -> pd.DataFrame:
    """Industry-hint candidates not yet members: quotes rows whose
    ``industry`` contains any hint keyword, member codes excluded,
    sorted by market cap desc. Discovery aid only — promotion into the
    member list is a deliberate per-name act (thesis amend)."""
    snap_dir = Path(snap_dir)
    rows = []
    member_keys = {f"{m.market}/{m.code}" for m in thesis.members}
    for market, kws in (thesis.industry_hints or {}).items():
        path = snap_dir / f"{market.lower()}_quotes.csv"
        if not kws or not path.exists():
            continue
        q = pd.read_csv(path, dtype={"code": str})
        ind = q.get("industry")
        if ind is None:
            continue
        mask = pd.Series(False, index=q.index)
        for kw in kws:
            mask = mask | ind.astype(str).str.contains(
                re.escape(kw), case=False, na=False)
        q = q[mask]
        for _, r in q.iterrows():
            key = f"{market}/{r['code']}"
            if key in member_keys:
                continue
            rows.append({"market": market, "code": str(r["code"]),
                         "name": r.get("name"),
                         "industry": r.get("industry"),
                         "market_cap": r.get("market_cap")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["market", "code"])
    return df.sort_values("market_cap", ascending=False,
                          na_position="last").head(limit)
