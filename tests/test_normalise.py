"""One reading of every source's text (pipeline/normalise.py): accents, punctuation, CAP's short forms, makes,
units; and, over every derivative name the fixtures hold, that no two different names of one model read alike."""
import re
import unittest
from collections import defaultdict
from pathlib import Path

from pipeline import normalise as N
from pipeline.providers import carwow_deals, carwow_model, leaseloco, ncd, parkers
from pipeline.providers.types import Target
from pipeline.services import facts, match, resolve

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-16T00:00:00+00:00"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


class Reading(unittest.TestCase):
    def test_accents_and_case(self):
        self.assertEqual(N.fold("Škoda Citroën"), "skoda citroen")
        self.assertEqual(N.compact("Škoda"), N.compact("SKODA"))
        self.assertEqual(N.compact("ProPILOT™ Assist"), "propilotassist")

    def test_punctuation_is_read_alike_and_the_plus_stays(self):
        self.assertEqual(N.words("GT-Line S"), N.words("GT Line S"))
        self.assertEqual(N.words("Techno +"), ["techno+"])
        self.assertNotEqual(N.words("Techno+"), N.words("Techno"))

    def test_cap_short_forms_read_as_the_long_ones(self):
        same = [("250kW eDr40 M Sport", "250kW eDrive40 M Sport"), ("370kW S6 Qtro 100kWh", "370kW S6 Quattro 100kWh"),
                ("Black Ed", "Black Edition"), ("Tech+/Comf+", "Tech+ Comfort+"), ("185kW Ext Range Plus", "185kW Extended Range Plus"),
                ("[Ext+ Pan]", "[Exterior+ Pan]"), ("350kW 82kWh LR DM", "350kW 82kWh Long Range Dual Motor")]
        for short, long in same:
            self.assertEqual(N.name_words(short), N.name_words(long), short)
        self.assertEqual(N.name_words("350 4M AMG Line", "Mercedes-Benz"), N.name_words("350 4MATIC AMG Line", "Mercedes"))
        self.assertEqual(N.name_words("210kW 4M Match Pro", "Volkswagen"), N.name_words("210kW 4MOTION Match Pro", "Volkswagen"))
        self.assertEqual(N.name_words("210kW 4M Match Pro"), ["210kw", "4m", "match", "pro"])   # no make, no guess
        self.assertEqual(N.name_words("Edrive40"), ["edrive40"])   # a whole word only

    def test_the_words_that_tell_versions_apart_are_kept(self):
        ws = N.name_words("250kW Long Range AWD Performance 82kWh 5dr Auto [Heat Pump] [7 Seat]")
        for w in ("250kw", "long", "range", "awd", "performance", "82kwh", "heat", "pump", "7", "seat"):
            self.assertIn(w, ws)

    def test_makes_and_their_aliases(self):
        self.assertEqual(N.make_key("Mercedes-Benz"), N.make_key("mercedes"))
        self.assertEqual(N.make_key("SsangYong"), N.make_key("kgm-motors"))
        self.assertTrue(N.same_make("Škoda", {"make": "skoda", "make_name": "Skoda"}))
        self.assertFalse(N.same_make("", {"make": "skoda", "make_name": "Skoda"}))

    def test_units(self):
        self.assertEqual((N.kw("150kW GT-Line S 81.4kWh"), N.kwh("150kW GT-Line S 81.4kWh")), (150, 81.4))
        self.assertEqual(N.kwhs("● 63kWh, 84 kWh"), [63.0, 84.0])
        self.assertEqual((N.ps("160kW (218PS) RWD"), N.bhp("AWD Dual Motor 320 BHP")), (218, 320))
        self.assertIsNone(N.kw("77kWh"))
        self.assertAlmostEqual(N.km_to_miles(1.609344), 1.0)

    def test_record_keys_are_identities_and_never_change(self):
        self.assertEqual(N.key("Škoda", "Enyaq", "85 Edition 82 kWh"), "škoda|enyaq|85 edition 82kwh")
        self.assertEqual(N.slug("GT-Line S"), "gt-line-s")


class Matching(unittest.TestCase):
    def test_ev_database_s_skoda_and_citroen_variants_file_under_the_catalogue(self):
        catalogue = [{"slug": "skoda/enyaq", "make": "skoda", "model": "enyaq", "make_name": "Skoda", "model_name": "Enyaq"},
                     {"slug": "citroen/e-c4", "make": "citroen", "model": "e-c4", "make_name": "Citroen", "model_name": "e-C4"}]
        self.assertEqual(facts.model_of("Škoda", "Enyaq 85", catalogue)["slug"], "skoda/enyaq")
        self.assertEqual(facts.model_of("Citroën", "e-C4 54 kWh", catalogue)["slug"], "citroen/e-c4")

    def test_a_trim_printed_with_or_without_its_hyphen_is_one_trim(self):
        car = {"id": "c", "make": "Kia", "trim": "GT-Line S · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto"}
        self.assertIsNotNone(match.score("150kW GT Line S 81.4kWh 5dr Auto", car))

    def test_an_exact_cap_name_is_taken_before_any_reading(self):
        name = "150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]"
        named = {"id": "carwow-cap:1", "make": "Kia", "trim": "GT-Line S · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto",
                 "list_price_gbp": 45000.0, "cap_name": name}
        twin = {**named, "id": "carwow-cap:2", "list_price_gbp": 46000.0, "cap_name": "150kW GT-Line S 81.4kWh 5dr Auto"}
        # Read alike, the bracket rule would take the dearer twin; the name as printed says which it is.
        self.assertEqual(resolve.choose({"derivative": name}, [named, twin]).car_id, "carwow-cap:1")
        self.assertEqual(resolve.choose({"derivative": "150kW GT Line S 81.4kWh 5dr Auto [Heat Pump]"}, [named, twin]).car_id,
                         "carwow-cap:2")
        # LeaseLoco's reader appends the seat count; what LeaseLoco printed is the name before it.
        self.assertEqual(resolve.choose({"derivative": name + " [5 seat]"}, [named, twin]).car_id, "carwow-cap:1")

    def test_a_pin_under_the_name_as_printed_comes_first(self):
        name = "150kW GT-Line S 81.4kWh 5dr Auto"
        a = {"id": "carwow-cap:1", "make": "Kia", "trim": "GT-Line S · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto",
             "list_price_gbp": 45000.0}
        b = {**a, "id": "carwow-cap:2", "list_price_gbp": 46000.0}
        exact, alike = resolve.pin_keys(name)
        pins = {exact: {"carwow-cap:2"}, alike: {"carwow-cap:1", "carwow-cap:2"}}
        self.assertEqual(resolve.choose({"derivative": name}, [a, b], pins).method, "name")
        self.assertEqual(resolve.choose({"derivative": name}, [a, b], pins).car_id, "carwow-cap:2")


def fixture_names() -> dict[tuple, set[str]]:
    """(source, make, model) → every derivative name the fixtures print for it."""
    out: dict[tuple, set[str]] = defaultdict(set)
    for r in carwow_model.parse_page(fixture("carwow_hyundai_inster_model.html"), "hyundai", "inster", "u", T):
        out["carwow registry", "hyundai", "inster"].add(r["name"])
    for f, mk, mo in (("carwow_hyundai_ioniq-3_deals.html", "hyundai", "ioniq-3"), ("carwow_kia_ev3_deals.html", "kia", "ev3"),
                      ("carwow_hyundai_ioniq-5_deals.html", "hyundai", "ioniq-5")):
        for r in carwow_deals.parse_page(fixture(f), mk, mo, "u", T):
            stub = (r.get("car_ref") or {}).get("stub") or {}
            if stub:
                out["carwow deals", mk, mo].add(f"{stub.get('trim')} {stub.get('engine')}")
    for f in ("leaseloco_hyundai_kona-electric.html", "leaseloco_hyundai_kona-electric_2026-10-11.html"):
        for r in leaseloco.parse_page(fixture(f), "u", T):
            ref = r["car_ref"]
            out["leaseloco", N.make_key(ref["make"]), N.compact(ref["model"])].add(ref["derivative"])
    for f, mk in (("ncd_hyundai_ioniq-3_listing.html", "hyundai"), ("ncd_kia_ev6_4x4_listing.html", "kia"),
                  ("ncd_kia_ev6_estate_listing.html", "kia")):
        for r in ncd.parse_page(fixture(f), mk, "u", T):
            ref = r["car_ref"]
            out["ncd", mk, N.compact(ref["model"])].add(ref["derivative"])
    sitemap = (FIX / "parkers_sitemap_slice.xml").read_bytes()
    for rec in parkers.parse_sitemap(sitemap, Target("spec-1", {"url": "u", "observed_at": T})):
        if rec.row["entry"] == "derivative":
            out["parkers sitemap", rec.row["make_slug"], rec.row["model_slug"]].add(rec.row["slug"])
    for name in ("150kw-ultimate-64kwh-5dr-auto", "premium-se-64-kwh-battery-204ps-auto-5d"):
        row = parkers.parse_page(fixture(f"parkers_kona-electric_suv-2018_{name}.html"), {"make_slug": "hyundai", "model_slug": "kona-electric"}, T)
        out["parkers", "hyundai", "kona-electric"].add(row["name"])
    return out


SHORT_WORDS = {re.sub(r"\(.*", "", short).split()[0] for short, *_ in N.SHORT_FORMS}


class Collisions(unittest.TestCase):
    """Two different names of one model must never read as one: names that differ in more than case, accents,
    punctuation or a listed CAP short form keep different keys, and no word of a name is dropped."""

    def test_no_two_derivative_names_of_one_model_read_alike(self):
        names = fixture_names()
        self.assertGreater(sum(len(v) for v in names.values()), 60)
        for (source, make, model), printed in names.items():
            by_key: dict[str, set[str]] = defaultdict(set)
            for n in printed:
                by_key[" ".join(N.name_words(n, make))].add(n)
            for key, same in by_key.items():
                self.assertEqual(len({N.compact(n) for n in same}), 1, f"{source} {make}/{model}: {sorted(same)} all read as {key!r}")

    def test_no_word_of_a_derivative_name_is_dropped(self):
        for (source, make, model), printed in fixture_names().items():
            for n in printed:
                kept = set(N.name_words(n, make))
                for w in N.words(n):
                    if w.rstrip("+") not in SHORT_WORDS and not re.fullmatch(r"(edr|xdr|dir)\d*\+?", w):
                        self.assertIn(w, kept, f"{source} {make}/{model}: {n!r} lost {w!r}")
