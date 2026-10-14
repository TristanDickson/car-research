"""NHTSA's vehicle safety recalls (the US register): every recall filed in the US since 2010, in the file
NHTSA publishes for download (static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip, field guide RCL.txt).

One tab-separated line per recall, make, model, model year and recalled component: the campaign number
(24V868000, written 24V-868), the make and model as the recall record names them ('HYUNDAI', 'IONIQ 5';
'MERCEDES-BENZ', 'EQS 450' in one campaign and 'EQS450' in the next), the model year, the maker's reference,
the component, the build dates, the cars affected in the US (the campaign's total, every model in it), the
dates the report was received and the owners told, who started it, the defect, the consequence, the remedy,
the notes, and whether owners are told not to drive or to park outside. A recall that replaces one whose fix
did not hold says so ("This recall expands and replaces previous recall number 24V-204. Vehicles previously
repaired under recall 24V-204 will need to have the new remedy completed."); the build links them.

The open API (api.nhtsa.gov/recalls/recallsByVehicle?make=&model=&modelYear=) was surveyed first and left:
it answers only for a model name exactly as one campaign wrote it, its model lists use other names again
('MUSTANG MACH-E' where the recalls say 'MUSTANG MACH E'), and it returned 1 of the 13 recalls of the 2022
EQS 450 (docs/SOURCES.md). The file has every recall under every name.

MODELS names the catalogue models sold in the US (the API's model lists of model years 2019 to 2027, read
14 Oct 2026) with the pattern their recall records' model names follow, by make. Read: every vehicle recall
of model year 2019 or later whose make and model one of them matches. Left: equipment, tyre and child-seat
recalls, other cars, older model years, the component part numbers.

Emits one 'spec' record, nhtsa:recalls: the recalls read, each with the catalogue models it names, and the
list of models sold in the US. The file changes daily; it is fetched once every FRESH_DAYS (15 MB).
"""
from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

from pipeline.providers.http import fetch_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "nhtsa"
URL = "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip"
SINCE = 2019
FRESH_DAYS = 7
# Catalogue slug -> (the recall records' make, the pattern of their model names, the first model year it applies
# to). A name several catalogue models share (the Tesla Model 3 and its Performance) is read for each.
MODELS: dict[str, tuple[str, str] | tuple[str, str, int]] = {
    "audi/a6-avant-e-tron": ("AUDI", r"A6 (AVANT )?E-TRON"),
    "audi/a6-sportback-e-tron": ("AUDI", r"A6 (SPORTBACK )?E-TRON"),
    "audi/e-tron": ("AUDI", r"E-TRON( QUATTRO| S)?"),
    "audi/e-tron-gt": ("AUDI", r"(S )?E-TRON GT"),
    "audi/e-tron-sportback": ("AUDI", r"E-TRON( S)? SPORTBACK"),
    "audi/q4-e-tron": ("AUDI", r"Q4 E-TRON"),
    "audi/q4-e-tron-sportback": ("AUDI", r"Q4 SPORTBACK E-TRON"),
    "audi/q6-e-tron": ("AUDI", r"Q6 E-TRON"),
    "audi/q6-e-tron-sportback": ("AUDI", r"Q6 SPORTBACK E-TRON"),
    "audi/q8-e-tron": ("AUDI", r"Q8 E-TRON"),
    "audi/q8-e-tron-sportback": ("AUDI", r"Q8 SPORTBACK E-TRON"),
    "audi/rs-e-tron-gt": ("AUDI", r"RS E-TRON GT( PERFORMANCE)?"),
    "audi/s6-avant-e-tron": ("AUDI", r"S6 (AVANT )?E-TRON"),
    "audi/s6-sportback-e-tron": ("AUDI", r"S6 (SPORTBACK )?E-TRON"),
    "audi/sq6-e-tron": ("AUDI", r"SQ6 E-TRON"),
    "audi/sq6-e-tron-sportback": ("AUDI", r"SQ6 SPORTBACK E-TRON"),
    "audi/sq8-e-tron": ("AUDI", r"SQ8 E-TRON"),
    "audi/sq8-sportback-e-tron": ("AUDI", r"SQ8 SPORTBACK E-TRON"),
    "bmw/i3": ("BMW", r"I3( BEV| REX| S)?"),
    "bmw/i4": ("BMW", r"I4( .+)?"),
    "bmw/i5": ("BMW", r"I5( .+)?"),
    "bmw/i7": ("BMW", r"I7( .+)?"),
    "bmw/ix": ("BMW", r"IX( BEV| M\d+.*| XDRIVE\d+.*)?"),
    "bmw/ix3": ("BMW", r"IX3( .+)?"),
    "fiat/500-electric": ("FIAT", r"500E|500 BEV|500 ELECTRIC"),
    "ford/mustang-mach-e": ("FORD", r"MUSTANG MACH[- ]E( .+)?"),
    "genesis/electrified-gv70": ("GENESIS", r"(ELECTRIFIED GV70|GV70 ELECTRIFIED)( BEV)?"),
    "genesis/g80-electrified": ("GENESIS", r"(ELECTRIFIED G80|G80 ELECTRIFIED)( BEV)?"),
    "genesis/gv60": ("GENESIS", r"GV60( .+)?"),
    "genesis/gv70": ("GENESIS", r"(ELECTRIFIED GV70|GV70 ELECTRIFIED)( BEV)?"),
    "hyundai/ioniq-5": ("HYUNDAI", r"IONIQ 5( BEV)?"),
    "hyundai/ioniq-5-n": ("HYUNDAI", r"IONIQ 5( N)?( BEV)?", 2025),   # the N's recalls are filed under IONIQ 5
    "hyundai/ioniq-6": ("HYUNDAI", r"IONIQ 6( BEV)?"),
    "hyundai/ioniq-6-n": ("HYUNDAI", r"IONIQ 6( N)?( BEV)?", 2026),
    "hyundai/ioniq-9": ("HYUNDAI", r"IONIQ 9( BEV)?"),
    "hyundai/ioniq-electric": ("HYUNDAI", r"IONIQ (ELECTRIC|EV)"),
    "hyundai/kona-electric": ("HYUNDAI", r"KONA (ELECTRIC|EV)"),
    "jaguar/i-pace": ("JAGUAR", r"I-PACE"),
    "kia/ev3": ("KIA", r"EV3( BEV)?"),
    "kia/ev6": ("KIA", r"EV6( GT| BEV)?"),
    "kia/ev9": ("KIA", r"EV9( BEV)?"),
    "kia/niro-ev-estate": ("KIA", r"NIRO (EV|ELECTRIC)( BEV)?"),
    "kia/soul-ev": ("KIA", r"SOUL (EV|ELECTRIC)"),
    "lexus/rz": ("LEXUS", r"RZ( ?\d+E)?( BEV)?"),
    "lotus/eletre": ("LOTUS", r"ELETRE( .+)?"),
    "mazda/mx-30": ("MAZDA", r"MX-30( EV)?"),
    "mercedes/amg-eqe-53": ("MERCEDES-BENZ", r"AMG EQE( 53)?( 4MATIC\+?)?"),
    "mercedes/amg-eqe-suv-53": ("MERCEDES-BENZ", r"AMG EQE SUV( .+)?"),
    "mercedes/amg-eqs": ("MERCEDES-BENZ", r"AMG EQS( 53)?( 4MATIC\+?)?"),
    "mercedes/cla-electric": ("MERCEDES-BENZ", r"CLA (250\+|350 4MATIC)( \(EV\))?"),
    "mercedes/eqb": ("MERCEDES-BENZ", r"EQB( .+)?"),
    "mercedes/eqe": ("MERCEDES-BENZ", r"EQE( ?\d[\w+ ]*)?"),
    "mercedes/eqe-suv": ("MERCEDES-BENZ", r"EQE SUV( .+)?"),
    "mercedes/eqs": ("MERCEDES-BENZ", r"EQS( ?\d[\w+ ]*)?"),
    "mercedes/eqs-suv": ("MERCEDES-BENZ", r"EQS SUV( .+)?"),
    "mercedes/g-class-electric": ("MERCEDES-BENZ", r"G ?580( .+)?"),
    "mercedes/glc-electric": ("MERCEDES-BENZ", r"GLC 400( .+)?"),
    "mini/countryman-electric": ("MINI", r"COUNTRYMAN (SE|E)( ALL4)?( BEV)?", 2025),
    "mini/electric": ("MINI", r"(MINI )?COOPER SE( HARDTOP)?|HARDTOP SE"),
    "nissan/ariya": ("NISSAN", r"ARIYA( .+)?"),
    "nissan/leaf": ("NISSAN", r"LEAF( .+)?"),
    "polestar/2": ("POLESTAR", r"POLESTAR 2"),
    "polestar/3": ("POLESTAR", r"POLESTAR 3"),
    "polestar/4": ("POLESTAR", r"POLESTAR 4"),
    "polestar/4-suv": ("POLESTAR", r"POLESTAR 4"),
    "porsche/cayenne-electric": ("PORSCHE", r"CAYENNE( S| TURBO)?( COUPE)? ELECTRIC"),
    "porsche/macan-electric": ("PORSCHE", r"MACAN( 4S?| TURBO)? ELECTRIC|MACAN 4S?"),
    "porsche/taycan": ("PORSCHE", r"TAYCAN( 4| 4S| GTS| TURBO( S| GT)?)?( WITH .+)?"),
    "porsche/taycan-cross-turismo": ("PORSCHE", r"TAYCAN( 4| 4S| TURBO( S)?)? CROSS TURI\w*"),
    "porsche/taycan-gts-sport-turismo": ("PORSCHE", r"TAYCAN( GTS)? SPORT TURISMO"),
    "smart/eq-fortwo": ("SMART", r"FORTWO( .+)?|ELECTRIC COUPE"),
    "smart/eq-fortwo-cabrio": ("SMART", r"FORTWO( .+)?|ELECTRIC CABRIO"),
    "smart/fortwo": ("SMART", r"FORTWO( .+)?|ELECTRIC COUPE"),
    "smart/fortwo-electric-drive": ("SMART", r"FORTWO( .+)?|ELECTRIC COUPE"),
    "subaru/solterra": ("SUBARU", r"SOLTERRA( .+)?"),
    "tesla/model-3": ("TESLA", r"MODEL 3( .+)?"),
    "tesla/model-3-performance": ("TESLA", r"MODEL 3( .+)?"),
    "tesla/model-3-premium": ("TESLA", r"MODEL 3( .+)?"),
    "tesla/model-s": ("TESLA", r"MODEL S( .+)?"),
    "tesla/model-x": ("TESLA", r"MODEL X( .+)?"),
    "tesla/model-y": ("TESLA", r"MODEL Y( (?!L\b).+)?"),
    "tesla/model-y-performance": ("TESLA", r"MODEL Y( (?!L\b).+)?"),
    "tesla/model-y-premium": ("TESLA", r"MODEL Y( (?!L\b).+)?"),
    "toyota/bz4x": ("TOYOTA", r"BZ4X|BZ( BEV)?"),
    "toyota/bz4x-touring": ("TOYOTA", r"BZ WOODLAND( .+)?|BZ4X TOURING"),
    "toyota/c-hr-plus": ("TOYOTA", r"C-HR( BEV)?", 2026),
    "volkswagen/id4": ("VOLKSWAGEN", r"ID\.? ?4( .+)?"),
    "volkswagen/idbuzz": ("VOLKSWAGEN", r"ID\.? ?BUZZ( .+)?"),
    "volvo/c40-recharge": ("VOLVO", r"C40 ?(BEV|RECHARGE.*|P8.*)|EC40( .+)?"),
    "volvo/ec40": ("VOLVO", r"C40 ?(BEV|RECHARGE.*|P8.*)|EC40( .+)?"),
    "volvo/ex30": ("VOLVO", r"EX30( BEV)?"),
    "volvo/ex30-cross-country": ("VOLVO", r"EX30 ?CC|EX30 CROSS COUNTRY"),
    "volvo/ex40": ("VOLVO", r"XC40 ?(BEV|RECHARGE.*|P8.*)|EX40( .+)?"),
    "volvo/ex60": ("VOLVO", r"EX60( .+)?"),
    "volvo/ex90": ("VOLVO", r"EX90( .+)?"),
    "volvo/xc40-electric": ("VOLVO", r"XC40 ?(BEV|RECHARGE.*|P8.*)|EX40( .+)?"),
}
# Sold in the US, but filed under a name its petrol and hybrid cars share, so its recalls are not told apart.
SHARED_NAMES = {"lexus/es-electric": "ES", "land-rover/range-rover-electric": "RANGE ROVER"}
COMPILED = {slug: (spec[0], re.compile(spec[1], re.I), spec[2] if len(spec) > 2 else SINCE) for slug, spec in MODELS.items()}
MAKES = {make for make, _, _ in COMPILED.values()}
# The file's columns (RCL.txt), counted from 0.
CAMPNO, MAKETXT, MODELTXT, YEARTXT, MFGCAMPNO, COMPNAME, MFGNAME, BGMAN, ENDMAN, RCLTYPECD, POTAFF, ODATE, INFLUENCED_BY = range(1, 14)
RCDATE, DESC_DEFECT, CONSEQUENCE, CORRECTIVE_ACTION, NOTES, DO_NOT_DRIVE, PARK_OUTSIDE = 15, 19, 20, 21, 22, 27, 28


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    """The file, unless one read in the last FRESH_DAYS is held (a named target is always fetched)."""
    if target.identifier not in ("all", "recalls"):
        return
    conn: sqlite3.Connection | None = ctx.extras.get("db")
    if target.identifier == "all" and conn is not None:
        try:
            row = conn.execute("SELECT last_seen_at FROM specs WHERE spec_key='nhtsa:recalls'").fetchone()
        except sqlite3.OperationalError:
            row = None
        cutoff = (datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)).isoformat()
        if row and row[0] and row[0] >= cutoff:
            return
    yield Target(identifier="recalls", metadata={"url": URL})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx, accept="application/zip", timeout=120)


def _iso(d: str | None) -> str | None:
    d = (d or "").strip()
    if not re.fullmatch(r"\d{8}", d):
        return None
    try:
        return date(int(d[:4]), int(d[4:6]), int(d[6:])).isoformat()
    except ValueError:
        return None


def campaign(number: str) -> str:
    """'24V868000' -> '24V-868'."""
    m = re.fullmatch(r"(\d\d[A-Z])([0-9A-Z]{3})000", number.strip())
    return f"{m.group(1)}-{m.group(2)}" if m else number.strip()


def models_of(make: str, model: str, year: int) -> list[str]:
    """The catalogue models a recall record's make, model name and model year belong to."""
    name = " ".join(model.split())
    return sorted(slug for slug, (mk, rx, since) in COMPILED.items() if mk == make and year >= since and rx.fullmatch(name))


def parse_lines(lines: Iterator[str]) -> list[dict]:
    """Every vehicle recall naming a catalogue model since SINCE, one per campaign, with the records that name
    our models (make, model, year) and the catalogue models they belong to."""
    out: dict[str, dict] = {}
    for line in lines:
        c = line.rstrip("\r\n").split("\t")
        if len(c) < 23 or c[MAKETXT] not in MAKES or c[RCLTYPECD] != "V" or not c[YEARTXT].isdigit() or int(c[YEARTXT]) < SINCE:
            continue
        slugs = models_of(c[MAKETXT], c[MODELTXT], int(c[YEARTXT]))
        if not slugs:
            continue
        number = campaign(c[CAMPNO])
        r = out.get(number)
        if r is None:
            units = re.sub(r"\D", "", c[POTAFF])
            r = out[number] = {
                "number": number, "reported": _iso(c[RCDATE]), "owners_told": _iso(c[ODATE]), "maker": c[MFGNAME].strip(),
                "maker_ref": c[MFGCAMPNO].strip() or None, "started_by": c[INFLUENCED_BY].strip() or None,
                "defect": c[DESC_DEFECT].strip(), "consequence": c[CONSEQUENCE].strip(), "remedy": c[CORRECTIVE_ACTION].strip(),
                "notes": c[NOTES].strip(), "units": int(units) if units else None, "components": [], "vehicles": [],
                "built_from": None, "built_to": None,
                "do_not_drive": len(c) > DO_NOT_DRIVE and c[DO_NOT_DRIVE].strip().upper() == "YES",
                "park_outside": len(c) > PARK_OUTSIDE and c[PARK_OUTSIDE].strip().upper() == "YES",
            }
        if c[COMPNAME].strip() and c[COMPNAME].strip() not in r["components"]:
            r["components"].append(c[COMPNAME].strip())
        v = {"make": c[MAKETXT], "model": " ".join(c[MODELTXT].split()), "year": int(c[YEARTXT]), "models": slugs}
        if v not in r["vehicles"]:
            r["vehicles"].append(v)
        for f, d, pick in (("built_from", _iso(c[BGMAN]), min), ("built_to", _iso(c[ENDMAN]), max)):
            if d:
                r[f] = pick(r[f], d) if r[f] else d
    return sorted(out.values(), key=lambda r: (r["reported"] or "", r["number"]))


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        with z.open(name) as f:
            recalls = parse_lines(io.TextIOWrapper(f, encoding="latin-1", newline=""))
    if recalls:
        yield ParsedRecord(kind="spec", key="nhtsa:recalls", row={
            "spec_key": "nhtsa:recalls", "source_url": target.metadata.get("url"), "observed_at": observed_at_for(target),
            "recalls": recalls, "sold_in_us": sorted(MODELS), "shared_names": SHARED_NAMES})


recalls = Capability(name="recalls", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="nhtsa_recalls", default_capability="recalls", capabilities={"recalls": recalls}, live=True)
