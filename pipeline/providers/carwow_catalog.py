"""The catalogue of every EV on sale in the UK, from Carwow's own index pages.

Three kinds of page, all public and server-rendered:

  sitemap/car_models.xml        every <make>/<model> page and which have a
                                /specifications page
  sitemap/car_model_deals.xml   which models have a /deals page
  /<make>/electric              one per make: the make's electric models, by name

The per-make electric pages come from sitemap/brand_fuel_types.xml, which
discover reads live (with a static list as the fallback). Makes whose whole
range is electric (Tesla, Polestar, XPeng ...) have no such page, so they are
flagged by make; a few models whose make is mixed but which have no electric
page (MINI's electric models) are listed by slug.

Emits one 'model' record per page mention. Gold merges them by slug (a flag
set by any page sticks), so the models table ends up with make, model, the
printed names and the three flags per slug. carwow_deals, carwow_specs and
leaseloco discover their targets from it.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections.abc import Iterator

from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.parse import text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

BASE = "https://www.carwow.co.uk"
SITEMAPS = {
    "sitemap/car_models": f"{BASE}/sitemap/car_models.xml",
    "sitemap/car_model_deals": f"{BASE}/sitemap/car_model_deals.xml",
}
FUEL_SITEMAP = f"{BASE}/sitemap/brand_fuel_types.xml"

# Makes with no /electric page because everything they sell is electric.
ELECTRIC_MAKES = {"tesla", "polestar", "xpeng", "lucid", "zeekr", "nio", "rivian", "aion", "leapmotor", "denza", "skywell"}
# Electric models of mixed makes that Carwow's /electric page misses (MINI's
# /electric URL is the Cooper Electric model page itself).
EXTRA_ELECTRIC = {
    "mini/electric", "mini/electric-convertible", "mini/electric-jcw", "mini/aceman", "mini/aceman-jcw",
    "mini/countryman-electric", "maserati/granturismo-folgore", "seat/mii-electric",
}
# Models Carwow still lists that are long out of production and have neither a
# deals nor a specifications page are dropped by discover (nothing to fetch).

# Fallback when the fuel-type sitemap cannot be read: the makes with an
# /electric page on 2026-10-06.
KNOWN_EV_MAKES = [
    "abarth", "aion", "alpine", "audi", "bmw", "byd", "citroen", "cupra", "dacia", "ds", "fiat", "ford", "geely",
    "genesis", "gwm", "honda", "hyundai", "jaecoo", "jaguar", "jeep", "kgm-motors", "kia", "land-rover", "leapmotor",
    "lexus", "lotus", "mazda", "mercedes", "mg", "nissan", "omoda", "peugeot", "polestar", "porsche", "renault",
    "skoda", "smart", "ssangyong", "subaru", "suzuki", "toyota", "vauxhall", "volkswagen", "volvo",
]

# How Carwow prints a make whose slug does not simply capitalise.
PRETTY_MAKES = {
    "bmw": "BMW", "byd": "BYD", "mg": "MG", "ds": "DS", "gwm": "GWM", "kgm-motors": "KGM", "vw": "Volkswagen",
    "land-rover": "Land Rover", "alfa-romeo": "Alfa Romeo", "rolls-royce": "Rolls-Royce", "aston-martin": "Aston Martin",
    "mercedes": "Mercedes", "mini": "MINI", "seat": "SEAT", "xpeng": "XPeng", "cupra": "Cupra", "ssangyong": "SsangYong",
    "kgm": "KGM", "mclaren": "McLaren", "ineos": "INEOS",
}

GENERIC_PAGES = {"electric", "deals", "lease", "used", "petrol", "diesel", "hybrid", "automatic", "manual"}
LINK_RE = re.compile(r"<a class='medium' href='/([a-z0-9-]+)/([a-z0-9-]+)'>\s*(.*?)\s*</a>", re.S)
LIST_RE = re.compile(r"alternative-transmissions-for-model-links-list__container(.*?)</div>\s*</div>\s*</div>", re.S)
LOC_RE = re.compile(r"<loc>https://www\.carwow\.co\.uk/([a-z0-9-]+)/([a-z0-9-]+)(/specifications|/deals)?</loc>")


def pretty_make(slug: str) -> str:
    return PRETTY_MAKES.get(slug) or " ".join(w.capitalize() for w in slug.split("-"))


def electric_makes(ctx: Context) -> list[str]:
    """Makes with an /electric page, from the fuel-type sitemap (live), else the known list."""
    try:
        body = fetch_url(FUEL_SITEMAP, ctx, accept="application/xml").body.decode("utf-8", "replace")
    except FetchError as e:
        print(f"  carwow fuel-type sitemap unavailable ({e}); using the built-in make list", file=sys.stderr, flush=True)
        return list(KNOWN_EV_MAKES)
    makes = re.findall(r"<loc>https://www\.carwow\.co\.uk/([a-z0-9-]+)/electric</loc>", body)
    return sorted(set(makes)) or list(KNOWN_EV_MAKES)


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    ident = target.identifier
    for key, url in SITEMAPS.items():
        if ident in ("all", key):
            yield Target(identifier=key, metadata={"url": url, "kind": "sitemap"})
    if ident == "all":
        makes = electric_makes(ctx)
    elif ident.startswith("brand/"):
        makes = [ident.split("/", 1)[1]]
    else:
        makes = []
    for make in makes:
        yield Target(identifier=f"brand/{make}", metadata={"url": f"{BASE}/{make}/electric", "kind": "brand", "make": make})


def fetch(target: Target, ctx: Context) -> Fetched:
    accept = "application/xml" if target.metadata.get("kind") == "sitemap" else "text/html"
    return fetch_url(target.metadata["url"], ctx, accept=accept)


def _record(slug: str, observed_at: str, url: str, **fields) -> dict:
    make, model = slug.split("/", 1)
    row = {"slug": slug, "make": make, "model": model, "make_name": None, "model_name": None,
           "electric": None, "has_deals": None, "has_specs": None, "observed_at": observed_at, "source_url": url}
    row.update(fields)
    return row


def parse_sitemap(body: str, which: str, url: str, observed_at: str) -> list[dict]:
    """car_models: every model, has_specs where a /specifications page exists;
    car_model_deals: has_deals for every listed model. Electric-only makes and
    the extra slugs are flagged electric here, since no brand page will."""
    seen: dict[str, dict] = {}
    for make, model, suffix in LOC_RE.findall(body):
        slug = f"{make}/{model}"
        if model in GENERIC_PAGES and slug not in EXTRA_ELECTRIC:
            continue  # /<make>/electric and friends are listings, not models
        row = seen.setdefault(slug, _record(slug, observed_at, url))
        if which == "sitemap/car_model_deals":
            if suffix == "/deals":
                row["has_deals"] = 1
        else:
            if suffix == "/specifications":
                row["has_specs"] = 1
        if make in ELECTRIC_MAKES or slug in EXTRA_ELECTRIC:
            row["electric"] = 1
    if which == "sitemap/car_model_deals":
        return [r for r in seen.values() if r["has_deals"]]
    return list(seen.values())


def parse_brand(body: str, make: str, url: str, observed_at: str) -> list[dict]:
    """The 'X Electric cars' link list on /<make>/electric. A make page that is
    really a model page (MINI) has no such list and yields nothing."""
    m = LIST_RE.search(body)
    if not m:
        return []
    title = re.search(r"<h2[^>]*>\s*(.*?)\s*</h2>", m.group(0), re.S)
    make_name = text(title.group(1)).replace(" Electric cars", "").strip() if title else pretty_make(make)
    rows = []
    for mk, model, name in LINK_RE.findall(m.group(1)):
        if mk != make:
            continue
        name = text(name)
        model_name = name[len(make_name):].strip() if name.lower().startswith(make_name.lower()) else name
        rows.append(_record(f"{mk}/{model}", observed_at, url, make_name=make_name, model_name=model_name, electric=1))
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    page = body.decode("utf-8", "replace")
    observed_at = observed_at_for(target)
    if target.metadata.get("kind") == "sitemap":
        rows = parse_sitemap(page, target.identifier, target.metadata["url"], observed_at)
    else:
        rows = parse_brand(page, target.metadata["make"], target.metadata["url"], observed_at)
    for row in rows:
        yield ParsedRecord(kind="model", key=row["slug"], row=row)


def electric_models(ctx: Context, need: str | None = None) -> list[dict] | None:
    """The catalogue's electric models from the run's database, for the scrapers'
    discover: [{slug, make, model, make_name, model_name}], or None when no
    catalogue is available (no DB in the context, table empty), so the caller
    falls back to its static list. `need` = 'has_deals' | 'has_specs'."""
    conn: sqlite3.Connection | None = ctx.extras.get("db")
    if conn is None:
        return None
    where = "WHERE electric=1" + (f" AND {need}=1" if need else "")
    try:
        rows = conn.execute(f"SELECT slug, make, model, make_name, model_name FROM models {where} ORDER BY slug").fetchall()
    except sqlite3.OperationalError:
        return None
    out = [dict(r) for r in rows]
    for r in out:
        r["make_name"] = r["make_name"] or pretty_make(r["make"])
    return out or None


catalog = Capability(name="catalog", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("model",))
provider = Provider(name="carwow_catalog", default_capability="catalog", capabilities={"catalog": catalog}, live=True)
