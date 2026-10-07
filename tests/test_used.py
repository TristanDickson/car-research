"""Carwow used stock: the parser against a saved frame, stock in gold (present /
gone), the replay, and the residual evidence it feeds the true-monthly."""
import json
import unittest
from datetime import date
from pathlib import Path

from model.deal_math import DEFAULT_BASIS, compute, expected_value, used_route
from pipeline.history import export_used, import_used
from pipeline.providers import carwow_used
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from pipeline.services.snapshot import used_evidence, used_summary
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-07T00:00:00+00:00"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def _provider(files: dict[str, str]):
    cap = carwow_used.stock

    def discover(target: Target, ctx: Context):
        for t in cap.discover(target, ctx):
            if t.identifier in files:
                yield t

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes())

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name="carwow_used", default_capability=c.name, capabilities={c.name: c}, live=False)


class UsedCards(unittest.TestCase):
    def test_cards_give_derivative_price_year_mileage_and_a_deal_link(self):
        rows = carwow_used.parse_page(fixture("carwow_used_hyundai_ioniq-5_p1.html"), "hyundai", "ioniq-5", "u", T, "Hyundai")
        self.assertEqual(len(rows), 6)
        r = rows[0]
        self.assertEqual((r["make"], r["model"], r["derivative"], r["price_gbp"], r["year"], r["mileage"], r["town"]),
                         ("Hyundai", "Ioniq 5", "125kW 58 kWh Auto Premium Part Leather", 18733.0, 2024, 31860, "Mountsorrel"))
        self.assertTrue(r["listing_key"].startswith("carwow-used:") and r["source_url"].startswith("https://quotes.carwow.co.uk/deals/"))
        self.assertEqual(r["car_ref"]["derivative"], r["derivative"])
        self.assertIn("Used", r["badges"])

    def test_pages_join_and_deal_ids_dedupe(self):
        page = fixture("carwow_used_hyundai_ioniq-5_p1.html") + carwow_used.PAGE_BREAK + fixture("carwow_used_hyundai_ioniq-5_p3.html")
        rows = carwow_used.parse_page(page, "hyundai", "ioniq-5", "u", T, "Hyundai")
        # Carwow's pages overlap (two of page 3's three cars are on page 1): one row per car.
        self.assertEqual(len(rows), 7)
        self.assertEqual(len({r["listing_key"] for r in rows}), 7)
        self.assertEqual(len(carwow_used.deal_ids(fixture("carwow_used_hyundai_ioniq-5_p3.html"))), 3)


class UsedInGold(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)

    def test_stock_is_present_until_a_later_page_lacks_it(self):
        p = _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"})
        res = run(self.conn, p, ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.records, res.gold_rows), (0, 6, 6))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM used_listings WHERE present=1").fetchone()[0], 6)
        # The next visit lists three cars (one new, two already known): those three are stock, the other four gone.
        p3 = _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p3.html"})
        run(self.conn, p3, ctx=Context(root=FIX))
        rows = {r[0]: r[1] for r in self.conn.execute("SELECT listing_key, present FROM used_listings")}
        self.assertEqual(len(rows), 7)
        self.assertEqual(sum(rows.values()), 3)

    def test_round_trip_through_history(self):
        p = _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"})
        run(self.conn, p, ctx=Context(root=FIX))
        tmp = FIX.parent / "_used.jsonl"
        try:
            self.assertEqual(export_used(self.conn, tmp), 6)
            other = fresh_conn()
            run_all(other)
            self.assertEqual(import_used(other, tmp), 6)
            self.assertEqual(other.execute("SELECT price_gbp, year FROM used_listings WHERE listing_key LIKE '%907dd561%'").fetchone()[:], (18733.0, 2024))
        finally:
            tmp.unlink(missing_ok=True)


class ResidualEvidence(unittest.TestCase):
    BASIS = {**DEFAULT_BASIS, "term_months": 37, "savings_rate_apr": 0.04, "residual_pct_of_list": 0.45, "residual_at_months": 36}

    def listings(self, years_prices):
        return [{"listing_key": f"k{i}", "present": True, "price_gbp": p, "year": y, "last_seen_at": "2026-10-07T00:00:00+00:00"}
                for i, (y, p) in enumerate(years_prices)]

    def test_three_examples_of_the_right_age_make_a_residual(self):
        ev = used_evidence(self.listings([(2023, 20000), (2023, 22000), (2023, 21000), (2022, 15000)]), date(2026, 10, 7), self.BASIS)
        self.assertEqual((ev["target_year"], ev["residual"]), (2023, {"value": 21000, "source": "used-market", "n": 3, "year": 2023}))
        ev = used_evidence(self.listings([(2023, 20000), (2023, 22000)]), date(2026, 10, 7), self.BASIS)
        self.assertIsNone(ev["residual"], "two is not evidence")
        self.assertEqual(ev["by_year"][2023], {"n": 2, "median": 21000, "min": 20000})

    def test_expected_value_prefers_evidence_then_the_grown_gfv_then_the_assumption(self):
        v, src = expected_value("c", 40000.0, 37, self.BASIS, {"c": {"value": 21000, "source": "used-market"}}, gfv=18000.0)
        self.assertEqual((v, src), (21000.0, "used-market"))
        v, src = expected_value("c", 40000.0, 37, self.BASIS, {}, gfv=18000.0)
        self.assertEqual(src, "gfv-grown")
        self.assertAlmostEqual(v, 18000.0 * 1.04 ** (37 / 12), places=2)
        v, src = expected_value("c", 40000.0, 37, self.BASIS, {}, gfv=None)
        self.assertEqual(src, "assumption")
        self.assertAlmostEqual(v, 40000.0 * 0.45 ** (37 / 36), places=2)

    def test_evidence_flows_into_the_pcp_and_cash_metrics(self):
        pcp = {"id": "p", "car_id": "c", "finance_type": "pcp", "status": "live", "list_price": 40000.0, "vehicle_price": 36000.0,
               "customer_deposit": 0.0, "manufacturer_contribution": 0.0, "apr": 0.0, "num_payments": 36, "term_months": 37,
               "gfv": 18000.0, "monthly_payment": 500.0}
        cash = {"id": "k", "car_id": "c", "finance_type": "cash", "status": "live", "list_price": 40000.0, "vehicle_price": 34000.0}
        r = {m["id"]: m for m in compute([pcp, cash], self.BASIS, {"c": {"value": 21000, "source": "used-market"}})}
        self.assertEqual((r["p"]["residual_source"], r["p"]["expected_value_at_end"], r["p"]["expected_equity"]), ("used-market", 21000.0, 3000.0))
        self.assertEqual((r["k"]["residual_source"], r["k"]["expected_value_at_end"]), ("used-market", 21000.0))
        r = {m["id"]: m for m in compute([pcp, cash], self.BASIS)}
        self.assertEqual((r["p"]["residual_source"], r["k"]["residual_source"]), ("gfv-grown", "gfv-grown"), "the cash route borrows the car's GFV")

    def test_the_used_route_costs_a_listing_like_the_others(self):
        ev = used_evidence(self.listings([(2024, 19000), (2021, 12000), (2021, 12500), (2021, 11500)]), date(2026, 10, 7), self.BASIS)
        s = used_summary(self.listings([(2024, 19000), (2021, 12000), (2021, 12500), (2021, 11500)]), ev, self.BASIS, date(2026, 10, 7))
        self.assertEqual((s["count"], s["cheapest"]["price_gbp"], s["cheapest"]["year"]), (4, 11500, 2021))
        self.assertEqual(s["route"]["residual_source"], "assumption", "nothing listed from 2018 to say what a 2021 car is worth in 2029")
        self.assertAlmostEqual(s["route"]["true_monthly"], used_route(11500, 5, self.BASIS)["true_monthly"])
        # A 2024 car's end value is what 2021 cars ask today: three of them, median £12,000.
        s2 = used_summary(self.listings([(2024, 19000), (2021, 12000), (2021, 12500), (2021, 11500)]), ev, self.BASIS, date(2026, 10, 7))
        route_2024 = used_route(19000, 2, self.BASIS, 12000)
        self.assertEqual(route_2024["residual_source"], "used-market")
        self.assertLess(route_2024["true_monthly"], used_route(19000, 2, self.BASIS)["true_monthly"] + 1)


if __name__ == "__main__":
    unittest.main()
