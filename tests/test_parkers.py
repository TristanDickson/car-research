"""Parkers, against a slice of its real spec sitemap (tests/fixtures/parkers_sitemap_slice.xml: the Kona Electric's two
generations, the Peugeot 208 of 2019 with its petrol and electric versions, the Ford Focus, the Tesla Model 3) and two
of the first Kona Electric's derivative pages."""
import unittest
from pathlib import Path

from pipeline.providers import parkers
from pipeline.providers.types import Target

FIX = Path(__file__).parent / "fixtures"
SITEMAP = (FIX / "parkers_sitemap_slice.xml").read_bytes()


def page(name: str) -> str:
    return (FIX / f"parkers_kona-electric_suv-2018_{name}.html").read_text(encoding="utf-8", errors="replace")


class Sitemap(unittest.TestCase):
    def setUp(self):
        self.rows = [r.row for r in parkers.parse_sitemap(SITEMAP, Target("spec-1", {"url": "u", "observed_at": "2026-10-16"}))]
        self.by = {r["spec_key"].split(":", 1)[1]: r for r in self.rows}

    def test_every_generation_its_trims_engines_and_derivatives(self):
        kona = [r for r in self.rows if r["model_slug"] == "kona-electric"]
        self.assertEqual(sorted({r["generation"] for r in kona}), ["suv-2018", "suv-2023"])
        trims = sorted(r["slug"] for r in kona if r["generation"] == "suv-2023" and r["entry"] == "trim")
        self.assertEqual(trims, ["advance", "n-line", "n-line-s", "ultimate"])
        lux = self.by["hyundai/kona-electric/suv-2023/160kw-ultimate-65kwh-5dr-auto-[lux-pack]"]
        self.assertEqual((lux["entry"], lux["generation_start"], lux["body"]), ("derivative", 2023, "suv"))

    def test_only_electric_versions(self):
        e208 = sorted(r["slug"] for r in self.rows if r["model_slug"] == "208" and r["entry"] == "derivative")
        self.assertEqual(e208, ["100kw-envy-50kwh-5dr-auto", "115kw-envy-51kwh-5dr-auto", "207kw-gti-51kwh-5dr-auto"], "the petrol 208s are left")
        self.assertFalse([r for r in self.rows if r["model_slug"] == "focus"])
        tesla = [r for r in self.rows if r["model_slug"] == "model-3" and r["entry"] == "derivative"]
        self.assertEqual(len(tesla), 14, "names without a kWh count when every engine of the generation is electric")


class Page(unittest.TestCase):
    def row(self, name: str) -> dict:
        target = f"hyundai/kona-electric/suv-2018/{name}"
        meta = {"url": f"https://www.parkers.co.uk/{target}/specs/", "make_slug": "hyundai", "model_slug": "kona-electric", "generation": "suv-2018"}
        (rec,) = parkers.parse_page_record(page(name).encode("utf-8"), Target(target, dict(meta, observed_at="2026-10-16")))
        return rec.row

    def test_the_derivative_its_dates_and_price(self):
        r = self.row("150kw-ultimate-64kwh-5dr-auto")
        self.assertEqual(r["spec_key"], "parkers:hyundai/kona-electric/suv-2018/150kw-ultimate-64kwh-5dr-auto")
        self.assertEqual((r["name"], r["on_sale_since"], r["on_sale_until"], r["price_new"]), ("150kW Ultimate 64kWh 5dr Auto", "2021-03", "2023-06", 39900.0))
        n = r["numbers"]
        self.assertEqual((n["power_bhp"], n["battery_kwh"], n["wltp_range_mi"], n["efficiency_mi_kwh"], n["insurance_group"], n["wheelbase_m"]),
                         (201.0, 64.0, 301.0, 4.2, 24.0, 2.6))
        self.assertEqual(r["charging"]["Public charger (ultrarapid) 100kW · 10-80 % full"], "47 mins")

    def test_the_equipment_without_its_headings(self):
        r = self.row("150kw-ultimate-64kwh-5dr-auto")
        self.assertEqual((len(r["features"]), len(r["options"])), (124, 23), "the page's own counts")
        self.assertNotIn("Entertainment", r["features"])
        self.assertIn("Krell premium audio system with 8 speakers and subwoofer", r["features"])
        self.assertIn("Heat pump", r["options"], "an option on the first Kona's Ultimate")

    def test_the_older_naming_is_an_earlier_version_not_a_duplicate(self):
        r = self.row("premium-se-64-kwh-battery-204ps-auto-5d")
        self.assertEqual((r["name"], r["on_sale_since"], r["on_sale_until"], r["price_new"]), ("Premium SE 64 kWh Battery 204PS auto 5d", "2019-12", "2021-01", 41500.0))


class Discover(unittest.TestCase):
    def test_never_read_pages_first_newest_generations_first_within_the_budget(self):
        class Store:
            def __init__(self):
                self.bodies = {"s1": SITEMAP}
                self.rows = [{"source": "parkers", "capability": "sitemap", "target": "spec-1", "status": 200, "fetched_at": "2026-10-16T00:00:00+00:00", "sha256": "s1"},
                             {"source": "parkers", "capability": "pages", "target": "hyundai/kona-electric/suv-2023/160kw-advance-65kwh-5dr-auto",
                              "status": 200, "fetched_at": "2026-10-16T00:00:00+00:00", "sha256": "x"}]

            def entries(self):
                return iter(self.rows)

            def get(self, sha):
                return self.bodies[sha]

            def read_log(self, kind):
                return iter(())

        from pipeline.providers.types import Context
        ctx = Context(root=FIX.parent, extras={"raw_store": Store(), "parkers_per_run": 5})
        got = [t.identifier for t in parkers.discover_pages(Target("all"), ctx)]
        self.assertEqual(len(got), 5)
        self.assertTrue(all("/suv-2023/" in g for g in got), "the newest generation first")
        self.assertNotIn("hyundai/kona-electric/suv-2023/160kw-advance-65kwh-5dr-auto", got, "read today")


if __name__ == "__main__":
    unittest.main()
