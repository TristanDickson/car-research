"""Carwow's configurator, one page per derivative:
https://quotes.carwow.co.uk/car_configuration/choose-options?cap_derivative_id=<cap>&…

Public, server-rendered. The page embeds a JSON block with every option the
derivative can be ordered with (name, category, price, whether it is fitted by
default) and every pack, with the options each pack bundles. It is the one
source that says what a derivative can be *given*: the trim's standard list
says what it has, this says what it can have, by option or by pack, and at
what price. A feature in neither, on a complete page, is not available.

Emits one 'options' record per derivative, the registry Gold keeps in
`options`; the claims model (services/claims.py) turns it into option, pack and
absence claims. Which derivatives to read comes from the derivative registry
(carwow_model) and the specification rows.
"""
from __future__ import annotations

import html as H
import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from pipeline.providers.http import fetch_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for, original_url

SITE = "carwow-cap"
FRESH_DAYS = 7
PER_RUN = 250   # about ten minutes at the polite pace
CHOOSER_RE = re.compile(r"<carwow-options-chooser([^>]*)>", re.S)
ATTR_RE = re.compile(r"([a-z_]+)='([^']*)'")


def configurator_url(cap_id: str, version_date: str | None, engine: str | None, make_slug: str, configurator_model: str) -> str:
    q = {"cap_derivative_id": cap_id, "derivative_version_id": f"car_{cap_id}_{version_date}" if version_date else f"car_{cap_id}",
         "doors": "Front & Rear", "engine_name": engine or "", "fuel": "Electric", "make": make_slug, "model": configurator_model,
         "transmission": "Automatic"}
    return "https://quotes.carwow.co.uk/car_configuration/choose-options?" + urlencode(q)


def _targets(conn: sqlite3.Connection) -> Iterator[tuple[str, str]]:
    """(cap_id, configurator URL): every derivative the registry names (its own configurator link), then
    every specification-page derivative the registry does not, with the model's configurator slug borrowed
    from a registry row of the same model."""
    seen: set[str] = set()
    model_slug: dict[tuple[str, str], str] = {}
    for r in conn.execute("SELECT cap_id, make_slug, model_slug, payload FROM derivatives ORDER BY make_slug, model_slug, cap_id"):
        p = json.loads(r["payload"])
        if p.get("configurator_model"):
            model_slug.setdefault((r["make_slug"], r["model_slug"]), p["configurator_model"])
        url = p.get("configurator_url") or (configurator_url(r["cap_id"], p.get("version_date"), p.get("engine"), r["make_slug"], p["configurator_model"]) if p.get("configurator_model") else None)
        if not url:
            continue
        seen.add(r["cap_id"])
        yield r["cap_id"], url
    for r in conn.execute("SELECT cap_id, version_date, payload FROM specs WHERE spec_key LIKE 'carwow-cap:%' AND cap_id IS NOT NULL ORDER BY cap_id"):
        if r["cap_id"] in seen:
            continue
        p = json.loads(r["payload"])
        cm = model_slug.get(((p.get("make_slug") or "").lower(), p.get("model_slug") or ""))
        if not cm:
            continue
        seen.add(r["cap_id"])
        yield r["cap_id"], configurator_url(r["cap_id"], r["version_date"], p.get("engine"), (p.get("make_slug") or "").lower(), cm)


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    """A derivative's options seldom change, and there are a thousand of them: a run reads the ones never
    read, then those last read more than FRESH_DAYS ago, stalest first, PER_RUN at most, so the nightly
    reads spread over the week. A named target is read regardless."""
    conn: sqlite3.Connection | None = ctx.extras.get("db")
    if conn is None:
        return
    try:
        every = list(_targets(conn))
        last = {r["cap_id"]: r["last_seen_at"] for r in conn.execute("SELECT cap_id, last_seen_at FROM options")}
    except sqlite3.OperationalError:
        return
    if target.identifier != "all":
        for cap, url in every:
            if target.identifier in ("all", cap):
                yield Target(identifier=cap, metadata={"cap_id": cap, "url": url})
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)).isoformat()
    due = [(last.get(cap) or "", i, cap, url) for i, (cap, url) in enumerate(every) if (last.get(cap) or "") < cutoff]
    for _, _, cap, url in sorted(due)[: int(ctx.extras.get("carwow_options_per_run", PER_RUN))]:
        yield Target(identifier=cap, metadata={"cap_id": cap, "url": url})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def _price(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_page(page: str, cap_id: str, url: str, observed_at: str) -> dict | None:
    """The chooser's JSON as one record: options and packs with their contents and prices."""
    m = CHOOSER_RE.search(page)
    if not m:
        return None
    attrs = dict(ATTR_RE.findall(m.group(1)))
    if "derivative" not in attrs:
        return None
    d = json.loads(H.unescape(attrs["derivative"]))
    options = [{"name": o.get("name"), "category": o.get("category"), "price": _price(o.get("price")), "default": bool(o.get("is_default"))}
               for o in d.get("options") or [] if o.get("name")]
    packs = [{"name": p.get("name"), "price": _price(p.get("price")), "default": bool(p.get("is_default")),
              "items": [i.get("name") for i in p.get("included_options") or [] if i.get("name")]}
             for p in d.get("packs") or [] if p.get("name")]
    return {"cap_id": cap_id, "options": options, "packs": packs, "colours": len(d.get("colours") or []),
            "source": "Carwow configurator", "source_url": url, "observed_at": observed_at}


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    row = parse_page(body.decode("utf-8", "replace"), target.metadata["cap_id"], original_url(target), observed_at_for(target))
    if row:
        yield ParsedRecord(kind="options", key=f"{SITE}:{row['cap_id']}", row=row)


options = Capability(name="options", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("options",))
provider = Provider(name="carwow_options", default_capability="options", capabilities={"options": options}, live=True)
