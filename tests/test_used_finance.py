"""Used stock keeps what the cinch and Motorpoint listings print beyond the price: cinch's finance
quote for each car (and whether it adds up), Motorpoint's lowest monthly payment, and the colour,
drive, reduction, tags, warranty and plate each prints, and what cinch says of the car in fields of
its own (trim, seats, range). Fixtures are pages stored on 11 Oct 2026, trimmed to a few listings:
cinch's Hyundai and Tesla page 1 API responses (facets dropped) and Motorpoint's page 8 search
result; and cinch's BMW and Mazda page 1 responses of 16 Oct, trimmed the same way."""
import copy
import json
import unittest
from pathlib import Path

from pipeline.providers import cinch_used, motorpoint_used
from pipeline.providers.types import Target
from pipeline.services.snapshot import load_used
from tests.helpers import Raws

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-11T03:19:02+00:00"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def models(*rows: tuple[str, str, str, str]) -> list[dict]:
    return [{"make": mk, "model": mo, "make_name": mkn, "model_name": mon} for mk, mo, mkn, mon in rows]


HYUNDAI = models(("hyundai", "ioniq-5", "Hyundai", "Ioniq 5"), ("hyundai", "ioniq-9", "Hyundai", "Ioniq 9"),
                 ("hyundai", "kona-electric", "Hyundai", "Kona Electric"), ("hyundai", "ioniq-electric", "Hyundai", "Ioniq electric"))
TESLA = models(("tesla", "model-3", "Tesla", "Model 3"), ("tesla", "model-y", "Tesla", "Model Y"))
BMW = models(("bmw", "i3", "BMW", "i3"), ("bmw", "i4", "BMW", "i4"), ("bmw", "ix3", "BMW", "iX3"))
MAZDA = models(("mazda", "mx-30", "Mazda", "MX-30"))
SUPERMARKET = models(("vauxhall", "mokka-electric", "Vauxhall", "Mokka Electric"), ("tesla", "model-y", "Tesla", "Model Y"),
                     ("ford", "explorer", "Ford", "Explorer"), ("skywell", "be11", "Skywell", "BE11"),
                     ("volkswagen", "id-7", "Volkswagen", "ID.7"))


def cinch_rows(fixture: str, make: str, catalogue: list[dict]) -> dict[str, dict]:
    t = Target(identifier=make, metadata={"make": make, "url": "u", "models": catalogue})
    return {r["listing_key"].split(":")[1][:8]: r for r in cinch_used.parse_body(load(fixture), t, T)}


class CinchQuotes(unittest.TestCase):
    def setUp(self):
        self.rows = cinch_rows("cinch_used_hyundai_2026-10-11_p1.json", "hyundai", HYUNDAI)

    def test_a_pcp_quote_is_kept_whole_and_its_deposit_and_credit_are_the_price_before_the_fee(self):
        r = self.rows["679b3263"]
        self.assertEqual(r["finance"], {"type": "pcp", "monthly_payment": 334.46, "deposit": 2010.0, "apr": 0.124, "num_payments": 48,
                                        "term_months": 49, "final_payment": 8589.0, "credit": 18090.0, "charges": 6553.08,
                                        "annual_mileage": 8000, "excess_mileage_ppm": 6.0, "reconciles": True})
        self.assertEqual(r["finance"]["deposit"] + r["finance"]["credit"], r["price_before_fees"])
        self.assertEqual((r["price_gbp"], r["colour"], r["drive"], r["discount_gbp"], r["tags"]), (20199.0, "Black", "Front-wheel drive", None, []))
        self.assertIn("heated seats", [c["name"] for c in r["categories"]])

    def test_a_quote_whose_charges_carry_ten_pounds_no_payment_shows_still_reconciles(self):
        f = self.rows["5584548d"]["finance"]
        self.assertAlmostEqual(f["credit"] + f["charges"] - f["final_payment"] - f["monthly_payment"] * f["num_payments"], 10.0, places=2)
        self.assertTrue(f["reconciles"])

    def test_a_quote_a_payment_short_does_not_reconcile(self):
        v = copy.deepcopy(load("cinch_used_hyundai_2026-10-11_p1.json")["vehicleListings"][0])
        v["quoteTermMonths"] -= 1
        self.assertIs(cinch_used.finance(v)["reconciles"], False)

    def test_discount_tags_and_the_excess_charge_in_pence_a_mile(self):
        r = self.rows["1ada8c2f"]
        self.assertEqual((r["discount_gbp"], r["tags"], r["finance"]["apr"]), (700.0, ["cars-on-offer"], 0.1241))
        r = self.rows["7e32966b"]
        self.assertEqual((r["tags"], r["drive"], r["finance"]["excess_mileage_ppm"]), (["nearly-new"], "Four-wheel drive", 14.9))

    def test_a_car_without_a_quote_has_none_and_a_reserved_car_stays_out(self):
        self.assertIsNone(self.rows["0456bcf2"]["finance"])
        self.assertEqual(len(self.rows), 5, "six on the trimmed page, one reserved")
        self.assertNotIn("7f6ddfec", self.rows)

    def test_an_hp_quote_has_no_final_payment_or_mileage_terms(self):
        rows = cinch_rows("cinch_used_tesla_2026-10-11_p1.json", "tesla", TESLA)
        self.assertEqual(rows["7ad7d4e6"]["finance"], {"type": "hp", "monthly_payment": 364.93, "deposit": 2000.0, "apr": 0.1242, "num_payments": 60,
                                                       "term_months": 60, "credit": 16500.0, "charges": 5405.8, "reconciles": True})
        self.assertEqual(rows["c0fbf96f"]["finance"]["type"], "pcp")

    def test_existing_fields_are_unchanged(self):
        r = self.rows["679b3263"]
        self.assertEqual((r["make"], r["model"], r["model_slug"], r["derivative"], r["price_before_fees"], r["year"], r["mileage"], r["vrm"]),
                         ("Hyundai", "Kona Electric", "kona-electric", "160kW Advance 65kWh 5dr Auto [Comfort Pack]", 20100.0, 2024, 9434, "BJ24ECC"))
        self.assertTrue(r["listing_key"].startswith("cinch:679b3263"))


class CinchCarFields(unittest.TestCase):
    CAR = ("trim", "seats", "doors", "body", "fuel", "range_mi", "range_test")

    def test_trim_seats_doors_body_and_range_reach_the_row_and_its_car_ref(self):
        rows = cinch_rows("cinch_used_hyundai_2026-10-11_p1.json", "hyundai", HYUNDAI)
        r = rows["679b3263"]
        self.assertEqual({k: r[k] for k in self.CAR},
                         {"trim": "Advance", "seats": 5, "doors": 5, "body": "SUV", "fuel": "Electric", "range_mi": 319, "range_test": "WLTP"})
        self.assertEqual({k: r["car_ref"][k] for k in self.CAR}, {k: r[k] for k in self.CAR})
        self.assertEqual(r["car_ref"]["derivative"], "160kW Advance 65kWh 5dr Auto [Comfort Pack]", "the text the matching reads is unchanged")
        self.assertEqual((rows["1ada8c2f"]["seats"], rows["1ada8c2f"]["trim"]), (7, "Ultimate"))
        self.assertEqual((r["stock_type"], rows["1ada8c2f"]["stock_type"]), ("cinch", "marketplace"))
        self.assertNotIn("stock_type", r["car_ref"], "whose stock it is says nothing of the car")
        tesla = cinch_rows("cinch_used_tesla_2026-10-11_p1.json", "tesla", TESLA)
        self.assertEqual(tesla["c0fbf96f"]["stock_type"], "partner_sourced")

    def test_an_nedc_range_keeps_its_test_a_fractional_one_its_decimals_and_a_missing_trim_is_left_out(self):
        rows = cinch_rows("cinch_used_bmw_2026-10-16_p1.json", "bmw", BMW)
        self.assertEqual((rows["fc89ee2c"]["trim"], rows["fc89ee2c"]["range_mi"], rows["fc89ee2c"]["range_test"]), ("S", 214, "NEDC"))
        self.assertEqual((rows["677e18b1"]["range_mi"], rows["677e18b1"]["range_test"]), (490.3, "WLTP"))
        i3 = rows["25a1981c"]
        self.assertNotIn("trim", i3)
        self.assertNotIn("trim", i3["car_ref"])
        self.assertEqual((i3["derivative"], i3["seats"], i3["range_mi"]), ("125kW 42kWh 5dr Auto", 4, 188.9))

    def test_a_range_extender_is_marked_by_its_fuel_and_has_no_range(self):
        rows = cinch_rows("cinch_used_mazda_2026-10-16_p1.json", "mazda", MAZDA)
        rex, bev = rows["64a3153c"], rows["b28f9aa9"]
        self.assertEqual((rex["fuel"], rex["trim"], rex["derivative"]), ("Electric range extender", "Prime Line", "125kW R-EV Prime Line 5dr Auto"))
        self.assertNotIn("range_mi", rex)
        self.assertNotIn("range_test", rex)
        self.assertEqual((bev["fuel"], bev["range_mi"], bev["range_test"]), ("Electric", 124, "WLTP"))

    def test_the_fields_reach_used_json(self):
        with Raws() as raws:
            raws.add(cinch_used.provider, "bmw", body=json.dumps({"make": "bmw", "pages": [load("cinch_used_bmw_2026-10-16_p1.json")]}).encode("utf-8"),
                     metadata={"make": "bmw", "url": "u", "models": BMW}, at=T)
            conn = raws.build()
            used = {u["listing_key"][6:14]: u for u in load_used(conn)}
        self.assertEqual({k: used["fc89ee2c"].get(k) for k in self.CAR + ("stock_type",)},
                         {"trim": "S", "seats": 4, "doors": 5, "body": "Hatchback", "fuel": "Electric", "range_mi": 214, "range_test": "NEDC",
                          "stock_type": "cinch"})
        self.assertNotIn("trim", used["25a1981c"])


class MotorpointLowestFinance(unittest.TestCase):
    def setUp(self):
        t = Target(identifier="electric", metadata={"url": motorpoint_used.LISTING, "models": SUPERMARKET})
        self.rows = {r["listing_key"]: r for r in motorpoint_used.parse_body(load("motorpoint_used_electric_2026-10-11_p8.json"), t, T)}

    def test_only_the_lowest_monthly_and_its_type_are_kept(self):
        r = self.rows["motorpoint:1677891"]
        self.assertEqual(r["finance"], {"type": "pcp", "monthly_payment": 217.0, "lowest": True})
        self.assertEqual((r["colour"], r["warranty_months_left"], r["plate_age_id"], r["previous_price_gbp"], r["discount_gbp"], r["coming_soon"]),
                         ("Red", 3, "23", None, None, False))
        self.assertEqual(self.rows["motorpoint:1682735"]["finance"], {"type": "hp", "monthly_payment": 347.3, "lowest": True})

    def test_a_reduced_car_keeps_its_price_before_the_reduction(self):
        r = self.rows["motorpoint:1683160"]
        self.assertEqual((r["price_gbp"], r["previous_price_gbp"], r["discount_gbp"]), (28649.0, 30299.0, 1650.0))
        self.assertEqual(r["previous_price_gbp"] - r["discount_gbp"], r["price_gbp"])

    def test_a_car_coming_soon_is_kept_with_its_price_and_marked(self):
        r = self.rows["motorpoint:1678963"]
        self.assertEqual((r["coming_soon"], r["price_gbp"], r["town"], r["model_slug"], r["finance"]["monthly_payment"]),
                         (True, 29899.0, None, "id-7", 462.93))
        self.assertIn("coming soon", r["badges"])
        self.assertEqual(len(self.rows), 5)


class FinanceInGold(unittest.TestCase):
    def test_the_quote_and_the_coming_soon_mark_reach_the_stored_listing(self):
        with Raws() as raws:
            for p, ident, meta, body in (
                    (cinch_used, "hyundai", {"make": "hyundai", "url": "u", "models": HYUNDAI},
                     {"make": "hyundai", "pages": [load("cinch_used_hyundai_2026-10-11_p1.json")]}),
                    (motorpoint_used, "electric", {"url": motorpoint_used.LISTING, "models": SUPERMARKET},
                     {"pages": [load("motorpoint_used_electric_2026-10-11_p8.json")]})):
                raws.add(p.provider, ident, body=json.dumps(body).encode("utf-8"), metadata=meta, at=T)
            conn = raws.build()
            pay = {k: json.loads(p) for k, p in conn.execute("SELECT listing_key, payload FROM used_listings")}
            cinch = next(p for k, p in pay.items() if k.startswith("cinch:679b3263"))
            self.assertEqual((cinch["finance"]["monthly_payment"], cinch["finance"]["reconciles"]), (334.46, True))
            self.assertTrue(pay["motorpoint:1678963"]["coming_soon"])
            present = conn.execute("SELECT present FROM used_listings WHERE listing_key='motorpoint:1678963'").fetchone()[0]
            self.assertEqual(present, 1)


if __name__ == "__main__":
    unittest.main()
