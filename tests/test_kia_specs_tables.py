"""Kia UK specification pages: the numbers each table prints, read per grade × powertrain × seats
(charge times with the charger each is for, towing, seat-count tables, Wh/km, colspans)."""
import unittest
from pathlib import Path

from pipeline.providers import kia_specs

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-11T00:00:00+00:00"


def rows(model: str) -> dict[str, dict]:
    page = (FIX / f"kia_{model}_specification.html").read_text(encoding="utf-8", errors="replace")
    return {r["spec_key"].split(":", 2)[2]: r for r in kia_specs.parse_page(page, model, "u", T)}


class ChargeTimes(unittest.TestCase):
    def test_every_row_is_kept_and_the_fastest_dc_is_the_10_80_time(self):
        ev3 = rows("ev3")
        lr = ev3["gt-line:81-4-kwh-fwd"]
        self.assertEqual(lr["numbers"]["dc_10_80_min"], 31.0, "'DC Charge Time (10-80%)- 128kWh' | '31m'")
        dc = [(c["charger_kw"], c["minutes"]) for c in lr["charge_times"] if c["kind"] == "dc"]
        self.assertEqual(dc, [(50.0, 79.0), (128.0, 31.0)])
        self.assertEqual(ev3["air:58-3-kwh-fwd"]["numbers"]["dc_10_80_min"], 29.0, "the 58.3 kWh's own 101 kW row")
        ac = [c for c in lr["charge_times"] if c["kind"] == "ac"]
        self.assertEqual([(c["from"], c["to"], c["charger_kw"], c["minutes"]) for c in ac], [(10, 100, None, 1930.0), (10, 100, 11.0, 435.0)])

    def test_ev6_hours_and_ev2_118kw(self):
        ev6 = rows("ev6")["gt-line:84-kwh-rwd-225-bhp"]
        self.assertEqual(ev6["numbers"]["dc_10_80_min"], 18.0)
        self.assertIn({"kind": "dc", "from": 10, "to": 80, "charger_kw": 50.0, "minutes": 76.0, "printed": "1hr 16 mins",
                       "label": "DC Charge Time (10-80%) - 50kw (max 125A)"}, ev6["charge_times"])
        self.assertEqual(rows("ev2")["first-edition:42-2-kwh-fwd"]["numbers"]["dc_10_80_min"], 29.0)

    def test_a_bound_is_noted_and_two_times_in_one_cell_are_not_read(self):
        pv5 = rows("pv5-passenger")["essential:51-5-kwh-fwd:5seat"]
        self.assertEqual((pv5["numbers"]["dc_10_80_min"], pv5["notes"]["dc_10_80_min"]), (30.0, "<30 mins"))
        ac11 = next(c for c in pv5["charge_times"] if c["charger_kw"] == 11.0)
        self.assertEqual((ac11["minutes"], ac11["printed"]), (None, "Up to 5 hours6hrs 30mins"))

    def test_minutes(self):
        m = kia_specs._minutes
        self.assertEqual([m("31m"), m("1hr 16 mins"), m("34 hrs 40 mins"), m("23h 10m"), m("Up to 7 hours"), m("TBC")],
                         [31.0, 76.0, 2080.0, 1390.0, 420.0, None])


class SeatTables(unittest.TestCase):
    """The PV5's weight, boot and dimension tables are headed '5-Seat' | '7-Seat'."""

    def test_towing_boot_and_length_by_seat_count_and_range(self):
        pv5 = rows("pv5-passenger")
        n = {k: r["numbers"] for k, r in pv5.items()}
        self.assertEqual(n["essential:51-5-kwh-fwd:5seat"]["tow_kg"], 750.0, "'Standard Range: 750kg Long Range: 1,500kg'")
        self.assertEqual(n["plus:71-2-kwh-fwd:5seat"]["tow_kg"], 1500.0)
        self.assertEqual(n["plus:71-2-kwh-fwd:7seat"]["tow_kg"], 750.0, "'Essential and Plus - 750kg Elite - Cannot Tow - 0kg'")
        self.assertEqual((n["elite:71-2-kwh-fwd:7seat"]["tow_kg"], pv5["elite:71-2-kwh-fwd:7seat"]["notes"]["tow_kg"]), (0.0, "Cannot Tow - 0kg"))
        self.assertEqual((n["elite:71-2-kwh-fwd:5seat"]["boot_l"], n["elite:71-2-kwh-fwd:7seat"]["boot_l"]), (1330.0, 350.0))
        self.assertEqual((n["elite:71-2-kwh-fwd:5seat"]["boot_max_l"], n["elite:71-2-kwh-fwd:7seat"]["boot_max_l"]), (3615.0, 3430.0))
        self.assertEqual(n["elite:71-2-kwh-fwd:7seat"]["length_mm"], 4695.0)
        self.assertEqual(n["essential:51-5-kwh-fwd:5seat"]["kerb_weight_kg"], 1990.0)
        self.assertEqual(n["essential:71-2-kwh-fwd:5seat"]["kerb_weight_kg"], 2070.0)
        self.assertEqual((n["essential:71-2-kwh-fwd:7seat"]["wheelbase_m"], n["essential:71-2-kwh-fwd:7seat"]["width_mirrors_mm"]), (2.995, 2255.0))

    def test_power_insurance_and_the_standard_range_wltp(self):
        n = {k: r["numbers"] for k, r in rows("pv5-passenger").items()}
        self.assertEqual((n["plus:71-2-kwh-fwd:7seat"]["power_bhp"], n["plus:71-2-kwh-fwd:7seat"]["power_kw"]), (160.0, 120.0), "'Motor Output, BHP/kW'")
        self.assertIsNone(n["elite:71-2-kwh-fwd:7seat"]["insurance_group"], "'TBC' is no group")
        self.assertEqual(n["essential:71-2-kwh-fwd:5seat"]["insurance_group"], "29D")
        sr = n["essential:51-5-kwh-fwd:5seat"]
        self.assertEqual((sr["wltp_range_mi"], sr["zero_to_62_s"], sr["efficiency_wh_km"]), (183.0, 12.8, 192.0), "'5-Seat: Standard Range - 51.5 kWh'")

    def test_grade_columns(self):
        pv5 = rows("pv5-passenger")
        plus7, plus5 = pv5["plus:71-2-kwh-fwd:7seat"], pv5["plus:71-2-kwh-fwd:5seat"]
        self.assertEqual(plus7["flags"]["v2l_internal"], "standard", "'Plus: 5 and 7 Seat' columns are Plus's")
        self.assertIn("50:50 split folding 2nd row seats with 3 stage recline", plus7["features"], "the second 'Plus 5- Seat' column is the 7-seat")
        self.assertNotIn("50:50 split folding 2nd row seats with 3 stage recline", plus5["features"])
        self.assertEqual(plus7["flags"]["heated_front_seats"], "standard")


class Towing(unittest.TestCase):
    def test_braked_trailer_per_powertrain(self):
        ev3 = rows("ev3")
        self.assertEqual([ev3[k]["numbers"]["tow_kg"] for k in ("air:58-3-kwh-fwd", "air:81-4-kwh-fwd", "gt:81-4-kwh-awd")], [500.0, 1000.0, 1500.0])
        self.assertEqual(ev3["gt:81-4-kwh-awd"]["numbers"]["tow_ball_kg"], 100.0)
        self.assertEqual(rows("ev6")["air:84-kwh-rwd-225-bhp"]["numbers"]["tow_kg"], 1800.0)
        self.assertEqual(rows("ev2")["gt-line:61-kwh-fwd"]["numbers"]["tow_kg"], 750.0)


class Efficiency(unittest.TestCase):
    def test_wh_per_km_is_converted_and_kept(self):
        ev6 = rows("ev6")
        air = ev6["air:84-kwh-rwd-225-bhp"]["numbers"]
        self.assertEqual((air["efficiency_wh_km"], air["efficiency_mi_kwh"]), (159.0, 3.91), "1000 / (159 × 1.609344)")
        gts = ev6["gt-line-s:84-kwh-awd-320-bhp"]["numbers"]
        self.assertEqual((gts["wltp_range_mi"], gts["efficiency_wh_km"], gts["top_speed_mph"]), (324.0, 177.0, 116.0), "'GT-Line S (incl. Heat Pump Versions)'")

    def test_ev2_prints_both_under_a_wh_km_label(self):
        gl = rows("ev2")["gt-line:61-kwh-fwd"]["numbers"]
        self.assertEqual((gl["efficiency_mi_kwh"], gl["efficiency_wh_km"]), (3.85, 162.0), "'3.85 (162)'")
        self.assertEqual(rows("ev2")["air:61-kwh-fwd"]["numbers"]["wltp_range_mi"], 275.0, "'Range (mi) (KM) - Combined' | '275 (444)'")

    def test_ev3_mi_kwh_spans_two_columns(self):
        air = rows("ev3")["air:81-4-kwh-fwd"]["numbers"]
        self.assertEqual((air["efficiency_mi_kwh"], air["top_speed_mph"], air["length_mm"]), (4.1, 105.0, 4300.0), "colspan=2 over both FWD columns")
        self.assertIsNone(air["efficiency_wh_km"])


class BodyAndPower(unittest.TestCase):
    def test_ev3_boot_colspan_and_grouped_dimensions(self):
        ev3 = rows("ev3")
        self.assertEqual([ev3[k]["numbers"]["boot_l"] for k in ("air:58-3-kwh-fwd", "gt-line:81-4-kwh-fwd", "gt:81-4-kwh-awd")], [460.0, 460.0, 413.0],
                         "'460l' spans both FWD columns, '413l' is the AWD's")
        self.assertEqual(ev3["gt-line:81-4-kwh-fwd"]["numbers"]["length_mm"], 4310.0, "'GT-Line / S' group")
        self.assertEqual(ev3["gt-line-s-heat-pump:81-4-kwh-fwd"]["numbers"]["height_mm"], 1570.0)
        self.assertEqual((ev3["gt:81-4-kwh-awd"]["numbers"]["frunk_l"], ev3["gt:81-4-kwh-awd"]["numbers"]["roof_load_kg"]), (25.0, 80.0))
        self.assertEqual(ev3["gt:81-4-kwh-awd"]["numbers"]["power_kw"], 215.0, "the drive train's kW, not the battery pack's 253")

    def test_ev2_power_boot_and_gt_line_s_dimensions(self):
        ev2 = rows("ev2")
        fe = ev2["first-edition:42-2-kwh-fwd"]["numbers"]
        self.assertEqual((fe["power_bhp"], fe["power_kw"]), (144.0, 107.8), "'Max. Power, bhp at rpm (kW)' | '144 (107.8)'")
        self.assertEqual((fe["boot_l"], fe["boot_max_l"], fe["gvwr_kg"]), (362.0, 1201.0, 2090.0))
        self.assertEqual(ev2["gt-line-s:61-kwh-fwd"]["numbers"]["length_mm"], 4065.0, "'GT-Line / S'")

    def test_pv5_room_by_row_and_seat_count(self):
        pv5 = rows("pv5-passenger")
        five, seven = pv5["elite:71-2-kwh-fwd:5seat"], pv5["elite:71-2-kwh-fwd:7seat"]
        keys = ("legroom_front_mm", "legroom_rear_mm", "headroom_front_mm", "headroom_rear_mm", "shoulder_front_mm", "shoulder_rear_mm")
        self.assertEqual([five["numbers"][k] for k in keys], [1041.0, 995.0, 1020.0, 1076.0, 1732.0, 1617.0], "'1,041 / 995'")
        self.assertEqual([seven["numbers"][k] for k in keys], [1041.0, 977.0, 1020.0, 1076.0, 1732.0, 1617.0], "the 7-seat's own 2nd row")
        self.assertEqual(seven["notes"]["legroom_rear_mm"], "1,041 / 977 / 970 (1st / 2nd / 3rd row): Leg Room (1st row / 2nd row) (mm)")
        self.assertNotIn("legroom_rear_mm", five["notes"])
        self.assertIsNone(rows("ev3")["gt-line:81-4-kwh-fwd"]["numbers"]["legroom_front_mm"], "the EV3 page prints none")

    def test_ev6_boot_follows_the_sound_system(self):
        ev6 = rows("ev6")
        self.assertEqual(ev6["gt-line:84-kwh-rwd-225-bhp"]["numbers"]["boot_l"], 490.0)
        self.assertEqual(ev6["gt-line-s:84-kwh-rwd-225-bhp"]["numbers"]["boot_l"], 480.0, "GT-Line S has the Meridian system")
        self.assertEqual(ev6["gt-line-s:84-kwh-rwd-225-bhp"]["notes"]["kerb_weight_kg"], "2050 / 2060")
        self.assertIsNone(ev6["gt-line-s:84-kwh-rwd-225-bhp"]["numbers"]["power_kw"], "the EV6 page prints bhp only")
        self.assertEqual(ev6["gt-line-s:84-kwh-rwd-225-bhp"]["numbers"]["power_bhp"], 225)


if __name__ == "__main__":
    unittest.main()
