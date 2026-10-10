"""The catalogue provider against saved index pages, the derivatives the build makes
from every CAP id a page names, and the derivative-text matcher."""
import json
import unittest

from pipeline import gold
from pipeline.build import Build
from pipeline.providers import carwow_catalog, carwow_deals, carwow_specs, leaseloco
from pipeline.providers.types import Context, Target
from pipeline.providers.wayback import backfill_capability
from pipeline.services import match
from pipeline.services.snapshot import load_cars
from tests.helpers import FIX, Raws, dump, fresh_conn

T = "2026-10-06T00:00:00+00:00"
KONA_CAPS = ("103322", "103324", "103325", "103326")   # the seed maps these to the owner's Kona cars


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


CATALOG_FILES = {
    "sitemap/car_models": "carwow_sitemap_car_models.xml",
    "sitemap/car_model_deals": "carwow_sitemap_car_model_deals.xml",
    "brand/kia": "carwow_brand_kia_electric.html",
    "brand/mini": "carwow_brand_mini_electric.html",
}


def add_catalog(raws: Raws) -> None:
    for key, f in CATALOG_FILES.items():
        kind = "sitemap" if key.startswith("sitemap/") else "brand"
        meta = {"url": f"https://www.carwow.co.uk/{key}", "kind": kind}
        if kind == "brand":
            meta["make"] = key.split("/")[1]
        raws.add("carwow_catalog", key, f, metadata=meta, at=T)


def build_with(conn, sightings=(), registry=(), drop_decisions=()):
    """A build over the owner's files plus records handed in directly: registry rows, and price sightings
    (at, provider, row). `drop_decisions` takes (source, key) decisions out, as if the owner had not made them."""
    for r in registry:
        gold.upsert_derivative(conn, r, "carwow_model", None, None, T)
    b = Build(conn, None)
    b.owner()
    for k in drop_decisions:
        b.decisions.pop(k, None)
    for at, provider, row in sightings:
        b._sight(at, 2, provider, row, None)
    b.finish()
    conn.commit()
    return b


def ev3(cap, rrp, trim="GT-Line S", engine="150kW 81.4kWh Auto", version="2025-10-01"):
    return {"cap_id": cap, "make_slug": "kia", "model_slug": "ev3", "make": "Kia", "model": "EV3", "name": f"{engine} {trim}",
            "trim": trim, "engine": engine, "rrp": rrp, "version_date": version}


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
        self.raws = Raws()
        add_catalog(self.raws)
        self.conn = self.raws.build()

    def tearDown(self):
        self.raws.close()

    def test_pages_merge_by_slug(self):
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


class Derivatives(unittest.TestCase):
    """Every CAP id a page names is a derivative; nothing else makes a car, and the owner's entry stands for its own."""

    def test_a_deals_page_line_describes_a_derivative_and_the_spec_page_describes_it_better(self):
        with Raws() as raws:
            raws.add("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", at=T)
            conn = raws.build()
            stub = json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
            self.assertEqual((stub["auto"], stub["source_kind"], stub["trim"], stub["list_price_gbp"], stub["heat_pump"]),
                             (True, "stub", "Advance · 108kW 42kWh Auto", 22245.0, "unknown"))
            self.assertEqual(conn.execute("SELECT car_id FROM offer_observations WHERE offer_key='carwow:cash:110663'").fetchone()[0],
                             "carwow-cap:110663")
            self.assertEqual(conn.execute("SELECT car_id FROM offer_observations WHERE offer_key='carwow:cash:111015'").fetchone()[0],
                             "hyundai-ioniq3-61-ultimate-evpack", "the derivative the owner entered is the owner's car")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='unmapped' AND source='carwow-cap'").fetchone()[0], 0)

            raws.add("carwow_specs", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_specifications.html", at="2026-10-07T00:00:00+00:00")
            # The deals page again, later: its line never outranks the specification page.
            raws.add("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", at="2026-10-09T00:00:00+00:00")
            conn = raws.build()
            car = json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
            flags = json.loads(conn.execute("SELECT payload FROM specs WHERE spec_key='carwow-cap:110663'").fetchone()["payload"])["flags"]
            self.assertEqual((car["source_kind"], car["heat_pump"], car["seats"]), ("spec", flags["heat_pump"] or "unknown", 5))
            self.assertTrue(car["image_url"].startswith("https://car-data.carwow.co.uk/image?"))
            span = conn.execute("SELECT observed_at, confirmed_at FROM offer_observations WHERE offer_key='carwow:cash:110663'").fetchall()
            self.assertEqual([tuple(r) for r in span], [(T, "2026-10-09T00:00:00+00:00")], "the same price two days apart is one span")

    def test_the_owners_entry_is_the_one_car_for_its_derivative(self):
        with Raws() as raws:
            raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at=T)
            conn = raws.build()
            ids = {c["id"] for c in load_cars(conn)}
            for cap in KONA_CAPS:
                self.assertNotIn(f"carwow-cap:{cap}", ids, "no second car beside the owner's")
            owner = {r[0] for r in conn.execute("SELECT car_id FROM specs WHERE cap_id IN (?,?,?,?)", KONA_CAPS)}
            self.assertTrue(owner <= {"hyundai-kona-65-advance", "hyundai-kona-65-ultimate", "hyundai-kona-65-nline", "hyundai-kona-65-nlines"}, owner)
            ultimate = json.loads(conn.execute("SELECT payload FROM cars WHERE id='hyundai-kona-65-ultimate'").fetchone()["payload"])
            self.assertFalse(ultimate.get("auto"))
            self.assertIn(str(ultimate["cap_id"]), KONA_CAPS, "the owner's entry carries its CAP id")

    def test_the_latest_line_describes_a_derivative_only_a_deals_page_prints(self):
        conn = fresh_conn()
        old = {"offer_key": "carwow:cash:9", "observed_at": "2025-04-01T00:00:00+00:00", "finance_type": "cash", "status": "lead",
               "vehicle_price": 30000.0, "car_ref": {"source": "carwow-cap", "key": "9", "stub": {
                   "cap_id": "9", "make": "Kia", "model": "EV3", "trim": "Air", "engine": "150kW 58.3kWh Auto", "rrp": 33055.0,
                   "version_date": "2025-04-01"}}}
        new = json.loads(json.dumps(old))
        new.update(observed_at="2026-10-01T00:00:00+00:00")
        new["car_ref"]["stub"].update(rrp=32995.0, version_date="2026-10-01")
        build_with(conn, [(new["observed_at"], "carwow_deals", new), (old["observed_at"], "carwow_deals", old)])
        car = json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:9'").fetchone()[0])
        self.assertEqual((car["list_price_gbp"], car["version_date"]), (32995.0, "2026-10-01"))
        # The registry's line outranks any deals page's.
        conn = fresh_conn()
        build_with(conn, [(new["observed_at"], "carwow_deals", new)], registry=[ev3("9", 33500.0, "Air", "150kW 58.3kWh Auto", "2026-10-09")])
        car = json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:9'").fetchone()[0])
        self.assertEqual((car["list_price_gbp"], car["version_date"]), (33500.0, "2026-10-09"))


class Determinism(unittest.TestCase):
    """The build is a function of its inputs: the same pages, added in any order, give the same database."""

    PAGES = [("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html"),
             ("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html"),
             ("leaseloco", "hyundai/kona-electric", "leaseloco_hyundai_kona-electric.html"),
             ("carwow_deals", "kia/ev3", "carwow_kia_ev3_deals.html")]

    def test_two_builds_and_any_order_agree_row_for_row(self):
        with Raws() as a, Raws() as b:
            for p in self.PAGES:
                a.add(*p, at=T)
            for p in reversed(self.PAGES):
                b.add(*p, at=T)
            first, again, other = dump(a.build()), dump(a.build()), dump(b.build())
            self.assertEqual(first, again)
            self.assertEqual(first, other)
            self.assertGreater(len(first["offer_observations"]), 10)


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

    def test_broker_rows_match_derivatives_in_the_build(self):
        with Raws() as raws:
            raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at=T)
            raws.add("leaseloco", "hyundai/kona-electric", "leaseloco_hyundai_kona-electric.html", at=T)
            conn = fresh_conn()
            b = Build(conn, raws.store)
            b.owner()
            # Take the owner's LeaseLoco decisions out: every Kona lease is then matched by the rules.
            for k in [k for k in b.decisions if k[0] == "leaseloco"]:
                b.decisions.pop(k)
            entries = list(raws.store.entries())
            b.raws(entries)
            b.finish()
            rows = conn.execute("SELECT source_key, car_id, method, evidence FROM trim_map WHERE source='leaseloco' AND status='auto'").fetchall()
            self.assertTrue(rows, "Kona leases land on Kona derivatives")
            cap_of = {r[0]: r[1] for r in conn.execute("SELECT car_id, source_key FROM trim_map WHERE source='carwow-cap' AND status='mapped'")}
            for r in rows:
                self.assertIn(r["method"], ("trim-powertrain", "rrp", "name", "bracket", "base", "version"))
                self.assertIsNotNone(json.loads(r["evidence"]).get("score"))
                car = json.loads(conn.execute("SELECT payload FROM cars WHERE id=?", (r["car_id"],)).fetchone()["payload"])
                trim = (car.get("trim") or "").split(" · ")[0].split(" (")[0].lower().replace("-", " ")
                if car.get("auto"):
                    self.assertIn(trim, r["source_key"].replace("-", " "), f"{r['source_key']} -> {car['trim']}")
                else:
                    self.assertIn(r["car_id"], cap_of, "a match on a derivative the owner entered is the owner's car")


class ResolutionRules(unittest.TestCase):
    """services/resolve.py: twins of one trim and powertrain, told apart by RRP, bracket, version."""

    def twins(self):
        return [
            {"id": "carwow-cap:1", "auto": True, "trim": "GT-Line S · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto",
             "list_price_gbp": 43055.0, "version_date": "2025-10-01", "seats": 5},
            {"id": "carwow-cap:2", "auto": True, "trim": "GT-Line S · 150kW 81.4kWh Auto", "variant": "150kW 81.4kWh Auto",
             "list_price_gbp": 43955.0, "version_date": "2025-10-01", "seats": 5},
        ]

    def test_rrp_pins_the_twin(self):
        from pipeline.services import resolve
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto", "rrp": 43955.0}, self.twins())
        self.assertEqual((r.car_id, r.method), ("carwow-cap:2", "rrp"))
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto", "rrp": 43053.0}, self.twins())
        self.assertEqual((r.car_id, r.method), ("carwow-cap:1", "rrp"), "within a few pounds counts")

    def test_bracket_goes_to_the_dearer_twin_and_says_what_it_is(self):
        from pipeline.services import resolve
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]"}, self.twins())
        self.assertEqual((r.car_id, r.method, r.brackets), ("carwow-cap:2", "bracket", ["Heat Pump"]))
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto [No Heat Pump]"}, self.twins())
        self.assertEqual((r.car_id, r.method), ("carwow-cap:1", "base"))
        self.assertEqual(r.brackets, ["No Heat Pump"])
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto"}, self.twins())
        self.assertEqual((r.car_id, r.method), ("carwow-cap:1", "base"))
        self.assertEqual(resolve.pack_brackets("x [6St] [Tech Pack]"), ["Tech Pack"])

    def test_three_prices_and_a_pack_is_a_conflict_not_a_guess(self):
        from pipeline.services import resolve
        three = self.twins() + [{"id": "carwow-cap:3", "auto": True, "trim": "GT-Line S · 150kW 81.4kWh Auto",
                                 "variant": "150kW 81.4kWh Auto", "list_price_gbp": 45455.0, "version_date": "2025-10-01"}]
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto [Tech Pack]"}, three)
        self.assertEqual((r.car_id, r.method), (None, "conflict"))
        self.assertEqual(r.evidence["packs"], ["Tech Pack"])
        # ... unless the broker's RRP settles it.
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto [Tech Pack]", "rrp": 45455.0}, three)
        self.assertEqual((r.car_id, r.method), ("carwow-cap:3", "rrp"))

    def test_identical_prices_take_the_current_version(self):
        from pipeline.services import resolve
        same = [dict(self.twins()[0], list_price_gbp=39995.0, version_date="2025-04-01"),
                dict(self.twins()[1], list_price_gbp=39995.0, version_date="2026-09-30")]
        r = resolve.choose({"derivative": "150kW GT-Line S 81.4kWh 5dr Auto"}, same)
        self.assertEqual((r.car_id, r.method), ("carwow-cap:2", "version"))

    def test_a_pin_from_one_source_is_reused_by_another(self):
        from pipeline.services import resolve
        text = "150kW GT-Line S 81.4kWh 5dr Auto"
        r = resolve.choose({"derivative": text}, self.twins(), {resolve.name_key(text): {"carwow-cap:2"}})
        self.assertEqual((r.car_id, r.method), ("carwow-cap:2", "name"), "NCD's RRP pinned the dearer twin; LeaseLoco's identical name follows it")
        r = resolve.choose({"derivative": text}, self.twins(), {resolve.name_key(text): {"carwow-cap:1", "carwow-cap:2"}})
        self.assertEqual(r.method, "base", "a name pinned to both twins pins neither")

    def test_in_the_build_the_name_rule_reads_every_records_rrp_whatever_order_they_came_in(self):
        text = "150kW GT-Line S 81.4kWh 5dr Auto"
        ncd = {"offer_key": "ncd:1", "finance_type": "cash", "status": "lead", "vehicle_price": 41000.0,
               "car_ref": {"source": "ncd", "key": "kia|ev3|x", "make": "Kia", "model": "EV3", "derivative": text, "rrp": 43955.0}}
        ll = {"offer_key": "leaseloco:1", "finance_type": "pch", "status": "lead", "monthly_payment": 399.0,
              "car_ref": {"source": "leaseloco", "key": "kia|ev3|y", "make": "Kia", "model": "EV3", "derivative": text}}
        twins = [ev3("1", 43055.0), ev3("2", 43955.0)]
        for order in ([("2026-10-01", "ncd", ncd), ("2026-10-02", "leaseloco", ll)], [("2026-10-01", "leaseloco", ll), ("2026-10-02", "ncd", ncd)]):
            conn = fresh_conn()
            build_with(conn, order, registry=twins)
            got = dict(conn.execute("SELECT offer_key, car_id FROM offer_observations WHERE offer_key IN ('ncd:1', 'leaseloco:1')").fetchall())
            self.assertEqual(got, {"ncd:1": "carwow-cap:2", "leaseloco:1": "carwow-cap:2"})
            self.assertEqual(conn.execute("SELECT method FROM trim_map WHERE source='leaseloco' AND source_key='kia|ev3|y'").fetchone()[0], "name")

    def test_a_bracket_says_something_of_its_derivative_and_nothing_is_written_on_the_car(self):
        from pipeline.services import claims
        from pipeline.services.snapshot import load_broker_names
        conn = fresh_conn()
        row = {"offer_key": "leaseloco:2", "finance_type": "pch", "status": "lead", "monthly_payment": 399.0,
               "car_ref": {"source": "leaseloco", "key": "kia|ev3|x [heat pump]", "make": "Kia", "model": "EV3",
                           "label": "Kia EV3 150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]",
                           "derivative": "150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]"}}
        build_with(conn, [("2026-10-01", "leaseloco", row)], registry=[ev3("1", 43055.0), ev3("2", 43955.0)])
        self.assertEqual(tuple(conn.execute("SELECT car_id, status, method FROM trim_map WHERE source='leaseloco' AND source_key='kia|ev3|x [heat pump]'").fetchone()),
                         ("carwow-cap:2", "auto", "bracket"))
        self.assertNotIn("packs", json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:2'").fetchone()[0]))
        cars = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM cars")]
        claims.resolve_all(cars, claims.build_store(cars, [], [], [], [], load_broker_names(conn)))
        self.assertEqual(next(c for c in cars if c["id"] == "carwow-cap:2")["heat_pump"], "standard")


class OffersFollowTheirMatch(unittest.TestCase):
    def test_an_offer_keys_whole_history_sits_on_the_car_its_latest_sighting_names(self):
        conn = fresh_conn()
        base = {"offer_key": "x:1", "finance_type": "cash", "status": "lead", "vehicle_price": 30000.0}
        first = dict(base, car_ref={"source": "carwow-cap", "key": "1"})
        later = dict(base, car_ref={"source": "carwow-cap", "key": "2"})
        build_with(conn, [("2026-01-01T00:00:00+00:00", "t", first), ("2026-02-01T00:00:00+00:00", "t", later)],
                   registry=[ev3("1", 33055.0, "Air", "150kW 58.3kWh Auto"), ev3("2", 33055.0, "Air", "150kW 58.3kWh Auto")])
        rows = conn.execute("SELECT car_id, observed_at, confirmed_at FROM offer_observations WHERE offer_key='x:1'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("carwow-cap:2", "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00")],
                         "same price a month on: one span, on the car the offer now names")


if __name__ == "__main__":
    unittest.main()
