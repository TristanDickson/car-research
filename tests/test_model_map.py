"""Carwow's catalogue models on Parkers' models and generations (services/model_map.py), built from real pages:
Carwow's Audi, Hyundai and Kia electric pages (the catalogue), its registry tables for the Kona Electric, the
Ioniq 3 and both Q4 e-trons (tests/fixtures/carwow_*_model_trims.html: each page's trims and prices table, as
printed), a slice of Parkers' spec sitemaps (tests/fixtures/parkers_sitemap_t2_slice.xml: the Q4 e-tron, the Kona
Electric, the Ioniq 5, the Ioniq Electric, the Soul and the Soul EV, every entry as printed) and one Parkers
derivative page (a Q4 Sportback e-tron)."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.providers import carwow_model
from pipeline.services import model_map
from pipeline.services.snapshot import export_snapshot
from tests.helpers import Raws

T = "2026-10-17T03:00:00+00:00"
REGISTRY = {"hyundai/kona-electric": ("Hyundai", "Kona Electric"), "hyundai/ioniq-3": ("Hyundai", "Ioniq 3"),
            "audi/q4-e-tron": ("Audi", "Q4 e-tron"), "audi/q4-e-tron-sportback": ("Audi", "Q4 Sportback e-tron")}
PAGE = "audi/q4-e-tron/sportback-2021/150kw-63kwh-sport-5dr-auto"


def fill(raws: Raws, reverse: bool = False) -> None:
    adds = []
    for make in ("audi", "hyundai", "kia"):
        adds.append(("carwow_catalog", f"brand/{make}", f"carwow_brand_{make}_electric.html",
                     {"url": f"https://www.carwow.co.uk/{make}/electric", "kind": "brand", "make": make}, None))
    for slug, (make_name, model_name) in REGISTRY.items():
        make, model = slug.split("/")
        adds.append(("carwow_model", slug, f"carwow_{make}_{model}_model_trims.html",
                     {"make": make, "model": model, "make_name": make_name, "model_name": model_name,
                      "url": carwow_model.url_for(make, model)}, None))
    adds.append(("parkers", "spec-1", "parkers_sitemap_t2_slice.xml",
                 {"url": "https://www.parkers.co.uk/sitemap/zip-files/spec-1.xml.gz"}, "sitemap"))
    adds.append(("parkers", PAGE, "parkers_q4-e-tron_sportback-2021_150kw-63kwh-sport-5dr-auto.html",
                 {"url": f"https://www.parkers.co.uk/{PAGE}/specs/", "make_slug": "audi", "model_slug": "q4-e-tron",
                  "generation": "sportback-2021"}, "pages"))
    for provider, ident, fixture, meta, cap in (reversed(adds) if reverse else adds):
        raws.add(provider, ident, fixture, metadata=meta, capability=cap, at=T)


class ModelMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Raws() as raws:
            fill(raws)
            cls.conn = raws.build()
        cls.rows = {r["slug"]: r for r in model_map.load(cls.conn)}

    def gens(self, slug: str) -> list[str]:
        return [g["generation"] for g in self.rows[slug]["generations"]]

    def test_a_carwow_model_spans_every_generation_of_its_parkers_model(self):
        r = self.rows["hyundai/kona-electric"]
        self.assertEqual((r["status"], r["parkers"], r["rule"]), ("placed", "hyundai/kona-electric", "name and derivatives"))
        self.assertEqual(self.gens("hyundai/kona-electric"), ["suv-2018", "suv-2023"], "the resolver tells the two apart by dates")
        shared = {g["generation"]: g["shared"] for g in r["generations"]}
        self.assertEqual(shared["suv-2018"], 0)
        self.assertGreater(shared["suv-2023"], 0, "Carwow's registry is the current price list")

    def test_a_body_word_in_the_name_picks_the_generation(self):
        sb = self.rows["audi/q4-e-tron-sportback"]
        self.assertEqual((sb["status"], sb["parkers"]), ("placed", "audi/q4-e-tron"), "Parkers files the Sportback as a generation")
        self.assertEqual(self.gens("audi/q4-e-tron-sportback"), ["sportback-2021"])
        self.assertEqual(self.gens("audi/q4-e-tron"), ["suv-2021"], "the generation the Sportback does not name")
        page = next(g for g in sb["generations"] if g["generation"] == "sportback-2021")
        self.assertGreaterEqual(page["shared"], 1, "the derivative page's name is the registry's, exactly as printed")
        self.assertEqual(page["since"], "2026-06", "the one derivative page held: its on-sale date")

    def test_a_version_parkers_files_as_a_generation(self):
        self.assertEqual((self.rows["hyundai/ioniq-5-n"]["parkers"], self.gens("hyundai/ioniq-5-n")), ("hyundai/ioniq-5", ["n-2023"]))
        self.assertEqual(self.gens("hyundai/ioniq-5"), ["suv-2021"])

    def test_a_number_after_the_name_is_another_model(self):
        r = self.rows["hyundai/ioniq-3"]
        self.assertEqual(r["status"], "unplaced", "the Ioniq 3 is not the Ioniq Electric, and Parkers has no Ioniq 3 model")
        self.assertIn("5 of 10, in hyundai/ioniq-5", r["why"], "Parkers files half its derivatives under the Ioniq 5 N: listed, not placed")

    def test_two_parkers_models_that_fit_alike_are_listed_not_guessed(self):
        r = self.rows["kia/soul-ev"]
        self.assertEqual((r["status"], r["parkers"]), ("ambiguous", None))
        self.assertEqual(sorted(c["parkers"] for c in r["candidates"]), ["kia/soul", "kia/soul-ev"])

    def test_a_model_parkers_does_not_list_is_unplaced(self):
        r = self.rows["kia/ev3"]
        self.assertEqual((r["status"], r["parkers"], r["generations"]), ("unplaced", None, []))
        self.assertTrue(r["why"])

    def test_the_reading_order_decides_nothing(self):
        with Raws() as raws:
            fill(raws, reverse=True)
            conn = raws.build()
        self.assertEqual(model_map.load(conn), list(self.rows.values()))

    def test_the_snapshot_carries_it_with_the_cars_on_sale(self):
        with tempfile.TemporaryDirectory() as tmp:
            export_snapshot(self.conn, tmp, generated_at=T)
            data = json.loads((Path(tmp) / "data.json").read_text(encoding="utf-8"))
        row = next(r for r in data["model_map"] if r["slug"] == "hyundai/kona-electric")
        self.assertEqual(row["parkers"], "hyundai/kona-electric")
        self.assertGreater(row["cars_on_sale"], 0, "the registry's derivatives are cars on sale")
        self.assertEqual(len(data["model_map"]), len(self.rows))


class Names(unittest.TestCase):
    def close(self, a: str, b: str) -> float:
        return model_map._closeness(model_map._core(model_map._model_words(a), []), model_map._core(model_map._model_words(b), []))

    def test_how_alike_two_model_names_read(self):
        self.assertEqual(self.close("e:Ny1", "eny1"), 2.0)
        self.assertEqual(self.close("C-HR+", "c-hr-plus"), 2.0)
        self.assertEqual(self.close("Ora 03", "ora-3"), 2.0)
        self.assertEqual(self.close("ForTwo EQ (2017-2020)", "eq-fortwo"), 1.95)
        self.assertEqual(self.close("500e", "500-electric"), 1.9)
        self.assertGreater(self.close("Model 3 Performance", "model-3"), 1.0)
        self.assertGreater(self.close("AMG EQE 53", "amg-eqe"), 1.0)
        self.assertEqual(self.close("Ioniq 3", "ioniq-electric"), 0.0)
        self.assertEqual(self.close("CX-6e", "6e"), 0.0)


if __name__ == "__main__":
    unittest.main()
