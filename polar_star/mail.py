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

import base64
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
#
# Research-note shell (user mandate 2026-10-19: HSBC / Morgan Stanley
# daily-note style; layout mandate 2026-10-21: single column for phone
# readers — 邮件取消两栏): horizontal navy masthead bar + red stripe on
# top, headline block (kicker / h1 / .meta band / .standfirst abstract),
# then a one-column body and a dark footer band with the data-as-of
# line. Legacy two-column fragments (table.cols > td.col-main +
# td.col-side) still parse — the cells stack full-width via an
# unconditional display:block, so old letters render single-column
# everywhere, media queries or not (phone mail clients ignore them).
#
# Body-fragment contract (what the AI writes each day, all optional
# except h1):
#   <p class="kicker">每日价值研究 · 2026年10月21日</p>
#   <h1>今日标题</h1>
#   <p class="meta">VALUE DAILY · A股 / 港股 / 美股</p>
#   <div class="standfirst">摘要：一两句话概括今日要点</div>
#   正文区段直接顺序排列（各位股东开场 / 推荐 / 故事 / 分析 / 三期实盘）
# Data tables use <table class="data"> (the three-season P&L is a
# table, user mandate 2026-10-21: 列一个表格展示三期持仓收益以及分析);
# P&L coloring uses .up / .dn (A股 convention red-up green-down);
# .num right-aligns numerics; two chart tokens exist (mandate
# 2026-10-21: 收益曲线使用图像展示; mandate 2026-10-23: 虚拟持仓逐票
# 盈亏用图表呈现、自选股汇总成表不逐条散文) — `mail send` replaces
# them with CID-inline PNGs drawn from the live season data
# (--dry-run embeds a data URI so the preview renders in a browser):
#   {{NAV_CHART}}     three-season cumulative net-return curves
#   {{POSITION_CHART}} per-position unrealized P&L % bars
# ---------------------------------------------------------------------------
LETTER_CSS = """
body{margin:0;padding:24px;background:#e9edf1;}
.letter{max-width:720px;margin:0 auto;background:#ffffff;border:1px solid #d3dae2;
font-family:Georgia,"Times New Roman","Songti SC","SimSun",serif;font-size:15.5px;
line-height:1.8;color:#1c2530;}
.mast{width:100%;border-collapse:collapse;background:#10243e;}
.mast td{padding:13px 28px;}
.mast-l{font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;font-size:18px;
font-weight:bold;color:#ffffff;letter-spacing:6px;}
.mast-r{text-align:right;font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;
font-size:10.5px;color:#8fa3bd;letter-spacing:2px;white-space:nowrap;}
.stripe{height:3px;background:#c80000;}
.content{padding:28px 36px 24px;}
.content p{margin:0 0 12px;}
.kicker{font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;font-size:11px;
font-weight:bold;letter-spacing:3px;color:#c80000;margin-bottom:8px;}
.content h1{font-size:23px;line-height:1.35;color:#10243e;margin:0 0 10px;}
.meta{font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;font-size:11px;
letter-spacing:2px;color:#5a6b7f;border-top:2px solid #10243e;
border-bottom:1px solid #c9d4de;padding:5px 0;margin-bottom:18px;}
.standfirst{background:#f2f5f8;border-left:3px solid #10243e;padding:12px 16px;
font-size:14px;color:#33404d;margin:0 0 22px;}
.content h2{font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;font-size:15.5px;
color:#10243e;letter-spacing:1px;border-left:4px solid #c80000;padding-left:8px;
border-bottom:1px solid #c9d4de;padding-bottom:5px;margin:24px 0 10px;}
.cols{width:100%;border-collapse:collapse;}
.cols td{vertical-align:top;display:block;width:100%;padding-right:0;}
.col-side{padding-top:18px;}
.box{background:#f2f5f8;border:1px solid #dbe3ea;border-top:3px solid #10243e;
padding:10px 12px;margin:0 0 14px;font-size:13px;line-height:1.6;}
.box.red{border-top-color:#c80000;}
.box-t{font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;font-size:11.5px;
font-weight:bold;letter-spacing:1.5px;color:#10243e;border-bottom:1px solid #c9d4de;
padding-bottom:4px;margin-bottom:8px;}
.box p{margin:6px 0;}
.letter table.data{border-collapse:collapse;width:100%;font-size:12.5px;}
.letter table.data th{background:#10243e;color:#ffffff;font-weight:normal;
font-size:11px;letter-spacing:1px;padding:5px 6px;text-align:left;}
.letter table.data td{border-bottom:1px solid #dbe3ea;padding:5px 6px;}
.letter table.data th:first-child,.letter table.data td:first-child{
white-space:nowrap;}
.num{text-align:right;}
.up{color:#c80000;}
.dn{color:#1a7a4a;}
.mut{color:#8a94a0;font-size:11px;}
.footer{margin-top:26px;border-top:2px solid #10243e;padding-top:12px;
font-family:Helvetica,Arial,"Microsoft YaHei",sans-serif;font-size:11px;
color:#8a94a0;line-height:1.6;}
@media only screen and (max-width:620px){
body{padding:8px;}
.content{padding:18px 16px 16px;}
.mast td{padding:10px 16px;}
.content h1{font-size:20px;}
}
"""

MASTHEAD = "北极星研究"
MAST_TAG = "POLAR STAR RESEARCH · VALUE DAILY"

DISCLAIMER = "本邮件为北极星研究服务的个人订阅通讯，不构成投资建议。"


def wrap_letter(body_html: str, data_as_of: str) -> str:
    """Fixed research-note shell: navy masthead bar + red stripe,
    IEEE-like two-column body classes, footer band with the data-as-of
    line (freshness contract) — the AI only writes the body fragment;
    the shell guarantees the bank-note feel every day."""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>{LETTER_CSS}</style></head><body>"
            '<div class="letter">'
            '<table class="mast"><tr>'
            f'<td class="mast-l">{MASTHEAD}</td>'
            f'<td class="mast-r">{MAST_TAG}</td>'
            '</tr></table>'
            '<div class="stripe"></div>\n'
            '<div class="content">\n'
            f'{body_html}\n'
            f'<div class="footer">数据截至：{data_as_of}'
            f"<br>{DISCLAIMER}</div>\n"
            "</div></div></body></html>")


_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    """Plain-text fallback for the MIME alternative part."""
    text = unescape(_TAG_RE.sub("", html))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
NAV_CHART_TOKEN = "{{NAV_CHART}}"
NAV_CHART_CID = "nav_curve"
POSITION_CHART_TOKEN = "{{POSITION_CHART}}"
POSITION_CHART_CID = "pos_pnl"
_CHART_IMG_STYLE = ("display:block;width:100%;max-width:640px;height:auto;"
                    "border:1px solid #dbe3ea;")


def _chart_img(src_cid: str, alt: str, height: int, dry_run: bool,
               png: bytes) -> str:
    if dry_run:
        uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        src = f'src="{uri}"'
    else:
        src = f'src="cid:{src_cid}"'
    return (f'<img {src} width="640" height="{height}" alt="{alt}" '
            f'style="{_CHART_IMG_STYLE}">')


def _nav_chart_html(dry_run: bool) -> tuple:
    """(replacement html, png bytes | None) for the {{NAV_CHART}} token.
    Real sends reference a CID attachment; dry-runs embed a data URI so
    the preview renders in a browser. No drawable season -> an honest
    muted gap note — a missing curve is declared, never faked (user
    mandate 2026-10-21: 收益曲线使用图像展示)."""
    from . import mail_chart
    try:
        curves = mail_chart.seasons_curves()
        if not curves:
            raise ValueError("no active season with >=2 NAV marks")
        png = mail_chart.render_seasons_png(curves)
    except Exception as exc:   # noqa: BLE001 — the chart must never sink the letter
        note = f"三期收益曲线暂缺：{type(exc).__name__}: {exc}"
        return f'<p class="mut">{note}</p>', None
    return _chart_img(NAV_CHART_CID, "三期累计收益曲线", 300, dry_run, png), png


def _position_chart_html(dry_run: bool) -> tuple:
    """(replacement html, png bytes | None) for the {{POSITION_CHART}}
    token — per-position unrealized P&L % bars, one color per season
    (user mandate 2026-10-23: 逐票盈亏用图表呈现). Same honest-gap
    contract as the NAV curve: no positions -> a muted note, never a
    fabricated chart."""
    from . import mail_chart
    try:
        items = mail_chart.positions_pnl()
        if not items:
            raise ValueError("no open positions with cost and price")
        png = mail_chart.render_positions_png(items)
    except Exception as exc:   # noqa: BLE001 — the chart must never sink the letter
        note = f"逐票盈亏图暂缺：{type(exc).__name__}: {exc}"
        return f'<p class="mut">{note}</p>', None
    height = 34 + 26 * len(items) + 26
    return _chart_img(POSITION_CHART_CID, "虚拟持仓逐票浮动盈亏", height,
                      dry_run, png), png


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
    charts = []   # [(cid, png)] — every replaced token attaches its image
    for token, builder in ((NAV_CHART_TOKEN, _nav_chart_html),
                           (POSITION_CHART_TOKEN, _position_chart_html)):
        if token in html:
            img_html, png = builder(dry_run)
            html = html.replace(token, img_html)
            if png is not None:
                cid = (NAV_CHART_CID if token == NAV_CHART_TOKEN
                       else POSITION_CHART_CID)
                charts.append((cid, png))
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
    if charts:
        # RFC 2045 Content-ID needs angle brackets; the matching img src
        # drops them per RFC 2392 (cid:nav_curve / cid:pos_pnl).
        html_part = msg.get_payload()[1]
        for cid, png in charts:
            html_part.add_related(png, maintype="image", subtype="png",
                                  cid=f"<{cid}>")
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
# Digest: seasons P&L (the AI's own three paper-trading seasons)
# ---------------------------------------------------------------------------
def build_seasons_block(snap_dir=None) -> list:
    """Active-season P&L material for the letter (user mandate
    2026-10-19: 每日邮件增加三期持仓盈亏和分析): NAV / day / net return
    plus per-position unrealized P&L (cost merged by
    trade._summary_from). Marking NAV is the designed daily mark —
    the same path `trade status` walks."""
    from . import trade
    out = []
    for s in trade.status_all(snap_dir=snap_dir):
        out.append({"id": s["id"], "name": s["name"],
                    "base_currency": s["base_currency"],
                    "initial_capital": s["initial_capital"],
                    "nav": s["nav"], "day_pnl": s["day_pnl"],
                    "net_return_pct": s["net_return_pct"],
                    "cash": s["cash"], "positions": s["positions"],
                    "last_nav_date": s["last_nav_date"]})
    return out


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
    """'MARKET:CODE' -> Match. The resolve chain supplies market_id (the
    secid prefix live quotes die without — master.csv carries no
    market_id column, 2026-10-21 digest gap); the master hit only wins
    the canonical name + score. None when both miss (the item becomes a
    declared gap)."""
    market, _, code = token.partition(":")
    name, market_id, score = "", "", 0.0
    if resolve_fn is not None:
        for m in resolve_fn(code):
            if m.market == market and m.code == code:
                name, market_id, score = m.name, m.market_id, m.score
                break
    if master is not None:
        hit = master[(master["market"] == market)
                     & (master["code"].astype(str) == code)]
        if not hit.empty:
            r = hit.iloc[0]
            return Match(market, code,
                         str(r.get("name") or name or code), 100.0,
                         market_id)
    if name:
        return Match(market, code, name, score, market_id)
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


def _watch_snapshot_prices(snap_dir: Path, master) -> dict:
    """{(market, code): {price, pe_ttm, pb}} from the snapshot's
    master/watchlist rows — the honest price fallback when every live
    quote source fails (same contract as recommend / holding list)."""
    frames = []
    if master is not None and not master.empty:
        frames.append(master)
    p = Path(snap_dir) / "watchlist.csv"
    if p.exists():
        try:
            frames.append(pd.read_csv(p, dtype={"code": str}))
        except (OSError, pd.errors.ParserError, ValueError):
            pass
    rows: dict = {}
    for df in frames:
        if not {"market", "code", "price"}.issubset(df.columns):
            continue
        for _, r in df.iterrows():
            key = (str(r["market"]), str(r["code"]))
            if key in rows:
                continue
            try:
                price = r.get("price")
                if price is None or pd.isna(price):
                    continue
            except (TypeError, ValueError):
                continue
            rows[key] = {k: (None if pd.isna(r.get(k)) else r.get(k))
                         for k in ("price", "pe_ttm", "pb")}
    return rows


def build_digest(snap_dir, subscribers, master=None, analyze_fn=None,
                 resolve_fn=None, overlays: bool = True,
                 seasons_fn=None) -> dict:
    """Aggregate today's letter material: the L1 pool (recommendation
    half) + one ask summary per deduped subscriber watch stock + the
    active-seasons P&L block. analyze_fn/resolve_fn/seasons_fn are
    injectable so tests never touch the network; a stock that fails
    becomes a missing item the AI must declare, never a fabricated
    row; a seasons failure becomes seasons_error, same contract."""
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
    if seasons_fn is None:
        seasons_fn = build_seasons_block
    pool = build_l1_pool(master, overlays=overlays)
    try:
        seasons, seasons_error = seasons_fn(snap_dir), None
    except Exception as exc:   # seasons must never sink the digest
        seasons, seasons_error = [], f"{type(exc).__name__}: {exc}"
    watch = []
    snapshot_prices = _watch_snapshot_prices(snap_dir, master)
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
            item = _watch_item(m, analyze_fn(m, snapshot_dir=snap_dir))
        except Exception as exc:   # one stock must never sink the digest
            watch.append({"market": m.market, "code": m.code,
                          "name": m.name, "missing": True,
                          "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if item.get("price") is None or item.get("pe_ttm") is None \
                or item.get("pb") is None:
            row = snapshot_prices.get((m.market, str(m.code)))
            filled = []
            if row is not None:
                for k in ("price", "pe_ttm", "pb"):
                    if item.get(k) is None and row.get(k) is not None:
                        item[k] = row[k]
                        filled.append(k)
            if filled:
                item["warnings"].append(
                    "live quote silent on " + "/".join(filled)
                    + f"; filled from snapshot {Path(snap_dir).name}")
        watch.append(item)
    return {"date": date.today().isoformat(),
            "data_as_of": _data_as_of(snap_dir),
            "snapshot": snap_dir.name,
            "l1_pool": _pool_records(pool),
            "watchlist": watch,
            "seasons": seasons,
            "seasons_error": seasons_error}


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
    if digest.get("seasons_error"):
        lines.append(f"seasons: ERROR ({digest['seasons_error']})")
    else:
        lines.append(f"seasons: {len(digest.get('seasons') or [])} active")
    for s in digest.get("seasons") or []:
        lines.append(f"  {s['id']} {s['name']}  NAV {s['nav']:,.2f} "
                     f"{s['base_currency']}  day {s['day_pnl']:+,.2f}  "
                     f"net {s['net_return_pct']:+.2f}%  "
                     f"positions {len(s['positions'])}")
    return "\n".join(lines)
