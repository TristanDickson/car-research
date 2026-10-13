"""New Car Discount's PCP quotes, against responses captured on 2026-10-11 (no network).

ncd_kia_ev6_4x4_pcp.json is the combined body the pcp capability built that night from the
EV6 4x4 listing (ncd_kia_ev6_4x4_listing.html), seven derivative pages and seven /fincalc
answers; ncd_kia_ev6_gt_4x4_derivative.html is one of those pages. The Ioniq 5 N Line page and
its answer are the example the figures were checked against by eye: £683.01 a month, 35
payments, £1,000 deposit, final payment £15,623.74, 7.9% APR. The Ioniq 3 listing of that day
(kept by the nightly) and its Premium EV Pack's page and answer go through the build.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from pipeline.providers import ncd
from pipeline.providers.http import Blocked, FetchError
from pipeline.providers.types import Context, Fetched, Target

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-11T18:54:00+00:00"
LISTING_URL = "https://www.new-car-discount.com/car/kia/ev6/4x4/all/all"
GT = "/car/kia/ev6-electric-estate/4x4/electric/automatic/478kw-gt-84kwh-5dr-awd-auto/25/"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def ev6_target(**meta) -> Target:
    return Target("kia/ev6-4x4", {"make": "kia", "url": LISTING_URL, **meta})


class QuoteRequest(unittest.TestCase):
    def test_ioniq5_page_defaults(self):
        self.assertEqual(ncd.quote_request(fixture("ncd_hyundai_ioniq-5_nline_derivative.html")),
                         {"ftype": "PCP", "autoSelectPlan": True, "username": "xml", "capcode": "HYI500NLI5HE A  1",
                          "advance": 34815, "mileage": 10000, "deposit": 1000, "period": 36})

    def test_ev6_page_gives_the_request_sent_that_night(self):
        sent = next(q["request"] for q in json.loads(fixture("ncd_kia_ev6_4x4_pcp.json"))["quotes"] if q["href"] == GT)
        self.assertEqual(ncd.quote_request(fixture("ncd_kia_ev6_gt_4x4_derivative.html")), sent)

    def test_page_without_calculator(self):
        self.assertIsNone(ncd.quote_request("<html><body>gone</body></html>"))


class QuoteRow(unittest.TestCase):
    def test_ioniq5_answer(self):
        cash = {"vehicle_price": 34815.0, "listing_url": "u", "car_ref": {"source": "ncd", "key": "k"}}
        q = {"href": "/car/x/24/", "response": json.loads(fixture("ncd_hyundai_ioniq-5_nline_fincalc.json"))}
        r = ncd.quote_row(q, cash, T)
        self.assertEqual((r["monthly_payment"], r["num_payments"], r["term_months"], r["customer_deposit"], r["gfv"], r["apr"]),
                         (683.01, 35, 36, 1000.0, 15623.74, 0.079))
        self.assertEqual((r["vehicle_price"], r["amount_of_credit"], r["total_payable_stated"], r["cost_of_credit_stated"]),
                         (34815.0, 33815.0, 40529.09, 5714.09))
        self.assertEqual((r["annual_mileage"], r["status"], r["finance_type"], r["reconciles"]), (10000, "illustrative", "pcp", True))
        self.assertEqual(r["source_ref"], "HYI500NLI5HE A  1")
        self.assertNotIn("excess_mileage_ppm", r)   # NCD does not print one

    def test_failed_answer_gives_no_row(self):
        self.assertIsNone(ncd.quote_row({"href": "/x/", "response": {"ftype": "PCP", "monthlyPayments": 0}}, {"car_ref": {}}, T))
        self.assertIsNone(ncd.quote_row({"href": "/x/", "error": "HTTP 500"}, {"car_ref": {}}, T))


class ParsePcp(unittest.TestCase):
    def rows(self):
        body = (FIX / "ncd_kia_ev6_4x4_pcp.json").read_bytes()
        return [r.row for r in ncd.pcp.parse(body, ev6_target(observed_at=T))]

    def test_every_ev6_on_the_4x4_listing(self):
        rows = self.rows()
        self.assertEqual(len(rows), 7)
        gt = next(r for r in rows if r["offer_key"] == f"ncd:pcp:{GT}")
        self.assertEqual((gt["vehicle_price"], gt["monthly_payment"], gt["num_payments"], gt["gfv"], gt["apr"]),
                         (60788.0, 1334.68, 35, 22630.5, 0.079))
        self.assertEqual((gt["observed_at"], gt["captured_at"]), (T, "2026-10-11"))
        self.assertTrue(all(r["reconciles"] for r in rows))

    def test_car_ref_is_the_cash_rows(self):
        cash = {r["source_url"]: r for r in ncd.parse_page(fixture("ncd_kia_ev6_4x4_listing.html"), "kia", LISTING_URL, T)}
        for r in self.rows():
            self.assertEqual(r["car_ref"], cash[r["source_url"]]["car_ref"])
            self.assertEqual(r["vehicle_price"], cash[r["source_url"]]["vehicle_price"])

    def test_deterministic(self):
        self.assertEqual(self.rows(), self.rows())


class FetchQuotes(unittest.TestCase):
    """fetch_quotes against the captured responses, with a stand-in for fetch_url."""

    def setUp(self):
        self.doc = json.loads(fixture("ncd_kia_ev6_4x4_pcp.json"))
        self.answers = {q["request"]["capcode"]: json.dumps(q["response"]).encode() for q in self.doc["quotes"]}
        self.sent = []

    def fake(self, refuse_after=None):
        def fetch_url(url, ctx, *, data=None, **kw):
            self.sent.append((url, data))
            if url == LISTING_URL:
                return Fetched(url, 200, fixture("ncd_kia_ev6_4x4_listing.html").encode("utf-8"))
            if url == ncd.FINCALC:
                return Fetched(url, 200, self.answers[json.loads(data)["capcode"]], "application/json")
            if refuse_after is not None and len(self.sent) > refuse_after:
                raise Blocked("not asked", url=url)
            if url.endswith(GT):
                return Fetched(url, 200, fixture("ncd_kia_ev6_gt_4x4_derivative.html").encode("utf-8"))
            raise FetchError(f"{url} -> HTTP 404", status=404, body=b"not found", url=url)
        return fetch_url

    def test_failed_pages_kept_and_skipped(self):
        with mock.patch.object(ncd, "fetch_url", self.fake()):
            f = ncd.pcp.fetch(ev6_target(), Context(root=FIX))
        # the listing, six pages that answered 404, the GT's page and its answer
        self.assertEqual([p.status_code for p in f.parts], [200] + [404] * 6 + [200, 200])
        doc = json.loads(f.body)
        self.assertEqual(len(doc["quotes"]), 7)
        self.assertEqual([q["href"] for q in doc["quotes"] if "response" in q], [GT])
        rows = [r.row for r in ncd.pcp.parse(f.body, ev6_target(observed_at=T))]
        self.assertEqual([(r["offer_key"], r["monthly_payment"]) for r in rows], [(f"ncd:pcp:{GT}", 1334.68)])

    def test_refused_host_stops_asking(self):
        with mock.patch.object(ncd, "fetch_url", self.fake(refuse_after=3)), self.assertRaises(FetchError) as e:
            ncd.pcp.fetch(ev6_target(), Context(root=FIX))
        # no quote answered: the run is told so, and what came back is still kept
        self.assertEqual(len(e.exception.parts), 3)
        self.assertEqual(len(self.sent), 4)


class ThroughTheBuild(unittest.TestCase):
    """The Ioniq 3 listing of 2026-10-11 and the Premium EV Pack's page and quote fetched that day."""

    PREMIUM = "/car/hyundai/ioniq-3-electric-hatchback/hatchback/electric/automatic/99kw-premium-61kwh-5dr-auto-ev-pack/26/"
    URL = "https://www.new-car-discount.com/car/hyundai/ioniq-3/hatchback/all/all"

    def fetch_url(self, url, ctx, *, data=None, **kw):
        if url == self.URL:
            return Fetched(url, 200, (FIX / "ncd_hyundai_ioniq-3_listing_2026-10-11.html").read_bytes())
        if url == ncd.FINCALC:
            return Fetched(url, 200, (FIX / "ncd_hyundai_ioniq-3_premium-ev-pack_fincalc.json").read_bytes())
        if url.endswith(self.PREMIUM):
            return Fetched(url, 200, (FIX / "ncd_hyundai_ioniq-3_premium-ev-pack_derivative.html").read_bytes())
        raise FetchError(f"{url} -> HTTP 404", status=404, body=b"", url=url)

    def test_the_quote_is_on_the_cash_rows_car(self):
        from tests.helpers import Raws
        target = Target("hyundai/ioniq-3", {"make": "hyundai", "url": self.URL})
        with mock.patch.object(ncd, "fetch_url", self.fetch_url):
            body = ncd.pcp.fetch(target, Context(root=FIX)).body
        with Raws() as raws:
            raws.add("ncd", "hyundai/ioniq-3", "ncd_hyundai_ioniq-3_listing_2026-10-11.html", at=T)
            raws.add("ncd", "hyundai/ioniq-3", body=body, capability="pcp", at=T)
            conn = raws.build()
        q = "SELECT car_id, status, vehicle_price, monthly_payment FROM offer_observations WHERE offer_key=?"
        cash, pcp = conn.execute(q, (f"ncd:{self.PREMIUM}",)).fetchone(), conn.execute(q, (f"ncd:pcp:{self.PREMIUM}",)).fetchone()
        self.assertEqual(tuple(cash), ("hyundai-ioniq3-61-premium-evpack", "lead", 28829.0, None))
        self.assertEqual(tuple(pcp), ("hyundai-ioniq3-61-premium-evpack", "illustrative", 28829.0, 600.77))


class Listings(unittest.TestCase):
    def test_ev6_4x4_listing_read(self):
        targets = {t.identifier: t.metadata["url"] for t in ncd.discover(Target("all"), Context(root=FIX))}
        self.assertEqual(targets["kia/ev6-4x4"], LISTING_URL)
        self.assertNotIn("kia/ev6", targets, "the estate listing holds only the GT's diesel-coded copy")
        rows = ncd.parse_page(fixture("ncd_kia_ev6_4x4_listing.html"), "kia", LISTING_URL, T)
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]["car_ref"]["key"], "kia|kia ev6 electric estate|125kw air sr 63kwh 5dr auto")

    def test_an_electric_car_filed_under_another_fuel_is_not_read(self):
        """NCD's EV6 estate listing (11 Oct 2026) holds one line, the EV6 GT filed as a diesel: a copy with the
        wrong vehicle code, priced £60 under the electric one, that NCD's finance quote answers 'not found in
        residual database'."""
        page = fixture("ncd_kia_ev6_estate_listing.html")
        self.assertIn("/estate/diesel/automatic/478kw-gt-84kwh-5dr-awd-auto/", page)
        self.assertEqual(ncd.parse_page(page, "kia", "https://www.new-car-discount.com/car/kia/ev6/estate/all/all", T), [])

    def test_capabilities(self):
        self.assertEqual(sorted(ncd.provider.capabilities), ["backfill", "listing", "pcp"])
        self.assertEqual(ncd.provider.default_capability, "listing")


if __name__ == "__main__":
    unittest.main()
