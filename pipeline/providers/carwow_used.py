"""Carwow's used stock per model: the deal cards behind https://www.carwow.co.uk/<make>/<model>/used

The model page itself is a shell; the cards come from a Turbo frame on
quotes.carwow.co.uk (stock_cars/deal-cards). Each card prints the derivative as
CAP names it ('125kW 58 kWh Auto Premium Part Leather'), the price, the
registration year, the mileage, the dealer's town and a deal link. This is
Carwow's partner dealers' stock, not the whole used market, which is enough
for a 'buy used' route and for what a three-year-old example asks today, the
residual value the true-monthly needs.

A results page draws only its sponsored ('Ad') cards in full. Every other car
is a placeholder frame (`lazy_deal_card_<id>`) whose card the browser fetches
later from stock_cars/deal-card?id=<id>. The page names every car on it in
`results-deal-ids-value`, states the model's total in `results-count-value`,
and gives every car's price and registration year in
`results-ecommerce-items-value`. So one fetch is: the results pages (asked for
electric only, PER_PAGE to a page) until every stated car has been named, then
the deal card of each named car that has no full card on the pages, up to
tonight's share (see `_quotas`). A car whose card is not fetched tonight keeps
the card an earlier night fetched, carried into tonight's body with the date
it was seen. A car with no card at all yields a listing with only the price
and year from the ecommerce list (`detail` 'price-year'; derivative, mileage
and town unknown, no car_ref so the build does not guess its derivative).

Every response is kept as it came (Fetched.parts). The combined body the
parser reads starts with V2, then the results pages, then one segment per
fetched or carried card, cut down to the card itself (`slim`). A body without
V2 (fetched before this layout) is read as it always was: its full cards only.

Emits one 'used' record per car, keyed carwow-used:<deal hash>, electric cars
only. Gold keeps them as current stock (first / last seen, present) rather
than price history.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator
from urllib.parse import parse_qs, urlencode, urlparse

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.carwow_deals import MODELS
from pipeline.providers.http import REFUSED, Blocked, FetchError, fetch_url
from pipeline.providers.parse import money, number, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

NAME = "carwow_used"
SITE = "carwow-used"
HOST = "quotes.carwow.co.uk"
CARDS = f"https://{HOST}/stock_cars/deal-cards"
CARD = f"https://{HOST}/stock_cars/deal-card"
FRAME = "stock_cars_v2_cards"
PER_PAGE = 200   # Carwow's own pages ask for 12; 200 puts all but a handful of models on one page
MAX_PAGES = 40
PAGE_BREAK = "\n<!-- carwow-used page break -->\n"
V2 = "<!-- carwow-used v2: results pages, then the deal cards they show only as placeholders -->\n"
CARD_RE = re.compile(r"<div class='deal-card'>(.*?)(?=<div class='deal-card'>|</turbo-frame>|$)", re.S)
SEGMENT_RE = re.compile(r"<!-- carwow-used card ([0-9a-f]+)(?: seen (\S+))? -->")

# Every model shares CARD_BUDGET cards a night (a car's price comes from the results page each night; its
# card adds derivative, mileage and town, which rarely change): cars never fetched first, then the longest
# since fetched, each model's share from what its last fetch named. A run for one model fetches every card
# of it that is new or CARD_REFRESH_DAYS old.
CARD_REFRESH_DAYS = 7
CARD_BUDGET = 440
CARD_SECONDS = 60 * 60   # and never more than this of the night on cards, however slow the site is
UNSEEN_GUESS = 12        # cards to set aside for a model no earlier night fetched


def cards_url(make: str, model: str, page: int = 1) -> str:
    """The model's results as Carwow's own page asks for them. Page 1 is the target's url, which names the
    listing page its cars came from (gold retires a sampled source's cars per listing page), so it stays as it was."""
    q = {
        "brand_slug": make, "cross_domain": "true", "locked_filters[brand_slug]": make, "locked_filters[model_slug]": model,
        "locked_filters[vehicle_state_group]": "used", "locked_filters[vehicle_type]": "car", "model_slug": model,
        "page": page, "vehicle_state_group": "used", "vehicle_type": "car",
    }
    return f"{CARDS}?{urlencode(q)}"


def results_url(make: str, model: str, page: int = 1) -> str:
    """What the fetch asks for: electric cars only (the filter Carwow's brand pages use), PER_PAGE to a page."""
    return cards_url(make, model, page) + "&" + urlencode(
        {"locked_filters[vehicle_fuel_category]": "electric", "vehicle_fuel_category": "electric", "per_page": PER_PAGE})


def card_url(deal_id: str) -> str:
    return f"{CARD}?id={deal_id}"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    models = electric_models(ctx) or [{"make": mk, "model": mo, "make_name": pretty_make(mk)} for mk, mo in MODELS]
    wanted = [(f"{m['make']}/{m['model']}", m) for m in models if target.identifier in ("all", f"{m['make']}/{m['model']}")]
    # A run over every model shares the night's cards out; a run for one model fetches all of its cards.
    quotas = _quotas(ctx, [ident for ident, _ in wanted]) if target.identifier == "all" else {}
    for ident, m in wanted:
        meta = {"make": m["make"], "model": m["model"], "make_name": m["make_name"], "url": cards_url(m["make"], m["model"])}
        if ident in quotas:
            meta["card_quota"] = quotas[ident]
        yield Target(identifier=ident, metadata=meta)


# -- reading a results page


def _attr(page: str, name: str):
    m = re.search(rf"data-stock-cars-v2--results-{name}-value='([^']*)'", page)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1)))
    except ValueError:
        return None


def deal_ids(page: str) -> list[str]:
    """The cars drawn in full on a page (their deal links)."""
    return re.findall(r"quotes\.carwow\.co\.uk/deals/([0-9a-f]{16,})", page)


def page_ids(page: str) -> list[str]:
    """Every car a results page names, in its order: the ids it lists, else its placeholders and full cards."""
    ids = _attr(page, "deal-ids")
    if isinstance(ids, list):
        return [str(i) for i in ids]
    return list(dict.fromkeys(re.findall(r"lazy_deal_card_([0-9a-f]{16,})", page) + deal_ids(page)))


def stated_count(page: str) -> int | None:
    n = _attr(page, "count")
    return int(n) if isinstance(n, int) else None


def listing_items(page: str) -> dict[str, dict]:
    """deal id -> the page's ecommerce entry for it (price, year_registered, state_of_vehicle, ...)."""
    items = _attr(page, "ecommerce-items")
    return {str(i["item_id"]): i for i in items if isinstance(i, dict) and i.get("item_id")} if isinstance(items, list) else {}


def electric_only(page: str) -> bool:
    """Whether the page was asked for electric cars only, so a car it names without a card is electric."""
    return "electric" in (_attr(page, "filter-fuel-type") or [])


def _has_next(page: str) -> bool:
    return "rel='next'" in page or 'rel="next"' in page


def slim(card: str) -> str:
    """A card cut down to what the parser reads: no score dialog or ad forms after it, one image, no icons.
    Only the size depends on these cuts; a card they miss is kept whole."""
    card = card.split("<div class='modal-dialog-container'", 1)[0]
    card = re.sub(r"<svg.*?</svg>", "", card, flags=re.S)
    first = [True]

    def first_img(m: re.Match) -> str:
        keep, first[0] = first[0], False
        return m.group(0) if keep else ""

    card = re.sub(r"<img[^>]*>", first_img, card)
    return re.sub(r"\n\s*\n+", "\n", card).strip()


def _blocks(page: str) -> Iterator[tuple[str, str]]:
    """(deal id, card markup) for every full card on a page."""
    for m in CARD_RE.finditer(page):
        link = re.search(r"href='https://quotes\.carwow\.co\.uk/deals/([0-9a-f]+)'", m.group(1))
        if link:
            yield link.group(1), m.group(0)


def _segment(deal_id: str, seen: str | None, card: str) -> str:
    return f"<!-- carwow-used card {deal_id}{' seen ' + seen if seen else ''} -->\n{card}\n</turbo-frame>"


def _segments(body: str) -> Iterator[tuple[str, str | None, str | None]]:
    """(text, card id, seen) for each part of a combined body: a results page has no card id; a card fetched
    tonight has no seen date (it is the body's own date), a card carried from an earlier night has one."""
    if not body.startswith(V2):
        for seg in body.split(PAGE_BREAK):
            yield seg, None, None
        return
    for seg in body[len(V2):].split(PAGE_BREAK):
        m = SEGMENT_RE.match(seg)
        yield (seg, m.group(1), m.group(2)) if m else (seg, None, None)


# -- what earlier nights fetched (the raw store), and tonight's share of cards


def _state(ctx: Context) -> dict:
    """This run's view of the raw store, read once: the latest stored body per model, every stored deal card,
    and the run's own bookkeeping (refused, deadline)."""
    st = ctx.extras.get("_carwow_used")
    if st is not None:
        return st
    store = ctx.extras.get("raw_store")
    st = {"store": store, "main": {}, "cards": {}, "card_fetches": [], "last": {}, "stopped": False, "deadline": None}
    if store is not None:
        for e in store.entries():   # oldest first, so a later fetch replaces an earlier one
            if e.get("source") != NAME or e.get("origin", "live") != "live":
                continue
            url = e.get("url") or ""
            if e.get("role") == "part":
                if url.startswith(CARD + "?"):
                    st["card_fetches"].append(e)
                    deal_id = (parse_qs(urlparse(url).query).get("id") or [""])[0]
                    if e.get("status") == 200 and e.get("sha256") and deal_id:
                        st["cards"].setdefault(e["target"], {})[deal_id] = (e["fetched_at"], e["sha256"])
            elif e.get("status") == 200 and e.get("sha256"):
                st["main"][e["target"]] = (e["fetched_at"], e["sha256"])
    ctx.extras["_carwow_used"] = st
    return st


def _last(st: dict, ident: str) -> dict:
    """What the store knows of a model: the cars its latest body named ('listed', None when there is no body) and
    every card it holds, deal id -> [seen at, slim card or None until loaded, stored deal-card sha or None]."""
    if ident in st["last"]:
        return st["last"][ident]
    out = {"listed": None, "cards": {}}
    store = st["store"]
    if store is not None and ident in st["main"]:
        at, sha = st["main"][ident]
        try:
            body = store.get(sha).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - a body that will not read costs only its carried cards
            print(f"  carwow_used {ident}: stored body {sha[:12]} unreadable ({e})", file=sys.stderr, flush=True)
            body = None
        if body is not None:
            out["listed"] = set()
            for seg, deal_id, seen in _segments(body):
                if deal_id is None:
                    out["listed"].update(page_ids(seg))
                for i, card in _blocks(seg):
                    if deal_id is None or i == deal_id:
                        out["cards"][i] = [seen or at, slim(card), None]
            if not out["listed"] and not body.startswith(V2):
                out["listed"] = None   # the old fetch kept no page when the first had no ad on it: unknown, not empty
    for i, (at, sha) in st["cards"].get(ident, {}).items():
        if i not in out["cards"] or out["cards"][i][0] < at:
            out["cards"][i] = [at, None, sha]
    st["last"][ident] = out
    return out


def _card_from(body: bytes, deal_id: str) -> str | None:
    for i, card in _blocks(body.decode("utf-8", "replace")):
        if i == deal_id:
            return slim(card)
    return None


def _stored_card(st: dict, rec: list, deal_id: str) -> str | None:
    if rec[1] is None and rec[2] and st["store"] is not None:
        try:
            rec[1] = _card_from(st["store"].get(rec[2]), deal_id)
        except Exception:  # noqa: BLE001
            rec[2] = None
    return rec[1]


def _share(needs: dict[str, int], budget: int) -> dict[str, int]:
    """`budget` split over `needs` as evenly as they allow: no model gets more than it needs, and what a small
    one does not use goes to the others. Deterministic (models in name order)."""
    out = {k: 0 for k in needs}
    active = sorted(k for k, n in needs.items() if n > 0)
    while budget > 0 and active:
        each = max(1, budget // len(active))
        for k in list(active):
            give = min(each, needs[k] - out[k], budget)
            out[k] += give
            budget -= give
            if out[k] >= needs[k]:
                active.remove(k)
            if budget <= 0:
                break
    return out


class _CardFetches:
    """The stored deal-card fetches dressed as top-level entries, so politeness.allowance reads their refusals
    (it skips parts, and every card is a part)."""

    def __init__(self, entries: list[dict]):
        self._entries = entries

    def entries(self) -> Iterator[dict]:
        for e in self._entries:
            yield {**e, "role": None}


def _refresh_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=CARD_REFRESH_DAYS)).isoformat(timespec="seconds")


def _due(ids, known: dict, cutoff: str) -> list[str]:
    """The cars among `ids` whose card is missing or older than `cutoff` (an ISO time)."""
    return [i for i in ids if i not in known or known[i][0] < cutoff]


def _quotas(ctx: Context, idents: list[str]) -> dict[str, int]:
    """Tonight's cards per model, sharing CARD_BUDGET: first the cars each model's last fetch named that have
    never had a card, then the ones whose card is oldest. politeness.allowance cuts the whole night's number
    after refusals, from the results pages' answers and the cards' alike."""
    from pipeline.providers.politeness import allowance, note

    st = _state(ctx)
    new, old = {}, {}
    for ident in idents:
        last = _last(st, ident)
        listed = last["listed"]
        if listed is None:
            new[ident], old[ident] = UNSEEN_GUESS, 0
        else:
            new[ident] = len(listed - set(last["cards"]))
            old[ident] = len(listed) - new[ident]
    tonight = min(allowance(st["store"], HOST, CARD_BUDGET), allowance(_CardFetches(st["card_fetches"]), HOST, CARD_BUDGET))
    note(ctx, HOST, tonight, CARD_BUDGET)
    if tonight == 0:
        print("  carwow_used: Carwow refused on recent nights; no deal cards tonight", flush=True)
    first = _share(new, tonight)
    then = _share(old, tonight - sum(first.values()))
    return {k: first[k] + then[k] for k in new}


# -- fetch


def fetch(target: Target, ctx: Context) -> Fetched:
    """The model's results pages, then the deal cards they show only as placeholders, joined into one body
    (each response also kept as it came). Carwow returns the cars in a different order on every request, so
    the paging goes on until every car the page states has been named, or two pages in a row name nothing
    new; past the last page it starts again from the first."""
    make, model = target.metadata["make"], target.metadata["model"]
    ident = target.identifier
    st = _state(ctx)
    pages: list[str] = []
    parts: list[Fetched] = []
    named: dict[str, None] = {}
    stale, p = 0, 1
    for _ in range(MAX_PAGES):
        try:
            f = fetch_url(results_url(make, model, p), ctx, headers={"Turbo-Frame": FRAME})
        except FetchError as e:
            e.parts = tuple(parts)
            raise
        parts.append(f)
        page = f.body.decode("utf-8", "replace")
        pages.append(page)
        ids = page_ids(page)
        if not ids:
            break
        new = [i for i in ids if i not in named]
        named.update(dict.fromkeys(new))
        stated = stated_count(page)
        stale = 0 if new else stale + 1
        if (stated is not None and len(named) >= stated) or stale >= 2:
            break
        if _has_next(page):
            p += 1
        elif stated is None or p == 1:
            break
        else:
            p = 1

    drawn = {i for page in pages for i in deal_ids(page)}
    want = [i for i in named if i not in drawn]
    known = _last(st, ident)["cards"]
    order = sorted(i for i in want if i not in known) + sorted((i for i in want if i in known), key=lambda i: (known[i][0], i))
    quota = target.metadata.get("card_quota")
    if quota is None:   # a run for one model: the cards that are new or a week old
        due = set(_due(order, known, _refresh_cutoff()))
        order = [i for i in order if i in due]
    cards: dict[str, tuple[str | None, str]] = {}
    for i in order[:quota] if quota is not None else order:
        if st["deadline"] is None:
            st["deadline"] = time.monotonic() + CARD_SECONDS
        if st["stopped"] or time.monotonic() > st["deadline"]:
            break
        try:
            c = fetch_url(card_url(i), ctx, headers={"Turbo-Frame": f"lazy_deal_card_{i}"})
        except Blocked:
            st["stopped"] = True
            break
        except FetchError as e:
            if e.status is not None:
                parts.append(Fetched(url=e.url or card_url(i), status_code=e.status, body=e.body, content_type=None))
            if e.status in REFUSED:
                st["stopped"] = True   # the rest wait for another night; the results pages still go on
                break
            continue
        parts.append(c)
        card = _card_from(c.body, i)
        if card:
            cards[i] = (None, card)
    for i in want:
        if i not in cards and i in known:
            card = _stored_card(st, known[i], i)
            if card:
                cards[i] = (known[i][0], card)
    body = V2 + PAGE_BREAK.join(pages) + "".join(PAGE_BREAK + _segment(i, seen, card) for i, (seen, card) in sorted(cards.items()))
    return Fetched(url=target.metadata["url"], status_code=200, body=body.encode("utf-8"), content_type="text/html",
                   parts=tuple(parts))


# -- parse


def _card_row(c: str, deal_id: str, link: str, make: str, model: str, url: str, observed_at: str, make_name: str) -> dict | None:
    """One full card's listing, or None for a car that is not electric (Carwow's results for a model with
    petrol versions, e.g. ford/focus, name those too unless asked for electric only)."""
    summary = re.search(r"deal-card__summary'>(.*?)</ul>", c, re.S)
    facts = [text(x) for x in re.findall(r"<li>(.*?)</li>", summary.group(1), re.S)] if summary else []
    if facts and "Electric" not in facts:
        return None
    deriv = re.search(r"deal-card__derivative'>\s*(.*?)\s*</div>", c, re.S)
    title = re.search(r"deal-card__title'>\s*(.*?)\s*</div>", c, re.S)
    price = re.search(r"deal-card__price'>\s*(.*?)\s*</div>", c, re.S)
    year = re.search(r"<li>\s*((?:19|20)\d\d)\s*</li>", c)
    miles = re.search(r"<li>\s*([\d,]+)\s*miles\s*</li>", c)
    town = re.search(r"data-deal-location-target='town'>\s*(.*?)\s*</span>", c, re.S)
    badges = [text(b) for b in re.findall(r"class='badge[^']*'>\s*(.*?)\s*</(?:div|span)>", c, re.S)]
    img = re.search(r"srcset='(https://[^\s']+)", c)
    title_t = text(title.group(1)) if title else f"{make_name} {model}"
    model_name = title_t[len(make_name):].strip() if title_t.lower().startswith(make_name.lower()) else title_t
    derivative = text(deriv.group(1)) if deriv else ""
    return {
        "listing_key": f"{SITE}:{deal_id}", "source": "Carwow used stock", "source_url": link,
        "listing_url": url, "observed_at": observed_at,
        "make": make_name, "make_slug": make, "model": model_name, "model_slug": model,
        "derivative": derivative, "price_gbp": money(price.group(1)) if price else None,
        "year": int(year.group(1)) if year else None,
        "mileage": int(number(miles.group(1)) or 0) if miles else None,
        "town": text(town.group(1)) if town else None, "badges": [b for b in badges if b],
        "image_url": img.group(1) if img else None, "detail": "card",
        "car_ref": {"source": SITE, "key": deal_id, "make": make_name, "model": model_name, "derivative": derivative,
                    "label": f"{title_t} {derivative}".strip()},
    }


def _cards(page: str, make: str, model: str, url: str, observed_at: str, make_name: str) -> dict[str, dict | None]:
    """deal id -> its card's listing (None: not electric), first card per id."""
    out: dict[str, dict | None] = {}
    for m in CARD_RE.finditer(page):
        c = m.group(1)
        link = re.search(r"href='(https://quotes\.carwow\.co\.uk/deals/([0-9a-f]+))'", c)
        if link and link.group(2) not in out:
            out[link.group(2)] = _card_row(c, link.group(2), link.group(1), make, model, url, observed_at, make_name)
    return out


def parse_page(page: str, make: str, model: str, url: str, observed_at: str, make_name: str | None = None) -> list[dict]:
    """The listings of the full cards on a page (or pages joined), electric ones with a price, in page order."""
    rows = _cards(page, make, model, url, observed_at, make_name or pretty_make(make)).values()
    return [r for r in rows if r and r["price_gbp"]]


def parse_body(body: str, make: str, model: str, url: str, observed_at: str, make_name: str | None = None) -> list[dict]:
    """Every car a combined body names. A car with a card tonight is read from it; a car whose card was carried
    from an earlier night is read from that card, with tonight's price ('stored-card', card_seen_at saying
    when its other facts were seen); a car with neither, on a page asked for electric only, yields its price
    and year ('price-year'). Rows in deal-id order."""
    if not body.startswith(V2):
        return parse_page(body, make, model, url, observed_at, make_name)
    make_name = make_name or pretty_make(make)
    named: dict[str, dict | None] = {}   # deal id -> its ecommerce entry when the page was asked for electric only
    fresh: dict[str, dict | None] = {}
    carried: dict[str, tuple[str, dict | None]] = {}
    for seg, deal_id, seen in _segments(body):
        cards = _cards(seg, make, model, url, observed_at, make_name)
        if deal_id is None:
            items = listing_items(seg) if electric_only(seg) else {}
            for i in page_ids(seg):
                if named.get(i) is None:
                    named[i] = items.get(i)
            for i, r in cards.items():
                fresh.setdefault(i, r)
        elif deal_id in cards:
            if seen:
                carried[deal_id] = (seen, cards[deal_id])
            else:
                fresh.setdefault(deal_id, cards[deal_id])
    rows: list[dict] = []
    for i in sorted(set(named) | set(fresh)):
        item = named.get(i) or {}
        if i in fresh:
            r = fresh[i]
        elif i in carried:
            seen, r = carried[i]
            if r is not None:
                r = {**r, "detail": "stored-card", "card_seen_at": seen}
                if item.get("price"):
                    r["price_gbp"] = float(item["price"])
        elif item.get("price"):
            r = {"listing_key": f"{SITE}:{i}", "source": "Carwow used stock", "source_url": f"https://{HOST}/deals/{i}",
                 "listing_url": url, "observed_at": observed_at,
                 "make": make_name, "make_slug": make, "model": item.get("model") or model, "model_slug": model,
                 "derivative": None, "price_gbp": float(item["price"]),
                 "year": int(item["year_registered"]) if item.get("year_registered") else None,
                 "mileage": None, "town": None, "badges": [], "image_url": None, "detail": "price-year", "car_ref": None}
        else:
            continue
        if r is None or not r["price_gbp"]:
            continue
        if item.get("state_of_vehicle"):
            r = {**r, "vehicle_state": item["state_of_vehicle"]}
        rows.append(r)
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_body(body.decode("utf-8", "replace"), target.metadata["make"], target.metadata["model"],
                          target.metadata["url"], observed_at_for(target), target.metadata.get("make_name")):
        yield ParsedRecord(kind="used", key=row["listing_key"], row=row)


stock = Capability(name="used-stock", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("used",))
provider = Provider(name=NAME, default_capability="used-stock", capabilities={"used-stock": stock}, live=True)
