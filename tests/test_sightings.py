"""The used asking-price spans in gold (one state per span, closed when the
listing goes), their backfill, and the span files the exporter writes for the
browser's cost model (web/src/lib/model)."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import gold
from pipeline.services.snapshot import export_snapshot, load_sightings, load_used_spans, source_of
from tests.helpers import Raws

T1, T2 = "2026-10-01T00:00:00+00:00", "2026-10-08T00:00:00+00:00"
P1, P3 = "carwow_used_hyundai_ioniq-5_p1.html", "carwow_used_hyundai_ioniq-5_p3.html"


class UsedSpans(unittest.TestCase):
    def setUp(self):
        self.raws = Raws()

    def tearDown(self):
        self.raws.close()

    def test_a_listing_s_price_becomes_spans_that_close_when_it_goes(self):
        self.raws.add("carwow_used", "hyundai/ioniq-5", P1, at=T1)
        conn = self.raws.build()
        self.assertEqual(conn.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (6, 6))
        # A week on: an unchanged price extends its span; a changed one opens a new span; four cars gone: closed.
        self.raws.add("carwow_used", "hyundai/ioniq-5", P3, at=T2)
        conn = self.raws.build()
        rows = conn.execute("SELECT listing_key, COUNT(*), SUM(present), MIN(present) FROM used_observations GROUP BY 1 ORDER BY 1").fetchall()
        gone = [r for r in rows if r[3] == 0]
        self.assertEqual(len(gone), 4, "the four cars not on page 3 got a present=0 span")
        self.assertTrue(all(r[1] == 2 for r in gone))
        kept = [r for r in rows if r[3] == 1]
        self.assertEqual(len(kept), 3)
        extended = conn.execute(
            "SELECT COUNT(*) FROM used_observations WHERE present=1 AND observed_at=? AND confirmed_at=?", (T1, T2)).fetchone()[0]
        self.assertGreaterEqual(extended, 1, "an unchanged price re-sighted pushes confirmed_at")
        # Added the other way round (the later page first), the build says the same.
        other = Raws()
        try:
            other.add("carwow_used", "hyundai/ioniq-5", P3, at=T2)
            other.add("carwow_used", "hyundai/ioniq-5", P1, at=T1)
            spans = lambda c: sorted(tuple(r) for r in c.execute(
                "SELECT listing_key, price_gbp, present, observed_at, confirmed_at FROM used_observations"))
            self.assertEqual(spans(other.build()), spans(conn))
        finally:
            other.close()

    def test_spans_are_backfilled_from_stock_recorded_before_them(self):
        self.raws.add("carwow_used", "hyundai/ioniq-5", P1, at=T1)
        conn = self.raws.build()
        conn.execute("DELETE FROM used_observations")
        conn.execute("UPDATE used_listings SET present=0 WHERE listing_key LIKE '%907dd561%'")
        self.assertEqual(gold.backfill_used_spans(conn), 6)
        self.assertEqual(conn.execute("SELECT COUNT(*), SUM(present) FROM used_observations").fetchone()[:], (7, 6))
        self.assertEqual(gold.backfill_used_spans(conn), 0, "idempotent")

    def test_the_exporter_writes_spans_with_their_payloads_and_a_source_dimension(self):
        self.raws.add("carwow_used", "hyundai/ioniq-5", P1, at=T1)
        self.conn = self.raws.build()
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
