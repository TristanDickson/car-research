"""Blocking is normal: how hard to lean on a site tonight, worked out from how it answered before."""
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from pipeline.providers import http, politeness
from pipeline.providers.types import Context
from pipeline.raw import RawStore
from tests.helpers import ROOT

HOST = "ev-database.org"


def night(store, day: str, statuses: list[int]) -> None:
    for i, s in enumerate(statuses):
        store.save(source="evdb_cars", capability="cars", target=str(i), metadata=None, url=f"https://{HOST}/uk/car/{i}",
                   fetched_at=f"{day}T03:{i % 60:02d}:00+00:00", status=s, body=b"x" if s == 200 else None)


class Allowance(unittest.TestCase):
    def test_back_off_after_refused_nights_then_ramp_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            self.assertEqual(politeness.allowance(store, HOST, 60), 60, "never asked: the usual number")
            night(store, "2026-10-10", [200] * 55 + [429])          # 55 pages, then refused
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 11, 3, 17, tzinfo=timezone.utc)), 0, "a refused night: rest the next one")
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 12, 3, 17, tzinfo=timezone.utc)), 10, "then ask for a few pages")
            night(store, "2026-10-11", [429])                       # what happened: refused again at once
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 12, 3, 17, tzinfo=timezone.utc)), 0, "two refused nights: rest two")
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 13, 3, 17, tzinfo=timezone.utc)), 0)
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 14, 3, 17, tzinfo=timezone.utc)), 10)
            night(store, "2026-10-14", [200] * 10)
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 15, 3, 17, tzinfo=timezone.utc)), 20, "each clean night doubles it")
            night(store, "2026-10-15", [200] * 20)
            night(store, "2026-10-16", [200] * 40)
            self.assertEqual(politeness.allowance(store, HOST, 60, datetime(2026, 10, 17, 3, 17, tzinfo=timezone.utc)), 60, "up to the usual number")
            self.assertEqual(politeness.allowance(None, HOST, 60), 60, "without a store (a hand run) the usual number")

    def test_a_guess_that_404d_this_week_is_not_asked_again_until_next_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawStore.open(tmp)
            for target, status, day in (("abarth/500e", 404, "2026-10-10"), ("kia/ev3", 200, "2026-10-10"),
                                        ("bmw/i4", 404, "2026-10-01"), ("mg/mg4", 404, "2026-10-09"), ("mg/mg4", 200, "2026-10-10")):
                store.save(source="leaseloco", capability="best-deals", target=target, metadata=None, url="u",
                           fetched_at=f"{day}T03:00:00+00:00", status=status, body=b"x" if status == 200 else None)
            got = politeness.recently_missing(store, "leaseloco", today=datetime(2026, 10, 11, tzinfo=timezone.utc))
            self.assertEqual(got, {"abarth/500e"}, "bmw/i4's 404 is over a week old; mg/mg4 answered since")


class OneRunNeverHammers(unittest.TestCase):
    def test_a_host_that_refuses_twice_in_a_row_is_not_asked_again_this_run(self):
        import urllib.error
        calls = []

        def refuse(req, timeout):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

        http.reset_refusals()
        ctx = Context(root=ROOT, delay_seconds=0)
        with mock.patch("urllib.request.urlopen", refuse):
            for i in range(2):
                with self.assertRaises(http.FetchError) as e:
                    http.fetch_url(f"https://{HOST}/{i}", ctx)
                self.assertNotIsInstance(e.exception, http.Blocked)
            with self.assertRaises(http.Blocked):
                http.fetch_url(f"https://{HOST}/2", ctx)
        self.assertEqual(len(calls), 2, "a 429 is not retried at once, and the third page is never sent")
        http.reset_refusals()


if __name__ == "__main__":
    unittest.main()
