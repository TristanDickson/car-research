"""Kia dealer groups' offer pages: the worked PCP example each prints for an electric model.

Kia's own pages give only the headline ("3.9% APR, up to £3,000 contribution") and its quote API
answers "No quote available", but dealer groups print the complete representative example, each
with its own contribution on top of Kia's. Two groups, plain HTML, one target each:

  lloyd   Lloyd Motor Group, /Kia/Current-Offers (one page per offer)
  hj      Halliwell Jones, /kia/offers (one page per offer)

A target's fetch reads the index, then every electric model's offer page (Motability, business
and lease offers left out), and keeps each response. The parser reads every "Representative
Example" on each page: monthly payment, deposit, Kia's and the dealer's contributions, the grant,
the on-the-road price, credit, interest, final payment, term, mileage, excess charge and APR.
The figures reconcile on the pages read (on-the-road price, less deposit, contributions and
grant, is the credit), which the row records as `reconciles`.
"""
from __future__ import annotations

import html as H
import json
import re
from collections.abc import Iterator

from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.parse import norm_key
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "kia-dealer"
SITES = {
    "lloyd": {"name": "Lloyd Kia", "base": "https://www.lloydmotorgroup.com", "index": "https://www.lloydmotorgroup.com/Kia/Current-Offers",
              "link": r'href="(/Kia/Current-Offers/[^"]+)"', "headings": True},
    "hj": {"name": "Halliwell Jones Kia", "base": "https://www.halliwelljones.co.uk", "index": "https://www.halliwelljones.co.uk/kia/offers",
           "link": r'href="(https://www\.halliwelljones\.co\.uk/kia/offers/[^"]+)"', "headings": False},
}
ELECTRIC = re.compile(r"\b(ev[2-9]|pv5|niro[- ]?ev|e-?niro)\b", re.I)
SKIP = re.compile(r"motability|business|pch|contract-hire|hybrid|petrol|diesel", re.I)
MAX_PAGES = 30


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for key, s in SITES.items():
        if target.identifier in ("all", key):
            yield Target(identifier=key, metadata={"url": s["index"], "site": key})


def offer_links(index_html: str, site: str) -> list[str]:
    s = SITES[site]
    out: list[str] = []
    for href in re.findall(s["link"], index_html):
        url = href if href.startswith("http") else s["base"] + href
        if ELECTRIC.search(url.replace("-", " ")) and not SKIP.search(url) and url not in out:
            out.append(url)
    return out[:MAX_PAGES]


def fetch(target: Target, ctx: Context) -> Fetched:
    """The index, then every electric offer page it links, joined (each response also kept as it came)."""
    site = target.metadata["site"]
    parts: list[Fetched] = []
    try:
        index = fetch_url(target.metadata["url"], ctx)
        parts.append(index)
        pages = []
        for url in offer_links(index.body.decode("utf-8", "replace"), site):
            f = fetch_url(url, ctx)
            parts.append(f)
            pages.append({"url": url, "html": f.body.decode("utf-8", "replace")})
    except FetchError as e:
        e.parts = tuple(parts)
        raise
    body = json.dumps({"site": site, "pages": pages}, ensure_ascii=False).encode("utf-8")
    return Fetched(url=target.metadata["url"], status_code=200, body=body, content_type="application/json", parts=tuple(parts))


def page_text(page: str) -> str:
    page = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", page)
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def _money(block: str, *labels: str) -> float | None:
    for label in labels:
        m = re.search(label + r"[^£\d]{0,40}£\s*([\d,]+(?:\.\d+)?)", block, re.I)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def _pct(block: str, *labels: str) -> float | None:
    for label in labels:
        m = re.search(label, block, re.I)
        if m:
            return float(m.group(1)) / 100
    return None


def _label(text: str, start: int, block: str, headings: bool = True) -> str | None:
    """The car the example is for: 'Based on a Kia EV3 GT-Line.' in the block, else (where the site's headings sit right
    before their examples, as Lloyd's do) the 'Kia ...' heading just before it. Halliwell Jones's model pages run one
    card's heading into the next card's example, so there only an example that names its own car counts here (its
    offer pages are labelled by parse_page from the page's own heading)."""
    m = re.search(r"Based on an? (Kia [^.]{3,80}?)\.(?:\s|$)", block)
    if m:
        return m.group(1).strip()
    if not headings:
        return None
    before = text[max(0, start - 200):start]
    heads = list(re.finditer(r"Kia (?:EV\d|PV5|Niro EV|e-Niro)\b", before, re.I))
    if not heads:
        return None
    name = before[heads[-1].start():]   # the last heading before the example names it
    name = re.sub(r"\s*(?:Personal Contract Purchase \(PCP\)|PCP)\s*$", "", name).replace("'", "")
    return name.strip() or None


def parse_page(page: str, url: str, site: str, observed_at: str) -> list[dict]:
    text = page_text(page)
    starts = [m.start() for m in re.finditer(r"Representative Example", text)]
    # An offer page (Halliwell Jones): its heading names the car, and its banner ('From only £399 p/m Deposit
    # £4,999') says which of the page's examples is that offer's.
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    h1 = page_text(h1.group(1)) if h1 else None
    banner = re.search(r"From only £\s*([\d,.]+)\s*p/m\s*Deposit £\s*([\d,.]+)", text)
    rows = []
    for i, start in enumerate(starts):
        block = text[start:starts[i + 1] if i + 1 < len(starts) else start + 1600]
        label = _label(text, start, block, SITES[site]["headings"])
        monthly = _money(block, r"Monthly Payment")
        if not label and not SITES[site]["headings"] and "/offers/kia-" in url and h1 and banner and monthly is not None:
            if (monthly, _money(block, r"Customer Deposit")) == (float(banner.group(1).replace(",", "")), float(banner.group(2).replace(",", ""))):
                label = h1
        if not label or not monthly or not ELECTRIC.search(label):
            continue
        name = re.sub(r"\s+", " ", re.sub(r"\b(\d+)\s*Kw\b", r"\1kW", re.sub(r"Kwh", "kWh", label, flags=re.I)))
        model = ELECTRIC.search(name).group(1).upper().replace("NIRO EV", "Niro EV")
        derivative = name.split(model, 1)[-1].strip() if model in name else name
        otr = _money(block, r"On the Road (?:Cash )?Price")
        grant = _money(block, r"Electric Car Grant") or 0.0
        deposit = _money(block, r"Customer Deposit") or 0.0
        kia = _money(block, r"Kia UK Deposit Contribution") or 0.0
        loyalty = _money(block, r"Kia UK Loyalty contribution") or 0.0
        dealer = _money(block, r"(?:Lloyd Kia|Dealer) (?:Deposit )?Contribution") or 0.0
        credit = _money(block, r"Amount of Credit")
        term = re.search(r"(?:Duration|Term) of Agreement\s*(\d+)\s*months", block, re.I)
        miles = re.search(r"Estimated Annual Mileage\s*([\d,]+)", block, re.I) or re.search(r"\(([\d,]+) per annum\)", block, re.I)
        excess = re.search(r"Excess Mileage Charge[^£\d]{0,30}(£\s*0?\.(\d+)|(\d+(?:\.\d+)?)p)", block, re.I)
        ppm = (float("0." + excess.group(2)) * 100 if excess.group(2) else float(excess.group(3))) if excess else None
        # The offer's dates, from the terms that follow the example (a page can carry an old offer's terms).
        valid = re.search(r"between (\d{2})\.(\d{2})\.(\d{4}) and (\d{2})\.(\d{2})\.(\d{4})", text[start:start + 2500])
        price = otr - grant if otr else None
        contribution = kia + loyalty + dealer
        reconciles = abs(price - deposit - contribution - credit) <= 2 if price and credit else None
        key = f"{site}:{norm_key(name).replace(' ', '-')}:pcp"
        n = int(term.group(1)) - 1 if term else None
        rows.append({
            "id": key, "offer_key": key, "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "live", "verification": "scraped", "source": SITES[site]["name"], "dealer": SITES[site]["name"],
            "source_url": url, "car_ref": {"source": SITE, "key": norm_key(site, name), "label": name, "make": "Kia", "model": model,
                                           "derivative": derivative or name},
            "finance_type": "pcp", "list_price": otr, "grant_gbp": grant, "vehicle_price": price,
            "customer_deposit": deposit, "manufacturer_contribution": contribution,
            "kia_contribution": kia + loyalty, "dealer_contribution": dealer, "amount_of_credit": credit,
            "monthly_payment": monthly, "num_payments": n, "term_months": int(term.group(1)) if term else None,
            "apr": _pct(block, r"([\d.]+)%\s*APR", r"Representative APR\s*([\d.]+)%"),
            "fixed_rate_pa": _pct(block, r"(?:Fixed )?Rate of Interest\s*([\d.]+)%"),
            "gfv": _money(block, r"Optional Final Payment"), "total_payable_stated": _money(block, r"Total Amount Payable"),
            "cost_of_credit_stated": _money(block, r"Interest Charges"),
            "annual_mileage": int(miles.group(1).replace(",", "")) if miles else None, "excess_mileage_ppm": ppm,
            "valid_from": f"{valid.group(3)}-{valid.group(2)}-{valid.group(1)}" if valid else None,
            "valid_to": f"{valid.group(6)}-{valid.group(5)}-{valid.group(4)}" if valid else None,
            "reconciles": reconciles,
            "notes": f"{SITES[site]['name']}'s representative example, with its own deposit contribution on top of Kia's.",
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    doc = json.loads(body.decode("utf-8", "replace"))
    seen: set[str] = set()
    for p in doc.get("pages") or []:
        for row in parse_page(p["html"], p["url"], doc["site"], observed_at_for(target)):
            if row["offer_key"] not in seen:
                seen.add(row["offer_key"])
                yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


offers = Capability(name="offers", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="kia_dealers", default_capability="offers", capabilities={"offers": offers}, live=True)
