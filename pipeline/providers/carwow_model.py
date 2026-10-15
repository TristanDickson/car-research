"""Carwow public model pages: https://www.carwow.co.uk/<make>/<model>

The "trims and prices" table near the foot of the page is the one place Carwow
prints every derivative of a model by its CAP name, brackets included
('71kW 01 42kWh 5dr Auto [No Heat Pump] - Price from £22,995'), each with the
CAP derivative id, the engine and the version date in its configurator link.
The specification page lists one derivative per trim and engine and names the
trim only, so a no-heat-pump version of a trim and its standard twin look the
same there; here they do not.

Emits one 'derivative' record per row: the registry Gold keeps in `derivatives`,
which gives a stub car to any derivative no other page described and tells the
facts overlay (services/facts.py) what the brackets say. Which models to read
comes from the catalogue (carwow_catalog).
"""
from __future__ import annotations

import html as H
import re
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.http import fetch_url
from pipeline.providers.parse import combustion, money, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for, original_url

SITE = "carwow-cap"
MODELS = [("hyundai", "inster"), ("hyundai", "kona-electric"), ("kia", "ev3")]
ROW_RE = re.compile(r"<tr>\s*<td>\s*(.*?)\s*</td>\s*<td[^>]*>\s*<a[^>]*href=\"([^\"]*cap_derivative_id=[^\"]*)\"", re.S)
TABLE_RE = re.compile(r"make-model-hub__trims-table'>(.*?)</table>", re.S)
BRACKET_RE = re.compile(r"\[([^\]]+)\]")


def url_for(make: str, model: str) -> str:
    return f"https://www.carwow.co.uk/{make}/{model}"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    models = electric_models(ctx) or [{"make": mk, "model": mo, "make_name": pretty_make(mk), "model_name": None} for mk, mo in MODELS]
    for m in models:
        ident = f"{m['make']}/{m['model']}"
        if target.identifier in ("all", ident):
            yield Target(identifier=ident, metadata={"make": m["make"], "model": m["model"], "make_name": m["make_name"],
                                                     "model_name": m.get("model_name"), "url": url_for(m["make"], m["model"])})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def trim_of(name: str, engine: str) -> str:
    """The trim words of a CAP name: what is left after the brackets, the engine's
    own words and the door count. '71kW 01 42kWh 5dr Auto [No Heat Pump]' with
    engine '71kW 42kWh Auto' → '01'; '85kW GT-Line S 77kWh 5dr Auto' → 'GT-Line S'."""
    bare = BRACKET_RE.sub(" ", name)
    engine_words = {w.lower() for w in engine.split()}
    words = [w for w in bare.split() if w.lower() not in engine_words and not re.fullmatch(r"\d+dr", w, re.I)]
    return " ".join(words).strip()


def parse_page(page: str, make: str, model: str, url: str, observed_at: str, make_name: str | None = None,
               model_name: str | None = None) -> list[dict]:
    make_name = make_name or pretty_make(make)
    table = TABLE_RE.search(page)
    if not table:
        return []
    rows: list[dict] = []
    seen: set[str] = set()
    for label, href in ROW_RE.findall(table.group(1)):
        q = parse_qs(urlparse(H.unescape(href)).query)
        cap = (q.get("cap_derivative_id") or [None])[0]
        if not cap or cap in seen:
            continue
        seen.add(cap)
        label = text(label)
        name, _, price = label.partition(" - Price from ")
        name = name.strip()
        engine = (q.get("engine_name") or [""])[0].strip()
        if combustion(f"{name} {engine}"):   # a petrol version the model's page lists too
            continue
        version = (q.get("derivative_version_id") or [""])[0].rsplit("_", 1)[-1]
        brackets = [b.strip() for b in BRACKET_RE.findall(name) if b.strip()]
        rows.append({
            "cap_id": cap, "make": make_name, "make_slug": make, "model": model_name or (q.get("model") or [model])[0].rsplit("-", 1)[0].replace("-", " ").title(),
            "model_slug": model, "name": name, "trim": trim_of(name, engine), "engine": engine, "brackets": brackets,
            "rrp": money(price) if price else None, "version_date": version if re.fullmatch(r"\d{4}-\d{2}-\d{2}", version) else None,
            "configurator_model": (q.get("model") or [None])[0], "configurator_url": H.unescape(href),
            "source": "Carwow model page", "source_url": url, "observed_at": observed_at,
        })
    return rows


REVIEW_RE = re.compile(r"<(h2|h3)(?:\s[^>]*)?>(.*?)</\1>|<p(?:\s[^>]*)?>(.*?)</p>|<li(?:\s[^>]*)?>(.*?)</li>", re.S)   # not <picture>, not <link>


def parse_review(page: str) -> dict | None:
    """Carwow's review of the model, as printed on the model page: its verdict lists ('What's good', 'What's not
    so good') and every section of the review by heading ('Space in the back seats', 'On the motorway', 'Reliability
    and problems'), each its paragraphs' text. The FAQs and what follows them are left."""
    sections: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    heading, inside = None, False
    for m in REVIEW_RE.finditer(page):
        if m.group(1):
            title = text(m.group(2))
            if inside and re.search(r"\bFAQs?\b", title):
                break
            if re.match(r"(Is the .+ a good car\?|What's good|What&#39;s good)", title) or title.startswith("What's good"):
                inside = True
            heading = title if inside else None
            continue
        if not inside or not heading:
            continue
        if m.group(4) is not None and heading.lower().startswith("what"):
            item = text(m.group(4))
            if item:
                lists.setdefault(heading, []).append(item)
        elif m.group(3) is not None:
            para = text(m.group(3))
            if para:
                sections[heading] = f"{sections[heading]} {para}" if heading in sections else para
    if not sections and not lists:
        return None
    good = next((v for k, v in lists.items() if k.startswith("What's good")), [])
    bad = next((v for k, v in lists.items() if k.startswith("What's not")), [])
    return {"good": good, "not_so_good": bad, "sections": sections}


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    page = body.decode("utf-8", "replace")
    for row in parse_page(page, target.metadata["make"], target.metadata["model"], original_url(target),
                          observed_at_for(target), target.metadata.get("make_name"), target.metadata.get("model_name")):
        yield ParsedRecord(kind="derivative", key=f"{SITE}:{row['cap_id']}", row=row)
    review = parse_review(page)
    if review:
        slug = f"{target.metadata['make']}/{target.metadata['model']}"
        yield ParsedRecord(kind="spec", key=f"carwow-review:{slug}", row={
            "spec_key": f"carwow-review:{slug}", "model_slug": slug, "source_url": original_url(target), "observed_at": observed_at_for(target), **review})


derivatives = Capability(name="derivatives", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("derivative", "spec"))
provider = Provider(name="carwow_model", default_capability="derivatives", capabilities={"derivatives": derivatives}, live=True)
