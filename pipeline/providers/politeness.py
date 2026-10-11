"""How hard to lean on a site tonight, from how it answered on earlier nights.

Sites throttle (EV Database answers 429 after a few dozen car pages, and some nights at the
first one). That is normal, not a failure: a page not fetched tonight costs nothing, since the
build keeps what earlier pages said, and it is asked for again on a later night. The rules:

  back off    a night that ended in a refusal (429, or 403) is followed by a pause of one
              night, then two, four, eight, sixteen, as long as nights keep ending in refusals
  ramp up     the first night back asks for a few pages, and each clean night after it twice
              as many, up to the provider's usual number
  never twice in one run  http.fetch_url stops asking a host that has refused twice in a row
              this run (its other pages wait for another night)

Everything here is read from the raw store's index, where every answer is kept, so there is
no state of its own to keep.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

REFUSED = (429, 403)
START = 10
MAX_PAUSE_NIGHTS = 16


def _nights(store, host: str) -> list[tuple[date, bool]]:
    """(night, whether it ended in a refusal) for every night we asked `host` anything, oldest first.
    A night runs from noon to noon UTC, so one scrape after midnight is one night."""
    by: dict[date, bool] = {}
    for e in store.entries():
        if e.get("origin") not in ("live", None) or e.get("role") == "part" or urlparse(e.get("url") or "").netloc != host:
            continue
        night = (datetime.fromisoformat(e["fetched_at"]) - timedelta(hours=12)).date()
        by[night] = by.get(night, False) or e.get("status") in REFUSED
    return sorted(by.items())


def allowance(store, host: str, usual: int, now: datetime | None = None) -> int:
    """How many pages to ask `host` for tonight: 0 while backing off, else START doubled for each clean
    night since the last refusal, up to `usual`. With no store (a test, a hand run) the usual number."""
    if store is None:
        return usual
    nights = _nights(store, host)
    if not nights:
        return usual
    today = ((now or datetime.now(timezone.utc)) - timedelta(hours=12)).date()   # tonight, labelled like the others
    refused_streak = 0
    for _, refused in reversed(nights):
        if not refused:
            break
        refused_streak += 1
    if refused_streak:
        pause = min(2 ** (refused_streak - 1), MAX_PAUSE_NIGHTS)
        if (today - nights[-1][0]).days <= pause:
            return 0
        return min(START, usual)
    last_refusal = next((n for n, refused in reversed(nights) if refused), None)
    if last_refusal is None:
        return usual
    clean = sum(1 for n, refused in nights if n > last_refusal and not refused)
    return min(usual, START * 2 ** clean)


def recently_missing(store, source: str, days: int = 7, today: datetime | None = None) -> set[str]:
    """Targets of `source` whose latest answer, within the last `days`, was a 404: a guessed page the site
    does not have. Asked again once that answer is older than `days`."""
    if store is None:
        return set()
    cutoff = ((today or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
    latest: dict[str, tuple[str, int | None]] = {}
    for e in store.entries():
        if e["source"] == source and e.get("origin") == "live" and e.get("role") != "part":
            if e["target"] not in latest or e["fetched_at"] >= latest[e["target"]][0]:
                latest[e["target"]] = (e["fetched_at"], e.get("status"))
    return {t for t, (at, status) in latest.items() if status == 404 and at >= cutoff}
