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
        assert "Georgia" in html          # serif body, AI-invariant
        assert 'class="mast"' in html     # horizontal navy masthead bar
        assert "北极星研究" in html
        assert 'class="stripe"' in html   # red accent stripe
        # single column (mandate 2026-10-21): legacy .cols cells stack
        # full-width unconditionally — phone clients ignore media queries
        assert ".cols td{vertical-align:top;display:block" in html
        assert "width:63%" not in html and "width:37%" not in html
        assert "<h1>致股东</h1><p>正文</p>" in html
        assert "数据截至：快照 20261017" in html
        assert "不构成投资建议" in html

    def test_html_to_text(self):
        text = ml.html_to_text("<h1>标题</h1><p>一<br>二&amp;三</p>")
        assert "<" not in text
        assert "标题" in text and "二&三" in text


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


class TestNavChart:
    """{{NAV_CHART}} -> CID inline PNG (user mandate 2026-10-21:
    收益曲线使用图像展示)."""

    def setup_method(self):
        _FakeSMTP.instances = []

    @staticmethod
    def _curves():
        return [{"id": "s001", "label": "S1 US",
                 "points": [("2026-09-16", 0.0),
                            ("2026-09-17", 1.5),
                            ("2026-09-18", -0.4)]}]

    def test_send_attaches_cid_related_png(self, mail_tmp, monkeypatch):
        from polar_star import mail_chart
        monkeypatch.setattr(mail_chart, "seasons_curves",
                            lambda: self._curves())
        cfg = _write_config(mail_tmp)
        result = ml.send_message(cfg, _subs(), "主题",
                                 "<p>正文</p>{{NAV_CHART}}", "as-of",
                                 today="2026-10-21",
                                 smtp_factory=_FakeSMTP)
        assert result["sent"] is True
        msg, _ = _FakeSMTP.instances[0].sent[0]
        html_part = msg.get_payload()[1]
        assert html_part.get_content_type() == "multipart/related"
        html = html_part.get_payload()[0].get_content()
        assert 'src="cid:nav_curve"' in html
        assert "{{NAV_CHART}}" not in html
        img = html_part.get_payload()[-1]
        assert img.get_content_type() == "image/png"
        assert img["Content-ID"] == "<nav_curve>"   # RFC 2045 brackets
        assert img.get_payload(decode=True)[:8] == b"\x89PNG\r\n\x1a\n"
        # the plain-text alternative carries neither token nor cid
        text = msg.get_payload()[0].get_content()
        assert "{{NAV_CHART}}" not in text and "cid:" not in text

    def test_dry_run_embeds_data_uri_preview(self, mail_tmp, monkeypatch):
        from polar_star import mail_chart
        monkeypatch.setattr(mail_chart, "seasons_curves",
                            lambda: self._curves())
        cfg = _write_config(mail_tmp)
        result = ml.send_message(cfg, _subs(), "主题",
                                 "<p>x</p>{{NAV_CHART}}", "as-of",
                                 dry_run=True)
        # browser-previewable: data URI instead of a dead cid reference
        assert "data:image/png;base64," in result["html"]
        assert "cid:nav_curve" not in result["html"]
        assert "{{NAV_CHART}}" not in result["html"]

    def test_no_curves_leaves_honest_gap_note(self, mail_tmp, monkeypatch):
        from polar_star import mail_chart
        monkeypatch.setattr(mail_chart, "seasons_curves", lambda: [])
        cfg = _write_config(mail_tmp)
        result = ml.send_message(cfg, _subs(), "主题",
                                 "<p>x</p>{{NAV_CHART}}", "as-of",
                                 today="2026-10-21",
                                 smtp_factory=_FakeSMTP)
        assert result["sent"] is True
        msg, _ = _FakeSMTP.instances[0].sent[0]
        # no drawable season -> declared gap, no fabricated image
        assert msg.get_payload()[1].get_content_type() == "text/html"
        assert "三期收益曲线暂缺" in msg.get_payload()[1].get_content()

    def test_body_without_token_gets_no_image_part(self, mail_tmp):
        cfg = _write_config(mail_tmp)
        ml.send_message(cfg, _subs(), "主题", "<p>x</p>", "as-of",
                        today="2026-10-21", smtp_factory=_FakeSMTP)
        msg, _ = _FakeSMTP.instances[0].sent[0]
        assert msg.get_payload()[1].get_content_type() == "text/html"
        assert not any(p.get_content_type() == "image/png"
                       for p in msg.walk())


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

    def test_nan_flags_never_display_as_vetoes(self):
        """Real master.csv carries NaN intel_red for HK/US rows (no intel
        coverage); NaN is not a flag — bool(float('nan')) is True, which
        is exactly the bug this test guards."""
        master = _master_frame()
        master["intel_red"] = [float("nan")] * 3
        pool = ml.build_l1_pool(master, overlays=False)
        records = ml._pool_records(pool)
        assert records[0]["vetoes"] == []

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

    def test_resolve_watch_market_id_comes_from_resolve_chain(self):
        """master.csv carries no market_id column — the secid prefix must
        come from the resolve chain or the live quote dies (2026-10-21
        digest gap); the master hit still wins the canonical name."""
        from polar_star.resolve import Match

        master = pd.DataFrame([{"market": "US", "code": "AAPL",
                                "name": "苹果"}])

        def resolve(q):
            return [Match("US", q.upper(), q.upper(), 90.0, "105")]

        m = ml._resolve_watch("US:AAPL", master, resolve)
        assert m.market_id == "105"
        assert m.name == "苹果"
        assert m.score == 100.0
        # out of master: the resolve chain alone decides
        m2 = ml._resolve_watch("US:AGNC", master, resolve)
        assert m2.market_id == "105"
        assert m2.name == "AGNC"

    def test_digest_watch_price_falls_back_to_snapshot(self, mail_tmp):
        """Every live source down: the watch item still carries the
        snapshot price/pe/pb with an explicit warning — a declared
        fallback, never a fabricated row."""

        def _dead_analyze(match, snapshot_dir=None, **kwargs):
            return {"quote": None, "percentiles": {}, "cores": {},
                    "risk_flags": [], "warnings": ["live quote unavailable"]}

        ml.add_subscriber("我", "me@qq.com", ["A:000001"])
        digest = ml.build_digest(
            mail_tmp, ml.load_subscribers(), master=_master_frame(),
            analyze_fn=_dead_analyze, resolve_fn=lambda q: [],
            overlays=False)
        item = digest["watchlist"][0]
        assert item["missing"] is False
        assert item["price"] == 10.0          # master 000001 snapshot price
        assert item["pe_ttm"] == 12.0
        assert item["pb"] == 1.2
        assert any("snapshot" in w for w in item["warnings"])

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


def _fake_seasons(snap_dir=None):
    return [{"id": "s001", "name": "第一期-纯美股", "base_currency": "USD",
             "initial_capital": 7180.0, "nav": 7648.92, "day_pnl": 12.3,
             "net_return_pct": 6.53, "cash": {"USD": 1493.44},
             "positions": [{"market": "US", "code": "ZM", "name": "Zoom",
                            "qty": 16.0, "price": 94.19, "currency": "USD",
                            "value_base": 1507.04, "avg_cost": 80.0,
                            "unrealized_pnl": 227.04,
                            "unrealized_pnl_pct": 17.74}],
             "last_nav_date": "2026-10-19"}]


class TestDigestSeasons:
    def test_seasons_block_carried(self, mail_tmp):
        ml.add_subscriber("我", "me@qq.com", ["A:000001"])
        digest = ml.build_digest(
            mail_tmp, ml.load_subscribers(), master=_master_frame(),
            analyze_fn=_fake_analyze, resolve_fn=lambda q: [],
            overlays=False, seasons_fn=_fake_seasons)
        assert digest["seasons_error"] is None
        s = digest["seasons"][0]
        assert s["nav"] == 7648.92
        assert s["positions"][0]["unrealized_pnl_pct"] == 17.74
        payload = json.loads(ml.digest_to_json(digest))
        assert payload["seasons"][0]["id"] == "s001"

    def test_seasons_failure_becomes_error_not_crash(self, mail_tmp):
        def _boom(snap_dir=None):
            raise RuntimeError("season store corrupted")

        digest = ml.build_digest(
            mail_tmp, [], master=_master_frame(),
            analyze_fn=_fake_analyze, resolve_fn=lambda q: [],
            overlays=False, seasons_fn=_boom)
        assert digest["seasons"] == []
        assert "season store corrupted" in digest["seasons_error"]

    def test_render_summary_shows_seasons(self, mail_tmp):
        digest = ml.build_digest(
            mail_tmp, [], master=_master_frame(),
            analyze_fn=_fake_analyze, resolve_fn=lambda q: [],
            overlays=False, seasons_fn=_fake_seasons)
        text = ml.render_digest_summary(digest)
        assert "s001" in text and "+6.53%" in text


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
