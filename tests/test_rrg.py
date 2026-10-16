"""RRG Kia's offers (pages captured 11 Oct 2026): the index, and the representative example on each
electric offer page, PCP and personal lease. The figures asserted were read off the pages."""
import json
import unittest
from pathlib import Path
from unittest import mock

from pipeline.providers import rrg
from pipeline.providers.types import Context, Fetched, Target
from tests.helpers import Raws

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-11T03:00:00+00:00"
PV5_KEY = "kia|pv5 electric estate 120kw elite long range 71kwh 5dr auto [7 seat]"
ELECTRIC = {"ev2-offer", "ev4", "ev5-storm", "ev6", "ev9", "pv5-passenger-7-seater", "pv5-passenger-pcp",
            "pv5-passenger-long-range-plus-7-seater", "pv5-passenger-with-met-long-range-plus", "pv5-passenger-elite-7-seater-pch",
            "pv5-passenger-long-range-elite-5-seater", "pv5-passenger-long-range-160-plus",
            "pv5-passenger-standard-range-essential-5-seater"}
PAGES = {"ev6": "rrg_ev6.html", "ev2-offer": "rrg_ev2.html", "pv5-passenger-7-seater": "rrg_pv5_offers.html",
         "pv5-passenger-elite-7-seater-pch": "rrg_pv5_elite_7_pch.html", "pv5-passenger-long-range-plus-7-seater": "rrg_pv5_plus_7.html"}


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def one(name: str, page: str) -> dict:
    rows = rrg.parse_page(fixture(name), rrg.page_url(page), T)
    assert len(rows) == 1, rows
    return rows[0]


def fake_fetch(asked: list[str]):
    """fetch_url serving the captured pages; an offer page without a fixture gets the index, as RRG
    answers for an ended offer."""
    def fetch_url(url: str, ctx, **kw) -> Fetched:
        asked.append(url)
        if url == rrg.INDEX:
            name = "rrg_index_p1.html"
        elif url == rrg.INDEX + "?page=2&per_page=10":
            name = "rrg_index_p2.html"
        else:
            name = PAGES.get(url[len(rrg.INDEX):].strip("/"), "rrg_index_p1.html")
        return Fetched(url=url, status_code=200, body=(FIX / name).read_bytes(), content_type="text/html")
    return fetch_url


def combined_body() -> bytes:
    pages = [{"url": rrg.page_url(p), "html": fixture(n)} for p, n in PAGES.items()]
    return json.dumps({"pages": pages}, ensure_ascii=False).encode("utf-8")


class Discovery(unittest.TestCase):
    def test_all_is_the_index_and_a_named_page_is_that_page(self):
        ctx = Context(root=Path("."))
        self.assertEqual([(t.identifier, t.metadata) for t in rrg.discover(Target("all"), ctx)],
                         [("kia/offers", {"url": rrg.INDEX, "kind": "index"})])
        self.assertEqual([t.metadata["url"] for t in rrg.discover(Target("kia/pv5-passenger-7-seater"), ctx)],
                         ["https://www.rrg-group.com/kia/new-car-offers/pv5-passenger-7-seater/"])

    def test_the_backfill_reads_each_known_page(self):
        urls = [t.metadata["url"] for t in rrg.discover_known(Target("all"), Context(root=Path(".")))]
        self.assertIn(rrg.page_url("pv5-passenger-7-seater"), urls)
        self.assertIn(rrg.page_url("ev3"), urls)
        self.assertTrue(ELECTRIC <= {u[len(rrg.INDEX):].strip("/") for u in urls})

    def test_the_index_lists_nineteen_offers_over_two_pages(self):
        p1, p2 = fixture("rrg_index_p1.html"), fixture("rrg_index_p2.html")
        self.assertEqual(rrg.index_pages(p1), [rrg.INDEX + "?page=2&per_page=10"])
        links = rrg.offer_links(p1) + rrg.offer_links(p2)
        self.assertEqual(len(links), 19)
        self.assertEqual({p for p, electric in links if electric}, ELECTRIC)
        self.assertNotIn("ev2-39percent-apr-representative", {p for p, _ in links}, "the carousel's ended offer")

    def test_fetch_reads_every_index_page_then_every_electric_offer_page(self):
        asked: list[str] = []
        with mock.patch.object(rrg, "fetch_url", fake_fetch(asked)):
            f = rrg.fetch(Target("kia/offers", {"url": rrg.INDEX, "kind": "index"}), Context(root=Path(".")))
        self.assertEqual(asked[:2], [rrg.INDEX, rrg.INDEX + "?page=2&per_page=10"])
        self.assertEqual({u[len(rrg.INDEX):].strip("/") for u in asked[2:]}, ELECTRIC)
        self.assertEqual(len(asked), 15)
        self.assertEqual([p.url for p in f.parts], asked, "each response kept as it came")
        doc = json.loads(f.body)
        self.assertEqual((doc["offers_available"], len(doc["listed"]), len(doc["pages"])), (19, 19, 13))
        keys = {r.key for r in rrg.parse(f.body, Target("kia/offers", {"url": rrg.INDEX, "observed_at": T}))}
        self.assertEqual(keys, {"rrg:ev6:pcp", "rrg:ev2-offer:pcp", "rrg:pv5-electric-estate-120kw-elite-long-range-71kwh-5dr-auto-7-seat:pcp",
                                "rrg:pv5-passenger-elite-7-seater-pch:pch", "rrg:pv5-passenger-long-range-plus-7-seater:pcp"})


class Examples(unittest.TestCase):
    def test_ev6_pcp(self):
        r = one("rrg_ev6.html", "ev6")
        self.assertEqual(r["offer_key"], "rrg:ev6:pcp")
        self.assertEqual(r["car_ref"], {"source": "rrg", "key": "kia|ev6 'air' 84.0kwh lithium-ion rwd ev automatic",
                                        "label": "Kia EV6 'Air' 84.0kWh lithium-ion RWD EV Automatic", "make": "Kia", "model": "EV6",
                                        "derivative": "'Air' 84.0kWh lithium-ion RWD EV Automatic", "rrp": 52835.0})
        self.assertEqual(r["example_model"], "Kia EV6 Air' 84.0kWh 225bhp RWD Automatic")
        self.assertEqual((r["num_payments"], r["monthly_payment"], r["term_months"]), (36, 600.84, 37))
        self.assertEqual((r["customer_deposit"], r["manufacturer_contribution"], r["grant_gbp"]), (12500.0, 1500.0, 0.0))
        self.assertEqual((r["list_price"], r["vehicle_price"], r["amount_of_credit"]), (52835.0, 52835.0, 38835.0))
        self.assertEqual((r["cost_of_credit_stated"], r["gfv"], r["total_payable_stated"]), (3535.63, 20740.39, 56370.63))
        self.assertEqual((r["apr"], r["fixed_rate_pa"]), (0.039, 0.0201))
        self.assertEqual((r["annual_mileage"], r["excess_mileage_ppm"]), (6000, 9.0))
        self.assertEqual((r["valid_from"], r["valid_to"]), ("2026-10-01", "2026-12-15"))
        self.assertTrue(r["reconciles"])
        self.assertEqual((r["finance_type"], r["status"]), ("pcp", "live"))

    def test_ev2_grant_and_dates_in_words(self):
        r = one("rrg_ev2.html", "ev2-offer")
        self.assertEqual((r["car_ref"]["key"], r["car_ref"]["model"]), ("kia|ev2", "EV2"))
        self.assertEqual((r["list_price"], r["grant_gbp"], r["vehicle_price"]), (36995.0, 3750.0, 33245.0))
        self.assertEqual((r["customer_deposit"], r["manufacturer_contribution"], r["amount_of_credit"]), (5900.0, 0.0, 27345.0))
        self.assertEqual((r["monthly_payment"], r["gfv"]), (399.2, 15516.12))
        self.assertEqual((r["valid_from"], r["valid_to"]), ("2026-10-01", "2026-10-15"), "the offer's own dates, not the terms copied below")
        self.assertTrue(r["reconciles"])

    def test_pv5_keeps_its_key_whatever_url_it_is_read_under(self):
        r = one("rrg_pv5_offers.html", "pv5-passenger-7-seater")
        self.assertEqual(r["offer_key"], "rrg:pv5-electric-estate-120kw-elite-long-range-71kwh-5dr-auto-7-seat:pcp")
        self.assertEqual(r["car_ref"]["key"], PV5_KEY)
        self.assertEqual(r["offer_key"], rrg.parse_page(fixture("rrg_pv5_offers.html"), "u", T)[0]["offer_key"])
        self.assertTrue(r["reconciles"])
        self.assertNotIn("name_conflict", r)

    def test_personal_lease(self):
        r = one("rrg_pv5_elite_7_pch.html", "pv5-passenger-elite-7-seater-pch")
        self.assertEqual((r["offer_key"], r["finance_type"]), ("rrg:pv5-passenger-elite-7-seater-pch:pch", "pch"))
        self.assertEqual(r["car_ref"]["key"], PV5_KEY, "heading and derivative agree: the hand mapping applies")
        self.assertEqual((r["initial_rental"], r["monthly_rental"], r["num_rentals"]), (5630.4, 469.2, 47))
        self.assertEqual((r["term_months"], r["profile"], r["annual_mileage"]), (48, "12+47", None))
        self.assertEqual((r["valid_from"], r["valid_to"]), ("2026-10-01", "2026-12-15"))
        self.assertNotIn("monthly_payment", r)

    def test_a_copied_derivative_line_gives_way_to_the_heading(self):
        r = one("rrg_pv5_plus_7.html", "pv5-passenger-long-range-plus-7-seater")
        self.assertEqual(r["offer_key"], "rrg:pv5-passenger-long-range-plus-7-seater:pcp")
        self.assertEqual(r["name_conflict"]["derivative_printed"], "PV5 Electric Estate 120Kw Elite Long Range 71Kwh 5Dr Auto [7 Seat]")
        self.assertEqual(r["car_ref"]["key"], "kia|pv5 passenger long range plus 7 seater")
        self.assertEqual((r["list_price"], r["monthly_payment"], r["gfv"]), (40265.0, 427.97, 17702.4))
        self.assertTrue(r["reconciles"])

    def test_an_ended_offer_redirected_to_the_index_yields_nothing(self):
        self.assertEqual(rrg.parse_page(fixture("rrg_index_p1.html"), rrg.page_url("ev3"), T), [])


class ThroughTheBuild(unittest.TestCase):
    def test_combined_fetch_builds_and_each_pv5_row_lands_on_its_own_trim(self):
        with Raws() as raws:
            raws.add("rrg", "kia/offers", body=combined_body(), at=T)
            raws.add("carwow_specs", "kia/pv5-passenger", "carwow_kia_pv5-passenger_specifications.html", at=T)   # the derivatives
            conn = raws.build()
            cars = {r["offer_key"]: r["car_id"] for r in
                    conn.execute("SELECT offer_key, car_id FROM offer_observations WHERE source='rrg'")}
        elite = "carwow-cap:110972"   # Elite · 120kW Long Range 71kWh Auto
        self.assertEqual(cars.get("rrg:pv5-electric-estate-120kw-elite-long-range-71kwh-5dr-auto-7-seat:pcp"), elite)
        self.assertEqual(cars.get("rrg:pv5-passenger-elite-7-seater-pch:pch"), elite)
        self.assertEqual(cars.get("rrg:pv5-passenger-long-range-plus-7-seater:pcp"), "carwow-cap:108179", "the Plus, not the Elite")


if __name__ == "__main__":
    unittest.main()
