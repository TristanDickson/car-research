"""The owner's files through the build, prices folded into spans, the snapshot's shape, and
the legacy history read with its matches taken out."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline import legacy
from pipeline.build import Build
from pipeline.db import ROOT
from pipeline.raw import RawStore
from pipeline.services.snapshot import SCHEMA_VERSION, evaluate_hard, export_snapshot, latest_offers
from tests.helpers import dump, fresh_conn, run_all


def _seed_counts():
    cars = json.loads((ROOT / "data/seed/cars.json").read_text(encoding="utf-8"))["cars"]
    deals = json.loads((ROOT / "data/seed/deals.json").read_text(encoding="utf-8"))["deals"]
    trims = json.loads((ROOT / "data/seed/trim_map.json").read_text(encoding="utf-8"))["trim_map"]
    return len(cars), len(deals), len(trims)


def q(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def sight(b: Build, at: str, row: dict, provider: str = "carwow_paste", priority: int = 2) -> None:
    b._sight(at, priority, provider, dict(row, observed_at=at), None)


class OwnerFiles(unittest.TestCase):
    def setUp(self):
        self.conn = run_all()

    def test_the_owners_files_build_the_same_every_time(self):
        n_cars, n_deals, n_trims = _seed_counts()
        c = self.conn
        self.assertEqual(q(c, "SELECT COUNT(*) FROM cars"), n_cars)
        self.assertEqual(q(c, "SELECT COUNT(DISTINCT offer_key) FROM offer_observations"), n_deals + 4, "the seed's offers and the four pastes")
        self.assertEqual(q(c, "SELECT COUNT(*) FROM trim_map WHERE status='mapped'"), q(c, "SELECT COUNT(*) FROM trim_map WHERE car_id IS NOT NULL"))
        self.assertGreaterEqual(q(c, "SELECT COUNT(*) FROM trim_map"), n_trims, "every decision is listed")
        self.assertEqual(q(c, "SELECT COUNT(*) FROM requirements"), 1)
        self.assertEqual(dump(c), dump(run_all()), "a second build is the same database")

    def test_carwow_pastes_resolve_through_the_owners_decisions(self):
        row = self.conn.execute("SELECT car_id, monthly_payment, source FROM offer_observations WHERE offer_key=?",
                                ("carwow:deal:aea9f090b32568c0f0326d4ef6cf6299",)).fetchone()
        self.assertEqual((row["car_id"], row["monthly_payment"], row["source"]), ("hyundai-kona-65-ultimate", 546.64, "carwow_paste"))

    def test_a_paste_nobody_has_decided_on_is_listed_unmapped_and_has_no_car(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "data" / "seed", root / "data" / "seed")
            shutil.copytree(ROOT / "data" / "pastes", root / "data" / "pastes")
            paste = root / "data/pastes/carwow/2026-10-05_ccbac930e8c40084fe1590a6e91466a1.txt"
            page = paste.read_text(encoding="utf-8")
            page = page.replace("99kW 61kWh Auto Ultimate EV Pack Brand new", "99kW 61kWh Auto N Line Evo Brand new")
            page = page.replace("Deal ID: ccbac930e8c40084fe1590a6e91466a1", "Deal ID: " + "f" * 32)
            paste.write_text(page, encoding="utf-8")
            conn = fresh_conn()
            Build(conn, None, root=root).run()
        self.assertIsNone(conn.execute("SELECT 1 FROM offer_observations WHERE offer_key=?", ("carwow:deal:" + "f" * 32,)).fetchone())
        tm = conn.execute("SELECT * FROM trim_map WHERE status='unmapped'").fetchone()
        self.assertEqual(tm["source_key"], "hyundai|ioniq 3|99kw 61kwh auto n line evo")
        self.assertEqual(tm["label"], "Hyundai Ioniq 3 99kW 61kWh Auto N Line Evo")

    def test_export_snapshot_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = export_snapshot(self.conn, tmp, generated_at="2026-10-06T00:00:00+00:00")
            out = Path(tmp)
            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(manifest["counts"]["unmapped_trims"], 0)
            self.assertFalse((out / "deals.json").exists())
            cars = json.loads((out / "cars.json").read_text(encoding="utf-8"))
            details = json.loads((out / "details.json").read_text(encoding="utf-8"))
            for c in cars:
                c["requirement_check"] = details[c["id"]]["requirement_check"]
            spans = json.loads((out / "sightings.json").read_text(encoding="utf-8"))
            data = json.loads((out / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cars), manifest["counts"]["cars"])
            self.assertEqual(len({s["key"] for s in spans}), manifest["counts"]["offers"])
            self.assertEqual(manifest["counts"]["offers"], 29 + 4)
            self.assertEqual([p["name"] for p in data["providers"]][:2], ["manual_seed", "carwow_paste"])
            self.assertEqual(data["unmapped_trims"], [])
            for s in spans:
                self.assertTrue(set(s) >= {"key", "car_id", "route", "source", "from", "to", "present", "deal", "status"})
                self.assertNotIn("metrics", s, "costs are the browser's")
            offers = latest_offers(self.conn)
            for o in offers:
                self.assertIn(o["freshness"]["state"], {"live", "lead", "derived", "illustrative", "campaign", "expired", "historical", "gone"})
            by_id = {c["id"]: c for c in cars}
            for c in cars:
                self.assertIn("picks", c)
                self.assertIn("image", c)
            self.assertEqual(by_id["kia-pv5-passenger-71-elite-7seat"]["picks"][0]["verdict"], "want")
            kona = by_id["hyundai-kona-65-ultimate"]
            self.assertTrue(kona["requirement_check"]["passes"])
            self.assertNotIn("deal_summary", kona, "the pipeline exports facts; the browser costs them")
            kona_pcp = [s for s in spans if s["car_id"] == kona["id"] and s["route"] == "pcp" and s["key"] == "carwow:deal:aea9f090b32568c0f0326d4ef6cf6299"]
            self.assertEqual(len(kona_pcp), 1)
            self.assertAlmostEqual(kona_pcp[0]["deal"]["monthly_payment"], 546.64)
            self.assertEqual((kona_pcp[0]["source"], kona_pcp[0]["to"]), ("carwow", "2026-10-05"))
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


class Spans(unittest.TestCase):
    """Sightings fold into spans in date order, whichever order they were read in."""

    KEY = "carwow:deal:aea9f090b32568c0f0326d4ef6cf6299"

    def build(self, points):
        conn = fresh_conn()
        b = Build(conn, None)
        b.owner()
        base = next(s.row for s in b.sightings if s.key == self.KEY)
        for at, changes in points:
            sight(b, at, dict(base, **changes))
        b.finish()
        return conn

    def spans(self, conn):
        return [(r["observed_at"][:10], (r["confirmed_at"] or r["observed_at"])[:10], r["monthly_payment"], r["present"])
                for r in conn.execute("SELECT * FROM offer_observations WHERE offer_key=? ORDER BY observed_at", (self.KEY,))]

    def test_history_and_freshness(self):
        conn = self.build([("2026-10-20", {"monthly_payment": 560.0}), ("2026-11-02", {"present": 0})])
        offers = {o["id"]: o for o in latest_offers(conn, today=date(2026, 11, 3))}
        f = offers[self.KEY]["freshness"]
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

    def test_older_copies_of_a_page_fold_in_wherever_they_fall(self):
        p = {"monthly_payment": 546.64}
        points = [("2026-10-06T00:00:00+00:00", p), ("2026-09-20T00:00:00+00:00", p),          # same price, earlier: one span
                  ("2026-09-01T00:00:00+00:00", {"monthly_payment": 580.0}), ("2026-09-08T00:00:00+00:00", {"monthly_payment": 580.0}),
                  ("2026-09-15T00:00:00+00:00", p), ("2026-10-07T00:00:00+00:00", p),
                  ("2026-10-12T00:00:00+00:00", {"monthly_payment": 520.0}),                    # a different price inside a span splits it
                  ("2026-10-12T12:00:00+00:00", p), ("2026-10-20T00:00:00+00:00", p),
                  ("2026-10-25T00:00:00+00:00", dict(p, present=0))]                             # gone: never merged
        want = [("2026-09-01", "2026-09-08", 580.0, 1), ("2026-09-15", "2026-10-07", 546.64, 1), ("2026-10-12", "2026-10-12", 520.0, 1),
                ("2026-10-12", "2026-10-20", 546.64, 1), ("2026-10-25", "2026-10-25", 546.64, 0)]
        # The paste's own sighting (5 Oct) sits inside the second span.
        got = self.spans(self.build(points))
        self.assertEqual(got, want)
        self.assertEqual(self.spans(self.build(list(reversed(points)))), want, "the order sightings arrive in changes nothing")

    def test_at_one_instant_a_page_we_hold_outranks_a_legacy_copy(self):
        conn = fresh_conn()
        b = Build(conn, None)
        b.owner()
        base = next(s.row for s in b.sightings if s.key == self.KEY)
        sight(b, "2026-10-08T00:00:00+00:00", dict(base, monthly_payment=999.0), priority=2)
        sight(b, "2026-10-08T00:00:00+00:00", dict(base, monthly_payment=111.0), priority=1)
        b.finish()
        self.assertEqual(self.spans(conn)[-1][2], 999.0)


class LegacyHistory(unittest.TestCase):
    """The committed history as a legacy source: copied byte for byte, read with its matches taken out."""

    def test_reading_strips_every_match(self):
        obs = (json.dumps({"offer_key": "ncd:1", "source": "ncd", "car_id": "carwow-cap:1", "observed_at": "t", "present": 1,
                           "payload": {"car_id": "carwow-cap:1", "vehicle_price": 30000.0, "saving_stated": 2000.0,
                                       "car_ref": {"source": "ncd", "key": "k", "make": "kia"}}}) + "\n"
               + json.dumps({"offer_key": "x", "source": "manual_seed", "car_id": "c", "payload": {}}) + "\n").encode()
        rows = legacy.read("observations", obs)
        self.assertEqual(len(rows), 1, "the owner's own offers are read from data/seed, not from their copy")
        self.assertNotIn("car_id", rows[0])
        self.assertNotIn("car_id", rows[0]["payload"])
        from pipeline.providers.ncd import OTR_EXTRAS_GBP
        self.assertEqual(rows[0]["payload"]["car_ref"]["rrp"], 30000.0 + 2000.0 - OTR_EXTRAS_GBP,
                         "the RRP today's parser derives from the price and saving the row kept")
        self.assertEqual(legacy.read("resolutions", b'{"car_id": "x"}\n'), [], "the old matches yield nothing")
        self.assertNotIn("car_id", legacy.read("specs", b'{"spec_key": "s", "car_id": "c", "payload": {"car_id": "c"}}\n')[0])

    def test_migrate_copies_every_committed_version_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, raw = Path(tmp) / "repo", Path(tmp) / "raw"
            (repo / "data" / "history").mkdir(parents=True)
            git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.email", "t@t")
            git("config", "user.name", "t")
            f = repo / "data" / "history" / "models.jsonl"
            for n in (1, 2):
                f.write_text(f'{{"slug": "kia/ev{n}"}}\n', encoding="utf-8")
                git("add", "-A")
                git("commit", "-q", "-m", f"v{n}")
            store = RawStore.open(raw)
            self.assertEqual(legacy.migrate(store, repo), {"added": 2, "already_there": 0})
            self.assertEqual(legacy.migrate(store, repo), {"added": 0, "already_there": 2}, "a second run adds nothing")
            entries = list(store.entries())
            self.assertEqual([store.get(e["sha256"]) for e in entries], [b'{"slug": "kia/ev1"}\n', b'{"slug": "kia/ev2"}\n'])
            self.assertEqual({(e["source"], e["capability"]) for e in entries}, {("legacy", "models")})


class TheScraperKeepsEveryResponse(unittest.TestCase):
    """runner.run keeps what each site sent: a combined fetch's parts byte for byte, a failed answer too."""

    def provider(self, fetch):
        from pipeline.providers.types import Capability, Provider, Target
        discover = lambda t, ctx: iter([Target("a", {"url": "https://x.test/a"}), Target("b", {"url": "https://x.test/b"})])
        parse = lambda body, t: iter([])
        return Provider("rrg", "offers", {"offers": Capability("offers", "1", discover, fetch, parse, ("offer",))})

    def test_parts_and_failures_are_kept(self):
        from pipeline import runner
        from pipeline.providers.http import FetchError
        from pipeline.providers.types import Context, Fetched

        def fetch(t, ctx):
            if t.identifier == "b":
                raise FetchError("https://x.test/b -> HTTP 429", status=429, body=b"slow down", url="https://x.test/b")
            p1, p2 = Fetched("https://x.test/a?p=1", 200, b'{"n": 1}'), Fetched("https://x.test/a?p=2", 200, b'{"n":2}')
            return Fetched("https://x.test/a", 200, b'{"pages": [1, 2]}', parts=(p1, p2))

        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            res = runner.run(store, None, self.provider(fetch), ctx=Context(root=ROOT))
            self.assertEqual((res.fetches, res.errors), (2, 1))
            entries = list(store.entries())
            parts = [e for e in entries if e.get("role") == "part"]
            self.assertEqual([store.get(e["sha256"]) for e in parts], [b'{"n": 1}', b'{"n":2}'], "each response as it came")
            self.assertEqual([e["url"] for e in parts], ["https://x.test/a?p=1", "https://x.test/a?p=2"])
            failed = next(e for e in entries if e["target"] == "b")
            self.assertEqual((failed["status"], store.get(failed["sha256"]), failed["error"]), (429, b"slow down", "https://x.test/b -> HTTP 429"))
            runs = list(store.read_log("runs"))
            self.assertEqual((runs[0]["source"], runs[0]["fetches"], runs[0]["errors"]), ("rrg", 2, 1))
            conn = fresh_conn()
            report = Build(conn, store).run()
            self.assertEqual((report.fetches, report.failures), (1, []), "the build parses the combined body; parts and failures are not pages")


class TheRawStoreSurvivesCrashes(unittest.TestCase):
    def test_a_torn_index_line_costs_only_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            store.save(source="rrg", capability="offers", target="a", metadata=None, url="u", fetched_at="2026-10-11T03:00:00+00:00",
                       status=200, body=b"one")
            with (Path(tmp) / "index" / "2026-10.jsonl").open("ab") as f:
                f.write(b'{"source": "rrg", "torn')          # a crash mid-write
            store.save(source="rrg", capability="offers", target="b", metadata=None, url="u", fetched_at="2026-10-11T03:01:00+00:00",
                       status=200, body=b"two")
            self.assertEqual([e["target"] for e in store.entries()], ["a", "b"])

    def test_a_broken_body_is_written_again_by_the_next_fetch_of_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            sha = store.put(b"the page")
            store.body_path(sha).write_bytes(b"")                 # a crash before the bytes reached the disk
            self.assertEqual(store.put(b"the page"), sha)
            self.assertEqual(store.get(sha), b"the page")

    def test_a_combined_fetch_that_fails_partway_keeps_the_pages_it_had(self):
        from pipeline import runner
        from pipeline.providers.http import FetchError
        from pipeline.providers.types import Capability, Context, Fetched, Provider, Target

        def fetch(t, ctx):
            e = FetchError("p3 -> HTTP 503", status=503, body=b"busy", url="https://x.test/a?p=3")
            e.parts = (Fetched("https://x.test/a?p=1", 200, b"page 1"), Fetched("https://x.test/a?p=2", 200, b"page 2"))
            raise e

        p = Provider("rrg", "offers", {"offers": Capability("offers", "1", lambda t, c: iter([Target("a", {"url": "u"})]), fetch,
                                                            lambda b, t: iter([]), ("offer",))})
        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            runner.run(store, None, p, ctx=Context(root=ROOT))
            got = sorted(store.get(e["sha256"]) for e in store.entries())
            self.assertEqual(got, [b"busy", b"page 1", b"page 2"])


if __name__ == "__main__":
    unittest.main()
