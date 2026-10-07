"""Spec providers against saved pages, the feature-flag mapping, and specs flowing
through the runner into gold with the trim map."""
import json
import unittest
from pathlib import Path

from pipeline.providers import carwow_specs, kia_specs
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from pipeline.services.features import flags_for
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-06T00:00:00+00:00"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


class Flags(unittest.TestCase):
    def test_wording_from_both_sources_maps_to_the_same_flags(self):
        carwow = flags_for(["Heat pump", "V2L (Vehicle to Load) - Inside", "Heated front seats"])
        kia = flags_for(["Vehicle-to-Load (V2L) Capability", "Vehicle-to-Load (V2L) Capability with Adapter", "Heated Front Seats"], ["Heat Pump"])
        self.assertEqual((carwow["heat_pump"], carwow["v2l_internal"], carwow["v2l_external"], carwow["heated_front_seats"]), ("standard", "standard", None, "standard"))
        self.assertEqual((kia["heat_pump"], kia["v2l_internal"], kia["v2l_external"], kia["heated_front_seats"]), ("option", "standard", "standard", "standard"))
        self.assertIsNone(flags_for([])["heat_pump"])


class CarwowSpecs(unittest.TestCase):
    def test_kona_trims(self):
        rows = carwow_specs.parse_page(fixture("carwow_hyundai_kona-electric_specifications.html"), "hyundai", "kona-electric", "u", T)
        self.assertEqual([r["cap_id"] for r in rows], ["103322", "103324", "103325", "103326"])
        adv = rows[0]
        self.assertEqual((adv["trim"], adv["engine"], adv["rrp"], adv["carwow_price"], adv["version_date"]), ("Advance", "160kW 65kWh Auto", 35000.0, 27795.0, "2026-10-01"))
        self.assertEqual(adv["car_ref"], {"source": "carwow-cap", "key": "103322", "label": "Hyundai Kona Electric 160kW 65kWh Auto · Advance · RRP £35,000"})
        self.assertGreater(len(adv["features"]), 80)
        self.assertIn("Heat pump", adv["features"])
        self.assertEqual(adv["flags"]["heat_pump"], "standard")
        self.assertEqual(adv["flags"]["v2l_internal"], "standard")  # Carwow says so; the seed disagrees, which spec_check surfaces
        self.assertEqual((adv["numbers"]["seats"], adv["numbers"]["boot_l"], adv["numbers"]["wltp_range_mi"], adv["numbers"]["zero_to_60_s"], adv["numbers"]["power_bhp"]),
                         (5, 466.0, 319.0, 7.8, 218.0))
        self.assertIn("derivative_id%5D=103322", adv["image_url"])
        self.assertIn("size%5D=800", adv["image_url"])
        ult = rows[2]
        self.assertEqual(ult["flags"]["heated_front_seats"], "standard")

    def test_pv5_page(self):
        rows = carwow_specs.parse_page(fixture("carwow_kia_pv5-passenger_specifications.html"), "kia", "pv5-passenger", "u", T)
        by_cap = {r["cap_id"]: r for r in rows}
        self.assertEqual(by_cap["110972"]["trim"], "Elite")
        self.assertEqual(by_cap["110972"]["flags"]["heat_pump"], "standard")
        self.assertEqual(by_cap["110972"]["numbers"]["wltp_range_mi"], 256.0)


class KiaSpecs(unittest.TestCase):
    def test_ev3_grades_powertrains_and_heat_pump_variant(self):
        rows = kia_specs.parse_page(fixture("kia_ev3_specification.html"), "ev3", "u", T)
        keys = [r["spec_key"] for r in rows]
        self.assertEqual(keys, ["kia-spec:ev3:air:58-3-kwh-fwd", "kia-spec:ev3:air:81-4-kwh-fwd", "kia-spec:ev3:gt-line:81-4-kwh-fwd",
                                "kia-spec:ev3:gt-line-s:81-4-kwh-fwd", "kia-spec:ev3:gt-line-s-heat-pump:81-4-kwh-fwd", "kia-spec:ev3:gt:81-4-kwh-awd"])
        gts = rows[3]
        self.assertEqual(gts["flags"]["heat_pump"], "option")
        self.assertIn("Heat Pump", gts["options"])
        self.assertEqual(gts["flags"]["v2l_internal"], "standard")
        self.assertEqual((gts["numbers"]["wltp_range_mi"], gts["numbers"]["zero_to_62_s"], gts["numbers"]["power_bhp"], gts["numbers"]["insurance_group"]), (362.0, 7.9, 201.0, "37D"))
        hp = rows[4]
        self.assertEqual(hp["flags"]["heat_pump"], "standard")
        self.assertEqual(hp["numbers"]["wltp_range_mi"], 361.0)
        self.assertEqual(hp["car_ref"]["key"], "kia|ev3|gt-line s heat pump|81.4kwh fwd|")
        self.assertEqual(rows[0]["numbers"]["length_mm"], 4300.0)
        self.assertEqual(rows[5]["numbers"]["drive"], "AWD")

    def test_pv5_seat_variants(self):
        rows = kia_specs.parse_page(fixture("kia_pv5-passenger_specification.html"), "pv5-passenger", "u", T)
        keys = {r["spec_key"] for r in rows}
        self.assertIn("kia-spec:pv5-passenger:elite:71-2-kwh-fwd:7seat", keys)
        self.assertIn("kia-spec:pv5-passenger:essential:51-5-kwh-fwd:5seat", keys)
        self.assertNotIn("kia-spec:pv5-passenger:essential:51-5-kwh-fwd:7seat", keys, "standard range is 5-seat only")
        elite7 = next(r for r in rows if r["spec_key"].endswith("elite:71-2-kwh-fwd:7seat"))
        self.assertEqual((elite7["seats"], elite7["numbers"]["wltp_range_mi"], elite7["flags"]["heat_pump"]), (7, 246.0, "standard"))
        self.assertEqual(elite7["car_ref"]["key"], "kia|pv5-passenger|elite|71.2kwh fwd|7-seat")

    def test_ev2_and_ev6_shapes(self):
        ev2 = kia_specs.parse_page(fixture("kia_ev2_specification.html"), "ev2", "u", T)
        self.assertEqual([r["trim"] for r in ev2], ["Air", "First Edition", "GT-Line", "GT-Line S"])
        self.assertEqual(ev2[1]["numbers"]["battery_kwh"], 42.2)
        self.assertEqual(ev2[3]["flags"]["heat_pump"], "option")
        ev6 = kia_specs.parse_page(fixture("kia_ev6_specification.html"), "ev6", "u", T)
        self.assertIn("kia-spec:ev6:gt-line-s:84-kwh-rwd-225-bhp", [r["spec_key"] for r in ev6])
        self.assertEqual(next(r for r in ev6 if r["trim"] == "GT-Line" and r["numbers"]["drive"] == "RWD")["numbers"]["wltp_range_mi"], 361.0)


def _fixture_provider(module, name, files: dict[str, str]) -> Provider:
    cap = module.provider.capability_for(None)

    def discover(target, ctx):
        for t in cap.discover(target, ctx):
            if t.identifier in files:
                yield t

    def fetch(target, ctx):
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes())

    c = Capability(cap.name, cap.parser_version, discover, fetch, cap.parse, cap.kinds)
    return Provider(name, c.name, {c.name: c}, live=False)


class ThroughTheRunner(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)

    def test_specs_land_in_gold_mapped_or_not(self):
        p = _fixture_provider(carwow_specs, "carwow_specs", {"hyundai/kona-electric": "carwow_hyundai_kona-electric_specifications.html",
                                                              "hyundai/ioniq-3": "carwow_hyundai_ioniq-3_specifications.html"})
        res = run(self.conn, p, ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.unmapped), (0, 0), "untracked variants are not mapping tasks")
        rows = self.conn.execute("SELECT spec_key, car_id, image_url FROM specs ORDER BY spec_key").fetchall()
        self.assertEqual(len(rows), 9)
        by = {r["spec_key"]: r for r in rows}
        self.assertEqual(by["carwow-cap:103322"]["car_id"], "hyundai-kona-65-advance")
        self.assertEqual(by["carwow-cap:110664"]["car_id"], "hyundai-ioniq3-61-advance")
        # The 42kWh Ioniq 3 is 'ignored' in the trim map (no hand-curated car): it gets a generated car.
        self.assertEqual(by["carwow-cap:110663"]["car_id"], "carwow-cap:110663")
        auto = json.loads(self.conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
        self.assertEqual((auto["auto"], auto["make"], auto["model"], auto["trim"], auto["list_price_gbp"], auto["model_year"]),
                         (True, "Hyundai", "Ioniq 3", "Advance · 108kW 42kWh Auto", 22245.0, 2026))
        flags = json.loads(self.conn.execute("SELECT payload FROM specs WHERE spec_key='carwow-cap:110663'").fetchone()["payload"])["flags"]
        self.assertEqual(auto["heat_pump"], flags["heat_pump"] or "unknown", "tri-state from the equipment list; absence is 'unknown', not 'none'")
        self.assertEqual(auto["internal_v2l"], "unknown")
        self.assertEqual(self.conn.execute("SELECT status, car_id FROM trim_map WHERE source='carwow-cap' AND source_key='110663'").fetchone()[:],
                         ("auto", "carwow-cap:110663"))
        self.assertTrue(by["carwow-cap:103322"]["image_url"].startswith("https://car-data.carwow.co.uk/image?"))
        # No unmapped rows were recorded for the untracked derivatives.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='unmapped'").fetchone()[0], 0)
        # Re-running is an upsert: same count, changed_at untouched when nothing changed.
        first = self.conn.execute("SELECT changed_at, last_seen_at FROM specs WHERE spec_key='carwow-cap:103322'").fetchone()
        run(self.conn, p, ctx=Context(root=FIX))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM specs").fetchone()[0], 9)
        second = self.conn.execute("SELECT changed_at, last_seen_at FROM specs WHERE spec_key='carwow-cap:103322'").fetchone()
        self.assertEqual(first["changed_at"], second["changed_at"])
        self.assertGreaterEqual(second["last_seen_at"], first["last_seen_at"])

    def test_kia_specs_resolve_through_seeded_map(self):
        p = _fixture_provider(kia_specs, "kia_specs", {"ev3": "kia_ev3_specification.html", "pv5-passenger": "kia_pv5-passenger_specification.html"})
        run(self.conn, p, ctx=Context(root=FIX))
        m = {r["spec_key"]: r["car_id"] for r in self.conn.execute("SELECT spec_key, car_id FROM specs")}
        self.assertEqual(m["kia-spec:ev3:gt-line-s-heat-pump:81-4-kwh-fwd"], "kia-ev3-81-gtlines-hp")
        self.assertEqual(m["kia-spec:pv5-passenger:elite:71-2-kwh-fwd:7seat"], "kia-pv5-passenger-71-elite-7seat")
        self.assertIsNone(m["kia-spec:ev3:air:58-3-kwh-fwd"])

    def test_specs_round_trip_through_history_and_into_the_snapshot(self):
        import tempfile
        from pipeline.history import export_specs, import_specs
        from pipeline.services.snapshot import export_snapshot
        p = _fixture_provider(carwow_specs, "carwow_specs", {"hyundai/kona-electric": "carwow_hyundai_kona-electric_specifications.html"})
        run(self.conn, p, ctx=Context(root=FIX))
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "specs.jsonl"
            self.assertEqual(export_specs(self.conn, f), 4)
            other = fresh_conn()
            run_all(other)
            self.assertEqual(import_specs(other, f), 4)
            manifest = export_snapshot(other, tmp, generated_at="2026-10-06T00:00:00+00:00")
            self.assertEqual(manifest["counts"]["specs"], 4)
            cars = {c["id"]: c for c in json.loads((Path(tmp) / "cars.json").read_text())}
            details = json.loads((Path(tmp) / "details.json").read_text())
            for cid, c in cars.items():
                c["specs"] = details[cid]["specs"]
                c["spec_check"] = details[cid]["spec_check"]
            kona = cars["hyundai-kona-65-advance"]
            self.assertEqual(kona["specs"][0]["spec_key"], "carwow-cap:103322")
            self.assertEqual(kona["specs"][0]["flags"]["heat_pump"], "standard")
            self.assertTrue(kona["image"].startswith("https://car-data.carwow.co.uk/"))
            checks = {r["field"]: r["verdict"] for r in kona["spec_check"]["rows"]}
            self.assertEqual(checks["heat_pump"], "agrees")
            self.assertEqual(checks["internal_v2l"], "source lists it")  # seed says none, Carwow lists it
            self.assertEqual(kona["spec_check"]["disagreements"], 1)
            specs = json.loads((Path(tmp) / "specs.json").read_text())
            self.assertEqual(len(specs), 4)
            self.assertNotIn("car_ref", specs[0])


if __name__ == "__main__":
    unittest.main()
