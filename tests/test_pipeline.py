"""Import the seed through the medallion and export a snapshot, in memory."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.db import ROOT, connect, init_schema
from pipeline.providers import manual_seed
from pipeline.providers.types import Context
from pipeline.runner import run
from pipeline.services.snapshot import SCHEMA_VERSION, evaluate_hard, export_snapshot


def _seed_counts():
    cars = json.loads((ROOT / "data/seed/cars.json").read_text())["cars"]
    deals = json.loads((ROOT / "data/seed/deals.json").read_text())["deals"]
    return len(cars), len(deals)


class SeedImportAndExport(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_schema(self.conn)
        self.ctx = Context(root=ROOT)

    def test_import_is_idempotent_and_keeps_lineage(self):
        n_cars, n_deals = _seed_counts()
        first = run(self.conn, manual_seed.provider, ctx=self.ctx)
        self.assertEqual(first.artifacts, 3)
        self.assertEqual(first.new_artifacts, 3)
        self.assertEqual(first.records, n_cars + n_deals + 1)
        second = run(self.conn, manual_seed.provider, ctx=self.ctx)
        self.assertEqual(second.new_artifacts, 0, "unchanged seed must not mint new artifacts")
        q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        self.assertEqual(q("SELECT COUNT(*) FROM artifacts"), 3)
        self.assertEqual(q("SELECT COUNT(*) FROM source_rows"), n_cars + n_deals + 1)
        self.assertEqual(q("SELECT COUNT(*) FROM cars"), n_cars)
        self.assertEqual(q("SELECT COUNT(*) FROM deals"), n_deals)
        self.assertEqual(q("SELECT COUNT(*) FROM requirements"), 1)
        self.assertEqual(q("SELECT COUNT(*) FROM runs WHERE status='ok'"), 2)
        # Every deal points at a car (the FK would have rejected the import otherwise).
        self.assertEqual(q("SELECT COUNT(*) FROM deals d LEFT JOIN cars c ON c.id=d.car_id WHERE c.id IS NULL"), 0)

    def test_export_snapshot_shape(self):
        run(self.conn, manual_seed.provider, ctx=self.ctx)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = export_snapshot(self.conn, tmp, generated_at="2026-10-06T00:00:00+00:00")
            out = Path(tmp)
            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(json.loads((out / "manifest.json").read_text())["generated_at"], "2026-10-06T00:00:00+00:00")
            cars = json.loads((out / "cars.json").read_text())
            deals = json.loads((out / "deals.json").read_text())
            reqs = json.loads((out / "requirements.json").read_text())
            self.assertEqual(len(cars), manifest["counts"]["cars"])
            self.assertEqual(len(deals), manifest["counts"]["deals"])
            self.assertIn("hard", reqs)
            for c in cars:
                self.assertIn("requirement_check", c)
                self.assertIn("deal_summary", c)
            for d in deals:
                self.assertIn("metrics", d)
            by_id = {c["id"]: c for c in cars}
            # Advance Kona has no internal V2L: fails. Ultimate passes.
            self.assertFalse(by_id["hyundai-kona-65-advance"]["requirement_check"]["passes"])
            self.assertIn("internal_v2l", by_id["hyundai-kona-65-advance"]["requirement_check"]["failures"])
            self.assertTrue(by_id["hyundai-kona-65-ultimate"]["requirement_check"]["passes"])
            self.assertEqual(by_id["hyundai-kona-65-ultimate"]["deal_summary"]["best_cash_price"], 26966)
            self.assertAlmostEqual(by_id["hyundai-kona-65-ultimate"]["deal_summary"]["best_pcp_monthly"], 546.64)
            # Used EV6 with unknown heat pump: not a fail, flagged unknown.
            ev6 = by_id["kia-ev6-77-gtlines-2024-used"]["requirement_check"]
            self.assertTrue(ev6["passes"])
            self.assertIn("heat_pump", ev6["unknown"])

    def test_evaluate_hard_skips_deal_rules(self):
        reqs = {"hard": [
            {"id": "a", "field": "seats", "op": ">=", "value": 4},
            {"id": "b", "field": "customer_deposit", "op": "==", "value": 0, "applies_to": "deal"},
            {"id": "c", "field": "heat_pump", "op": "in", "value": ["standard", "pack"]},
        ]}
        self.assertEqual(evaluate_hard(reqs, {"seats": 4, "heat_pump": "none"}),
                         {"passes": False, "failures": ["c"], "unknown": []})
        self.assertEqual(evaluate_hard(reqs, {"seats": 5}),
                         {"passes": True, "failures": [], "unknown": ["c"]})


if __name__ == "__main__":
    unittest.main()
