"""EV Database car pages: every number the variant's own page prints, and the
model-level body numbers the claim store infers when every current variant agrees."""
import unittest
from pathlib import Path

from pipeline.providers import evdb_cars
from pipeline.services.claims import build_store, resolve_car
from pipeline.services.features import wheel_size, wheel_sizes

FIXTURE = Path(__file__).parent / "fixtures" / "evdb_car_inster_standard.html"
META = {"evdb_id": "3033", "url": "https://ev-database.org/uk/car/3033/Hyundai-Inster-Standard-Range", "make": "Hyundai", "model": "Inster 42 kWh"}
CATALOGUE = [{"make": "hyundai", "model": "inster", "make_name": "Hyundai", "model_name": "Inster"}]


class CarPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = evdb_cars.parse_page(FIXTURE.read_text(), META, "2026-10-09")

    def test_charging_reads_the_home_and_rapid_tables(self):
        n = self.row["numbers"]
        self.assertEqual((n["ac_kw"], n["dc_peak_kw"], n["dc_avg_kw"], n["dc_10_80_min"]), (11.0, 73.0, 60.0, 29.0))
        self.assertEqual((n["battery_kwh"], n["battery_usable_kwh"], n["architecture_v"]), (42.0, 39.0, 400))

    def test_dimensions_weights_and_practicality(self):
        n = self.row["numbers"]
        self.assertEqual((n["length_mm"], n["width_mm"], n["height_mm"], n["wheelbase_m"]), (3825.0, 1610.0, 1575.0, 2.58))
        self.assertEqual((n["weight_kg"], n["gvwr_kg"], n["payload_kg"], n["roof_load_kg"]), (1380.0, 1730.0, 425.0, 75.0))
        self.assertEqual((n["seats"], n["isofix_seats"], n["boot_l"], n["boot_max_l"], n["roof_rails"]), (4, 2, 280.0, 1059.0, True))

    def test_ranges_performance_and_safety(self):
        n = self.row["numbers"]
        self.assertEqual((n["wltp_range_mi"], n["real_range_mi"], n["real_range_cold_mi"], n["motorway_range_mild_mi"]), (203.0, 155.0, 130.0, 145.0))
        self.assertEqual((n["power_kw"], n["power_hp"], n["zero_to_62_s"], n["top_speed_mph"], n["drive"]), (71.0, 95.0, 11.7, 87.0, "FWD"))
        self.assertEqual((n["ncap_stars"], n["ncap_adult_pct"], n["ncap_year"]), (4, 70.0, 2025))
        self.assertNotIn("platform", n, "'No Data' is not a value")

    def test_outlets_and_heat_pump(self):
        self.assertEqual(self.row["flags"]["heat_pump"], "none")
        self.assertEqual((self.row["flags"]["v2l_internal"], self.row["numbers"]["v2l_kw"]), ("standard", 3.6))
        self.assertEqual(self.row["spec_key"], "evdb-car:3033")


class PageIntoClaims(unittest.TestCase):
    def _index(self, vid, model, year, **nums):
        return {"provider": "evdb", "spec_key": f"evdb:{vid}", "make": "Hyundai", "model": model, "source_url": f"u{vid}",
                "numbers": {"battery_usable_kwh": nums.pop("usable", 39.0), "year_from": year, "on_sale": True, **nums}, "flags": {}}

    def test_the_page_fills_the_variant_and_agreeing_body_numbers_speak_for_the_model(self):
        page = evdb_cars.parse_page(FIXTURE.read_text(), META, "2026-10-09")
        index = [self._index("3033", "Inster 42 kWh", 2024), self._index("3034", "Inster 49 kWh", 2024, usable=46.0)]
        other = {**page, "spec_key": "evdb-car:3034", "evdb_id": "3034", "numbers": {**page["numbers"], "battery_usable_kwh": 46.0, "dc_peak_kw": 85.0}}
        c = {"id": "carwow-cap:1", "auto": True, "cap_id": "1", "make": "Hyundai", "model": "Inster", "trim": "01 · 71kW 42kWh Auto", "variant": "71kW 42kWh Auto",
             "battery_kwh": 42.0}
        stub = {"id": "carwow-cap:2", "auto": True, "source_kind": "stub", "cap_id": "2", "make": "Hyundai", "model": "Inster", "trim": "Cross", "variant": "Cross"}
        pages = [{**page, "provider": "evdb_cars"}, {**other, "provider": "evdb_cars"}]
        store = build_store([c, stub], index + pages, CATALOGUE, [], [], [])
        resolve_car(c, store)
        resolve_car(stub, store)
        self.assertEqual((c["width_mm"], c["dc_peak_kw"], c["ac_kw"], c["evdb_url"]), (1610.0, 73.0, 11.0, "u3033"))
        self.assertIn("EV Database", c["field_sources"]["width_mm"])
        self.assertEqual(stub["width_mm"], 1610.0, "every current variant agrees, so the model says it")
        self.assertIn("every current", stub["field_sources"]["width_mm"])
        self.assertIsNone(stub.get("dc_peak_kw"), "charging differs by variant: no battery, no answer")


class WheelSizes(unittest.TestCase):
    def test_sizes_from_equipment_lines(self):
        self.assertEqual(wheel_sizes(['17" alloy wheels', "Steering wheel heated", "Tyre repair kit"]), {17})
        self.assertEqual(wheel_sizes(["19-inch diamond-cut alloy wheels", "Tyres 235/55 R19"]), {19})
        self.assertEqual(wheel_sizes(["Alloy wheels - 18in"]), {18})
        self.assertEqual(wheel_sizes(["20” wheels with aero covers"]), {20})
        self.assertEqual(wheel_sizes(["Wheelbase 2,580mm", "Wheel arch cladding 17 inch"]), set())

    def test_one_size_or_none(self):
        self.assertEqual(wheel_size(['17" alloy wheels']), 17)
        self.assertIsNone(wheel_size(['17" alloy wheels (49kWh)', '15" steel wheels (42kWh)']))
        self.assertIsNone(wheel_size(["LED headlights"]))


if __name__ == "__main__":
    unittest.main()


class Discover(unittest.TestCase):
    """Which pages a run reads: never-read first, one per model in turn, newest variant first, the curated models first."""

    def setUp(self):
        from pipeline.providers.types import Context
        from tests.helpers import fresh_conn
        self.conn = fresh_conn()
        self.addCleanup(self.conn.close)
        now = "2026-10-09T00:00:00+00:00"
        for slug, make, model, mn in (("hyundai/inster", "hyundai", "inster", "Inster"), ("kia/ev3", "kia", "ev3", "EV3")):
            self.conn.execute("INSERT INTO models (slug, make, model, make_name, model_name, electric, source, payload, first_seen_at, last_seen_at) "
                              "VALUES (?,?,?,?,?,1,'test','{}',?,?)", (slug, make, model, make.title() if make != "kia" else "Kia", mn, now, now))
        for vid, make, model, year in (("1", "Kia", "EV3 Standard Range", 2024), ("2", "Kia", "EV3 Long Range", 2025),
                                       ("3", "Hyundai", "Inster 42 kWh", 2024), ("4", "Hyundai", "Inster 49 kWh", 2025), ("9", "Tesla", "Model Y", 2025)):
            payload = {"make": make, "model": model, "source_url": f"https://ev-database.org/uk/car/{vid}/x", "numbers": {"year_from": year}}
            self.conn.execute("INSERT INTO specs (spec_key, source, make, model, payload, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?)",
                              (f"evdb:{vid}", "evdb", make, model, __import__("json").dumps(payload), now, now))
        self.conn.execute("INSERT INTO cars (id, make, model, payload, source, updated_at) VALUES (?,?,?,?,?,?)",
                          ("hyundai-inster-49-02", "Hyundai", "Inster", '{"make": "Hyundai", "model": "Inster"}', "seed", now))
        self.ctx = Context(root=Path("."))
        self.ctx.extras["db"] = self.conn

    def ids(self, **extras):
        from pipeline.providers.types import Target
        self.ctx.extras.update(extras)
        return [t.identifier for t in evdb_cars.discover(Target(identifier="all"), self.ctx)]

    def test_order_and_batch(self):
        self.assertEqual(self.ids(), ["4", "2", "3", "1"], "the curated Inster first; each model's newest variant before any model's second; no catalogue model, no page")
        self.assertEqual(self.ids(evdb_cars_per_run=2), ["4", "2"])
        self.assertEqual(self.ids(evdb_cars_per_run=40, evdb_cars_budget_s=-1), [], "the run's time is spent")
