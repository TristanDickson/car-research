"""DVSA's vehicle safety recalls, against 27 rows cut byte for byte from the file Chrome downloaded on
2026-10-13 (the whole file is 7.7 MB): the Ioniq 5's, Ioniq 5 N's, Kona's and PV5's recalls of interest,
the petrol Konas', the Jaguar I-Pace recall that says an earlier one was "incorrectly completed", a Cupra
Born recall filed under SEAT, and lorries, a quad bike and rows from 2008 that are not read.
"""
import unittest
from pathlib import Path
from unittest import mock

from pipeline.providers import dvsa_recalls
from pipeline.providers.http import FetchError
from pipeline.providers.types import Context, Target
from pipeline.services import claims

FIX = Path(__file__).parent / "fixtures"


def lines() -> list[dict]:
    return dvsa_recalls.parse_file((FIX / "dvsa_recalls_2026-10-13.csv").read_text(encoding="utf-8"))


def cat(slug: str, make_name: str, model_name: str) -> dict:
    return {"slug": slug, "make": slug.split("/")[0], "model": slug.split("/")[1], "make_name": make_name, "model_name": model_name}


CATALOGUE = [cat("hyundai/ioniq-5", "Hyundai", "Ioniq 5"), cat("hyundai/ioniq-5-n", "Hyundai", "Ioniq 5 N"), cat("hyundai/kona-electric", "Hyundai", "Kona Electric"),
             cat("hyundai/ioniq-6", "Hyundai", "Ioniq 6"), cat("kia/pv5-passenger", "Kia", "PV5 Passenger"), cat("jaguar/i-pace", "Jaguar", "I-Pace"),
             cat("volkswagen/id3", "Volkswagen", "ID.3"), cat("cupra/born", "Cupra", "Born")]


class ParseFile(unittest.TestCase):
    def test_cars_since_2012(self):
        rs = lines()
        self.assertEqual(len(rs), 19)   # the lorries, the quad bike and the 2008 rows left
        self.assertFalse([r for r in rs if r["launched"] < "2012"])
        (iccu,) = [r for r in rs if r["number"] == "R/2024/164" and r["model"] == "IONIQ 5"]
        self.assertEqual((iccu["launched"], iccu["vehicles"], iccu["built_from"], iccu["built_to"]), ("2024-05-06", 16297, "2021-01-13", "2024-02-29"))
        self.assertTrue(iccu["remedy"].startswith("On all affected vehicles update the ICCU software and check and replace if necessary"))

    def test_one_file_one_record(self):
        (rec,) = dvsa_recalls.parse((FIX / "dvsa_recalls_2026-10-13.csv").read_bytes(), Target("recalls", {"url": dvsa_recalls.URL, "observed_at": "2026-10-13"}))
        self.assertEqual((rec.kind, rec.key, len(rec.row["recalls"])), ("spec", "dvsa:recalls", 19))

    def test_discover_and_the_browser_it_needs(self):
        (t,) = dvsa_recalls.discover(Target("all"), Context(root=FIX))
        self.assertEqual(t.metadata["url"], "https://www.check-vehicle-recalls.service.gov.uk/documents/RecallsFile.csv")
        with mock.patch("shutil.which", return_value=None), self.assertRaises(FetchError):
            dvsa_recalls.fetch(t, Context(root=FIX))


class ByModel(unittest.TestCase):
    def setUp(self):
        self.by = claims.recalls_by_model(lines(), CATALOGUE)

    def numbers(self, slug):
        return [x["number"] for x in self.by.get(slug, [])]

    def test_each_model_its_own_lines(self):
        self.assertEqual(self.numbers("hyundai/ioniq-5"), ["R/2026/146", "R/2024/164", "R/2022/160"])   # newest first
        self.assertEqual(self.numbers("hyundai/ioniq-5-n"), ["R/2026/146"])                               # its own line, not the Ioniq 5's
        self.assertEqual(self.numbers("hyundai/ioniq-6"), ["R/2024/164"])
        self.assertEqual(self.numbers("cupra/born"), ["R/2026/153"])                                      # filed under SEAT

    def test_a_shared_name_without_its_combustion_cars(self):
        # The cluster recall's 'Kona SX2' and the old Kona Electric's battery recall; not the 1.0 and 1.6 T-GDI lines,
        # nor R/2024/172, a transmission fault of a Kona SX2 that does not say electric.
        self.assertEqual(self.numbers("hyundai/kona-electric"), ["R/2026/128", "R/2026/146"])   # 4 May, 2 Apr 2026

    def test_a_recalls_lines_combined(self):
        (pv5,) = self.by["kia/pv5-passenger"]
        self.assertEqual((pv5["number"], pv5["vehicles"], pv5["built_from"], pv5["built_to"], pv5["models"]),
                         ("R/2026/219", 465, "2025-11-12", "2026-03-31", ["PV5"]))

    def test_a_fix_that_did_not_hold(self):
        later, earlier = self.by["jaguar/i-pace"]
        self.assertEqual((later["number"], later["follows"], earlier["number"], earlier["followed_by"]), ("R/2023/297", ["R/2023/154"], "R/2023/154", ["R/2023/297"]))
        self.assertIn("Follows R/2023/154, a fix that did not hold.", claims.recall_text(later))
        self.assertIn("Followed by R/2023/297.", claims.recall_text(earlier))

    def test_said_of_the_model(self):
        store = claims.Store()
        claims.from_recalls(store, [{"recalls": lines()}], CATALOGUE)
        car = {"id": "c", "make": "Hyundai", "model": "Ioniq 5", "trim": "Premium"}
        claims.resolve_car(car, store)
        self.assertEqual((car["recalls_count"], car["recalls_latest"]), (3, "2026-04-02"))
        self.assertTrue(car["recalls"].startswith("2 Apr 2026, R/2026/146: Some vehicles may face a concern where the instrument cluster panel may reboot"))
        self.assertIn("6 May 2024, R/2024/164: On affected vehicles the Integrated Charging Control Unit (ICCU)", car["recalls"])
        self.assertIn("cars built 13 Jan 2021 to 29 Feb 2024 (16,297), listed as IONIQ 5.", car["recalls"])


if __name__ == "__main__":
    unittest.main()
