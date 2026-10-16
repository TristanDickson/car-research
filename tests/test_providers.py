"""Live providers parsed against saved pages in tests/fixtures (no network).

Each fixture is a real page captured on 2026-10-06; the asserted figures were
read off the page by eye, so a parser that drifts fails here rather than
silently writing nonsense into gold.
"""
import json
import unittest
from pathlib import Path

from pipeline.providers import carwow_deals, hyundai_offers, leaseloco, ncd, rrg
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from tests.helpers import Raws

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-06T12:00:00+00:00"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class CarwowDeals(unittest.TestCase):
    def test_hyundai_page_cash_prices_and_rep_example(self):
        rows = carwow_deals.parse_page(fixture("carwow_hyundai_ioniq-3_deals.html"), "hyundai", "ioniq-3", "u", T)
        by_key = {r["offer_key"]: r for r in rows}
        self.assertEqual(len(rows), 21)  # 20 derivatives + 1 representative example
        ult = by_key["carwow:cash:111015"]
        self.assertEqual({k: v for k, v in ult["car_ref"].items() if k != "stub"},
                         {"source": "carwow-cap", "key": "111015", "label": "Hyundai Ioniq 3 99kW 61kWh Auto · Ultimate · RRP £31,195"})
        # Enough to generate a car for a derivative nobody curates (see autocars.from_stub).
        self.assertEqual(ult["car_ref"]["stub"], {"cap_id": "111015", "make": "Hyundai", "make_slug": "hyundai", "model": "Ioniq 3",
                                                  "model_slug": "ioniq-3", "trim": "Ultimate", "engine": "99kW 61kWh Auto",
                                                  "rrp": 31195.0, "version_date": "2026-10-01"})
        self.assertEqual((ult["list_price"], ult["vehicle_price"], ult["saving_stated"]), (31195.0, 25620.0, 5575.0))
        self.assertEqual(ult["finance_type"], "cash")
        self.assertEqual(ult["status"], "lead")
        self.assertEqual(ult["observed_at"], T)
        # Hyundai pages carry an indicative "Monthly from" on the footnote's basis.
        adv = by_key["carwow:cash:110663"]
        self.assertEqual(adv["monthly_from_indicative"], 189.0)
        self.assertIn("8.9%", adv["indicative_basis"])
        rep = by_key["carwow:rep:110663"]
        self.assertEqual(rep["status"], "illustrative")
        self.assertEqual(rep["finance_type"], "pcp")
        self.assertEqual((rep["customer_deposit"], rep["monthly_payment"], rep["gfv"]), (3441.0, 189.0, 10137.64))
        self.assertAlmostEqual(rep["apr"], 0.089)
        self.assertEqual((rep["term_months"], rep["num_payments"], rep["annual_mileage"]), (36, 36, 8000))
        self.assertEqual(rep["total_payable_stated"], 20372.0)

    def test_kia_page_has_separate_pcp_finance_price(self):
        rows = carwow_deals.parse_page(fixture("carwow_kia_ev3_deals.html"), "kia", "ev3", "u", T)
        by_key = {r["offer_key"]: r for r in rows}
        gts = by_key["carwow:cash:106394"]
        self.assertEqual((gts["list_price"], gts["vehicle_price"], gts["pcp_finance_price"]), (43055.0, 40099.0, 37100.0))
        self.assertEqual(gts["pcp_finance_price_delta"], -2999.0)
        # The card's footnotes: what its PCP price assumes.
        air = by_key["carwow:cash:106391"]
        self.assertEqual((air["finance_deposit_contribution"], air["finance_apr"]), (2000.0, 0.039))
        self.assertNotIn("monthly_from_indicative", gts)
        self.assertEqual(sorted(k for k in by_key if k.startswith("carwow:cash:")),
                         ["carwow:cash:106391", "carwow:cash:106392", "carwow:cash:106393", "carwow:cash:106394", "carwow:cash:110993"])

    def test_rep_example_goes_to_the_twin_whose_monthly_it_is(self):
        """Two Ioniq 5 Advance 63 kWh derivatives share the £40,695 RRP; the example's £301 a month
        is the 'Monthly from' on 111632's card, not 105814's (£325)."""
        rows = carwow_deals.parse_page(fixture("carwow_hyundai_ioniq-5_deals.html"), "hyundai", "ioniq-5", "u", T)
        rep = [r for r in rows if r["finance_type"] == "pcp"]
        self.assertEqual([(r["offer_key"], r["monthly_payment"]) for r in rep], [("carwow:rep:111632", 301.0)])

    def test_discover_targets(self):
        ts = list(carwow_deals.discover(Target("all"), Context(root=FIX)))
        self.assertEqual(len(ts), len(carwow_deals.MODELS))
        self.assertEqual(ts[0].metadata["url"], "https://www.carwow.co.uk/hyundai/ioniq-3/deals")
        self.assertEqual([t.identifier for t in carwow_deals.discover(Target("kia/ev3"), Context(root=FIX))], ["kia/ev3"])


class NewCarDiscount(unittest.TestCase):
    def test_listing(self):
        rows = ncd.parse_page(fixture("ncd_hyundai_ioniq-3_listing.html"), "hyundai", "u", T)
        self.assertEqual(len(rows), 20)
        by_trim = {r["car_ref"]["key"]: r for r in rows}
        prem = by_trim["hyundai|ioniq 3 electric hatchback|99kw premium 61kwh 5dr auto [ev pack]"]
        self.assertEqual(prem["vehicle_price"], 28649.0)
        self.assertEqual(prem["finance_type"], "cash")
        self.assertEqual(prem["offer_key"],
                         "ncd:/car/hyundai/ioniq-3-electric-hatchback/hatchback/electric/automatic/99kw-premium-61kwh-5dr-auto-ev-pack/26/")
        self.assertTrue(prem["source_url"].startswith("https://"))
        self.assertEqual(by_trim["hyundai|ioniq 3 electric hatchback|99kw advance 61kwh 5dr auto"]["vehicle_price"], 25700.0)
        self.assertEqual(by_trim["hyundai|ioniq 3 electric hatchback|99kw ultimate 61kwh 5dr auto [comfort/design/ev]"]["vehicle_price"], 35150.0)


class LeaseLoco(unittest.TestCase):
    def test_best_deals_ex_vat_converted_and_non_evs_dropped(self):
        rows = leaseloco.parse_page(fixture("leaseloco_hyundai_kona-electric.html"), "u", T)
        self.assertEqual(len(rows), 5)  # petrol / hybrid Konas on the same page are dropped
        first = rows[0]
        self.assertEqual(first["offer_key"], "leaseloco:44401:48:12:6000")
        self.assertEqual(first["car_ref"]["key"], "hyundai|kona electric|160kw n line s 65kwh 5dr auto")
        self.assertEqual(first["finance_type"], "pch")
        self.assertEqual(first["monthly_rental"], 287.78)  # 239.8167 ex VAT
        self.assertEqual(first["initial_rental"], 3453.36)
        self.assertEqual((first["profile"], first["num_rentals"], first["term_months"]), ("12+47", 47, 48))
        self.assertEqual((first["fees_gbp"], first["annual_mileage"]), (358.0, 6000))

    def test_the_in_stock_deal_keeps_a_key_of_its_own(self):
        """The Kona N Line's in-stock deal (£267.04) shares its vehicle and profile with the factory-order best
        deal (£269.16); it is kept beside it, not over it."""
        rows = {r["offer_key"]: r for r in leaseloco.parse_page(fixture("leaseloco_hyundai_kona-electric_2026-10-11.html"), "u", T)}
        stock, best = rows["leaseloco:44399:48:12:6000:in-stock"], rows["leaseloco:44399:48:12:6000"]
        self.assertEqual((stock["monthly_rental"], stock["stock_status"], stock["source"]), (267.04, 1, "LeaseLoco in-stock personal lease"))
        self.assertEqual((best["monthly_rental"], best["in_stock_list"]), (269.16, False))

    def test_missing_next_data_raises(self):
        with self.assertRaises(ValueError):
            leaseloco.parse_page("<html></html>", "u", T)


class RRG(unittest.TestCase):
    def test_pv5_elite_example(self):
        rows = rrg.parse_page(fixture("rrg_pv5_offers.html"), "u", T)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["offer_key"], "rrg:pv5-electric-estate-120kw-elite-long-range-71kwh-5dr-auto-7-seat:pcp")
        self.assertEqual(r["car_ref"]["key"], "kia|pv5 electric estate 120kw elite long range 71kwh 5dr auto [7 seat]")
        self.assertEqual((r["list_price"], r["grant_gbp"], r["vehicle_price"]), (41975.0, 1500.0, 40475.0))
        self.assertEqual((r["customer_deposit"], r["amount_of_credit"]), (8500.0, 31975.0))
        self.assertEqual((r["term_months"], r["num_payments"], r["monthly_payment"], r["gfv"]), (37, 36, 453.47, 18652.06))
        self.assertAlmostEqual(r["apr"], 0.039)
        self.assertAlmostEqual(r["fixed_rate_pa"], 0.0201)
        self.assertEqual((r["cost_of_credit_stated"], r["total_payable_stated"]), (3001.98, 44976.98))
        self.assertEqual(r["status"], "live")


class HyundaiOffers(unittest.TestCase):
    def test_kona_pcp_offer(self):
        rows = hyundai_offers.parse_page(fixture("hyundai_offer_kona_electric.html"), "u", T)
        self.assertEqual([(r["offer_key"], r["finance_type"]) for r in rows],
                         [("hyundai:PCP_15_7FW5ZHZ7ZGG0VH", "pcp"), ("hyundai:PML_16_7FW5ZHZ7ZGG0VH", "hp")])
        hp = rows[1]
        self.assertEqual((hp["product"], hp["monthly_payment"], hp["gfv"], hp["vehicle_price"]), ("Personal Motor Loan Offer", 754.53, 0.0, 31250.0))
        r = rows[0]
        self.assertTrue(r["reconciles"])
        self.assertEqual(r["offer_key"], "hyundai:PCP_15_7FW5ZHZ7ZGG0VH")
        self.assertEqual(r["car_ref"]["source"], "hyundai-cap")
        self.assertEqual(r["car_ref"]["key"], "hykn00ade5he a 2")
        self.assertEqual((r["car_ref"]["make"], r["car_ref"]["model"], r["car_ref"]["derivative"]), ("Hyundai", "KONA Electric", "65kWh 218PS Advance"))
        self.assertEqual((r["list_price"], r["grant_gbp"], r["vehicle_price"]), (35000.0, 3750.0, 31250.0))
        self.assertEqual((r["customer_deposit"], r["manufacturer_contribution"], r["amount_of_credit"]), (3500.0, 1750.0, 26000.0))
        self.assertEqual((r["term_months"], r["num_payments"], r["monthly_payment"], r["gfv"]), (37, 36, 454.46, 11292.98))
        self.assertAlmostEqual(r["apr"], 0.029)
        self.assertAlmostEqual(r["fixed_rate_pa"], 0.0149)
        self.assertEqual((r["total_payable_stated"], r["cost_of_credit_stated"]), (32903.54, 1653.54))
        self.assertEqual((r["annual_mileage"], r["excess_mileage_ppm"]), (10000, 9.0))
        self.assertEqual((r["valid_from"], r["valid_to"]), ("2026-10-01", "2027-01-04"))
        self.assertTrue(r["heat_pump_listed"])
        self.assertTrue(r["configurator_url"].startswith("https://www.hyundai.com/uk/en/models/kona-electric/configurator.html"))

    def test_grant_in_any_discount_slot(self):
        """The Ioniq 3's £3,750 grant is in discount2Value, not discount1Value."""
        r = hyundai_offers.parse_page(fixture("hyundai_offer_all-new_ioniq_3.html"), "u", T)[0]
        self.assertEqual((r["list_price"], r["grant_gbp"], r["vehicle_price"], r["reconciles"]), (25745.0, 3750.0, 21995.0, True))
        self.assertEqual((r["car_ref"]["model"], r["car_ref"]["derivative"]), ("IONIQ 3", "61kWh 135PS FWD ADVANCE"), "'All-new' is no part of the name")

    def test_example_priced_with_paid_paint(self):
        """The Inster's OTR (£27,375) is above its cash price (£27,005) by the £370 paint in extId 'SAW-370'."""
        r = hyundai_offers.parse_page(fixture("hyundai_offer_inster.html"), "u", T)[0]
        self.assertEqual((r["list_price"], r["vehicle_price"], r["paint_code"], r["paint_gbp"], r["grant_gbp"], r["reconciles"]),
                         (27005.0, 27375.0, "SAW", 370.0, 0.0, True))


def _fixture_provider(module, name: str, files: dict[str, str]) -> Provider:
    """A copy of a live provider whose fetch reads a fixture instead of the web."""
    cap = module.provider.capability_for(None)

    def discover(target: Target, ctx: Context):
        for t in cap.discover(target, ctx):
            if t.identifier in files:
                yield t

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes(),
                       content_type="text/html")

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name=name, default_capability=c.name, capabilities={c.name: c}, live=False)


class ThroughTheBuild(unittest.TestCase):
    """Live providers' pages, kept in the raw store, go through the build."""

    def setUp(self):
        self.raws = Raws()

    def tearDown(self):
        self.raws.close()

    def test_carwow_cap_ids_resolve_to_their_derivatives(self):
        self.raws.add("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", at=T)
        conn = self.raws.build()
        auto = {r["source_key"] for r in conn.execute("SELECT source_key FROM trim_map WHERE source='carwow-cap' AND status='auto'")}
        self.assertTrue({"110664", "111014", "111015", "111021"} <= auto)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='unmapped'").fetchone()[0], 0)
        row = conn.execute("SELECT car_id, vehicle_price, status FROM offer_observations WHERE offer_key='carwow:cash:111015'").fetchone()
        self.assertEqual((row["car_id"], row["vehicle_price"], row["status"]), ("carwow-cap:111015", 25620.0, "lead"))
        self.assertEqual(conn.execute("SELECT COUNT(DISTINCT offer_key) FROM offer_observations WHERE source='carwow_deals'").fetchone()[0], 21)

    def test_a_name_nothing_matches_is_listed_unmapped(self):
        self.raws.add("rrg", "kia/pv5-passenger-7-seater", "rrg_pv5_offers.html", at=T)
        conn = self.raws.build()
        tm = conn.execute("SELECT * FROM trim_map WHERE source='rrg'").fetchone()
        self.assertEqual(tm["status"], "unmapped")
        self.assertEqual(tm["source_key"], "kia|pv5 electric estate 120kw elite long range 71kwh 5dr auto [7 seat]")
        self.assertIsNone(conn.execute("SELECT 1 FROM offer_observations WHERE source='rrg'").fetchone())

    def test_the_same_page_fetched_again_extends_its_span(self):
        self.raws.add("hyundai_offers", "kona_electric", "hyundai_offer_kona_electric.html", at=T)
        self.raws.add("hyundai_offers", "kona_electric", "hyundai_offer_kona_electric.html", at="2026-10-07T12:00:00+00:00")
        self.raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at=T)   # the derivatives
        conn = self.raws.build()
        rows = conn.execute("SELECT observed_at, confirmed_at, car_id FROM offer_observations WHERE offer_key='hyundai:PCP_15_7FW5ZHZ7ZGG0VH'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(T, "2026-10-07T12:00:00+00:00", "carwow-cap:103322")], "on the Advance, by its words")
        self.assertEqual(len(list((self.raws.store.root / "bodies").rglob("*.gz"))), 2, "an unchanged page is stored once (beside the spec page)")
        self.assertEqual(len(list(self.raws.store.entries())), 3, "and its second fetch is still recorded")


class CinchNewCars(unittest.TestCase):
    """cinch's new-car listing (captured 11 Oct 2026): a real PCP quote and a cash price per car."""

    def setUp(self):
        from pipeline.providers import cinch_new
        body = json.dumps({"pages": [json.loads(fixture("cinch_new_electric.json"))]}).encode()
        t = Target("electric", {"url": cinch_new.api_url(), "observed_at": T})
        self.rows = [r.row for r in cinch_new.parse(body, t)]

    def test_every_car_has_a_pcp_quote_and_a_cash_price(self):
        self.assertEqual(sum(r["finance_type"] == "pcp" for r in self.rows), 21)
        self.assertEqual(sum(r["finance_type"] == "cash" for r in self.rows), 21)
        surf = next(r for r in self.rows if r["finance_type"] == "pcp" and r["source_ref"] == "3428c23d-959f-4e57-aad1-1c21e6217f17")
        self.assertEqual((surf["vehicle_price"], surf["customer_deposit"], surf["monthly_payment"], surf["num_payments"], surf["term_months"]),
                         (22331.0, 1999.0, 259.01, 48, 49))
        self.assertEqual((surf["gfv"], surf["apr"], surf["amount_of_credit"], surf["annual_mileage"], surf["excess_mileage_ppm"]),
                         (8316.75, 0.019, 19668.0, 6000, 14.9))
        self.assertEqual((surf["manufacturer_contribution"], surf["contribution_implied"], surf["reconciles"]), (664.0, True, True))
        self.assertEqual(surf["car_ref"]["derivative"], "115kW Comfort 43kWh 5dr Auto")

    def test_the_inster_quote_finances_its_contribution_and_two_nissans_do_not_add_up(self):
        inster = next(r for r in self.rows if r["finance_type"] == "pcp" and r["car_ref"]["model"] == "INSTER")
        self.assertEqual(inster["manufacturer_contribution"], 3750.0)
        self.assertEqual(sorted(r["car_ref"]["model"] for r in self.rows if r.get("reconciles") is False), ["Ariya", "LEAF"])
        cash = next(r for r in self.rows if r["finance_type"] == "cash" and r["source_ref"] == inster["source_ref"])
        self.assertEqual((cash["vehicle_price"], cash["fees_gbp"]), (26584.0, 99.0))


class KiaDealers(unittest.TestCase):
    """Two dealer groups' EV3 pages (captured 11 Oct 2026): the worked PCP example each prints."""

    def rows(self, site, f):
        from pipeline.providers import kia_dealers
        return kia_dealers.parse_page(fixture(f), "u", site, T)

    def test_lloyd_s_example_with_its_own_contribution(self):
        (r,) = self.rows("lloyd", "kia_dealer_lloyd_ev3.html")
        self.assertEqual((r["car_ref"]["model"], r["car_ref"]["derivative"]), ("EV3", "GT-Line 150kW 81.4kWh Auto"))
        self.assertEqual((r["list_price"], r["grant_gbp"], r["vehicle_price"], r["customer_deposit"]), (40105.0, 1500.0, 38605.0, 4499.0))
        self.assertEqual((r["kia_contribution"], r["dealer_contribution"], r["manufacturer_contribution"]), (2000.0, 430.0, 2430.0))
        self.assertEqual((r["amount_of_credit"], r["monthly_payment"], r["num_payments"], r["term_months"]), (31676.0, 449.45, 36, 37))
        self.assertEqual((r["apr"], r["gfv"], r["annual_mileage"], r["excess_mileage_ppm"], r["reconciles"]), (0.039, 18469.34, 6000, 9.0, True))
        self.assertEqual(r["valid_to"], "2026-09-30", "the page still shows July's offer, so it shows as expired")

    def test_halliwell_jones_only_where_the_example_names_its_car(self):
        rows = self.rows("hj", "kia_dealer_hj_ev3.html")
        self.assertEqual([r["car_ref"]["label"] for r in rows], ["Kia EV3 GT-Line"], "the model page's other examples sit under the wrong headings")
        r = rows[0]
        self.assertEqual((r["vehicle_price"], r["manufacturer_contribution"], r["amount_of_credit"], r["monthly_payment"], r["valid_to"]),
                         (37955.0, 2955.0, 30001.0, 399.0, "2026-12-31"))
        self.assertTrue(r["reconciles"])

    def test_a_halliwell_jones_offer_page_is_labelled_by_its_heading(self):
        from pipeline.providers import kia_dealers
        url = "https://www.halliwelljones.co.uk/kia/offers/kia-ev3-gt-line-pcp"
        rows = kia_dealers.parse_page(fixture("kia_dealer_hj_ev3_gt-line_offer.html"), url, "hj", T)
        self.assertEqual([(r["car_ref"]["label"], r["monthly_payment"], r["customer_deposit"]) for r in rows], [("Kia EV3 GT-Line", 399.0, 4999.0)],
                         "the page's second example is a card for another offer, read from that offer's own page")
        self.assertTrue(rows[0]["banner_agrees"])

    def test_the_offer_page_s_own_example_is_kept_when_its_banner_disagrees(self):
        """The EV5 Storm page's example prints £449 a month under a '£499 p/m' banner (its own credit, APR and
        final payment imply about £499). The example is the page's own, so it is kept, with the banner beside it.
        Its mileage is printed 'Contract Mileage 18000 (6,000 per annum)'."""
        from pipeline.providers import kia_dealers
        url = "https://www.halliwelljones.co.uk/kia/offers/kia-ev5-air-pcp-"
        (r,) = kia_dealers.parse_page(fixture("kia_dealer_hj_ev5_storm_offer.html"), url, "hj", T)
        self.assertEqual((r["car_ref"]["label"], r["list_price"], r["monthly_payment"], r["banner_monthly"], r["banner_agrees"], r["annual_mileage"]),
                         ("Kia EV5 Storm", 43145.0, 449.0, 499.0, False, 6000))

    def test_lloyd_s_annual_mileage_wording(self):
        url = "https://www.lloydmotorgroup.com/Kia/Current-Offers/Kia-PV5-Passenger-Offer/618"
        from pipeline.providers import kia_dealers
        (r,) = kia_dealers.parse_page(fixture("kia_dealer_lloyd_pv5.html"), url, "lloyd", T)
        self.assertEqual((r["car_ref"]["model"], r["monthly_payment"], r["annual_mileage"]), ("PV5", 331.27, 10000))

    def test_the_index_links_only_electric_retail_offers(self):
        from pipeline.providers import kia_dealers
        page = 'href="/Kia/Current-Offers/Kia-EV3-Deals/382" href="/Kia/Current-Offers/Kia-Sportage/205" href="/Kia/Current-Offers/Kia-EV2-on-the-Motability-Scheme/631"'
        self.assertEqual(kia_dealers.offer_links(page, "lloyd"), ["https://www.lloydmotorgroup.com/Kia/Current-Offers/Kia-EV3-Deals/382"])


if __name__ == "__main__":
    unittest.main()
