"""New Car Discount model listings: https://www.new-car-discount.com/car/<make>/<model>/<body>/all/all

Server-rendered list of derivatives with the broker's all-in price (first
registration, road tax, warranty included; grant applied where it applies).
Only electric derivatives (a 'kW' in the name) are kept. Offer key is the
derivative's own URL path; trim resolution by the derivative text (trim_map
source 'ncd').
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import money, norm_key, text
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "ncd"
BASE = "https://www.new-car-discount.com"
LISTINGS = {
    "hyundai/ioniq-3": "/car/hyundai/ioniq-3/hatchback/all/all",
    "hyundai/kona": "/car/hyundai/kona/hatchback/all/all",
    "hyundai/inster": "/car/hyundai/inster/hatchback/all/all",
    "hyundai/ioniq-5": "/car/hyundai/ioniq-5/hatchback/all/all",
    "kia/ev2": "/car/kia/ev2/hatchback/all/all",
    "kia/ev3": "/car/kia/ev3/estate/all/all",
    "kia/ev6": "/car/kia/ev6/estate/all/all",
    "kia/pv5": "/car/kia/pv5/mpv/all/all",
}
ITEM_RE = re.compile(r'<li class="example-listing">(.*?)</li>', re.S)


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for ident, path in LISTINGS.items():
        if target.identifier in ("all", ident):
            yield Target(identifier=ident, metadata={"make": ident.split("/")[0], "url": BASE + path})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def parse_page(page: str, make: str, url: str, observed_at: str) -> list[dict]:
    rows = []
    for m in ITEM_RE.finditer(page):
        b = m.group(1)
        name = re.search(r'<span class="derivative-name">(.*?)</span>', b, re.S)
        group = re.search(r'<span class="derivative-group">(.*?)</span>', b, re.S)
        price = re.search(r'<p class="derivative-rrp">(.*?)</p>', b, re.S)
        save = re.search(r'<span class="absolute">(.*?)</span>', b, re.S)
        href = re.search(r'href="(/car/[^"]+/\d+/)"', b)
        if not (name and price and href):
            continue
        name_t, group_t = text(name.group(1)), text(group.group(1)) if group else ""
        if "kw" not in name_t.lower():
            continue  # not electric
        rows.append({
            "id": f"ncd:{href.group(1)}", "offer_key": f"ncd:{href.group(1)}",
            "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "lead", "verification": "scraped", "source": "New Car Discount",
            "source_url": BASE + href.group(1), "listing_url": url,
            "car_ref": {"source": SITE, "key": norm_key(make, group_t, name_t), "label": f"{group_t} {name_t}".strip(),
                        "make": make, "model": group_t, "derivative": name_t},
            "finance_type": "cash", "vehicle_price": money(price.group(1)),
            "saving_stated": money(save.group(1)) if save else None,
            "notes": "Broker all-in price including first registration, road tax and warranty. Availability for a December delivery not confirmed.",
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["make"], original_url(target), observed_at_for(target)):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


listing = Capability(name="listing", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="ncd", default_capability="listing", capabilities={"listing": listing, "backfill": backfill_capability(listing)}, live=True)
