"""HTTP layer: resilient GET client with retry, backoff and rate-limit cooldown.

Shared by all data source modules (Eastmoney, Tencent, SEC EDGAR). Every
Fetcher carries a ``source_id``; persistent failures and successes are
recorded into fetch.health so the registry can demote a source that
keeps refusing connections (dynamic priority).
"""

import json
import sys
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .. import config
from .health import get_health


def num(v):
    """Coerce an API value to float; return None for null-ish inputs."""
    if v is None or v == "-" or v == "":
        return None
    try:
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _status_error(status: int) -> requests.HTTPError:
    """An HTTPError carrying its status code, for health grading."""
    err = requests.HTTPError(f"HTTP {status}")
    err.response = requests.Response()
    err.response.status_code = status
    return err


class Fetcher:
    """HTTP client with automatic retries and rate-limit cooldown.

    After `cooldown_after` consecutive failures the client sleeps
    `cooldown_sec` before the next attempt, which recovers gracefully from
    Eastmoney's transient rate limiting.
    """

    def __init__(self, headers, name="http", source_id=""):
        self.name = name
        # registry source this client belongs to; "" disables health
        # recording (ad-hoc clients outside the source registry)
        self.source_id = source_id
        # in-flight call cap per family: parallel pipeline stages share
        # the client without hammering one host
        workers = config.FETCH_WORKERS.get(
            name, config.FETCH_WORKERS.get("default", 4))
        self._slots = threading.Semaphore(workers)
        self.consecutive_fail = 0
        self.session = requests.Session()
        self.session.headers.update(headers)
        retry = Retry(total=4, connect=2, read=2, backoff_factor=0.5,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=frozenset(["GET", "HEAD"]))
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8,
                               pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_json(self, url, params=None, timeout=20, retries=2,
                 cooldown_after=5, cooldown_sec=75, total_timeout=None):
        """GET a URL and parse JSON. Returns None on persistent failure.

        `timeout` is the per-read socket timeout; `total_timeout`
        (default: max(45, 3x timeout)) caps the whole download so a
        trickle-fed connection cannot stall the pipeline forever.
        A 404 is treated as "no data" (returns None without retry).
        """
        total_timeout = total_timeout or max(45, timeout * 3)
        last_err = None
        last_exc = None
        attempt = 0
        total_attempts = retries + 1
        with self._slots:
            while attempt < total_attempts:
                attempt += 1
                try:
                    deadline = time.monotonic() + total_timeout
                    with self.session.get(url, params=params,
                                          timeout=timeout,
                                          stream=True) as r:
                        chunks = []
                        for chunk in r.iter_content(chunk_size=65536):
                            chunks.append(chunk)
                            if time.monotonic() > deadline:
                                raise requests.Timeout(
                                    f"download exceeded {total_timeout}s")
                        body = b"".join(chunks)
                        status = r.status_code
                    if status == 200:
                        self.consecutive_fail = 0
                        self._health_success()
                        return json.loads(body)
                    if status == 404:
                        self.consecutive_fail = 0
                        return None
                    last_err = f"HTTP {status}"
                    last_exc = _status_error(status)
                except Exception as e:  # noqa: BLE001
                    last_err = f"{type(e).__name__}: {str(e)[:120]}"
                    last_exc = e
                self.consecutive_fail += 1
                if self.consecutive_fail >= cooldown_after and attempt < total_attempts:
                    print(f"    [cooldown] {self.name} failed "
                          f"{self.consecutive_fail}x ({last_err}), "
                          f"sleeping {cooldown_sec}s...", file=sys.stderr)
                    time.sleep(cooldown_sec)
                else:
                    time.sleep(2.0 * attempt)
        print(f"    [warn] {self.name} request failed: {url[:70]} -> "
              f"{last_err}", file=sys.stderr)
        self._health_failure(last_exc)
        return None

    def get_text(self, url, params=None, timeout=20, retries=2,
                 cooldown_after=5, cooldown_sec=75, total_timeout=None):
        """GET a URL and return the body as text (for HTML pages).
        None on persistent failure; 404 counts as no data."""
        body = self._fetch("GET", url, params=params, timeout=timeout,
                           retries=retries, cooldown_after=cooldown_after,
                           cooldown_sec=cooldown_sec,
                           total_timeout=total_timeout)
        if body is None:
            return None
        enc = getattr(self, "_last_encoding", None)
        return body.decode(enc or "utf-8", errors="replace")

    def get_bytes(self, url, params=None, timeout=60, retries=1,
                  cooldown_after=5, cooldown_sec=75, total_timeout=None):
        """GET a URL and return raw bytes (PDFs etc.).
        None on persistent failure; 404 counts as no data."""
        return self._fetch("GET", url, params=params, timeout=timeout,
                           retries=retries, cooldown_after=cooldown_after,
                           cooldown_sec=cooldown_sec,
                           total_timeout=total_timeout)

    def post_json(self, url, data=None, timeout=20, retries=2,
                  cooldown_after=5, cooldown_sec=75, total_timeout=None):
        """POST form data and parse JSON (cninfo disclosure APIs).
        None on persistent failure; 404 counts as no data."""
        body = self._fetch("POST", url, data=data, timeout=timeout,
                           retries=retries, cooldown_after=cooldown_after,
                           cooldown_sec=cooldown_sec,
                           total_timeout=total_timeout)
        if body is None:
            return None
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _fetch(self, method, url, params=None, data=None, timeout=20,
               retries=2, cooldown_after=5, cooldown_sec=75,
               total_timeout=None):
        """Shared retry/backoff core: returns raw body bytes or None."""
        total_timeout = total_timeout or max(45, timeout * 3)
        last_err = None
        last_exc = None
        attempt = 0
        total_attempts = retries + 1
        with self._slots:
            while attempt < total_attempts:
                attempt += 1
                try:
                    deadline = time.monotonic() + total_timeout
                    req = (self.session.post if method == "POST"
                           else self.session.get)
                    kwargs = {"timeout": timeout, "stream": True}
                    if method == "POST":
                        kwargs["data"] = data
                    else:
                        kwargs["params"] = params
                    with req(url, **kwargs) as r:
                        chunks = []
                        for chunk in r.iter_content(chunk_size=65536):
                            chunks.append(chunk)
                            if time.monotonic() > deadline:
                                raise requests.Timeout(
                                    f"download exceeded {total_timeout}s")
                        body = b"".join(chunks)
                        status = r.status_code
                        self._last_encoding = (
                            r.encoding if isinstance(r.encoding, str)
                            else None)
                    if status == 200:
                        self.consecutive_fail = 0
                        self._health_success()
                        return body
                    if status == 404:
                        self.consecutive_fail = 0
                        return None
                    last_err = f"HTTP {status}"
                    last_exc = _status_error(status)
                except Exception as e:  # noqa: BLE001
                    last_err = f"{type(e).__name__}: {str(e)[:120]}"
                    last_exc = e
                self.consecutive_fail += 1
                if self.consecutive_fail >= cooldown_after and attempt < total_attempts:
                    print(f"    [cooldown] {self.name} failed "
                          f"{self.consecutive_fail}x ({last_err}), "
                          f"sleeping {cooldown_sec}s...", file=sys.stderr)
                    time.sleep(cooldown_sec)
                else:
                    time.sleep(2.0 * attempt)
        print(f"    [warn] {self.name} request failed: {url[:70]} -> "
              f"{last_err}", file=sys.stderr)
        self._health_failure(last_exc)
        return None

    def _health_success(self):
        if self.source_id:
            get_health().record_success(self.source_id)

    def _health_failure(self, exc):
        if self.source_id:
            get_health().record_failure(self.source_id, exc)


# Shared client instances (one per data source). source_id ties each
# client to the registry for health tracking; the semaphore bounds
# concurrent requests per family (config.FETCH_WORKERS) so the parallel
# pipeline stays polite per host.
EM = Fetcher({"User-Agent": config.EM_UA}, "EM",
             source_id="eastmoney")      # push2 quotes/klines
DC = Fetcher({"User-Agent": config.EM_UA}, "DC",
             source_id="eastmoney")      # datacenter reports
SEC = Fetcher(config.SEC_HEADERS, "SEC",
              source_id="sec_edgar")     # SEC EDGAR frames
TX = Fetcher(config.TX_UA, "TX",
             source_id="tencent")        # Tencent fallback
EM_WEB = Fetcher({"User-Agent": config.EM_UA}, "EM_WEB",
                 source_id="eastmoney")  # np-anotice / np-listapi / reportapi
SA = Fetcher({"User-Agent": config.EM_UA}, "SA",
             source_id="stockanalysis")  # stockanalysis.com HTML

# push2 mirror rotation with failure avoidance: a host that just failed is
# skipped for EM_HOST_COOLDOWN seconds, so a blocked mirror costs one quick
# attempt instead of a retry storm (http only; https gets connection-reset).
_em_host_fail: dict = {}


def em_push2_get(path: str, params: dict | None = None, timeout: int = 20):
    """GET a push2 API path, rotating across mirror hosts on failure.

    Returns parsed JSON from the first healthy host, or None when every
    mirror fails. When all mirrors are in cooldown the call fails fast
    (an all-mirror failure signature is a client-side block, not a
    single-host blip) so the Tencent fallback runs instead.
    """
    now = time.monotonic()
    healthy = [h for h in config.EM_PUSH2_HOSTS
               if now - _em_host_fail.get(h, -1e9) >= config.EM_HOST_COOLDOWN]
    if not healthy:
        # every mirror failed within the cooldown window — that signature
        # means a client-side block (IP rate-limit), not a single-host
        # blip; fail fast so the caller's Tencent fallback runs instead
        # of burning one full timeout per request for the whole run
        return None
    for host in healthy:
        d = EM.get_json(f"http://{host}{path}", params=params,
                        timeout=timeout, retries=0)
        if d is not None:
            return d
        _em_host_fail[host] = time.monotonic()
    return None
