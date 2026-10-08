"""Hyundai UK's Tech & Spec guides, read as text: trims, their batteries, the ● / - table,
qualified ticks and footnotes, packs with prices. The fixtures are pdftotext -layout output
of the real guides (October 2026)."""
import unittest
from pathlib import Path

from pipeline.providers import hyundai_specs as h

FIX = Path(__file__).parent / "fixtures"
INSTER = (FIX / "hyundai_inster_tech_spec.txt").read_text()
IONIQ5 = (FIX / "hyundai_ioniq5_tech_spec.txt").read_text()
KONA = (FIX / "hyundai_kona_tech_spec.txt").read_text()


def rows_of(txt, model, name):
    return {r["trim"]: r for r in h.parse_text(txt, model, name, "https://example/guide.pdf", "2026-10-08T00:00:00Z")}


class Inster(unittest.TestCase):
    rows = rows_of(INSTER, "inster", "Inster")

    def test_one_row_per_trim_from_the_latest_model_year(self):
        self.assertEqual(sorted(self.rows), ["01", "02", "Cross"])
        self.assertEqual({r["model_year"] for r in self.rows.values()}, {2027})
        self.assertEqual(self.rows["01"]["spec_key"], "hyundai-spec:inster:01")

    def test_the_pricing_table_gives_each_trim_its_batteries(self):
        self.assertEqual(sorted(self.rows["01"]["batteries"]), [42.0, 49.0])
        self.assertEqual(sorted(self.rows["02"]["batteries"]), [42.0, 49.0])
        self.assertEqual(self.rows["Cross"]["batteries"], [49.0])

    def test_heat_pump_is_standard_on_01_and_cross_and_49kwh_only_on_02(self):
        self.assertIn("Heat Pump and Battery Heater", self.rows["01"]["features"])
        self.assertIn("Heat Pump and Battery Heater", self.rows["Cross"]["features"])
        self.assertEqual(self.rows["01"]["flags"]["heat_pump"], "standard")
        q = self.rows["02"]["qualified"]
        self.assertEqual(q, [{"item": "Heat Pump and Battery Heater", "note": "49kWh only", "standard_kwh": [49.0], "none_kwh": [42.0]}])
        self.assertNotIn("Heat Pump and Battery Heater", self.rows["02"]["features"])
        self.assertIsNone(self.rows["02"]["flags"].get("heat_pump"), "the trim alone does not say")

    def test_a_dash_is_an_explicit_absence(self):
        self.assertIn("Roof Rails", self.rows["01"]["absent"])
        self.assertIn("Roof Rails", self.rows["Cross"]["features"])
        self.assertIn("Heated Steering Wheel", self.rows["01"]["absent"])
        self.assertEqual(len(self.rows["01"]["features"]) + len(self.rows["01"]["absent"]), 103, "every row of the table lands in one list or the other")

    def test_the_last_column_is_read_on_the_page_whose_header_shares_the_title_line(self):
        # page 2's header is 'Specifications   INSTER 01   INSTER 02 ...' on one line; the Cross column must not be lost
        self.assertEqual(len(self.rows["Cross"]["features"]) + len(self.rows["Cross"]["absent"]), 104)
        self.assertIn("12V Power Outlet - Front", self.rows["Cross"]["features"])

    def test_paint_is_an_option_not_a_pack(self):
        self.assertEqual(self.rows["01"]["packs"], [])
        self.assertEqual(self.rows["01"]["options"], ["Solid Paint (Atlas White)", "Special Paint (Jungle Khaki, Glow Mint)", "Metallic / Pearl Paint"])


class Ioniq5(unittest.TestCase):
    rows = rows_of(IONIQ5, "ioniq-5", "Ioniq 5")

    def test_trims_and_batteries(self):
        self.assertEqual(sorted(self.rows), ["Advance", "N Line", "N Line S", "Premium", "Ultimate"])
        self.assertEqual(self.rows["Advance"]["batteries"], [63.0, 84.0])
        self.assertEqual(self.rows["Ultimate"]["batteries"], [84.0])
        self.assertIsNone(self.rows["Advance"]["model_year"])

    def test_the_footnote_beside_the_key_qualifies_only_the_marked_cells(self):
        # 'Heat Pump***' with cells '●***' on Advance and Premium, '●' on the rest;
        # '*** Heat pump is only standard on the 84kWh battery (N/A on 63kWh) for Advance and Premium.' printed beside '● Standard'
        for t in ("Advance", "Premium"):
            self.assertEqual(self.rows[t]["qualified"], [{"item": "Heat Pump", "note": "Heat pump is only standard on the 84kWh battery (N/A on 63kWh) for Advance and Premium.",
                                                          "standard_kwh": [84.0], "none_kwh": [63.0]}])
            self.assertNotIn("Heat Pump", self.rows[t]["features"])
        for t in ("N Line", "Ultimate", "N Line S"):
            self.assertIn("Heat Pump", self.rows[t]["features"])
            self.assertEqual(self.rows[t]["qualified"], [])

    def test_v2l_inside_is_absent_on_advance_and_standard_above(self):
        self.assertIn("V2L - Vehicle to Load - Inside", self.rows["Advance"]["absent"])
        self.assertIsNone(self.rows["Advance"]["flags"].get("v2l_internal"))
        for t in ("Premium", "N Line", "Ultimate", "N Line S"):
            self.assertEqual(self.rows[t]["flags"]["v2l_internal"], "standard")

    def test_packs_with_contents_price_and_trims(self):
        packs = {p["name"]: p for p in self.rows["Ultimate"]["packs"]}
        self.assertEqual(packs["Tech Pack"]["price"], 1500.0)
        self.assertEqual(packs["Tech Pack"]["items"], ["Remote Smart Park Assist", "Parking Collision Avoidance Assist", "Surround View Monitor", "Blind Spot View Monitor"])
        self.assertEqual(packs["Zen Pack"]["price"], 2500.0)
        self.assertEqual(self.rows["Advance"]["packs"], [], "available on Ultimate trim only")
        self.assertIn("Digital Mirrors", self.rows["N Line S"]["options"])
        self.assertNotIn("Digital Mirrors", self.rows["Ultimate"]["options"])
        self.assertIn("Seat Trim - Moonlight Grey Leather (Seat Facings Only)", self.rows["Ultimate"]["options"])

    def test_an_item_in_a_pack_offered_on_the_trim_is_the_optional_glyph(self):
        u = self.rows["Ultimate"]
        self.assertNotIn("Surround View Monitor (SVM)", u["features"], "the Tech Pack sells it on Ultimate")
        self.assertNotIn("Vision Roof", u["features"])
        self.assertNotIn("Front Seats - Memory Driver Side", u["features"], "the Zen Pack's 'Driver Memory Seats', by flag")
        self.assertIsNone(u["flags"].get("camera_360"))
        self.assertIn("Surround View Monitor (SVM)", self.rows["N Line S"]["features"], "no pack offers it there: standard")

    def test_a_wrapped_label_is_joined(self):
        labels = self.rows["Ultimate"]["features"] + self.rows["Ultimate"]["absent"]
        self.assertTrue(any(l.startswith("Touchscreen") or "Touchscreen" in l for l in labels), labels[:5])
        self.assertFalse(any(l.endswith("*") for l in labels), "footnote marks are not part of a label")


class Kona(unittest.TestCase):
    rows = rows_of(KONA, "kona-electric", "Kona Electric")

    def test_trims_batteries_and_a_pack_named_after_a_colon(self):
        self.assertEqual(sorted(self.rows), ["Advance", "N Line", "N Line S", "Ultimate"])
        self.assertEqual({tuple(r["batteries"]) for r in self.rows.values()}, {(65.0,)})
        self.assertEqual(self.rows["Advance"]["packs"], [{"name": "Comfort Pack", "price": 600.0,
                                                           "items": ["Heated Front Seats", "Heated Steering Wheel", "Wireless Charger", "Privacy Glass", "Passenger Seat Height Adjust"]}])
        self.assertEqual(self.rows["N Line"]["packs"], [], "Advance only")

    def test_the_packs_own_table_row_is_not_an_item(self):
        for r in self.rows.values():
            self.assertFalse(any(l.startswith("Comfort Pack") for l in r["features"] + r["absent"]), r["trim"])
        self.assertIn("Heated Steering Wheel", self.rows["Advance"]["absent"])
        self.assertIn("Heated Steering Wheel", self.rows["N Line"]["features"])

    def test_the_cabin_socket_is_a_dash_below_n_line_s(self):
        for t in ("Advance", "N Line"):
            self.assertIn("Vehicle to Load (V2L) (Internal 3 Pin Plug)", self.rows[t]["absent"])
            self.assertIsNone(self.rows[t]["flags"].get("v2l_internal"))
        for t in ("N Line S", "Ultimate"):
            self.assertEqual((self.rows[t]["flags"]["v2l_internal"], self.rows[t]["flags"]["three_pin_socket"]), ("standard", "standard"))


ADAPTOR = """Specifications
                                        Premium   Ultimate

CHARGING
Vehicle to Load (Interior)                 ●         ●
Vehicle to Load (Exterior Adaptor)         -         -
Heat Pump                                  ●         ●
 KEY
 ● Standard
Pricing
"""


class Pieces(unittest.TestCase):
    def test_an_accessory_dash_is_sold_separately_not_unavailable(self):
        rows = {r["trim"]: r for r in h.parse_text(ADAPTOR, "ioniq-6", "Ioniq 6", "u", "2026-10-08T00:00:00Z")}
        self.assertEqual(sorted(rows), ["Premium", "Ultimate"])
        self.assertEqual(rows["Premium"]["features"], ["Vehicle to Load (Interior)", "Heat Pump"])
        self.assertEqual(rows["Premium"]["options"], ["Vehicle to Load (Exterior Adaptor)"])
        self.assertEqual(rows["Premium"]["absent"], [])
        self.assertEqual((rows["Premium"]["flags"]["v2l_internal"], rows["Premium"]["flags"]["v2l_external"]), ("standard", "option"))

    def test_cell_values(self):
        self.assertEqual(h._cell_value("●"), ("standard", ""))
        self.assertEqual(h._cell_value("● 49kWh only"), ("standard", "49kWh only"))
        self.assertEqual(h._cell_value("●***"), ("standard", "***"))
        self.assertEqual(h._cell_value("-"), ("none", ""))
        self.assertEqual(h._cell_value("Standard on MY26"), ("standard", "Standard on MY26"))
        self.assertEqual(h._cell_value(""), (None, ""))

    def test_qualify_against_the_trims_batteries(self):
        self.assertEqual(h._qualify("Heat Pump", "49kWh only", [42.0, 49.0]), ("qualified", {"item": "Heat Pump", "note": "49kWh only", "standard_kwh": [49.0], "none_kwh": [42.0]}))
        self.assertEqual(h._qualify("Heat Pump", "only standard on the 84kWh battery (N/A on 63kWh)", [84.0]), ("standard", None))
        self.assertEqual(h._qualify("Heat Pump", "only standard on the 84kWh battery (N/A on 63kWh)", [63.0]), ("none", None))

    def test_discover_names_the_five_models(self):
        from pipeline.providers.types import Context, Target
        ts = list(h.discover(Target(identifier="all"), Context(root=Path("."))))
        self.assertEqual([t.identifier for t in ts], ["inster", "ioniq-5", "ioniq-6", "ioniq-9", "kona-electric"])
        self.assertEqual(ts[0].metadata["url"], "https://www.hyundai.com/uk/en/models/inster/downloads.html")


if __name__ == "__main__":
    unittest.main()
