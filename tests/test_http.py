"""Tests for value_genie.fetch.http (no network)."""

import json
from unittest.mock import MagicMock, patch

import requests

from value_genie.fetch import http


class TestNum:
    def test_numeric_string(self):
        assert http.num("12.5") == 12.5

    def test_int(self):
        assert http.num(7) == 7.0

    def test_none_like(self):
        assert http.num(None) is None
        assert http.num("-") is None
        assert http.num("") is None

    def test_nan(self):
        assert http.num(float("nan")) is None

    def test_garbage(self):
        assert http.num("abc") is None


def _mock_response(status, body: bytes = b""):
    """A response mock supporting stream-style `with` + iter_content."""
    resp = MagicMock()
    resp.status_code = status
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.iter_content.return_value = [body] if body else []
    return resp


class TestFetcher:
    def _fetcher_with(self, status, json_body=None, exc=None):
        f = http.Fetcher({"User-Agent": "test"}, "T")
        body = json.dumps(json_body).encode() if json_body is not None else b""
        resp = _mock_response(status, body)
        with patch.object(f.session, "get", side_effect=(exc or MagicMock(return_value=resp))):
            yield f, resp

    def test_ok_json(self):
        gen = self._fetcher_with(200, {"data": 1})
        f, _ = next(gen)
        assert f.get_json("http://x", retries=0) == {"data": 1}

    def test_404_returns_none(self):
        gen = self._fetcher_with(404)
        f, _ = next(gen)
        assert f.get_json("http://x", retries=0) is None
        assert f.consecutive_fail == 0

    def test_persistent_failure_returns_none(self):
        gen = self._fetcher_with(500)
        f, _ = next(gen)
        assert f.get_json("http://x", retries=1) is None

    def test_exception_path(self):
        gen = self._fetcher_with(200, exc=requests.ConnectionError("boom"))
        f, _ = next(gen)
        assert f.get_json("http://x", retries=0) is None
        assert f.consecutive_fail == 1

    def test_success_resets_fail_counter(self):
        f = http.Fetcher({"User-Agent": "test"}, "T")
        f.consecutive_fail = 4
        resp = _mock_response(200, b'{"ok": true}')
        with patch.object(f.session, "get", return_value=resp):
            assert f.get_json("http://x", retries=0) == {"ok": True}
        assert f.consecutive_fail == 0

    def test_total_timeout_stops_trickle_download(self):
        """A response that trickles forever is cut by the total deadline."""
        import itertools

        f = http.Fetcher({"User-Agent": "test"}, "T")
        resp = _mock_response(200)
        resp.iter_content.return_value = itertools.repeat(b"chunk")
        clock = itertools.count()
        with patch.object(f.session, "get", return_value=resp), \
                patch.object(http.time, "monotonic", side_effect=clock), \
                patch.object(http.time, "sleep", lambda s: None):
            assert f.get_json("http://x", retries=0, total_timeout=1) is None


def test_em_push2_get_rotates_and_cooldowns():
    """First host success short-circuits; failed hosts are skipped."""
    calls = []

    def fake_get_json(url, params=None, **kw):
        calls.append(url)
        if "h1" in url:
            return None  # first mirror is down
        return {"ok": True}

    http._em_host_fail.clear()
    with patch.object(http.EM, "get_json", side_effect=fake_get_json), \
            patch.object(http.config, "EM_PUSH2_HOSTS",
                         ["h1", "h2", "h3"]):
        assert http.em_push2_get("/api/x") == {"ok": True}
    assert calls == ["http://h1/api/x", "http://h2/api/x"]
    # h1 failed -> it is in cooldown now
    assert "h1" in http._em_host_fail
    http._em_host_fail.clear()


def test_em_push2_get_all_hosts_failed():
    http._em_host_fail.clear()
    with patch.object(http.EM, "get_json", return_value=None), \
            patch.object(http.config, "EM_PUSH2_HOSTS", ["h1", "h2"]):
        assert http.em_push2_get("/api/x") is None
        assert set(http._em_host_fail) == {"h1", "h2"}
        # every host cooling down -> the least-recently-failed one is
        # retried (rotation always makes progress), and can recover
        with patch.object(http.EM, "get_json", return_value={"ok": 1}) as em:
            assert http.em_push2_get("/api/x") == {"ok": 1}
            em.assert_called_once()
    http._em_host_fail.clear()
