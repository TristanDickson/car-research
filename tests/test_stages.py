"""The Data page's pipeline section (pipeline/stages.py): what each source holds at each level, and what
each stage did night by night, from the raw store's index and logs and the build's own matching."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import stages
from pipeline.services.snapshot import export_snapshot
from tests.helpers import Raws

NIGHT = "2026-10-11T02:20:00+00:00"   # the 03:17 BST run on 11 Oct: the night of 10 Oct


class NightLabels(unittest.TestCase):
    def test_a_night_runs_from_noon_to_noon(self):
        self.assertEqual(stages.night_of("2026-10-11T02:20:00+00:00"), "2026-10-10")
        self.assertEqual(stages.night_of("2026-10-10T18:12:00+00:00"), "2026-10-10", "the evening before is the same night")
        self.assertEqual(stages.night_of("2026-10-11T12:30:00+00:00"), "2026-10-11")
        self.assertIsNone(stages.night_of(None))


class LevelsAndNights(unittest.TestCase):
    def setUp(self):
        self.raws = Raws()
        s = self.raws.store
        self.raws.add("ncd", "hyundai/ioniq-3", "ncd_hyundai_ioniq-3_listing.html", at=NIGHT)
        # A refused fetch: kept in the index with its status, no records.
        s.save(source="ncd", capability="listing", target="hyundai/kona", metadata={"make": "hyundai", "url": "u"}, url="u",
               fetched_at="2026-10-11T02:21:00+00:00", status=429, body=b"slow down")
        s.log_run({"source": "ncd", "capability": "listing", "target": "all", "started_at": NIGHT, "finished_at": "2026-10-11T02:22:00+00:00",
                   "status": "ok", "fetches": 2, "records": 20, "errors": 1, "skipped": 0, "deferred": 1})
        s.log_run({"source": "evdb_cars", "capability": "pages", "target": "all", "started_at": NIGHT, "finished_at": NIGHT,
                   "status": "ok", "fetches": 0, "records": 0, "errors": 0, "allowance": {"ev-database.org": [0, 40]}})
        s.log("builds", {"stage": "build", "mode": "nightly", "started_at": "2026-10-10T02:30:00+00:00", "finished_at": "2026-10-10T02:33:00+00:00",
                         "seconds": 150.0, "fetches": 1, "parsed": 1, "from_cache": 0, "records": 20, "sightings": 20, "record_spans": 20,
                         "unparsed": 0, "commit": "abc", "snapshot": {"cars": 1}})
        self.conn = self.raws.build()

    def tearDown(self):
        self.raws.close()

    def test_each_source_at_each_level(self):
        page = stages.page(self.conn, None, {"ncd": {"offers": 3}})
        ncd = next(lv for lv in page["levels"] if lv["provider"] == "ncd")
        self.assertEqual((ncd["raw"]["fetches"], ncd["raw"]["failed"], ncd["raw"]["refused"]), (2, 1, 1))
        offers = ncd["records"]["offer"]["keys"]
        self.assertGreater(offers, 0)
        self.assertEqual(ncd["matched"]["offers"]["total"], offers, "every offer read is counted at the matching level")
        self.assertEqual(ncd["in_snapshot"], {"offers": 3})
        self.assertFalse(ncd["describes_models"])

    def test_each_night_has_its_scrapes_builds_and_refusals(self):
        page = stages.page(self.conn, {"stage": "build", "mode": "build", "started_at": "2026-10-11T03:00:00+00:00"}, {})
        night = next(n for n in page["nights"] if n["night"] == "2026-10-10")
        ncd = next(s for s in night["scrapes"] if s["source"] == "ncd")
        self.assertEqual((ncd["fetches"], ncd["responses"], ncd["refused"], ncd["deferred"], ncd["records"]), (2, 2, 1, 1, 20))
        evdb = next(s for s in night["scrapes"] if s["source"] == "evdb_cars")
        self.assertEqual(evdb["allowance"], {"ev-database.org": [0, 40]}, "resting: politeness let it ask for nothing")
        self.assertEqual([b.get("this", False) for b in night["builds"]], [True], "this snapshot's own build, on the night it ran")
        earlier = next(n for n in page["nights"] if n["night"] == "2026-10-09")
        self.assertEqual(earlier["builds"][0]["mode"], "nightly", "a logged build, on its own night")

    def test_the_snapshot_carries_the_section(self):
        with tempfile.TemporaryDirectory() as out:
            export_snapshot(self.conn, out, generated_at="2026-10-11T03:05:00+00:00")
            data = json.loads((Path(out) / "data.json").read_text(encoding="utf-8"))
        ncd = next(lv for lv in data["pipeline"]["levels"] if lv["provider"] == "ncd")
        self.assertEqual(ncd["in_snapshot"]["offers"], ncd["matched"]["offers"]["matched"], "every offer that names a car reaches the app")
        self.assertTrue(any(n["night"] == "2026-10-10" for n in data["pipeline"]["nights"]))


class TheRunLog(unittest.TestCase):
    def test_a_run_records_what_politeness_allowed_it(self):
        from pipeline.providers.politeness import note
        from pipeline.providers.types import Capability, Context, Provider
        from pipeline.runner import run

        def discover(target, ctx):
            note(ctx, "example.org", 0, 40)   # resting after refusals: nothing asked tonight
            return iter(())

        cap = Capability(name="pages", parser_version="1", discover=discover, fetch=None, parse=None, kinds=("spec",))
        provider = Provider(name="resting", default_capability="pages", capabilities={"pages": cap}, live=True)
        with Raws() as raws:
            run(raws.store, None, provider, ctx=Context(root=Path(".")))
            (r,) = raws.store.read_log("runs")
        self.assertEqual((r["fetches"], r["allowance"]), (0, {"example.org": [0, 40]}))


class TheBuildLog(unittest.TestCase):
    """A build logs itself only when it writes the real snapshot: a build into a scratch folder is someone
    trying something, and stays out of the history."""

    def test_only_a_build_of_the_real_snapshot_is_logged(self):
        from argparse import Namespace
        from unittest import mock

        from pipeline import cli

        with Raws() as raws, tempfile.TemporaryDirectory() as real, tempfile.TemporaryDirectory() as scratch:
            raws.add("ncd", "hyundai/ioniq-3", "ncd_hyundai_ioniq-3_listing.html", at=NIGHT)
            args = Namespace(db=str(Path(scratch) / "b.sqlite"), no_cache=True, generated_at=None, cmd="nightly")
            with mock.patch.object(cli, "DEFAULT_OUT", Path(real)):
                cli._build(args, raws.store, str(Path(scratch) / "out"))
                self.assertEqual(list(raws.store.read_log("builds")), [], "a scratch folder is not logged")
                cli._build(args, raws.store, real)
            (b,) = raws.store.read_log("builds")
            self.assertEqual((b["mode"], b["fetches"], b["snapshot"]["offers"] > 0), ("nightly", 1, True))
            data = json.loads((Path(real) / "data.json").read_text(encoding="utf-8"))
            built = [x for n in data["pipeline"]["nights"] for x in n["builds"]]
            self.assertEqual([x.get("this") for x in built], [True], "the snapshot names its own build")


if __name__ == "__main__":
    unittest.main()
