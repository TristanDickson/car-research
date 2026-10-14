"""ADAC Autotest, against car pages captured on 2026-10-13 (no network).

adac_hyundai_kona_329429 is the page of the Kona Elektro (65 kWh) Prime-Paket ADAC tested in December
2023, which also carries the breakdown statistics of every Kona; adac_kia_pv5_340739 the PV5 Passenger
(71,2 kWh) Elite tested in July 2026, a model too new for breakdown statistics; adac_range_hyundai_ioniq-5
the Ioniq 5's range page, whose statistics are the first generation's (the facelift's test page has none).

The test PDFs, as poppler's pdftotext -layout reads them: adac_pdf_at6366_hyundai_kona (December 2023, the
layout of 2019 to 2025), adac_pdf_at6641_kia_ev2 (August 2026, the two-column layout with wrapped labels),
and adac_pdf_at5861_bmw_i3 (August 2019, before the electric-drive page with the charging figures).
"""
import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pipeline.providers import adac
from pipeline.providers.types import Context, Target
from pipeline.services import claims

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-13T03:00:00+00:00"
KONA = "hyundai/kona-electric"
CATALOGUE = [{"slug": KONA, "make": "hyundai", "model": "kona-electric", "make_name": "Hyundai", "model_name": "Kona Electric"},
             {"slug": "kia/pv5-passenger", "make": "kia", "model": "pv5-passenger", "make_name": "Kia", "model_name": "PV5 Passenger"}]


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def kona() -> dict:
    return adac.parse_page(page("adac_hyundai_kona_329429_2026-10-13.html"), KONA, adac.BASE + adac.TESTS[KONA] + "/", T)


class ParsePage(unittest.TestCase):
    def test_the_kona_test_and_breakdowns(self):
        r = kona()
        self.assertEqual(r["spec_key"], "adac:hyundai/kona-electric")
        self.assertEqual(r["numbers"], {"adac_suspension": 2.5, "adac_comfort": 2.4, "adac_build": 3.6, "adac_boot": 2.6, "adac_rear_space": 2.3,
                                        "adac_total": 2, "adac_family": 2.7, "adac_tested": "Kona Elektro (65 kWh) Prime-Paket, 12/2023",
                                        "adac_breakdowns": 6.1, "adac_breakdown_year": 2023, "adac_breakdown_rating": "satisfactory",
                                        "adac_breakdown_causes": "12-volt battery (2018-2021, 2023); ignition coil (2018)"})
        self.assertEqual(r["grades"]["Komfort"]["subs"]["Federung"], 2.5)
        self.assertEqual(r["breakdowns"]["name"], "Hyundai Kona")
        self.assertEqual(r["breakdowns"]["years"][:2], [{"year": 2023, "per_1000": 6.1, "grade": 3}, {"year": 2022, "per_1000": 6.6, "grade": 2}])
        self.assertEqual(r["breakdowns"]["defects"][0], {"name": "Starterbatterie", "years": "2018-2021, 2023"})
        # Every test of the generation, the petrol and hybrid Konas among them: a newer electric one would show here.
        self.assertEqual([t["id"] for t in r["range_tests"]], ["6341", "6393", "6366"])
        self.assertIn("einfache Materialien im Innenraum", r["test"]["weaknesses"])

    def test_a_model_too_new_for_breakdown_statistics(self):
        r = adac.parse_page(page("adac_kia_pv5_340739_2026-10-13.html"), "kia/pv5-passenger", "u", T)
        self.assertEqual((r["numbers"]["adac_rear_space"], r["numbers"]["adac_boot"], r["numbers"]["adac_build"]), (0.9, 0.6, 3.1))
        self.assertNotIn("adac_breakdowns", r["numbers"])
        self.assertNotIn("breakdowns", r)

    def test_a_page_without_its_data(self):
        with self.assertRaises(ValueError):
            adac.parse_page("<html><body>maintenance</body></html>", KONA, "u", T)
        self.assertIsNone(adac.parse_page('<script>window.__APOLLO_STATE__ = {"ROOT_QUERY": {}};</script>', KONA, "u", T))


class RangePage(unittest.TestCase):
    def test_the_ioniq5s_breakdowns(self):
        r = adac.parse_range_page(page("adac_range_hyundai_ioniq-5_2026-10-13.html"), "hyundai/ioniq-5", "u", T)
        self.assertEqual(r["spec_key"], "adac:breakdowns:hyundai/ioniq-5")
        self.assertEqual(r["numbers"], {"adac_breakdowns": 19.5, "adac_breakdown_year": 2023, "adac_breakdown_rating": "poor",
                                        "adac_breakdown_causes": "general electrics (2022-2023); 12-volt battery (2021-2023)"})
        self.assertEqual(r["breakdowns"]["years"], [{"year": 2023, "per_1000": 19.5, "grade": 5}, {"year": 2022, "per_1000": 28.2, "grade": 5}])
        self.assertEqual([d["name"] for d in r["breakdowns"]["defects"]], ["Fahrzeugelektrik allgemein", "Starterbatterie"])

    def test_one_range_page_for_a_model_and_its_n(self):
        (t,) = adac.discover_ranges(Target("hyundai/ioniq-5"), Context(root=FIX))
        self.assertEqual((t.identifier, t.metadata["models"]), ("hyundai/ioniq-5", ["hyundai/ioniq-5", "hyundai/ioniq-5-n"]))

    def test_the_range_pages_statistics_win(self):
        test = kona()
        ranged = {"spec_key": "adac:breakdowns:hyundai/kona-electric", "model_slug": KONA, "breakdowns": {"name": "Hyundai Kona"},
                  "numbers": {"adac_breakdowns": 5.0, "adac_breakdown_year": 2023, "adac_breakdown_rating": "good"}}
        store = claims.Store()
        claims.from_adac(store, [test, ranged], CATALOGUE)
        car = {"id": "c", "make": "Hyundai", "model": "Kona Electric", "trim": "Ultimate", "auto": True}
        claims.resolve_car(car, store)
        self.assertEqual((car["adac_breakdowns"], car["adac_breakdown_rating"], car["adac_build"]), (5.0, "good", 3.6))


class Discover(unittest.TestCase):
    def specs(self, seen: dict[str, str]) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE specs (spec_key TEXT, source TEXT, last_seen_at TEXT)")
        conn.executemany("INSERT INTO specs VALUES (?, 'adac', ?)", [(f"adac:{k}", v) for k, v in seen.items()])
        return conn

    def test_never_read_first_then_the_stalest(self):
        slugs = list(adac.TESTS)
        seen = {s: "2026-10-12T03:00:00+00:00" for s in slugs}   # all read yesterday ...
        seen.update({f"breakdowns:{s}": "2026-01-01T00:00:00+00:00" for s in slugs})   # the range pages are another capability's
        seen[slugs[3]] = "2026-01-01T03:00:00+00:00"              # ... but one long ago
        seen[slugs[1]] = "2025-12-01T03:00:00+00:00"              # and one longer ago still
        del seen[slugs[5]]                                         # and one never
        ctx = Context(root=FIX, extras={"db": self.specs(seen)})
        got = [t.metadata["models"] for t in adac.discover(Target("all"), ctx)]
        self.assertEqual([[s for s in m if s in (slugs[5], slugs[1], slugs[3])] for m in got], [[slugs[5]], [slugs[1]], [slugs[3]]])

    def test_a_first_run_reads_a_batch_the_households_models_first(self):
        conn = self.specs({})
        conn.execute("CREATE TABLE cars (payload TEXT)")
        conn.execute("CREATE TABLE models (slug TEXT, make_name TEXT, model_name TEXT)")
        conn.execute("""INSERT INTO cars VALUES ('{"make": "Kia", "model": "PV5 Passenger"}'), ('{"make": "Kia", "model": "EV3", "auto": true}')""")
        conn.executemany("INSERT INTO models VALUES (?, ?, ?)", [("kia/pv5-passenger", "Kia", "PV5 Passenger"), ("kia/ev3", "Kia", "EV3")])
        got = list(adac.discover(Target("all"), Context(root=FIX, extras={"db": conn})))
        self.assertEqual(len(got), adac.PER_RUN)
        self.assertEqual(got[0].metadata["models"], ["kia/pv5-passenger"])   # the owner entered one; the EV3 is only a generated car
        self.assertEqual((got[0].identifier, got[0].metadata["url"]), (adac.TESTS["kia/pv5-passenger"], adac.BASE + adac.TESTS["kia/pv5-passenger"] + "/"))
        self.assertEqual(len({t.identifier for t in got}), len(got))

    def test_one_model_on_demand(self):
        got = list(adac.discover(Target(KONA), Context(root=FIX)))
        self.assertEqual([(t.identifier, t.metadata["url"], t.metadata["models"]) for t in got],
                         [("hyundai/kona/2generation/329429", adac.BASE + "hyundai/kona/2generation/329429/", [KONA])])

    def test_a_page_several_models_read_is_fetched_once(self):
        enyaq = adac.TESTS["skoda/enyaq"]
        (t,) = adac.discover(Target(enyaq), Context(root=FIX))
        self.assertEqual(t.metadata["models"], ["skoda/enyaq", "skoda/enyaq-coupe", "skoda/enyaq-coupe-vrs", "skoda/enyaq-vrs"])
        rows = list(adac.parse((FIX / "adac_hyundai_kona_329429_2026-10-13.html").read_bytes(), Target(KONA, {"url": "u", "models": [KONA, "x/y"]})))
        self.assertEqual([r.key for r in rows], ["adac:hyundai/kona-electric", "adac:x/y"])

    def test_the_test_table(self):
        for slug, path in adac.TESTS.items():
            self.assertRegex(path, r"^[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+/\d+$", slug)
        # An N reads the N's test, its base model the other one.
        self.assertNotEqual(adac.TESTS["hyundai/ioniq-5"], adac.TESTS["hyundai/ioniq-5-n"])


class Claims(unittest.TestCase):
    def test_said_of_the_model(self):
        store = claims.Store()
        claims.from_adac(store, [kona()], CATALOGUE)
        car = {"id": "c", "make": "Hyundai", "model": "Kona Electric", "trim": "Ultimate", "auto": True}
        claims.resolve_car(car, store)
        self.assertEqual((car["adac_suspension"], car["adac_build"], car["adac_breakdowns"], car["adac_breakdown_rating"]), (2.5, 3.6, 6.1, "satisfactory"))
        self.assertEqual(car["field_sources"]["adac_suspension"], "ADAC Autotest · Kona Elektro (65 kWh) Prime-Paket, 12/2023")
        self.assertIn("every powertrain", car["field_sources"]["adac_breakdowns"])

    def test_a_model_not_in_the_catalogue_is_left(self):
        store = claims.Store()
        claims.from_adac(store, [dict(kona(), model_slug="hyundai/gone")], CATALOGUE)
        self.assertEqual(store.count(), 0)


KONA_TEST = {"id": "6366", "date": "12/2023", "model": "Kona Elektro (65 kWh) Prime-Paket",
             "document": "at6366-hyundai-kona-elektro-654-kwh-prime-paket/hyundai-kona-elektro-654-kwh-prime-paket.pdf"}


def pdf_row(name: str, model: str = KONA, test: dict = KONA_TEST) -> dict:
    return adac.parse_pdf_text(page(name), model, adac.ASSETS + test["document"], T, test)


class ParsePdf(unittest.TestCase):
    def test_the_kona_pdf(self):
        r = pdf_row("adac_pdf_at6366_hyundai_kona.txt")
        self.assertEqual(r["spec_key"], "adac:pdf:hyundai/kona-electric")
        self.assertEqual(r["numbers"], {
            "adac_tyres_tested": "235/45 R19 99V, Nexen N Fera Sport", "adac_boot_measured_l": 350, "adac_boot_max_measured_l": 1320,
            "adac_braking_100_m": 35.7, "adac_noise_130_db": 67.6, "adac_60_100_s": 3.7, "adac_width_mirrors_mm": 2110,
            "adac_weight_kg": 1762, "adac_payload_kg": 458, "adac_dc_10_80_min": 39, "adac_dc_avg_kw": 85.1, "adac_full_charge_kwh": 77.3,
            "adac_turning_circle_m": 10.4, "adac_ecotest_range_mi": 255, "adac_ecotest_mi_kwh": 3.31})
        p = r["printed"]
        self.assertEqual((p["turning_circle_m"], p["range_km"], p["consumption_kwh_100km"], p["cycle"]), ([10.4, 10.3], 410, 18.8, "Ecotest"))
        self.assertEqual((p["boot_folded_l"], p["price_tested_eur"]), (775, 55290))
        self.assertEqual(r["test"]["id"], "6366")

    def test_the_2026_layout(self):
        # Two columns, 'Kofferraum normal' and 'Fahrzeugbreite' wrapped onto a second line, one turning circle,
        # 'Autotest-Verbrauch' for Ecotest, a charge time as hh:mm.
        r = pdf_row("adac_pdf_at6641_kia_ev2.txt", "kia/ev2", {"id": "6641", "date": "08/2026", "model": "EV2 (42,2 kWh) Earth", "document": "d.pdf"})
        self.assertEqual(r["numbers"], {
            "adac_tyres_tested": "205/65 R16 95H, Hankook iON GT EV", "adac_boot_measured_l": 315, "adac_boot_max_measured_l": 1140,
            "adac_braking_100_m": 36.3, "adac_noise_130_db": 65.4, "adac_60_100_s": 4.8, "adac_width_mirrors_mm": 2060,
            "adac_weight_kg": 1584, "adac_payload_kg": 506, "adac_dc_10_80_min": 28, "adac_dc_avg_kw": 64.5, "adac_full_charge_kwh": 46.1,
            "adac_turning_circle_m": 11.7, "adac_ecotest_range_mi": 152, "adac_ecotest_mi_kwh": 3.31})
        self.assertEqual((r["printed"]["cycle"], r["printed"]["overtake_80_120_s"], r["printed"]["boot_folded_l"]), ("Autotest", 6.4, 660))

    def test_a_test_without_the_electric_drive_page(self):
        r = pdf_row("adac_pdf_at5861_bmw_i3.txt", "bmw/i3", {"id": "5861", "date": "08/2019", "model": "i3 (120 Ah)", "document": "d.pdf"})
        self.assertEqual((r["numbers"]["adac_tyres_tested"], r["numbers"]["adac_turning_circle_m"], r["numbers"]["adac_boot_measured_l"]),
                         ("155/70 R19 84Q, Brigdestone Ecopia EP 500", 10.0, 205))
        for f in ("adac_dc_10_80_min", "adac_dc_avg_kw", "adac_full_charge_kwh"):
            self.assertNotIn(f, r["numbers"])

    def test_a_pdf_without_the_block(self):
        self.assertIsNone(adac.parse_pdf_text("Autotest\n\nno measurements here\n", KONA, "u", T, KONA_TEST))

    def test_one_pdf_for_every_model_that_reads_the_test(self):
        text = page("adac_pdf_at6366_hyundai_kona.txt")
        with mock.patch.object(adac, "pdf_text", return_value=text):
            rows = list(adac.parse_pdfs(b"%PDF", Target("d", {"url": "u", "models": [KONA, "x/y"], "test": KONA_TEST})))
        self.assertEqual([r.key for r in rows], ["adac:pdf:hyundai/kona-electric", "adac:pdf:x/y"])


class DiscoverPdfs(unittest.TestCase):
    def db(self, rows: list[tuple[str, dict, str]]) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE specs (spec_key TEXT, source TEXT, payload TEXT, last_seen_at TEXT)")
        conn.executemany("INSERT INTO specs VALUES (?, 'adac', ?, ?)", [(k, json.dumps(p), at) for k, p, at in rows])
        return conn

    def page_row(self, slug: str, test: dict, at: str = T) -> tuple[str, dict, str]:
        return (f"adac:{slug}", {"model_slug": slug, "source_url": adac.BASE + adac.TESTS[slug] + "/", "test": test}, at)

    def test_the_pdf_of_each_test_read(self):
        ev3 = {"id": "6480", "date": "06/2025", "model": "EV3", "document": "at6480/ev3.pdf"}
        enyaq = {"id": "6505", "date": "x", "model": "Enyaq", "document": "at6505/enyaq.pdf"}
        conn = self.db([self.page_row(KONA, KONA_TEST), self.page_row("kia/ev3", ev3), self.page_row("skoda/enyaq", enyaq),
                        self.page_row("skoda/enyaq-coupe", enyaq),
                        # read long ago, and of this test: due again
                        (f"adac:pdf:{KONA}", {"model_slug": KONA, "test": KONA_TEST}, "2026-01-01T00:00:00+00:00"),
                        # read yesterday, but of the EV3's previous test: the new test's PDF is never read
                        ("adac:pdf:kia/ev3", {"model_slug": "kia/ev3", "test": {"id": "6000"}}, T),
                        ("adac:breakdowns:kia/ev3", {"model_slug": "kia/ev3", "source_url": "r"}, T)])
        got = list(adac.discover_pdfs(Target("all"), Context(root=FIX, extras={"db": conn})))
        self.assertEqual([(t.identifier, t.metadata["models"]) for t in got],
                         [("at6480/ev3.pdf", ["kia/ev3"]), ("at6505/enyaq.pdf", ["skoda/enyaq", "skoda/enyaq-coupe"]),
                          (KONA_TEST["document"], [KONA])])
        self.assertEqual((got[0].metadata["url"], got[0].metadata["test"]), (adac.ASSETS + "at6480/ev3.pdf", ev3))

    def test_a_pdf_read_lately_waits(self):
        lately = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        conn = self.db([self.page_row(KONA, KONA_TEST), (f"adac:pdf:{KONA}", {"model_slug": KONA, "test": KONA_TEST}, lately)])
        self.assertEqual(list(adac.discover_pdfs(Target("all"), Context(root=FIX, extras={"db": conn}))), [])
        (t,) = adac.discover_pdfs(Target(KONA), Context(root=FIX, extras={"db": conn}))   # unless asked for
        self.assertEqual(t.identifier, KONA_TEST["document"])

    def test_a_test_page_tests_no_longer_names_is_left(self):
        conn = self.db([(f"adac:{KONA}", {"model_slug": KONA, "source_url": adac.BASE + "hyundai/kona/1generation/1/", "test": KONA_TEST}, T)])
        self.assertEqual(list(adac.discover_pdfs(Target("all"), Context(root=FIX, extras={"db": conn}))), [])

    def test_no_database_no_targets(self):
        self.assertEqual(list(adac.discover_pdfs(Target("all"), Context(root=FIX))), [])


class PdfClaims(unittest.TestCase):
    def resolve(self, rows: list[dict]) -> dict:
        store = claims.Store()
        claims.from_adac(store, rows, CATALOGUE)
        car = {"id": "c", "make": "Hyundai", "model": "Kona Electric", "trim": "Ultimate", "auto": True}
        claims.resolve_car(car, store)
        return car

    def test_said_of_the_model_with_the_test_named(self):
        car = self.resolve([kona(), pdf_row("adac_pdf_at6366_hyundai_kona.txt")])
        self.assertEqual((car["adac_tyres_tested"], car["adac_braking_100_m"], car["adac_ecotest_range_mi"], car["adac_dc_10_80_min"]),
                         ("235/45 R19 99V, Nexen N Fera Sport", 35.7, 255, 39))
        src = car["field_sources"]
        self.assertEqual(src["adac_braking_100_m"], "ADAC Autotest · Kona Elektro (65 kWh) Prime-Paket, 12/2023 · ADAC's measurement")
        self.assertIn("Ecotest range 410 km, converted to miles", src["adac_ecotest_range_mi"])
        self.assertIn("10.4 m and 10.3 m (left and right), the larger", src["adac_turning_circle_m"])
        # The ride grade names the tyres it was given on.
        self.assertEqual(src["adac_suspension"], "ADAC Autotest · Kona Elektro (65 kWh) Prime-Paket, 12/2023 · on 235/45 R19 99V, Nexen N Fera Sport")

    def test_a_pdf_of_another_test_is_not_said(self):
        old = pdf_row("adac_pdf_at6366_hyundai_kona.txt", test=dict(KONA_TEST, id="6000"))
        car = self.resolve([kona(), old])
        self.assertNotIn("adac_braking_100_m", car)
        self.assertEqual(car["field_sources"]["adac_suspension"], "ADAC Autotest · Kona Elektro (65 kWh) Prime-Paket, 12/2023")


class ThroughTheBuild(unittest.TestCase):
    def test_the_pdf_becomes_a_spec_row(self):
        from tests.helpers import Raws
        text = page("adac_pdf_at6366_hyundai_kona.txt")
        with Raws() as raws, mock.patch.object(adac, "pdf_text", return_value=text):
            raws.add("adac", KONA_TEST["document"], body=b"%PDF-1.7", capability="pdf", at=T,
                     metadata={"url": adac.ASSETS + KONA_TEST["document"], "models": [KONA], "test": KONA_TEST})
            conn = raws.build()
        payload = json.loads(conn.execute("SELECT payload FROM specs WHERE spec_key='adac:pdf:hyundai/kona-electric'").fetchone()[0])
        self.assertEqual((payload["numbers"]["adac_noise_130_db"], payload["test"]["id"]), (67.6, "6366"))

    def test_the_page_becomes_a_spec_row(self):
        from tests.helpers import Raws
        with Raws() as raws:
            raws.add("adac", adac.TESTS[KONA], "adac_hyundai_kona_329429_2026-10-13.html", at=T, metadata={"url": adac.BASE + adac.TESTS[KONA] + "/", "models": [KONA]})
            conn = raws.build()
        row = conn.execute("SELECT source, car_id FROM specs WHERE spec_key='adac:hyundai/kona-electric'").fetchone()
        self.assertEqual(tuple(row), ("adac", None))


if __name__ == "__main__":
    unittest.main()
