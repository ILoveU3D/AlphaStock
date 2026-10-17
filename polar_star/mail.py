"""Daily mail service: subscriber store, digest aggregation, letter
shell and SMTP delivery.

Architecture (user-mandated 2026-10-17, spec
docs/superpowers/specs/2026-10-17-daily-mail-design.md): the machine
aggregates the material (``mail digest``), the AI writes the letter
(no LLM inside the toolkit), the machine delivers it (``mail send``
via QQ-mail SMTP, stdlib smtplib only).

Storage is LOCAL-ONLY under top-level ``mail/`` (gitignored, never
pushed — same boundary as ``users/``): ``config.json`` (SMTP
credentials, hand-edited once), ``subscribers.json`` (CLI-maintained,
atomic writes) and ``sent.log`` (one ISO date per successful send —
the anti-double-send guard for the scheduled task).
"""

import json
import re
import smtplib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from html import unescape
from pathlib import Path

import pandas as pd

from . import config
from .atomic import atomic_write_text
from .resolve import Match, parse_code_form

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WATCH_TOKEN_RE = re.compile(r"^(A|HK|US):(.+)$", re.IGNORECASE)
CONFIG_KEYS = ("smtp_host", "smtp_port", "username", "auth_code", "from_name")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def mail_dir() -> Path:
    return Path(config.MAIL_DIR)


def config_path() -> Path:
    return mail_dir() / "config.json"


def subscribers_path() -> Path:
    return mail_dir() / "subscribers.json"


def sent_log_path() -> Path:
    return mail_dir() / "sent.log"


# ---------------------------------------------------------------------------
# Subscriber store
# ---------------------------------------------------------------------------
@dataclass
class Subscriber:
    name: str
    email: str
    watchlist: list = field(default_factory=list)   # ["MARKET:CODE", ...]


def load_subscribers() -> list:
    path = subscribers_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"corrupt subscribers file {path}: {exc}") from None
    if not isinstance(data, list):
        raise ValueError(
            f"corrupt subscribers file {path}: top level must be a list")
    subs = []
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("email"):
            raise ValueError(
                f"corrupt subscribers file {path}: "
                f"every entry needs an 'email'")
        subs.append(Subscriber(
            name=str(entry.get("name") or entry["email"]),
            email=str(entry["email"]),
            watchlist=[str(w).upper() for w in entry.get("watchlist") or []]))
    return subs


def save_subscribers(subs: list) -> Path:
    path = subscribers_path()
    atomic_write_text(path, json.dumps(
        [asdict(s) for s in subs], ensure_ascii=False, indent=2))
    return path


def normalize_watchlist(tokens) -> list:
    """Validate + canonicalize 'MARKET:CODE' tokens (dedup, order-stable)."""
    out = []
    for tok in tokens or []:
        m = WATCH_TOKEN_RE.match(str(tok).strip())
        if not m:
            raise ValueError(
                f"bad watch entry {tok!r}; expected MARKET:CODE "
                f"like HK:00700")
        market = m.group(1).upper()
        form = parse_code_form(m.group(2).strip())
        if form is None or form[0] != market:
            raise ValueError(
                f"bad watch entry {tok!r}; code does not fit "
                f"market {market}")
        canon = f"{market}:{form[1]}"
        if canon not in out:
            out.append(canon)
    return out


def add_subscriber(name: str, email: str, watchlist=None) -> Subscriber:
    email = (email or "").strip()
    if not EMAIL_RE.match(email):
        raise ValueError(f"bad email {email!r}")
    subs = load_subscribers()
    if any(s.email.lower() == email.lower() for s in subs):
        raise ValueError(
            f"subscriber {email} already exists; remove it first to change")
    sub = Subscriber(name=(name or "").strip() or email, email=email,
                     watchlist=normalize_watchlist(watchlist or []))
    subs.append(sub)
    save_subscribers(subs)
    return sub


def remove_subscriber(email: str) -> bool:
    subs = load_subscribers()
    kept = [s for s in subs if s.email.lower() != (email or "").lower()]
    if len(kept) == len(subs):
        return False
    save_subscribers(kept)
    return True


def collect_watchlist(subs) -> list:
    """Union of every subscriber's watchlist, deduped, order-stable."""
    out = []
    for s in subs:
        for tok in s.watchlist:
            if tok not in out:
                out.append(tok)
    return out


# ---------------------------------------------------------------------------
# SMTP config (hand-edited once)
# ---------------------------------------------------------------------------
def load_mail_config() -> dict:
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"no mail config {path}; create it once with keys "
            f"{', '.join(CONFIG_KEYS)} — QQ 邮箱授权码在 "
            f"邮箱设置→账户→POP3/SMTP服务 开启后获取")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt mail config {path}: {exc}") from None
    missing = [k for k in CONFIG_KEYS if not cfg.get(k)]
    if missing:
        raise ValueError(
            f"mail config {path} missing keys: {', '.join(missing)}")
    return cfg


# ---------------------------------------------------------------------------
# Letter shell (fixed CSS — the AI only writes the body fragment)
# ---------------------------------------------------------------------------
LETTER_CSS = """
body{margin:0;padding:24px;background:#f7f5f0;}
.letter{max-width:640px;margin:0 auto;background:#ffffff;padding:40px 48px;
font-family:Georgia,"Songti SC","SimSun",serif;font-size:16px;line-height:1.8;
color:#1a1a1a;}
.letter h1{font-size:22px;border-bottom:1px solid #d8d2c4;padding-bottom:12px;}
.letter h2{font-size:18px;margin-top:32px;color:#5b4a2f;}
.letter table{border-collapse:collapse;width:100%;font-size:14px;}
.letter th,.letter td{border:1px solid #d8d2c4;padding:6px 8px;text-align:left;}
.footer{margin-top:40px;padding-top:16px;border-top:1px solid #d8d2c4;
font-size:12px;color:#8a8578;}
"""

DISCLAIMER = "本邮件为北极星研究服务的个人订阅通讯，不构成投资建议。"


def wrap_letter(body_html: str, data_as_of: str) -> str:
    """Fixed shareholder-letter shell: serif single column, footer with
    the data-as-of line (freshness contract) — the AI only writes the
    body fragment; the shell guarantees the letter feel every day."""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>{LETTER_CSS}</style></head><body>"
            f'<div class="letter">\n{body_html}\n'
            f'<div class="footer">数据截至：{data_as_of}'
            f"<br>{DISCLAIMER}</div>\n</div></body></html>")


_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    """Plain-text fallback for the MIME alternative part."""
    text = unescape(_TAG_RE.sub("", html))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def send_message(cfg: dict, subscribers: list, subject: str,
                 body_html: str, data_as_of: str, force: bool = False,
                 dry_run: bool = False, today: str | None = None,
                 smtp_factory=None) -> dict:
    """Assemble + deliver the daily letter. To: the sender mailbox;
    Cc: every subscriber (sender-address duplicates skipped). One send
    per day unless force — the scheduled task must never double-mail."""
    if not subscribers:
        raise ValueError("no subscribers; add one with "
                         "`python -m polar_star subscriber add`")
    today = today or date.today().isoformat()
    log = sent_log_path()
    sent_dates = (set(log.read_text(encoding="utf-8").split())
                  if log.exists() else set())
    if today in sent_dates and not force:
        raise ValueError(f"daily mail already sent on {today}; "
                         f"pass --force to send again")
    html = wrap_letter(body_html, data_as_of)
    cc = []
    for s in subscribers:
        if s.email.lower() == cfg["username"].lower() or s.email in cc:
            continue
        cc.append(s.email)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"], cfg["username"]))
    msg["To"] = cfg["username"]
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(html_to_text(html))
    msg.add_alternative(html, subtype="html")
    if dry_run:
        return {"dry_run": True, "to": cfg["username"], "cc": cc,
                "subject": subject, "html": html}
    factory = smtp_factory or smtplib.SMTP_SSL
    try:
        with factory(cfg["smtp_host"], int(cfg["smtp_port"]),
                     timeout=30) as server:
            server.login(cfg["username"], cfg["auth_code"])
            server.send_message(msg, to_addrs=[cfg["username"], *cc])
    except smtplib.SMTPAuthenticationError as exc:
        raise ValueError(
            "SMTP authentication failed — QQ 邮箱需要 SMTP 授权码"
            "（不是登录密码），在 邮箱设置→账户→POP3/SMTP服务 "
            "重新生成后更新 mail/config.json") from exc
    sent_dates.add(today)
    atomic_write_text(log, "\n".join(sorted(sent_dates)) + "\n")
    return {"sent": True, "to": cfg["username"], "cc": cc,
            "subject": subject}


# ---------------------------------------------------------------------------
# Digest: L1 pool (the quant half of the fused recommendation)
# ---------------------------------------------------------------------------
POOL_COLUMNS = ("market", "code", "name", "core_score", "core_business",
                "core_culture", "core_dcf", "vote_count", "masters_passed",
                "graham_g", "expectation_gap")
POOL_MAX = 40   # material cap for the letter (top core_score rows)
_VETO_FLAGS = ("intel_red", "borrowed_dividend", "profit_spike",
               "expectation_overreach")


def build_l1_pool(master: pd.DataFrame,
                  overlays: bool = True) -> pd.DataFrame:
    """The masters-vote L1 wide pool (vote_count>=1 and not hard-vetoed),
    sorted by core_score — the quant half of the fused recommendation;
    the AI completes L2-L4 while writing the letter. Same chain as
    cmd_masters_vote minus the live pass. overlays=False skips the
    local profile/model stores so tests stay hermetic."""
    from .arsenal import core_triad as _cores
    from .arsenal import master_vote_panel as mvp
    from .arsenal import red_flag_battery as rfb
    df = master
    if "core_score" not in df.columns:
        df = _cores.add_core_scores(df)
    df = rfb.add_snapshot_flags(mvp.masters_vote(df))
    if overlays:
        from . import profile as _prof
        from .model import store as _mstore
        df, _ = _prof.apply_distilled_culture(df)
        df, _ = _mstore.apply_modeled_dcf(df)
    pool = df[(df["vote_count"] >= 1) & (~df["veto_hard"])]
    return pool.sort_values("core_score", ascending=False,
                            na_position="last").reset_index(drop=True)


def _truthy(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and f != 0.0   # NaN is not a flag (NaN != NaN)


def _pool_records(pool: pd.DataFrame) -> list:
    from . import report
    cols = [c for c in POOL_COLUMNS if c in pool.columns]
    head = pool.head(POOL_MAX)
    records = report.df_records(head[cols])
    for rec, (_, row) in zip(records, head.iterrows()):
        rec["vetoes"] = [f for f in _VETO_FLAGS if _truthy(row.get(f))]
    return records


# ---------------------------------------------------------------------------
# Digest: watch stock summaries + the material pack
# ---------------------------------------------------------------------------
def _data_as_of(snap_dir: Path) -> str:
    snap_dir = Path(snap_dir)
    man = snap_dir / "manifest.json"
    ts = ""
    if man.exists():
        ts = datetime.fromtimestamp(
            man.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"快照 {snap_dir.name}" + (f"（更新于 {ts}）" if ts else "")


def _resolve_watch(token: str, master, resolve_fn):
    """'MARKET:CODE' -> Match: the master.csv row is preferred (it
    carries market_id for live quotes); resolve_fn is the fallback;
    None when both miss (the item becomes a declared gap)."""
    market, _, code = token.partition(":")
    if master is not None:
        hit = master[(master["market"] == market)
                     & (master["code"].astype(str) == code)]
        if not hit.empty:
            r = hit.iloc[0]
            return Match(market, code, str(r.get("name") or code), 100.0,
                         str(r.get("market_id") or ""))
    if resolve_fn is not None:
        for m in resolve_fn(code):
            if m.market == market and m.code == code:
                return m
    return None


def _watch_item(m: Match, result: dict) -> dict:
    q = result.get("quote") or {}
    return {"market": m.market, "code": m.code, "name": m.name,
            "missing": False,
            "price": q.get("price"), "pct_chg": q.get("pct_chg"),
            "pe_ttm": q.get("pe_ttm"), "pb": q.get("pb"),
            "percentiles": result.get("percentiles") or {},
            "cores": result.get("cores") or {},
            "flags": result.get("risk_flags") or [],
            "warnings": result.get("warnings") or []}


def build_digest(snap_dir, subscribers, master=None, analyze_fn=None,
                 resolve_fn=None, overlays: bool = True) -> dict:
    """Aggregate today's letter material: the L1 pool (recommendation
    half) + one ask summary per deduped subscriber watch stock.
    analyze_fn/resolve_fn are injectable so tests never touch the
    network; a stock that fails becomes a missing item the AI must
    declare, never a fabricated row."""
    snap_dir = Path(snap_dir)
    if master is None:
        from . import report
        master = report.load_master(snap_dir)
    if analyze_fn is None:
        from . import analyze as az
        analyze_fn = az.analyze_stock
    if resolve_fn is None:
        from . import resolve as rs
        resolve_fn = rs.resolve
    pool = build_l1_pool(master, overlays=overlays)
    watch = []
    for token in collect_watchlist(subscribers):
        m = _resolve_watch(token, master, resolve_fn)
        if m is None:
            market, _, code = token.partition(":")
            watch.append({"market": market, "code": code, "name": "",
                          "missing": True,
                          "reason": "not found in snapshot or resolve "
                                    "chain"})
            continue
        try:
            watch.append(_watch_item(m, analyze_fn(m,
                                                   snapshot_dir=snap_dir)))
        except Exception as exc:   # one stock must never sink the digest
            watch.append({"market": m.market, "code": m.code,
                          "name": m.name, "missing": True,
                          "reason": f"{type(exc).__name__}: {exc}"})
    return {"date": date.today().isoformat(),
            "data_as_of": _data_as_of(snap_dir),
            "snapshot": snap_dir.name,
            "l1_pool": _pool_records(pool),
            "watchlist": watch}


def _jsonable(obj):
    """JSON-safe conversion (numpy scalars -> python, NaN -> None)."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and pd.isna(obj):
        return None
    return obj


def digest_to_json(digest: dict) -> str:
    return json.dumps(_jsonable(digest), ensure_ascii=False, indent=2)


def render_digest_summary(digest: dict) -> str:
    lines = [f"== 每日邮件素材 {digest['date']} ==",
             f"data-as-of: {digest['data_as_of']}",
             f"L1 pool: {len(digest['l1_pool'])} rows "
             f"(top by core_score)"]
    for rec in digest["l1_pool"][:10]:
        lines.append(f"  {rec.get('market')}:{rec.get('code')} "
                     f"{rec.get('name')}  core={rec.get('core_score')}  "
                     f"vetoes={','.join(rec.get('vetoes') or []) or '-'}")
    lines.append(f"watchlist: {len(digest['watchlist'])} stocks")
    for w in digest["watchlist"]:
        if w.get("missing"):
            lines.append(f"  {w['market']}:{w['code']} "
                         f"MISSING ({w.get('reason')})")
        else:
            lines.append(f"  {w['market']}:{w['code']} {w.get('name')}  "
                         f"price={w.get('price')} "
                         f"({w.get('pct_chg')}%)  "
                         f"flags={len(w.get('flags') or [])}")
    return "\n".join(lines)
