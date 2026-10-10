"""Polite HTTP for live providers: one UA, per-host delay, retries on 429/5xx.

urllib honours HTTPS_PROXY and the system CA store, so this works both in the
cloud session (egress proxy) and on a laptop.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from pipeline.providers.types import Context, Fetched

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0 Safari/537.36")
_last_hit: dict[str, float] = {}


class FetchError(RuntimeError):
    """A fetch that failed. An HTTP error keeps its status and body, so the raw store can keep the response too."""

    def __init__(self, message: str, status: int | None = None, body: bytes | None = None, url: str | None = None):
        super().__init__(message)
        self.status, self.body, self.url = status, body, url


def fetch_url(url: str, ctx: Context, *, headers: dict | None = None, accept: str = "text/html",
              retries: int = 2, timeout: int = 40, data: bytes | None = None) -> Fetched:
    """GET the url (POST it when `data` is given), politely per host, with retries on 429/5xx."""
    host = urlparse(url).netloc
    wait = _last_hit.get(host, 0.0) + ctx.delay_seconds - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Accept": accept, "Accept-Language": "en-GB,en;q=0.9", **(headers or {}),
    })
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                _last_hit[host] = time.monotonic()
                return Fetched(url=url, status_code=r.status, body=body, content_type=r.headers.get("Content-Type"))
        except urllib.error.HTTPError as e:
            _last_hit[host] = time.monotonic()
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2.0 * (2 ** attempt))
                last_exc = e
                continue
            try:
                err_body = e.read()
            except Exception:  # noqa: BLE001
                err_body = None
            raise FetchError(f"{url} -> HTTP {e.code}", status=e.code, body=err_body, url=url) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(2.0 * (2 ** attempt))
                continue
            raise FetchError(f"{url} -> {e}", url=url) from e
    raise FetchError(f"{url} -> {last_exc}")
