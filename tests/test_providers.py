"""Live providers parsed against saved pages in tests/fixtures (no network).

Each fixture is a real page captured on 2026-10-06; the asserted figures were
read off the page by eye, so a parser that drifts fails here rather than
silently writing nonsense into gold.
"""
import unittest
from pathlib import Path

from pipeline.providers import carwow_deals, hyundai_offers, leaseloco, ncd, rrg
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from tests.helpers import fresh_conn, run_all

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
        self.assertEqual(ult["car_ref"], {"source": "carwow-cap", "key": "111015",
                                          "label": "Hyundai Ioniq 3 99kW 61kWh Auto · Ultimate · RRP £31,195"})
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
        self.assertNotIn("monthly_from_indicative", gts)
        self.assertEqual(sorted(k for k in by_key if k.startswith("carwow:cash:")),
                         ["carwow:cash:106391", "carwow:cash:106392", "carwow:cash:106393", "carwow:cash:106394", "carwow:cash:110993"])

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
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["offer_key"], "hyundai:PCP_15_7FW5ZHZ7ZGG0VH")
        self.assertEqual(r["car_ref"]["source"], "hyundai-cap")
        self.assertEqual(r["car_ref"]["key"], "hykn00ade5he a 2")
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


class ThroughTheRunner(unittest.TestCase):
    """Live providers go through the same Bronze → Silver → Gold path as pastes, including trim resolution."""

    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)  # seed: cars + trim_map

    def test_carwow_cap_ids_resolve_via_seeded_trim_map(self):
        p = _fixture_provider(carwow_deals, "carwow_deals", {"hyundai/ioniq-3": "carwow_hyundai_ioniq-3_deals.html"})
        res = run(self.conn, p, ctx=Context(root=FIX))
        self.assertEqual(res.errors, 0)
        self.assertEqual(res.records, 21)
        self.assertEqual(res.unmapped, 0)
        mapped = {r["source_key"] for r in self.conn.execute("SELECT source_key FROM trim_map WHERE source='carwow-cap' AND status='mapped'")}
        self.assertTrue({"110664", "111014", "111015", "111021"} <= mapped)
        # Derivatives we don't track (e.g. the 42kWh Advance) are seeded as 'ignored', not left dangling.
        n_unmapped = self.conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='unmapped'").fetchone()[0]
        self.assertEqual(n_unmapped, 0)
        row = self.conn.execute("SELECT car_id, vehicle_price, status FROM offer_observations WHERE offer_key='carwow:cash:111015'").fetchone()
        self.assertEqual((row["car_id"], row["vehicle_price"], row["status"]), ("hyundai-ioniq3-61-ultimate-evpack", 25620.0, "lead"))

    def test_unknown_key_lands_in_trim_map_as_unmapped(self):
        p = _fixture_provider(rrg, "rrg", {"kia/pv5-passenger-7-seater": "rrg_pv5_offers.html"})
        self.conn.execute("DELETE FROM trim_map WHERE source='rrg'")
        res = run(self.conn, p, ctx=Context(root=FIX))
        self.assertEqual(res.unmapped, 1)
        tm = self.conn.execute("SELECT * FROM trim_map WHERE source='rrg'").fetchone()
        self.assertEqual(tm["status"], "unmapped")
        self.assertEqual(tm["source_key"], "kia|pv5 electric estate 120kw elite long range 71kwh 5dr auto [7 seat]")

    def test_resighting_bumps_confirmed_at_instead_of_duplicating(self):
        p = _fixture_provider(hyundai_offers, "hyundai_offers", {"kona_electric": "hyundai_offer_kona_electric.html"})
        run(self.conn, p, ctx=Context(root=FIX))
        run(self.conn, p, ctx=Context(root=FIX))
        rows = self.conn.execute("SELECT observed_at, confirmed_at FROM offer_observations WHERE offer_key='hyundai:PCP_15_7FW5ZHZ7ZGG0VH'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["confirmed_at"])
        self.assertGreaterEqual(rows[0]["confirmed_at"], rows[0]["observed_at"])


if __name__ == "__main__":
    unittest.main()
