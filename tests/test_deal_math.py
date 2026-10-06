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
