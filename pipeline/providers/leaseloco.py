"""LeaseLoco model pages: https://www.leaseloco.com/car-leasing/<make>/<model>

The page embeds its data as Next.js __NEXT_DATA__; originalBestDealList holds
the best personal lease per derivative. Prices in the JSON are ex-VAT; the page
shows them inc VAT, so they are multiplied by 1.2 here. A deal is key'd by
vehicle id + profile (term, initial months, mileage), which is stable while the
price moves; trim resolution by make|model|derivative text (source 'leaseloco').
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import norm_key
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "leaseloco"
SLUGS = ["hyundai/kona-electric", "hyundai/inster", "hyundai/ioniq-5", "kia/ev3", "kia/ev6"]
VAT = 1.2


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for slug in SLUGS:
        if target.identifier in ("all", slug):
            yield Target(identifier=slug, metadata={"url": f"https://www.leaseloco.com/car-leasing/{slug}"})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def parse_page(page: str, url: str, observed_at: str) -> list[dict]:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("no __NEXT_DATA__ on page")
    props = json.loads(m.group(1))["props"]["pageProps"]
    # Most model pages carry a curated originalBestDealList; some (Inster) ship
    # only the first page of search results. Take both, first list wins on dupes.
    deals, seen = [], set()
    for list_name in ("originalBestDealList", "originalSearchResultDeals"):
        for d in props.get(list_name) or []:
            pid = (d.get("vehiclePrice") or {}).get("id")
            if pid in seen:
                continue
            seen.add(pid)
            deals.append(dict(d, _list=list_name))
    rows = []
    for d in deals:
        v, p = d.get("vehicle") or {}, d.get("vehiclePrice") or {}
        if not v or not p or p.get("monthlyPayment") is None:
            continue
        # The Kona Electric page also lists petrol and hybrid Konas.
        if (v.get("fuelTypeName") or "").lower() != "electric" and "kw" not in (v.get("derivativeName") or "").lower():
            continue
        monthly = round(float(p["monthlyPayment"]) * VAT, 2)
        init_months = int(p.get("initialPaymentInMonths") or 1)
        term = int(p.get("term") or 0)
        fee = round(float(p.get("documentFee") or 0) * VAT, 2)
        mileage = int(p.get("mileage") or 0) or None
        key = f"leaseloco:{v.get('id')}:{term}:{init_months}:{mileage}"
        rows.append({
            "id": key, "offer_key": key,
            "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "lead", "verification": "scraped", "source": "LeaseLoco best personal lease",
            "source_url": url, "source_ref": f"deal {p.get('id')} vehicle {v.get('id')}",
            "car_ref": {"source": SITE,
                        "key": norm_key(v.get("manufacturerName", ""), v.get("modelName", ""), v.get("derivativeName", "")),
                        "label": f"{v.get('manufacturerName')} {v.get('modelName')} {v.get('derivativeName')}"},
            "finance_type": "pch", "term_months": term, "profile": f"{init_months}+{term - 1}",
            "initial_rental": round(monthly * init_months, 2), "num_rentals": term - 1, "monthly_rental": monthly,
            "fees_gbp": fee, "annual_mileage": mileage, "lease_type": p.get("leaseType"),
            "stock_status": p.get("stockStatus"), "locoscore": p.get("rating"), "deal_list": d["_list"],
            "notes": "Best personal-lease price on LeaseLoco for this derivative and profile; figures converted from ex-VAT.",
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), original_url(target), observed_at_for(target)):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


best = Capability(name="best-deals", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="leaseloco", default_capability="best-deals", capabilities={"best-deals": best, "backfill": backfill_capability(best)}, live=True)
