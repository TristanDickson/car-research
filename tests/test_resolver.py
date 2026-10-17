"""The resolver (services/resolver.py, BOARD.md T3), built from real pages: Parkers' spec sitemaps (a slice: the Kona
Electric's two generations, the Q4 e-tron, the Ioniq 5, the Ioniq Electric, the Soul) and two first-generation Kona
derivative pages; Carwow's Audi, Hyundai and Kia catalogue pages, the Kona Electric's and the Ioniq 3's registry
tables, the Kona Electric's specification page and the Ioniq 3's deals page; Hyundai's configurator for the Ioniq 3;
LeaseLoco's Kona Electric page; and a page of cinch's used Hyundais of 15 Oct 2026 with six first-generation Konas.

The rule tests further down read names exactly as Parkers, Carwow and the brokers print them."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.providers import carwow_model, cinch_used
from pipeline.services import model_map, resolver as R
from pipeline.services.snapshot import export_snapshot
from tests.helpers import FIX, Raws, dump

T = "2026-10-17T03:00:00+00:00"
KONA_2018 = ("150kw-ultimate-64kwh-5dr-auto", "premium-se-64-kwh-battery-204ps-auto-5d")
REGISTRY = {"hyundai/kona-electric": ("Hyundai", "Kona Electric"), "hyundai/ioniq-3": ("Hyundai", "Ioniq 3")}
CINCH_MODELS = [{"make": "hyundai", "model": m, "make_name": "Hyundai", "model_name": n}
                for m, n in (("kona-electric", "Kona Electric"), ("ioniq-5", "Ioniq 5"), ("ioniq-9", "Ioniq 9"), ("ioniq-electric", "Ioniq electric"))]


def adds() -> list[tuple]:
    out = []
    for make in ("audi", "hyundai", "kia"):
        out.append(("carwow_catalog", f"brand/{make}", f"carwow_brand_{make}_electric.html",
                    {"url": f"https://www.carwow.co.uk/{make}/electric", "kind": "brand", "make": make}, None, None))
    for slug, (make_name, model_name) in REGISTRY.items():
        make, model = slug.split("/")
        out.append(("carwow_model", slug, f"carwow_{make}_{model}_model_trims.html",
                    {"make": make, "model": model, "make_name": make_name, "model_name": model_name, "url": carwow_model.url_for(make, model)},
                    None, None))
    out.append(("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", None, None, None))
    out.append(("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", None, None, None))
    out.append(("hyundai_configurator", "ioniq-3", "hyundai_configurator_ioniq3.json", None, None, None))
    out.append(("leaseloco", "hyundai/kona-electric", "leaseloco_hyundai_kona-electric.html", None, None, None))
    out.append(("parkers", "spec-1", "parkers_sitemap_t2_slice.xml", {"url": "https://www.parkers.co.uk/sitemap/zip-files/spec-1.xml.gz"}, "sitemap", None))
    for leaf in KONA_2018:
        path = f"hyundai/kona-electric/suv-2018/{leaf}"
        out.append(("parkers", path, f"parkers_kona-electric_suv-2018_{leaf}.html",
                    {"url": f"https://www.parkers.co.uk/{path}/specs/", "make_slug": "hyundai", "model_slug": "kona-electric",
                     "generation": "suv-2018"}, "pages", None))
    page = json.loads((FIX / "cinch_used_hyundai_2026-10-15_p1.json").read_text(encoding="utf-8"))
    out.append(("cinch_used", "hyundai", None, {"make": "hyundai", "url": cinch_used.api_url("hyundai"), "models": CINCH_MODELS}, None,
                json.dumps({"make": "hyundai", "pages": [page]}).encode("utf-8")))
    return out


def build(order=lambda xs: xs, resolve=True):
    with Raws() as raws:
        for provider, ident, fixture, meta, cap, body in order(adds()):
            raws.add(provider, ident, fixture, body=body, metadata=meta, capability=cap, at=T)
        if resolve:
            return raws.build()
        with mock.patch.object(R, "run", lambda conn: None):
            return raws.build()


def links(conn) -> dict[tuple[str, str], dict]:
    return {(r["source"], r["record_key"]): {**dict(r), "payload": json.loads(r["payload"])} for r in conn.execute("SELECT * FROM resolver_links")}


class Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = build()
        cls.links = links(cls.conn)
        cls.cars = {r["id"]: json.loads(r["payload"]) for r in cls.conn.execute("SELECT id, payload FROM resolver_cars")}

    def derivative(self, cap: str) -> dict:
        return self.links[("carwow", cap)]

    def test_every_parkers_derivative_is_a_car_old_generations_included(self):
        kona = {c["generation"] for c in self.cars.values() if c["model"] == "kona-electric" and c["source"] == "parkers"}
        self.assertEqual(kona, {"suv-2018", "suv-2023"})
        page = next(c for c in self.cars.values() if "Premium SE 64 kWh Battery 204PS auto 5d" in c["names"])
        self.assertEqual(page["id"], "hyundai/kona-electric/suv-2018/150kw-premium-se-64kwh-5dr", "its id is built from its details")
        self.assertEqual((page["since"], page["until"], page["trim"], page["kw"]), ("2019-12", "2021-01", "premium se", 150))
        self.assertIn("premium se electric 64 kwh battery 204ps auto 5d", page["names"],
                      "the sitemap's address of the same derivative in the older naming is the same car")

    def test_a_first_generation_kona_is_not_the_2023_car(self):
        """BOARD.md, T3: 2021 Konas counted as the 2023-on car."""
        used = {k: v for k, v in self.links.items() if k[0] == "cinch_used" and v["model"] == "hyundai/kona-electric"}
        old = [v for v in used.values() if (v["payload"]["details"].get("date") or "") < "2023"]
        self.assertGreaterEqual(len(old), 5)
        for v in old:
            self.assertTrue((v["car_id"] or v["version"] or "").startswith("hyundai/kona-electric/suv-2018/"), v["payload"]["why"])
        premium = [v for v in old if v["payload"]["label"].endswith("150kW Premium 64kWh 5dr Auto (2022)")]
        self.assertEqual({v["car_id"] for v in premium}, {"hyundai/kona-electric/suv-2018/150kw-premium-64kwh-5dr"})
        self.assertIn("motor", premium[0]["payload"]["decided_by"], "its 150 kW motor rules out the 2023 cars' 160 kW")

    def test_the_configurator_rows_reach_the_derivatives_only_the_deals_page_names(self):
        """BOARD.md, T3: the Ioniq 3 Ultimate with the Design Pack is named only by Carwow's deals page."""
        self.assertEqual(self.derivative("111017")["status"], "new car", "Parkers files no Ioniq 3, so Carwow's derivatives are its cars")
        design = self.links[("hyundai_configurator", "6JW5ZFZ7ZHH157")]
        self.assertEqual(design["car_id"], self.derivative("111017")["car_id"])
        self.assertIn("list price", design["payload"]["decided_by"])
        self.assertEqual(design["outcome"], "newly placed", "today's lookups match configurations only against the registry")
        placed = [v for k, v in self.links.items() if k[0] == "hyundai_configurator"]
        self.assertTrue(placed and all(v["car_id"] for v in placed))

    def test_a_record_printing_a_cap_id_goes_where_its_derivative_went(self):
        for (src, key), v in self.links.items():
            if src == "carwow_deals" and key.startswith("carwow:cash:"):
                self.assertEqual(v["car_id"], self.derivative(key.rsplit(":", 1)[1])["car_id"])
                self.assertEqual(v["payload"]["decided_by"][0], "CAP id")

    def test_the_kona_s_registry_lines_are_parkers_cars(self):
        for cap in ("103322", "103325", "103326"):
            car = self.derivative(cap)["car_id"]
            self.assertTrue(car.startswith("hyundai/kona-electric/suv-2023/"), car)
            self.assertEqual(self.cars[car]["source"], "parkers")

    def test_every_link_says_why(self):
        self.assertTrue(self.links)
        for k, v in self.links.items():
            self.assertTrue(v["payload"]["why"], k)
            if v["kind"] != "derivative":
                self.assertIn(v["outcome"], R.OUTCOMES, k)

    def test_the_comparison_reaches_the_snapshot_and_the_cars_do_not_change(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            export_snapshot(self.conn, a, generated_at=T)
            export_snapshot(build(resolve=False), b, generated_at=T)
            data = json.loads((Path(a) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("cinch_used", data["resolver"]["by_source"])
            self.assertGreater(data["resolver"]["by_source"]["hyundai_configurator"]["newly placed"], 0)
            self.assertTrue(data["resolver"]["changes"])
            for f in ("cars.json", "sightings.json", "used.json", "specs.json"):
                self.assertEqual((Path(a) / f).read_text(encoding="utf-8"), (Path(b) / f).read_text(encoding="utf-8"), f)

    def test_the_order_the_pages_were_read_in_decides_nothing(self):
        again = build(order=lambda xs: list(reversed(xs)))
        for table in ("resolver_cars", "resolver_links"):
            self.assertEqual(dump(again)[table], dump(self.conn)[table], table)

    def test_the_order_the_records_come_in_decides_nothing(self):
        mapping = model_map.load(self.conn)
        parkers, _ = R.master_list(self.conn)
        comps, raw = R.compounds(self.conn, R.today_facts(self.conn))
        derivs = {cap: R.derivative_compound(cap, d, ()) for cap, d in raw.items()}
        base = R.resolve(parkers, comps, derivs, mapping)
        for seed in (1, 2, 3):
            rnd = random.Random(seed)
            cs, ds, ps = list(comps), list(derivs.items()), list(parkers.items())
            rnd.shuffle(cs)
            rnd.shuffle(ds)
            rnd.shuffle(ps)
            got = R.resolve(dict(ps), cs, dict(ds), list(reversed(mapping)))
            self.assertEqual({k: l.row() for k, l in got.links.items()}, {k: l.row() for k, l in base.links.items()}, seed)
            self.assertEqual({k: l.row() for k, l in got.derivatives.items()}, {k: l.row() for k, l in base.derivatives.items()}, seed)
            self.assertEqual(sorted(got.cars), sorted(base.cars), seed)
        self.assertTrue(base.converged)


def car(cars: dict, path: str, name: str, trims=(), since=None, until=None, price=None) -> R.Car:
    """A Parkers derivative onto `cars`, as master_list adds one from its page."""
    mk, md, gen, leaf = path.split("/")
    trims = [tuple(R._words(t, mk)) for t in trims]
    page = {"name": name, "on_sale_since": since, "on_sale_until": until, "price_new": price, "numbers": {}}
    return R.add_entry(cars, f"{path}/{leaf}", mk, md, gen, name, trims, page)


def resolver_for(cars: dict, model: str) -> R.Resolver:
    for c in cars.values():
        c.version = R.version_of(c)
    mapping = [{"slug": model, "parkers": "/".join(next(iter(cars.values())).id.split("/")[:2]),
                "generations": [{"generation": g} for g in sorted({c.generation for c in cars.values()})]}]
    return R.Resolver(cars, *R._model_pools(cars, mapping))


class Names(unittest.TestCase):
    def key(self, name: str, trim: tuple = ()) -> str:
        return R.car_key("audi", "q4-e-tron", "suv-2021", trim, R.read(name, "audi"))

    def test_two_names_that_read_alike_are_one_car(self):
        self.assertEqual(self.key("250kW Qtro Perf 82kWh S Line 5dr Auto [Tech Pack]", ("s", "line")),
                         self.key("250kW Quattro Performance 82kWh S Line 5dr Auto [Tech Pack]", ("s", "line")))
        old, new = R.read("Premium SE 64 kWh Battery 204PS auto 5d", "hyundai"), R.read("150kW Premium SE 64kWh 5dr Auto", "hyundai")
        self.assertEqual((old.kw, old.kwh, old.doors), (150, 64.0, 5), "204 PS is 150 kW; '5d' is five doors")
        self.assertEqual(R.car_key("hyundai", "kona-electric", "suv-2018", ("premium", "se"), old),
                         R.car_key("hyundai", "kona-electric", "suv-2018", ("premium", "se"), new))

    def test_a_pack_with_a_plus_is_another_pack(self):
        self.assertNotEqual(self.key("450e 230kW Direct4 71.4 kWh 5dr Auto [Premium +]"), self.key("450e 230kW Direct4 71.4 kWh 5dr Auto [Premium]"))

    def test_the_drive_a_name_prints(self):
        for name, drive in (("200kW 100kWh Long Range Dual Motor Plus 5dr Auto", "awd"), ("210kW 85x 82kWh Sportline 5dr Auto", "awd"),
                            ("230kW xDrive30 M Sport 65kWh 5dr Auto", "awd"), ("200kW 100kWh Rear Motor Prime 5dr Auto", None),
                            ("239kW GT-Line S 77.4kWh 5dr AWD Auto", "awd"), ("Long Range RWD 4dr Auto", "rwd")):
            self.assertEqual(R.read(name).drive, drive, name)


class Rules(unittest.TestCase):
    def test_a_price_list_s_new_price_rules_nothing_out(self):
        """The Polestar 4 Rear Motor Prime at £60,750 on Parkers and on Carwow's June list, £58,750 on its September list."""
        cars = {}
        car(cars, "polestar/4/suv-2024/x", "200kW 100kWh Rear Motor Prime 5dr Auto", ("prime",), "2026-06", None, 60750.0)
        car(cars, "polestar/4/suv-2024/y", "200kW 100kWh Rear Motor Business 5dr Auto", ("business",), "2026-06", None, 56750.0)
        res = resolver_for(cars, "polestar/4-suv")
        c = R.compound("carwow", "derivative", "111294", "200kW 100kWh Rear Motor Prime 5dr Auto", make="Polestar", model="polestar/4-suv",
                       name="200kW 100kWh Rear Motor Prime 5dr Auto", trim="Prime", price=58750.0, date="2026-09-01", date_kind="listed")
        link = res.place(c, R.Evidence())
        self.assertEqual((link.status, link.car), ("placed", "polestar/4/suv-2024/200kw-prime-rear-100kwh-5dr"))

    def test_a_price_another_generation_had_rules_nothing_out(self):
        """Carwow's 48 kWh Kona Advance at £34,995, Parkers' price for the first generation's Premium 39 kWh."""
        cars = {}
        car(cars, "hyundai/kona-electric/suv-2018/a", "100kW Premium 39kWh 5dr Auto", ("premium",), "2021-03", "2023-06", 34995.0)
        car(cars, "hyundai/kona-electric/suv-2023/b", "115kW Advance 48kWh 5dr Auto", ("advance",), "2023-07", None, 32390.0)
        res = resolver_for(cars, "hyundai/kona-electric")
        c = R.compound("carwow", "derivative", "103320", "Advance 115kW 48kWh Auto", make="Hyundai", model="hyundai/kona-electric",
                       trim="Advance", price=34995.0, date="2026-10-16", date_kind="listed")
        self.assertEqual(res.place(c, R.Evidence()).car, "hyundai/kona-electric/suv-2023/115kw-advance-48kwh-5dr")

    def test_pages_that_share_a_car_agree_whichever_comes_first(self):
        """Two of Parkers' BMW i3 addresses read as one car; one page prints the battery, the other does not."""
        pages = [("bmw/i3/hatchback-2013/a", {"name": "Interior Lodge World 5dr", "numbers": {"battery_kwh": 33.2, "power_bhp": 168}}),
                 ("bmw/i3/hatchback-2013/b", {"name": "Interior Lodge World 5dr Auto", "numbers": {}})]
        got = []
        for order in (pages, list(reversed(pages))):
            cars = {}
            for path, page in order:
                R.add_entry(cars, path, "bmw", "i3", "hatchback-2013", page["name"], [], page)
            (only,) = cars.values()
            got.append((only.id, only.kw, only.kwh, sorted(only.names)))
        self.assertEqual(got[0], got[1])
        self.assertEqual(got[0][1:3], (125, 33.2))

    def test_a_price_that_is_another_car_s_contradicts_the_text(self):
        """A dealer's line copied from another derivative: an 'Air' at the GT-Line's list price fits neither."""
        cars = {}
        car(cars, "kia/ev6/suv-2021/a", "168kW Air 84kWh 5dr Auto", ("air",), "2024-09", None, 45875.0)
        car(cars, "kia/ev6/suv-2021/b", "168kW GT-Line 84kWh 5dr Auto", ("gt-line",), "2024-09", None, 52835.0)
        res = resolver_for(cars, "kia/ev6")
        c = R.compound("rrg", "offer", "rrg:x", "'Air' 84kWh 225bhp RWD Automatic", make="Kia", model="kia/ev6", price=52835.0,
                       date="2026-10-16", date_kind="seen")
        link = res.place(c, R.Evidence())
        self.assertEqual(link.status, "listed")
        self.assertIn("is the list price of kia/ev6/suv-2021/168kw-gt-line-84kwh-5dr", link.why)

    def test_a_black_edition_lease_is_the_black_edition(self):
        """BOARD.md, T3: two EX30 'Twin Motor Performance Black Edition' leases went on the plain trim."""
        cars = {}
        trims = ("plus", "plus black edition")
        car(cars, "volvo/ex30/suv-2024/a", "315kW TM Performance Plus 69kWh 5dr Auto", trims, "2024-02")
        car(cars, "volvo/ex30/suv-2024/b", "315kW TM Performance Plus Black Ed 69kWh 5dr Auto", trims, "2024-09")
        res = resolver_for(cars, "volvo/ex30")
        c = R.compound("leaseloco", "offer", "leaseloco:55579", "315kW TM Performance Plus Black Ed 69kWh 5dr Auto [5 seat]", make="Volvo",
                       model="volvo/ex30", name="315kW TM Performance Plus Black Ed 69kWh 5dr Auto", date="2026-10-16", date_kind="seen")
        link = res.place(c, R.Evidence())
        self.assertEqual((link.status, link.car), ("placed", "volvo/ex30/suv-2024/315kw-plus-black-edition-performance-twin-69kwh-5dr"))

    def test_a_cap_style_name_that_leaves_out_a_trim_is_not_that_trim(self):
        """LeaseLoco prints the RZ 450e's Premium + pack unbracketed; it is not the Takumi, and it is the Premium + pack."""
        cars = {}
        trims = ("takumi", "urban")
        car(cars, "lexus/rz/suv-2022/a", "450e 230kW Direct4 Takumi 71.4 kWh 5dr Auto", trims, "2022-07", "2026-05", 65735.0)
        car(cars, "lexus/rz/suv-2022/b", "450e 230kW Direct4 71.4 kWh 5dr Auto [Premium +]", trims, "2022-07", "2026-04", 61085.0)
        car(cars, "lexus/rz/suv-2022/c", "450e 230kW Direct4 71.4 kWh 5dr Auto [Premium]", trims, "2022-07", "2026-04", 58035.0)
        res = resolver_for(cars, "lexus/rz")
        c = R.compound("leaseloco", "offer", "leaseloco:40605", "450e 230kW Direct4 Premium + 71 kWh 5dr Auto", make="Lexus", model="lexus/rz",
                       name="450e 230kW Direct4 Premium + 71 kWh 5dr Auto", date="2026-10-16", date_kind="seen")
        link = res.place(c, R.Evidence())
        self.assertEqual((link.status, link.car), ("placed", "lexus/rz/suv-2022/230kw-450e-direct4-71-4kwh-5dr-with-premium-plus"))
        self.assertIn("packs", link.decided_by)

    def test_a_used_card_of_price_and_year_stays_at_its_model(self):
        cars = {}
        car(cars, "hyundai/kona-electric/suv-2023/a", "160kW Ultimate 65kWh 5dr Auto", ("ultimate",), "2023-07")
        car(cars, "hyundai/kona-electric/suv-2023/b", "115kW Advance 48kWh 5dr Auto", ("advance",), "2023-07", "2025-05")
        res = resolver_for(cars, "hyundai/kona-electric")
        c = R.compound("carwow_used", "used", "carwow-used:x", "", make="Hyundai", model="hyundai/kona-electric", date="2024-06", date_kind="registered")
        link = res.place(c, R.Evidence())
        self.assertEqual((link.level, link.status, link.car), ("model", "model", None))


if __name__ == "__main__":
    unittest.main()
