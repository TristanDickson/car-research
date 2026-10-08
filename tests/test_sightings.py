"""The used asking-price spans in gold (one state per span, closed when the
listing goes), their backfill and round trip, and the span files the exporter
writes for the browser's cost model (web/src/lib/model)."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import gold
from pipeline.history import export_used_observations, import_used_observations
from pipeline.providers import carwow_used
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from pipeline.services.snapshot import export_snapshot, load_sightings, load_used_spans, source_of
from tests.helpers import fresh_conn, run_all

FIX = Path(__file__).parent / "fixtures"


def _provider(files: dict[str, str]):
    cap = carwow_used.stock

    def discover(target: Target, ctx: Context):
        for t in cap.discover(target, ctx):
            if t.identifier in files:
                yield t

    def fetch(target: Target, ctx: Context) -> Fetched:
        return Fetched(url=target.metadata["url"], status_code=200, body=(FIX / files[target.identifier]).read_bytes())

    c = Capability(name=cap.name, parser_version=cap.parser_version, discover=discover, fetch=fetch, parse=cap.parse, kinds=cap.kinds)
    return Provider(name="carwow_used", default_capability=c.name, capabilities={c.name: c}, live=False)


class UsedSpans(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        run_all(self.conn)

    def spans(self):
        return [tuple(r) for r in self.conn.execute(
            "SELECT listing_key, price_gbp, present, observed_at < confirmed_at FROM used_observations ORDER BY listing_key, observed_at, id")]

    def test_a_listing_s_price_becomes_spans_that_close_when_it_goes(self):
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
        self.assertEqual(self.conn.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (6, 6))
        # Seen again at the same price: the span extends; one car's price changes: a new span; four cars gone: closed.
        self.conn.execute("UPDATE used_observations SET observed_at='2026-10-01T00:00:00+00:00', confirmed_at='2026-10-01T00:00:00+00:00'")
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p3.html"}), ctx=Context(root=FIX))
        rows = self.conn.execute(
            "SELECT listing_key, COUNT(*), SUM(present), MIN(present) FROM used_observations GROUP BY 1 ORDER BY 1").fetchall()
        gone = [r for r in rows if r[3] == 0]
        self.assertEqual(len(gone), 4, "the four cars not on page 3 got a present=0 span")
        self.assertTrue(all(r[1] == 2 for r in gone))
        kept = [r for r in rows if r[3] == 1]
        self.assertEqual(len(kept), 3)
        extended = self.conn.execute(
            "SELECT COUNT(*) FROM used_observations WHERE present=1 AND observed_at='2026-10-01T00:00:00+00:00' AND confirmed_at > observed_at").fetchone()[0]
        self.assertGreaterEqual(extended, 1, "an unchanged price re-sighted pushes confirmed_at")

    def test_spans_are_backfilled_from_stock_recorded_before_them_and_round_trip(self):
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
        self.conn.execute("DELETE FROM used_observations")
        self.conn.execute("UPDATE used_listings SET present=0 WHERE listing_key LIKE '%907dd561%'")
        self.assertEqual(gold.backfill_used_spans(self.conn), 6)
        self.assertEqual(self.conn.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (7, 6))
        self.assertEqual(gold.backfill_used_spans(self.conn), 0, "idempotent")
        tmp = FIX.parent / "_used_obs.jsonl"
        try:
            self.assertEqual(export_used_observations(self.conn, tmp), 7)
            other = fresh_conn()
            run_all(other)
            run(other, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
            other.execute("DELETE FROM used_observations")
            self.assertEqual(import_used_observations(other, tmp), 7)
            self.assertEqual(other.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (7, 6))
        finally:
            tmp.unlink(missing_ok=True)

    def test_the_exporter_writes_spans_with_their_payloads_and_a_source_dimension(self):
        run(self.conn, _provider({"hyundai/ioniq-5": "carwow_used_hyundai_ioniq-5_p1.html"}), ctx=Context(root=FIX))
        spans = load_sightings(self.conn, {"hyundai-kona-65-ultimate": "hyundai/kona-electric"})
        kona = [s for s in spans if s["car_id"] == "hyundai-kona-65-ultimate" and s["route"] == "pcp"]
        self.assertTrue(kona)
        s = kona[0]
        self.assertEqual((s["source"], s["model"], s["present"]), ("carwow", "hyundai/kona-electric", True))
        self.assertEqual(s["from"], s["deal"].get("captured_at", s["from"])[:10])
        for k in ("monthly_payment", "gfv", "num_payments", "vehicle_price"):
            self.assertIn(k, s["deal"], "the payload carries what the browser costs")
        self.assertNotIn("car_ref", s["deal"])
        used = load_used_spans(self.conn)
        self.assertEqual(len(used), 6)
        self.assertEqual({u["source"] for u in used}, {"carwow"})
        self.assertEqual({u["model"] for u in used}, {"hyundai/ioniq-5"})
        self.assertTrue(all(u["year"] and u["price"] and u["from"] <= u["to"] for u in used))
        self.assertEqual((source_of("carwow_deals"), source_of("cinch_used"), source_of("something_new")), ("carwow", "cinch", "something_new"))
        with tempfile.TemporaryDirectory() as tmp:
            manifest = export_snapshot(self.conn, tmp, generated_at="2026-10-08T00:00:00+00:00")
            out = Path(tmp)
            self.assertEqual(manifest["schema_version"], "7")
            self.assertEqual(len(json.loads((out / "sightings.json").read_text())), len(spans))
            self.assertEqual(len(json.loads((out / "used_spans.json").read_text())), 6)
            for gone in ("offers.json", "series.json", "residuals.json"):
                self.assertFalse((out / gone).exists(), f"{gone} is derived in the browser now")
            car = next(c for c in json.loads((out / "cars.json").read_text()) if c["id"] == "hyundai-kona-65-ultimate")
            for derived in ("deal_summary", "used_stock"):
                self.assertNotIn(derived, car, "the pipeline exports facts, not costs")
            data = json.loads((out / "data.json").read_text())
            self.assertEqual(data["sources"]["ncd"], "New Car Discount")
            self.assertNotIn("assumptions", data)


if __name__ == "__main__":
    unittest.main()
