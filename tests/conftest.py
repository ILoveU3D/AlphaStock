"""Shared test fixtures: neutralize fetch-pipeline rate-limit sleeps so the
suite stays fast enough for sandboxed CI runners."""

import time

import pytest


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
