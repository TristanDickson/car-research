"""Carwow used stock beyond the sponsored cards: the results pages name every car (and give its price and
year), the deal-card pages fill in the rest, and a card fetched on an earlier night is carried forward.
Against pages captured on 2026-10-11: Kia EV3 and Hyundai Ioniq 5 results asked for electric only at 200 a
page, EV3 at Carwow's own 12 a page, one EV3 deal card, and a Ford Focus results page (petrol cards) from
the raw store."""
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from pipeline.providers import carwow_used as cu
from pipeline.providers.http import FetchError
from pipeline.providers.types import Context, Fetched, Target
from pipeline.raw import RawStore
from pipeline.runner import run

FIX = Path(__file__).parent / "fixtures"
T1, T2 = "2026-10-11T03:00:00+00:00", "2026-10-12T03:00:00+00:00"
EV3 = "carwow_used_kia_ev3_electric.html"
IONIQ5 = "carwow_used_hyundai_ioniq-5_electric.html"
CARD_ID = "2661f54994666fdc67fa26af1ef55292"


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def target(ident: str, **meta) -> Target:
    make, model = ident.split("/")
    return Target(ident, {"make": make, "model": model, "make_name": cu.pretty_make(make), "url": cu.cards_url(make, model), **meta})


class FakeCarwow:
    """fetch_url for the provider: every results page is `results`, the captured EV3 card answers for its id,
    every other card is gone (404). Records what was asked."""

    def __init__(self, results: str | bytes, cards: dict[str, bytes] | None = None):
        self.results = results if isinstance(results, bytes) else (FIX / results).read_bytes()
        self.cards = {CARD_ID: (FIX / "carwow_used_kia_ev3_card.html").read_bytes()} if cards is None else cards
        self.asked: list[str] = []

    def __call__(self, url, ctx, **kw):
        self.asked.append(url)
        if "/stock_cars/deal-cards?" in url:
            return Fetched(url=url, status_code=200, body=self.results, content_type="text/html")
        deal_id = url.rsplit("=", 1)[1]
        if deal_id in self.cards:
            return Fetched(url=url, status_code=200, body=self.cards[deal_id], content_type="text/html; charset=utf-8")
        raise FetchError(f"{url} -> HTTP 404", status=404, body=b"not found", url=url)

    def card_asks(self) -> list[str]:
        return [u for u in self.asked if "/deal-card?" in u]


def fetch(ident: str, fake: FakeCarwow, ctx: Context | None = None, **meta) -> tuple[Fetched, list[dict]]:
    t = target(ident, **meta)
    with mock.patch.object(cu, "fetch_url", fake):
        f = cu.fetch(t, ctx or Context(root=FIX))
    rows = cu.parse_body(f.body.decode("utf-8"), t.metadata["make"], t.metadata["model"], t.metadata["url"], T1, t.metadata["make_name"])
    return f, rows


class ResultsPages(unittest.TestCase):
    def test_a_results_page_names_every_car_with_its_price_and_year(self):
        p = page(EV3)
        ids = cu.page_ids(p)
        self.assertEqual((cu.stated_count(p), len(ids), len(set(ids))), (48, 48, 48))
        self.assertEqual(cu.deal_ids(p), [], "not one EV3 card is drawn in full: the old parser read nothing here")
        self.assertEqual(len(re.findall(r'id="lazy_deal_card_', p)), 48)
        items = cu.listing_items(p)
        self.assertEqual(set(items), set(ids))
        self.assertTrue(all(i["price"] and i["year_registered"] for i in items.values()))
        self.assertTrue(cu.electric_only(p))

    def test_ioniq_5_draws_only_its_ads_in_full(self):
        p = page(IONIQ5)
        self.assertEqual((cu.stated_count(p), len(set(cu.page_ids(p)))), (173, 173))
        self.assertEqual(len(set(cu.deal_ids(p))), 4)

    def test_carwow_s_own_page_size_names_twelve_and_is_not_asked_electric_only(self):
        p = page("carwow_used_kia_ev3_p1.html")
        self.assertEqual((cu.stated_count(p), len(cu.page_ids(p)), cu.electric_only(p)), (48, 12, False))

    def test_the_fetch_asks_for_electric_cars_two_hundred_a_page(self):
        u = cu.results_url("kia", "ev3", 2)
        for q in ("vehicle_fuel_category%5D=electric", "&vehicle_fuel_category=electric", "per_page=200", "page=2"):
            self.assertIn(q, u)
        self.assertNotIn("fuel", cu.cards_url("kia", "ev3"), "the target url (the listing page's identity in gold) is unchanged")


class DealCards(unittest.TestCase):
    def test_a_deal_card_page_reads_like_a_full_card(self):
        card = page("carwow_used_kia_ev3_card.html")
        rows = cu.parse_page(card, "kia", "ev3", "u", T1, "Kia")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["listing_key"], r["model"], r["derivative"], r["price_gbp"], r["year"], r["mileage"], r["town"], r["detail"]),
                         (f"carwow-used:{CARD_ID}", "EV3", "150kW 81.4kWh Auto GT-Line", 30480.0, 2025, 7010, "Greater Manchester", "card"))
        slim = cu._card_from(card.encode("utf-8"), CARD_ID)
        self.assertLess(len(slim), len(card) / 5)
        self.assertEqual(cu.parse_page(slim + "</turbo-frame>", "kia", "ev3", "u", T1, "Kia"), rows, "the cut-down card reads the same")

    def test_cards_that_are_not_electric_are_dropped(self):
        p = page("carwow_used_ford_focus_petrol.html")
        cards = cu._cards(p, "ford", "focus", "u", T1, "Ford")
        self.assertTrue(cards)
        self.assertTrue(all(r is None for r in cards.values()), "every full card on the page prints Petrol")
        self.assertEqual(cu.parse_page(p, "ford", "focus", "u", T1, "Ford"), [])
        # Nor does the page's ecommerce list stand in for them: the page was not asked for electric only.
        self.assertEqual(cu.parse_body(cu.V2 + p, "ford", "focus", "u", T1, "Ford"), [])


class Fetch(unittest.TestCase):
    def test_every_named_car_yields_a_listing_and_says_how_much_is_known(self):
        fake = FakeCarwow(EV3)
        f, rows = fetch("kia/ev3", fake)
        self.assertEqual(len([u for u in fake.asked if "/deal-cards?" in u]), 1, "one page names all 48 stated cars")
        self.assertEqual(len(fake.card_asks()), 48)
        self.assertEqual(len(f.parts), 1 + 48, "the results page, the card, and the 47 cards that were gone, each kept as it came")
        self.assertEqual(sorted({p.status_code for p in f.parts}), [200, 404])
        self.assertEqual(len(rows), 48)
        by = {r["listing_key"]: r for r in rows}
        full = by[f"carwow-used:{CARD_ID}"]
        self.assertEqual((full["detail"], full["derivative"], full["mileage"]), ("card", "150kW 81.4kWh Auto GT-Line", 7010))
        items = cu.listing_items(page(EV3))
        rest = [r for r in rows if r is not full]
        self.assertTrue(all(r["detail"] == "price-year" for r in rest))
        for r in rest:
            i = items[r["listing_key"].split(":")[1]]
            self.assertEqual((r["price_gbp"], r["year"], r["derivative"], r["mileage"], r["car_ref"]),
                             (float(i["price"]), i["year_registered"], None, None, None))
            self.assertEqual(r["source_url"], f"https://quotes.carwow.co.uk/deals/{r['listing_key'].split(':')[1]}")
        self.assertEqual({r["vehicle_state"] for r in rows}, {"Used", "New"})
        # The body is what parse reads, and the same responses make the same body.
        f2, rows2 = fetch("kia/ev3", FakeCarwow(EV3))
        self.assertEqual((f2.body, rows2), (f.body, rows))

    def test_ioniq_5_s_ads_are_read_from_the_page_and_not_fetched_again(self):
        fake = FakeCarwow(IONIQ5)
        f, rows = fetch("hyundai/ioniq-5", fake)
        self.assertEqual(len(rows), 173)
        self.assertEqual(len(fake.card_asks()), 169)
        self.assertEqual(sum(r["detail"] == "card" for r in rows), 4)

    def test_paging_follows_the_named_ids_not_the_ad_links(self):
        # Carwow's own 12 a page, no ad on it: the old fetch stopped at page 1. The fake answers every page
        # with the same twelve, so after two pages with nothing new the paging stops.
        fake = FakeCarwow("carwow_used_kia_ev3_p1.html", cards={})
        f, rows = fetch("kia/ev3", fake, card_quota=0)
        pages = [u for u in fake.asked if "/deal-cards?" in u]
        self.assertEqual([re.search(r"[?&]page=(\d+)", u).group(1) for u in pages], ["1", "2", "3"])
        self.assertEqual(fake.card_asks(), [])
        self.assertEqual(rows, [], "a page not asked for electric only gives no price-only listings")

    def test_a_quota_takes_the_cars_never_fetched_first_in_id_order(self):
        fake = FakeCarwow(EV3, cards={})
        f, rows = fetch("kia/ev3", fake, card_quota=5)
        self.assertEqual([u.rsplit("=", 1)[1] for u in fake.card_asks()], sorted(cu.page_ids(page(EV3)))[:5])
        self.assertEqual(len(rows), 48)
        fake = FakeCarwow(EV3, cards={})
        fetch("kia/ev3", fake, card_quota=0)
        self.assertEqual(fake.card_asks(), [])

    def test_a_refused_card_stops_the_cards_for_the_run(self):
        class Refusing(FakeCarwow):
            def __call__(self, url, ctx, **kw):
                if "/deal-card?" in url:
                    self.asked.append(url)
                    raise FetchError(f"{url} -> HTTP 429", status=429, body=b"slow down", url=url)
                return super().__call__(url, ctx, **kw)

        ctx = Context(root=FIX)
        fake = Refusing(EV3)
        f, rows = fetch("kia/ev3", fake, ctx)
        self.assertEqual(len(fake.card_asks()), 1)
        self.assertEqual([p.status_code for p in f.parts], [200, 429])
        self.assertEqual(len(rows), 48)
        fake2 = Refusing(EV3)
        fetch("hyundai/ioniq-5", fake2, ctx)
        self.assertEqual(fake2.card_asks(), [], "the next model's results are asked for, its cards are not")


class AcrossNights(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RawStore.open(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def night(self, fake: FakeCarwow, at: str):
        ctx = Context(root=FIX, extras={"raw_store": self.store})
        with mock.patch.object(cu, "fetch_url", fake), mock.patch("pipeline.runner._now", return_value=at):
            res = run(self.store, None, cu.provider, target="kia/ev3", ctx=ctx)
        self.assertEqual((res.fetches, res.errors, res.records), (1, 0, 48))
        main = [e for e in self.store.entries() if e.get("role") != "part" and e["fetched_at"] == at][-1]
        return cu.parse_body(self.store.get(main["sha256"]).decode("utf-8"), "kia", "ev3", main["metadata"]["url"], at, "Kia")

    def test_a_card_fetched_on_an_earlier_night_is_carried_with_tonight_s_price(self):
        first = {r["listing_key"]: r for r in self.night(FakeCarwow(EV3), T1)}
        self.assertEqual(first[f"carwow-used:{CARD_ID}"]["detail"], "card")
        parts = [e for e in self.store.entries() if e.get("role") == "part"]
        self.assertEqual(len(parts), 49)
        # The next night the card is gone (404) and the car's price has dropped on the results page.
        body = re.sub(r'(&quot;item_id&quot;:&quot;%s&quot;.*?&quot;price&quot;:)30480\.0' % CARD_ID, r"\g<1>29990.0",
                      page(EV3), count=1, flags=re.S).encode("utf-8")
        self.assertNotEqual(body, (FIX / EV3).read_bytes())
        second = {r["listing_key"]: r for r in self.night(FakeCarwow(body, cards={}), T2)}
        r = second[f"carwow-used:{CARD_ID}"]
        self.assertEqual((r["detail"], r["card_seen_at"], r["derivative"], r["mileage"], r["price_gbp"]),
                         ("stored-card", T1, "150kW 81.4kWh Auto GT-Line", 7010, 29990.0))
        self.assertTrue(r["car_ref"])
        self.assertEqual(sum(x["detail"] == "price-year" for x in second.values()), 47)


class Shares(unittest.TestCase):
    def test_the_budget_is_split_as_evenly_as_the_needs_allow(self):
        self.assertEqual(cu._share({"a": 1, "b": 10, "c": 3}, 8), {"a": 1, "b": 4, "c": 3})
        self.assertEqual(cu._share({"a": 1, "b": 2}, 10), {"a": 1, "b": 2})
        self.assertEqual(cu._share({"a": 5, "b": 5}, 0), {"a": 0, "b": 0})

    def test_the_household_s_models_get_every_card_and_the_rest_a_share(self):
        q = cu._quotas(Context(root=FIX), ["kia/ev3", "hyundai/ioniq-5", "tesla/model-3", "mg/mg-4"])
        self.assertEqual(q, {"tesla/model-3": cu.UNSEEN_GUESS, "mg/mg-4": cu.UNSEEN_GUESS},
                         "no store: a model never fetched sets aside one page's worth; the household's are not capped")

    def test_a_card_refused_tonight_rests_the_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            store.save(source="carwow_used", capability="used-stock", target="kia/ev3", metadata={"part": 2, "of": 2},
                       url=cu.card_url(CARD_ID), fetched_at=now, status=429, body=b"slow down", role="part")
            q = cu._quotas(Context(root=FIX, extras={"raw_store": store}), ["kia/ev3", "tesla/model-3"])
        self.assertEqual(q, {"kia/ev3": 0, "tesla/model-3": 0})


if __name__ == "__main__":
    unittest.main()
