"""Carwow dealer-offer pages pasted as text (data/pastes/carwow/*.txt).

Carwow has no API and blocks datacenter scraping, but the offer page copied out
of a logged-in browser is a complete representative example. Each paste file is
the Bronze artifact; this parser turns it into one offer observation.

File format:
    # captured_at: 2026-10-05T15:26:50Z      (any other '# ...' header lines are ignored)
    <the page text as copied>

Carwow's own vocabulary is kept in the Silver row; the Gold conventions applied
here are: vehicle_price = "Carwow price" (net of discount and grant, before the
manufacturer contribution); num_payments reconciled against the page's own
totals (Carwow sometimes prints 35 where 36 reconciles); offer key = the Carwow
deal id, which is stable per dealer offer.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline.providers.types import (
    Capability,
    Context,
    Fetched,
    ParsedRecord,
    Provider,
    Target,
)

SITE = "carwow"
MONEY = re.compile(r"£\s*([\d,]+(?:\.\d+)?)")


def money(s: str | None) -> float | None:
    m = MONEY.search(s or "")
    return float(m.group(1).replace(",", "")) if m else None


def pct(s: str | None) -> float | None:
    m = re.search(r"([\d.]+)\s*%", s or "")
    return float(m.group(1)) / 100 if m else None


def number(s: str | None) -> float | None:
    m = re.search(r"([\d,]+(?:\.\d+)?)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def normalise_trim_key(make: str, model: str, trim: str) -> str:
    t = re.sub(r"\s*kwh", "kwh", trim.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return f"{make.lower()}|{model.lower()}|{t}"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    folder = ctx.root / "data" / "pastes" / "carwow"
    if not folder.exists():
        return
    names = sorted(p.name for p in folder.glob("*.txt"))
    if target.identifier != "all":
        names = [n for n in names if n == target.identifier]
    for name in names:
        yield Target(identifier=name)


def fetch(target: Target, ctx: Context) -> Fetched:
    path = ctx.root / "data" / "pastes" / "carwow" / target.identifier
    return Fetched(url=path.resolve().as_uri(), status_code=200, body=path.read_bytes(), content_type="text/plain")


class _Lines:
    def __init__(self, text: str):
        self.all = [ln.strip() for ln in text.splitlines()]
        self.lines = [ln for ln in self.all if ln]

    def index(self, label: str, start: int = 0) -> int:
        for i in range(start, len(self.lines)):
            if self.lines[i] == label:
                return i
        return -1

    def after(self, label: str, start: int = 0) -> str | None:
        i = self.index(label, start)
        return self.lines[i + 1] if 0 <= i < len(self.lines) - 1 else None

    def match(self, pattern: str, start: int = 0) -> re.Match | None:
        rx = re.compile(pattern)
        for ln in self.lines[start:]:
            m = rx.search(ln)
            if m:
                return m
        return None


def parse_page(text: str) -> dict:
    """Parse one pasted Carwow dealer-offer page into an offer row (Gold schema)."""
    captured = re.search(r"^#\s*captured_at:\s*(\S+)", text, re.M)
    if not captured:
        raise ValueError("paste file needs a '# captured_at: <iso>' header line")
    observed_at = captured.group(1)
    body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    L = _Lines(body)

    deal = re.search(r"Deal ID:\s*([0-9a-f]{32})", body)
    if not deal:
        raise ValueError("no 'Deal ID:' on the page")
    deal_id = deal.group(1)

    i = L.index("My cars")
    model_line = L.lines[i + 1] if i >= 0 else None
    dealer = L.lines[i + 2] if i >= 0 else None
    if not model_line:
        raise ValueError("could not find the model line after 'My cars'")
    make, _, model = model_line.partition(" ")

    trim_m = L.match(r"^(.*?)\s+Brand new\b(?:\s+(.*))?$")
    if not trim_m:
        raise ValueError("could not find the trim line ('... Brand new <location>')")
    trim, location = trim_m.group(1), (trim_m.group(2) or "").strip() or None

    pcp = L.index("Carwow PCP offer")
    finance_type = "pcp" if pcp >= 0 else "cash"
    s = pcp if pcp >= 0 else 0

    stated_payments = L.match(r"^(\d+) monthly payments of$", s)
    row: dict = {
        "id": f"{SITE}:deal:{deal_id}",
        "offer_key": f"{SITE}:deal:{deal_id}",
        "observed_at": observed_at,
        "captured_at": observed_at[:10],
        "present": 1,
        "status": "live",
        "verification": "pasted",
        "source": "Carwow dealer offer",
        "dealer": dealer,
        "source_ref": f"Carwow deal ID {deal_id}",
        "car_ref": {"source": SITE, "key": normalise_trim_key(make, model, trim), "label": f"{model_line} {trim}"},
        "finance_type": finance_type,
        "condition": "Brand new",
        "location": location,
        "list_price": money(L.after("RRP", s)),
        "vehicle_price": money(L.after("Carwow price", s)),
        "saving_stated": money(L.after("You save", s)),
    }
    if finance_type == "pcp":
        monthly = money(L.after("Carwow PCP offer", s))
        total_payable = money(L.after("Total amount payable", s))
        gfv = money(L.after("Optional final payment", s))
        contrib = money(L.after("Manufacturer deposit contribution", s)) or 0.0
        deposit = money(L.after("Deposit", s)) or 0.0
        n_stated = int(stated_payments.group(1)) if stated_payments else None
        n = n_stated
        if monthly and total_payable is not None and gfv is not None:
            implied = round((total_payable - contrib - deposit - gfv) / monthly)
            if n_stated is None or implied != n_stated:
                n = implied
        row.update({
            "customer_deposit": deposit,
            "manufacturer_contribution": contrib,
            "amount_of_credit": money(L.after("Total amount of credit", s)),
            "term_months": int(number(L.after("Term of agreement", s)) or 0) or None,
            "num_payments": n,
            "num_payments_stated": n_stated,
            "monthly_payment": monthly,
            "apr": pct(L.after("Representative APR", s)),
            "fixed_rate_pa": pct(L.after("Fixed rate of interest pa", s)),
            "gfv": gfv,
            "total_payable_stated": total_payable,
            "cost_of_credit_stated": money(L.after("Cost of credit", s)),
            "annual_mileage": int(number(L.after("Mileage per annum", s)) or 0) or None,
            "excess_mileage_ppm": number(L.after("Excess mileage charges", s)),
        })
        if n_stated is not None and n != n_stated:
            row["notes"] = (
                f"Page says {n_stated} monthly payments but {n} reconciles with its total payable, "
                f"contribution and final payment; {n} recorded."
            )
    ins = L.match(r"^(\d{1,2}[A-Z])$", L.index("Insurance group") if L.index("Insurance group") >= 0 else 0)
    row["car_facts"] = {
        "power_bhp": number(L.after("Engine power")),
        "seats": int(number(L.after("Seats")) or 0) or None,
        "wltp_range_mi": number(L.after("Battery range")),
        "boot_l": number(L.after("Boot (seats up)")),
        "boot_max_l": number(L.after("Boot (seats down)")),
        "insurance_group": ins.group(1) if ins else None,
        "zero_to_62_s": number(L.after("Acceleration (0-62mph)")),
        "top_speed_mph": number(L.after("Top speed")),
        "efficiency_mi_kwh": number(L.after("Efficiency")),
        "warranty": L.after("Warranty"),
    }
    return row


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    row = parse_page(body.decode("utf-8"))
    yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)


offers = Capability(
    name="offers",
    parser_version="1",
    discover=discover,
    fetch=fetch,
    parse=parse,
    kinds=("offer",),
)

provider = Provider(name="carwow_paste", default_capability="offers", capabilities={"offers": offers})
