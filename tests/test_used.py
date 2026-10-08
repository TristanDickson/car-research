"""Carwow used stock: the parser against a saved frame, stock in gold (present /
gone), the replay, and the residual evidence it feeds the true-monthly."""
import json
import unittest
from datetime import date
from pathlib import Path

from model.deal_math import DEFAULT_BASIS, compute, expected_value
from pipeline.history import export_used, import_used
from pipeline.providers import carwow_used, cinch_used, motorpoint_used
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.providers.used_match import bare, match_model
from pipeline.runner import run
from pipeline.services.snapshot import dedupe_listings
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


def _json_provider(base, files: dict[str, list[str]], wrap, models: list[dict] | None = None):
    """A JSON-paged used-stock provider (cinch, Motorpoint) served from fixture
    pages, filing listings under `models` rather than the test database's catalogue."""
    cap = base.stock

    def discover(target: Target, ctx: Context):
        for t in cap.discover(target, ctx):
            if t.identifier in files:
                yield Target(t.identifier, {**t.metadata, "models": models} if models else t.metadata)

    def fetch(target: Target, ctx: Context) -> Fetched:
        pages = [json.loads((FIX / f).read_text(encoding="utf-8")) for f in files[target.identifier]]
        return Fetched(url=target.metadata["url"], status_code=200, body=json.dumps(wrap(target, pages)).encode("utf-8"))

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name=base.provider.name, default_capability=c.name, capabilities={c.name: c}, live=False)


HYUNDAI = [{"make": "hyundai", "model": m, "make_name": "Hyundai", "model_name": n} for m, n in
           (("ioniq-5", "Ioniq 5"), ("ioniq-5-n", "Ioniq 5 N"), ("ioniq-6", "Ioniq 6"), ("ioniq-9", "Ioniq 9"), ("inster", "Inster"),
            ("kona-electric", "Kona Electric"), ("ioniq-electric", "Ioniq electric"))]


SUPERMARKET = HYUNDAI + [{"make": mk, "model": mo, "make_name": mkn, "model_name": mon} for mk, mo, mkn, mon in
                         (("polestar", "4", "Polestar", "4"), ("tesla", "model-3", "Tesla", "Model 3"), ("mazda", "mx-30", "Mazda", "MX-30"),
                          ("mg", "mg-4", "MG", "MG4 EV"), ("kia", "niro-ev-estate", "Kia", "Niro EV"))]


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


class CinchListings(unittest.TestCase):
    def target(self):
        return Target(identifier="hyundai", metadata={"make": "hyundai", "url": "u", "models": HYUNDAI})

    def test_listings_file_under_the_catalogue_model_with_registration_and_fee_inclusive_price(self):
        rows = cinch_used.parse_body(json.loads(fixture("cinch_hyundai_electric_p1.json")), self.target(), T)
        self.assertEqual(len(rows), 31, "32 on the page, one reserved")
        by_model = {}
        for r in rows:
            by_model[r["model_slug"]] = by_model.get(r["model_slug"], 0) + 1
        self.assertEqual(by_model, {"kona-electric": 12, "ioniq-5": 10, "ioniq-5-n": 4, "ioniq-9": 3, "inster": 1, "ioniq-electric": 1},
                         "cinch's 'Kona' is the catalogue's Kona Electric, 'IONIQ' the old Ioniq electric")
        r = rows[0]
        self.assertEqual((r["make"], r["model"], r["derivative"], r["price_gbp"], r["price_before_fees"], r["year"], r["mileage"], r["vrm"]),
                         ("Hyundai", "Ioniq 9", "226kW Ultimate 110kWh 5dr AWD Auto", 50599.0, 50500.0, 2025, 10776, "ET25RSY"))
        self.assertTrue(r["listing_key"].startswith("cinch:") and r["source_url"].startswith("https://www.cinch.co.uk/used-cars/hyundai/ioniq-9/details/"))
        self.assertEqual(r["car_ref"]["model"], "Ioniq 9")

    def test_pages_join_and_vehicle_ids_dedupe(self):
        p1, p3 = json.loads(fixture("cinch_hyundai_electric_p1.json")), json.loads(fixture("cinch_hyundai_electric_p3.json"))
        rows = cinch_used.parse_body({"make": "hyundai", "pages": [p1, p3, p1]}, self.target(), T)
        self.assertEqual((len(rows), len({r["listing_key"] for r in rows})), (53, 53))

    def test_the_api_url_filters_electric_and_pages(self):
        self.assertEqual(cinch_used.api_url("hyundai"), "https://search-api.snc-prod.aws.cinch.co.uk/used-cars?url=hyundai%3FfuelType%3Delectric")
        self.assertIn("pageNumber%3D2", cinch_used.api_url("mercedes-benz", 2))


class MotorpointListings(unittest.TestCase):
    def target(self):
        return Target(identifier="electric", metadata={"url": motorpoint_used.LISTING, "models": SUPERMARKET})

    def test_the_search_result_files_cars_under_catalogue_models(self):
        rows = motorpoint_used.parse_body(json.loads(fixture("motorpoint_electric_p1.json")), self.target(), T)
        self.assertEqual(len(rows), 12, "35 on the page; the twelve we sell among the models listed")
        r = rows[0]
        self.assertEqual((r["make"], r["model"], r["model_slug"], r["derivative"], r["price_gbp"], r["year"], r["mileage"], r["town"], r["list_price_when_new"]),
                         ("Polestar", "4", "4", "200kW 100kWh LR Single Motor Plus [Pilot] 5dr Auto", 32699.0, 2025, 5472, "Glasgow", 62235.0),
                         "Motorpoint's '4 Coupe' is the Polestar 4, and it prints the list price when new")
        self.assertEqual((r["listing_key"], r["source_url"], r["vrm"]),
                         ("motorpoint:1676078", "https://www.motorpoint.co.uk/vehicle-details/polestar-4-coupe/1676078", None))
        by_model = {}
        for x in rows:
            by_model[x["model_slug"]] = by_model.get(x["model_slug"], 0) + 1
        self.assertEqual(by_model, {"4": 1, "model-3": 3, "mx-30": 3, "mg-4": 2, "niro-ev-estate": 1, "kona-electric": 1, "ioniq-5": 1})

    def test_pages_join_and_the_page_url_pages(self):
        p1, p2 = json.loads(fixture("motorpoint_electric_p1.json")), json.loads(fixture("motorpoint_electric_p2.json"))
        rows = motorpoint_used.parse_body({"pages": [p1, p2, p1]}, self.target(), T)
        self.assertEqual(len(rows), len({r["listing_key"] for r in rows}))
        self.assertGreater(len(rows), 12)
        self.assertEqual((motorpoint_used.page_url(1), motorpoint_used.page_url(3)),
                         ("https://www.motorpoint.co.uk/used-cars/electric", "https://www.motorpoint.co.uk/used-cars/electric?page=3"))
        html = '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"initialSearch": p2}}}) + "</script></html>"
        self.assertEqual(motorpoint_used.search_result(html)["metadata"]["total"], 582)


class NameMatching(unittest.TestCase):
    MODELS = HYUNDAI + [{"make": "mercedes", "model": "eqa", "make_name": "Mercedes-Benz", "model_name": "EQA"},
                        {"make": "mg", "model": "mg-4", "make_name": "MG", "model_name": "MG4 EV"},
                        {"make": "peugeot", "model": "e-2008", "make_name": "Peugeot", "model_name": "e-2008"},
                        {"make": "citroen", "model": "e-c4", "make_name": "Citroen", "model_name": "e-C4"},
                        {"make": "kia", "model": "niro-ev-estate", "make_name": "Kia", "model_name": "Niro EV"},
                        {"make": "bmw", "model": "i4", "make_name": "BMW", "model_name": "i4"},
                        {"make": "polestar", "model": "4", "make_name": "Polestar", "model_name": "4"},
                        {"make": "polestar", "model": "4-suv", "make_name": "Polestar", "model_name": "4 SUV"},
                        {"make": "fiat", "model": "500-electric", "make_name": "Fiat", "model_name": "500e"},
                        {"make": "fiat", "model": "500-convertible", "make_name": "Fiat", "model_name": "500 Convertible"},
                        {"make": "volvo", "model": "c40-recharge", "make_name": "Volvo", "model_name": "C40 Recharge"},
                        {"make": "volvo", "model": "ec40", "make_name": "Volvo", "model_name": "EC40"},
                        {"make": "mini", "model": "electric", "make_name": "MINI", "model_name": None}]

    def slug(self, make, model):
        m = match_model(make, model, self.MODELS)
        return m and f"{m['make']}/{m['model']}"

    def test_exact_then_bare_then_alias(self):
        self.assertEqual(self.slug("Hyundai", "IONIQ 5"), "hyundai/ioniq-5")
        self.assertEqual(self.slug("HYUNDAI", "KONA"), "hyundai/kona-electric")
        self.assertEqual(self.slug("Mercedes-Benz", "EQA"), "mercedes/eqa")
        self.assertEqual(self.slug("MG MOTOR UK", "MG4"), "mg/mg-4")
        self.assertEqual(self.slug("PEUGEOT", "2008"), "peugeot/e-2008")
        self.assertEqual(self.slug("CITROEN", "C4"), "citroen/e-c4")
        self.assertEqual(self.slug("KIA", "NIRO"), "kia/niro-ev-estate")
        self.assertEqual(self.slug("BMW", "i4 Gran Coupe"), "bmw/i4")
        self.assertEqual(self.slug("POLESTAR", "4 Coupe"), "polestar/4")
        self.assertEqual(self.slug("Fiat", "500"), "fiat/500-electric")
        self.assertEqual((self.slug("Volvo", "C40"), self.slug("Volvo", "EC40")), ("volvo/c40-recharge", "volvo/ec40"))
        self.assertEqual((self.slug("MINI", "Hatchback"), self.slug("MINI", "COOPER")), ("mini/electric", "mini/electric"))

    def test_what_we_do_not_sell_stays_unmatched(self):
        self.assertIsNone(self.slug("Kia", "e-Niro"), "the previous generation is not the Niro EV")
        self.assertIsNone(self.slug("Alfa Romeo", "Junior"))
        self.assertIsNone(self.slug("Hyundai", "i10"))
        self.assertEqual((bare("Kona Electric"), bare("500e"), bare("e-2008"), bare("e-C4"), bare("e-Berlingo"), bare("3 E-Tense"), bare("EV6")),
                         ("kona", "500", "2008", "c4", "berlingo", "3", "ev6"))


class StockAcrossSources(unittest.TestCase):
    def listing(self, key, source, price, year=2023, mileage=30000, vrm=None, present=True):
        return {"listing_key": key, "provider": source, "source": source, "price_gbp": price, "year": year, "mileage": mileage,
                "vrm": vrm, "present": present, "last_seen_at": T}

    def test_the_same_registration_or_the_same_year_and_mileage_is_one_car(self):
        rows = dedupe_listings([
            self.listing("a", "Carwow used stock", 18000, mileage=30000),                      # no registration printed
            self.listing("b", "cinch", 18099, mileage=30000, vrm="AB23 CDE"),                 # the same car, with one
            self.listing("c", "cinch", 17000, mileage=30000, vrm="ZZ23ZZZ"),                  # another car at the same mileage
            self.listing("d", "Motorpoint", 17500, mileage=30050),                            # mileage differs: its own car
            self.listing("e", "Motorpoint", 16000, mileage=30000, year=2022),                 # year differs
            self.listing("f", "cinch", 15000, mileage=31000, vrm="ab23cde", present=False),   # the same car as a/b, gone since
        ])
        by_key = {r["listing_key"]: r for r in rows}
        self.assertEqual(sorted(by_key), ["a", "c", "d", "e"])
        self.assertEqual(by_key["a"]["sources"], ["Carwow used stock", "cinch"], "the cheapest live listing stands, naming both sites")
        self.assertNotIn("sources", by_key["d"])


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

    def present_by_source(self):
        return {r[0]: (r[1], r[2]) for r in self.conn.execute("SELECT source, SUM(present), COUNT(*) FROM used_listings GROUP BY 1")}

    def test_each_source_marks_only_its_own_stock_gone(self):
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
        wrap = lambda t, pages: {"make": t.identifier, "pages": pages}
        res = run(self.conn, _json_provider(cinch_used, {"hyundai": ["cinch_hyundai_electric_p1.json"]}, wrap, HYUNDAI), ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.records), (0, 31))
        self.assertEqual(self.present_by_source(), {"carwow_used": (6, 6), "cinch_used": (31, 31)})
        # cinch's next visit shows only page 3's cars: its page-1 cars are gone (whatever
        # model they were, the make's page covers them all), Carwow's six untouched.
        run(self.conn, _json_provider(cinch_used, {"hyundai": ["cinch_hyundai_electric_p3.json"]}, wrap, HYUNDAI), ctx=Context(root=FIX))
        self.assertEqual(self.present_by_source(), {"carwow_used": (6, 6), "cinch_used": (22, 53)})
        t = Target("hyundai", {"make": "hyundai", "url": "u", "models": HYUNDAI})
        expected = {}
        for r in cinch_used.parse_body(json.loads(fixture("cinch_hyundai_electric_p3.json")), t, T):
            expected[r["model_slug"]] = expected.get(r["model_slug"], 0) + 1
        self.assertEqual(dict(self.conn.execute("SELECT model_slug, COUNT(*) FROM used_listings WHERE source='cinch_used' AND present=1 GROUP BY 1").fetchall()), expected)
        self.assertGreaterEqual(len(expected), 3)

    def test_motorpoint_stock_lands_beside_the_others(self):
        wrap = lambda t, pages: {"pages": pages}
        res = run(self.conn, _json_provider(motorpoint_used, {"electric": ["motorpoint_electric_p1.json"]}, wrap, SUPERMARKET), ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.records), (0, 12))
        row = self.conn.execute("SELECT make, model, price_gbp, year, mileage, payload FROM used_listings WHERE listing_key='motorpoint:1676078'").fetchone()
        self.assertEqual(row[:5], ("Polestar", "4", 32699.0, 2025, 5472))
        self.assertEqual((json.loads(row[5])["town"], json.loads(row[5])["list_price_when_new"]), ("Glasgow", 62235.0))
        run(self.conn, _json_provider(motorpoint_used, {"electric": ["motorpoint_electric_p2.json"]}, wrap, SUPERMARKET), ctx=Context(root=FIX))
        t = Target("electric", {"url": motorpoint_used.LISTING, "models": SUPERMARKET})
        n2 = len(motorpoint_used.parse_body(json.loads(fixture("motorpoint_electric_p2.json")), t, T))
        self.assertEqual(self.present_by_source(), {"motorpoint_used": (n2, 12 + n2)})

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
    """How evidence reaches the deal maths (the oracle); reading the evidence from
    the spans is the browser's (web/src/lib/model/sightings.ts)."""
    BASIS = {**DEFAULT_BASIS, "term_months": 37, "savings_rate_apr": 0.04, "residual_pct_of_list": 0.45, "residual_at_months": 36}

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


if __name__ == "__main__":
    unittest.main()
