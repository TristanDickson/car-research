"""Regression tests: the normalisation must reproduce the real Carwow / dealer
figures (pasted pages + seed) and the ChatGPT-derived estimates."""
import unittest

from model.deal_math import compute
from pipeline.services.snapshot import latest_offers
from tests.helpers import fresh_conn, run_all

IONIQ3 = "carwow:deal:ccbac930e8c40084fe1590a6e91466a1"
KONA = "carwow:deal:aea9f090b32568c0f0326d4ef6cf6299"
INSTER = "carwow:deal:c1d1cb71b766f5eee32cd608b778b11f"
IONIQ5 = "carwow:deal:74386145a70f0465c61e28b78b7afc43"


class DealMathReproducesQuotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = fresh_conn()
        run_all(conn)
        cls.r = {m["id"]: m for m in compute(latest_offers(conn))}

    def test_carwow_ioniq3_pcp(self):
        m = self.r[IONIQ3]
        self.assertAlmostEqual(m["apr_implied"], 0.089, delta=0.0005)
        self.assertAlmostEqual(m["paid_if_bought"], 32977.80, delta=0.01)
        self.assertAlmostEqual(m["cost_of_credit"], 5532.80, delta=0.01)
        # Same price as the cash benchmark, so the premium is exactly the interest.
        self.assertAlmostEqual(m["funding_premium_vs_cash"], 5532.80, delta=0.01)
        self.assertAlmostEqual(m["effective_rate_vs_cash"], 0.089, delta=0.0005)

    def test_carwow_kona_ultimate_pcp_vs_cash_lead(self):
        m = self.r[KONA]
        self.assertAlmostEqual(m["apr_implied"], 0.029, delta=0.0005)
        self.assertAlmostEqual(m["cost_of_credit"], 2037.09, delta=0.05)
        self.assertAlmostEqual(m["finance_vs_own_cash_price"], 287.09, delta=0.05)
        self.assertEqual(m["best_cash_price"], 26966)
        self.assertAlmostEqual(m["funding_premium_vs_cash"], 6870.69, delta=0.05)
        self.assertGreater(m["effective_rate_vs_cash"], 0.10)

    def test_zero_percent_deals_imply_zero(self):
        for did in (INSTER, IONIQ5):
            m = self.r[did]
            self.assertEqual(m["num_payments"], 36, "Carwow prints 35; 36 reconciles")
            self.assertAlmostEqual(m["apr_implied"], 0.0, delta=0.0005)
            self.assertAlmostEqual(m["cost_of_credit"], 0.0, delta=0.5)
            # Contribution makes financing cheaper than the seller's cash price.
            self.assertAlmostEqual(m["finance_vs_own_cash_price"], -3000, delta=0.5)

    def test_derived_monthlies_match_chatgpt_estimates(self):
        pv5 = self.r["2026-10-05_derived_pv5-elite-7seat_pcp-0dep"]
        self.assertIn("monthly_payment", pv5["derived_fields"])
        self.assertAlmostEqual(pv5["monthly_payment"], 699.5, delta=1.0)
        ev3 = self.r["2026-10-05_brayleys-derived_ev3-81-gtlines-hp_pcp-0dep"]
        self.assertAlmostEqual(ev3["monthly_payment"], 681, delta=1.0)
        self.assertAlmostEqual(ev3["funding_premium_vs_cash"], 7316, delta=40)
        self.assertAlmostEqual(ev3["effective_rate_vs_cash"], 0.085, delta=0.003)

    def test_deposit_only_moves_money(self):
        a = self.r["2026-09_richmond_kona-65-advance_pcp-0pct_3000dep"]
        b = self.r["2026-09_richmond_kona-65-advance_pcp-0pct_430dep"]
        self.assertAlmostEqual(a["paid_if_handed_back"], b["paid_if_handed_back"], delta=1.0)
        self.assertAlmostEqual(a["paid_if_handed_back"], 15931, delta=1.0)
        self.assertAlmostEqual(a["cost_of_credit"], 0.0, delta=0.5)

    def test_cost_of_credit_excludes_deposit_on_rrg_example(self):
        m = self.r["2026-10-05_rrg_pv5-elite-7seat_pcp-rep-example"]
        self.assertAlmostEqual(m["apr_implied"], 0.039, delta=0.0005)
        self.assertAlmostEqual(m["cost_of_credit"], 3032.78, delta=1.0)

    def test_pch_effective_monthly(self):
        m = self.r["2026-09_richmond_kona-65-advance_pch"]
        self.assertAlmostEqual(m["total_cost"], 16113, delta=0.01)
        self.assertAlmostEqual(m["effective_monthly"], 335.69, delta=0.01)

    def test_back_solved_credit_when_price_unknown(self):
        m = self.r["2026-10_hyundai-uk_ioniq3-61-advance_pcp-rep-example"]
        self.assertIn("amount_of_credit", m["derived_fields"])
        self.assertAlmostEqual(m["apr_implied"], 0.089, delta=0.0005)
        self.assertTrue(21000 < m["vehicle_price"] < 23000)

    def test_campaigns_and_incomplete_deals_are_skipped_not_crashed(self):
        self.assertGreaterEqual(sum(1 for r in self.r.values() if "skipped" in r), 8)


if __name__ == "__main__":
    unittest.main()


class TrueMonthly(unittest.TestCase):
    """Every route on one footing: discounted at the savings rate, residual credited back."""

    PCP = {"id": "p", "car_id": "c", "finance_type": "pcp", "status": "live", "list_price": 40000.0, "vehicle_price": 36000.0,
           "customer_deposit": 0.0, "manufacturer_contribution": 0.0, "apr": 0.0, "num_payments": 36, "term_months": 37,
           "gfv": 18000.0, "monthly_payment": 500.0}
    PCH = {"id": "l", "car_id": "c", "finance_type": "pch", "status": "live", "term_months": 36, "num_rentals": 35,
           "monthly_rental": 400.0, "initial_rental": 3600.0, "fees_gbp": 300.0}
    CASH = {"id": "k", "car_id": "c", "finance_type": "cash", "status": "live", "list_price": 40000.0, "vehicle_price": 34000.0}

    def test_at_zero_rate_and_gfv_residual_it_is_the_plain_arithmetic(self):
        from model.deal_math import compute
        basis = {"term_months": 37, "savings_rate_apr": 0.0, "residual_pct_of_list": 0.45, "residual_at_months": 37}
        r = {m["id"]: m for m in compute([self.PCP, self.PCH, self.CASH], basis)}
        # PCP: 36 × £500 paid, the car worth exactly the GFV at the end: no equity, so cost = payments / 37.
        self.assertEqual(r["p"]["expected_value_at_end"], 18000.0)
        self.assertAlmostEqual(r["p"]["true_monthly"], 500 * 36 / 37, places=2)
        self.assertEqual(r["p"]["true_monthly"], r["p"]["true_monthly_floor"])
        # Lease: everything paid spread over the term.
        self.assertAlmostEqual(r["l"]["true_monthly"], (3600 + 35 * 400 + 300) / 36, places=2)
        # Cash: price less the car's value at the end, spread over the standard term; floor uses the lender's GFV.
        self.assertAlmostEqual(r["k"]["true_monthly"], (34000 - 18000) / 37, places=2)
        self.assertAlmostEqual(r["k"]["true_monthly_floor"], (34000 - 18000) / 37, places=2)

    def test_savings_rate_and_equity_move_the_routes_the_right_way(self):
        from model.deal_math import compute
        basis = {"term_months": 37, "savings_rate_apr": 0.04, "residual_pct_of_list": 0.55, "residual_at_months": 36}
        r = {m["id"]: m for m in compute([self.PCP, self.PCH, self.CASH], basis)}
        self.assertGreater(r["p"]["expected_equity"], 0, "a 55% residual beats an 45% GFV: there is equity")
        self.assertLess(r["p"]["true_monthly"], r["p"]["true_monthly_floor"], "expected equity makes the PCP cheaper than its floor")
        # Paying £34k up front forgoes 4% a year on it: cash gets dearer than the zero-rate arithmetic says.
        self.assertGreater(r["k"]["true_monthly"], (34000 - r["k"]["expected_value_at_end"]) / 37)
        # A lease has nothing coming back, so its true monthly stays within a few pounds of the plain
        # average: the discounting and the annuity spread nearly cancel.
        self.assertAlmostEqual(r["l"]["true_monthly"], r["l"]["effective_monthly"], delta=0.03 * r["l"]["effective_monthly"])
        self.assertEqual(r["l"]["horizon_months"], 36)
