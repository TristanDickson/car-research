"""Carwow's model deals pages: the representative PCP example's number of monthly payments,
against real pages (the Jeep Avenger's of 12 Oct 2026, the Hyundai ones of 6 Oct)."""
import unittest
from pathlib import Path

from model.deal_math import annualise, irr_monthly
from pipeline.providers.carwow_deals import parse_page, payments_in

FIX = Path(__file__).resolve().parent / "fixtures"


def example(name: str, make: str, model: str) -> dict:
    rows = parse_page((FIX / name).read_text(encoding="utf-8"), make, model, "u", "2026-10-12T12:00:00+00:00")
    return next(r for r in rows if r["finance_type"] == "pcp")


class RepresentativeExample(unittest.TestCase):
    def test_a_36_month_jeep_has_35_payments_and_then_the_final_one(self):
        r = example("carwow_jeep_avenger_deals.html", "jeep", "avenger")
        self.assertEqual((r["term_months"], r["num_payments"], r["monthly_payment"]), (36, 35, 218.0))
        # 35 payments make up the total with the deposits and the final payment (Carwow rounds the monthly up)...
        paid = r["total_payable_stated"] - r["customer_deposit"] - r["manufacturer_contribution"] - r["gfv"]
        self.assertAlmostEqual(paid / 35, 217.4, places=1)
        # ... and at that payment the stated 4.9% APR comes back.
        rate = irr_monthly([(0, r["amount_of_credit"])] + [(k, -paid / 35) for k in range(1, 36)] + [(36, -r["gfv"])])
        self.assertAlmostEqual(annualise(rate), r["apr"], delta=0.0006)

    def test_a_36_month_hyundai_has_36_payments(self):
        for name, model in (("carwow_hyundai_ioniq-5_deals.html", "ioniq-5"), ("carwow_hyundai_ioniq-3_deals.html", "ioniq-3")):
            r = example(name, "hyundai", model)
            self.assertEqual((r["term_months"], r["num_payments"]), (36, 36), name)

    def test_without_a_total_the_term_is_the_count(self):
        self.assertEqual(payments_in(36, 218.0, None, 5826.0, 5725.0, 12113.0), 36)
        self.assertIsNone(payments_in(None, 218.0, 31273.0, 5826.0, 5725.0, 12113.0))
