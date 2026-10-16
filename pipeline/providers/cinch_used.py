"""cinch's used stock: every electric car it lists, per make.

The pages at https://www.cinch.co.uk/used-cars/<make>?fuelType=electric are a
Next.js shell over a public search API (search-api.snc-prod.aws.cinch.co.uk),
which returns 32 listings a page as JSON with the registration (vrm), the CAP
variant ('125kW Premium 58 kWh 5dr Auto [Part Leather]'), the price with
cinch's admin fee, the model year, the mileage and the site holding the car.
cinch is a retailer (its own stock plus marketplace dealers), so this is a
second, larger pool than Carwow's partner dealers: ~1,300 EVs at the time of
writing against Carwow's ~670.

One target per make (a cinch make slug; the catalogue's makes mapped where the
slugs differ), the pages joined into one JSON body. Each listing is filed under
the catalogue model whose name it matches (cinch names the model, e.g. 'Kona'
or 'ID.4', the catalogue 'Kona Electric' or 'ID.4'), the few that match
nothing we sell are skipped. Emits 'used' records keyed cinch:<vehicleId>; the
vrm rides along so the snapshot can fold the same car listed on two sites.

Every listing also carries cinch's finance quote for the car (PCP, or HP on a
few older cars): deposit, monthly payment over quoteTermMonths payments, APR,
the PCP's final payment, the credit and its charges, the mileage allowance and
the excess charge. It is kept under `finance` with whether it reconciles, beside
the colour, drive, discount, cinch's tags ('cars-on-offer', 'nearly-new') and
its feature categories. The quote's deposit plus credit is the price before
cinch's admin fee.

Each listing also names the car in fields of its own (`details`): the trim, the
seats and doors, the body, the fuel (cinch files the range-extender MX-30 and i3
as 'Electric range extender') and the range with the test it comes from (WLTP,
or NEDC on some older cars, which reads higher). They go on the row
and its car_ref; the stock type (cinch's own, a marketplace dealer's or a
partner's) goes on the row.
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from urllib.parse import quote

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.carwow_deals import MODELS
from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.used_match import match_model
from pipeline.providers.wayback import observed_at_for

SITE = "cinch"
API = "https://search-api.snc-prod.aws.cinch.co.uk/used-cars"
PAGE_SIZE = 32
MAX_PAGES = 60

# Catalogue make slug → the cinch make slug(s) that hold the same cars.
MAKE_SLUGS = {"mercedes": ("mercedes-benz",), "kgm-motors": ("kgm", "ssangyong"), "gwm": ("ora", "gwm")}


def api_url(make: str, page: int = 1) -> str:
    path = f"{make}?fuelType=electric" + (f"&pageNumber={page}" if page > 1 else "")
    return f"{API}?url={quote(path, safe='')}"


def _catalogue(ctx: Context) -> list[dict]:
    models = electric_models(ctx)
    if models is None:
        models = [{"make": mk, "model": mo, "make_name": pretty_make(mk), "model_name": None, "slug": f"{mk}/{mo}"} for mk, mo in MODELS]
    return models


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    by_cinch_make: dict[str, list[dict]] = {}
    for m in _catalogue(ctx):
        for cm in MAKE_SLUGS.get(m["make"], (m["make"],)):
            by_cinch_make.setdefault(cm, []).append({"make": m["make"], "model": m["model"], "make_name": m["make_name"],
                                                     "model_name": m.get("model_name")})
    for cm in sorted(by_cinch_make):
        if target.identifier in ("all", cm):
            yield Target(identifier=cm, metadata={"make": cm, "url": api_url(cm), "models": by_cinch_make[cm]})


def fetch(target: Target, ctx: Context) -> Fetched:
    """Every page of the make's electric stock, joined into one JSON body."""
    make = target.metadata["make"]
    pages: list[dict] = []
    parts: list[Fetched] = []
    got = 0
    for p in range(1, MAX_PAGES + 1):
        try:
            f = fetch_url(api_url(make, p), ctx, accept="application/json")
        except FetchError as e:
            e.parts = tuple(parts)   # the pages already received are kept too
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
    body = json.dumps({"make": make, "pages": pages}, ensure_ascii=False).encode("utf-8")
    return Fetched(url=target.metadata["url"], status_code=200, body=body, content_type="application/json", parts=tuple(parts))


def _model_slug(name: str) -> str:
    return re.sub(r"\s+", "-", (name or "").strip().lower())


def _pounds(pence) -> float | None:
    return round(pence / 100, 2) if isinstance(pence, (int, float)) else None


# credit + charges - final payment - payments × n was nil on 523 of the 1,284 quotes of 11 Oct and exactly
# £10 on the other 761 (every HP among them): the charges carry £10 no payment shows. One payment's slack,
# as cinch_new allows, would also pass a quote one payment short, so the slack here is the £10.
RECONCILE_SLACK_GBP = 10.0


def finance(v: dict) -> dict | None:
    """cinch's quote for the car, the figures it prints and no others; None for a car without one."""
    kind, payment = (v.get("quoteType") or "").lower(), _pounds(v.get("quoteRegularPaymentInPence"))
    if not kind or not payment:
        return None
    n = int(v["quoteTermMonths"]) if v.get("quoteTermMonths") else None
    credit, charges, final = _pounds(v.get("quoteBalanceInPence")), _pounds(v.get("quoteChargesInPence")), _pounds(v.get("quoteResidualValueInPence"))
    excess = re.search(r"([\d.]+)", v.get("quoteExcessMileage") or "")
    apr = v.get("quoteApr")
    f = {"type": kind, "monthly_payment": payment, "deposit": _pounds(v.get("quoteDepositInPence")),
         "apr": round(apr / 100, 6) if isinstance(apr, (int, float)) else None,
         "num_payments": n, "term_months": (n + 1 if final else n) if n else None,   # a PCP's final payment is a month of its own
         "final_payment": final, "credit": credit, "charges": charges,
         "annual_mileage": v.get("quoteAnnualMiles"), "excess_mileage_ppm": float(excess.group(1)) if excess else None}
    f = {k: x for k, x in f.items() if x is not None}
    if None in (credit, charges) or not n or (kind == "pcp" and final is None):
        f["reconciles"] = None
    else:   # an HP quote has no final payment
        f["reconciles"] = abs(credit + charges - (final or 0.0) - payment * n) <= RECONCILE_SLACK_GBP + 0.005
    return f


def details(v: dict) -> dict:
    """What the listing says of the car in fields of its own; a field it leaves empty is left out."""
    rng = v.get("rangeInMiles")
    d = {"trim": (v.get("trim") or "").strip() or None, "seats": v.get("seats") or None, "doors": v.get("doors") or None,
         "body": v.get("bodyType") or None, "fuel": v.get("fuelType") or None,
         "range_mi": rng if isinstance(rng, (int, float)) and rng > 0 else None}
    if d["range_mi"] is not None:
        d["range_test"] = v.get("rangeType") or None
    return {k: x for k, x in d.items() if x is not None}


def parse_body(body: dict, target: Target, observed_at: str) -> list[dict]:
    pages = body.get("pages") if "pages" in body else [body]
    models = target.metadata.get("models") or []
    rows: list[dict] = []
    seen: set[str] = set()
    unmatched: dict[str, int] = {}
    for page in pages:
        for v in page.get("vehicleListings") or []:
            vid = v.get("vehicleId")
            if not vid or vid in seen or not v.get("isAvailable", True) or v.get("isReserved"):
                continue
            seen.add(vid)
            m = match_model(v.get("make") or "", v.get("model") or "", models)
            if m is None:
                k = f"{v.get('make')} {v.get('model')}"
                unmatched[k] = unmatched.get(k, 0) + 1
                continue
            price = v.get("priceIncludingAdminFee") or v.get("price")
            if not price:
                continue
            make_name = m.get("make_name") or pretty_make(m["make"])
            model_name = m.get("model_name") or v.get("model") or m["model"]
            variant = (v.get("variant") or v.get("trim") or "").strip()
            car = details(v)
            rows.append({
                "listing_key": f"{SITE}:{vid}", "source": "cinch", "listing_url": target.metadata.get("url"),
                "source_url": f"https://www.cinch.co.uk/used-cars/{_model_slug(v.get('make'))}/{_model_slug(v.get('model'))}/details/{vid}",
                "observed_at": observed_at,
                "make": make_name, "make_slug": m["make"], "model": model_name, "model_slug": m["model"],
                "derivative": variant, "price_gbp": float(price), "price_before_fees": float(v["price"]) if v.get("price") else None,
                "year": v.get("modelYear") or v.get("vehicleYear"), "mileage": v.get("mileage"),
                "town": v.get("site"), "vrm": v.get("vrm") or v.get("fullRegistration"),
                "badges": [b for b in ("cinch" if v.get("stockType") == "cinch" else "marketplace", f"{v['rangeInMiles']} mi range" if v.get("rangeInMiles") else "") if b],
                "image_url": v.get("thumbnailUrl"), "first_listed_at": v.get("firstPublishedDate"),
                "finance": finance(v), "colour": v["colour"].title() if v.get("colour") else None, "drive": v.get("driveType"),
                "discount_gbp": _pounds(v.get("discountInPence")) or None, "tags": list(v.get("tags") or []),
                "categories": list(v.get("categories") or []), "stock_type": v.get("stockType"), **car,
                "car_ref": {"source": SITE, "key": vid, "make": make_name, "model": model_name, "derivative": variant,
                            "label": f"{make_name} {model_name} {variant}".strip(), **car},
            })
    if unmatched:
        print(f"  cinch {target.identifier}: not in the catalogue, skipped: "
              + ", ".join(f"{k} ×{n}" for k, n in sorted(unmatched.items())), file=sys.stderr, flush=True)
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_body(json.loads(body.decode("utf-8", "replace")), target, observed_at_for(target)):
        yield ParsedRecord(kind="used", key=row["listing_key"], row=row)


stock = Capability(name="used-stock", parser_version="3", discover=discover, fetch=fetch, parse=parse, kinds=("used",))
provider = Provider(name="cinch_used", default_capability="used-stock", capabilities={"used-stock": stock}, live=True)
