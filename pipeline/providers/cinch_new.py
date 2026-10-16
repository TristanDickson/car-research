"""cinch's new cars: a complete PCP quote for every electric car it stocks, and its cash price.

The same search API the used-stock reader calls, at `/new-cars`. Each listing is a car at one of
Marshall Motor Group's branches (`site`), in stock (`physical`) or to order (`virtual`), with
cinch's quote from its finance partner: deposit, monthly payment, number of payments, APR, the
optional final payment, the credit and its charges, the mileage allowance and the excess charge.
These are real quotes for one car each, not a representative example.

The quote finances less than the listed price on most cars (the Inster: listed £26,485, deposit
plus credit £22,735): the difference is a finance deposit contribution the quote does not name.
It is recorded as the contribution, worked out from the quote's own figures and marked
`contribution_implied`. A quote whose payments do not reconcile with its credit, charges and final
payment (two Nissans on 11 Oct) is kept as printed and marked `reconciles: false`.

Emits two offers per listing: `cinch-new:pcp:<vehicle id>` and `cinch-new:cash:<vehicle id>`. Their
`car_ref` carries the CAP-style variant text, matched to a derivative by the rules.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from pipeline import normalise
from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "cinch-new"
API = "https://search-api.snc-prod.aws.cinch.co.uk/new-cars"
MAX_PAGES = 10


def api_url(page: int = 1) -> str:
    return f"{API}?url=electric-fuel-type&channelId=CINCH" + (f"&pageNumber={page}" if page > 1 else "")


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    if target.identifier in ("all", "electric"):
        yield Target(identifier="electric", metadata={"url": api_url()})


def fetch(target: Target, ctx: Context) -> Fetched:
    """Every page of the electric new-car listing, joined (each response also kept as it came)."""
    pages: list[dict] = []
    parts: list[Fetched] = []
    got = 0
    for p in range(1, MAX_PAGES + 1):
        try:
            f = fetch_url(api_url(p), ctx, accept="application/json")
        except FetchError as e:
            e.parts = tuple(parts)
            raise
        parts.append(f)
        page = json.loads(f.body.decode("utf-8", "replace"))
        listings = page.get("vehicleListings") or []
        if not listings:
            break
        pages.append(page)
        got += len(listings)
        if got >= int(page.get("searchResultsCount") or 0):
            break
    body = json.dumps({"pages": pages}, ensure_ascii=False).encode("utf-8")
    return Fetched(url=target.metadata["url"], status_code=200, body=body, content_type="application/json", parts=tuple(parts))


def _pounds(pence) -> float | None:
    return round(pence / 100, 2) if isinstance(pence, (int, float)) else None


def parse_listing(v: dict, url: str, observed_at: str) -> list[dict]:
    if v.get("condition") != "new" or not v.get("make") or not v.get("variant"):
        return []
    vid = v["vehicleId"]
    make, model, variant = v["make"], v.get("model") or "", v["variant"]
    ref = {"source": SITE, "key": normalise.key(make, model, variant), "label": f"{make} {model} {variant}",
           "make": make, "model": model, "derivative": variant}
    price, with_fee = v.get("price"), v.get("priceIncludingAdminFee")
    site = v.get("site")
    site = ", ".join(site) if isinstance(site, list) else site   # a car to order lists every branch that can supply it
    base = {"observed_at": observed_at, "captured_at": observed_at[:10], "present": 1, "status": "live", "verification": "scraped",
            "source": "cinch", "dealer": site or "cinch", "source_url": url, "source_ref": vid, "car_ref": ref,
            "stock": v.get("inventoryType"), "colour": v.get("colour"), "range_wltp_mi": v.get("rangeInMiles"),
            "image_url": v.get("thumbnailUrl")}
    rows = []
    if with_fee:
        key = f"cinch-new:cash:{vid}"
        rows.append({**base, "id": key, "offer_key": key, "finance_type": "cash", "vehicle_price": float(with_fee),
                     "fees_gbp": float(with_fee - price) if price else None,
                     "notes": "cinch's price for this car, its admin fee included."})
    if v.get("quoteType") == "pcp" and v.get("quoteRegularPaymentInPence"):
        payment, n = _pounds(v["quoteRegularPaymentInPence"]), int(v.get("quoteTermMonths") or 0)
        credit, deposit = _pounds(v.get("quoteBalanceInPence")), _pounds(v.get("quoteDepositInPence")) or 0.0
        final, charges = _pounds(v.get("quoteResidualValueInPence")), _pounds(v.get("quoteChargesInPence"))
        stated = _pounds(v.get("depositContributionInPence")) or 0.0
        implied = round(float(price) - deposit - credit, 2) if price and credit is not None else None
        contribution = stated or (implied if implied and implied > 0 else 0.0)
        reconciles = None
        if None not in (credit, charges, final) and payment and n:
            reconciles = abs(credit + charges - final - payment * n) <= max(5.0, payment)
        excess = re.search(r"([\d.]+)", v.get("quoteExcessMileage") or "")
        key = f"cinch-new:pcp:{vid}"
        rows.append({**base, "id": key, "offer_key": key, "finance_type": "pcp",
                     "vehicle_price": float(price) if price else None, "list_price": float(price) if price else None,
                     "customer_deposit": deposit, "manufacturer_contribution": contribution,
                     "contribution_implied": bool(not stated and contribution),
                     "amount_of_credit": credit, "monthly_payment": payment, "num_payments": n, "term_months": n + 1 if n else None,
                     "apr": (v.get("quoteApr") or 0.0) / 100, "gfv": final, "cost_of_credit_stated": charges,
                     "annual_mileage": v.get("quoteAnnualMiles"), "excess_mileage_ppm": float(excess.group(1)) if excess else None,
                     "fees_gbp": float(with_fee - price) if with_fee and price else None, "reconciles": reconciles,
                     "notes": "cinch's quote for this car from its finance partner." + (
                         " The quote finances less than the price; the difference is shown as a contribution." if not stated and contribution else "")
                     + (" Its payments do not add up to its credit, charges and final payment; kept as printed." if reconciles is False else "")})
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    doc = json.loads(body.decode("utf-8", "replace"))
    for page in doc.get("pages") or []:
        for v in page.get("vehicleListings") or []:
            for row in parse_listing(v, target.metadata.get("url") or API, observed_at_for(target)):
                yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


quotes = Capability(name="quotes", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="cinch_new", default_capability="quotes", capabilities={"quotes": quotes}, live=True)
