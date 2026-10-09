"""One fact store, one resolver: every field of every car from claims at the
levels a derivative belongs to, with packs, precedence, agreement and provenance."""
import unittest

from pipeline.services import claims
from pipeline.services.claims import Store, build_store, resolve_car, trim_head

CATALOGUE = [{"make": "hyundai", "model": "inster", "make_name": "Hyundai", "model_name": "Inster"},
             {"make": "skoda", "model": "elroq", "make_name": "Skoda", "model_name": "Elroq"}]

INSTER_02_SPEC = {"provider": "carwow_specs", "cap_id": "110532", "make": "Hyundai", "model": "Inster", "trim": "02", "engine": "85kW 49kWh Auto",
                  "variant": "Inster 02 85kW 49kWh Auto", "rrp": 24740.0,
                  "features": [f"Item {i}" for i in range(45)] + ["Heated front seats", "Heated steering wheel", "Rear privacy glass", "LED headlights"],
                  "description": "Step up to 02 trim and you get upgraded seats. The front seats and steering wheel are also heated.",
                  "numbers": {"seats": 4, "battery_kwh": 49.0, "wltp_range_mi": 229.0, "power_bhp": 115.0, "zero_to_60_s": 10.6, "boot_l": 280.0, "drive": "FWD"}}
INSTER_01_SPEC = {**INSTER_02_SPEC, "cap_id": "110533", "trim": "01", "engine": "71kW 42kWh Auto", "variant": "Inster 01 71kW 42kWh Auto", "rrp": 22995.0,
                  "features": [f"Item {i}" for i in range(45)] + ["LED headlights", "Battery heating system"],
                  "description": "The Inster in 01 trim can be had with either powertrain. Regardless of which one you opt for you get the same generous level of equipment, including a heat pump and battery heater to maximise your range.",
                  "numbers": {"seats": 4, "battery_kwh": 42.0, "wltp_range_mi": 203.0, "power_bhp": 97.0, "drive": "FWD"}}
REGISTRY = [
    {"cap_id": "110532", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "85kW 02 49kWh 5dr Auto [No Heat Pump]", "trim": "02", "brackets": ["No Heat Pump"], "rrp": 24740.0},
    {"cap_id": "106646", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "85kW 02 49kWh 5dr Auto", "trim": "02", "brackets": [], "rrp": 27115.0},
    {"cap_id": "110533", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "71kW 01 42kWh 5dr Auto [No Heat Pump]", "trim": "01", "brackets": ["No Heat Pump"], "rrp": 22995.0},
    {"cap_id": "106644", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "71kW 01 42kWh 5dr Auto", "trim": "01", "brackets": [], "rrp": 23755.0},
    {"cap_id": "109120", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "85kW 02 49kWh 5dr Auto [Tech Pack]", "trim": "02", "brackets": ["Tech Pack"], "rrp": 28115.0},
]
CURATED = {"id": "hyundai-inster-49-02", "make": "Hyundai", "model": "Inster", "trim": "02 49kWh", "cap_id": "106646", "heat_pump": "standard",
           "internal_v2l": "pack", "external_v2l": "standard", "packs_required": {"internal_v2l": "Tech Pack (£1,000)"},
           "seats": 4, "battery_kwh": 49.0, "list_price_gbp": 27115.0, "memory_seats": False}


def car(cap, trim, engine, kind="spec", **kw):
    return {"id": f"carwow-cap:{cap}", "auto": True, "source_kind": kind, "cap_id": cap, "make": "Hyundai", "model": "Inster",
            "trim": f"{trim} · {engine}", "variant": engine, "heat_pump": "unknown", "internal_v2l": "unknown", "external_v2l": "unknown", **kw}


class Keys(unittest.TestCase):
    def test_trim_head_strips_engines_brackets_and_packs(self):
        self.assertEqual(trim_head("02 · 85kW 49kWh Auto"), "02")
        self.assertEqual(trim_head("GT-Line S Heat Pump"), "GT-Line S")
        self.assertEqual(trim_head("Ultimate 65kWh"), "Ultimate")
        self.assertEqual(trim_head("Elite 7-seat"), "Elite")
        self.assertEqual(claims.trim_subject("Kia", "EV3", "GT-Line S · 150kW 81kWh Auto"), claims.trim_subject("Kia", "EV3", "GT-Line S"))


class Inster(unittest.TestCase):
    """The real case: a trim sold with and without a heat pump, a Tech Pack version, a curated reading of the 02."""

    def setUp(self):
        self.cars = [car("110532", "02", "85kW 49kWh Auto"), car("106646", "02", "85kW 49kWh Auto", "stub"), car("110533", "01", "71kW 42kWh Auto"),
                     car("106644", "01", "71kW 42kWh Auto", "stub"), car("109120", "02", "85kW 49kWh Auto", "stub"), dict(CURATED)]
        self.store = build_store(self.cars, [INSTER_02_SPEC, INSTER_01_SPEC], CATALOGUE, REGISTRY, [], [])
        for c in self.cars:
            resolve_car(c, self.store)
        self.by = {c["id"]: c for c in self.cars}

    def test_the_bracket_says_none_whatever_the_description_says(self):
        c = self.by["carwow-cap:110533"]
        self.assertEqual(c["heat_pump"], "none")
        self.assertIn("[No Heat Pump]", c["field_sources"]["heat_pump"])
        self.assertEqual(c["flags"]["led_headlights"], "standard")

    def test_the_twin_without_the_bracket_has_it(self):
        c = self.by["carwow-cap:106644"]
        self.assertEqual(c["heat_pump"], "standard")
        self.assertIn("[No …] version", c["field_sources"]["heat_pump"])
        self.assertEqual((c["seats"], c["battery_kwh"], c["list_price_gbp"]), (4, 42.0, 23755.0), "a stub takes the model's seats, the engine's battery and the registry's RRP")
        self.assertIn("same engine", c["field_sources"]["battery_kwh"])

    def test_a_curated_car_reads_onto_its_trim_and_keeps_its_own_word(self):
        c = self.by["carwow-cap:106646"]
        self.assertEqual((c["heat_pump"], c["internal_v2l"], c["external_v2l"]), ("standard", "pack", "standard"))
        self.assertEqual((c["packs_required"]["internal_v2l"], c["pack_prices_gbp"]["Tech Pack"]), ("Tech Pack", 1000.0))
        self.assertEqual(c["flags"]["heated_front_seats"], "standard")
        self.assertEqual(c["flags"]["v2l_any"], "standard")
        k = self.by["hyundai-inster-49-02"]
        self.assertEqual((k["heat_pump"], k["internal_v2l"], k["memory_seats"]), ("standard", "pack", False))
        self.assertNotIn("heat_pump", k.get("field_sources") or {}, "a curated car's own reading is not a filled gap")
        self.assertEqual(k["flags"]["heated_front_seats"], "standard", "and it still learns its trim's equipment")

    def test_an_included_pack_makes_its_contents_standard(self):
        c = self.by["carwow-cap:109120"]
        self.assertEqual(c["internal_v2l"], "standard")
        self.assertIn("Tech Pack (included)", c["field_sources"]["internal_v2l"])
        self.assertEqual(c["packs"], ["Tech Pack"])
        self.assertEqual(c["heat_pump"], "standard", "the 02 has a [No Heat Pump] version, and this is not it")

    def test_absence_from_a_complete_list_is_none(self):
        c = self.by["carwow-cap:110532"]
        self.assertEqual(c["flags"]["powered_tailgate"], "none")
        self.assertIn("not in Carwow's standard equipment", c["field_sources"]["powered_tailgate"])
        self.assertEqual(c["flags"]["rear_privacy_glass"], "standard")


class Configurator(unittest.TestCase):
    def test_options_packs_and_what_is_offered_in_neither(self):
        spec = {"provider": "carwow_specs", "cap_id": "106738", "make": "Skoda", "model": "Elroq", "trim": "SE L", "engine": "150kW 60 63kWh Auto", "variant": "Elroq SE L",
                "features": [f"Item {i}" for i in range(50)] + ["Heated front seats"], "numbers": {"seats": 5}}
        opts = {"cap_id": "106738", "options": [{"name": "Heat pump", "category": "Interior Features", "price": 1100.0, "default": False},
                                                {"name": "Dual zone climate control", "category": "Interior Features", "price": 0.0, "default": True}],
                "packs": [{"name": "Winter package - Elroq", "price": 600.0, "default": False, "items": ["Heated rear seats", "Heated windscreen"]}]}
        reg = [{"cap_id": "106738", "make": "Skoda", "model": "Elroq", "make_slug": "skoda", "model_slug": "elroq", "name": "150kW 60 SE L 63kWh 5dr Auto", "trim": "SE L", "brackets": [], "rrp": 33970.0}]
        c = {"id": "carwow-cap:106738", "auto": True, "source_kind": "spec", "cap_id": "106738", "make": "Skoda", "model": "Elroq", "trim": "SE L · 150kW 60 63kWh Auto", "variant": "150kW 60 63kWh Auto"}
        store = build_store([c], [spec], CATALOGUE, reg, [opts], [])
        resolve_car(c, store)
        self.assertEqual((c["heat_pump"], c["field_sources"]["heat_pump"]), ("option", "Carwow configurator · Heat pump"))
        self.assertEqual((c["flags"]["heated_rear_seats"], c["packs_required"]["heated_rear_seats"], c["pack_prices_gbp"]["Winter package - Elroq"]), ("pack", "Winter package - Elroq", 600.0))
        self.assertEqual(c["flags"]["heated_front_seats"], "standard")
        self.assertEqual(c["flags"]["glass_roof"], "none")
        self.assertIn("not offered as an option or pack", c["field_sources"]["glass_roof"])


class Precedence(unittest.TestCase):
    def test_disagreement_within_the_strongest_bucket_is_unknown_and_kept(self):
        store = Store()
        t = claims.trim_subject("Kia", "EV3", "Air")
        store.add(t, claims.Claim("heat_pump", "standard", "listed", "A", "A says yes"))
        store.add(t, claims.Claim("heat_pump", "none", "absent", "B", "B says no"))
        store.add(t, claims.Claim("glass_roof", "standard", "listed", "A", "A says yes"))
        store.add(t, claims.Claim("glass_roof", "none", "listed", "B", "B says no"))
        c = {"id": "carwow-cap:9", "auto": True, "cap_id": "9", "make": "Kia", "model": "EV3", "trim": "Air · 150kW 58kWh Auto", "variant": "150kW 58kWh Auto"}
        resolve_car(c, store)
        self.assertEqual(c["heat_pump"], "standard", "listed outranks absent")
        self.assertIsNone(c.get("glass_roof"))
        self.assertNotIn("glass_roof", c["flags"])
        self.assertEqual(sorted(c["disagreements"]), ["glass_roof"])

    def test_ev_database_decides_between_option_and_none_when_the_list_is_silent_and_agrees_across_variants(self):
        rows = [{"provider": "evdb", "spec_key": "evdb:1", "make": "Skoda", "model": "Elroq 60", "numbers": {"battery_usable_kwh": 59.0, "dc_avg_kw": 110.0}, "flags": {"heat_pump": "option"}, "source_url": "u1"},
                {"provider": "evdb", "spec_key": "evdb:2", "make": "Skoda", "model": "Elroq 85", "numbers": {"battery_usable_kwh": 77.0, "dc_avg_kw": 130.0}, "flags": {"heat_pump": "option"}, "source_url": "u2"}]
        spec = {"provider": "carwow_specs", "cap_id": "1", "make": "Skoda", "model": "Elroq", "trim": "SE", "engine": "150kW 60 63kWh Auto", "variant": "Elroq SE",
                "features": [f"Item {i}" for i in range(50)], "numbers": {"battery_kwh": 63.0}}
        c = {"id": "carwow-cap:1", "auto": True, "cap_id": "1", "make": "Skoda", "model": "Elroq", "trim": "SE · 150kW 60 63kWh Auto", "variant": "150kW 60 63kWh Auto"}
        stub = {"id": "carwow-cap:2", "auto": True, "source_kind": "stub", "cap_id": "2", "make": "Skoda", "model": "Elroq", "trim": "SE L · 210kW 85 82kWh Auto", "variant": "210kW 85 82kWh Auto"}
        store = build_store([c, stub], [spec] + rows, CATALOGUE, [], [], [])
        resolve_car(c, store)
        resolve_car(stub, store)
        self.assertEqual((c["heat_pump"], c["dc_avg_kw"], c["evdb_url"]), ("option", 110.0, "u1"), "the battery picks the 60 variant; availability beats absence")
        self.assertEqual(stub["heat_pump"], "option")
        self.assertIn("every Skoda", stub["field_sources"]["heat_pump"])
        self.assertIsNone(stub.get("dc_avg_kw"), "no battery, no variant: a number that differs by variant stays unknown")

    def test_prices_take_the_latest_sighting_and_close_numbers_agree(self):
        spec = {"provider": "carwow_specs", "cap_id": "7", "make": "Hyundai", "model": "Inster", "trim": "01", "engine": "71kW 42kWh Auto", "variant": "Inster 01",
                "rrp": 23495.0, "last_seen_at": "2026-10-06", "features": [], "numbers": {"wltp_range_mi": 203.0}}
        spec2 = {**spec, "cap_id": "8", "trim": "01 Premium", "variant": "Inster 01 Premium", "rrp": 24000.0, "numbers": {"wltp_range_mi": 199.0}}
        reg = [{"cap_id": "7", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "71kW 01 42kWh 5dr Auto", "trim": "01", "brackets": [], "rrp": 23755.0, "observed_at": "2026-10-08"}]
        c = car("7", "01", "71kW 42kWh Auto")
        stub = car("9", "02", "71kW 42kWh Auto", "stub")
        store = build_store([c, stub], [spec, spec2], CATALOGUE, reg, [], [])
        resolve_car(c, store)
        resolve_car(stub, store)
        self.assertEqual((c["list_price_gbp"], c["field_sources"]["list_price_gbp"]), (23755.0, "Carwow model page · 71kW 01 42kWh 5dr Auto"))
        self.assertEqual(stub["wltp_range_mi"], 203.0, "two readings of the engine's range within 5% are one reading")
        self.assertNotIn("list_price_gbp", c.get("disagreements") or {})

    def test_broker_names_carry_brackets_too(self):
        c = {"id": "carwow-cap:5", "auto": True, "cap_id": "5", "make": "Hyundai", "model": "IONIQ 5", "trim": "Ultimate · 168kW 84 kWh Auto", "variant": "168kW 84 kWh Auto", "seats": None}
        store = build_store([c], [], CATALOGUE, [], [], [{"source": "leaseloco", "car_id": "carwow-cap:5", "label": "Hyundai IONIQ 5 168kW Ultimate 84 kWh 5dr Auto [Vision Roof] [7 seat]"}])
        resolve_car(c, store)
        self.assertEqual((c["flags"]["glass_roof"], c["seats"]), ("standard", 7))
        self.assertEqual(c["field_sources"]["glass_roof"], "CAP derivative name · Hyundai IONIQ 5 168kW Ultimate 84 kWh 5dr Auto [Vision Roof] [7 seat] (seen on LeaseLoco)")


if __name__ == "__main__":
    unittest.main()


HY_01 = {"provider": "hyundai_specs", "source": "Hyundai UK specification", "make": "Hyundai", "model": "Inster", "trim": "01", "batteries": [42.0, 49.0],
         "features": ["Heat Pump and Battery Heater", "LED Headlights"], "absent": ["Heated Steering Wheel", "Roof Rails"], "qualified": [], "options": [], "packs": []}
HY_02 = {"provider": "hyundai_specs", "source": "Hyundai UK specification", "make": "Hyundai", "model": "Inster", "trim": "02", "batteries": [49.0, 42.0],
         "features": ["Heated Steering Wheel", "LED Headlights"], "absent": ["Roof Rails"], "options": [],
         "qualified": [{"item": "Heat Pump and Battery Heater", "note": "49kWh only", "standard_kwh": [49.0], "none_kwh": [42.0]}],
         "packs": [{"name": "Tech Pack", "price": 1000.0, "items": ["V2L - Internal 3 pin plug 230V 3.6kW", "Surround View Monitor"]}]}
REGISTRY_02_42 = {"cap_id": "110534", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "71kW 02 42kWh 5dr Auto [No Heat Pump]", "trim": "02", "brackets": ["No Heat Pump"], "rrp": 24740.0}


class Maker(unittest.TestCase):
    """The maker's own table ranks with CAP's brackets: where they differ the car shows both sides, not a winner."""

    def setUp(self):
        self.cars = [car("110533", "01", "71kW 42kWh Auto"), car("106644", "01", "71kW 42kWh Auto", "stub"), car("110532", "02", "85kW 49kWh Auto"),
                     car("110534", "02", "71kW 42kWh Auto", "stub"), car("106646", "02", "85kW 49kWh Auto", "stub")]
        self.store = build_store(self.cars, [INSTER_02_SPEC, INSTER_01_SPEC, HY_01, HY_02], CATALOGUE, REGISTRY + [REGISTRY_02_42], [], [])
        for c in self.cars:
            resolve_car(c, self.store)
        self.by = {c["id"]: c for c in self.cars}

    def test_cap_says_no_heat_pump_and_hyundai_says_fitted_is_a_disagreement(self):
        c = self.by["carwow-cap:110533"]
        self.assertEqual(c["heat_pump"], "unknown")
        self.assertNotIn("heat_pump", c["flags"])
        sides = c["disagreements"]["heat_pump"]
        self.assertEqual(len(sides), 2)
        self.assertTrue(any("[No Heat Pump]" in s and s.startswith("none") for s in sides), sides)
        self.assertTrue(any("Hyundai UK specification · 01" in s and s.startswith("standard") for s in sides), sides)

    def test_the_twin_without_the_bracket_takes_the_makers_word(self):
        c = self.by["carwow-cap:106644"]
        self.assertEqual((c["heat_pump"], c["field_sources"]["heat_pump"]), ("standard", "Hyundai UK specification · 01"))

    def test_a_49kwh_only_tick_speaks_at_trim_and_battery_level(self):
        both = self.by["carwow-cap:110534"]   # 02 42kWh [No Heat Pump]: CAP and Hyundai agree
        self.assertEqual(both["battery_kwh"], 42.0)
        self.assertEqual(both["heat_pump"], "none")
        self.assertNotIn("heat_pump", both.get("disagreements") or {})
        differ = self.by["carwow-cap:110532"]   # 02 49kWh [No Heat Pump]: Hyundai says the 49 has it
        self.assertEqual(differ["heat_pump"], "unknown")
        self.assertTrue(any("02 49 kWh" in s and "49kWh only" in s for s in differ["disagreements"]["heat_pump"]), differ["disagreements"])
        plain = self.by["carwow-cap:106646"]    # 02 49kWh, no bracket
        self.assertEqual(plain["heat_pump"], "standard")
        self.assertIn("02 49 kWh", plain["field_sources"]["heat_pump"])

    def test_a_dash_outranks_a_standard_list_and_a_pack_is_offered_with_its_price(self):
        c = self.by["carwow-cap:110532"]
        self.assertEqual((c["flags"]["heated_steering_wheel"], c["field_sources"]["heated_steering_wheel"]), ("standard", "Hyundai UK specification · 02"))
        self.assertEqual((c["flags"]["v2l_internal"], c["packs_required"]["internal_v2l"], c["pack_prices_gbp"]["Tech Pack"]), ("pack", "Tech Pack", 1000.0))
        self.assertEqual(c["flags"]["camera_360"], "pack")
        one = self.by["carwow-cap:110533"]
        self.assertEqual(one["flags"]["heated_steering_wheel"], "none", "a - in the maker's table")
        self.assertEqual(one["field_sources"]["heated_steering_wheel"], "Hyundai UK specification · 01")

    def test_a_dash_is_not_standard_so_a_pack_offered_on_the_trim_upgrades_it(self):
        kona = {"provider": "hyundai_specs", "source": "Hyundai UK specification", "make": "Hyundai", "model": "Kona Electric", "trim": "Advance", "batteries": [65.0],
                "features": ["LED Headlights"], "absent": ["Heated Front Seats", "Heated Steering Wheel", "Wireless Phone Charging Pad"], "qualified": [], "options": [],
                "packs": [{"name": "Comfort Pack", "price": 600.0, "items": ["Heated Front Seats", "Heated Steering Wheel", "Wireless Charger", "Privacy Glass"]}]}
        reg = [{"cap_id": "103322", "make": "Hyundai", "model": "Kona Electric", "make_slug": "hyundai", "model_slug": "kona-electric", "name": "160kW Advance 65kWh 5dr Auto", "trim": "Advance", "brackets": [], "rrp": 35000.0}]
        c = {"id": "carwow-cap:103322", "auto": True, "cap_id": "103322", "make": "Hyundai", "model": "Kona Electric", "trim": "Advance · 160kW 65kWh Auto", "variant": "160kW 65kWh Auto", "battery_kwh": 65.0}
        store = build_store([c], [kona], CATALOGUE, reg, [], [])
        resolve_car(c, store)
        self.assertEqual((c["flags"]["heated_front_seats"], c["packs_required"]["heated_front_seats"], c["pack_prices_gbp"]["Comfort Pack"]), ("pack", "Comfort Pack", 600.0))
        self.assertEqual(c["flags"]["wireless_charging"], "pack")
        self.assertEqual(c["flags"]["led_headlights"], "standard")
        self.assertNotIn("heated_front_seats", c.get("disagreements") or {})

    def test_a_grades_columns_that_differ_say_nothing_of_the_trim(self):
        kia = [{"provider": "kia_specs", "source": "Kia UK specification", "make": "Kia", "model": "EV3", "trim": "GT-Line S", "numbers": {"battery_kwh": 81.4},
                "features": [f"Item {i}" for i in range(45)] + ["Heated steering wheel"], "options": ["Heat pump"]},
               {"provider": "kia_specs", "source": "Kia UK specification", "make": "Kia", "model": "EV3", "trim": "GT-Line S Heat Pump", "numbers": {"battery_kwh": 81.4},
                "features": [f"Item {i}" for i in range(45)] + ["Heated steering wheel", "Heat Pump"], "options": []}]
        reg = [{"cap_id": "9001", "make": "Kia", "model": "EV3", "make_slug": "kia", "model_slug": "ev3", "name": "150kW GT-Line S 81kWh 5dr Auto [Heat Pump]", "trim": "GT-Line S", "brackets": ["Heat Pump"], "rrp": 43000.0},
               {"cap_id": "9002", "make": "Kia", "model": "EV3", "make_slug": "kia", "model_slug": "ev3", "name": "150kW GT-Line S 81kWh 5dr Auto", "trim": "GT-Line S", "brackets": [], "rrp": 42100.0}]
        cars = [{"id": "carwow-cap:9001", "auto": True, "cap_id": "9001", "make": "Kia", "model": "EV3", "trim": "GT-Line S · 150kW 81kWh Auto", "variant": "150kW 81kWh Auto", "battery_kwh": 81.4},
                {"id": "carwow-cap:9002", "auto": True, "cap_id": "9002", "make": "Kia", "model": "EV3", "trim": "GT-Line S · 150kW 81kWh Auto", "variant": "150kW 81kWh Auto", "battery_kwh": 81.4}]
        store = build_store(cars, kia, CATALOGUE, reg, [], [])
        for c in cars:
            resolve_car(c, store)
        self.assertEqual([c["heat_pump"] for c in cars], ["standard", "option"], "the bracket decides; Kia's two columns differ so the trim says nothing")
        self.assertIn("[Heat Pump]", cars[0]["field_sources"]["heat_pump"])
        self.assertEqual(cars[1]["field_sources"]["heat_pump"], "Kia UK specification · GT-Line S 81.4 kWh (its columns differ; the plainest says option)")
        self.assertEqual((cars[1]["flags"]["heated_steering_wheel"], cars[1]["field_sources"]["heated_steering_wheel"]), ("standard", "Kia UK specification · GT-Line S 81.4 kWh"))
        self.assertEqual((cars[1]["flags"]["glass_roof"], cars[1]["field_sources"]["glass_roof"]), ("none", "not in Kia UK specification · GT-Line S 81.4 kWh"), "a complete list without blanks of its own: not listed is not fitted, weakly")


class Configurator(unittest.TestCase):
    """Hyundai's own configurator, read from the saved Inster response: nine orderable configurations
    matched to CAP derivatives by trim, battery and price; what is in the price is fitted, what is
    offered is an extra, what the model sells elsewhere only is not available."""

    @classmethod
    def setUpClass(cls):
        import json
        from pathlib import Path
        from pipeline.providers import hyundai_configurator as hc
        d = json.loads((Path(__file__).parent / "fixtures" / "hyundai_configurator_inster.json").read_text())
        cls.cfg = hc.parse_payload(d, "inster", "Inster", "2026-10-08T12:00:00+00:00")
        reg = REGISTRY + [REGISTRY_02_42,
                          {"cap_id": "110535", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "85kW Cross 49kWh 5dr Auto [No Heat Pump]", "trim": "Cross", "engine": "85kW 49kWh Auto", "brackets": ["No Heat Pump"], "rrp": 28420.0},
                          {"cap_id": "106647", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "85kW Cross 49kWh 5dr Auto", "trim": "Cross", "engine": "85kW 49kWh Auto", "brackets": [], "rrp": 29245.0}]
        for r in reg:
            r.setdefault("engine", {"01": "71kW 42kWh Auto", "02": "85kW 49kWh Auto" if "49" in r["name"] else "71kW 42kWh Auto", "Cross": "85kW 49kWh Auto"}[r["trim"]])
        cls.cars = [car("110533", "01", "71kW 42kWh Auto"), car("106644", "01", "71kW 42kWh Auto", "stub"), car("110532", "02", "85kW 49kWh Auto"),
                    car("110534", "02", "71kW 42kWh Auto", "stub"), car("106646", "02", "85kW 49kWh Auto", "stub"), car("109120", "02", "85kW 49kWh Auto", "stub"),
                    car("110535", "Cross", "85kW 49kWh Auto", "stub"), car("106647", "Cross", "85kW 49kWh Auto", "stub")]
        cls.store = build_store(cls.cars, [INSTER_02_SPEC, INSTER_01_SPEC, HY_01, HY_02], CATALOGUE, reg, [], [], cls.cfg)
        for c in cls.cars:
            resolve_car(c, cls.store)
        cls.by = {c["id"]: c for c in cls.cars}

    def test_configurations_match_cap_derivatives_by_trim_battery_and_price(self):
        self.assertEqual(self.store.configured, {"110533": "6XS5ZDZ7ZSS182", "110532": "6XS5ZDZ7ZHH07V", "110534": "6XS5ZDZ7ZHH07Y", "106646": "6XS5ZDZ7ZHH07O",
                                                 "110535": "6XS5ZDZ7ZJJ834", "106647": "6XS5ZDZ7ZJJ835",
                                                 "109120": "6XS5ZDZ7ZHH597"})   # [Tech Pack] at another price: the only pairing whose brackets agree with the packages

    def test_the_configurator_settles_the_heat_pump_against_the_pdf_table(self):
        one = self.by["carwow-cap:110533"]   # 01 42kWh £22,995: Hyundai's table ticked it, CAP said no; the configurator sells no heat pump on 01 at all
        self.assertEqual(one["heat_pump"], "none")
        self.assertNotIn("heat_pump", one.get("disagreements") or {})
        self.assertIn("Hyundai UK configurator", one["field_sources"]["heat_pump"])
        self.assertIn("not offered on this trim", one["field_sources"]["heat_pump"])
        cross = self.by["carwow-cap:110535"]   # Cross £28,420: the heat pump is a £760 extra
        self.assertEqual((cross["heat_pump"], cross["packs_required"]["heat_pump"], cross["pack_prices_gbp"]["Heat Pump"]), ("pack", "Heat Pump", 760.0))
        self.assertTrue(any("Heat Pump (£760) is an extra, not in this price" in k.label for k in self.store.claims["derivative:110535"]))
        with_it = self.by["carwow-cap:106647"]   # Cross £29,245: in the price
        self.assertEqual((with_it["heat_pump"], with_it["field_sources"]["heat_pump"]), ("standard", "Hyundai UK configurator · Cross 49kWh Battery 115PS Motor £29,245 · Heat Pump in the price"))
        self.assertEqual(with_it["packs"], ["Heat Pump"])

    def test_the_02_49kwh_without_the_package_is_an_extra_and_the_tech_pack_gives_the_socket(self):
        c = self.by["carwow-cap:110532"]
        self.assertEqual((c["heat_pump"], c["pack_prices_gbp"]["Heat Pump"]), ("pack", 760.0))
        self.assertEqual((c["internal_v2l"], c["packs_required"]["internal_v2l"], c["pack_prices_gbp"]["Tech Pack"]), ("pack", "Tech Pack", 500.0))
        self.assertEqual(c["flags"]["three_pin_socket"], "pack")
        self.assertEqual(c["flags"]["digital_key"], "pack")
        self.assertEqual(c["list_price_gbp"], 26290.0)
        self.assertIn("Hyundai UK configurator", c["field_sources"]["list_price_gbp"])

    def test_no_tech_pack_on_01_or_cross_means_no_socket(self):
        for cid in ("carwow-cap:110533", "carwow-cap:110535"):
            c = self.by[cid]
            self.assertEqual(c["internal_v2l"], "none", cid)
            self.assertIn("Tech Pack", c["field_sources"]["internal_v2l"])
            self.assertNotIn("internal_v2l", c.get("disagreements") or {})

    def test_the_trims_standard_list_speaks_for_the_trim_as_a_list(self):
        c = self.by["carwow-cap:110534"]   # 02 42kWh
        self.assertEqual(c["flags"]["heated_front_seats"], "standard")
        self.assertTrue(c["field_sources"]["heated_front_seats"].endswith("02 standard equipment"))
        self.assertTrue(any(k.kind == "listed" and k.label == "Hyundai UK configurator · 02 standard equipment" for k in self.store.claims[claims.trim_subject("Hyundai", "Inster", "02")]))
        self.assertEqual(c["flags"]["led_headlights"], "standard")
        self.assertEqual(self.by["carwow-cap:110533"]["flags"]["heated_steering_wheel"], "none", "the 01 lists none; the PDF's dash stands")

    def test_what_the_configurator_overrules_stays_visible(self):
        one = self.by["carwow-cap:110533"]
        self.assertEqual(one["overruled"]["heat_pump"], ["standard (Hyundai UK specification · 01)"])
        self.assertNotIn("heated_steering_wheel", one["overruled"] or {})

    def test_an_unmatched_derivative_keeps_the_other_sources(self):
        c = self.by["carwow-cap:106644"]   # 01 42kWh £23,755: a MY26 price the configurator no longer sells
        self.assertNotIn("106644", self.store.configured)
        self.assertEqual(c["heat_pump"], "standard", "Hyundai's table and the [No …] twin rule still speak")


class BrokerEchoes(unittest.TestCase):
    def test_brokers_reprinting_a_cap_name_are_one_claim_with_sightings(self):
        reg = [{"cap_id": "110533", "make": "Hyundai", "model": "Inster", "make_slug": "hyundai", "model_slug": "inster", "name": "71kW 01 42kWh 5dr Auto [No Heat Pump]", "trim": "01", "brackets": ["No Heat Pump"], "rrp": 22995.0}]
        c = car("110533", "01", "71kW 42kWh Auto")
        brokers = [{"source": "leaseloco", "car_id": "carwow-cap:110533", "label": "Hyundai Inster 71kW 01 42kWh 5dr Auto [No Heat Pump]"},
                   {"source": "ncd", "car_id": "carwow-cap:110533", "label": "INSTER ELECTRIC HATCHBACK 71kW 01 42kWh 5dr Auto [No Heat Pump]"}]
        store = build_store([c], [HY_01], CATALOGUE, reg, [], brokers)
        named = [k for k in store.claims["derivative:110533"] if k.kind == "named"]
        self.assertEqual(len(named), 1)
        self.assertEqual(named[0].label, "CAP derivative name · 71kW 01 42kWh 5dr Auto [No Heat Pump] (seen on Carwow, LeaseLoco, New Car Discount)")
        resolve_car(c, store)
        self.assertEqual(c["disagreements"]["heat_pump"], ["none (CAP derivative name · 71kW 01 42kWh 5dr Auto [No Heat Pump] (seen on Carwow, LeaseLoco, New Car Discount))",
                                                             "standard (Hyundai UK specification · 01)"])


class Wheels(unittest.TestCase):
    def test_the_configurators_fitted_wheels_beat_the_standard_list_and_the_rest_are_options(self):
        spec = {"provider": "carwow_specs", "cap_id": "5", "make": "Hyundai", "model": "Inster", "trim": "02", "engine": "85kW 49kWh Auto", "variant": "Inster 02",
                "features": ['17" alloy wheels', "Heated steering wheel"], "numbers": {},
                "raw_numbers": {"Top speed": "93 mph", "Consumption": "4.1 miles/kWh"}}
        options = [{"cap_id": "5", "options": [{"name": '17" alloy wheels', "default": True, "price": 0},
                                               {"name": '18" diamond-cut alloy wheels', "default": False, "price": 500}]}]
        c = {"id": "carwow-cap:5", "auto": True, "cap_id": "5", "make": "Hyundai", "model": "Inster", "trim": "02 · 85kW 49kWh Auto", "variant": "85kW 49kWh Auto"}
        resolve_car(c, build_store([c], [spec], CATALOGUE, [], options, []))
        self.assertEqual((c["wheel_in"], c["wheel_options"]), (17, '18"'))
        self.assertIn("configurator", c["field_sources"]["wheel_in"])
        self.assertEqual((c["top_speed_mph"], c["efficiency_mi_kwh"]), (93.0, 4.1), "numbers the old parse left as text")

    def test_a_list_naming_two_sizes_says_nothing(self):
        spec = {"provider": "carwow_specs", "cap_id": "6", "make": "Hyundai", "model": "Inster", "trim": "01", "engine": "71kW 42kWh Auto", "variant": "Inster 01",
                "features": ['15" steel wheels (42kWh)', '17" alloy wheels (49kWh)'], "numbers": {}}
        c = {"id": "carwow-cap:6", "auto": True, "cap_id": "6", "make": "Hyundai", "model": "Inster", "trim": "01 · 71kW 42kWh Auto", "variant": "71kW 42kWh Auto"}
        resolve_car(c, build_store([c], [spec], CATALOGUE, [], [], []))
        self.assertIsNone(c.get("wheel_in"))
