# Daily Mail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日一封巴菲特股东信质感的中文邮件——`mail digest` 聚合素材（过新鲜度门）、AI 写信、`mail send` 经 QQ 邮箱 SMTP 套壳群发，`subscriber` 管理订阅名单。

**Architecture:** AI 撰写 + CLI 送信（spec: `docs/superpowers/specs/2026-10-17-daily-mail-design.md`，已提交于 feat/daily-mail）。机器聚合素材（L1 宽池 + 订阅者关注股 ask 摘要），AI 完成 L2-L4 判断并写 prose，机器套固定排版壳发送。存储全部 local-only（顶层 `mail/`，gitignored）。零新第三方依赖（smtplib/email 为标准库）。

**Tech Stack:** Python 3.10+ / pandas / smtplib+email（标准库）/ pytest。

**Spec 之外的一处实现细化（已向用户声明）：** 素材包的 L1 池按 core_score 截前 40 行（`POOL_MAX = 40`）——宽池可达上百行，信件素材需要可读规模。

**File structure:**
- Create `polar_star/mail.py` — 全部逻辑：订阅者存储、digest 聚合、排版壳、SMTP 发送
- Modify `polar_star/config.py` — 加 `MAIL_DIR` 常量（紧随 USERS_DIR 之后）
- Modify `.gitignore` — 加 `mail/` 块（紧随 `users/` 块之后）
- Modify `polar_star/__main__.py` — `cmd_mail` / `cmd_subscriber` + argparse 注册 + 模块 docstring 用法行
- Create `tests/test_mail.py` — 独立测试文件（repo 约定 each file standalone）
- Modify `AGENTS.md` — 每日邮件一节（操作手册登记）

---

### Task 1: config 常量 + .gitignore + 订阅者存储

**Files:**
- Modify: `polar_star/config.py`（USERS_DIR 行之后）
- Modify: `.gitignore`（`users/` 块之后）
- Create: `polar_star/mail.py`（本任务只写路径 + 订阅者存储部分）
- Test: `tests/test_mail.py`

- [ ] **Step 1: config.py 加常量**

`polar_star/config.py` 第 14 行 `USERS_DIR = ...` 之后插入：

```python
MAIL_DIR = BASE_DIR / "mail"      # local-only mail territory, never pushed
```

- [ ] **Step 2: .gitignore 加块**

`.gitignore` 中 `users/` 块（第 15-19 行）之后插入：

```
# Mail territory is LOCAL-ONLY (2026-10-17): SMTP credentials, subscriber
# list and send log are private — never pushed to any remote
mail/
```

- [ ] **Step 3: 写失败测试**

Create `tests/test_mail.py`:

```python
"""Tests for the daily mail service (polar_star/mail.py)."""

import json

import pandas as pd
import pytest

from polar_star import config
from polar_star import mail as ml
from polar_star.strategy import masters  # noqa: F401 — trigger registration
from polar_star.strategy import presets  # noqa: F401


@pytest.fixture
def mail_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAIL_DIR", tmp_path)
    return tmp_path


class TestSubscriberStore:
    def test_add_list_remove_roundtrip(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com", ["HK:00700", "A:600519"])
        ml.add_subscriber("朋友", "friend@163.com", ["US:AAPL", "hk:00700"])
        subs = ml.load_subscribers()
        assert [s.email for s in subs] == ["me@qq.com", "friend@163.com"]
        # canonical form: market upper, HK code zero-padded, deduped
        assert subs[1].watchlist == ["US:AAPL", "HK:00700"]
        assert ml.remove_subscriber("me@qq.com") is True
        assert [s.email for s in ml.load_subscribers()] == ["friend@163.com"]
        assert ml.remove_subscriber("ghost@qq.com") is False

    def test_duplicate_email_rejected(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com")
        with pytest.raises(ValueError, match="already exists"):
            ml.add_subscriber("另一个我", "me@qq.com")

    def test_bad_email_rejected(self, mail_tmp):
        with pytest.raises(ValueError, match="bad email"):
            ml.add_subscriber("我", "not-an-email")

    def test_bad_watch_entry_rejected(self, mail_tmp):
        with pytest.raises(ValueError, match="MARKET:CODE"):
            ml.add_subscriber("我", "me@qq.com", ["腾讯"])
        with pytest.raises(ValueError, match="does not fit"):
            ml.add_subscriber("我", "me@qq.com", ["A:00700"])

    def test_collect_watchlist_dedup(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com", ["HK:00700", "A:600519"])
        ml.add_subscriber("朋友", "f@qq.com", ["A:600519", "US:AAPL"])
        assert ml.collect_watchlist(ml.load_subscribers()) == [
            "HK:00700", "A:600519", "US:AAPL"]

    def test_empty_store(self, mail_tmp):
        assert ml.load_subscribers() == []
```

- [ ] **Step 4: 跑测试确认失败**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'polar_star.mail'`

- [ ] **Step 5: 实现 mail.py（路径 + 订阅者存储）**

Create `polar_star/mail.py`:

```python
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
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: 6 passed

- [ ] **Step 7: Commit**

```powershell
git add polar_star/config.py .gitignore polar_star/mail.py tests/test_mail.py
git commit -m "feat(mail): 订阅者存储 + MAIL_DIR 配置 — local-only mail/ 目录"
```

---

### Task 2: SMTP 配置加载 + 股东信排版壳

**Files:**
- Modify: `polar_star/mail.py`（追加）
- Test: `tests/test_mail.py`（追加）

- [ ] **Step 1: 写失败测试**

Append to `tests/test_mail.py`:

```python
def _write_config(tmp_path, **overrides):
    cfg = {"smtp_host": "smtp.qq.com", "smtp_port": 465,
           "username": "me@qq.com", "auth_code": "secret",
           "from_name": "北极星"}
    cfg.update(overrides)
    (tmp_path / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return cfg


class TestMailConfig:
    def test_missing_config_hint(self, mail_tmp):
        with pytest.raises(FileNotFoundError, match="no mail config"):
            ml.load_mail_config()

    def test_missing_keys_rejected(self, mail_tmp):
        _write_config(mail_tmp, auth_code="")
        with pytest.raises(ValueError, match="missing keys: auth_code"):
            ml.load_mail_config()

    def test_roundtrip(self, mail_tmp):
        cfg = _write_config(mail_tmp)
        assert ml.load_mail_config() == cfg


class TestLetterShell:
    def test_wrap_letter_structure(self):
        html = ml.wrap_letter("<h1>致股东</h1><p>正文</p>", "快照 20261017")
        assert 'class="letter"' in html
        assert "Georgia" in html          # serif shell, AI-invariant
        assert "<h1>致股东</h1><p>正文</p>" in html
        assert "数据截至：快照 20261017" in html
        assert "不构成投资建议" in html

    def test_html_to_text(self):
        text = ml.html_to_text("<h1>标题</h1><p>一<br>二&amp;三</p>")
        assert "<" not in text
        assert "标题" in text and "二&三" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: FAIL — `AttributeError: module 'polar_star.mail' has no attribute 'load_mail_config'`

- [ ] **Step 3: 实现（追加到 mail.py）**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```powershell
git add polar_star/mail.py tests/test_mail.py
git commit -m "feat(mail): SMTP配置加载 + 股东信排版壳（衬线单列+data-as-of页脚）"
```

---

### Task 3: send_message（发送 + 防重 + dry-run）

**Files:**
- Modify: `polar_star/mail.py`（追加）
- Test: `tests/test_mail.py`（追加）

- [ ] **Step 1: 写失败测试**

Append to `tests/test_mail.py`:

```python
class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.logged_in = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg, to_addrs=None):
        self.sent.append((msg, to_addrs))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _subs():
    return [ml.Subscriber("我", "me@qq.com", []),
            ml.Subscriber("朋友", "friend@163.com", [])]


class TestSendMessage:
    def setup_method(self):
        _FakeSMTP.instances = []

    def test_dry_run_touches_nothing(self, mail_tmp):
        cfg = _write_config(mail_tmp)
        result = ml.send_message(cfg, _subs(), "主题", "<p>正文</p>",
                                 "快照 20261017", dry_run=True)
        assert result["dry_run"] is True
        assert result["to"] == "me@qq.com"
        # sender-duplicate address skipped in Cc
        assert result["cc"] == ["friend@163.com"]
        assert "数据截至：快照 20261017" in result["html"]
        assert _FakeSMTP.instances == []
        assert not ml.sent_log_path().exists()

    def test_send_records_sent_log_and_guards(self, mail_tmp):
        cfg = _write_config(mail_tmp)
        result = ml.send_message(cfg, _subs(), "主题", "<p>正文</p>",
                                 "快照 20261017", today="2026-10-17",
                                 smtp_factory=_FakeSMTP)
        assert result["sent"] is True
        server = _FakeSMTP.instances[0]
        assert server.logged_in == ("me@qq.com", "secret")
        msg, to_addrs = server.sent[0]
        assert to_addrs == ["me@qq.com", "friend@163.com"]
        assert msg["Subject"] == "主题"
        assert msg["To"] == "me@qq.com"
        assert msg["Cc"] == "friend@163.com"
        assert "multipart/alternative" in msg.get_content_type()
        assert ml.sent_log_path().read_text().split() == ["2026-10-17"]
        # same day again -> blocked, then --force passes
        with pytest.raises(ValueError, match="already sent"):
            ml.send_message(cfg, _subs(), "主题", "<p>x</p>", "as-of",
                            today="2026-10-17", smtp_factory=_FakeSMTP)
        ml.send_message(cfg, _subs(), "主题", "<p>x</p>", "as-of",
                        today="2026-10-17", force=True,
                        smtp_factory=_FakeSMTP)

    def test_no_subscribers_rejected(self, mail_tmp):
        cfg = _write_config(mail_tmp)
        with pytest.raises(ValueError, match="no subscribers"):
            ml.send_message(cfg, [], "主题", "<p>x</p>", "as-of",
                            dry_run=True)

    def test_auth_error_guidance(self, mail_tmp):
        import smtplib as _s

        class _AuthFailSMTP(_FakeSMTP):
            def login(self, user, password):
                raise _s.SMTPAuthenticationError(535, b"Login fail")

        cfg = _write_config(mail_tmp)
        with pytest.raises(ValueError, match="授权码"):
            ml.send_message(cfg, _subs(), "主题", "<p>x</p>", "as-of",
                            today="2026-10-18", smtp_factory=_AuthFailSMTP)
        # failed send must not record the day
        assert not ml.sent_log_path().exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'send_message'`

- [ ] **Step 3: 实现（追加到 mail.py）**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit**

```powershell
git add polar_star/mail.py tests/test_mail.py
git commit -m "feat(mail): send_message — To本人+CC订阅者、sent.log防重发、dry-run、授权码失败指引"
```

---

### Task 4: build_l1_pool（masters-vote L1 宽池聚合）

**Files:**
- Modify: `polar_star/mail.py`（追加）
- Test: `tests/test_mail.py`（追加）

- [ ] **Step 1: 写失败测试**

Append to `tests/test_mail.py`:

```python
def _scores(v, g, q, s, m, c):
    return {"value_score": v, "growth_score": g, "quality_score": q,
            "safety_score": s, "momentum_score": m, "cashflow_score": c}


def _master_frame():
    """Synthetic master.csv-style frame (same contract as
    tests/test_consensus.py): row 000001 passes the five fundamental
    masters; 000002 is a profit-spike cyclical peak (hard-vetoed);
    000003 passes nothing."""
    rows = [
        {"market": "A", "code": "000001", "name": "低波优质",
         "price": 10.0, "pe_ttm": 12.0, "pb": 1.2, "roe": 25.0,
         "gross_margin": 60.0, "debt_ratio": 30.0, "ocf_yield": 8.0,
         "fcf_yield": 7.0, "borrowed_dividend": 0, "dividend_yield": 3.0,
         "profit_yoy": 20.0, "ret_60d": 5.0, "volatility": 20.0,
         "pos_52w": 70.0, **_scores(70, 80, 90, 70, 50, 85)},
        {"market": "A", "code": "000002", "name": "周期顶",
         "price": 5.0, "pe_ttm": 4.0, "pb": 0.8, "roe": 25.0,
         "gross_margin": 10.0, "debt_ratio": 40.0, "ocf_yield": 30.0,
         "fcf_yield": 20.0, "borrowed_dividend": 0, "dividend_yield": 2.0,
         "profit_yoy": 250.0, "ret_60d": 5.0, "volatility": 30.0,
         "pos_52w": 70.0, **_scores(75, 65, 45, 50, 70, 65)},
        {"market": "A", "code": "000003", "name": "全挂",
         "price": 8.0, "pe_ttm": 60.0, "pb": 9.0, "roe": 2.0,
         "gross_margin": 5.0, "debt_ratio": 80.0, "ocf_yield": 0.5,
         "fcf_yield": 0.2, "borrowed_dividend": 1, "dividend_yield": 0.0,
         "profit_yoy": -30.0, "ret_60d": -20.0, "volatility": 80.0,
         "pos_52w": 5.0, **_scores(20, 30, 15, 25, 10, 20)},
    ]
    return pd.DataFrame(rows)


class TestL1Pool:
    def test_pool_excludes_vetoed_and_voteless(self):
        pool = ml.build_l1_pool(_master_frame(), overlays=False)
        assert list(pool["code"]) == ["000001"]

    def test_pool_records_shape_and_vetoes(self):
        pool = ml.build_l1_pool(_master_frame(), overlays=False)
        records = ml._pool_records(pool)
        assert len(records) == 1
        rec = records[0]
        for key in ("market", "code", "name", "core_score",
                    "core_business", "core_culture", "core_dcf",
                    "vote_count", "masters_passed",
                    "graham_g", "expectation_gap", "vetoes"):
            assert key in rec, f"missing pool key {key}"
        assert rec["vetoes"] == []
        # graham audit: (12 - 8.5) / 2 = 1.75 implied growth
        assert rec["graham_g"] == pytest.approx(1.75)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'build_l1_pool'`

- [ ] **Step 3: 实现（追加到 mail.py）**

```python
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
        return bool(float(v))
    except (TypeError, ValueError):
        return False


def _pool_records(pool: pd.DataFrame) -> list:
    from . import report
    cols = [c for c in POOL_COLUMNS if c in pool.columns]
    head = pool.head(POOL_MAX)
    records = report.df_records(head[cols])
    for rec, (_, row) in zip(records, head.iterrows()):
        rec["vetoes"] = [f for f in _VETO_FLAGS if _truthy(row.get(f))]
    return records
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: 17 passed

- [ ] **Step 5: Commit**

```powershell
git add polar_star/mail.py tests/test_mail.py
git commit -m "feat(mail): build_l1_pool — masters-vote宽池(去硬否决,core_score排序,素材截前40)"
```

---

### Task 5: build_digest（素材包聚合）

**Files:**
- Modify: `polar_star/mail.py`（追加）
- Test: `tests/test_mail.py`（追加）

- [ ] **Step 1: 写失败测试**

Append to `tests/test_mail.py`:

```python
def _fake_analyze(match, snapshot_dir=None, **kwargs):
    return {"quote": {"price": 100.0, "pct_chg": 1.5,
                      "pe_ttm": 12.0, "pb": 1.2},
            "percentiles": {"pe_ttm": 30.0},
            "cores": {"business": 80.0, "culture": None, "dcf": 70.0,
                      "core_score": 75.0, "gaps": "CULTURE_VETO_ONLY"},
            "risk_flags": ["示例旗标 verbatim"],
            "warnings": []}


class TestDigest:
    def test_digest_aggregates_pool_and_watch(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com",
                          ["A:000001", "HK:00700", "A:000003"])
        digest = ml.build_digest(
            mail_tmp, ml.load_subscribers(), master=_master_frame(),
            analyze_fn=_fake_analyze, resolve_fn=lambda q: [],
            overlays=False)
        assert digest["snapshot"] == mail_tmp.name
        assert digest["data_as_of"].startswith("快照 ")
        assert len(digest["l1_pool"]) == 1
        watch = {w["code"]: w for w in digest["watchlist"]}
        assert set(watch) == {"000001", "00700", "000003"}
        # in-master stock analyzed via the injected analyze_fn
        assert watch["000001"]["missing"] is False
        assert watch["000001"]["price"] == 100.0
        assert watch["000001"]["flags"] == ["示例旗标 verbatim"]
        # absent from master + resolve miss -> declared missing
        assert watch["00700"]["missing"] is True
        # in master even though it passes no master gate -> analyzed
        assert watch["000003"]["missing"] is False

    def test_digest_analyze_exception_becomes_missing(self, mail_tmp):
        def _boom(match, snapshot_dir=None, **kwargs):
            raise RuntimeError("quote source down")

        ml.add_subscriber("我", "me@qq.com", ["A:000001"])
        digest = ml.build_digest(
            mail_tmp, ml.load_subscribers(), master=_master_frame(),
            analyze_fn=_boom, resolve_fn=lambda q: [], overlays=False)
        item = digest["watchlist"][0]
        assert item["missing"] is True
        assert "quote source down" in item["reason"]

    def test_digest_json_roundtrip(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com", ["A:000001"])
        digest = ml.build_digest(
            mail_tmp, ml.load_subscribers(), master=_master_frame(),
            analyze_fn=_fake_analyze, resolve_fn=lambda q: [],
            overlays=False)
        payload = json.loads(ml.digest_to_json(digest))
        assert payload["l1_pool"][0]["code"] == "000001"
        assert payload["watchlist"][0]["cores"]["business"] == 80.0

    def test_render_summary_smoke(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com", ["A:000001", "HK:00700"])
        digest = ml.build_digest(
            mail_tmp, ml.load_subscribers(), master=_master_frame(),
            analyze_fn=_fake_analyze, resolve_fn=lambda q: [],
            overlays=False)
        text = ml.render_digest_summary(digest)
        assert "L1 pool" in text and "MISSING" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'build_digest'`

- [ ] **Step 3: 实现（追加到 mail.py）**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: 21 passed

- [ ] **Step 5: Commit**

```powershell
git add polar_star/mail.py tests/test_mail.py
git commit -m "feat(mail): build_digest — L1池+关注股ask摘要素材包,missing如实声明,注入式analyze/resolve"
```

---

### Task 6: CLI 接线（cmd_mail / cmd_subscriber + argparse + docstring）

**Files:**
- Modify: `polar_star/__main__.py`（docstring + 两个 cmd 函数 + parser 注册）
- Test: `tests/test_mail.py`（追加 CLI 冒烟测试）

- [ ] **Step 1: 写失败测试**

Append to `tests/test_mail.py`:

```python
class TestCli:
    def test_subscriber_roundtrip_and_send_dry_run(self, mail_tmp,
                                                   capsys):
        from polar_star.__main__ import main
        assert main(["subscriber", "add", "--name", "我",
                     "--email", "me@qq.com",
                     "--watch", "HK:00700,A:600519"]) == 0
        capsys.readouterr()   # drain the "added ..." line
        assert main(["subscriber", "list", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out[0]["watchlist"] == ["HK:00700", "A:600519"]

        _write_config(mail_tmp)
        letter = mail_tmp / "letter.html"
        letter.write_text("<h1>致股东</h1><p>正文</p>", encoding="utf-8")
        assert main(["mail", "send", "--file", str(letter),
                     "--subject", "北极星日报 2026-10-17",
                     "--data-as-of", "快照 20261017", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "[DRY RUN]" in out
        assert "数据截至：快照 20261017" in out
        # dry-run 不计入 sent.log —— 同一天真发不被拦
        assert not ml.sent_log_path().exists()

    def test_send_without_config_exits(self, mail_tmp, capsys):
        from polar_star.__main__ import main
        main(["subscriber", "add", "--name", "我", "--email", "me@qq.com"])
        letter = mail_tmp / "letter.html"
        letter.write_text("<p>正文</p>", encoding="utf-8")
        with pytest.raises(SystemExit):
            main(["mail", "send", "--file", str(letter),
                  "--subject", "s", "--data-as-of", "a", "--dry-run"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: FAIL — `argparse ... invalid choice: 'subscriber'`

- [ ] **Step 3: 实现 __main__.py 接线**

① 模块 docstring（第 15 行 `python -m polar_star user ...` 之后）插入用法行：

```
    python -m polar_star mail digest [--json]
    python -m polar_star mail send --file X.html --subject "..." --data-as-of "..."
    python -m polar_star subscriber add|remove|list
```

② 在 `cmd_masters_vote` 函数定义之前（第 168 行前）插入两个命令函数：

```python
def cmd_mail(args) -> int:
    """Daily letter: `digest` aggregates the material (freshness-gated
    like every data command); `send` delivers the AI-written letter —
    no gate, it reads no market data."""
    from . import mail as ml
    if args.mail_cmd == "digest":
        if not _check_freshness(args):
            return 1
        try:
            snap_dir = report.resolve_snapshot(args.data_dir,
                                               args.snapshot)
            digest = ml.build_digest(snap_dir, ml.load_subscribers())
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        print(ml.digest_to_json(digest) if args.json
              else ml.render_digest_summary(digest))
        return 0
    # send
    try:
        body = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read {args.file}: {exc}") from None
    try:
        result = ml.send_message(
            ml.load_mail_config(), ml.load_subscribers(), args.subject,
            body, args.data_as_of, force=args.force,
            dry_run=args.dry_run)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from None
    if result.get("dry_run"):
        print(f"[DRY RUN] To: {result['to']}"
              + (f"  Cc: {', '.join(result['cc'])}"
                 if result["cc"] else ""))
        print(result["html"])
    else:
        print(f"sent: To {result['to']}"
              + (f", Cc {len(result['cc'])}" if result["cc"] else "")
              + f" — {result['subject']}")
    return 0


def cmd_subscriber(args) -> int:
    """Subscriber registry management — not freshness-gated (same
    contract as tower/thesis: the registry depends on no snapshot)."""
    from dataclasses import asdict
    from . import mail as ml
    try:
        if args.subscriber_cmd == "add":
            watch = [t.strip() for t in (args.watch or "").split(",")
                     if t.strip()]
            sub = ml.add_subscriber(args.name, args.email, watch)
            print(f"added {sub.email}"
                  + (f" watching {', '.join(sub.watchlist)}"
                     if sub.watchlist else ""))
            return 0
        if args.subscriber_cmd == "remove":
            if not ml.remove_subscriber(args.email):
                raise SystemExit(f"no subscriber {args.email!r}")
            print(f"removed {args.email}")
            return 0
        subs = ml.load_subscribers()
        if args.json:
            print(json.dumps([asdict(s) for s in subs],
                             ensure_ascii=False, indent=2))
        elif not subs:
            print("no subscribers; add one with `python -m polar_star "
                  "subscriber add --name X --email Y`")
        else:
            for s in subs:
                print(f"{s.name} <{s.email}>"
                      + (f"  watch: {', '.join(s.watchlist)}"
                         if s.watchlist else ""))
        return 0
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
```

③ argparse 注册：在 `pdoc = sub.add_parser("doctor", ...)` 块（第 2886 行）之前插入：

```python
    pmail = sub.add_parser(
        "mail", help="daily letter: digest the material / send the letter")
    pmail_sub = pmail.add_subparsers(dest="mail_cmd", required=True)
    pmail_d = pmail_sub.add_parser(
        "digest", help="aggregate today's letter material "
                       "(freshness-gated)")
    pmail_d.add_argument("--json", action="store_true")
    pmail_d.add_argument("--snapshot", default=None)
    pmail_d.add_argument("--data-dir", dest="data_dir", default=None)
    pmail_d.add_argument("--no-check", dest="no_check",
                         action="store_true",
                         help="skip the freshness gate (testing only)")
    pmail_s = pmail_sub.add_parser(
        "send", help="send the AI-written letter via QQ-mail SMTP")
    pmail_s.add_argument("--file", required=True,
                         help="HTML body fragment written by the AI")
    pmail_s.add_argument("--subject", required=True)
    pmail_s.add_argument("--data-as-of", dest="data_as_of",
                         required=True,
                         help="from the digest's data_as_of field")
    pmail_s.add_argument("--force", action="store_true",
                         help="override the one-send-per-day guard")
    pmail_s.add_argument("--dry-run", dest="dry_run",
                         action="store_true",
                         help="assemble and print without sending")
    pmail.set_defaults(func=cmd_mail)

    psubr = sub.add_parser("subscriber",
                           help="manage daily-mail subscribers")
    psubr_sub = psubr.add_subparsers(dest="subscriber_cmd",
                                     required=True)
    psubr_a = psubr_sub.add_parser("add", help="add a subscriber")
    psubr_a.add_argument("--name", required=True)
    psubr_a.add_argument("--email", required=True)
    psubr_a.add_argument("--watch", default="",
                         help="comma-separated MARKET:CODE watchlist, "
                              "e.g. HK:00700,A:600519")
    psubr_r = psubr_sub.add_parser("remove",
                                   help="remove a subscriber")
    psubr_r.add_argument("--email", required=True)
    psubr_l = psubr_sub.add_parser("list", help="list subscribers")
    psubr_l.add_argument("--json", action="store_true")
    psubr.set_defaults(func=cmd_subscriber)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -B -m pytest tests/test_mail.py -q`
Expected: 23 passed

- [ ] **Step 5: Commit**

```powershell
git add polar_star/__main__.py tests/test_mail.py
git commit -m "feat(mail): CLI接线 — mail digest|send + subscriber add|remove|list"
```

---

### Task 7: 全量回归 + AGENTS.md 登记

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 全量测试**

Run: `python -B -m pytest tests -q`
Expected: 全绿（mail 23 个 + 既有套件无回归）

- [ ] **Step 2: CLI 手工冒烟（只读路径）**

Run: `python -m polar_star subscriber list`
Expected: 打印 `no subscribers; add one with ...`（本机 mail/ 尚无名单）

Run: `python -m polar_star mail digest --no-check`
Expected: 打印素材摘要（L1 pool 行数 + watchlist 0 stocks）或快照缺失提示

- [ ] **Step 3: AGENTS.md 登记**

在 `AGENTS.md` 的 "Holding-period dimension" 一节之后插入：

```markdown
## Daily mail (每日邮件)

A daily Buffett-letter-style Chinese letter (user mandate 2026-10-17,
spec `docs/superpowers/specs/2026-10-17-daily-mail-design.md`):
**the machine aggregates, the AI writes, the machine delivers** —
`python -m polar_star mail digest [--json]` builds the material pack
(L1 wide pool + one ask summary per deduped subscriber watch stock;
freshness-gated like every data command), the AI composes the letter
(today's pick via the fused pipeline / a story from its own knowledge
/ watch-stock analyses — 3-5 minute read), and `python -m polar_star
mail send --file X.html --subject "..." --data-as-of "..."` wraps it
in the fixed serif shell and delivers it via QQ-mail SMTP
(To: the sender mailbox, Cc: all subscribers; one send per day unless
`--force`; `--dry-run` prints without sending). Subscribers are
managed with `subscriber add|remove|list`; storage is LOCAL-ONLY
under top-level `mail/` (gitignored, never pushed — SMTP credentials
in `mail/config.json`, hand-edited once). The scheduled task
(TRAE solo, 10:00 daily) runs: doctor → fetch if needed → digest →
write letter → send.
```

- [ ] **Step 4: Commit**

```powershell
git add AGENTS.md
git commit -m "docs: AGENTS.md 登记每日邮件功能（操作手册）"
```

---

## Self-Review 记录

**Spec coverage：** digest 过门 ✓(T6 `_check_freshness`)、send/subscriber 不过门 ✓、
config.json 五键 ✓(T2)、subscribers.json 原子写 ✓(T1 `atomic_write_text`)、
sent.log 防重 ✓(T3)、To/CC+同址跳过 ✓(T3)、MIME html+plain 双格式 ✓(T3)、
排版壳衬线 640px ✓(T2)、data-as-of 页脚 ✓(T2)、missing 股如实声明 ✓(T5)、
L1 池 veto 旗标+graham 列 ✓(T4)、测试 mock SMTP/合成快照/tmp 目录 ✓(T1-T6)。
POOL_MAX=40 为本计划新增实现细节，已在头部声明。

**Type consistency：** `Subscriber(name, email, watchlist)`、`send_message(...) -> dict`
键 `{sent|dry_run, to, cc, subject[, html]}`、digest 键
`{date, data_as_of, snapshot, l1_pool, watchlist}` 跨任务一致；
`_pool_records`/`_resolve_watch`/`_watch_item` 私有名全文统一。
