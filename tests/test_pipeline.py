"""The default settings through the build, prices folded into spans, the snapshot's shape, and
the committed history read with its matches taken out."""
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline import history
from pipeline.build import Build
from pipeline.db import ROOT
from pipeline.providers.types import Target
from pipeline.raw import RawStore
from pipeline.services.snapshot import SCHEMA_VERSION, export_snapshot, latest_offers
from tests.helpers import Raws, dump, fresh_conn, run_all


def q(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def sight(b: Build, at: str, row: dict, provider: str = "carwow_deals", priority: int = 2) -> None:
    b._sight(at, priority, provider, dict(row, observed_at=at), None)


def offer(key: str, monthly: float, cap: str = "9") -> dict:
    """A Carwow PCP whose line describes its derivative (a stub), so the build makes the car it sits on."""
    return {"offer_key": key, "finance_type": "pcp", "status": "live", "vehicle_price": 30000.0, "monthly_payment": monthly,
            "car_ref": {"source": "carwow-cap", "key": cap, "stub": {
                "cap_id": cap, "make": "Kia", "model": "EV3", "trim": "Air", "engine": "150kW 58.3kWh Auto", "rrp": 33055.0,
                "version_date": "2025-04-01"}}}


class DefaultSettings(unittest.TestCase):
    def test_the_settings_alone_build_no_car_and_the_same_every_time(self):
        c = run_all()
        self.assertEqual(q(c, "SELECT COUNT(*) FROM cars"), 0, "nothing but a page makes a car")
        self.assertEqual(q(c, "SELECT COUNT(*) FROM offer_observations"), 0)
        self.assertEqual(q(c, "SELECT COUNT(*) FROM trim_map"), 0)
        reqs = json.loads(q(c, "SELECT payload FROM requirements WHERE id=1"))
        self.assertEqual(set(reqs) - {"schema_version", "as_of"}, {"quoting_basis", "searches"})
        self.assertEqual(reqs["quoting_basis"]["term_months"], 37)
        self.assertTrue(any(s.get("default") for s in reqs["searches"]))
        self.assertEqual(dump(c), dump(run_all()), "a second build is the same database")

    def test_export_snapshot_shape(self):
        with Raws() as raws, tempfile.TemporaryDirectory() as tmp:
            raws.add("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", at="2026-10-05T00:00:00+00:00")
            conn = raws.build()
            manifest = export_snapshot(conn, tmp, generated_at="2026-10-06T00:00:00+00:00")
            out = Path(tmp)
            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(manifest["counts"]["unmapped_trims"], 0)
            self.assertFalse((out / "deals.json").exists())
            cars = json.loads((out / "cars.json").read_text(encoding="utf-8"))
            details = json.loads((out / "details.json").read_text(encoding="utf-8"))
            self.assertNotIn("requirement_check", next(iter(details.values())), "requirements are the reader's searches")
            spans = json.loads((out / "sightings.json").read_text(encoding="utf-8"))
            data = json.loads((out / "data.json").read_text(encoding="utf-8"))
            reqs = json.loads((out / "requirements.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cars), manifest["counts"]["cars"])
            self.assertGreater(len(cars), 10)
            self.assertEqual(len({s["key"] for s in spans}), manifest["counts"]["offers"])
            self.assertGreater(manifest["counts"]["offers"], 10)
            self.assertEqual([p["name"] for p in data["providers"]][0], "manual_seed")
            self.assertEqual(data["unmapped_trims"], [])
            self.assertIn("quoting_basis", reqs)
            for s in spans:
                self.assertTrue(set(s) >= {"key", "car_id", "route", "source", "from", "to", "present", "deal", "status"})
                self.assertNotIn("metrics", s, "costs are the browser's")
                self.assertEqual(s["source"], "carwow")
            for o in latest_offers(conn):
                self.assertIn(o["freshness"]["state"], {"live", "lead", "derived", "illustrative", "campaign", "expired", "historical", "gone"})
            for c in cars:
                self.assertTrue(c["id"].startswith("carwow-cap:"))
                self.assertIn("image", c)
                self.assertNotIn("deal_summary", c, "the pipeline exports facts; the browser costs them")


class Spans(unittest.TestCase):
    """Sightings fold into spans in date order, whichever order they were read in."""

    KEY = "carwow:deal:aea9f090b32568c0f0326d4ef6cf6299"
    OTHER = "carwow:deal:ccbac930e8c40084fe1590a6e91466a1"
    BASE = offer(KEY, 546.64)

    def build(self, points):
        conn = fresh_conn()
        b = Build(conn, None)
        b.settings()
        sight(b, "2026-10-05T00:00:00+00:00", self.BASE)
        sight(b, "2026-10-05T00:00:00+00:00", offer(self.OTHER, 526.07))
        for at, changes in points:
            sight(b, at, dict(self.BASE, **changes))
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
        other = offers[self.OTHER]["freshness"]
        self.assertEqual(other["state"], "live")
        self.assertTrue(other["stale"])
        self.assertEqual(other["age_days"], 29)

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
        # The first sighting (5 Oct) sits inside the second span.
        got = self.spans(self.build(points))
        self.assertEqual(got, want)
        self.assertEqual(self.spans(self.build(list(reversed(points)))), want, "the order sightings arrive in changes nothing")

    def test_at_one_instant_a_page_we_hold_outranks_the_committed_historys_copy(self):
        conn = fresh_conn()
        b = Build(conn, None)
        b.settings()
        sight(b, "2026-10-08T00:00:00+00:00", dict(self.BASE, monthly_payment=999.0), priority=2)
        sight(b, "2026-10-08T00:00:00+00:00", dict(self.BASE, monthly_payment=111.0), priority=1)
        b.finish()
        self.assertEqual(self.spans(conn)[-1][2], 999.0)


class CommittedHistory(unittest.TestCase):
    """The committed history as a source: copied byte for byte, read with its matches taken out."""

    def test_reading_strips_every_match(self):
        obs = (json.dumps({"offer_key": "ncd:1", "source": "ncd", "car_id": "carwow-cap:1", "observed_at": "t", "present": 1,
                           "payload": {"car_id": "carwow-cap:1", "vehicle_price": 30000.0, "saving_stated": 2000.0,
                                       "car_ref": {"source": "ncd", "key": "k", "make": "kia"}}}) + "\n"
               + json.dumps({"offer_key": "x", "source": "manual_seed", "car_id": "c", "payload": {}}) + "\n").encode()
        rows = history.read("observations", obs)
        self.assertEqual(len(rows), 1, "the hand-entered offers the owner ruled out are not read from their copy either")
        self.assertNotIn("car_id", rows[0])
        self.assertNotIn("car_id", rows[0]["payload"])
        from pipeline.providers.ncd import OTR_EXTRAS_GBP
        self.assertEqual(rows[0]["payload"]["car_ref"]["rrp"], 30000.0 + 2000.0 - OTR_EXTRAS_GBP,
                         "the RRP today's parser derives from the price and saving the row kept")
        self.assertEqual(history.read("resolutions", b'{"car_id": "x"}\n'), [], "the old matches yield nothing")
        # A Carwow example kept 36 payments for its 36-month term; its own total says 35 (the Avenger's, 6 Oct).
        rep = json.dumps({"offer_key": "carwow:rep:110446", "source": "carwow_deals", "finance_type": "pcp", "observed_at": "t", "present": 1,
                          "payload": {"term_months": 36, "num_payments": 36, "monthly_payment": 294.0, "customer_deposit": 6621.0,
                                      "manufacturer_contribution": 6550.0, "gfv": 11963.0, "total_payable_stated": 35412.0}}).encode()
        self.assertEqual(history.read("observations", rep)[0]["payload"]["num_payments"], 35)
        self.assertNotIn("car_id", history.read("specs", b'{"spec_key": "s", "car_id": "c", "payload": {"car_id": "c"}}\n')[0])

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
            self.assertEqual(history.migrate(store, repo), {"added": 2, "already_there": 0})
            self.assertEqual(history.migrate(store, repo), {"added": 0, "already_there": 2}, "a second run adds nothing")
            entries = list(store.entries())
            self.assertEqual([store.get(e["sha256"]) for e in entries], [b'{"slug": "kia/ev1"}\n', b'{"slug": "kia/ev2"}\n'])
            self.assertEqual({(e["source"], e["capability"]) for e in entries}, {("history", "models")})


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


class Records(unittest.TestCase):
    """`records`: what each source said, as spans of unchanged content."""

    def test_a_page_seen_again_extends_its_records_and_a_change_starts_a_new_one(self):
        from tests.helpers import Raws
        with Raws() as raws:
            for at in ("2026-10-06T00:00:00+00:00", "2026-10-07T00:00:00+00:00"):
                raws.add("carwow_specs", "hyundai/kona-electric", "carwow_hyundai_kona-electric_specifications.html", at=at)
            conn = raws.build()
            rows = conn.execute("SELECT first_seen_at, last_seen_at, sightings, origin FROM records "
                                "WHERE source='carwow_specs' AND record_key='carwow-cap:103322'").fetchall()
            self.assertEqual([tuple(r) for r in rows], [("2026-10-06T00:00:00+00:00", "2026-10-07T00:00:00+00:00", 2, "live")])
            # The same page, a week on, with the Advance's RRP changed: a second span.
            body = (Path(__file__).parent / "fixtures" / "carwow_hyundai_kona-electric_specifications.html").read_bytes()
            from pipeline.providers import carwow_specs
            recs = [r for r in carwow_specs.parse(body, Target("hyundai/kona-electric", {
                "make": "hyundai", "model": "kona-electric", "make_name": "Hyundai",
                "url": "https://www.carwow.co.uk/hyundai/kona-electric/specifications"})) if r.key == "carwow-cap:103322"]
            rrp = recs[0].row["rrp"]
            changed = body.replace(f"{rrp:,.0f}".encode(), f"{rrp + 500:,.0f}".encode())
            self.assertNotEqual(changed, body)
            raws.add("carwow_specs", "hyundai/kona-electric", body=changed, at="2026-10-14T00:00:00+00:00")
            conn = raws.build()
            spans = conn.execute("SELECT first_seen_at, sightings FROM records WHERE source='carwow_specs' "
                                 "AND record_key='carwow-cap:103322' ORDER BY first_seen_at").fetchall()
            self.assertEqual([tuple(r) for r in spans], [("2026-10-06T00:00:00+00:00", 2), ("2026-10-14T00:00:00+00:00", 1)])
            # The default settings are a record too, undated.
            self.assertEqual(conn.execute("SELECT first_seen_at, origin FROM records WHERE kind='requirements'").fetchone()[:],
                             ("", "settings"))


if __name__ == "__main__":
    unittest.main()
