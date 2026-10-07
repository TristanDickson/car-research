"""The sighting model: one fact per route, source as a dimension, costed as of
a date; the used asking-price spans in gold; the series the exporter writes."""
import json
import unittest
from datetime import date
from pathlib import Path

from model.deal_math import DEFAULT_BASIS, used_route
from model.sightings import (Costed, Sighting, best_by_route, cost, cost_all, current, floor_gfv_at, gone_dates, residual_at,
                             residual_series, series, source_of, subject)
from pipeline import gold
from pipeline.history import export_used_observations, import_used_observations
from pipeline.providers import carwow_used
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from pipeline.services.snapshot import deal_summary
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"
BASIS = {**DEFAULT_BASIS, "term_months": 37, "savings_rate_apr": 0.04, "residual_pct_of_list": 0.45, "residual_at_months": 36}
MODEL = "hyundai/ioniq-5"


def used(key, price, year, seen_from, seen_to, source="cinch", vrm=None, mileage=30000, present=True):
    return Sighting(key=key, route="used", source=source, model=MODEL, car_id=None, seen_from=seen_from, seen_to=seen_to,
                    present=present, deal={"price": price, "year": year, "mileage": mileage, "vrm": vrm})


def offer(key, route, source, deal, seen_from, seen_to, car_id="car-a", present=True):
    return Sighting(key=key, route=route, source=source, model=MODEL, car_id=car_id, seen_from=seen_from, seen_to=seen_to,
                    present=present, deal=deal, seller=deal.get("dealer"))


PCP = {"list_price": 40000.0, "vehicle_price": 36000.0, "customer_deposit": 0.0, "manufacturer_contribution": 0.0, "apr": 0.0,
       "num_payments": 36, "term_months": 37, "gfv": 18000.0, "monthly_payment": 500.0, "dealer": "Hyundai Finance"}
CASH = {"list_price": 40000.0, "vehicle_price": 34000.0, "dealer": "A broker"}


class Evidence(unittest.TestCase):
    def test_the_residual_is_read_as_of_a_date_and_counts_a_car_once(self):
        stock = [used("a", 20000, 2023, "2026-10-01", "2026-10-07", vrm="AB23CDE"),
                 used("b", 20099, 2023, "2026-10-03", "2026-10-07", source="carwow", mileage=30000),   # the same car, no plate
                 used("c", 22000, 2023, "2026-10-03", "2026-10-07", vrm="ZZ23ZZZ", mileage=1),
                 used("d", 21000, 2023, "2026-10-05", "2026-10-07", source="motorpoint", mileage=2),
                 used("e", 15000, 2023, "2026-09-01", "2026-09-20", vrm="OLD23OLD", mileage=3, present=False)]
        at = residual_at(stock)
        self.assertIsNone(at(MODEL, 2023, date(2026, 10, 2)), "one car is not evidence")
        self.assertIsNone(at(MODEL, 2023, date(2026, 10, 4)), "a and b are one car: two cars, not three")
        self.assertEqual(at(MODEL, 2023, date(2026, 10, 6)), (21000, 3))
        self.assertIsNone(at(MODEL, 2022, date(2026, 10, 6)))
        self.assertIsNone(at(MODEL, 2023, date(2026, 9, 10)), "a gone listing is not evidence")

    def test_the_floor_is_the_highest_gfv_guaranteed_on_the_day(self):
        at = floor_gfv_at([offer("p1", "pcp", "hyundai", {**PCP, "gfv": 18000.0}, "2026-01-01", "2026-06-30"),
                           offer("p2", "pcp", "carwow", {**PCP, "gfv": 19000.0}, "2026-05-01", "2026-10-07")])
        self.assertEqual((at("car-a", date(2026, 3, 1)), at("car-a", date(2026, 6, 1)), at("car-a", date(2026, 9, 1)), at("car-b", date(2026, 6, 1))),
                         (18000.0, 19000.0, 19000.0, None))


class Costing(unittest.TestCase):
    STOCK = [used(f"s{i}", p, 2023, "2026-10-01", "2026-10-07", vrm=f"V{i}", mileage=i) for i, p in enumerate((20000, 21000, 22000))]

    def test_a_pcp_sighting_is_costed_on_what_the_market_said_that_day(self):
        pcp = offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07")
        residual, floor = residual_at(self.STOCK), floor_gfv_at([pcp])
        june = cost(pcp, BASIS, residual, floor, date(2026, 6, 1))
        today = cost(pcp, BASIS, residual, floor, date(2026, 10, 7))
        self.assertEqual((june.residual_source, today.residual_source), ("gfv-grown", "used-market"))
        self.assertEqual(today.expected_value_at_end, 21000.0)
        self.assertLess(today.true_monthly, june.true_monthly, "equity above the GFV makes the PCP cheaper")
        self.assertEqual((june.headline, june.basis_rate, june.as_of), (500.0, 0.04, "2026-06-01"))

    def test_a_used_sighting_is_costed_like_the_used_route(self):
        s = used("x", 19000, 2024, "2026-10-07", "2026-10-07")
        c = cost(s, BASIS, residual_at(self.STOCK), floor_gfv_at([]), date(2026, 10, 7))
        self.assertEqual((c.headline, c.residual_source), (19000.0, "assumption"), "nothing from 2021 says what a 2024 car is worth in 2029")
        self.assertAlmostEqual(c.true_monthly, used_route(19000, 2, BASIS)["true_monthly"])

    def test_cost_all_dates_history_by_first_day_and_today_by_today(self):
        pcp = offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07")
        cash = offer("k", "cash", "ncd", CASH, "2026-10-05", "2026-10-07")
        gone = offer("g", "cash", "carwow", CASH, "2026-01-05", "2026-02-07", present=False)
        history = {c.sighting.key: c for c in cost_all([pcp, cash, gone] + self.STOCK, BASIS)}
        self.assertEqual(sorted(history), ["k", "p", "s0", "s1", "s2"], "a gone sighting is not costed")
        self.assertEqual((history["p"].as_of, history["p"].residual_source, history["k"].residual_source), ("2026-06-01", "gfv-grown", "used-market"))
        now = {c.sighting.key: c for c in cost_all([pcp, cash] + self.STOCK, BASIS, as_of=date(2026, 10, 7))}
        self.assertEqual(now["p"].residual_source, "used-market")
        self.assertIsNone(cost(offer("bad", "pcp", "x", {"vehicle_price": 1.0}, "2026-01-01", "2026-01-01"), BASIS, residual_at([]), floor_gfv_at([]), date(2026, 1, 1)),
                          "a payload the maths cannot cost is dropped, not fatal")


class Series(unittest.TestCase):
    def test_series_group_by_subject_route_and_source(self):
        rows = cost_all([offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07"),
                         offer("p-again", "pcp", "hyundai", {**PCP, "monthly_payment": 480.0}, "2026-10-01", "2026-10-07"),
                         offer("k", "cash", "ncd", CASH, "2026-10-05", "2026-10-07"),
                         offer("k2", "cash", "carwow", {**CASH, "vehicle_price": 35000.0}, "2026-10-05", "2026-10-07"),
                         used("u1", 20000, 2023, "2026-10-01", "2026-10-07", vrm="A"),
                         used("u2", 18000, 2023, "2026-10-04", "2026-10-07", vrm="B"),
                         used("u3", 19000, 2023, "2026-10-02", "2026-10-07", source="carwow")], BASIS)
        out = {s["id"]: s for s in series(rows)}
        self.assertEqual(sorted(out), ["car-a|cash|carwow", "car-a|cash|ncd", "car-a|pcp|hyundai", "model:hyundai/ioniq-5|used|carwow", "model:hyundai/ioniq-5|used|cinch"])
        self.assertEqual([p["key"] for p in out["car-a|pcp|hyundai"]["points"]], ["p", "p-again"], "offers keep one flat span per sighting")
        self.assertEqual(out["car-a|cash|ncd"]["source_name"], "New Car Discount")
        steps = out["model:hyundai/ioniq-5|used|cinch"]["points"]
        self.assertEqual([(p["from"], p["to"], p["key"]) for p in steps], [("2026-10-01", "2026-10-04", "u1"), ("2026-10-04", "2026-10-07", "u2")],
                         "a model's used stock is the cheapest example, as steps")
        self.assertEqual(steps[1]["n"], 2)

    def test_an_offer_holds_to_its_next_sighting_unless_seen_gone_between(self):
        sightings = [offer("k", "cash", "carwow", CASH, "2025-06-01", "2025-06-01"),
                     offer("k", "cash", "carwow", {**CASH, "vehicle_price": 33000.0}, "2025-08-01", "2025-08-01"),
                     offer("k", "cash", "carwow", {**CASH, "vehicle_price": 33000.0}, "2025-09-15", "2025-09-15", present=False),
                     offer("k", "cash", "carwow", {**CASH, "vehicle_price": 32000.0}, "2026-02-01", "2026-10-06")]
        pts = series(cost_all(sightings, BASIS), gone_dates(sightings))[0]["points"]
        self.assertEqual([(p["from"], p["to"]) for p in pts], [("2025-06-01", "2025-08-01"), ("2025-08-01", "2025-08-01"), ("2026-02-01", "2026-10-06")],
                         "June held to August's capture; August not held across the September gone; February's span as confirmed")
        self.assertEqual(gone_dates(sightings), {"k": ["2025-09-15"]})

    def test_residual_series_samples_the_evidence_monthly(self):
        stock = [used(f"s{i}", 20000 + i * 1000, 2023, "2026-08-15", "2026-10-07", vrm=f"V{i}") for i in range(3)]
        out = residual_series(stock, date(2026, 10, 7))
        self.assertEqual((out[0]["model"], out[0]["year"]), (MODEL, 2023))
        self.assertEqual([p["date"] for p in out[0]["points"]], ["2026-09-01", "2026-10-01", "2026-10-07"])
        self.assertEqual(out[0]["points"][-1], {"date": "2026-10-07", "median": 21000, "n": 3})

    def test_current_is_the_cheapest_per_route_and_source_as_of_today(self):
        today = date(2026, 10, 7)
        rows = cost_all([offer("k", "cash", "ncd", CASH, "2026-10-05", "2026-10-07"),
                         offer("k-old", "cash", "ncd", {**CASH, "vehicle_price": 30000.0}, "2026-08-01", "2026-08-20"),   # stale
                         offer("k2", "cash", "carwow", {**CASH, "vehicle_price": 35000.0}, "2026-10-05", "2026-10-07"),
                         offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07"),
                         used("u1", 20000, 2023, "2026-10-01", "2026-10-07", vrm="A"), used("u2", 18000, 2023, "2026-10-04", "2026-10-07", vrm="B")],
                        BASIS, as_of=today)
        cur = current(rows, today, stale_days=14)
        self.assertEqual(sorted(cur), ["car-a", "model:hyundai/ioniq-5"])
        self.assertEqual(sorted(cur["car-a"]["cash"]), ["carwow", "ncd"])
        self.assertEqual((cur["car-a"]["cash"]["ncd"]["key"], cur["car-a"]["cash"]["ncd"]["headline"], cur["car-a"]["cash"]["ncd"]["age_days"]), ("k", 34000.0, 0))
        self.assertEqual(cur["model:hyundai/ioniq-5"]["used"]["cinch"]["key"], "u2")
        routes = {**cur["car-a"], **cur["model:hyundai/ioniq-5"]}
        best = best_by_route(routes)
        self.assertEqual((best["cash"]["key"], best["used"]["key"]), ("k", "u2"))
        summary = deal_summary([], {}, None, routes)
        self.assertEqual(sorted(summary["true_monthly_by_route"]), ["cash", "pcp", "used"])
        self.assertEqual(summary["true_monthly_by_route"]["cash"]["source"], "ncd")
        self.assertEqual(summary["routes"]["cash"]["carwow"]["source_name"], "Carwow")
        self.assertIn(summary["best_true_route"], ("cash", "pcp", "used"))

    def test_sources_are_a_dimension_of_their_own(self):
        self.assertEqual((source_of("carwow_deals"), source_of("carwow_used"), source_of("cinch_used"), source_of("something_new")),
                         ("carwow", "carwow", "cinch", "something_new"))
        self.assertEqual(subject(used("u", 1, 2023, "2026-10-01", "2026-10-01")), "model:hyundai/ioniq-5")
        self.assertEqual(subject(offer("o", "cash", "ncd", CASH, "2026-10-01", "2026-10-01")), "car-a")


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


class UsedSpans(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)

    def spans(self):
        return [tuple(r) for r in self.conn.execute(
            "SELECT listing_key, price_gbp, present, observed_at < confirmed_at FROM used_observations ORDER BY listing_key, observed_at, id")]

    def test_a_listing_s_price_becomes_spans_that_close_when_it_goes(self):
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
        self.assertEqual(self.conn.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (6, 6))
        # Seen again at the same price: the span extends; one car's price changes: a new span; four cars gone: closed.
        self.conn.execute("UPDATE used_observations SET observed_at='2026-10-01T00:00:00+00:00', confirmed_at='2026-10-01T00:00:00+00:00'")
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p3.html"}), ctx=Context(root=FIX))
        rows = self.conn.execute(
            "SELECT listing_key, COUNT(*), SUM(present), MIN(present) FROM used_observations GROUP BY 1 ORDER BY 1").fetchall()
        gone = [r for r in rows if r[3] == 0]
        self.assertEqual(len(gone), 4, "the four cars not on page 3 got a present=0 span")
        self.assertTrue(all(r[1] == 2 for r in gone))
        kept = [r for r in rows if r[3] == 1]
        self.assertEqual(len(kept), 3)
        extended = self.conn.execute(
            "SELECT COUNT(*) FROM used_observations WHERE present=1 AND observed_at='2026-10-01T00:00:00+00:00' AND confirmed_at > observed_at").fetchone()[0]
        self.assertGreaterEqual(extended, 1, "an unchanged price re-sighted pushes confirmed_at")

    def test_spans_are_backfilled_from_stock_recorded_before_them_and_round_trip(self):
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
        self.conn.execute("DELETE FROM used_observations")
        self.conn.execute("UPDATE used_listings SET present=0 WHERE listing_key LIKE '%907dd561%'")
        self.assertEqual(gold.backfill_used_spans(self.conn), 6)
        self.assertEqual(self.conn.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (7, 6))
        self.assertEqual(gold.backfill_used_spans(self.conn), 0, "idempotent")
        tmp = FIX.parent / "_used_obs.jsonl"
        try:
            self.assertEqual(export_used_observations(self.conn, tmp), 7)
            other = fresh_conn()
            run_all(other)
            run(other, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
            other.execute("DELETE FROM used_observations")
            self.assertEqual(import_used_observations(other, tmp), 7)
            self.assertEqual(other.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (7, 6))
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
