"""Motorpoint's used stock: every electric car it has, from the one listing.

https://www.motorpoint.co.uk/used-cars/electric is a Next.js page whose
__NEXT_DATA__ carries the search result it rendered: 35 cars a page under
initialSearch.vehicles (make, model, CAP trim, registration year, mileage,
price, branch, advert link, and the car's list price when new) with the total
under initialSearch.metadata, the next page at ?page=N. Motorpoint is a
nearly-new supermarket (one to four years old, a few hundred EVs), so it says
most about what a car is worth after a PCP term, which is the residual the
true-monthly needs.

One target, 'electric', the pages' search results joined into one JSON body.
Each car is filed under the catalogue model its names match (used_match);
emits 'used' records keyed motorpoint:<VehicleId>. Motorpoint prints no
registration, so the snapshot folds a car it shares with another site by
year and mileage.
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.carwow_deals import MODELS
from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.used_match import match_model
from pipeline.providers.wayback import observed_at_for

SITE = "motorpoint"
LISTING = "https://www.motorpoint.co.uk/used-cars/electric"
PAGE_SIZE = 35
MAX_PAGES = 40
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def page_url(page: int = 1) -> str:
    return LISTING + (f"?page={page}" if page > 1 else "")


def _catalogue(ctx: Context) -> list[dict]:
    models = electric_models(ctx)
    if models is None:
        models = [{"make": mk, "model": mo, "make_name": pretty_make(mk), "model_name": None} for mk, mo in MODELS]
    return [{"make": m["make"], "model": m["model"], "make_name": m["make_name"], "model_name": m.get("model_name")} for m in models]


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    if target.identifier in ("all", "electric"):
        yield Target(identifier="electric", metadata={"url": LISTING, "models": _catalogue(ctx)})


def search_result(html: str) -> dict:
    """The page's search result: {metadata: {total, page, start}, vehicles: [...]}."""
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("no __NEXT_DATA__ on the page")
    s = json.loads(m.group(1))["props"]["pageProps"].get("initialSearch") or {}
    return {"metadata": s.get("metadata") or {}, "vehicles": s.get("vehicles") or []}


def fetch(target: Target, ctx: Context) -> Fetched:
    pages: list[dict] = []
    parts: list[Fetched] = []
    got = 0
    for p in range(1, MAX_PAGES + 1):
        try:
            f = fetch_url(page_url(p), ctx)
        except FetchError as e:
            e.parts = tuple(parts)   # the pages already received are kept too
            raise
        parts.append(f)
        page = search_result(f.body.decode("utf-8", "replace"))
        if not page["vehicles"]:
            break
        pages.append(page)
        got += len(page["vehicles"])
        if got >= int(page["metadata"].get("total") or 0):
            break
    body = json.dumps({"pages": pages}, ensure_ascii=False).encode("utf-8")
    return Fetched(url=target.metadata["url"], status_code=200, body=body, content_type="application/json", parts=tuple(parts))


def parse_body(body: dict, target: Target, observed_at: str) -> list[dict]:
    pages = body.get("pages") if "pages" in body else [body]
    models = target.metadata.get("models") or []
    rows: list[dict] = []
    seen: set[int] = set()
    unmatched: dict[str, int] = {}
    for page in pages:
        for v in page.get("vehicles") or []:
            vid = v.get("VehicleId")
            if not vid or vid in seen or v.get("IsSold") or v.get("IsOnSale") is False:
                continue
            seen.add(vid)
            m = match_model(v.get("Make") or "", v.get("Model") or "", models)
            if m is None:
                k = f"{v.get('Make')} {v.get('Model')}"
                unmatched[k] = unmatched.get(k, 0) + 1
                continue
            price = v.get("CurrentPrice")
            if not price:
                continue
            make_name = m.get("make_name") or pretty_make(m["make"])
            model_name = m.get("model_name") or (v.get("Model") or m["model"]).title()
            trim = (v.get("Trim") or "").strip()
            badges = [b for b in ("in transit" if str(v.get("InTransit")).lower() == "true" else "",
                                  "coming soon" if v.get("IsComingSoon") else "") if b]
            rrp = (v.get("OriginalRetailPrice") or {}).get("BasicPrice")
            rows.append({
                "listing_key": f"{SITE}:{vid}", "source": "Motorpoint", "listing_url": target.metadata.get("url"),
                "source_url": v.get("VehicleAdvertUrl"), "observed_at": observed_at,
                "make": make_name, "make_slug": m["make"], "model": model_name, "model_slug": m["model"],
                "derivative": trim, "price_gbp": float(price), "year": v.get("RegYear"), "mileage": v.get("Mileage"),
                "town": v.get("Location"), "vrm": None, "badges": badges, "image_url": v.get("DefaultImageUri") or v.get("ImageUri"),
                "list_price_when_new": float(rrp) if rrp else None,
                "car_ref": {"source": SITE, "key": str(vid), "make": make_name, "model": model_name, "derivative": trim,
                            "label": f"{make_name} {model_name} {trim}".strip()},
            })
    if unmatched:
        print("  motorpoint: not in the catalogue, skipped: " + ", ".join(f"{k} ×{n}" for k, n in sorted(unmatched.items())),
              file=sys.stderr, flush=True)
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_body(json.loads(body.decode("utf-8", "replace")), target, observed_at_for(target)):
        yield ParsedRecord(kind="used", key=row["listing_key"], row=row)


stock = Capability(name="used-stock", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("used",))
provider = Provider(name="motorpoint_used", default_capability="used-stock", capabilities={"used-stock": stock}, live=True)
