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
