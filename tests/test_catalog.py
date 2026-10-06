"""The catalogue provider against saved index pages, the generated cars that
cover every derivative nobody curates, and the derivative-text matcher."""
import json
import unittest
from pathlib import Path

from pipeline import gold
from pipeline.providers import carwow_catalog, carwow_deals, carwow_specs, leaseloco
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.providers.wayback import backfill_capability
from pipeline.runner import run
from pipeline.services import autocars, match
from pipeline.history import export_history, export_models, export_specs, import_history, import_models, import_specs
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-06T00:00:00+00:00"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def _fixture_provider(module, name, files: dict[str, str], base=None):
    cap = base or module.provider.capability_for(None)

    def discover(target: Target, ctx: Context):
        for t in cap.discover(target, ctx):
            if t.identifier in files:
                yield t

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes(),
                       content_type="text/html")

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name=name, default_capability=c.name, capabilities={c.name: c}, live=False)


CATALOG_FILES = {
    "sitemap/car_models": "carwow_sitemap_car_models.xml",
    "sitemap/car_model_deals": "carwow_sitemap_car_model_deals.xml",
    "brand/kia": "carwow_brand_kia_electric.html",
    "brand/mini": "carwow_brand_mini_electric.html",
}


def catalog_provider():
    """The catalogue over fixtures; discover does not read the fuel-type sitemap."""
    cap = carwow_catalog.catalog

    def discover(target: Target, ctx: Context):
        for key in CATALOG_FILES:
            kind = "sitemap" if key.startswith("sitemap/") else "brand"
            meta = {"url": f"https://www.carwow.co.uk/{key}", "kind": kind}
            if kind == "brand":
                meta["make"] = key.split("/")[1]
            yield Target(identifier=key, metadata=meta)

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / CATALOG_FILES[target.identifier]).read_bytes())

    c = Capability(name="catalog", parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name="carwow_catalog", default_capability="catalog", capabilities={"catalog": c}, live=False)


class CatalogPages(unittest.TestCase):
    def test_brand_page_lists_the_makes_electric_models_by_name(self):
        rows = carwow_catalog.parse_brand(fixture("carwow_brand_kia_electric.html"), "kia", "u", T)
        self.assertEqual([r["slug"] for r in rows],
                         ["kia/ev2", "kia/ev3", "kia/ev4", "kia/ev4-fastback", "kia/ev5", "kia/ev6", "kia/ev9",
                          "kia/niro-ev-estate", "kia/pv5-passenger", "kia/soul-ev"])
        self.assertEqual((rows[1]["make_name"], rows[1]["model_name"], rows[1]["electric"]), ("Kia", "EV3", 1))
        self.assertEqual((rows[8]["model_name"], rows[8]["has_deals"]), ("PV5 Passenger", None))

    def test_mini_electric_is_a_model_page_not_a_list(self):
        self.assertEqual(carwow_catalog.parse_brand(fixture("carwow_brand_mini_electric.html"), "mini", "u", T), [])

    def test_sitemaps_give_the_page_flags_and_flag_all_electric_makes(self):
        models = {r["slug"]: r for r in carwow_catalog.parse_sitemap(fixture("carwow_sitemap_car_models.xml"), "sitemap/car_models", "u", T)}
        self.assertEqual((models["kia/ev3"]["has_specs"], models["kia/ev3"]["electric"]), (1, None))
        self.assertEqual((models["tesla/model-y"]["has_specs"], models["tesla/model-y"]["electric"]), (1, 1), "Tesla sells nothing else")
        self.assertEqual(models["mini/electric"]["electric"], 1, "listed by slug: MINI's /electric page is this model")
        self.assertIsNone(models["mini/cooper"]["electric"])
        self.assertNotIn("kia/electric", models)
        deals = {r["slug"]: r for r in carwow_catalog.parse_sitemap(fixture("carwow_sitemap_car_model_deals.xml"), "sitemap/car_model_deals", "u", T)}
        self.assertEqual(deals["kia/ev3"]["has_deals"], 1)
        self.assertNotIn("tesla/model-y", deals, "Carwow has no Tesla deals page")

    def test_pretty_make(self):
        self.assertEqual([carwow_catalog.pretty_make(m) for m in ("kia", "bmw", "land-rover", "mg", "alfa-romeo")],
                         ["Kia", "BMW", "Land Rover", "MG", "Alfa Romeo"])


class CatalogInGold(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)
        self.res = run(self.conn, catalog_provider(), ctx=Context(root=FIX))

    def test_pages_merge_by_slug(self):
        self.assertEqual(self.res.errors, 0)
        row = self.conn.execute("SELECT * FROM models WHERE slug='kia/ev3'").fetchone()
        self.assertEqual((row["make_name"], row["model_name"], row["electric"], row["has_deals"], row["has_specs"]), ("Kia", "EV3", 1, 1, 1))
        tesla = self.conn.execute("SELECT electric, has_deals, has_specs FROM models WHERE slug='tesla/model-y'").fetchone()
        self.assertEqual(tuple(tesla), (1, None, 1))
        electric = {r[0] for r in self.conn.execute("SELECT slug FROM models WHERE electric=1")}
        self.assertTrue({"kia/ev3", "kia/pv5-passenger", "tesla/model-y", "mini/electric", "mini/aceman", "seat/mii-electric"} <= electric, electric)
        self.assertFalse({"mini/cooper", "kia/sportage", "hyundai/i10"} & electric)

    def test_scrapers_discover_from_the_catalogue(self):
        ctx = Context(root=FIX, extras={"db": self.conn})
        deals = [t.identifier for t in carwow_deals.discover(Target("all"), ctx)]
        specs = [t.identifier for t in carwow_specs.discover(Target("all"), ctx)]
        self.assertIn("kia/ev9", deals)
        self.assertNotIn("tesla/model-y", deals)
        self.assertIn("tesla/model-y", specs)
        self.assertNotIn("mini/cooper", specs)
        t = next(t for t in carwow_specs.discover(Target("kia/ev3"), ctx))
        self.assertEqual((t.metadata["make_name"], t.metadata["url"]), ("Kia", "https://www.carwow.co.uk/kia/ev3/specifications"))
        # Without a catalogue (no DB in the context) the static lists still apply.
        self.assertEqual(len(list(carwow_deals.discover(Target("all"), Context(root=FIX)))), len(carwow_deals.MODELS))
        # LeaseLoco guesses the slug for catalogue models it does not know; those are optional (a 404 is not a failure).
        ll = {t.identifier: t for t in leaseloco.discover(Target("all"), ctx)}
        self.assertFalse(ll["kia/ev3"].metadata.get("optional"))
        self.assertTrue(ll["kia/ev9"].metadata["optional"])

    def test_catalogue_round_trips_through_history(self):
        tmp = FIX.parent / "_models_roundtrip.jsonl"
        try:
            self.assertEqual(export_models(self.conn, tmp), self.conn.execute("SELECT COUNT(*) FROM models").fetchone()[0])
            other = fresh_conn()
            self.assertEqual(import_models(other, tmp), export_models(self.conn, tmp))
            self.assertEqual(other.execute("SELECT make_name, has_deals FROM models WHERE slug='kia/ev3'").fetchone()[:], ("Kia", 1))
        finally:
            tmp.unlink(missing_ok=True)

    def test_shard_splits_the_pages_between_jobs(self):
        base = carwow_deals.deals
        seen = []

        def cdx(url, since, ctx):
            seen.append(url)
            return []

        import pipeline.providers.wayback as wb
        orig = wb.cdx_snapshots
        wb.cdx_snapshots = cdx
        try:
            cap = backfill_capability(base)
            for i in range(3):
                list(cap.discover(Target("all"), Context(root=FIX, extras={"db": self.conn, "shard": (i, 3)})))
        finally:
            wb.cdx_snapshots = orig
        every = [t.metadata["url"] for t in base.discover(Target("all"), Context(root=FIX, extras={"db": self.conn}))]
        self.assertEqual(sorted(seen), sorted(every), "three shards cover every page exactly once")


class GeneratedCars(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)

    def test_deals_page_makes_a_stub_car_and_the_spec_page_upgrades_it(self):
        deals = _fixture_provider(carwow_deals, "carwow_deals", {"hyundai/ioniq-3": "carwow_hyundai_ioniq-3_deals.html"})
        res = run(self.conn, deals, ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.unmapped), (0, 0), "every derivative has a car now")
        stub = json.loads(self.conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
        self.assertEqual((stub["auto"], stub["source_kind"], stub["trim"], stub["list_price_gbp"], stub["heat_pump"]),
                         (True, "stub", "Advance · 108kW 42kWh Auto", 22245.0, "unknown"))
        obs = self.conn.execute("SELECT car_id FROM offer_observations WHERE offer_key='carwow:cash:110663'").fetchone()
        self.assertEqual(obs["car_id"], "carwow-cap:110663")
        # The hand-curated Ultimate still wins its derivative.
        self.assertEqual(self.conn.execute("SELECT car_id FROM offer_observations WHERE offer_key='carwow:cash:111015'").fetchone()[0],
                         "hyundai-ioniq3-61-ultimate-evpack")
        specs = _fixture_provider(carwow_specs, "carwow_specs", {"hyundai/ioniq-3": "carwow_hyundai_ioniq-3_specifications.html"})
        run(self.conn, specs, ctx=Context(root=FIX))
        car = json.loads(self.conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
        flags = json.loads(self.conn.execute("SELECT payload FROM specs WHERE spec_key='carwow-cap:110663'").fetchone()["payload"])["flags"]
        self.assertEqual((car["source_kind"], car["heat_pump"], car["seats"]), ("spec", flags["heat_pump"] or "unknown", 5))
        self.assertTrue(car["image_url"].startswith("https://car-data.carwow.co.uk/image?"))
        # A stub never overwrites a spec-built car.
        run(self.conn, deals, ctx=Context(root=FIX))
        again = json.loads(self.conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
        self.assertEqual(again["source_kind"], "spec")

    def test_a_generated_car_never_replaces_a_hand_curated_one(self):
        hand = "hyundai-kona-65-advance"
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM cars WHERE id=?", (hand,)).fetchone())
        stub = autocars.from_stub({"cap_id": "x", "make": "Hyundai", "model": "Kona Electric"}) | {"id": hand}
        self.assertFalse(gold.ensure_auto_car(self.conn, stub, "t", None, None, T))
        self.assertNotIn('"auto": true', self.conn.execute("SELECT payload FROM cars WHERE id=?", (hand,)).fetchone()["payload"])

    def test_history_replay_regenerates_the_cars_in_order(self):
        # Kona deals (its spec page is not replayed: every Kona derivative becomes a stub car) and
        # Ioniq 3 specs (its uncurated derivatives become spec-built cars).
        deals = _fixture_provider(carwow_deals, "carwow_deals", {"kia/ev3": "carwow_kia_ev3_deals.html"})
        run(self.conn, deals, ctx=Context(root=FIX))
        specs = _fixture_provider(carwow_specs, "carwow_specs", {"hyundai/ioniq-3": "carwow_hyundai_ioniq-3_specifications.html"})
        run(self.conn, specs, ctx=Context(root=FIX))
        n_spec_cars = self.conn.execute("SELECT COUNT(DISTINCT car_id) FROM specs WHERE car_id LIKE 'carwow-cap:%'").fetchone()[0]
        self.assertGreater(n_spec_cars, 0)
        hist, spec = FIX.parent / "_obs.jsonl", FIX.parent / "_specs.jsonl"
        try:
            export_history(self.conn, hist)
            export_specs(self.conn, spec)
            other = fresh_conn()
            run_all(other)
            self.assertEqual(import_specs(other, spec), self.conn.execute("SELECT COUNT(*) FROM specs").fetchone()[0])
            self.assertEqual(other.execute("SELECT COUNT(*) FROM cars WHERE id LIKE 'carwow-cap:%'").fetchone()[0], n_spec_cars,
                             "uncurated derivatives come back from their specs")
            n = import_history(other, hist)
            self.assertEqual(n, self.conn.execute("SELECT COUNT(*) FROM offer_observations").fetchone()[0],
                             "no observation is dropped: stub cars come back from the observation's car_ref")
            stub = json.loads(other.execute("SELECT payload FROM cars WHERE id='carwow-cap:106391'").fetchone()["payload"])
            self.assertEqual((stub["source_kind"], stub["model"], stub["trim"]), ("stub", "EV3", "Air · 150kW 58.3kWh Auto"))
        finally:
            hist.unlink(missing_ok=True)
            spec.unlink(missing_ok=True)

    def test_prune_drops_only_orphans(self):
        gold.ensure_auto_car(self.conn, autocars.from_stub({"cap_id": "999", "make": "Kia", "model": "EV3", "trim": "Air", "engine": "150kW 58.3kWh Auto"}), "t", None, None, T)
        self.assertEqual(gold.prune_auto_cars(self.conn), 1)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM cars WHERE id='carwow-cap:999'").fetchone())


class DerivativeMatcher(unittest.TestCase):
    CARS = [
        {"id": "a", "trim": "Air · 150kW 58.3kWh Auto", "variant": "150kW 58.3kWh Auto", "battery_kwh": 58.3},
        {"id": "b", "trim": "Air · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto", "battery_kwh": 81.4},
        {"id": "c", "trim": "GT-Line · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto", "battery_kwh": 81.4},
        {"id": "d", "trim": "GT-Line S · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto", "battery_kwh": 81.4},
    ]

    def test_kw_kwh_and_trim_words_pick_one_car(self):
        self.assertEqual(match.best("150kW Air 81.4kWh 5dr Auto", self.CARS)["id"], "b")
        self.assertEqual(match.best("150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]", self.CARS)["id"], "d")
        self.assertEqual(match.best("150kW GT-Line 81.4kWh 5dr Auto", self.CARS)["id"], "c")

    def test_option_pack_twins_go_to_the_base_derivative_and_plus_trims_stay_apart(self):
        twins = [
            {"id": "p1", "trim": "Black Edition · 210kW Performance 82kWh Auto", "variant": "210kW Performance 82kWh Auto", "list_price_gbp": 52210.0},
            {"id": "p2", "trim": "Black Edition · 210kW Perf 82kWh Auto", "variant": "210kW Perf 82kWh Auto", "list_price_gbp": 54110.0},
            {"id": "s1", "trim": "Sport · 210kW Performance 82kWh Auto", "variant": "210kW Performance 82kWh Auto", "list_price_gbp": 46260.0},
        ]
        # The broker omits 'Performance'; both Black Edition derivatives fit and the cheaper one takes the price.
        self.assertEqual(match.best("210kW 45 82kWh Black Edition 5dr Auto [5 seat]", twins)["id"], "p1")
        plus = [
            {"id": "gt", "trim": "GT · 130kW 52kWh Auto", "variant": "130kW 52kWh Auto", "list_price_gbp": 33500.0},
            {"id": "gt+", "trim": "GT+ · 130kW 52kWh Auto", "variant": "130kW 52kWh Auto", "list_price_gbp": 33995.0},
        ]
        self.assertEqual(match.best("130kW GT 52kWh 5dr Auto", plus)["id"], "gt")
        self.assertEqual(match.best("130kW GT+ 52kWh 5dr Auto", plus)["id"], "gt+")
        self.assertIsNone(match.best("130kW GT Premiere 52kWh 5dr Auto", [plus[1]]), "'GT+' is not in the text")

    def test_contradiction_or_tie_is_a_miss(self):
        self.assertIsNone(match.best("150kW Air 64kWh 5dr Auto", self.CARS), "no 64kWh EV3")
        self.assertIsNone(match.best("150kW 81.4kWh 5dr Auto", self.CARS[1:3]), "Air or GT-Line? not ours to guess")
        self.assertIsNone(match.best("anything", []))

    def test_broker_rows_resolve_to_generated_cars_through_the_runner(self):
        conn = fresh_conn()
        run_all(conn)
        # Pretend nobody curated the Kona: its four derivatives become generated cars.
        conn.execute("DELETE FROM trim_map WHERE source='carwow-cap' AND source_key IN ('103322','103324','103325','103326')")
        specs = _fixture_provider(carwow_specs, "carwow_specs", {"hyundai/kona-electric": "carwow_hyundai_kona-electric_specifications.html"})
        run(conn, specs, ctx=Context(root=FIX))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cars WHERE id LIKE 'carwow-cap:%'").fetchone()[0], 4)
        conn.execute("DELETE FROM trim_map WHERE source='leaseloco'")
        ll = _fixture_provider(leaseloco, "leaseloco", {"hyundai/kona-electric": "leaseloco_hyundai_kona-electric.html"})
        res = run(conn, ll, ctx=Context(root=FIX))
        auto = conn.execute("SELECT COUNT(*) FROM trim_map WHERE source='leaseloco' AND status='auto'").fetchone()[0]
        self.assertGreater(auto, 0, "Kona derivatives land on the generated Kona cars")
        rows = conn.execute("SELECT source_key, car_id FROM trim_map WHERE source='leaseloco' AND status='auto'").fetchall()
        for key, car_id in rows:
            car = json.loads(conn.execute("SELECT payload FROM cars WHERE id=?", (car_id,)).fetchone()["payload"])
            self.assertIn(car["trim"].split(" · ")[0].lower().replace("-", " "), key.replace("-", " "), f"{key} -> {car['trim']}")
        self.assertEqual(res.unmapped + auto + conn.execute("SELECT COUNT(*) FROM trim_map WHERE source='leaseloco' AND status='mapped'").fetchone()[0],
                         conn.execute("SELECT COUNT(*) FROM trim_map WHERE source='leaseloco'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
