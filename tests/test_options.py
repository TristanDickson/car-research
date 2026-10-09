"""Carwow's configurator page per derivative: every option and pack with its
price and contents, kept in Gold and replayed from history."""
import json
import unittest
from pathlib import Path

from pipeline.history import export_options, import_options
from pipeline.providers import carwow_options
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-08T00:00:00+00:00"


def _provider(files: dict[str, str]):
    cap = carwow_options.options

    def discover(target: Target, ctx: Context):
        for cap_id, f in files.items():
            yield Target(identifier=cap_id, metadata={"cap_id": cap_id, "url": f"https://quotes.carwow.co.uk/car_configuration/choose-options?cap_derivative_id={cap_id}"})

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes())

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name="carwow_options", default_capability=c.name, capabilities={c.name: c}, live=False)


class ConfiguratorPage(unittest.TestCase):
    def test_options_and_packs_with_prices_and_contents(self):
        r = carwow_options.parse_page((FIX / "carwow_options_skoda_106738.html").read_text(encoding="utf-8"), "106738", "u", T)
        self.assertEqual(r["cap_id"], "106738")
        names = {o["name"]: o for o in r["options"]}
        self.assertEqual((names["Heat pump"]["price"], names["Heat pump"]["category"], names["Heat pump"]["default"]), (1100.0, "Interior Features", False))
        self.assertTrue(names["Dual zone climate control"]["default"])
        winter = next(p for p in r["packs"] if p["name"].startswith("Winter"))
        self.assertEqual((winter["price"], winter["items"]), (600.0, ["Heated rear seats", "Heated windscreen", "Automatic tri-zone climate control"]))
        self.assertEqual(len(r["packs"]), 2)

    def test_a_page_with_no_packs_and_only_paint(self):
        r = carwow_options.parse_page((FIX / "carwow_options_hyundai_106644.html").read_text(encoding="utf-8"), "106644", "u", T)
        self.assertEqual(r["packs"], [])
        self.assertTrue(all(o["category"] in ("Exterior Features", "Trim") for o in r["options"]))
        self.assertIsNone(carwow_options.parse_page("<html></html>", "1", "u", T))

    def test_the_url_is_built_the_way_carwow_links_it(self):
        u = carwow_options.configurator_url("106646", "2026-10-01", "85kW 49kWh Auto", "hyundai", "inster-2024")
        self.assertIn("cap_derivative_id=106646", u)
        self.assertIn("derivative_version_id=car_106646_2026-10-01", u)
        self.assertIn("engine_name=85kW+49kWh+Auto", u)
        self.assertIn("model=inster-2024", u)


class Registry(unittest.TestCase):
    def test_gold_keeps_one_row_per_derivative_and_history_round_trips(self):
        conn = fresh_conn()
        run_all(conn)
        res = run(conn, _provider({"106738": "carwow_options_skoda_106738.html", "106644": "carwow_options_hyundai_106644.html"}), ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.records), (0, 2))
        row = json.loads(conn.execute("SELECT payload FROM options WHERE cap_id='106738'").fetchone()["payload"])
        self.assertEqual(len(row["packs"]), 2)
        tmp = FIX.parent / "_options.jsonl"
        try:
            self.assertEqual(export_options(conn, tmp), 2)
            other = fresh_conn()
            run_all(other)
            self.assertEqual(import_options(other, tmp), 2)
            self.assertEqual(other.execute("SELECT COUNT(*) FROM options").fetchone()[0], 2)
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()


class Discover(unittest.TestCase):
    """A thousand derivatives whose options seldom change: never-read first, then the stalest, a batch a run."""

    def test_new_then_stale_then_nothing_fresh(self):
        from datetime import datetime, timedelta, timezone
        conn = fresh_conn()
        self.addCleanup(conn.close)
        ago = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).isoformat(timespec="seconds")
        for cap in ("1", "2", "3", "4"):
            conn.execute("INSERT INTO derivatives (cap_id, make_slug, model_slug, name, payload, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?)",
                         (cap, "kia", "ev3", f"EV3 {cap}", json.dumps({"configurator_url": f"https://x/{cap}"}), T, T))
        for cap, days in (("1", 1), ("2", 20), ("3", 9)):
            conn.execute("INSERT INTO options (cap_id, payload, first_seen_at, last_seen_at) VALUES (?,?,?,?)", (cap, "{}", ago(days), ago(days)))
        ctx = Context(root=Path("."), extras={"db": conn})
        ids = lambda **x: [t.identifier for t in carwow_options.discover(Target(identifier="all"), Context(root=Path("."), extras={"db": conn, **x}))]
        self.assertEqual(ids(), ["4", "2", "3"], "never read, then the stalest; read yesterday is skipped")
        self.assertEqual(ids(carwow_options_per_run=2), ["4", "2"])
        self.assertEqual(ids(reparse=True), ["1", "2", "3", "4"])
        self.assertEqual([t.identifier for t in carwow_options.discover(Target(identifier="1"), ctx)], ["1"], "a named derivative is read regardless")
