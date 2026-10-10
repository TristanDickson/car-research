"""Wayback backfill plumbing, without the network: thinning, timestamps, and a
backfilled capture kept in the raw store and folded into the span history."""
import unittest
from pathlib import Path

from pipeline.providers import carwow_deals, wayback
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from tests.helpers import Raws

FIX = Path(__file__).parent / "fixtures"


class Helpers(unittest.TestCase):
    def test_thin_keeps_one_per_window_and_drops_repeated_bodies(self):
        snaps = [("20250101120000", "A"), ("20250103120000", "A"), ("20250109120000", "A"), ("20250117120000", "B"),
                 ("20250118120000", "C"), ("20250301120000", "C")]
        # 0103 and 0109 fall inside the 7-day window after 0101; 0118 inside the one after 0117;
        # 0301 is a new body outside any window, so it stays.
        self.assertEqual(wayback.thin(snaps, 7), [("20250101120000", "A"), ("20250117120000", "B"), ("20250301120000", "C")])
        self.assertEqual(wayback.thin(snaps, 1), [("20250101120000", "A"), ("20250117120000", "B"), ("20250118120000", "C")])

    def test_timestamp_and_archive_url(self):
        self.assertEqual(wayback.ts_to_iso("20250901123456"), "2025-09-01T12:34:56+00:00")
        self.assertEqual(wayback.archive_url("20250901123456", "https://x.test/p"), "https://web.archive.org/web/20250901123456id_/https://x.test/p")

    def test_observed_at_and_original_url_fall_back(self):
        t = Target("x", {"url": "https://x.test/p"})
        self.assertEqual(wayback.original_url(t), "https://x.test/p")
        self.assertTrue(wayback.observed_at_for(t).startswith("20"))
        t2 = Target("x@1", {"url": "https://web.archive.org/web/1id_/https://x.test/p", "original_url": "https://x.test/p", "observed_at": "2025-09-01T00:00:00+00:00"})
        self.assertEqual((wayback.original_url(t2), wayback.observed_at_for(t2)), ("https://x.test/p", "2025-09-01T00:00:00+00:00"))


class ThroughTheScraper(unittest.TestCase):
    def test_a_capture_is_kept_dated_by_the_archive_and_folds_in_as_an_earlier_sighting(self):
        import json
        from pipeline import runner
        body = (FIX / "carwow_hyundai_ioniq-3_deals.html").read_bytes()
        page = carwow_deals.url_for("hyundai", "ioniq-3")
        base = carwow_deals.provider.capability_for("deals")

        def discover(target, ctx):
            yield Target("hyundai/ioniq-3@20250901000000", {"make": "hyundai", "model": "ioniq-3", "make_name": "Hyundai",
                                                            "url": wayback.archive_url("20250901000000", page), "original_url": page,
                                                            "observed_at": "2025-09-01T00:00:00+00:00"})

        def fetch(target, ctx):
            return Fetched(url=target.metadata["url"], status_code=200, body=body)

        p = Provider("carwow_deals", "deals", {"deals": base, "backfill": Capability("backfill", base.parser_version, discover, fetch, base.parse, base.kinds)})
        with Raws() as raws:
            res = runner.run(raws.store, None, p, "backfill", ctx=Context(root=FIX))
            self.assertEqual((res.errors, res.fetches), (0, 1))
            raws.add("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", at="2026-10-06T00:00:00+00:00")
            e = next(e for e in raws.store.entries() if e["capability"] == "backfill")
            self.assertEqual((e["origin"], e["target"], e["metadata"]["observed_at"]), ("wayback", "hyundai/ioniq-3@20250901000000", "2025-09-01T00:00:00+00:00"))
            self.assertTrue(e["url"].startswith("https://web.archive.org/web/20250901000000id_/"))
            conn = raws.build()
        rows = conn.execute("SELECT observed_at, confirmed_at, vehicle_price FROM offer_observations WHERE offer_key='carwow:cash:111015' ORDER BY observed_at").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("2025-09-01T00:00:00+00:00", "2026-10-06T00:00:00+00:00", 25620.0)],
                         "same price: one span, starting at the archived date")
        payload = json.loads(conn.execute("SELECT payload FROM offer_observations WHERE offer_key='carwow:cash:111015'").fetchone()["payload"])
        self.assertEqual(payload["source_url"], page, "the row's own source_url is the original page, not the archive copy")


class LedgerAndBudget(unittest.TestCase):
    """A chunk that stops at its time budget leaves a ledger the next run resumes from."""

    def _fake_cdx(self, counts):
        import pipeline.providers.wayback as wb
        orig = wb.cdx_snapshots
        seen = []

        def cdx(url, since, ctx):
            seen.append(url)
            return [(f"2025010{i + 1}120000", f"d{i}") for i in range(counts.get(url, 0))]

        wb.cdx_snapshots = cdx
        self.addCleanup(lambda: setattr(wb, "cdx_snapshots", orig))
        return seen

    def test_pages_whose_captures_were_consumed_are_skipped_next_time(self):
        from pipeline.db import connect, init_schema
        from pipeline.providers import carwow_deals
        from pipeline.providers.types import Context, Target
        from pipeline.providers.wayback import backfill_capability

        conn = connect(":memory:")
        init_schema(conn)
        cap = backfill_capability(carwow_deals.deals)
        urls = [t.metadata["url"] for t in carwow_deals.discover(Target("all"), Context(root=FIX))]
        seen = self._fake_cdx({urls[0]: 2, urls[1]: 1})
        ctx = Context(root=FIX, extras={"db": conn, "since": "2025-01-01", "every_days": 1})
        targets = list(cap.discover(Target("all"), ctx))
        self.assertEqual(len(targets), 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM backfill_ledger").fetchone()[0], len(urls), "every page done")
        seen.clear()
        self.assertEqual(list(cap.discover(Target("all"), ctx)), [])
        self.assertEqual(seen, [], "nothing asked of the archive the second time")
        # A different window is a different job.
        self.assertEqual(len(list(cap.discover(Target("all"), Context(root=FIX, extras={"db": conn, "since": "2024-01-01", "every_days": 1})))), 3)

    def test_budget_stops_before_a_new_page_and_the_ledger_marks_only_finished_ones(self):
        from pipeline.db import connect, init_schema
        from pipeline.providers import carwow_deals
        from pipeline.providers.types import Context, Target
        from pipeline.providers.wayback import backfill_capability

        conn = connect(":memory:")
        init_schema(conn)
        cap = backfill_capability(carwow_deals.deals)
        urls = [t.metadata["url"] for t in carwow_deals.discover(Target("all"), Context(root=FIX))]
        self._fake_cdx({u: 1 for u in urls})
        # A budget already spent (a negative one, so a coarse clock reading zero elapsed time still counts it spent).
        ctx = Context(root=FIX, extras={"db": conn, "since": "2025-01-01", "every_days": 1, "budget_seconds": -1})
        gen = cap.discover(Target("all"), ctx)
        first = next(gen)                       # the first page's capture is handed out
        self.assertEqual(first.metadata["original_url"], urls[0])
        self.assertEqual(list(gen), [], "no second page once the budget is spent")
        done = [r[0] for r in conn.execute("SELECT url FROM backfill_ledger")]
        self.assertEqual(done, [urls[0]], "the page whose capture was consumed is done; the rest wait")


if __name__ == "__main__":
    unittest.main()
