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
