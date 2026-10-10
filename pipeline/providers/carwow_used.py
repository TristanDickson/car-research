"""Carwow's used stock per model: the deal cards behind https://www.carwow.co.uk/<make>/<model>/used

The model page itself is a shell; the cards come from a Turbo frame on
quotes.carwow.co.uk (stock_cars/deal-cards, six per page, a 'next' link until
the stock runs out). Each card prints the derivative as CAP names it
('125kW 58 kWh Auto Premium Part Leather'), the price, the registration year,
the mileage, the dealer's town and a deal link. This is Carwow's partner
dealers' stock, not the whole used market: a few to a few dozen cars per
model, enough for a 'buy used' route and for what a three-year-old example
asks today, which is the residual value the true-monthly needs.

Emits one 'used' record per card, keyed carwow-used:<deal hash>. Gold keeps
them as current stock (first / last seen, present) rather than price history.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlencode

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.carwow_deals import MODELS
from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.parse import money, number, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "carwow-used"
CARDS = "https://quotes.carwow.co.uk/stock_cars/deal-cards"
MAX_PAGES = 40
PAGE_BREAK = "\n<!-- carwow-used page break -->\n"
CARD_RE = re.compile(r"<div class='deal-card'>(.*?)(?=<div class='deal-card'>|</turbo-frame>|$)", re.S)


def cards_url(make: str, model: str, page: int = 1) -> str:
    q = {
        "brand_slug": make, "cross_domain": "true", "locked_filters[brand_slug]": make, "locked_filters[model_slug]": model,
        "locked_filters[vehicle_state_group]": "used", "locked_filters[vehicle_type]": "car", "model_slug": model,
        "page": page, "vehicle_state_group": "used", "vehicle_type": "car",
    }
    return f"{CARDS}?{urlencode(q)}"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    models = electric_models(ctx) or [{"make": mk, "model": mo, "make_name": pretty_make(mk)} for mk, mo in MODELS]
    for m in models:
        ident = f"{m['make']}/{m['model']}"
        if target.identifier in ("all", ident):
            yield Target(identifier=ident, metadata={"make": m["make"], "model": m["model"], "make_name": m["make_name"],
                                                     "url": cards_url(m["make"], m["model"])})


def deal_ids(page: str) -> list[str]:
    return re.findall(r"quotes\.carwow\.co\.uk/deals/([0-9a-f]{16,})", page)


def fetch(target: Target, ctx: Context) -> Fetched:
    """Every page of the model's used stock, joined into one body (each response also kept as it came).
    Carwow repeats cards across pages, so a page with nothing new does not end the paging: it ends
    where there is no 'next' link, or after three pages in a row bring nothing new."""
    make, model = target.metadata["make"], target.metadata["model"]
    pages: list[str] = []
    parts: list[Fetched] = []
    seen: set[str] = set()
    stale = 0
    for p in range(1, MAX_PAGES + 1):
        try:
            f = fetch_url(cards_url(make, model, p), ctx, headers={"Turbo-Frame": "stock_cars_v2_cards"})
        except FetchError as e:
            e.parts = tuple(parts)
            raise
        parts.append(f)
        body = f.body.decode("utf-8", "replace")
        ids = [d for d in deal_ids(body) if d not in seen]
        if not deal_ids(body):
            break
        stale = 0 if ids else stale + 1
        seen.update(ids)
        pages.append(body)
        if stale >= 3 or ("rel='next'" not in body and 'rel="next"' not in body):
            break
    return Fetched(url=target.metadata["url"], status_code=200, body=PAGE_BREAK.join(pages).encode("utf-8"),
                   content_type="text/html", parts=tuple(parts))


def parse_page(page: str, make: str, model: str, url: str, observed_at: str, make_name: str | None = None) -> list[dict]:
    make_name = make_name or pretty_make(make)
    rows: list[dict] = []
    seen: set[str] = set()
    for m in CARD_RE.finditer(page):
        c = m.group(1)
        link = re.search(r"href='(https://quotes\.carwow\.co\.uk/deals/([0-9a-f]+))'", c)
        if not link or link.group(2) in seen:
            continue
        seen.add(link.group(2))
        deriv = re.search(r"deal-card__derivative'>\s*(.*?)\s*</div>", c, re.S)
        title = re.search(r"deal-card__title'>\s*(.*?)\s*</div>", c, re.S)
        price = re.search(r"deal-card__price'>\s*(.*?)\s*</div>", c, re.S)
        year = re.search(r"<li>\s*((?:19|20)\d\d)\s*</li>", c)
        miles = re.search(r"<li>\s*([\d,]+)\s*miles\s*</li>", c)
        town = re.search(r"data-deal-location-target='town'>\s*(.*?)\s*</span>", c, re.S)
        badges = [text(b) for b in re.findall(r"class='badge[^']*'>\s*(.*?)\s*</(?:div|span)>", c, re.S)]
        img = re.search(r"srcset='(https://[^\s']+)", c)
        title_t = text(title.group(1)) if title else f"{make_name} {model}"
        model_name = title_t[len(make_name):].strip() if title_t.lower().startswith(make_name.lower()) else title_t
        derivative = text(deriv.group(1)) if deriv else ""
        rows.append({
            "listing_key": f"{SITE}:{link.group(2)}", "source": "Carwow used stock", "source_url": link.group(1),
            "listing_url": url, "observed_at": observed_at,
            "make": make_name, "make_slug": make, "model": model_name, "model_slug": model,
            "derivative": derivative, "price_gbp": money(price.group(1)) if price else None,
            "year": int(year.group(1)) if year else None,
            "mileage": int(number(miles.group(1)) or 0) if miles else None,
            "town": text(town.group(1)) if town else None, "badges": [b for b in badges if b],
            "image_url": img.group(1) if img else None,
            "car_ref": {"source": SITE, "key": link.group(2), "make": make_name, "model": model_name, "derivative": derivative,
                        "label": f"{title_t} {derivative}".strip()},
        })
    return [r for r in rows if r["price_gbp"]]


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["make"], target.metadata["model"],
                          target.metadata["url"], observed_at_for(target), target.metadata.get("make_name")):
        yield ParsedRecord(kind="used", key=row["listing_key"], row=row)


stock = Capability(name="used-stock", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("used",))
provider = Provider(name="carwow_used", default_capability="used-stock", capabilities={"used-stock": stock}, live=True)
