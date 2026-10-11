"""RRG Kia's offer pages: the representative finance example each prints, PCP or personal lease.

The index (https://www.rrg-group.com/kia/new-car-offers/, ten offers a page) lists every Kia
offer RRG runs. The `kia/offers` target reads every page of it, then every electric model's
offer page it lists (EV2 to EV9, PV5, Niro EV; PCP and personal lease), and keeps each response.
Each offer page prints one example as a table under 'Representative Finance Example based on
<offer>': the derivative, then label and value rows in an order that differs by page. The parser
reads them label by label. A PCP example gives the monthly payment and count, deposit, deposit
contribution, grant, on-the-road price, credit, interest, final payment, term, mileage, excess
charge and APR, and records `reconciles` (on-the-road price, less deposit, contribution and grant,
is the credit). A personal-lease (PCH) example gives the advance rental, the monthly rental and
the number of rentals, VAT included, and no mileage.

RRG copies derivative lines between pages: on 11 Oct five PV5 pages printed 'PV5 Electric Estate
120Kw Elite Long Range 71Kwh 5Dr Auto [7 Seat]' (or 'Plus') under a heading naming another trim
or seat count, and the on-the-road price agreed with the heading. Where the heading and the
derivative line disagree on trim, battery range or seats, the heading names the car
(`name_conflict` keeps both), so the hand mapping of the Elite 7-seat line does not claim those
offers. A PCP row's car_ref carries the on-the-road price as `rrp`, which tells 5- and 7-seat
twins apart where it equals one's list price.

An offer page whose offer has ended redirects to the index (RRG's EV3 page did on 11 Oct), so it
prints no example and yields nothing.
"""
from __future__ import annotations

import html as H
import json
import re
from collections.abc import Iterator

from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.parse import norm_key, number, slug, text
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "rrg"
BASE = "https://www.rrg-group.com"
INDEX = BASE + "/kia/new-car-offers/"
# Electric offer pages seen on the index, plus older ones the Wayback Machine holds: what the
# backfill reads (the nightly run reads the index instead).
KNOWN = ("pv5-passenger-7-seater", "pv5-passenger-pcp", "pv5-passenger-long-range-plus-7-seater",
         "pv5-passenger-with-met-long-range-plus", "pv5-passenger-elite-7-seater-pch", "pv5-passenger-long-range-160-plus",
         "pv5-passenger-long-range-elite-5-seater", "pv5-passenger-standard-range-essential-5-seater",
         "ev2-offer", "ev2-39percent-apr-representative", "ev3", "ev3-air", "ev3-air-583kwh-auto-fwd-pch",
         "ev4", "ev5-storm", "ev6", "ev9")
# The page read before 11 Oct 2026: its offer keeps the key its history was recorded under.
KEYED_BY_DERIVATIVE = {"pv5-passenger-7-seater"}
ELECTRIC = re.compile(r"\b(ev\d|pv5|niro[ -]?ev|e[ -]?niro)\b", re.I)
OFFER_LINK = re.compile(r'href="(?:https?:)?(?://www\.rrg-group\.com)?/kia/new-car-offers/([a-z0-9-]+)/"')
NOT_OFFERS = {"search", "enquiry"}
MAX_INDEX_PAGES = 5
MAX_PAGES = 30
TRIMS = re.compile(r"\b(gt-line s|gt-line|gt|essential|plus|elite|air|earth|light)\b", re.I)
RANGE = re.compile(r"\b(standard|long) range\b", re.I)
SEATS = re.compile(r"(\d)[\s-]*seat", re.I)
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}


def page_url(page: str) -> str:
    return f"{INDEX}{page}/"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    if target.identifier in ("all", "kia/offers"):
        yield Target(identifier="kia/offers", metadata={"url": INDEX, "kind": "index"})
    elif target.identifier.startswith("kia/"):
        yield Target(identifier=target.identifier, metadata={"url": page_url(target.identifier[4:])})


def discover_known(target: Target, ctx: Context) -> Iterator[Target]:
    for page in KNOWN:
        if target.identifier in ("all", f"kia/{page}"):
            yield Target(identifier=f"kia/{page}", metadata={"url": page_url(page)})


def index_pages(index_html: str) -> list[str]:
    """The index's other pages, as its pager links them ('?page=2&per_page=10')."""
    pages = {int(n): H.unescape(q) for q, n in re.findall(r'href="/kia/new-car-offers/(\?page=(\d+)[^"]*)"', index_html)}
    return [INDEX + pages[n] for n in sorted(pages) if n > 1]


def offer_links(index_html: str) -> list[tuple[str, bool]]:
    """(page, electric) for each offer the index lists, from its listing cards (the advert carousel above
    them can link an ended offer); every offer link on the page if it has no cards."""
    cards = re.split(r'<div class="list-item ', index_html)[1:] or [index_html]
    out: list[tuple[str, bool]] = []
    for card in cards:
        model = re.match(r'[^"]*\bmodel-([\w-]+)', card)
        for page in OFFER_LINK.findall(card):
            if page in NOT_OFFERS or page in (p for p, _ in out):
                continue
            out.append((page, bool(ELECTRIC.search(f"{page} {model.group(1) if model else ''}".replace("-", " ")))))
            if len(cards) > 1:
                break   # a card links one offer
    return out


def fetch(target: Target, ctx: Context) -> Fetched:
    """One offer page; or, for the index target, every page of the index, then every electric offer page it
    lists, joined (each response also kept as it came)."""
    if target.metadata.get("kind") != "index":
        return fetch_url(target.metadata["url"], ctx)
    parts: list[Fetched] = []
    listed: list[tuple[str, bool]] = []
    pages: list[dict] = []
    try:
        queue, seen, index = [target.metadata["url"]], {target.metadata["url"]}, []
        while queue and len(index) < MAX_INDEX_PAGES:
            f = fetch_url(queue.pop(0), ctx)
            parts.append(f)
            index.append(f.body.decode("utf-8", "replace"))
            listed += [link for link in offer_links(index[-1]) if link[0] not in (p for p, _ in listed)]
            for url in index_pages(index[-1]):
                if url not in seen:
                    seen.add(url)
                    queue.append(url)
        for page in [p for p, electric in listed if electric][:MAX_PAGES]:
            f = fetch_url(page_url(page), ctx)
            parts.append(f)
            pages.append({"url": page_url(page), "html": f.body.decode("utf-8", "replace")})
    except FetchError as e:
        e.parts = tuple(parts)
        raise
    available = re.search(r"(\d+)\s*Offers available", text(index[0]))
    body = json.dumps({"offers_available": int(available.group(1)) if available else None,
                       "listed": [page_url(p) for p, _ in listed], "pages": pages}, ensure_ascii=False).encode("utf-8")
    return Fetched(url=target.metadata["url"], status_code=200, body=body, content_type="application/json", parts=tuple(parts))


def _rows(table: str) -> list[tuple[str, str]]:
    return [(text(label), text(value)) for label, value in
            re.findall(r'<td class="label">(.*?)</td>\s*<td class="value[^"]*">(.*?)</td>', table, re.S)]


def _get(rows: list[tuple[str, str]], pattern: str) -> tuple[str, str] | None:
    for label, value in rows:
        if re.fullmatch(pattern, label.rstrip("+ "), re.I):
            return label, value
    return None


def _money(rows: list[tuple[str, str]], pattern: str) -> float | None:
    hit = _get(rows, pattern)
    m = re.search(r"£\s*([\d,]+(?:\.\d+)?)", hit[1]) if hit else None
    return float(m.group(1).replace(",", "")) if m else None


def _num(rows: list[tuple[str, str]], pattern: str) -> float | None:
    hit = _get(rows, pattern)
    return number(hit[1]) if hit else None


def _dates(after: str) -> tuple[str | None, str | None]:
    """The offer's dates: the first range printed after the example ('01/10/2026 to 15/12/2026',
    '01.10.2026 and 15.12.2026', 'From 1st October 2026 until 15th October 2026')."""
    found = []
    m = re.search(r"(\d{2})[./](\d{2})[./](\d{4})\s*(?:to|and|-|–|until)\s*(\d{2})[./](\d{2})[./](\d{4})", after)
    if m:
        found.append((m.start(), f"{m[3]}-{m[2]}-{m[1]}", f"{m[6]}-{m[5]}-{m[4]}"))
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+)\s+(\d{4})\s+(?:to|until|and|-)\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+)\s+(\d{4})", after)
    if m and m[2].lower() in MONTHS and m[5].lower() in MONTHS:
        found.append((m.start(), f"{m[3]}-{MONTHS[m[2].lower()]:02d}-{int(m[1]):02d}", f"{m[6]}-{MONTHS[m[5].lower()]:02d}-{int(m[4]):02d}"))
    if not found:
        return None, None
    _, start, end = min(found)
    return start, end


def _conflict(heading: str, derivative: str) -> bool:
    """Whether the offer's heading names another trim, battery range or seat count than its derivative line."""
    for rx in (TRIMS, RANGE, SEATS):
        h = {m.lower() for m in rx.findall(heading)}
        d = {m.lower() for m in rx.findall(derivative)}
        if h and d and not h & d:
            return True
    return False


def _page(url: str) -> str | None:
    m = re.search(r"/kia/new-car-offers/([a-z0-9-]+)/?$", url or "")
    return m.group(1) if m else None


def parse_page(page: str, url: str, observed_at: str) -> list[dict]:
    rows: list[dict] = []
    heads = list(re.finditer(r"Representative Finance Example based on\s*(.*?)</h3>", page, re.S))
    for i, h in enumerate(heads):
        end = page.find("</table>", h.end())
        block = page[h.end():end if end > 0 else h.end() + 6000]
        table = _rows(block)
        product = re.search(r'class="finance-product-label">\s*<span class="value">(.*?)</span>', block, re.S)
        heading = text(h.group(1))
        offer = re.sub(r"\s*\(PCH\)|:?\s*[\d.]+% APR Representative", "", heading, flags=re.I).strip()
        printed = text(product.group(1)) if product else ""
        model_line = (_get(table, r"Model") or (None, ""))[1]
        conflict = bool(printed) and _conflict(offer, printed)
        name = offer if conflict or not printed else printed
        found = ELECTRIC.search(name) or ELECTRIC.search(offer)
        if not table or not found:
            continue
        model = found.group(1).upper().replace("NIRO EV", "Niro EV").replace("NIRO-EV", "Niro EV")
        derivative = re.sub(r"^(?:Kia\s+)?" + re.escape(found.group(1)) + r"\s*", "", name, flags=re.I).strip() or name
        pch = _get(table, r"\d+ Monthly Rentals") is not None or _get(table, r"(?:Total |Finance )?Monthly Rental") is not None
        ftype = "pch" if pch else "pcp"
        pg = _page(url)
        if pg is None or pg in KEYED_BY_DERIVATIVE:
            key = f"rrg:{slug(printed or name)}:{ftype}"
        else:
            key = f"rrg:{pg}:{ftype}" + (f"-{i + 1}" if i else "")
        valid_from, valid_to = _dates(text(page[end:end + 20000]) if end > 0 else "")
        pv5 = model == "PV5"
        base = {
            "id": key, "offer_key": key, "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
            "status": "live", "verification": "scraped", "source": "RRG Kia offers page",
            "dealer": "RRG Kia (GWR Kia PBV Centre)" if pv5 else "RRG Kia",
            "source_url": url,
            "car_ref": {"source": SITE, "key": norm_key("kia", name), "label": f"Kia {name}", "make": "Kia", "model": model,
                        "derivative": derivative},
            "finance_type": ftype, "offer_title": offer, "valid_from": valid_from, "valid_to": valid_to,
        }
        if model_line:
            base["example_model"] = model_line
        if conflict:
            base["name_conflict"] = {"heading": offer, "derivative_printed": printed}
        note = (f" Its derivative line reads '{printed}', which contradicts the offer's heading; the heading names the car."
                if conflict else "")
        if pch:
            monthly = _money(table, r"Total Monthly Rental") or _money(table, r"Finance Monthly Rental") \
                or _money(table, r"\d+ Monthly Rentals")
            n = _get(table, r"(\d+) Monthly Rentals")
            n = int(re.match(r"\d+", n[0]).group()) if n else None
            upfront = (_money(table, r"Initial Rental") or 0.0) + (_money(table, r"Advance Rental") or 0.0) \
                or _money(table, r"Advance Payments")
            months = round(upfront / monthly) if upfront and monthly else None
            rows.append({**base, "term_months": n + 1 if n else None, "profile": f"{months}+{n}" if months and n else None,
                         "initial_rental": upfront, "num_rentals": n, "monthly_rental": monthly,
                         "service_monthly_rental": _money(table, r"Service Monthly Rental"), "annual_mileage": None,
                         "notes": f"RRG's personal lease example for {offer}: an advance rental, then {n} monthly rentals, "
                                  f"VAT included; the page prints no mileage or excess charge." + note})
            continue
        otr = _money(table, r"On the Road (?:Cash )?Price")
        grant = _money(table, r"Electric Car Grant") or 0.0
        deposit = _money(table, r"Customer Deposit") or 0.0
        kia = _money(table, r"Kia(?: UK)? Deposit Contribution") or 0.0
        dealer = _money(table, r"(?:Dealer|RRG|Retailer) (?:Deposit )?Contribution") or 0.0
        plain = _money(table, r"(?:PCP |Finance )*Deposit Contribution") or 0.0
        contribution = kia + dealer + plain
        credit = _money(table, r"Amount of Credit")
        payments = _get(table, r"(\d+) Monthly Payments(?: of)?")
        monthly = _money(table, r"\d+ Monthly Payments(?: of)?")
        n = int(re.match(r"\d+", payments[0]).group()) if payments else None
        term = _num(table, r"(?:Duration|Term) of Agreement")
        apr = _num(table, r"Representative APR")
        fixed = _num(table, r"(?:Fixed )?Rate of Interest")
        excess = _get(table, r"Excess Mileage Charge(?: per mile)?")
        ppm = None
        if excess:
            m = re.search(r"£\s*0?\.(\d+)|(\d+(?:\.\d+)?)\s*p", excess[1])
            ppm = (float("0." + m.group(1)) * 100 if m.group(1) else float(m.group(2))) if m else None
        miles = _num(table, r"(?:Estimated )?Annual Mileage")
        price = round(otr - grant, 2) if otr else None
        reconciles = abs(price - deposit - contribution - credit) <= 2 if price and credit else None
        if otr:   # tells a derivative's twins apart (5 and 7 seats) where it equals one's list price
            base["car_ref"]["rrp"] = otr
        rows.append({
            **base, "list_price": otr, "grant_gbp": grant, "vehicle_price": price,
            "customer_deposit": deposit, "manufacturer_contribution": contribution,
            "kia_contribution": kia, "dealer_contribution": dealer, "amount_of_credit": credit,
            "term_months": int(term) if term else (n + 1 if n else None), "num_payments": n, "monthly_payment": monthly,
            "apr": round(apr / 100, 6) if apr is not None else None,
            "fixed_rate_pa": round(fixed / 100, 6) if fixed is not None else None,
            "gfv": _money(table, r"Optional Final Payment"), "cost_of_credit_stated": _money(table, r"Interest Charges"),
            "total_payable_stated": _money(table, r"Total Amount Payable"),
            "annual_mileage": int(miles) if miles else None, "excess_mileage_ppm": ppm, "reconciles": reconciles,
            "notes": f"Representative example for {offer}; the deposit is the dealer's example, not £0."
                     + (" The deposit contribution is printed without saying whether Kia or RRG pays it." if plain else "") + note,
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    observed_at = observed_at_for(target)
    doc = body.decode("utf-8", "replace")
    pages = json.loads(doc)["pages"] if doc.lstrip().startswith("{") else [{"url": original_url(target), "html": doc}]
    seen: set[str] = set()
    for p in pages:
        if not isinstance(p, dict) or not p.get("html"):
            continue
        for row in parse_page(p["html"], p.get("url") or "", observed_at):
            if row["offer_key"] not in seen:
                seen.add(row["offer_key"])
                yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


offers = Capability(name="offers", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
_known = Capability(name="offers", parser_version="2", discover=discover_known, fetch=fetch, parse=parse, kinds=("offer",))
provider = Provider(name="rrg", default_capability="offers", capabilities={"offers": offers, "backfill": backfill_capability(_known)},
                    live=True)
