"""Carwow's review on its model page, against the Inster's page (tests/fixtures/carwow_hyundai_inster_model.html):
the verdict lists and every section of the review by heading, and the claims the build makes of them."""
import unittest
from pathlib import Path

from pipeline.providers import carwow_model
from pipeline.providers.types import Target
from pipeline.services import claims

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "carwow_hyundai_inster_model.html").read_text(encoding="utf-8")
CATALOGUE = [{"slug": "hyundai/inster", "make": "hyundai", "model": "inster", "make_name": "Hyundai", "model_name": "Inster"}]


class ParseReview(unittest.TestCase):
    def test_the_verdict_lists(self):
        r = carwow_model.parse_review(PAGE)
        self.assertEqual(r["good"], ["Cute looks", "Good price", "Clever back seats"])
        self.assertEqual(r["not_so_good"], ["Cheap cabin plastics", "Base model doesn't get clever seats", "Grabby brakes"])

    def test_the_sections_by_heading(self):
        sections = carwow_model.parse_review(PAGE)["sections"]
        for heading in ("In town", "On the motorway", "Space in the back seats", "Boot space", "Interior style, infotainment and accessories",
                        "Reliability and problems"):
            self.assertIn(heading, sections)
        self.assertTrue(sections["Space in the back seats"].startswith("The Inster’s back seats look quite cramped at first"))
        self.assertIn("At least the rear floor is totally flat", sections["Space in the back seats"])
        self.assertFalse([k for k in sections if "FAQ" in k or k.startswith("What is the")])   # the FAQs are left

    def test_one_review_record_beside_the_derivatives(self):
        recs = list(carwow_model.parse(PAGE.encode("utf-8"), Target("hyundai/inster", {"make": "hyundai", "model": "inster", "url": "u"})))
        review = [r for r in recs if r.kind == "spec"]
        self.assertEqual([r.key for r in review], ["carwow-review:hyundai/inster"])
        self.assertTrue([r for r in recs if r.kind == "derivative"])

    def test_a_page_without_a_review(self):
        self.assertIsNone(carwow_model.parse_review("<html><body><h2>Prices</h2><p>£20,000</p></body></html>"))


class Claims(unittest.TestCase):
    def test_said_of_the_model(self):
        review = {"spec_key": "carwow-review:hyundai/inster", "model_slug": "hyundai/inster", **carwow_model.parse_review(PAGE)}
        store = claims.Store()
        claims.from_carwow_review(store, [review], CATALOGUE)
        car = {"id": "c", "make": "Hyundai", "model": "Inster", "trim": "02"}
        claims.resolve_car(car, store)
        self.assertEqual(car["review_not_so_good"], "Cheap cabin plastics; Base model doesn't get clever seats; Grabby brakes")
        notes = car["review_rear_seat_notes"]
        self.assertTrue(notes.startswith("The Inster’s back seats look quite cramped at first, with tight rear legroom"))
        self.assertIn("At least the rear floor is totally flat, which is great for foot space", notes)
        self.assertNotIn("door bins", notes)   # only what says how a passenger sits
        self.assertTrue(car["review_ride_town"].startswith("The Inster’s big advantage around town is its visibility"))
        self.assertEqual(car["field_sources"]["review_rear_seats"], "Carwow's review of the Inster")


if __name__ == "__main__":
    unittest.main()
