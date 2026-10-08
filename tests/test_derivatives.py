"""The derivative registry: Carwow's model page names every derivative as CAP
does, brackets included; Gold keeps it, gives stub cars to what no spec page
listed, and replays it from history; services/claims.py reads the brackets."""
import json
import unittest
from pathlib import Path

from pipeline.history import export_derivatives, import_derivatives
from pipeline.providers import carwow_model
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-08T00:00:00+00:00"


def _provider(files: dict[str, str]):
    cap = carwow_model.derivatives

    def discover(target: Target, ctx: Context):
        for mk, mo in (("hyundai", "inster"),):
            ident = f"{mk}/{mo}"
            if ident in files:
                yield Target(identifier=ident, metadata={"make": mk, "model": mo, "make_name": "Hyundai", "model_name": "Inster", "url": carwow_model.url_for(mk, mo)})

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes())

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name="carwow_model", default_capability=c.name, capabilities={c.name: c}, live=False)


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
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)

    def test_a_derivative_no_spec_page_listed_gets_a_stub_car_and_the_registry_round_trips(self):
        res = run(self.conn, _provider({"hyundai/inster": "carwow_hyundai_inster_model.html"}), ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.records), (0, 9))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM derivatives").fetchone()[0], 9)
        car = json.loads(self.conn.execute("SELECT payload FROM cars WHERE id='carwow-cap:106646'").fetchone()["payload"])
        self.assertEqual((car["auto"], car["source_kind"], car["trim"], car["list_price_gbp"], car["model_year"]), (True, "stub", "02 · 85kW 49kWh Auto", 27115.0, 2026))
        tmp = FIX.parent / "_derivatives.jsonl"
        try:
            self.assertEqual(export_derivatives(self.conn, tmp), 9)
            other = fresh_conn()
            run_all(other)
            self.assertEqual(import_derivatives(other, tmp), 9)
            self.assertEqual(other.execute("SELECT COUNT(*) FROM derivatives").fetchone()[0], 9)
            self.assertIsNotNone(other.execute("SELECT 1 FROM cars WHERE id='carwow-cap:106646'").fetchone(), "the stub comes back on replay")
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
