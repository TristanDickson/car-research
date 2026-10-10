"""The derivative registry: Carwow's model page names every derivative as CAP
does, brackets included; the build keeps it and describes from it every
derivative no specification page lists; services/claims.py reads the brackets."""
import json
import unittest
from pathlib import Path

from pipeline.providers import carwow_model
from tests.helpers import FIX, Raws

T = "2026-10-08T00:00:00+00:00"
INSTER = {"make": "hyundai", "model": "inster", "make_name": "Hyundai", "model_name": "Inster",
          "url": carwow_model.url_for("hyundai", "inster")}


class ModelPage(unittest.TestCase):
    def setUp(self):
        self.rows = carwow_model.parse_page((FIX / "carwow_hyundai_inster_model.html").read_text(encoding="utf-8"), "hyundai", "inster", "u", T, "Hyundai", "Inster")

    def test_every_derivative_with_its_cap_name_brackets_engine_trim_and_rrp(self):
        by = {r["cap_id"]: r for r in self.rows}
        self.assertEqual(len(by), 9)
        self.assertEqual((by["110533"]["name"], by["110533"]["brackets"], by["110533"]["trim"], by["110533"]["engine"], by["110533"]["rrp"], by["110533"]["version_date"]),
                         ("71kW 01 42kWh 5dr Auto [No Heat Pump]", ["No Heat Pump"], "01", "71kW 42kWh Auto", 22995.0, "2026-10-01"))
        self.assertEqual((by["106646"]["name"], by["106646"]["brackets"], by["106646"]["trim"], by["106646"]["rrp"]), ("85kW 02 49kWh 5dr Auto", [], "02", 27115.0))
        self.assertEqual((by["106647"]["trim"], by["106647"]["rrp"]), ("Cross", 29245.0))
        self.assertEqual({r["make"] for r in self.rows}, {"Hyundai"})
        self.assertEqual({r["model"] for r in self.rows}, {"Inster"})

    def test_trim_words_survive_odd_engines(self):
        self.assertEqual(carwow_model.trim_of("150kW GT-Line S 77kWh 5dr Auto", "150kW 77kWh Auto"), "GT-Line S")
        self.assertEqual(carwow_model.trim_of("150kW Trophy Long Range 64kWh 5dr Auto [Heat Pump]", "150kW Long Range 64kWh Auto"), "Trophy")


class Registry(unittest.TestCase):
    def test_a_derivative_no_spec_page_listed_is_described_from_the_registry(self):
        with Raws() as raws:
            raws.add("carwow_model", "hyundai/inster", "carwow_hyundai_inster_model.html", metadata=INSTER, at=T)
            conn = raws.build()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM derivatives").fetchone()[0], 9)
            car = json.loads(conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:106647'").fetchone()["payload"])
            self.assertEqual((car["auto"], car["source_kind"], car["trim"], car["list_price_gbp"], car["model_year"]),
                             (True, "stub", "Cross · 85kW 49kWh Auto", 29245.0, 2026))
            # The 02 49kWh is the owner's own entry: it stands for that derivative, with no second car beside it.
            self.assertIsNone(conn.execute("SELECT 1 FROM cars WHERE id='carwow-cap:106646'").fetchone())
            mine = json.loads(conn.execute("SELECT payload FROM cars WHERE id='hyundai-inster-49-02'").fetchone()["payload"])
            self.assertEqual((mine.get("auto"), str(mine["cap_id"])), (None, "106646"))


if __name__ == "__main__":
    unittest.main()
