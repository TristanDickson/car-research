"""New Car Discount model listings: https://www.new-car-discount.com/car/<make>/<model>/<body>/all/all

Server-rendered list of derivatives with the broker's all-in price (first
registration, road tax, warranty included; grant applied where it applies).
Only electric derivatives (a 'kW' in the name) are kept. Offer key is the
derivative's own URL path; trim resolution by the derivative text (trim_map
source 'ncd').

The `pcp` capability reads the same listings, then each electric derivative's own page and
the PCP quote that page asks for. The quote is not in the page: NCD's /js/detail-page.js
POSTs JSON to /fincalc with the page's CAP code (hidden `derivative-id`), the on-the-road
price plus any option ticked by default (`advance`), and the PCP tab's default mileage,
deposit and term (10,000 miles, £1,000, 36 months on all nine pages read on 11 Oct 2026). The answer
echoes those inputs with the payment, APR, final value and total repayable. NCD prints it as
"Based on 35 monthly payments ... APR for illustration is 7.9%", so the row is `illustrative`.
The combined body holds the listing and every request and answer; the derivative pages and
answers are kept as parts. Offer key `ncd:pcp:<derivative path>`, with the cash row's car_ref.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from pipeline.providers.http import Blocked, FetchError, fetch_url
from pipeline.providers.parse import money, norm_key, text
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target

SITE = "ncd"
BASE = "https://www.new-car-discount.com"
FINCALC = BASE + "/fincalc"
# NCD's price and saving are on the road: price + saving sits a constant £135
# above the manufacturer's RRP as Carwow prints it (first registration fee,
# first-year VED, plates). Observed on 21 of 30 Hyundai/Kia rows in Oct 2026;
# the rest were the next derivative up, which is what the offset prevents.
OTR_EXTRAS_GBP = 135.0
LISTINGS = {
    "hyundai/ioniq-3": "/car/hyundai/ioniq-3/hatchback/all/all",
    "hyundai/kona": "/car/hyundai/kona/hatchback/all/all",
    "hyundai/inster": "/car/hyundai/inster/hatchback/all/all",
    "hyundai/ioniq-5": "/car/hyundai/ioniq-5/hatchback/all/all",
    "kia/ev2": "/car/kia/ev2/hatchback/all/all",
    "kia/ev3": "/car/kia/ev3/estate/all/all",
    "kia/ev6": "/car/kia/ev6/estate/all/all",        # the GT only
    "kia/ev6-4x4": "/car/kia/ev6/4x4/all/all",       # every other EV6, and a GT of its own
    "kia/pv5": "/car/kia/pv5/mpv/all/all",
    # Every other electric Hyundai and Kia NCD's make pages listed on 11 Oct 2026.
    "hyundai/ioniq-5-n": "/car/hyundai/ioniq-5-n/hatchback/all/all",
    "hyundai/ioniq-6-n": "/car/hyundai/ioniq-6-n/saloon/all/all",
    "hyundai/ioniq-9": "/car/hyundai/ioniq-9/4x4/all/all",
    "kia/ev4": "/car/kia/ev4/hatchback/all/all",
    "kia/ev4-saloon": "/car/kia/ev4/saloon/all/all",   # Carwow's EV4 Fastback; NCD's RRP tells the bodies apart
    "kia/ev5": "/car/kia/ev5/4x4/all/all",
    "kia/ev9": "/car/kia/ev9/4x4/all/all",
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
                        "make": make, "model": group_t, "derivative": name_t,
                        # price + stated saving - OTR extras = the RRP, which pins the derivative among same-trim twins
                        "rrp": round(money(price.group(1)) + money(save.group(1)) - OTR_EXTRAS_GBP, 2) if save and money(save.group(1)) else None},
            "finance_type": "cash", "vehicle_price": money(price.group(1)),
            "saving_stated": money(save.group(1)) if save else None,
            "notes": "Broker all-in price including first registration, road tax and warranty. Availability for a December delivery not confirmed.",
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["make"], original_url(target), observed_at_for(target)):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


# ---------------------------------------------------------------- PCP quotes


def _figure(s: str | None) -> float | None:
    """The page's own reading of a field: every character but digits and '.' dropped (detail-page.js)."""
    d = re.sub(r"[^\d.]", "", s or "")
    try:
        return float(d) if d else None
    except ValueError:
        return None


def _json_num(x: float) -> float | int:
    return int(x) if x == int(x) else round(x, 2)


def _select_value(block: str, name: str) -> str | None:
    """A <select>'s value as jQuery reads it: the selected option, else the first."""
    m = re.search(rf'<select name="{name}"[^>]*>(.*?)</select>', block, re.S)
    if not m:
        return None
    opts = re.findall(r"<option([^>]*)>", m.group(1))
    chosen = next((o for o in opts if re.search(r"\bselected\b", o)), opts[0] if opts else "")
    v = re.search(r'value="([^"]*)"', chosen)
    return v.group(1) if v else None


def quote_request(page: str) -> dict | None:
    """The PCP request detail-page.js sends for this page at its defaults, or None if the page has no calculator."""
    if 'class="vehicle-title"' not in page:
        return None   # the script returns before the calculator on a page without a vehicle title
    cap = re.search(r'<input[^>]*\bid="derivative-id"[^>]*>', page)
    capcode = re.search(r'value="([^"]*)"', cap.group(0)) if cap else None
    total = re.search(r'<div class="total-price">.*?<span>(.*?)</span>', page, re.S)
    tab = re.search(r'<div id="t1-content" data-ftype="PCP"(.*?)<div id="t2-content"', page, re.S)
    if not (capcode and total and tab):
        return None
    commercial = re.search(r'class="(?:[^"]*\s)?commercial[\s"]', page) is not None
    options = 0.0
    for inp in re.findall(r'<input type="checkbox"[^>]*data-option-id="[^"]*"[^>]*>', page):
        if 'checked="checked"' not in inp:
            continue
        basic = _figure((re.search(r'data-option-basic="([^"]*)"', inp) or [None, ""])[1]) or 0.0
        vat = _figure((re.search(r'data-option-vat="([^"]*)"', inp) or [None, ""])[1]) or 0.0
        options += basic if commercial else basic + vat
    totali2 = re.search(r'<p class="totali2">(.*?)</p>', page, re.S)
    if totali2 and text(totali2.group(1)):
        advance = (_figure(text(totali2.group(1))) or 0.0) + options * 1.2
    else:
        advance = (_figure(text(total.group(1))) or 0.0) + options
    block = tab.group(1)
    deposit = re.search(r'<input name="fin-deposit"[^>]*value="([^"]*)"', block)
    mileage, term = _select_value(block, "fin-mileage"), _select_value(block, "fin-term")
    if not (advance and deposit and term):
        return None
    return {"ftype": "PCP", "autoSelectPlan": True, "username": "xml", "capcode": capcode.group(1),
            "advance": _json_num(advance), "mileage": _json_num(_figure(mileage) or 0.0),
            "deposit": _json_num(_figure(deposit.group(1)) or 0.0), "period": _json_num(_figure(term) or 0.0)}


def _failed(e: FetchError) -> Fetched | None:
    """The response a failed fetch got, if the site answered, so it is kept too."""
    if e.status is None and e.body is None:
        return None
    return Fetched(url=e.url or "", status_code=e.status or 0, body=e.body or b"")


def fetch_quotes(target: Target, ctx: Context) -> Fetched:
    """The listing, then for each electric derivative on it its page and its PCP quote, joined (each response kept)."""
    url = target.metadata["url"]
    listing = fetch_url(url, ctx)
    parts: list[Fetched] = [listing]
    quotes: list[dict] = []
    for row in parse_page(listing.body.decode("utf-8", "replace"), target.metadata["make"], url, ""):
        q: dict = {"href": row["source_url"][len(BASE):], "page_url": row["source_url"]}
        quotes.append(q)
        try:
            page = fetch_url(row["source_url"], ctx)
        except Blocked as e:
            q["error"] = str(e)
            break   # the host refuses: nothing more is asked of it this run
        except FetchError as e:
            if (f := _failed(e)) is not None:
                parts.append(f)
            q.update(page_status=e.status, error=str(e))
            continue
        parts.append(page)
        q["page_status"] = page.status_code
        req = quote_request(page.body.decode("utf-8", "replace"))
        if req is None:
            q["error"] = "no finance calculator on the page"
            continue
        q["request"] = req
        try:
            ans = fetch_url(FINCALC, ctx, data=json.dumps(req).encode("utf-8"), accept="application/json, text/javascript, */*; q=0.01",
                            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": row["source_url"]})
        except Blocked as e:
            q["error"] = str(e)
            break
        except FetchError as e:
            if (f := _failed(e)) is not None:
                parts.append(f)
            q.update(status=e.status, error=str(e))
            continue
        parts.append(ans)
        q["status"] = ans.status_code
        try:
            q["response"] = json.loads(ans.body.decode("utf-8", "replace"))
        except ValueError as e:
            q["error"] = f"answer is not JSON: {e}"
    if quotes and not any(isinstance(q.get("response"), dict) for q in quotes):
        e = FetchError(f"{url}: no derivative's quote answered ({quotes[0].get('error')})", url=url)
        e.parts = tuple(parts)
        raise e
    body = {"listing_url": url, "listing": listing.body.decode("utf-8", "replace"), "quotes": quotes}
    return Fetched(url=url, status_code=200, body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                   content_type="application/json", parts=tuple(parts))


def _f(d: dict, k: str) -> float | None:
    v = d.get(k)
    return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def quote_row(q: dict, cash: dict, observed_at: str) -> dict | None:
    """One PCP offer from NCD's answer, on the cash row's car."""
    a = q.get("response")
    if not isinstance(a, dict) or a.get("ftype") != "PCP" or not _f(a, "monthlyPayments"):
        return None
    period = int(a.get("period") or 0)
    n = period - 1 if period else None   # PCP: the last month is the optional final payment (detail-page.js)
    pay, gfv, deposit = _f(a, "monthlyPayments"), _f(a, "finalValue"), _f(a, "deposit") or 0.0
    price, credit, total = _f(a, "advance"), _f(a, "balanceToFinance"), _f(a, "totalRepayable")
    fees = round(sum(_f(a, k) or 0.0 for k in ("docFeeFrontend", "docFeeBackend", "purchaseFee")), 2)
    charges = round((_f(a, "interestRepayable") or 0.0) + fees, 2)   # the page's "Total charge for credit"
    reconciles = None
    if None not in (total, gfv) and n:
        reconciles = abs(deposit + pay * n + gfv - total) <= 5.0
    key = f"ncd:pcp:{q['href']}"
    note = (f"NCD's finance calculator at its page defaults ({int(a.get('mileage') or 0):,} miles a year, "
            f"£{deposit:,.0f} deposit, {period} months); NCD gives the APR 'for illustration', subject to status. "
            f"Plan: {a.get('planMatched') or 'not named'}.")
    if price is not None and cash.get("vehicle_price") is not None and abs(price - cash["vehicle_price"]) > 0.5:
        note += f" Financed price £{price:,.2f} differs from the listing's £{cash['vehicle_price']:,.0f} (options ticked by default)."
    if reconciles is False:
        note += " Its deposit, payments and final payment do not add up to its total repayable; kept as printed."
    return {
        "id": key, "offer_key": key, "observed_at": observed_at, "captured_at": observed_at[:10], "present": 1,
        "status": "illustrative", "verification": "scraped", "source": "New Car Discount", "dealer": "New Car Discount",
        "source_url": q.get("page_url") or BASE + q["href"], "listing_url": cash.get("listing_url"),
        "source_ref": a.get("capcode"), "car_ref": dict(cash["car_ref"]),
        "finance_type": "pcp", "vehicle_price": price, "customer_deposit": deposit, "manufacturer_contribution": 0.0,
        "amount_of_credit": credit, "monthly_payment": pay, "num_payments": n, "term_months": period or None,
        "apr": round(float(a.get("apr") or 0.0) / 100, 5), "gfv": gfv,
        "total_payable_stated": total, "cost_of_credit_stated": charges, "fees_gbp": fees,
        "annual_mileage": int(a["mileage"]) if a.get("mileage") else None, "reconciles": reconciles,
        "finance_plan": a.get("planMatched"), "notes": note,
    }


def parse_quotes(doc: dict, make: str, observed_at: str) -> list[dict]:
    cash = {r["source_url"][len(BASE):]: r for r in parse_page(doc.get("listing") or "", make, doc.get("listing_url") or "", observed_at)}
    rows = []
    for q in doc.get("quotes") or []:
        if q.get("href") in cash and (row := quote_row(q, cash[q["href"]], observed_at)):
            rows.append(row)
    return rows


def parse_pcp(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    doc = json.loads(body.decode("utf-8", "replace"))
    for row in parse_quotes(doc, target.metadata["make"], observed_at_for(target)):
        yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


listing = Capability(name="listing", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("offer",))
# No backfill: the Wayback Machine keeps pages, not the quote calls they make.
pcp = Capability(name="pcp", parser_version="1", discover=discover, fetch=fetch_quotes, parse=parse_pcp, kinds=("offer",))
provider = Provider(name="ncd", default_capability="listing",
                    capabilities={"listing": listing, "pcp": pcp, "backfill": backfill_capability(listing)}, live=True)
