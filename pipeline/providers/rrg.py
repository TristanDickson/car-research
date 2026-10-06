"""RRG Kia PV5 offers page: representative Kia Finance PCP examples in plain text."""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timezone

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import norm_key, number, slug, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "rrg"
PAGES = {"kia/pv5-passenger-7-seater": "https://www.rrg-group.com/kia/new-car-offers/pv5-passenger-7-seater/"}
EX_RE = re.compile(
    r"Representative Finance Example based on (?P<name>.+?) (?P<deriv>PV5 Electric Estate .+?) On the Road Price £\s*(?P<otr>[\d,.]+)"
    r"(?: Electric Car Grant £\s*(?P<grant>[\d,.]+))? Customer Deposit £\s*(?P<dep>[\d,.]+) Amount of Credit £\s*(?P<credit>[\d,.]+)"
    r" Duration of Agreement (?P<term>\d+) Fixed Rate of Interest (?P<fixed>[\d.]+)% Representative APR (?P<apr>[\d.]+)%"
    r" (?P<n>\d+) Monthly Payments of £\s*(?P<monthly>[\d,.]+) Optional Final Payment £\s*(?P<gfv>[\d,.]+)"
    r" Interest Charges £\s*(?P<interest>[\d,.]+) Total Amount Payable £\s*(?P<total>[\d,.]+)",
    re.S,
)


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for ident, url in PAGES.items():
        if target.identifier in ("all", ident):
            yield Target(identifier=ident, metadata={"url": url})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def parse_page(page: str, url: str, observed_at: str) -> list[dict]:
    t = text(page)
    rows = []
    for m in EX_RE.finditer(t):
        g = {k: (number(v) if v and k not in ("name", "deriv") else v) for k, v in m.groupdict().items()}
        key = f"rrg:{slug(g['deriv'])}:pcp"
        rows.append({
            "id": key, "offer_key": key,
            "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "live", "verification": "scraped", "source": "RRG Kia offers page", "dealer": "RRG Kia (GWR Kia PBV Centre)",
            "source_url": url,
            "car_ref": {"source": SITE, "key": norm_key("kia", g["deriv"]), "label": f"Kia {g['deriv']}"},
            "finance_type": "pcp", "list_price": g["otr"], "grant_gbp": g.get("grant") or 0.0,
            "vehicle_price": round(g["otr"] - (g.get("grant") or 0.0), 2),
            "manufacturer_contribution": 0.0, "customer_deposit": g["dep"], "amount_of_credit": g["credit"],
            "term_months": int(g["term"]), "num_payments": int(g["n"]), "monthly_payment": g["monthly"],
            "apr": g["apr"] / 100, "fixed_rate_pa": g["fixed"] / 100, "gfv": g["gfv"],
            "cost_of_credit_stated": g["interest"], "total_payable_stated": g["total"],
            "notes": f"Representative example for {g['name']}; the deposit is the dealer's example, not £0.",
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["url"], now):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


offers = Capability(name="offers", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="rrg", default_capability="offers", capabilities={"offers": offers}, live=True)
