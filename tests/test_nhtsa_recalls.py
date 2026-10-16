"""NHTSA's US safety recalls, against 65 lines cut byte for byte from FLAT_RCL_POST_2010.txt as downloaded on
2026-10-14 (the whole file is 15 MB zipped, 311 MB of text): Hyundai's ICCU recall 24V-204 and the 24V-868 that
replaced it, a driveshaft recall shared with the Ioniq 6 and GV60, the Ioniq 5 N's braking recall and its
replacement, the I-Pace battery recalls, a Tesla recall superseded by another, two EQS 450 recalls shared with the
S-Class, a Mach-E recall shared with the Maverick, and lines that are not read: a petrol Kona, a 2021 C-HR, a 2017
Ioniq Electric, an equipment recall and a trailer.
"""
import io
import sqlite3
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pipeline.providers import nhtsa_recalls
from pipeline.providers.types import Context, Fetched, Target
from pipeline.services import claims

FIX = Path(__file__).parent / "fixtures" / "nhtsa_recalls_2026-10-14.txt"


def zipped() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("FLAT_RCL_POST_2010.txt", FIX.read_bytes())
    return buf.getvalue()


def row() -> dict:
    (rec,) = nhtsa_recalls.parse(zipped(), Target("recalls", {"url": nhtsa_recalls.URL, "observed_at": "2026-10-14"}))
    return rec.row


def cat(slug: str, make_name: str, model_name: str) -> dict:
    return {"slug": slug, "make": slug.split("/")[0], "model": slug.split("/")[1], "make_name": make_name, "model_name": model_name}


CATALOGUE = [cat("hyundai/ioniq-5", "Hyundai", "Ioniq 5"), cat("hyundai/ioniq-5-n", "Hyundai", "Ioniq 5 N"), cat("hyundai/ioniq-6", "Hyundai", "Ioniq 6"),
             cat("kia/ev3", "Kia", "EV3"), cat("byd/seal", "BYD", "Seal"), cat("lexus/es-electric", "Lexus", "ES Electric"),
             cat("tesla/model-3", "Tesla", "Model 3")]


class Parse(unittest.TestCase):
    def setUp(self):
        self.row = row()
        self.by = {r["number"]: r for r in self.row["recalls"]}

    def test_the_recalls_read(self):
        self.assertEqual((self.row["spec_key"], self.row["observed_at"]), ("nhtsa:recalls", "2026-10-14"))
        # The petrol Kona, the 2021 C-HR, the 2017 Ioniq, the equipment recall and the trailer are left.
        self.assertEqual(sorted(self.by), ["21V-00J", "21V-931", "21V-979", "22V-063", "22V-235", "23V-369", "23V-709", "24V-065",
                                           "24V-204", "24V-868", "25V-065", "25V-235", "26V-432"])
        self.assertIn("hyundai/ioniq-5", self.row["sold_in_us"])
        self.assertNotIn("byd/seal", self.row["sold_in_us"])

    def test_one_campaign_its_vehicles(self):
        iccu = self.by["24V-868"]
        self.assertEqual((iccu["reported"], iccu["units"], iccu["built_from"], iccu["built_to"]), ("2024-11-18", 145642, "2021-10-04", "2024-10-09"))
        ioniq5 = [(v["year"], v["models"]) for v in iccu["vehicles"] if v["model"] == "IONIQ 5"]
        self.assertEqual(sorted(ioniq5), [(2022, ["hyundai/ioniq-5"]), (2023, ["hyundai/ioniq-5"]), (2024, ["hyundai/ioniq-5"])])   # a line per component, once
        self.assertIn("This recall expands and replaces previous recall number 24V-204.", iccu["remedy"])
        # Only the cars of ours: not the S-Class beside the EQS 450, nor the Maverick beside the Mach-E.
        self.assertEqual({v["model"] for v in self.by["21V-931"]["vehicles"]}, {"EQS 450"})
        self.assertEqual({v["model"] for v in self.by["21V-979"]["vehicles"]}, {"MUSTANG MACH E"})
        self.assertTrue(self.by["26V-432"]["park_outside"])

    def test_names_as_the_records_write_them(self):
        self.assertEqual(nhtsa_recalls.models_of("MERCEDES-BENZ", "EQS450", 2023), ["mercedes/eqs"])
        self.assertEqual(nhtsa_recalls.models_of("MERCEDES-BENZ", "EQS SUV 450 4MATIC", 2023), ["mercedes/eqs-suv"])
        self.assertEqual(nhtsa_recalls.models_of("MERCEDES-BENZ", "AMG EQS 53", 2022), ["mercedes/amg-eqs"])
        self.assertEqual(nhtsa_recalls.models_of("HYUNDAI", "IONIQ 5", 2024), ["hyundai/ioniq-5"])
        self.assertEqual(nhtsa_recalls.models_of("HYUNDAI", "IONIQ 5", 2025), ["hyundai/ioniq-5", "hyundai/ioniq-5-n"])   # the N is filed under IONIQ 5
        self.assertEqual(nhtsa_recalls.models_of("TOYOTA", "C-HR", 2022), [])          # petrol; the C-HR is electric from 2026
        self.assertEqual(nhtsa_recalls.models_of("TOYOTA", "C-HR", 2026), ["toyota/c-hr-plus"])
        self.assertEqual(nhtsa_recalls.models_of("TESLA", "MODEL Y L", 2026), [])
        self.assertEqual(nhtsa_recalls.models_of("VOLVO", "XC40", 2023), [])            # the petrol XC40; the electric one is XC40BEV
        self.assertEqual(nhtsa_recalls.campaign("24V868000"), "24V-868")


class Discover(unittest.TestCase):
    def db(self, last_seen: str | None) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE specs (spec_key TEXT PRIMARY KEY, last_seen_at TEXT)")
        if last_seen:
            conn.execute("INSERT INTO specs VALUES ('nhtsa:recalls', ?)", (last_seen,))
        return conn

    def test_once_a_week(self):
        self.assertEqual(len(list(nhtsa_recalls.discover(Target("all"), Context(root=FIX.parent)))), 1)
        self.assertEqual(len(list(nhtsa_recalls.discover(Target("all"), Context(root=FIX.parent, extras={"db": self.db("2020-01-01T00:00:00+00:00")})))), 1)
        fresh = Context(root=FIX.parent, extras={"db": self.db("2999-01-01T00:00:00+00:00")})
        self.assertEqual(list(nhtsa_recalls.discover(Target("all"), fresh)), [])
        (t,) = nhtsa_recalls.discover(Target("recalls"), fresh)   # asked for by name: fetched anyway
        self.assertEqual(t.metadata["url"], "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip")

    def test_fetch(self):
        got = Fetched(url=nhtsa_recalls.URL, status_code=200, body=zipped())
        with mock.patch.object(nhtsa_recalls, "fetch_url", return_value=got) as f:
            self.assertIs(nhtsa_recalls.fetch(Target("recalls", {"url": nhtsa_recalls.URL}), Context(root=FIX.parent)), got)
        self.assertEqual(f.call_args.args[0], nhtsa_recalls.URL)


class ByModel(unittest.TestCase):
    def setUp(self):
        self.by = claims.us_recalls_by_model(row()["recalls"])

    def numbers(self, slug):
        return [x["number"] for x in self.by.get(slug, [])]

    def test_each_model_its_recalls(self):
        self.assertEqual(self.numbers("hyundai/ioniq-5"), ["26V-432", "25V-235", "25V-065", "24V-868", "24V-204", "24V-065"])   # newest first
        self.assertEqual(self.numbers("hyundai/ioniq-5-n"), ["25V-235", "25V-065"])                                             # 2025 cars on
        self.assertEqual(self.numbers("hyundai/ioniq-6"), ["24V-868", "24V-204", "24V-065"])
        self.assertEqual(self.numbers("tesla/model-3"), self.numbers("tesla/model-3-performance"))
        self.assertEqual(self.numbers("mercedes/eqs"), ["21V-00J", "21V-931"])

    def test_a_fix_that_did_not_hold(self):
        later, earlier = [x for x in self.by["hyundai/ioniq-5"] if x["number"] in ("24V-868", "24V-204")]
        self.assertEqual((later["follows"], earlier["followed_by"]), ({"24V-204": "not_held"}, [("24V-868", "not_held")]))
        self.assertIn("Follows 24V-204, a fix that did not hold.", claims.us_recall_text(later))
        self.assertIn("Cars it fixed were recalled again under 24V-868.", claims.us_recall_text(earlier))
        self.assertIn("2022 to 2024 model years built 4 Oct 2021 to 9 Oct 2024 (145,642 US vehicles in the recall), listed as IONIQ 5.", claims.us_recall_text(later))

    def test_the_ways_a_recall_names_another(self):
        # "Vehicles repaired under the previous recall will need to have the new remedy completed", beside "replaces".
        (n,) = [x for x in self.by["hyundai/ioniq-5-n"] if x["number"] == "25V-235"]
        self.assertEqual(n["follows"], {"25V-065": "not_held"})
        # "This recall has been superseded by Recall 22V-235", and the later one's "already remedied under 22V-063".
        old, new = [x for x in self.by["tesla/model-3"] if x["number"] in ("22V-063", "22V-235")][::-1]
        self.assertEqual((old["followed_by"], new["follows"]), ([("22V-235", "not_held")], {"22V-063": "not_held"}))
        (pace,) = [x for x in self.by["jaguar/i-pace"] if x["number"] == "23V-709"]
        self.assertEqual(pace["follows"], {"23V-369": "not_held"})

    def test_the_line(self):
        (x,) = [x for x in self.by["hyundai/ioniq-5"] if x["number"] == "26V-432"]
        text = claims.us_recall_text(x)
        self.assertTrue(text.startswith("2 Jul 2026, 26V-432: Hyundai Motor America (Hyundai) is recalling certain 2023-2024 Ioniq 5 vehicles."))
        self.assertIn("Fix: Owners are advised to park outside", text)
        self.assertNotIn("searchable on NHTSA.gov", text)    # the notice boilerplate is left
        self.assertTrue(text.endswith("NHTSA: park it outside until repaired."))


class SaidOfTheModel(unittest.TestCase):
    def resolved(self, make, model):
        store = claims.Store()
        claims.from_us_recalls(store, [row()], CATALOGUE)
        car = {"id": "c", "make": make, "model": model, "trim": "Premium"}
        claims.resolve_car(car, store)
        return car

    def test_sold_in_the_us(self):
        car = self.resolved("Hyundai", "Ioniq 5")
        self.assertEqual((car["us_recalls_count"], car["us_recalls_latest"]), (6, "2026-07-02"))
        self.assertEqual(len(car["us_recalls"].split("\n")), 6)
        self.assertIn("NHTSA safety recalls (US)", car["field_sources"]["us_recalls"])

    def test_sold_with_no_recall(self):
        car = self.resolved("Kia", "EV3")
        self.assertEqual((car["us_recalls_count"], car.get("us_recalls_latest")), (0, None))
        self.assertEqual(car["us_recalls"], "No US recall names the EV3 since model year 2019.")

    def test_not_sold_there(self):
        car = self.resolved("BYD", "Seal")
        self.assertIsNone(car.get("us_recalls_count"))
        self.assertEqual(car["us_recalls"], "Not sold in the US: NHTSA lists no BYD Seal since model year 2019.")
        self.assertTrue(self.resolved("Lexus", "ES Electric")["us_recalls"].startswith("Sold in the US, but NHTSA files its recalls under ES"))


if __name__ == "__main__":
    unittest.main()
