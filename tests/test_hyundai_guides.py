"""What Hyundai UK publishes beyond the equipment table: each trim's powertrains with the pricing table's
cells (on-the-road price, insurance group, P11D, BIK ...), the Technical pages' numbers per powertrain and
trim, the paint prices, the battery warranty; and the configurator's discounts, net package prices and
equipment categories, with the Ioniq 3. Fixtures: pdftotext -layout output of the guides (October 2026)
and the Ioniq 3 configurator's Trims response (11 October 2026)."""
import json
import unittest
from pathlib import Path

from pipeline.providers import hyundai_configurator as cfg
from pipeline.providers import hyundai_specs as h
from pipeline.providers.types import Context, Target
from pipeline.services.features import flags_for

FIX = Path(__file__).parent / "fixtures"


def rows_of(name, model, model_name):
    txt = (FIX / name).read_text(encoding="utf-8")
    return {(r["trim"], r["seats"]): r for r in h.parse_text(txt, model, model_name, "https://example/guide.pdf", "2026-10-11T00:00:00Z")}


def pts(row):
    return {(p["battery_kwh"], p["power_ps"]): p for p in row["powertrains"]}


IONIQ5 = rows_of("hyundai_ioniq5_tech_spec.txt", "ioniq-5", "Ioniq 5")
INSTER = rows_of("hyundai_inster_tech_spec.txt", "inster", "Inster")
KONA = rows_of("hyundai_kona_tech_spec.txt", "kona-electric", "Kona Electric")
IONIQ6 = rows_of("hyundai_ioniq6_tech_spec.txt", "ioniq-6", "Ioniq 6")
IONIQ9 = rows_of("hyundai_ioniq9_tech_spec.txt", "ioniq-9", "Ioniq 9")


class PriceTable(unittest.TestCase):
    def test_each_powertrain_keeps_its_own_price(self):
        u = pts(IONIQ5[("Ultimate", None)])
        self.assertEqual({k: p["otr_price_gbp"] for k, p in u.items()}, {(84.0, 228): 50255, (84.0, 325): 53755}, "the 228PS is not overwritten by the 325PS")
        a = pts(IONIQ5[("Advance", None)])
        self.assertEqual({k: p["otr_price_gbp"] for k, p in a.items()}, {(63.0, 170): 40695, (84.0, 228): 44195})

    def test_the_other_cells_as_printed(self):
        p = pts(IONIQ5[("Ultimate", None)])[(84.0, 228)]
        self.assertEqual(p["price_table"], {"co2_g_km": 0, "insurance_group": "38E", "ved_first_year_gbp": 10, "basic_retail_gbp": 41220.83,
                                            "vat_gbp": 8244.17, "retail_price_gbp": 49465, "otr_price_gbp": 50255, "p11d_gbp": 50190,
                                            "bik_pct": 4, "bik_monthly_20pct_gbp": 33.46, "bik_monthly_40pct_gbp": 66.92})
        self.assertEqual((p["numbers"]["list_price_gbp"], p["numbers"]["insurance_group"]), (50255, "38E"))
        k = pts(KONA[("Advance", None)])[(65.0, 218)]["price_table"]
        self.assertEqual((k["ved_band"], k["insurance_group"], k["otr_price_gbp"], k["bik_monthly_40pct_gbp"]), ("A", "31D", 35000, 46.58))

    def test_the_model_year_of_the_trims_column_picks_its_table(self):
        # the Inster guide prints an MY26 table (from stock) and an MY27 one; the rows are MY27
        self.assertEqual({k: p["otr_price_gbp"] for k, p in pts(INSTER[("01", None)]).items()}, {(42.0, 97): 22995, (49.0, 115): 24545})
        self.assertEqual({p["model_year"] for p in INSTER[("01", None)]["powertrains"]}, {2027})

    def test_a_trim_and_seat_count_printed_around_the_price_line(self):
        # 'CALLIGRAPHY' / price line / '7 SEAT BLACK INK (MY27)': the trim and seats are read from both sides
        bi7, bi6 = IONIQ9[("Calligraphy Black Ink", 7)], IONIQ9[("Calligraphy Black Ink", 6)]
        self.assertEqual([(p["power_ps"], p["otr_price_gbp"]) for p in bi7["powertrains"]], [(427, 79835)], "no PS printed: the Technical column's")
        self.assertEqual([(p["power_ps"], p["otr_price_gbp"]) for p in bi6["powertrains"]], [(427, 80835)])
        self.assertIsNone(bi7["powertrains"][0]["price_table"]["insurance_group"], "printed TBC")
        self.assertEqual([(p["power_ps"], p["otr_price_gbp"]) for p in IONIQ9[("Calligraphy", 7)]["powertrains"]], [(307, 76435), (427, 78235)])
        self.assertEqual([(p["power_ps"], p["otr_price_gbp"]) for p in IONIQ9[("Calligraphy", 6)]["powertrains"]], [(427, 79235)])

    def test_the_battery_list_is_unchanged(self):
        self.assertEqual(IONIQ5[("Advance", None)]["batteries"], [63.0, 84.0])
        self.assertEqual(KONA[("Advance", None)]["batteries"], [65.0])
        self.assertNotIn("battery_kwh", KONA[("Advance", None)]["numbers"], "the claim store keys trims on the price table's 65 kWh")
        self.assertEqual(pts(KONA[("Advance", None)])[(65.0, 218)]["numbers"]["battery_kwh"], 65.4, "the Technical page's figure stays with the powertrain")


class Options(unittest.TestCase):
    def test_paint_prices_beside_the_names(self):
        r = IONIQ5[("Ultimate", None)]
        self.assertEqual(r["options"], ["Special Solid Paint (Atlas White)", "Metallic / Pearl Paint", "Matt Paint", "Seat Trim - Moonlight Grey Leather (Seat Facings Only)"])
        self.assertEqual(r["option_prices"], [{"name": "Special Solid Paint (Atlas White)", "price_gbp": 420.0}, {"name": "Metallic / Pearl Paint", "price_gbp": 795.0},
                                              {"name": "Matt Paint", "price_gbp": 1295.0}, {"name": "Seat Trim - Moonlight Grey Leather (Seat Facings Only)", "price_gbp": 0.0}])
        self.assertEqual([o["name"] for o in r["option_prices"]], r["options"])

    def test_an_accessory_has_no_price(self):
        self.assertIn({"name": "Vehicle to Load (Exterior Adaptor)", "price_gbp": None}, IONIQ6[("Premium", None)]["option_prices"])

    def test_standard_on_one_trim_is_an_extra_on_the_others(self):
        self.assertIn("Metallic / Pearl Paint", IONIQ9[("Premium", 7)]["options"])
        self.assertNotIn("Metallic / Pearl Paint", IONIQ9[("Calligraphy Black Ink", 7)]["options"])
        self.assertNotIn("Matt Paint", IONIQ9[("Calligraphy Black Ink", 7)]["options"], "not available on Calligraphy Black Ink")
        self.assertIn("Digital Side Mirrors (DSM)", IONIQ9[("Calligraphy Black Ink", 6)]["options"])


class Technical(unittest.TestCase):
    def test_ioniq5_per_powertrain_and_trim(self):
        a = pts(IONIQ5[("Advance", None)])
        big, small = a[(84.0, 228)]["numbers"], a[(63.0, 170)]["numbers"]
        self.assertEqual((big["tow_kg"], big["wltp_range_mi"], big["power_kw"], big["kerb_weight_kg"]), (1600, 354, 168, 1985))
        self.assertEqual((small["tow_kg"], small["wltp_range_mi"]), (750, 273))
        n = IONIQ5[("Advance", None)]["numbers"]
        self.assertEqual((n["dc_10_80_min"], n["dc_10_80_charger_kw"], n["boot_l"], n["boot_max_l"], n["wheel_in"]), (18, 350, 520, 1580, 19))
        u = pts(IONIQ5[("Ultimate", None)])
        self.assertEqual((u[(84.0, 228)]["numbers"]["wltp_range_mi"], u[(84.0, 325)]["numbers"]["wltp_range_mi"]), (329, 311), "the Ultimate's own rows")

    def test_the_technical_column_names_the_drive_the_price_row_misprints(self):
        # the pricing table prints 'N Line 84 kWh 325PS RWD'; the Technical page's column is '84 kWh 325 PS AWD'
        p = pts(IONIQ5[("N Line", None)])[(84.0, 325)]
        self.assertEqual((p["drive"], p["technical_column"]), ("AWD", "84 kWh 325 PS AWD"))

    def test_inster_warranty_boot_and_a_trims_own_length(self):
        n = INSTER[("01", None)]["numbers"]
        self.assertEqual((n["warranty_years"], n["warranty_miles"], n["vehicle_warranty_years"], n["vehicle_warranty_miles"]), (8, 100000, 5, "unlimited"))
        self.assertEqual((n["length_mm"], INSTER[("Cross", None)]["numbers"]["length_mm"]), (3825, 3845), "'3825 (3845 CROSS)'")
        self.assertEqual((INSTER[("02", None)]["numbers"]["boot_l"], INSTER[("02", None)]["numbers"]["boot_rear_slid_l"]), (238, 351))
        self.assertEqual(INSTER[("01", None)]["numbers"]["tow_kg"], 0)
        p = pts(INSTER[("01", None)])
        self.assertEqual((p[(42.0, 97)]["numbers"]["dc_10_80_min"], p[(42.0, 97)]["numbers"]["dc_peak_kw"], p[(49.0, 115)]["numbers"]["dc_peak_kw"]),
                         (30, 73, 85), "'30 min @ 73kW max' on a 150 kW charger")

    def test_kona_wrapped_labels_and_the_battery_warranty(self):
        n = KONA[("Ultimate", None)]["numbers"]
        self.assertEqual((n["wltp_range_mi"], KONA[("Advance", None)]["numbers"]["wltp_range_mi"]), (282, 319))
        self.assertEqual((n["warranty_years"], n["warranty_miles"], n["tow_kg"], n["dc_10_80_min"], n["dc_peak_kw"]), (8, 100000, 750, 41, 101))
        facts = KONA[("Advance", None)]["powertrains"][0]["facts"]
        self.assertEqual(facts["Charging · Estimated Charging Emergency 3 Pin Connector (ICCB) 2.3kW (10-100%)"], "24hr 48min")

    def test_ioniq6_charging_sections_and_frunk(self):
        n = IONIQ6[("Premium", None)]["numbers"]
        self.assertEqual((n["dc_10_80_min"], n["dc_10_80_charger_kw"], n["dc_10_80_50kw_min"], n["boot_l"], n["tow_kg"]), (18, 350, 73, 401, 1500))
        p = {pt["drive"]: pt["numbers"] for pt in IONIQ6[("Premium", None)]["powertrains"]}
        self.assertEqual((p["RWD"]["frunk_l"], p["AWD"]["frunk_l"], p["RWD"]["power_kw"], p["AWD"]["power_ps"]), (45, 14.5, 168, 325))
        self.assertEqual((p["RWD"]["wltp_range_mi"], p["AWD"]["wltp_range_mi"]), (338, 322))

    def test_ioniq6_head_and_leg_room_by_row_and_trim(self):
        premium, ultimate = IONIQ6[("Premium", None)]["numbers"], IONIQ6[("Ultimate", None)]["numbers"]
        self.assertEqual((premium["headroom_front_mm"], premium["headroom_rear_mm"], premium["legroom_front_mm"]), (1022, 937, 1154))
        self.assertEqual(ultimate["headroom_front_mm"], 974, "the Ultimate columns' own '974'")
        self.assertNotIn("legroom_rear_mm", premium, "the guide prints no 2nd row leg room")
        self.assertNotIn("headroom_front_mm", IONIQ5[("Ultimate", None)]["numbers"], "nor the Ioniq 5's any")

    def test_ioniq9_seat_headings_and_both_boots(self):
        n = IONIQ9[("Calligraphy", 6)]["numbers"]
        self.assertEqual((n["boot_l"], n["boot_3rd_row_folded_l"], n["boot_max_l"], n["tow_kg"], n["wltp_range_mi"]), (338, 908, 2419, 2500, 372))
        self.assertEqual(IONIQ9[("Premium", 7)]["numbers"]["tow_kg"], 1600)
        self.assertEqual(pts(IONIQ9[("Premium", 7)])[(None, 218)]["numbers"]["battery_kwh"], 110.3)

    def test_existing_shapes_are_kept(self):
        r = IONIQ5[("Ultimate", None)]
        self.assertEqual(r["spec_key"], "hyundai-spec:ioniq-5:ultimate")
        self.assertTrue(all(isinstance(v, (int, float, str)) for v in r["numbers"].values()), "numbers stay scalars for the app")
        self.assertEqual(IONIQ9[("Premium", 7)]["numbers"]["seats"], 7)


class Ioniq3Configurator(unittest.TestCase):
    payload = json.loads((FIX / "hyundai_configurator_ioniq3.json").read_text(encoding="utf-8"))
    rows = {r["fsc"]: r for r in cfg.parse_payload(payload, "ioniq-3", "Ioniq 3", "2026-10-11T12:00:00+00:00")}

    def test_twenty_priced_configurations(self):
        self.assertEqual(self.payload["modelId"], "6J|W5||NG")
        self.assertEqual(len(self.rows), 20)
        self.assertEqual(len(self.payload["response"]["data"]["hppTrimEquipments"]), 320)
        self.assertEqual(sorted({r["trim"] for r in self.rows.values()}), ["Advance", "N Line Evo", "Premium", "Ultimate"])
        a = self.rows["6JW5ZFZ7ZDD000"]
        self.assertEqual((a["trim"], a["battery_kwh"], a["power_ps"], a["drive"], a["price"]), ("Advance", 42.0, 147, "FWD", 22245.0))
        u = self.rows["6JW5ZFZ7ZHH701"]
        self.assertEqual((u["trim"], u["battery_kwh"], u["price"], [p["name"] for p in u["packages"]]), ("Ultimate", 61.0, 31195.0, ["EV Pack"]))

    def test_packs_offered_on_ultimate_with_net_prices(self):
        offered = {p["name"]: (p["price"], p["net_price"]) for p in self.rows["6JW5ZFZ7ZHH038"]["offered"]}
        self.assertEqual(offered, {"Comfort Pack (Ultimate)": (2500.0, 2083.33), "Design Pack (Ultimate)": (1500.0, 1250.0), "EV Pack": (1250.0, 1041.67)})
        self.assertEqual(self.rows["6JW5ZFZ7ZDD000"]["offered"], [], "no packs on Advance")

    def test_a_pack_listed_one_item_per_line(self):
        ev = next(p for p in self.rows["6JW5ZFZ7ZHH701"]["packages"] if p["name"] == "EV Pack")
        self.assertEqual(ev["items"], ["EV Pack", "Heat Pump", "V2L - Vehicle to Load - Outside", "V2L (internal 3 pin plug)", "11KW + V2X"])
        f = flags_for(ev["items"])
        self.assertEqual((f["heat_pump"], f["v2l_internal"], f["v2l_external"]), ("standard",) * 3)
        comfort = next(p for p in self.rows["6JW5ZFZ7ZHH857"]["packages"] if p["name"] == "Comfort Pack (Ultimate)")
        self.assertIn("Front and Rear Seats - Heated", comfort["items"])
        self.assertEqual(flags_for(comfort["items"])["heated_front_seats"], "standard")

    def test_discounts_and_equipment_detail_kept(self):
        self.assertEqual({(r["discount1_price"], r["discount2_price"], r["discount3_price"]) for r in self.rows.values()}, {(0.0, 3750.0, 0.0)})
        r = self.rows["6JW5ZFZ7ZCC053"]
        self.assertEqual(len(r["equipment_detail"]), len(r["equipment"]))
        self.assertEqual([e["name"] for e in r["equipment_detail"]], r["equipment"])
        self.assertTrue({"Safety", "Exterior", "Comfort & Convenience"} <= {e["category"] for e in r["equipment_detail"]})
        self.assertTrue(any(e["highlight"] == "X" for e in r["equipment_detail"]))
        self.assertEqual((r["trim_sort"], r["body_type_name"]), ("4", "Wagon 5 DR"))

    def test_discovered(self):
        ts = {t.identifier: t for t in cfg.discover(Target(identifier="ioniq-3"), Context(root=Path(".")))}
        self.assertEqual(ts["ioniq-3"].metadata["url"], "https://www.hyundai.com/uk/en/models/ioniq3/configurator.html")
        self.assertEqual(ts["ioniq-3"].metadata["model_name"], "Ioniq 3")


class InsterConfigurator(unittest.TestCase):
    def test_the_fields_the_old_row_dropped(self):
        d = json.loads((FIX / "hyundai_configurator_inster.json").read_text(encoding="utf-8"))
        rows = {r["fsc"]: r for r in cfg.parse_payload(d, "inster", "Inster", "2026-10-08T12:00:00+00:00")}
        both = rows["6XS5ZDZ7ZHH597"]
        self.assertEqual([(p["name"], p["net_price"]) for p in both["packages"]], [("Tech Pack", 416.67), ("Heat Pump", 633.33)])
        self.assertEqual((both["discount1_price"], both["discount2_price"], both["discount3_price"]), (0.0, 0.0, 0.0))
        self.assertEqual(len(rows["6XS5ZDZ7ZSS182"]["equipment_detail"]), 48)


if __name__ == "__main__":
    unittest.main()
