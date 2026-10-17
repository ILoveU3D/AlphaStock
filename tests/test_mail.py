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
