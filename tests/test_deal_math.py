"""Regression tests: the normalisation must reproduce the real Carwow / dealer
figures captured in data/seed/deals.json (and the ChatGPT-derived estimates)."""
import json
import unittest
from pathlib import Path

from model.deal_math import compute

ROOT = Path(__file__).resolve().parents[1]


def _results():
    deals = json.loads((ROOT / "data/seed/deals.json").read_text())["deals"]
    return {r["id"]: r for r in compute(deals)}


class DealMathReproducesQuotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _results()

    def test_carwow_ioniq3_pcp(self):
        m = self.r["2026-10-05_carwow-richmond-guildford_ioniq3-61-ultimate-evpack_pcp"]
        self.assertAlmostEqual(m["apr_implied"], 0.089, delta=0.0005)
        self.assertAlmostEqual(m["paid_if_bought"], 32977.80, delta=0.01)
        self.assertAlmostEqual(m["cost_of_credit"], 5532.80, delta=0.01)
        # Same price as the cash benchmark, so the premium is exactly the interest.
        self.assertAlmostEqual(m["funding_premium_vs_cash"], 5532.80, delta=0.01)
        self.assertAlmostEqual(m["effective_rate_vs_cash"], 0.089, delta=0.0005)

    def test_carwow_kona_ultimate_pcp_vs_cash_lead(self):
        m = self.r["2026-10-05_carwow-richmond-guildford_kona-65-ultimate_pcp"]
        self.assertAlmostEqual(m["apr_implied"], 0.029, delta=0.0005)
        self.assertAlmostEqual(m["cost_of_credit"], 2037.09, delta=0.05)
        self.assertAlmostEqual(m["finance_vs_own_cash_price"], 287.09, delta=0.05)
        self.assertEqual(m["best_cash_price"], 26966)
        self.assertAlmostEqual(m["funding_premium_vs_cash"], 6870.69, delta=0.05)
        self.assertGreater(m["effective_rate_vs_cash"], 0.10)

    def test_zero_percent_deals_imply_zero(self):
        for did in (
            "2026-10-05_carwow-richmond-guildford_inster-49-02_pcp",
            "2026-10-05_carwow-richmond-guildford_ioniq5-84-premium_pcp",
        ):
            m = self.r[did]
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
        # Cost of credit excludes the deposit: 0% means £0 either way.
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
        self.assertGreater(m["vehicle_price"], 21000)
        self.assertLess(m["vehicle_price"], 23000)

    def test_campaigns_and_incomplete_deals_are_skipped_not_crashed(self):
        skipped = [r for r in self.r.values() if "skipped" in r]
        self.assertGreaterEqual(len(skipped), 8)


if __name__ == "__main__":
    unittest.main()
