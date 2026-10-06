"""The Carwow paste parser against the four real pages from the transcript."""
import unittest
from pathlib import Path

from pipeline.db import ROOT
from pipeline.providers.carwow_paste import normalise_trim_key, parse_page

PASTES = ROOT / "data" / "pastes" / "carwow"


def load(deal_id: str) -> dict:
    return parse_page((PASTES / f"2026-10-05_{deal_id}.txt").read_text(encoding="utf-8"))


class CarwowPasteParser(unittest.TestCase):
    def test_ioniq3_ultimate_ev_pack(self):
        r = load("ccbac930e8c40084fe1590a6e91466a1")
        self.assertEqual(r["offer_key"], "carwow:deal:ccbac930e8c40084fe1590a6e91466a1")
        self.assertEqual(r["observed_at"], "2026-10-05T15:26:50Z")
        self.assertEqual(r["dealer"], "Richmond Hyundai Guildford")
        self.assertEqual(r["car_ref"], {"source": "carwow", "key": "hyundai|ioniq 3|99kw 61kwh auto ultimate ev pack",
                                        "label": "Hyundai Ioniq 3 99kW 61kWh Auto Ultimate EV Pack"})
        self.assertEqual(r["finance_type"], "pcp")
        self.assertEqual(r["list_price"], 31195.0)
        self.assertEqual(r["vehicle_price"], 27445.0)
        self.assertEqual(r["saving_stated"], 3750.0)
        self.assertEqual(r["customer_deposit"], 0.0)
        self.assertEqual(r["manufacturer_contribution"], 0.0)
        self.assertEqual(r["amount_of_credit"], 27445.0)
        self.assertEqual(r["term_months"], 37)
        self.assertEqual(r["num_payments"], 36)
        self.assertEqual(r["monthly_payment"], 526.07)
        self.assertAlmostEqual(r["apr"], 0.089)
        self.assertAlmostEqual(r["fixed_rate_pa"], 0.0458)
        self.assertEqual(r["gfv"], 14039.28)
        self.assertEqual(r["total_payable_stated"], 32977.80)
        self.assertEqual(r["cost_of_credit_stated"], 5532.80)
        self.assertEqual(r["annual_mileage"], 6000)
        self.assertEqual(r["excess_mileage_ppm"], 9.0)
        self.assertEqual(r["location"], "Surrey")
        self.assertEqual(r["car_facts"]["seats"], 5)
        self.assertEqual(r["car_facts"]["boot_l"], 441.0)
        self.assertEqual(r["car_facts"]["wltp_range_mi"], 308.0)

    def test_kona_ultimate_with_contribution(self):
        r = load("aea9f090b32568c0f0326d4ef6cf6299")
        self.assertEqual(r["car_ref"]["key"], "hyundai|kona electric|160kw 65kwh auto ultimate")
        self.assertEqual(r["vehicle_price"], 33549.60)
        self.assertEqual(r["manufacturer_contribution"], 1750.0)
        self.assertEqual(r["amount_of_credit"], 31799.60)
        self.assertEqual(r["monthly_payment"], 546.64)
        self.assertAlmostEqual(r["apr"], 0.029)
        self.assertEqual(r["gfv"], 14157.65)
        self.assertEqual(r["num_payments"], 36)
        self.assertEqual(r["car_facts"]["insurance_group"], "33D")
        self.assertEqual(r["car_facts"]["efficiency_mi_kwh"], 3.7)

    def test_inster_reconciles_35_to_36_payments(self):
        r = load("c1d1cb71b766f5eee32cd608b778b11f")
        self.assertEqual(r["car_ref"]["key"], "hyundai|inster|85kw 49kwh auto 02")
        self.assertEqual(r["num_payments_stated"], 35)
        self.assertEqual(r["num_payments"], 36)
        self.assertIn("36 reconciles", r["notes"])
        self.assertEqual(r["manufacturer_contribution"], 3000.0)
        self.assertEqual(r["car_facts"]["seats"], 4)

    def test_ioniq5_space_in_kwh_normalises(self):
        r = load("74386145a70f0465c61e28b78b7afc43")
        self.assertEqual(r["car_ref"]["key"], "hyundai|ioniq 5|168kw 84kwh auto premium")
        self.assertEqual(r["monthly_payment"], 651.89)
        self.assertEqual(r["gfv"], 17528.97)
        self.assertEqual(r["num_payments"], 36)
        self.assertEqual(r["car_facts"]["insurance_group"], "38E")

    def test_normalise_trim_key(self):
        self.assertEqual(normalise_trim_key("Hyundai", "Ioniq 5", "168kW 84 kWh  Auto Premium"),
                         "hyundai|ioniq 5|168kw 84kwh auto premium")

    def test_header_required(self):
        with self.assertRaises(ValueError):
            parse_page("Skip to main content\nMy cars\nHyundai Ioniq 3\nDealer\nDeal ID: " + "a" * 32)


if __name__ == "__main__":
    unittest.main()
