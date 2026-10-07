"""Wayback backfill plumbing, without the network: thinning, timestamps, and a
backfilled capture flowing through the runner into the span history."""
import unittest
from pathlib import Path

from pipeline.providers import carwow_deals, wayback
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target
from pipeline.runner import run
from tests.helpers import fresh_conn, run_all

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


class ThroughTheRunner(unittest.TestCase):
    def test_backfilled_capture_lands_as_an_earlier_sighting(self):
        conn = fresh_conn()
        run_all(conn)
        base = carwow_deals.provider.capability_for("deals")
        body = (FIX / "carwow_hyundai_ioniq-3_deals.html").read_bytes()

        # A live sighting today, then a 'capture' of the same page dated 1 Sep.
        def live_discover(target, ctx):
            yield Target("hyundai/ioniq-3", {"make": "hyundai", "model": "ioniq-3", "url": carwow_deals.url_for("hyundai", "ioniq-3")})

        def live_fetch(target, ctx):
            return Fetched(url=target.metadata["url"], status_code=200, body=body)

        live = Capability("deals", "1", live_discover, live_fetch, base.parse, base.kinds)
        wb = wayback.backfill_capability(live)

        def fake_discover(target, ctx):
            for t in live_discover(target, ctx):
                yield Target(f"{t.identifier}@20250901000000", {**t.metadata, "url": wayback.archive_url("20250901000000", t.metadata["url"]),
                                                                   "original_url": t.metadata["url"], "observed_at": "2025-09-01T00:00:00+00:00"})

        def fake_fetch(target, ctx):
            return Fetched(url=target.metadata["url"], status_code=200, body=body)

        wb_offline = Capability("backfill", wb.parser_version, fake_discover, fake_fetch, wb.parse, wb.kinds)
        p = Provider("carwow_deals", "deals", {"deals": live, "backfill": wb_offline}, live=False)
        run(conn, p, "deals", ctx=Context(root=FIX))
        res = run(conn, p, "backfill", ctx=Context(root=FIX))
        self.assertEqual((res.errors, res.unmapped), (0, 0))
        rows = conn.execute("SELECT observed_at, confirmed_at, vehicle_price FROM offer_observations WHERE offer_key='carwow:cash:111015' ORDER BY observed_at").fetchall()
        self.assertEqual(len(rows), 1, "same price → one span, starting at the archived date")
        self.assertEqual(rows[0]["observed_at"], "2025-09-01T00:00:00+00:00")
        self.assertTrue(rows[0]["confirmed_at"] > "2026")
        self.assertEqual(rows[0]["vehicle_price"], 25620.0)
        art = conn.execute("SELECT url, target FROM artifacts WHERE capability='backfill'").fetchone()
        self.assertTrue(art["url"].startswith("https://web.archive.org/web/20250901000000id_/"))
        self.assertEqual(art["target"], "hyundai/ioniq-3@20250901000000")
        # The row's own source_url is the original page, not the archive copy.
        import json
        payload = json.loads(conn.execute("SELECT payload FROM offer_observations WHERE offer_key='carwow:cash:111015'").fetchone()["payload"])
        self.assertEqual(payload["source_url"], carwow_deals.url_for("hyundai", "ioniq-3"))


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
        ctx = Context(root=FIX, extras={"db": conn, "since": "2025-01-01", "every_days": 1, "budget_seconds": 0})
        gen = cap.discover(Target("all"), ctx)
        first = next(gen)                       # the first page's capture is handed out
        self.assertEqual(first.metadata["original_url"], urls[0])
        self.assertEqual(list(gen), [], "no second page once the budget is spent")
        done = [r[0] for r in conn.execute("SELECT url FROM backfill_ledger")]
        self.assertEqual(done, [urls[0]], "the page whose capture was consumed is done; the rest wait")


if __name__ == "__main__":
    unittest.main()
