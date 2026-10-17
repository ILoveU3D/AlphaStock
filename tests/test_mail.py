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
        assert "Georgia" in html          # serif shell, AI-invariant
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
