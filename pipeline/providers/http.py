"""Polite HTTP for live providers: one UA, per-host delay, retries on 5xx, and a site that refuses
(429, 403) is not hammered: a short Retry-After is honoured once, and a host that refuses twice in a
row is not asked again this run (providers/politeness.py has the rules across nights).

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
_refusals: dict[str, int] = {}   # host -> refusals in a row this run
REFUSED = (429, 403)
STOP_AFTER = 2


class FetchError(RuntimeError):
    """A fetch that failed. An HTTP error keeps its status and body, so the raw store can keep the response too."""

    def __init__(self, message: str, status: int | None = None, body: bytes | None = None, url: str | None = None):
        super().__init__(message)
        self.status, self.body, self.url = status, body, url
        self.parts: tuple = ()   # a combined fetch's responses received before this one failed


class Blocked(FetchError):
    """Not asked: the host refused STOP_AFTER times in a row this run. Nothing was sent, so nothing is kept."""


def reset_refusals() -> None:
    _refusals.clear()


def fetch_url(url: str, ctx: Context, *, headers: dict | None = None, accept: str = "text/html",
              retries: int = 2, timeout: int = 40, data: bytes | None = None) -> Fetched:
    """GET the url (POST it when `data` is given), politely per host, with retries on 429/5xx."""
    host = urlparse(url).netloc
    if _refusals.get(host, 0) >= STOP_AFTER:
        raise Blocked(f"{url} -> not asked: {host} refused {_refusals[host]} times in a row this run", url=url)
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
                _refusals[host] = 0
                return Fetched(url=url, status_code=r.status, body=body, content_type=r.headers.get("Content-Type"))
        except urllib.error.HTTPError as e:
            _last_hit[host] = time.monotonic()
            if e.code in REFUSED:
                # Asked to slow down: wait a short Retry-After out once; otherwise stop, and count it.
                try:
                    retry_after = float(e.headers.get("Retry-After") or "")
                except ValueError:
                    retry_after = None
                if retry_after is not None and retry_after <= 120 and attempt == 0 and retries:
                    time.sleep(retry_after)
                    last_exc = e
                    continue
                _refusals[host] = _refusals.get(host, 0) + 1
            elif e.code in (500, 502, 503, 504) and attempt < retries:
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
