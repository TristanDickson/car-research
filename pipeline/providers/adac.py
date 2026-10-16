"""ADAC Autotest (adac.de, Germany's motoring club): its test of one car of a model, and the model's
breakdown statistics, from the tested car's page in ADAC's car catalogue.

https://www.adac.de/rund-ums-fahrzeug/autokatalog/marken-modelle/<make>/<range>/<generation>/<car id>/
is server-rendered with the page's data as JSON (`window.__APOLLO_STATE__`); no browser is needed.
On a tested car's page that JSON holds the whole Autotest: the date, the car tested, its overall
grade and every section grade with its sub-grades (Karosserie: Verarbeitung = build quality,
Kofferraum-Volumen = boot; Innenraum: Raumangebot hinten = rear space; Komfort: Federung =
suspension; ...), the target-group scores (family, city, ...), strengths and weaknesses. Grades
use the German school scale: 0.6 is the best, 5.5 the worst. Every car page also carries the
model's breakdown statistics (ADAC's roadside callouts per 1,000 registered cars in Germany, by
year of first registration, graded 1 very good to 5 poor against that year's spread; all
powertrains of the model together) and lists every test of its generation (`rangeTests`).

TESTS names the test read for each catalogue model: the newest electric test in the newest ADAC
generation the model belongs to (an N model takes only N tests, and no other model takes one),
chosen from the survey of 13 Oct 2026 (docs/SOURCES.md). ADAC's generation is wider than the
model: the A6 Sportback reads the A6 Avant's test, the EV4 Fastback the hatchback's. The page's
`rangeTests` are kept with the row, so a newer test of the generation shows when one appears.
Left: German prices and running costs, the maker's specification (our UK sources give it), and
the conclusion text.

The `pdf` capability reads each test's PDF (the page's `document`, under ASSETS), found from the
test rows the last build made, with poppler's pdftotext as hyundai_specs reads the Hyundai guides.
Its "ADAC Messwerte" block is ADAC's own measurements of the car tested: the tyres fitted, boot,
turning circle, braking from 100 km/h, noise at 130 km/h, the Ecotest (from 2026 "Autotest")
consumption and range, width, weight; the electric-drive page (the 2019 i3 test has none) adds
the energy for a full charge and the DC 10-80% time and average power. Two layouts: to 2025 one line
a measurement, from 2026 two columns with some labels wrapped onto a second line.


A tested car's page carries the breakdown statistics of its own generation only, so a test of a
generation too new to have any (the Ioniq 5 facelift's) has none. The `breakdowns` capability
reads the range page (`<make>/<range>/`), which carries the statistics of the range's latest
generation that has them (the Ioniq 5's: 19.5 per 1,000 for 2023 registrations, grade 5); the
build takes those over a test page's.

A test never changes and the breakdown statistics change once a year (April), so a page is read
again only after FRESH_DAYS; PER_RUN pages a run per capability, never-read ones first. A page
several models read (the four Enyaqs) is fetched once for all of them. Emits 'spec' records
keyed adac:<catalogue model> (the test), adac:breakdowns:<catalogue model> (the range page) and
adac:pdf:<catalogue model> (the test's PDF).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from pipeline.providers.http import fetch_url
from pipeline.providers.hyundai_specs import pdf_text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "adac"
BASE = "https://www.adac.de/rund-ums-fahrzeug/autokatalog/marken-modelle/"
ASSETS = "https://assets.adac.de/image/upload/Autodatenbank/Autotest/"
FRESH_DAYS = 90
PER_RUN = 25
TESTS = {
    "alpine/a290": "alpine/a290/1generation/335864",   # at6498 A290 GTS
    "audi/a6-avant-e-tron": "audi/a6/gh-c9/336507",   # at6483 A6 Avant e-tron performance
    "audi/a6-sportback-e-tron": "audi/a6/gh-c9/336507",   # at6483 A6 Avant e-tron performance
    "audi/e-tron-gt": "audi/e-tron-gt/fw-facelift/336003",   # at6593 S e-tron GT quattro
    "audi/q4-e-tron": "audi/q4-e-tron/fz/339178",   # at6591 Q4 40 e-tron advanced
    "audi/q4-e-tron-sportback": "audi/q4-e-tron/fz/339178",   # at6591 Q4 40 e-tron advanced
    "audi/q6-e-tron": "audi/q6-e-tron/gf/335645",   # at6477 Q6 e-tron performance
    "audi/q6-e-tron-sportback": "audi/q6-e-tron/gf/335645",   # at6477 Q6 e-tron performance
    "audi/rs-e-tron-gt": "audi/e-tron-gt/fw-facelift/336003",   # at6593 S e-tron GT quattro
    "audi/s6-avant-e-tron": "audi/a6/gh-c9/336507",   # at6483 A6 Avant e-tron performance
    "bmw/i3": "bmw/i3/i01-facelift/294684",   # at5861 i3 (120 Ah)
    "bmw/i4": "bmw/i4/i04-facelift/340348",   # at6537 i4 xDrive40 M Sportpaket
    "bmw/i5": "bmw/i5/g60-g61/328670",   # at6398 i5 eDrive40
    "bmw/i5-touring": "bmw/i5/g60-g61/328670",   # at6398 i5 eDrive40
    "bmw/i7": "bmw/i7/g70/324421",   # at6280 i7 xDrive60 Design Pure Excellence
    "bmw/ix": "bmw/ix/i20-facelift/338529",   # at6586 iX xDrive45
    "bmw/ix1": "bmw/ix1/u11/324969",   # at6312 iX1 xDrive30
    "bmw/ix2": "bmw/ix2/u10/329949",   # at6460 iX2 xDrive30
    "bmw/ix3": "bmw/ix3/na5/343921",   # at6606 iX3 50 xDrive
    "byd/atto-2": "byd/atto-2/1generation/338827",   # at6544 Atto 2 Boost
    "byd/atto-3-evo": "byd/atto-3/1generation/326262",   # at6303 Atto 3 Design
    "byd/dolphin": "byd/dolphin/1generation/328859",   # at6431 Dolphin Comfort
    "byd/dolphin-surf": "byd/dolphin-surf/1generation/340316",   # at6528 Dolphin Surf Boost
    "byd/seal": "byd/seal/1generation/328021",   # at6432 Seal Design
    "byd/sealion-7": "byd/sealion-7/1generation/337795",   # at6560 Sealion 7 Excellence AWD
    "citroen/e-c3": "citroen/c3/4generation/330136",   # at6525 e-C3 113 Standard Range You
    "citroen/e-c4": "citroen/c4/3generation/326613",   # at6325 e-C4 X 136 Standard-Range Shine Pack
    "citroen/e-spacetourer": "citroen/spacetourer/1generation/316195",   # at6193 e-Spacetourer XL (75 kWh) Shine
    "cupra/born": "cupra/born/1generation/336129",   # at6429 Born (79 kWh) VZ
    "cupra/tavascan": "cupra/tavascan/1generation/328192",   # at6574 Tavascan (77 kWh) Endurance
    "dacia/spring": "dacia/spring/1generation-facelift/333896",   # at6497 Spring electric 65 Expression
    "ds/3-e-tense": "ds-automobiles/ds-3/2generation/302285",   # at6053 DS 3 Crossback E-Tense So Chic
    "fiat/500-convertible": "fiat/500/f1a/321957",   # at6353 500e (23,8 kWh) RED
    "fiat/500-electric": "fiat/500/f1a/321957",   # at6353 500e (23,8 kWh) RED
    "fiat/600e": "fiat/600/365/328873",   # at6422 600e La Prima
    "fiat/grande-panda-electric": "fiat/grande-panda/328/337756",   # at6527 Grande Panda Electric RED
    "ford/capri": "ford/capri/4generation/336318",   # at6511 Capri Extended Range (79 kWh) Premium AWD
    "ford/explorer": "ford/explorer-ev/1generation/333818",   # at6491 Explorer EV Extended Range (79 kWh) Premium AWD
    "ford/mustang-mach-e": "ford/mustang-mach-e/1generation/308741",   # at6234 Mustang Mach-E Extended Range AWD
    "genesis/electrified-gv70": "genesis/gv70/1generation-facelift/325913",   # at6286 GV70 Electrified Sport AWD
    "genesis/g80-electrified": "genesis/g80/2generation-facelift/341094",   # at6582 G80 Electrified Premium AWD
    "genesis/gv60": "genesis/gv60/1generation-facelift/343917",   # at6554 GV60
    "hyundai/inster": "hyundai/inster/1generation/337912",   # at6496 Inster (42 kWh) Select
    "hyundai/ioniq-5": "hyundai/ioniq-5/1generation-facelift/336719",   # at6502 IONIQ 5 (84 kWh) UNIQ 2WD
    "hyundai/ioniq-5-n": "hyundai/ioniq-5/1generation-facelift/331077",   # at6426 IONIQ 5 N
    "hyundai/ioniq-6": "hyundai/ioniq-6/1generation-facelift/348386",   # at6631 IONIQ 6 (84 kWh) CENTRIQ
    "hyundai/ioniq-9": "hyundai/ioniq-9/1generation/341124",   # at6536 IONIQ 9 TECHNIQ (7-Sitzer)
    "hyundai/kona-electric": "hyundai/kona/2generation/329429",   # at6366 Kona Elektro (65 kWh) Prime-Paket
    "jeep/avenger-electric": "jeep/avenger/1generation/328561",   # at6362 Avenger Elektro Summit+
    "kia/ev2": "kia/ev2/1generation/350316",   # at6641 EV2 (42,2 kWh) Earth
    "kia/ev3": "kia/ev3/sv1/336657",   # at6480 EV3 (58,3 kWh) Earth
    "kia/ev4": "kia/ev4/sz1e-ct1/341448",   # at6580 EV4 (81,4 kWh) Earth
    "kia/ev4-fastback": "kia/ev4/sz1e-ct1/341448",   # at6580 EV4 (81,4 kWh) Earth
    "kia/ev5": "kia/ev5/ov1/343925",   # at6614 EV5 (81,4 kWh) GT-Line
    "kia/ev6": "kia/ev6/cv-facelift/337257",   # at6472 EV6 (84 kWh) Earth
    "kia/ev9": "kia/ev9/mv1/328942",   # at6383 EV9 (99,8 kWh) GT-Line AWD (6-Sitzer)
    "kia/pv5-passenger": "kia/pv5/1generation/340739",   # at6611 PV5 Passenger (71,2 kWh) Elite (5-Sitzer)
    "leapmotor/t03": "leapmotor/t03/1generation/337001",   # at6549 T03
    "mazda/6e": "mazda/6/gn/338191",   # at6546 6e 258 Takumi Plus
    "mercedes/amg-eqe-53": "mercedes-benz/eqe/295/322253",   # at6236 EQE 350
    "mercedes/amg-eqe-suv-53": "mercedes-benz/eqe-suv/294/326398",   # at6314 EQE SUV 350+ Electric Art Advanced
    "mercedes/eqa": "mercedes-benz/eqa/243/318936",   # at6120 EQA 250 Electric Art
    "mercedes/eqb": "mercedes-benz/eqb/243/322571",   # at6203 EQB 350 Electric Art 4MATIC
    "mercedes/eqe": "mercedes-benz/eqe/295/322253",   # at6236 EQE 350
    "mercedes/eqe-suv": "mercedes-benz/eqe-suv/294/326398",   # at6314 EQE SUV 350+ Electric Art Advanced
    "mercedes/eqs": "mercedes-benz/eqs/297-facelift/334810",   # at6569 EQS 450+ AMG Line
    "mercedes/eqv": "mercedes-benz/eqv/447-facelift/331872",   # at6493 EQV 300 lang (90 kWh)
    "mercedes/glc-electric": "mercedes-benz/glc/540/343929",   # at6628 GLC 400 elektrisch Avantgarde 4MATIC
    "mg/4-xpower": "mg/mg4/1generation/329348",   # at6448 MG4 Electric Extended Range Trophy
    "mg/mg-4": "mg/mg4/1generation/329348",   # at6448 MG4 Electric Extended Range Trophy
    "mg/mg4-urban": "mg/mg4-urban/1generation/350632",   # at6659 MG4 EV Urban (54 kWh) Premium
    "mg/s5-ev": "mg/mgs5/1generation/340301",   # at6540 MGS5 EV Long Range Luxury
    "mini/aceman": "mini/aceman/j05/334836",   # at6508 Aceman SE Favoured Trim
    "mini/aceman-jcw": "mini/aceman/j05/334836",   # at6508 Aceman SE Favoured Trim
    "mini/countryman-electric": "mini/countryman/u25/348790",   # at6635 Countryman E Favoured Trim
    "nissan/ariya": "nissan/ariya/fe0e/325740",   # at6282 Ariya (63 kWh) Evolve Pack (OBC 22 kW)
    "nissan/leaf": "nissan/leaf/ze2/349441",   # at6609 Leaf (75 kWh) Evolve
    "nissan/micra": "nissan/micra/k15/344064",   # at6622 Micra (52 kWh) Evolve
    "peugeot/e-2008": "peugeot/2008/2generation-facelift/329341",   # at6412 e-2008 156 GT
    "peugeot/e-208": "peugeot/208/2generation-facelift/329826",   # at6392 e-208 156 GT
    "peugeot/e-3008": "peugeot/3008/3generation/330773",   # at6464 e-3008 210 GT
    "peugeot/e-308": "peugeot/308/3generation/329678",   # at6443 e-308 156 GT
    "peugeot/e-308-sw": "peugeot/308/3generation/329678",   # at6443 e-308 156 GT
    "peugeot/e-5008": "peugeot/5008/3generation/335661",   # at6500 e-5008 210 GT
    "polestar/2": "polestar/2/1generation/327131",   # at6355 2 Long Range Single Motor (82 kWh)
    "polestar/4": "polestar/4/1generation/330709",   # at6482 4 Coupé Long Range Single Motor
    "polestar/4-suv": "polestar/4/1generation/330709",   # at6482 4 Coupé Long Range Single Motor
    "renault/4-e-tech": "renault/r4/2generation/337177",   # at6541 R4 E-Tech Electric 150 Comfort Range (52 kWh) Iconic
    "renault/5-e-tech": "renault/r5/iii/333030",   # at6481 R5 E-Tech Electric 150 Comfort Range (52 kWh) Techno
    "renault/megane-etech-electric": "renault/megane/v/322268",   # at6222 Mégane E-Tech Electric EV60 220hp optimum charge Techno
    "renault/scenic-e-tech": "renault/scenic/v/331262",   # at6440 Scénic E-Tech Electric 220 Long Range (87 kWh) Iconic
    "skoda/elroq": "skoda/elroq/1generation/337074",   # at6474 Elroq 85
    "skoda/enyaq": "skoda/enyaq/1generation-facelift/338072",   # at6505 Enyaq 85x Sportline
    "skoda/enyaq-coupe": "skoda/enyaq/1generation-facelift/338072",   # at6505 Enyaq 85x Sportline
    "skoda/enyaq-coupe-vrs": "skoda/enyaq/1generation-facelift/338072",   # at6505 Enyaq 85x Sportline
    "skoda/enyaq-vrs": "skoda/enyaq/1generation-facelift/338072",   # at6505 Enyaq 85x Sportline
    "smart/1": "smart/1/1generation/324276",   # at6485 #1 Premium
    "smart/3": "smart/3/1generation/329576",   # at6486 #3 Premium
    "smart/smart-5": "smart/5/1generation/339569",   # at6572 #5 Premium
    "suzuki/e-vitara": "suzuki/vitara/3generation/339987",   # at6608 e Vitara eAxle (61 kWh) Comfort+
    "tesla/model-3": "tesla/model-3/1generation-facelift/329536",   # at6405 Model 3 Maximale Reichweite AWD
    "tesla/model-3-performance": "tesla/model-3/1generation-facelift/329536",   # at6405 Model 3 Maximale Reichweite AWD
    "tesla/model-3-premium": "tesla/model-3/1generation-facelift/329536",   # at6405 Model 3 Maximale Reichweite AWD
    "tesla/model-y": "tesla/model-y/1generation-facelift/343407",   # at6652 Model Y Performance AWD
    "tesla/model-y-performance": "tesla/model-y/1generation-facelift/343407",   # at6652 Model Y Performance AWD
    "tesla/model-y-premium": "tesla/model-y/1generation-facelift/343407",   # at6652 Model Y Performance AWD
    "toyota/bz4x": "toyota/bz4x/eam1/324431",   # at6337 bZ4X Comfort-Paket
    "vauxhall/astra-electric": "opel/astra/l/329568",   # at6381 Astra Electric Sports Tourer GS
    "vauxhall/astra-sports-tourer-electric": "opel/astra/l/329568",   # at6381 Astra Electric Sports Tourer GS
    "vauxhall/combo-e": "opel/combo/e/321210",   # at6175 Combo Electric Life Ultimate
    "vauxhall/corsa-electric": "opel/corsa/f-facelift/328870",   # at6417 Corsa Electric (54 kWh) GS
    "vauxhall/grandland-electric": "opel/grandland/2generation/345308",   # at6571 Grandland Electric Long Range (97 kWh) GS
    "vauxhall/mokka-e": "opel/mokka/b/315851",   # at6108 Mokka Electric Ultimate
    "volkswagen/id3-neo": "vw/id3/1generation-facelift/335652",   # at6499 ID.3 GTX
    "volkswagen/id7": "vw/id7/1generation/335716",   # at6459 ID.7 Tourer GTX 4MOTION
    "volkswagen/id7-tourer": "vw/id7/1generation/335716",   # at6459 ID.7 Tourer GTX 4MOTION
    "volkswagen/idbuzz": "vw-nutzfahrzeuge/id-buzz/1generation/335808",   # at6479 ID. Buzz lang Pro
    "volvo/ec40": "volvo/c40/1generation/323952",   # at6265 C40 Recharge Pure Electric Single Motor Ultimate
    "volvo/es90": "volvo/es90/1generation/339499",   # at6602 ES90 Single Motor Extended Range Ultra
    "volvo/ex30": "volvo/ex30/1generation/338828",   # at6548 EX30 Cross Country Twin Motor Performance Ultra AWD
    "volvo/ex40": "volvo/xc40/1generation-facelift/326919",   # at6360 XC40 Recharge Pure Electric Single Motor Extended Range Ultimate
    "volvo/ex60": "volvo/ex60/1generation/348642",   # at6649 EX60 P10 Electric Ultra AWD
    "volvo/ex90": "volvo/ex90/1generation/344731",   # at6658 EX90 Twin Performance Ultra AWD (6/7-Sitzer)
    "xpeng/g6": "xpeng/g6/1generation/335815",   # at6484 G6 Long Range
}
# What the app shows, by ADAC's name: (section, sub-grade or None for the section's own grade).
GRADES = {
    "adac_suspension": ("Komfort", "Federung"),
    "adac_comfort": ("Komfort", None),
    "adac_build": ("Karosserie", "Verarbeitung"),
    "adac_boot": ("Karosserie", "Kofferraum-Volumen"),
    "adac_rear_space": ("Innenraum", "Raumangebot hinten"),
}
BREAKDOWN_GRADES = {1: "very good", 2: "good", 3: "satisfactory", 4: "adequate", 5: "poor"}
# ADAC's names for what broke down, in English; a name not here is shown as ADAC printed it.
CAUSES = {"Starterbatterie": "12-volt battery", "Fahrzeugelektrik allgemein": "general electrics", "Zündspule": "ignition coil",
          "Zündkerze": "spark plug", "Zündung allgemein": "ignition", "Öldruck": "oil pressure", "Generator": "alternator",
          "Anlasser": "starter motor", "Hochvoltbatterie": "high-voltage battery", "Kraftstoffpumpe": "fuel pump",
          "Motorsteuerung": "engine management", "Bordnetz": "on-board electrics", "Wegfahrsperre": "immobiliser",
          "Schlüssel": "key", "Reifen": "tyres", "Bremsen": "brakes", "Kühlmittelverlust": "coolant loss"}


def range_of(path: str) -> str:
    """'hyundai/ioniq-5/1generation-facelift/336719' → 'hyundai/ioniq-5'."""
    return "/".join(path.split("/")[:2])


def _targets(target: Target, ctx: Context, page_of, prefix: str) -> Iterator[Target]:
    """One target per page: never-read models first, then pages read more than FRESH_DAYS ago, stalest first;
    PER_RUN of them. `page_of` maps a TESTS path to the page read."""
    conn: sqlite3.Connection | None = ctx.extras.get("db")
    seen: dict[str, str] = {}
    if conn is not None:
        try:
            seen = {r[0][len(prefix):]: r[1] for r in conn.execute("SELECT spec_key, last_seen_at FROM specs WHERE source='adac'")
                    if r[0].startswith(prefix) and ":" not in r[0][len(prefix):].split("/")[0]}
        except sqlite3.OperationalError:
            pass
    wanted = [s for s in TESTS if target.identifier in ("all", s, page_of(TESTS[s]))]
    pages: dict[str, None] = {}
    for slug in _order(wanted, seen, target.identifier == "all"):
        pages.setdefault(page_of(TESTS[slug]))
    for path in list(pages)[:PER_RUN]:
        yield Target(identifier=path, metadata={"url": BASE + path + "/", "models": [s for s in TESTS if page_of(TESTS[s]) == path]})


def _order(wanted: list[str], seen: dict[str, str], rotate: bool) -> list[str]:
    """Never-read models first, then those read more than FRESH_DAYS ago, stalest first; on demand (`rotate`
    false), every model asked for."""
    if not rotate:
        return wanted
    cutoff = (datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)).isoformat()
    return ([s for s in wanted if s not in seen]
            + sorted((s for s in wanted if s in seen and seen[s] < cutoff), key=lambda s: seen[s]))


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    """The tested car's page of each model."""
    return _targets(target, ctx, lambda p: p, "adac:")


def discover_ranges(target: Target, ctx: Context) -> Iterator[Target]:
    """The range page of each model's test, for its breakdown statistics."""
    return _targets(target, ctx, range_of, "adac:breakdowns:")


def discover_pdfs(target: Target, ctx: Context) -> Iterator[Target]:
    """The PDF of each test the autotest capability has read, from the test rows in the build's database: one
    target a PDF, shared by the models that read the test. A model's PDF counts as read once a PDF row of the
    same test exists, so a model whose test changes reads the new one's PDF as never read."""
    conn: sqlite3.Connection | None = ctx.extras.get("db")
    if conn is None:
        return
    tests: dict[str, dict] = {}            # model -> the test its test page row names
    pdfs: dict[str, tuple] = {}            # model -> (the test its PDF row is of, last seen)
    try:
        for key, payload, last in conn.execute("SELECT spec_key, payload, last_seen_at FROM specs WHERE source='adac'"):
            p = json.loads(payload)
            test, model = p.get("test") or {}, p.get("model_slug")
            if key.startswith("adac:pdf:"):
                pdfs[model] = (test.get("id"), last)
            elif model in TESTS and p.get("source_url") == BASE + TESTS[model] + "/" and test.get("document"):
                tests[model] = test   # the test of the page TESTS names now, not one it named before
    except sqlite3.OperationalError:
        return
    seen = {m: last for m, (tid, last) in pdfs.items() if m in tests and tid == tests[m].get("id")}
    wanted = [s for s in TESTS if s in tests and target.identifier in ("all", s, tests[s]["document"])]
    docs: dict[str, None] = {}
    for slug in _order(wanted, seen, target.identifier == "all"):
        docs.setdefault(tests[slug]["document"])
    for doc in list(docs)[:PER_RUN]:
        models = [s for s in TESTS if s in tests and tests[s]["document"] == doc]
        test = {k: tests[models[0]].get(k) for k in ("id", "date", "model", "document")}
        yield Target(identifier=doc, metadata={"url": ASSETS + doc, "models": models, "test": test})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def fetch_pdf(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx, accept="application/pdf")


def apollo(page: str) -> dict:
    m = re.search(r"window\.__APOLLO_STATE__\s*=\s*", page)
    if not m:
        raise ValueError("no __APOLLO_STATE__ on the page")
    state, _ = json.JSONDecoder().raw_decode(page, m.end())
    return state


def _resolve(state: dict, v):
    return state.get(v["__ref"]) if isinstance(v, dict) and "__ref" in v else v


def find_breakdowns(state: dict) -> dict | None:
    """The page's breakdown statistics, wherever its data keeps them (a car page's carPage, a range page's referenced object)."""
    stack = [state]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get("__typename") == "ApilBreakdownStatistics":
                return o
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def breakdowns(stats: dict | None) -> tuple[dict, dict | None]:
    """(the app's numbers: the latest registration year's callouts per 1,000 and its grade; the statistics as printed)."""
    years = sorted(((i["year"], i["value"], i.get("valuationKey")) for i in (stats or {}).get("indicators") or []
                    if isinstance(i.get("value"), (int, float))), reverse=True)
    if not years:
        return {}, None
    y, v, key = years[0]
    numbers = {"adac_breakdowns": v, "adac_breakdown_year": y, **({"adac_breakdown_rating": BREAKDOWN_GRADES[key]} if key in BREAKDOWN_GRADES else {})}
    causes = [f"{CAUSES.get(d.get('name'), d.get('name'))} ({d.get('year')})" for d in stats.get("defects") or [] if d.get("name")]
    if causes:
        numbers["adac_breakdown_causes"] = "; ".join(causes)
    return numbers, {"name": stats.get("name"), "years": [{"year": y, "per_1000": v, "grade": k} for y, v, k in years],
                     "defects": [{"name": d.get("name"), "years": d.get("year")} for d in stats.get("defects") or []]}


def parse_page(page: str, model: str, url: str, observed_at: str) -> dict | None:
    """The test and the breakdown statistics a car page prints, for the catalogue model it was read for."""
    state = apollo(page)
    car = next((v.get("carPage") for k, v in (state.get("ROOT_QUERY") or {}).items() if k.startswith("carPage(")), None)
    if not car:
        return None
    tests = car.get("tests") or {}
    test = _resolve(state, tests.get("carTest"))
    numbers: dict = {}
    row: dict = {"spec_key": f"adac:{model}", "model_slug": model, "source_url": url, "observed_at": observed_at, "numbers": numbers}
    if test:
        grades = {r["name"]: {"grade": r.get("ratingNumber"), "subs": {s["name"]: s.get("ratingNumber") for s in r.get("subRatings") or []}}
                  for r in test.get("ratings") or []}
        for field, (section, sub) in GRADES.items():
            g = (grades.get(section) or {}).get("grade") if sub is None else ((grades.get(section) or {}).get("subs") or {}).get(sub)
            if isinstance(g, (int, float)):
                numbers[field] = g
        if isinstance(test.get("totalRating"), (int, float)):
            numbers["adac_total"] = test["totalRating"]
        family = (test.get("targetGroupCheck") or {}).get("family")
        if isinstance(family, (int, float)):
            numbers["adac_family"] = family
        numbers["adac_tested"] = f"{test.get('model')}, {test.get('date')}"
        row["test"] = {k: test.get(k) for k in ("id", "date", "model", "title", "totalRating", "document", "strengths", "weaknesses")}
        row["grades"] = grades
        row["target_groups"] = {k: v for k, v in (test.get("targetGroupCheck") or {}).items() if k != "__typename"}
    b_numbers, b = breakdowns(car.get("breakdownStatistics"))
    if b:
        numbers.update(b_numbers)
        row["breakdowns"] = b
    row["range_tests"] = [{k: t.get(k) for k in ("id", "carId", "model", "generationSlug")}
                          for t in (_resolve(state, r) for r in tests.get("rangeTests") or []) if t]
    return row if numbers else None


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    page = body.decode("utf-8", "replace")
    for model in target.metadata.get("models") or []:
        row = parse_page(page, model, target.metadata.get("url") or "", observed_at_for(target))
        if row:
            yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


def parse_range_page(page: str, model: str, url: str, observed_at: str) -> dict | None:
    """A range page's breakdown statistics, for a catalogue model in the range."""
    numbers, b = breakdowns(find_breakdowns(apollo(page)))
    if not b:
        return None
    return {"spec_key": f"adac:breakdowns:{model}", "model_slug": model, "source_url": url, "observed_at": observed_at,
            "numbers": numbers, "breakdowns": b}


def parse_ranges(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    page = body.decode("utf-8", "replace")
    for model in target.metadata.get("models") or []:
        row = parse_range_page(page, model, target.metadata.get("url") or "", observed_at_for(target))
        if row:
            yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


# ---------------------------------------------------------------- the test PDF

# The 'ADAC Messwerte' block's labels, as printed in either layout: (what, the label, the whole left-hand cell).
MEASURES = (
    ("overtake_60_100_s", r"Überholvorgang 60-100 km/h(?: \(in Fahrstufe D\))?"),
    ("overtake_80_120_s", r"Überholvorgang 80-120 km/h"),
    ("braking_100_m", r"Bremsweg aus 100 km/h"),
    ("tyre_size", r"Reifengröße(?: Testwagen)?"),
    ("tyre_brand", r"Reifen(?:marke Testwagen)?"),
    ("turning_circle_m", r"Wendekreis(?: links/rechts| \(li\./re\.\))?"),
    ("consumption", r"(?:Eco[Tt]est|Autotest)-Verbrauch"),
    ("range_km", r"Reichweite"),
    ("noise_130_db", r"Innengeräusch 130 km/h"),
    ("width_mirrors_mm", r"Fahrzeugbreite(?: \(inkl\. Außenspiegel\))?"),
    ("weight_payload_kg", r"Leergewicht/Zuladung"),
    ("boot_l", r"Kofferraum normal(?:/geklappt/dachhoch)?"),
    ("boot_folded_l", r"geklappt/dachhoch"),   # the 2026 layout wraps 'Kofferraum normal' onto a second line
)
DE_NUM_RE = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")   # '1.320' is 1320, '35,7' is 35.7
KM_PER_MILE = 1.609344


def _de(text: str) -> list[float]:
    return [float(x.replace(".", "").replace(",", ".")) if "," in x else int(x.replace(".", "")) for x in DE_NUM_RE.findall(text)]


def messwerte(text: str) -> dict[str, tuple[str, str]]:
    """The block's left-hand column: {what: (the label as printed, the value as printed)}. The right-hand columns
    (equipment, grades) start far to the right, so a cell is the line's text up to its next wide gap."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if "ADAC Messwerte" in line), None)
    if start is None:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for line in lines[start + 1:]:
        if re.match(r"\s*(?:KOSTEN|Kosten)\b", line):
            break
        if len(line) - len(line.lstrip()) > 10:   # a right-hand column's line
            continue
        cells = re.split(r"\s{3,}", line.strip())
        if len(cells) < 2:
            continue
        for what, label in MEASURES:
            if what not in out and re.fullmatch(label, cells[0]):
                out[what] = (cells[0], cells[1])
                break
    return out


def parse_pdf_text(text: str, model: str, url: str, observed_at: str, test: dict) -> dict | None:
    """ADAC's measurements of the car tested, from the PDF's text, for the catalogue model it was read for."""
    cells = messwerte(text)
    printed: dict = {}
    for what, (label, value) in cells.items():
        nums = _de(value)
        if what in ("tyre_size", "tyre_brand"):
            printed[what] = value
        elif what == "consumption":
            m = re.search(r"([\d,]+)\s*kWh/100\s*km", value)
            if m:
                printed["consumption_kwh_100km"] = _de(m.group(1))[0]
                printed["cycle"] = "Autotest" if label.startswith("Autotest") else "Ecotest"
        elif what == "boot_l" and "/" in label and len(nums) == 3:
            printed.update(boot_l=nums[0], boot_folded_l=nums[1], boot_roof_l=nums[2])
        elif what == "boot_folded_l" and len(nums) == 2:
            printed.update(boot_folded_l=nums[0], boot_roof_l=nums[1])
        elif what == "turning_circle_m" and nums:
            printed[what] = nums   # left and right, or one figure
        elif what == "weight_payload_kg" and len(nums) == 2:
            printed.update(weight_kg=nums[0], payload_kg=nums[1])
        elif nums and what not in ("boot_folded_l", "weight_payload_kg"):
            printed[what] = nums[0]
    # The electric-drive page: energy from the socket for a full charge, and ADAC's own DC charge from 10 to 80%.
    if m := re.search(r"[Kk]omplette Vollladung mit(?: Ladeverlusten)?\s+([\d,]+)\s*kWh", text):
        printed["full_charge_kwh"] = _de(m.group(1))[0]
    if m := re.search(r"Ø Ladeleistung\s+([\d,]+)\s*kW", text):
        printed["dc_avg_kw"] = _de(m.group(1))[0]
    if m := re.search(r"Ladedauer\s+(\d{1,2}):(\d{2})\b", text):
        printed["dc_10_80_min"] = int(m.group(1)) * 60 + int(m.group(2))
    if m := re.search(r"Testwagenpreis inkl\.(?: Sonderausstattung)?\s+([\d.]+) Euro", text):
        printed["price_tested_eur"] = _de(m.group(1))[0]   # German, so kept and not shown
    numbers: dict = {}
    tyres = ", ".join(printed[k] for k in ("tyre_size", "tyre_brand") if printed.get(k))
    if tyres:
        numbers["adac_tyres_tested"] = tyres
    for field, key in (("adac_boot_measured_l", "boot_l"), ("adac_boot_max_measured_l", "boot_roof_l"), ("adac_braking_100_m", "braking_100_m"),
                       ("adac_noise_130_db", "noise_130_db"), ("adac_60_100_s", "overtake_60_100_s"), ("adac_width_mirrors_mm", "width_mirrors_mm"),
                       ("adac_weight_kg", "weight_kg"), ("adac_payload_kg", "payload_kg"), ("adac_dc_10_80_min", "dc_10_80_min"),
                       ("adac_dc_avg_kw", "dc_avg_kw"), ("adac_full_charge_kwh", "full_charge_kwh")):
        if printed.get(key) is not None:
            numbers[field] = printed[key]
    if printed.get("turning_circle_m"):
        numbers["adac_turning_circle_m"] = max(printed["turning_circle_m"])
    if printed.get("range_km"):
        numbers["adac_ecotest_range_mi"] = round(printed["range_km"] / KM_PER_MILE)
    if printed.get("consumption_kwh_100km"):
        numbers["adac_ecotest_mi_kwh"] = round(100 / printed["consumption_kwh_100km"] / KM_PER_MILE, 2)
    if not numbers:
        return None
    return {"spec_key": f"adac:pdf:{model}", "model_slug": model, "source_url": url, "observed_at": observed_at,
            "numbers": numbers, "test": test, "printed": printed}


def parse_pdfs(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    text = pdf_text(body)
    for model in target.metadata.get("models") or []:
        row = parse_pdf_text(text, model, target.metadata.get("url") or "", observed_at_for(target), target.metadata.get("test") or {})
        if row:
            yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


autotest = Capability(name="autotest", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
breakdown_stats = Capability(name="breakdowns", parser_version="2", discover=discover_ranges, fetch=fetch, parse=parse_ranges, kinds=("spec",))
pdf = Capability(name="pdf", parser_version="1", discover=discover_pdfs, fetch=fetch_pdf, parse=parse_pdfs, kinds=("spec",))
provider = Provider(name="adac", default_capability="autotest", capabilities={"autotest": autotest, "breakdowns": breakdown_stats, "pdf": pdf}, live=True)
