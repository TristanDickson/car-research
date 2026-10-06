"""Hyundai UK per-model offer pages: /uk/en/offers/new-cars/model/offer.<model>.html

Each offer component carries a data-js-options attribute (HTML-escaped JSON)
with the representative PCP example in full: CAP code, OTR after grant, deposit,
contribution, APR, monthly, balloon, mileage. Offer key = Hyundai's own
offerResourceName; trim resolution by CAP code (source 'hyundai-cap').
"""
from __future__ import annotations

import html as H
import json
import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import number, text
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "hyundai-cap"
MODELS = ["kona_electric", "inster", "ioniq_5", "all-new_ioniq_3"]
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d\d)")


def _iso(s: str) -> str | None:
    d = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(20\d\d)", (s or "").strip())
    if d:
        return f"{int(d.group(3)):04d}-{int(d.group(2)):02d}-{int(d.group(1)):02d}"
    m = DATE_RE.search(s or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for model in MODELS:
        if target.identifier in ("all", model):
            yield Target(identifier=model, metadata={"url": f"https://www.hyundai.com/uk/en/offers/new-cars/model/offer.{model}.html"})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def parse_page(page: str, url: str, observed_at: str) -> list[dict]:
    rows, seen = [], set()
    for m in re.finditer(r"data-js-options='(.*?)'", page, re.S):
        raw = H.unescape(m.group(1))
        if '"offers"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        o = (d.get("offers") or {}).get("PCP")
        if not o or not o.get("monthlyPayment") or o.get("offerResourceName") in seen:
            continue
        seen.add(o["offerResourceName"])
        terms = text(o.get("termsAndConditions") or "")
        # "ordered in the UK between 01/10/2026 and 04/01/2027" (occasionally "1st October 2026").
        dates = re.findall(r"(\d{1,2}/\d{1,2}/20\d\d|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+20\d\d)", terms)
        cap = re.sub(r"\s+", " ", (o.get("capCode") or "").strip())
        key = f"hyundai:{o['offerResourceName']}"
        # Every numeric field in Hyundai's JSON is a string ("454.46", "37.0").
        n = lambda k: number(o.get(k))  # noqa: E731
        i = lambda k: int(n(k)) if n(k) is not None else None  # noqa: E731
        rows.append({
            "id": key, "offer_key": key,
            "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "live", "verification": "scraped", "source": "Hyundai UK offer page", "dealer": "Hyundai Finance (national offer)",
            "source_url": url, "source_ref": o["offerResourceName"],
            "car_ref": {"source": SITE, "key": cap.lower(), "label": f"{o.get('model')} {o.get('trimAndPowertrain')} (CAP {cap})"},
            "finance_type": "pcp",
            "list_price": n("cashPrice"), "grant_gbp": n("discount1Value") or 0.0,
            "vehicle_price": n("otrPrice"),
            "manufacturer_contribution": n("depositContribution") or 0.0,
            "customer_deposit": n("deposit") or 0.0, "amount_of_credit": n("amountOfCredit"),
            "term_months": i("durationAgreement"), "num_payments": i("numberOfMonths"),
            "monthly_payment": n("monthlyPayment"),
            "apr": (n("apr") or 0.0) / 100, "fixed_rate_pa": (n("fixedRateInterest") or 0.0) / 100,
            "gfv": n("optionalFinalPayment"), "total_payable_stated": n("totalAmountPayable"),
            "cost_of_credit_stated": n("interestCharges"), "annual_mileage": i("annualMileage"),
            "excess_mileage_ppm": n("excessMileage"),
            "valid_from": _iso(dates[0]) if len(dates) >= 1 else None,
            "valid_to": _iso(dates[1]) if len(dates) >= 2 else None,
            "offer_strapline": text(o.get("offerStrapline") or ""),
            "heat_pump_listed": "heat pump" in text(o.get("modelInfo") or "").lower(),
            "configurator_url": ("https://www.hyundai.com" + o["deepLink"]) if o.get("deepLink") else None,
            "notes": "Hyundai's national representative example; the deposit is Hyundai's example, not £0. " + text(o.get("offerStrapline") or ""),
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), original_url(target), observed_at_for(target)):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


offers = Capability(name="offers", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="hyundai_offers", default_capability="offers", capabilities={"offers": offers, "backfill": backfill_capability(offers)}, live=True)
