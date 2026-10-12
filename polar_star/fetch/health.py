"""Per-source health tracking: dynamic priority demotion after failures.

A source that keeps refusing connections (Eastmoney's intermittent IP
blocks) sinks automatically: the registry's ``ordered_sources`` adds this
penalty on top of the static priority, so fallbacks (Tencent) take over
without any code change. Persisted to ``data/source_health.json`` —
regenerable run-time state: a lost file just resets every source to
healthy. Pure bookkeeping; ``fetch.driver`` and the instrumented HTTP
layer (``fetch.http``) are the producers, ``registry.ordered_sources``
the consumer.
"""

import json
import threading
import time
from pathlib import Path

import requests

from .. import config
from ..atomic import atomic_write_text

COOLDOWN_SEC = 3600.0       # aligned with config.EM_HOST_COOLDOWN
COOLDOWN_AFTER = 5          # accumulated failure weight before cooldown
FAIL_PENALTY = 50           # ordering penalty per consecutive failure
COOLDOWN_PENALTY = 1000     # dominates every static priority


def _grade(exc) -> int:
    """Failure weight: connection-refused classes sink a source fastest
    (3), server/timeout errors next (2), empty data / parse issues are
    the mildest (1) — the source works, the data is just suspect."""
    if exc is None:
        return 1
    if isinstance(exc, (requests.ConnectionError, requests.ConnectTimeout)):
        return 3
    if isinstance(exc, requests.Timeout):
        return 2
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int) and status >= 500:
        return 2
    return 1


class SourceHealth:
    """Failure counts + cooldown windows per source id (thread-safe)."""

    def __init__(self, path=None):
        self.path = (Path(path) if path
                     else config.DATA_DIR / "source_health.json")
        self._lock = threading.Lock()
        self._dirty = False
        # id -> {"fails": float, "weight": int, "until": float}
        self._state: dict = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state = {k: v for k, v in raw.items()
                               if isinstance(v, dict)}
        except (OSError, ValueError):
            self._state = {}

    def save(self):
        """Atomic write; no-op when nothing changed since load/save."""
        with self._lock:
            if not self._dirty:
                return
            payload = json.dumps(self._state, indent=1)
            self._dirty = False
        try:
            atomic_write_text(self.path, payload)
        except OSError:
            pass

    def penalty(self, source_id: str) -> int:
        with self._lock:
            st = self._state.get(source_id) or {}
        p = int(st.get("fails", 0)) * FAIL_PENALTY
        if float(st.get("until", 0.0)) > time.time():
            p += COOLDOWN_PENALTY
        return p

    def record_success(self, source_id: str):
        """A working request clears the consecutive-failure count."""
        with self._lock:
            if self._state.pop(source_id, None) is not None:
                self._dirty = True

    def record_failure(self, source_id: str, exc=None):
        """Accumulate a graded failure; >= COOLDOWN_AFTER weight parks
        the source for COOLDOWN_SEC and restarts the count."""
        w = _grade(exc)
        with self._lock:
            st = self._state.setdefault(
                source_id, {"fails": 0, "weight": 0, "until": 0.0})
            st["fails"] += w
            st["weight"] = w
            if st["fails"] >= COOLDOWN_AFTER:
                st["until"] = time.time() + COOLDOWN_SEC
                st["fails"] = 0
            self._dirty = True


_HEALTH: SourceHealth | None = None


def get_health() -> SourceHealth:
    """Process-wide tracker, lazily loaded from data/source_health.json."""
    global _HEALTH
    if _HEALTH is None:
        _HEALTH = SourceHealth()
    return _HEALTH
