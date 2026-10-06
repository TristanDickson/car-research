"""Import seed + pastes through the medallion, export a snapshot, in memory."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.db import ROOT
from pipeline.providers import carwow_paste, manual_seed
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.runner import run
from pipeline.services.snapshot import SCHEMA_VERSION, evaluate_hard, export_snapshot, latest_offers
from tests.helpers import fresh_conn, run_all


def _seed_counts():
    cars = json.loads((ROOT / "data/seed/cars.json").read_text())["cars"]
    deals = json.loads((ROOT / "data/seed/deals.json").read_text())["deals"]
    trims = json.loads((ROOT / "data/seed/trim_map.json").read_text())["trim_map"]
    return len(cars), len(deals), len(trims)


def q(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


class SeedImportAndExport(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.ctx = Context(root=ROOT)

    def test_seed_import_is_idempotent_and_keeps_lineage(self):
        n_cars, n_deals, n_trims = _seed_counts()
        first = run(self.conn, manual_seed.provider, ctx=self.ctx)
        self.assertEqual((first.artifacts, first.new_artifacts), (4, 4))
        self.assertEqual(first.records, n_cars + n_deals + 1 + n_trims)
        second = run(self.conn, manual_seed.provider, ctx=self.ctx)
        self.assertEqual(second.new_artifacts, 0, "unchanged seed must not mint new artifacts")
        c = self.conn
        self.assertEqual(q(c, "SELECT COUNT(*) FROM artifacts"), 4)
        self.assertEqual(q(c, "SELECT COUNT(*) FROM source_rows"), n_cars + n_deals + 1 + n_trims)
        self.assertEqual(q(c, "SELECT COUNT(*) FROM cars"), n_cars)
        self.assertEqual(q(c, "SELECT COUNT(*) FROM offer_observations"), n_deals, "re-import must not duplicate observations")
        self.assertEqual(q(c, "SELECT COUNT(*) FROM trim_map"), n_trims)
        self.assertEqual(q(c, "SELECT COUNT(*) FROM trim_map WHERE status='mapped'"),
                         q(c, "SELECT COUNT(*) FROM trim_map WHERE car_id IS NOT NULL"))
        self.assertEqual(q(c, "SELECT COUNT(*) FROM runs WHERE status='ok'"), 2)

    def test_carwow_pastes_resolve_through_trim_map(self):
        run(self.conn, manual_seed.provider, ctx=self.ctx)
        res = run(self.conn, carwow_paste.provider, ctx=self.ctx)
        self.assertEqual(res.artifacts, 4)
        self.assertEqual(res.records, 4)
        self.assertEqual(res.unmapped, 0)
        self.assertEqual(res.gold_rows, 4)
        row = self.conn.execute(
            "SELECT car_id, monthly_payment, source FROM offer_observations WHERE offer_key=?",
            ("carwow:deal:aea9f090b32568c0f0326d4ef6cf6299",)).fetchone()
        self.assertEqual(row["car_id"], "hyundai-kona-65-ultimate")
        self.assertEqual(row["monthly_payment"], 546.64)
        self.assertEqual(row["source"], "carwow_paste")

    def test_unmapped_trim_lands_in_silver_not_gold(self):
        run(self.conn, manual_seed.provider, ctx=self.ctx)
        page = (ROOT / "data/pastes/carwow/2026-10-05_ccbac930e8c40084fe1590a6e91466a1.txt").read_text()
        page = page.replace("99kW 61kWh Auto Ultimate EV Pack Brand new", "99kW 61kWh Auto N Line Evo Brand new")
        page = page.replace("Deal ID: ccbac930e8c40084fe1590a6e91466a1", "Deal ID: " + "f" * 32)

        def discover(t, ctx):
            yield Target("fake.txt")

        def fetch(t, ctx):
            return Fetched(url="file:///fake.txt", status_code=200, body=page.encode())

        fake = Provider("carwow_paste", "offers", {"offers": Capability(
            "offers", "1", discover, fetch, carwow_paste.parse, ("offer",))})
        res = run(self.conn, fake, ctx=self.ctx)
        self.assertEqual((res.records, res.unmapped, res.gold_rows), (1, 1, 0))
        self.assertEqual(q(self.conn, "SELECT COUNT(*) FROM source_rows WHERE source='carwow_paste'"), 1)
        tm = self.conn.execute("SELECT * FROM trim_map WHERE status='unmapped'").fetchone()
        self.assertEqual(tm["source_key"], "hyundai|ioniq 3|99kw 61kwh auto n line evo")
        self.assertEqual(tm["label"], "Hyundai Ioniq 3 99kW 61kWh Auto N Line Evo")

    def test_observation_history_and_freshness(self):
        run_all(self.conn)
        key = "carwow:deal:aea9f090b32568c0f0326d4ef6cf6299"
        base = json.loads(self.conn.execute(
            "SELECT payload FROM offer_observations WHERE offer_key=?", (key,)).fetchone()["payload"])

        def obs(observed_at, present=1, **changes):
            row = dict(base, observed_at=observed_at, present=present, **changes)
            rec = ParsedRecord("offer", key, row)
            from pipeline import gold
            gold.write(self.conn, "carwow_paste", ("offer",), {"offer": [(None, rec)]}, None)

        obs("2026-10-20", monthly_payment=560.0)
        obs("2026-11-02", present=0)
        offers = {o["id"]: o for o in latest_offers(self.conn, today=__import__("datetime").date(2026, 11, 3))}
        f = offers[key]["freshness"]
        self.assertEqual(f["observations"], 3)
        self.assertEqual(f["state"], "gone")
        self.assertEqual(f["last_seen_at"], "2026-10-20")
        self.assertEqual(f["last_checked_at"], "2026-11-02")
        self.assertEqual(f["age_days"], 14)
        self.assertEqual([h["monthly_payment"] for h in f["history"] if h["present"]], [546.64, 560.0])
        # A live offer not seen for more than STALE_DAYS is stale.
        ioniq3 = offers["carwow:deal:ccbac930e8c40084fe1590a6e91466a1"]["freshness"]
        self.assertEqual(ioniq3["state"], "live")
        self.assertTrue(ioniq3["stale"])
        self.assertEqual(ioniq3["age_days"], 29)

    def test_export_snapshot_shape(self):
        run_all(self.conn)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = export_snapshot(self.conn, tmp, generated_at="2026-10-06T00:00:00+00:00")
            out = Path(tmp)
            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(manifest["counts"]["unmapped_trims"], 0)
            self.assertFalse((out / "deals.json").exists())
            cars = json.loads((out / "cars.json").read_text())
            offers = json.loads((out / "offers.json").read_text())
            data = json.loads((out / "data.json").read_text())
            self.assertEqual(len(cars), manifest["counts"]["cars"])
            self.assertEqual(len(offers), manifest["counts"]["offers"])
            self.assertEqual(manifest["counts"]["offers"], 29 + 4)
            self.assertEqual([p["name"] for p in data["providers"]][:2], ["manual_seed", "carwow_paste"])
            self.assertEqual(data["unmapped_trims"], [])
            for o in offers:
                self.assertIn("metrics", o)
                self.assertIn("freshness", o)
                self.assertIn(o["freshness"]["state"], {"live", "lead", "derived", "illustrative", "campaign", "expired", "historical", "gone"})
            by_id = {c["id"]: c for c in cars}
            for c in cars:
                self.assertIn("picks", c)
                self.assertIn("image", c)
            self.assertEqual(by_id["kia-pv5-passenger-71-elite-7seat"]["picks"][0]["verdict"], "want")
            kona = by_id["hyundai-kona-65-ultimate"]
            self.assertTrue(kona["requirement_check"]["passes"])
            self.assertEqual(kona["deal_summary"]["best_cash_price"], 26966)
            self.assertAlmostEqual(kona["deal_summary"]["best_pcp_monthly"], 546.64)
            self.assertEqual(kona["deal_summary"]["best_pcp_offer_id"], "carwow:deal:aea9f090b32568c0f0326d4ef6cf6299")
            self.assertEqual(kona["deal_summary"]["best_pcp_age_days"], 1)
            self.assertFalse(by_id["hyundai-kona-65-advance"]["requirement_check"]["passes"])
            ev6 = by_id["kia-ev6-77-gtlines-2024-used"]["requirement_check"]
            self.assertTrue(ev6["passes"])
            self.assertIn("heat_pump", ev6["unknown"])
            # Richmond offers carry valid_to 2026-09-30 -> expired at export time.
            richmond = next(o for o in offers if o["id"] == "2026-09_richmond_kona-65-advance_pch")
            self.assertEqual(richmond["freshness"]["state"], "expired")

    def test_evaluate_hard_skips_deal_rules(self):
        reqs = {"hard": [
            {"id": "a", "field": "seats", "op": ">=", "value": 4},
            {"id": "b", "field": "customer_deposit", "op": "==", "value": 0, "applies_to": "deal"},
            {"id": "c", "field": "heat_pump", "op": "in", "value": ["standard", "pack"]},
        ]}
        self.assertEqual(evaluate_hard(reqs, {"seats": 4, "heat_pump": "none"}),
                         {"passes": False, "failures": ["c"], "unknown": []})
        self.assertEqual(evaluate_hard(reqs, {"seats": 5}), {"passes": True, "failures": [], "unknown": ["c"]})


if __name__ == "__main__":
    unittest.main()
