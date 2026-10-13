"""What Car? Reliability Survey, against the three articles captured on 2026-10-13 (no network).

The electric cars and electric SUVs articles (the 2025 survey, last modified April 2026) write up the
ten most and ten least reliable models of the class and rank every model in a closing table; the
overall article (the 2026 survey, published 22 Sep 2026) writes up its top 20 and bottom 10 only.
"""
import unittest
from pathlib import Path

from pipeline.providers import whatcar
from pipeline.providers.types import Context, Target
from pipeline.services import claims

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-13T03:00:00+00:00"
FILES = {"electric-cars": "whatcar_reliability_ev_cars_2026-10-13.html", "electric-suvs": "whatcar_reliability_ev_suvs_2026-10-13.html",
         "overall": "whatcar_reliability_2026_2026-10-13.html"}


def rows(article: str) -> list[dict]:
    return whatcar.parse_page((FIX / FILES[article]).read_text(encoding="utf-8"), article, whatcar.ARTICLES[article], T)


def named(rs: list[dict], name: str) -> list[dict]:
    return [r for r in rs if r["name"] == name]


def cat(slug: str, make: str, model: str) -> dict:
    return {"slug": slug, "make": slug.split("/")[0], "model": slug.split("/")[1], "make_name": make, "model_name": model}


CATALOGUE = [cat("hyundai/ioniq-5", "Hyundai", "Ioniq 5"), cat("hyundai/ioniq-5-n", "Hyundai", "Ioniq 5 N"), cat("volkswagen/id4", "Volkswagen", "ID.4"),
             cat("porsche/macan-electric", "Porsche", "Macan Electric"), cat("bmw/ix", "BMW", "iX"), cat("bmw/ix1", "BMW", "iX1"),
             cat("mg/mg-4", "MG", "MG4 EV"), cat("hyundai/kona-electric", "Hyundai", "Kona Electric")]


class ParsePage(unittest.TestCase):
    def test_a_class_article_ranks_every_model(self):
        rs = rows("electric-cars")
        self.assertEqual(len(rs), 19)
        (ioniq5,) = named(rs, "Hyundai Ioniq 5")
        self.assertEqual((ioniq5["rank"], ioniq5["of"], ioniq5["list"], ioniq5["numbers"], ioniq5["years"], ioniq5["current"]),
                         (18, 19, "least", {"reliability_pct": 80.7}, "2021-present", True))
        self.assertTrue(ioniq5["faults"].startswith("12-volt battery 20%"))
        self.assertEqual((ioniq5["published"], ioniq5["modified"]), ("2025-02-03", "2026-04-26"))
        (i3,) = named(rs, "BMW i3")   # the table puts the years first for a model no longer sold
        self.assertEqual((i3["years"], i3["current"], i3["rank"]), ("2013-2022", False, 1))

    def test_a_model_the_write_up_dates_differently_is_one_row(self):
        rs = rows("electric-suvs")
        (y,) = named(rs, "Tesla Model Y")   # 2021-present in the table, 2022-present in its write-up
        self.assertEqual((y["rank"], y["of"], y["list"], y["years"]), (3, 27, "most", "2021-present"))
        (kona,) = named(rs, "Hyundai Kona Electric")
        self.assertFalse(kona["current"])

    def test_the_overall_article(self):
        rs = rows("overall")
        self.assertEqual(len(rs), 30)
        (id4,) = named(rs, "Volkswagen ID 4")
        self.assertEqual((id4["rank"], id4["of"], id4["list"], id4["numbers"]["reliability_pct"], id4["published"]), (4, None, "least", 66.9, "2026-09-22"))
        self.assertEqual(len([r for r in rs if r["rank"] == 1 and r["list"] == "most"]), 2)   # '=1.': a tie
        self.assertEqual(len(named(rs, "Kia Niro hybrid and PHEV")), 2)                      # two generations, two rows

    def test_discover(self):
        self.assertEqual([t.identifier for t in whatcar.discover(Target("all"), Context(root=FIX))], ["electric-cars", "electric-suvs", "overall"])


class Claims(unittest.TestCase):
    def resolve(self, model: str) -> dict:
        store = claims.Store()
        claims.from_whatcar(store, rows("electric-cars") + rows("electric-suvs") + rows("overall"), CATALOGUE)
        make = next(c["make_name"] for c in CATALOGUE if c["model_name"] == model)
        car = {"id": "c", "make": make, "model": model, "trim": "t", "auto": True}
        claims.resolve_car(car, store)
        return car

    def test_the_rating_and_its_place(self):
        car = self.resolve("Ioniq 5")
        self.assertEqual(car["whatcar_reliability_pct"], 80.7)
        self.assertTrue(car["whatcar_reliability"].startswith("80.7%, 18th of 19 electric cars (Hyundai Ioniq 5 2021-present); most common faults: 12-volt battery 20%"))
        self.assertEqual(self.resolve("Ioniq 5 N")["whatcar_reliability_pct"], 80.7)   # a variant filed as a model of its own

    def test_the_newest_survey_wins(self):
        car = self.resolve("ID.4")
        self.assertEqual(car["whatcar_reliability_pct"], 66.9)   # 2026's overall article, not 2025's 79.6%
        self.assertTrue(car["whatcar_reliability"].startswith("66.9%, 4th least reliable of all cars"))

    def test_what_is_not_this_car(self):
        self.assertIsNone(self.resolve("Macan Electric").get("whatcar_reliability_pct"))   # the overall article's Macan is the petrol one
        self.assertIsNone(self.resolve("iX1").get("whatcar_reliability_pct"))              # 'iX' is not the iX1
        self.assertEqual(self.resolve("iX")["whatcar_reliability_pct"], 81.0)
        self.assertEqual(self.resolve("MG4 EV")["whatcar_reliability_pct"], 89.3)           # 'MG 4'
        self.assertIsNone(self.resolve("Kona Electric").get("whatcar_reliability_pct"))     # rated only as the 2018-2023 car


if __name__ == "__main__":
    unittest.main()
