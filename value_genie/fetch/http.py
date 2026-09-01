"""HTTP layer: resilient GET client with retry, backoff and rate-limit cooldown.

Shared by all data source modules (Eastmoney, Tencent, SEC EDGAR).
"""

import json
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .. import config


def num(v):
    """Coerce an API value to float; return None for null-ish inputs."""
    if v is None or v == "-" or v == "":
        return None
    try:
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


class Fetcher:
    """HTTP client with automatic retries and rate-limit cooldown.

    After `cooldown_after` consecutive failures the client sleeps
    `cooldown_sec` before the next attempt, which recovers gracefully from
    Eastmoney's transient rate limiting.
    """

    def __init__(self, headers, name="http"):
        self.name = name
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
        attempt = 0
        total_attempts = retries + 1
        while attempt < total_attempts:
            attempt += 1
            try:
                deadline = time.monotonic() + total_timeout
                with self.session.get(url, params=params, timeout=timeout,
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
                    return json.loads(body)
                if status == 404:
                    self.consecutive_fail = 0
                    return None
                last_err = f"HTTP {status}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
            self.consecutive_fail += 1
            if self.consecutive_fail >= cooldown_after and attempt < total_attempts:
                print(f"    [cooldown] {self.name} failed "
                      f"{self.consecutive_fail}x ({last_err}), "
                      f"sleeping {cooldown_sec}s...")
                time.sleep(cooldown_sec)
            else:
                time.sleep(2.0 * attempt)
        print(f"    [warn] {self.name} request failed: {url[:70]} -> {last_err}")
        return None


# Shared client instances (one per data source).
EM = Fetcher({"User-Agent": config.EM_UA}, "EM")        # push2 quotes/klines
DC = Fetcher({"User-Agent": config.EM_UA}, "DC")        # datacenter reports
SEC = Fetcher(config.SEC_HEADERS, "SEC")                # SEC EDGAR frames
TX = Fetcher(config.TX_UA, "TX")                        # Tencent fallback

# push2 mirror rotation with failure avoidance: a host that just failed is
# skipped for EM_HOST_COOLDOWN seconds, so a blocked mirror costs one quick
# attempt instead of a retry storm (http only; https gets connection-reset).
_em_host_fail: dict = {}


def em_push2_get(path: str, params: dict | None = None, timeout: int = 20):
    """GET a push2 API path, rotating across mirror hosts on failure.

    Returns parsed JSON from the first healthy host, or None when every
    mirror fails. When all mirrors are in cooldown the one that failed
    longest ago is retried, so the rotation always makes progress.
    """
    now = time.monotonic()
    healthy = [h for h in config.EM_PUSH2_HOSTS
               if now - _em_host_fail.get(h, -1e9) >= config.EM_HOST_COOLDOWN]
    if not healthy:
        healthy = [min(config.EM_PUSH2_HOSTS,
                       key=lambda h: _em_host_fail.get(h, -1e9))]
    for host in healthy:
        d = EM.get_json(f"http://{host}{path}", params=params,
                        timeout=timeout, retries=0)
        if d is not None:
            return d
        _em_host_fail[host] = time.monotonic()
    return None
