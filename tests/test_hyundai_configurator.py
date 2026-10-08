"""Hyundai UK's configurator, read from the saved Trims response for the Inster (October 2026)."""
import json
import unittest
from pathlib import Path

from pipeline.providers import hyundai_configurator as h
from pipeline.providers.types import Context, Target
from pipeline.services.features import flags_for

FIX = Path(__file__).parent / "fixtures" / "hyundai_configurator_inster.json"
ROWS = {r["fsc"]: r for r in h.parse_payload(json.loads(FIX.read_text()), "inster", "Inster", "2026-10-08T12:00:00+00:00")}


class Inster(unittest.TestCase):
    def test_nine_configurations_with_trim_battery_power_seats_and_price(self):
        self.assertEqual(len(ROWS), 9)
        r = ROWS["6XS5ZDZ7ZSS182"]
        self.assertEqual((r["trim"], r["battery_kwh"], r["power_ps"], r["seats"], r["price"], r["drive"]), ("01", 42.0, 97, 4, 22995.0, None))
        self.assertEqual(ROWS["6XS5ZDZ7ZJJ834"]["trim"], "Cross")
        self.assertEqual(sorted({r["trim"] for r in ROWS.values()}), ["01", "02", "Cross"])

    def test_packages_in_the_price_and_offered_on_the_trim_and_powertrain(self):
        plain = ROWS["6XS5ZDZ7ZHH07V"]   # 02 49kWh £26,290
        self.assertEqual(plain["packages"], [])
        self.assertEqual([(p["name"], p["price"]) for p in plain["offered"]], [("Heat Pump", 760.0), ("Tech Pack", 500.0)])
        both = ROWS["6XS5ZDZ7ZHH597"]
        self.assertEqual([(p["name"], p["price"]) for p in both["packages"]], [("Tech Pack", 500.0), ("Heat Pump", 760.0)])
        self.assertEqual(ROWS["6XS5ZDZ7ZSS187"]["offered"], [], "no extras on 01")
        self.assertEqual([p["name"] for p in ROWS["6XS5ZDZ7ZJJ834"]["offered"]], ["Heat Pump"], "no Tech Pack on Cross")

    def test_a_packages_description_reads_as_contents_without_its_exclusions(self):
        tp = next(p for p in ROWS["6XS5ZDZ7ZHH597"]["packages"] if p["name"] == "Tech Pack")
        f = flags_for(tp["items"])
        self.assertEqual((f["v2l_internal"], f["three_pin_socket"], f["digital_key"]), ("standard",) * 3)
        self.assertIsNone(f.get("v2l_external"), "'excluding external adaptor' is not an inclusion")
        self.assertEqual(flags_for(h.pack_items("Heat Pump", None))["heat_pump"], "standard")

    def test_the_trims_standard_equipment(self):
        self.assertEqual(len(ROWS["6XS5ZDZ7ZSS182"]["equipment"]), 48)
        self.assertIn("Smart Key - Keyless Entry with Start/Stop Button", ROWS["6XS5ZDZ7ZSS182"]["equipment"])
        self.assertEqual(len(ROWS["6XS5ZDZ7ZJJ834"]["equipment"]), 69)
        self.assertFalse(any("heat pump" in e.lower() for r in ROWS.values() for e in r["equipment"]), "the heat pump is a package, never standard equipment")

    def test_discover_and_names(self):
        ts = list(h.discover(Target(identifier="all"), Context(root=Path("."))))
        self.assertEqual([t.identifier for t in ts], ["inster", "ioniq-5", "ioniq-6", "ioniq-9", "kona-electric"])
        self.assertEqual(h.trim_name("N LINE S"), "N Line S")
        self.assertEqual(h.trim_name("Calligraphy Black Ink"), "Calligraphy Black Ink")
        self.assertEqual(h.trim_name("01"), "01")


if __name__ == "__main__":
    unittest.main()
