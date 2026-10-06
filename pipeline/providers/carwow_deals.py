"""Carwow public model deals pages: https://www.carwow.co.uk/<make>/<model>/deals

Server-rendered, no login. Per trim section, one card per derivative with the
CAP derivative id, RRP, Carwow's best cash price and either an indicative
"Monthly from" (Hyundai pages, on the footnote's basis) or a separate "PCP
Finance" price (Kia pages: the price you pay if you take the manufacturer's
PCP, which can differ from cash). Plus one model-level representative PCP
example, matched to its derivative by RRP.

Emits one cash observation per derivative (offer key carwow:cash:<cap id>) and
one illustrative PCP observation for the example. Trim resolution is by CAP id
(trim_map source 'carwow-cap'), which is stable across visits; a derivative
nobody curates resolves to a generated car (made from its spec row, or from
the stub this page carries in car_ref when the spec page does not list it).
Which models to read comes from the catalogue (carwow_catalog).
"""
from __future__ import annotations

import html as H
import re
from collections.abc import Iterator

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.http import fetch_url
from pipeline.providers.parse import money, number, pct, text
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "carwow-cap"
MODELS = [
    ("hyundai", "ioniq-3"), ("hyundai", "kona-electric"), ("hyundai", "inster"), ("hyundai", "ioniq-5"),
    ("kia", "pv5-passenger"), ("kia", "ev2"), ("kia", "ev3"), ("kia", "ev6"),
]
DERIV_RE = re.compile(
    r"class='derivative-deals__derivative'(.*?)(?=class='derivative-deals__derivative'|class='deals-finance-breakdown'|$)",
    re.S,
)
PRICE_RE = re.compile(r"prices-label'>\s*(.*?)\s*</div>\s*<div class='product-deal__pricing__prices-value'>\s*(.*?)\s*</div>", re.S)
DL_RE = re.compile(r"<dt>\s*(.*?)\s*</dt>\s*<dd>\s*(.*?)\s*</dd>", re.S)


def url_for(make: str, model: str) -> str:
    return f"https://www.carwow.co.uk/{make}/{model}/deals"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    """Every electric model with a deals page, from the catalogue; the static
    list when no catalogue has been written yet (first run, tests)."""
    models = electric_models(ctx, "has_deals") or [
        {"make": mk, "model": mo, "make_name": pretty_make(mk)} for mk, mo in MODELS]
    for m in models:
        ident = f"{m['make']}/{m['model']}"
        if target.identifier in ("all", ident):
            yield Target(identifier=ident, metadata={"make": m["make"], "model": m["model"], "make_name": m["make_name"],
                                                     "url": url_for(m["make"], m["model"])})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def parse_page(page: str, make: str, model: str, url: str, observed_at: str, make_name: str | None = None) -> list[dict]:
    make_name = make_name or pretty_make(make)
    derivatives = []
    for m in DERIV_RE.finditer(page):
        b = m.group(1)
        cap = re.search(r"cap_derivative_id=(\d+)", b)
        if not cap:
            continue
        trim = re.search(r'data-interaction-section="([^"]+) Trim"', b)
        parts = [text(p) for p in re.findall(r"<span class='product-title__part'>(.*?)</span>", b, re.S)]
        parts = [p for p in parts if p]
        version = re.search(r"derivative_version_id=([^&\"']+)", b)
        rrp = money(re.search(r"rrp-value'>\s*(£[\d,]+)", b).group(1)) if re.search(r"rrp-value'>\s*(£[\d,]+)", b) else None
        prices = {text(k): text(v) for k, v in PRICE_RE.findall(b)}
        derivatives.append({
            "cap": cap.group(1), "trim": trim.group(1) if trim else None, "title": " ".join(parts),
            # title parts are [model, engine]: enough to generate a car for a derivative nobody curates
            "model_name": parts[0] if parts else model, "engine": " ".join(parts[1:]),
            "version": version.group(1) if version else None, "rrp": rrp,
            "cash": money(prices.get("Cash")), "pcp_price": money(prices.get("PCP Finance")),
            "monthly_from": money(prices.get("Monthly from*") or prices.get("Monthly from")),
        })

    note = re.search(r"offer-finance-details__note'>\s*(.*?)\s*</p>", page, re.S)
    basis = text(note.group(1)) if note else None
    example = None
    rep = re.search(r"offer-finance-details__representative-table'>(.*?)</dl>", page, re.S)
    if rep:
        fields = {text(k): text(v) for k, v in DL_RE.findall(rep.group(1))}
        if fields.get("Monthly payment"):
            example = fields

    def ref(d: dict, label: str) -> dict:
        version_date = d["version"].rsplit("_", 1)[-1] if d["version"] and "_" in d["version"] else None
        return {"source": SITE, "key": d["cap"], "label": label,
                "stub": {"cap_id": d["cap"], "make": make_name, "make_slug": make, "model": d["model_name"], "model_slug": model,
                         "trim": d["trim"], "engine": d["engine"], "rrp": d["rrp"],
                         "version_date": version_date if version_date and len(version_date) == 10 else None}}

    rows: list[dict] = []
    for d in derivatives:
        label = f"{make_name} {d['title']} · {d['trim']} · RRP £{d['rrp']:,.0f}" if d["rrp"] else f"{make_name} {d['title']} · {d['trim']}"
        row = {
            "id": f"carwow:cash:{d['cap']}", "offer_key": f"carwow:cash:{d['cap']}",
            "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "lead", "verification": "scraped", "source": "Carwow best price",
            "source_url": url, "source_ref": f"CAP {d['cap']}" + (f" / {d['version']}" if d["version"] else ""),
            "car_ref": ref(d, label),
            "finance_type": "cash", "list_price": d["rrp"], "vehicle_price": d["cash"],
            "saving_stated": round(d["rrp"] - d["cash"], 2) if d["rrp"] and d["cash"] else None,
            "carwow_trim": d["trim"], "carwow_title": d["title"],
            "notes": "Best price across Carwow's dealers for this derivative; a named dealer offer needs the logged-in quotes page.",
        }
        if d["pcp_price"] is not None:
            row["pcp_finance_price"] = d["pcp_price"]
            row["pcp_finance_price_delta"] = round(d["pcp_price"] - d["cash"], 2) if d["cash"] else None
        if d["monthly_from"] is not None:
            row["monthly_from_indicative"] = d["monthly_from"]
            row["indicative_basis"] = basis
        if d["cash"] is None:
            continue
        rows.append(row)

    if example:
        rrp = money(example.get("RRP"))
        match = next((d for d in derivatives if d["rrp"] == rrp), None)
        if match:
            term = int(number(example.get("Term of agreement")) or 0) or None
            contrib_key = next((k for k in example if k.endswith("deposit contribution")), None)
            rows.append({
                "id": f"carwow:rep:{match['cap']}", "offer_key": f"carwow:rep:{match['cap']}",
                "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
                "status": "illustrative", "verification": "scraped",
                "source": "Carwow representative PCP example", "source_url": url,
                "source_ref": f"CAP {match['cap']}",
                "car_ref": ref(match, f"{make_name} {match['title']} · {match['trim']}"),
                "finance_type": "pcp",
                "list_price": rrp, "vehicle_price": money(example.get("Carwow price")),
                "customer_deposit": money(example.get("Customer deposit")) or 0.0,
                "manufacturer_contribution": money(example.get(contrib_key)) if contrib_key else 0.0,
                "amount_of_credit": money(example.get("Amount of credit")),
                "term_months": term, "num_payments": term,
                "monthly_payment": money(example.get("Monthly payment")),
                "apr": pct(example.get("Representative APR")),
                "fixed_rate_pa": pct(example.get("Fixed rate of interest")),
                "gfv": money(example.get("Optional final payment")),
                "total_payable_stated": money(example.get("Total amount payable")),
                "cost_of_credit_stated": money(example.get("Interest charges")),
                "annual_mileage": int(number(example.get("Mileage per annum")) or 0) or None,
                "excess_mileage_ppm": number(example.get("Excess mileage charges")),
                "notes": "Carwow's model-level representative example ('purely illustrative'); basis: " + (basis or ""),
            })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["make"], target.metadata["model"],
                          original_url(target), observed_at_for(target), target.metadata.get("make_name")):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


deals = Capability(name="deals", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="carwow_deals", default_capability="deals",
                    capabilities={"deals": deals, "backfill": backfill_capability(deals)}, live=True)
