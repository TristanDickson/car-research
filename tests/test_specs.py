"""Spec providers against saved pages, the feature-flag mapping, and specs flowing
through the build into gold, matched by CAP id or by the owner's decisions."""
import json
import unittest
from pathlib import Path

from pipeline.providers import carwow_specs, kia_specs
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.services.features import flags_for
from tests.helpers import Raws

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

    def test_carwow_s_configurator_wording_and_the_charging_cable(self):
        pack = flags_for(["V2L - Internal 3 pin plug 230V 3.6kW", "Digital key 2 Touch NFC type"])
        self.assertEqual((pack["v2l_internal"], pack["v2l_external"], pack["three_pin_socket"], pack["digital_key"]), ("standard", None, "standard", "standard"))
        cable = flags_for(["Charging cable - Emergency 3 pin connector mode 2 (ICCB)", "12V power outlet in front console"])
        self.assertIsNone(cable["three_pin_socket"], "the three-pin charging cable is not a socket in the car")
        self.assertIsNone(cable["v2l_internal"])
        ext = flags_for(["V2L external adaptor"])
        self.assertEqual((ext["v2l_external"], ext["v2l_internal"]), ("standard", None))
        # 'V2L capability' alone (Carwow's line for a Cupra Born VZ) does not say the socket is in the cabin.
        alone = flags_for(["Vehicle-to-load (V2L) capability"])
        self.assertEqual((alone["v2l_any"], alone["v2l_internal"], alone["v2l_external"]), ("standard", None, None))
        # An adapter named before the words is still the charge-port one, not a cabin socket; the boot is inside.
        for item in ("Adapter for V2L Charging (camping socket)", "Bi-directional charge adapter [V2L]"):
            f = flags_for([item])
            self.assertEqual((f["v2l_internal"], f["v2l_external"]), (None, "standard"), item)
        for item in ("230V inverter and outlet in boot to support V2L bi-directional charging capabilities", "Vehicle to load system in boot"):
            self.assertEqual(flags_for([item])["v2l_internal"], "standard", item)


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

    def test_each_derivative_takes_its_own_slide(self):
        """Advance, N Line, Ultimate and N Line S share the engine name '160kW 65kWh Auto' but the
        page prints 319 miles for the Advance and 282 for the others, each in the slide whose
        'Configure car' link names the CAP id."""
        rows = {r["cap_id"]: r for r in carwow_specs.parse_page(fixture("carwow_hyundai_kona-electric_specifications.html"), "hyundai", "kona-electric", "u", T)}
        self.assertEqual([(c, rows[c]["numbers"]["wltp_range_mi"], rows[c]["numbers"]["efficiency_mi_kwh"]) for c in ("103322", "103324", "103325", "103326")],
                         [("103322", 319.0, 4.2), ("103324", 282.0, 3.7), ("103325", 282.0, 3.7), ("103326", 282.0, 3.7)])
        self.assertEqual((rows["103324"]["rrp"], rows["103324"]["carwow_price"]), (37135.0, 29715.0))

    def test_pv5_page(self):
        rows = carwow_specs.parse_page(fixture("carwow_kia_pv5-passenger_specifications.html"), "kia", "pv5-passenger", "u", T)
        by_cap = {r["cap_id"]: r for r in rows}
        self.assertEqual(by_cap["110972"]["trim"], "Elite")
        self.assertEqual(by_cap["110972"]["flags"]["heat_pump"], "standard")
        self.assertEqual(by_cap["110972"]["numbers"]["wltp_range_mi"], 256.0)
        # The model prints '5 - 7' seats and a '350 - 1,330 L' boot: ranges, so no derivative takes a value from them.
        n = by_cap["108178"]["numbers"]
        self.assertEqual((n["seats"], n["seats_range"], n["boot_l"], n["boot_l_range"]), (None, [5.0, 7.0], None, [350.0, 1330.0]))
        # The model's cheapest lease ('Monthly £386*') and the basis its footnote prints.
        self.assertEqual((n["lease_from_gbp"], by_cap["108178"]["lease_from_basis"]),
                         (386.0, "personal contract hire, 9 month upfront fee, 48 month term, 8000 miles annually, inc VAT, excluding fees"))
        # The trim article prints the Essential's cheapest RRP; the Long Range's own slide prints its own.
        self.assertEqual((by_cap["108178"]["rrp"], by_cap["108178"]["trim_rrp"]), (36195.0, 33195.0))


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


class ThroughTheBuild(unittest.TestCase):
    def setUp(self):
        self.raws = Raws()

    def tearDown(self):
        self.raws.close()

    def test_specs_land_in_gold_on_the_owners_cars_or_their_derivatives(self):
        self.raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at=T)
        self.raws.add("carwow_specs", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_specifications.html", at=T)
        conn = self.raws.build()
        rows = conn.execute("SELECT spec_key, car_id, image_url FROM specs ORDER BY spec_key").fetchall()
        self.assertEqual(len(rows), 9)
        by = {r["spec_key"]: r for r in rows}
        self.assertEqual(by["carwow-cap:103322"]["car_id"], "hyundai-kona-65-advance")
        self.assertEqual(by["carwow-cap:110664"]["car_id"], "hyundai-ioniq3-61-advance")
        # The 42kWh Ioniq 3 is not one of the owner's cars: it is its own derivative.
        self.assertEqual(by["carwow-cap:110663"]["car_id"], "carwow-cap:110663")
        auto = json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:110663'").fetchone()["payload"])
        self.assertEqual((auto["auto"], auto["make"], auto["model"], auto["trim"], auto["list_price_gbp"], auto["model_year"]),
                         (True, "Hyundai", "Ioniq 3", "Advance · 108kW 42kWh Auto", 22245.0, 2026))
        flags = json.loads(conn.execute("SELECT payload FROM specs WHERE spec_key='carwow-cap:110663'").fetchone()["payload"])["flags"]
        self.assertEqual(auto["heat_pump"], flags["heat_pump"] or "unknown", "tri-state from the equipment list; absence is 'unknown', not 'none'")
        self.assertEqual(auto["internal_v2l"], "unknown")
        self.assertEqual(conn.execute("SELECT status, car_id FROM trim_map WHERE source='carwow-cap' AND source_key='110663'").fetchone()[:],
                         ("auto", "carwow-cap:110663"))
        self.assertTrue(by["carwow-cap:103322"]["image_url"].startswith("https://car-data.carwow.co.uk/image?"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='unmapped'").fetchone()[0], 0,
                         "untracked variants are not mapping tasks")
        # The same page a day later: one row each, changed_at untouched when nothing changed.
        first = conn.execute("SELECT changed_at, last_seen_at FROM specs WHERE spec_key='carwow-cap:103322'").fetchone()
        self.raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at="2026-10-07T00:00:00+00:00")
        conn = self.raws.build()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM specs").fetchone()[0], 9)
        second = conn.execute("SELECT changed_at, last_seen_at FROM specs WHERE spec_key='carwow-cap:103322'").fetchone()
        self.assertEqual(first["changed_at"], second["changed_at"])
        self.assertEqual(second["last_seen_at"], "2026-10-07T00:00:00+00:00")

    def test_kia_specs_resolve_through_the_owners_decisions(self):
        self.raws.add("kia_specs", "ev3", "kia_ev3_specification.html", at=T)
        self.raws.add("kia_specs", "pv5-passenger", "kia_pv5-passenger_specification.html", at=T)
        conn = self.raws.build()
        m = {r["spec_key"]: r["car_id"] for r in conn.execute("SELECT spec_key, car_id FROM specs")}
        self.assertEqual(m["kia-spec:ev3:gt-line-s-heat-pump:81-4-kwh-fwd"], "kia-ev3-81-gtlines-hp")
        self.assertEqual(m["kia-spec:pv5-passenger:elite:71-2-kwh-fwd:7seat"], "kia-pv5-passenger-71-elite-7seat")
        self.assertIsNone(m["kia-spec:ev3:air:58-3-kwh-fwd"])

    def test_the_makers_room_by_row_reaches_the_car(self):
        import tempfile
        from pipeline.services.snapshot import export_snapshot
        self.raws.add("kia_specs", "pv5-passenger", "kia_pv5-passenger_specification.html", at=T)
        conn = self.raws.build()
        with tempfile.TemporaryDirectory() as tmp:
            export_snapshot(conn, tmp, generated_at="2026-10-06T00:00:00+00:00")
            cars = {c["id"]: c for c in json.loads((Path(tmp) / "cars.json").read_text(encoding="utf-8"))}
        elite7 = cars["kia-pv5-passenger-71-elite-7seat"]
        self.assertEqual((elite7["legroom_front_mm"], elite7["headroom_rear_mm"], elite7["shoulder_rear_mm"]), (1041.0, 1076.0, 1617.0))
        # The 5-seat's 995 and the 7-seat's 977 share a trim and battery: that level stays silent, not the 5-seat's figure.
        self.assertIsNone(elite7.get("legroom_rear_mm"))

    def test_text_a_models_cars_share_is_written_once_for_the_model(self):
        from pipeline.services.snapshot import split_model_text
        cars = [{"id": "a", "model_key": "kia/ev3", "recalls": "R1", "review_interior": "Nice", "us_recalls": "U1"},
                {"id": "b", "model_key": "kia/ev3", "recalls": "R1", "review_interior": "Nice", "us_recalls": "U2"},
                {"id": "c", "model_key": "kia/ev9", "recalls": "R9"},
                {"id": "d", "model_key": "kia/ev9"}]
        self.assertEqual(split_model_text(cars), {"kia/ev3": {"recalls": "R1", "review_interior": "Nice"}})
        self.assertEqual(cars[0], {"id": "a", "model_key": "kia/ev3", "us_recalls": "U1"}, "worded differently: stays on the car")
        self.assertEqual(cars[2]["recalls"], "R9", "one car of the model lacks it: stays on the car")

    def test_specs_reach_the_snapshot(self):
        import tempfile
        from pipeline.services.snapshot import export_snapshot
        self.raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at=T)
        conn = self.raws.build()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = export_snapshot(conn, tmp, generated_at="2026-10-06T00:00:00+00:00")
            self.assertEqual(manifest["counts"]["specs"], 4)
            cars = {c["id"]: c for c in json.loads((Path(tmp) / "cars.json").read_text(encoding="utf-8"))}
            details = json.loads((Path(tmp) / "details.json").read_text(encoding="utf-8"))
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
            specs = json.loads((Path(tmp) / "specs.json").read_text(encoding="utf-8"))
            self.assertEqual(len(specs), 4)
            self.assertNotIn("car_ref", specs[0])


class ReadyForAVisitor(unittest.TestCase):
    """What a visitor needs from the snapshot: what is on sale, used cars by trim and battery. (Look-alikes are
    told apart in the app, web/src/lib/names.ts: that is presentation, not something the build decides.)"""

    def test_a_used_car_counts_as_a_car_of_its_trim_and_battery(self):
        from pipeline.services.snapshot import used_key, used_key_for_text
        kona = [{"used_key": used_key({"trim": t, "battery_kwh": 65.0}, "hyundai/kona-electric")} for t in ("Advance", "N Line", "N Line S", "Ultimate")]
        self.assertEqual([c["used_key"] for c in kona][:2], ["hyundai/kona-electric|advance|65", "hyundai/kona-electric|n line|65"])
        self.assertEqual(used_key_for_text("150kW 64kWh Auto Ultimate", kona), "hyundai/kona-electric|ultimate|65", "64 kWh is the 65's pack restated")
        self.assertEqual(used_key_for_text("160kW N Line S 65kWh 5dr Auto", kona), "hyundai/kona-electric|n line s|65", "the most specific trim")
        self.assertIsNone(used_key_for_text("150kW 64kWh Auto Premium", kona), "a trim no longer sold counts for none")
        self.assertIsNone(used_key_for_text("100kW 39kWh Auto Ultimate", kona), "nor a different battery")
        self.assertEqual(used_key({"trim": "GT Line S", "variant": "168kW 84kWh RWD Auto"}, "kia/ev6"),
                         used_key({"trim": "GT-Line S", "battery_kwh": 84.0}, "kia/ev6"), "hyphens and where the battery is printed do not matter")


if __name__ == "__main__":
    unittest.main()


class MakerTableWording(unittest.TestCase):
    """Hyundai's tables say 'Front Seats - Heated'; Carwow's lists say 'ventilated disc brakes' and
    'tinted windscreen', which are not seats or privacy glass."""

    def test_hyundai_seat_rows(self):
        from pipeline.services.features import flags_for
        f = flags_for(["Front Seats - Heated", "Rear Seats (Outer) - Heated", "Front Seats - Ventilated", "Privacy Glass - Rear Side and Tailgate"])
        self.assertEqual((f["heated_front_seats"], f["heated_rear_seats"], f["ventilated_seats"], f["rear_privacy_glass"]), ("standard",) * 4)
        self.assertEqual(flags_for(["Heated and ventilated front seats"])["heated_front_seats"], "standard")
        g = flags_for(["Front and Rear Seats - Heated", "Steering Wheel - Heated"])   # the configurator's wording
        self.assertEqual((g["heated_front_seats"], g["heated_rear_seats"], g["heated_steering_wheel"]), ("standard",) * 3)

    def test_brakes_windscreens_and_storage_are_not_seats_or_privacy_glass(self):
        from pipeline.services.features import flags_for
        f = flags_for(["Front ventilated disc brakes", "Ventilated wireless mobile phone charger (50W)", "Central front armrest with ventilated storage compartment",
                       "Ventilated 2nd row seats", "Rear Seats 2nd row - Ventilated", "Tinted (green glass) front windscreen", "Acoustic and tinted windscreen",
                       "Rear windscreen - Heated and Tinted"])
        self.assertIsNone(f.get("ventilated_seats"))
        self.assertIsNone(f.get("rear_privacy_glass"))
        self.assertEqual(flags_for(["Dark tinted rear windows"])["rear_privacy_glass"], "standard")
        self.assertIsNone(flags_for(["Tinted glass"]).get("rear_privacy_glass"), "every car's glass is tinted; privacy glass is dark")
        self.assertEqual(flags_for(["Heat insulating dark tinted glass"])["rear_privacy_glass"], "standard")

