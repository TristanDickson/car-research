"""EV Database cards as spec rows, and the overlays that fill a car's facts
with the source of every field recorded."""
import unittest
from pathlib import Path

from pipeline.providers import evdb
from pipeline.services.facts import model_of, pick_variant

FIX = Path(__file__).parent / "fixtures"
CATALOGUE = [
    {"make": "hyundai", "model": "inster", "make_name": "Hyundai", "model_name": "Inster"},
    {"make": "hyundai", "model": "ioniq-5", "make_name": "Hyundai", "model_name": "Ioniq 5"},
    {"make": "hyundai", "model": "kona-electric", "make_name": "Hyundai", "model_name": "Kona Electric"},
    {"make": "skoda", "model": "enyaq", "make_name": "Skoda", "model_name": "Enyaq"},
    {"make": "skoda", "model": "enyaq-coupe", "make_name": "Skoda", "model_name": "Enyaq Coupe"},
]


class Cards(unittest.TestCase):
    def setUp(self):
        self.rows = evdb.parse_page((FIX / "evdb_uk_index.html").read_text(encoding="utf-8"), "u", "T")

    def test_every_card_becomes_a_spec_row_with_measured_numbers(self):
        self.assertEqual(len(self.rows), 4)
        r = next(r for r in self.rows if r["model"] == "INSTER Long Range")
        self.assertEqual((r["spec_key"], r["make"], r["source_url"]), ("evdb:2231", "Hyundai", "https://ev-database.org/uk/car/2231/Hyundai-INSTER-Long-Range"))
        n = r["numbers"]
        self.assertEqual((n["battery_usable_kwh"], n["real_range_mi"], n["zero_to_62_s"], n["dc_avg_kw"], n["boot_l"], n["weight_kg"], n["seats"], n["price_gbp"]),
                         (46.0, 185.0, 10.6, 70.0, 351.0, 1410.0, 4, 24545.0))
        self.assertAlmostEqual(n["efficiency_mi_kwh"], 1000 / 249, places=2)
        self.assertNotIn("tow_kg", n, "'unknown' towing is not a number")
        self.assertEqual(r["flags"].get("v2l_external"), "standard")
        self.assertEqual(r["model_year_hint"], "2024")
        self.assertIsNone(r["cap_id"], "EV Database variants are not CAP derivatives")

    def test_heat_pump_wording_is_read_as_a_tri_state(self):
        for r in self.rows:
            self.assertIn(r["flags"].get("heat_pump"), ("none", "standard", "option"))
        self.assertEqual(next(r for r in self.rows if r["model"] == "INSTER Long Range")["flags"]["heat_pump"], "option", "'available' is offered, not promised standard")


class Overlays(unittest.TestCase):
    def test_a_variant_belongs_to_the_longest_matching_catalogue_model(self):
        self.assertEqual(model_of("Skoda", "Enyaq Coupe 85", CATALOGUE)["model"], "enyaq-coupe")
        self.assertEqual(model_of("Skoda", "Enyaq 85", CATALOGUE)["model"], "enyaq")
        self.assertEqual(model_of("Hyundai", "IONIQ 5 Long Range 2WD", CATALOGUE)["model"], "ioniq-5")
        self.assertEqual(model_of("Hyundai", "Kona Electric 65 kWh", CATALOGUE)["model"], "kona-electric")
        self.assertIsNone(model_of("Tesla", "Model 3", CATALOGUE))

    def test_the_variant_is_picked_by_battery_never_guessed(self):
        lr = {"model": "INSTER Long Range", "numbers": {"battery_usable_kwh": 46.0}}
        sr = {"model": "INSTER Standard Range", "numbers": {"battery_usable_kwh": 39.0}}
        self.assertIs(pick_variant({"battery_kwh": 49.0}, [lr, sr]), lr)
        self.assertIs(pick_variant({"battery_kwh": 42.0}, [lr, sr]), sr)
        self.assertIsNone(pick_variant({"battery_kwh": 77.0}, [lr, sr]), "no pack of that size")
        self.assertIs(pick_variant({"battery_kwh": None}, [lr]), lr, "one variant and no battery to contradict it")
        self.assertIsNone(pick_variant({"battery_kwh": None}, [lr, sr]), "two variants and nothing to choose by")

    def test_the_same_pack_across_years_picks_the_one_on_sale_for_the_cars_year(self):
        old = {"model": "Kona Electric 64 kWh", "numbers": {"battery_usable_kwh": 64.0, "year_from": 2018, "on_sale_until": "2023-03"}}
        new = {"model": "Kona Electric 65 kWh", "numbers": {"battery_usable_kwh": 64.8, "year_from": 2023, "on_sale": True}}
        self.assertIs(pick_variant({"battery_kwh": 65.0, "model_year": 2025}, [old, new]), new)
        self.assertIs(pick_variant({"battery_kwh": 65.0, "model_year": 2021}, [old, new]), old, "a used 2021 car is the old one")
        self.assertIs(pick_variant({"battery_kwh": 65.0}, [old, new]), new, "no year: the one on sale")


if __name__ == "__main__":
    unittest.main()
