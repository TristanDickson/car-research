"""One reading of every source's text: the make, model and derivative names a source prints, and the units
in them, read the same way before anything compares them (docs/ARCHITECTURE-NEXT.md, "Transform", step 1).

    fold        accents out and case folded: 'Škoda' → 'skoda', 'Citroën' → 'citroen'
    compact     letters and digits only, folded: names compared whole ('Mercedes-Benz' → 'mercedesbenz')
    words       folded words, any punctuation a break, a '+' kept on the word it follows: 'GT-Line S' is
                'GT Line S' (gt, line, s); 'Techno +' → techno+
    name_words  a derivative's, trim's, engine's or pack's words, CAP's short forms read as the long ones
                ('eDr40' → edrive40, 'Qtro' → quattro, 'Black Ed' → black edition): SHORT_FORMS
    make_key    a make, its aliases resolved: 'Mercedes-Benz', 'Mercedes' and the slug 'mercedes' agree
    units       kw, kwh, kwhs, ps, bhp, km_to_miles: the number a text prints before its unit
    key, slug   a record's identity, made from its names: never folded, so a record keeps the key it has
                always had (offers and committed history are keyed on these)

Nothing here drops a word that tells versions apart ('Long Range', 'AWD', 'Performance', the kW and kWh
figures, a bracketed pack's words): what a rule then ignores is the rule's own (services/match.py, STOP).
A rule comparing a CAP-style name with a registry name takes an exact match of the two as printed before
it compares them read this way (services/resolve.py), so nothing here can break an exact match.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Letters NFKD leaves whole; marks that would otherwise read as words ('™' as 'TM').
_LETTERS = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ł": "l", "Ł": "L", "đ": "d",
                          "Đ": "D", "ð": "d", "þ": "th", "ı": "i", "™": " ", "®": " ", "©": " "})


def fold(s: str | None) -> str:
    """Accents removed and case folded; nothing else changed."""
    s = unicodedata.normalize("NFKD", (s or "").translate(_LETTERS))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def compact(s: str | None) -> str:
    """Letters and digits only: 'GT-Line S' → 'gtlines', 'Škoda' → 'skoda'."""
    return re.sub(r"[^a-z0-9]", "", fold(s))


def words(s: str | None) -> list[str]:
    """The folded words: punctuation and spaces both break words, a '+' stays on the word before it."""
    return [re.sub(r"\s+", "", w) for w in re.findall(r"[a-z0-9]+(?:\s*\+)?", fold(s))]


# ---------------------------------------------------------------- CAP's short forms

# CAP's short descriptions and the long ones, both printed in the stored derivative names: Carwow's registry
# (its model pages' 'trims and prices' table, providers/carwow_model.py) and Parkers' derivative pages
# (providers/parkers.py), with the brokers that reprint CAP's names. Each: (short words, long words, the makes
# it holds for or None for any, where both forms were seen). A short form is read on whole words only, the
# longest first, and keeps a '+' after it ('Comf+' → comfort+). Not here: '4M' alone (Mercedes' 4MATIC and
# Volkswagen's 4MOTION, so it is kept to each make), 'Tech' (printed as the long form by every source), 'Bus'
# (Citroën's 'Bus Lounge' is Business, but a minibus is a body).
SHORT_FORMS: tuple[tuple[str, str, tuple[str, ...] | None, str], ...] = (
    ("ext range", "extended range", None,
     "Carwow: Volvo '185kW Ext Range Plus Black Edition 82kWh' / '185kW Extended Range Plus 82kWh'; Vauxhall Frontera"),
    ("ex range", "extended range", None, "Parkers: Volvo EX30 '200kW SM Ex Range Plus Black Ed 69kWh'"),
    ("nt ed", "night edition", None, "Carwow specification: Mercedes EQE '235kW AMG Line Nt Ed Prem 96kWh'"),
    (r"edr(\d+)", r"edrive\1", None, "Carwow: BMW i5 '250kW eDr40 M Sport Pro' / '250kW eDrive40 Sport Edition'; Parkers"),
    (r"xdr(\d*)", r"xdrive\1", None, "Carwow: BMW i7 '500kW M70 xDr Ultimate Ed', iX '400kW xDr60'; Parkers"),
    ("msport", "m sport", None, "Parkers: BMW iX1 '230kW xDr30 MSport 65kWh'"),
    ("qtro", "quattro", None, "Carwow: Audi A6 '370kW S6 Qtro 100kWh' / '315kW Quattro 100kWh'; Parkers"),
    ("perf", "performance", None, "Carwow: Audi Q4 '210kW Perf 82kWh', Volvo '325kW TM Perf'; Parkers (DS, Polestar, VW)"),
    ("perform", "performance", None, "Parkers: Mercedes-AMG EQS '484kW Night Ed Perform'"),
    ("ed", "edition", None, "Carwow: Audi Q6 '225kW Performance 100kWh Black Ed'; Parkers (every make)"),
    ("edn", "edition", None, "Parkers: Renault Zoe '100kW Riviera Limited Edn', Mercedes-AMG 'Night Edn'"),
    ("editon", "edition", None, "Carwow specification: Volvo EX40 'Plus Black Editon'; Kia's grade tables (kia_specs)"),
    ("comf", "comfort", None, "Carwow: BMW i5 'Tech+/Comf+', Genesis GV60 '[Comf/Innovation]'; Parkers"),
    ("cmf", "comfort", None, "Carwow: BMW i5 Touring 'Tech+/Cmf+/22kW'; Parkers"),
    ("tec", "tech", ("bmw",), "Carwow: BMW i5 '250kW eDrive40 Sport Edition 84kWh 4dr Auto [Tec+]'; Parkers"),
    ("tch", "tech", ("bmw",), "Parkers: BMW i5 '250kW eDrive40 M Sport Pro 84kWh 4dr At [Tch+Cmf+]'"),
    ("prem", "premium", None, "Carwow: Mercedes C-Class 'AMG Line Prem +'; Parkers: Lexus RZ 'Prem+/18\"'"),
    ("innov", "innovation", None, "Parkers: Genesis GV60 '[Comfort/Innov]'; Carwow '[Comf/Innovation]'"),
    ("int", "interior", None, "Carwow: VW ID.7 '[Int+ Pack]'; Parkers: VW '[Interior Pack]'"),
    ("ext", "exterior", None, "Carwow: VW ID.7 '[Ext+ Pan]'; Parkers: VW '[Exterior+ Pan]'"),
    ("exec", "executive", None, "Carwow: Mercedes GLB '200kW AMG Line Exec', BMW i7 '[Exec Lounge]'; Parkers"),
    ("exe", "executive", None, "Parkers: Mercedes CLA '200kW EQ Tech AMG Line Exe 85kWh'"),
    ("pk", "pack", None, "Parkers: Audi '[Tech Pk]', BMW i7 '[Ulti Pk]', Nissan Ariya '[Bose Tech Pk]'"),
    ("ulti", "ultimate", None, "Parkers: BMW i7 '400kW xDrive60 M Sport 105.7kWh 4dr Auto [Ulti Pk]'"),
    ("vorsp", "vorsprung", None, "Parkers: Audi e-tron GT '475kW Quattro 93kWh Carbon Vorsp'"),
    ("std", "standard", None, "Parkers: Peugeot e-Traveller '100kW Active Std [8 Seat]'"),
    (r"dir(\d+)", r"direct\1", None, "Parkers: Lexus RZ '450e 230kW Dir4 71 kWh' / '450e 230kW Direct4 71 kWh'"),
    ("rf", "roof", None, "Parkers: VW ID.3 '[Pan Rf]', Toyota bZ4X '[Pan Rf]' / '[Pan Roof]'"),
    ("lth", "leather", None, "Parkers: Audi Q4 '210kW 45 Qtro 82kWh S Line 5dr Auto [Lth/Tech Pro]'"),
    ("lr", "long range", None, "Carwow: Polestar 2 '350kW 82kWh LR DM Prime', Volvo EX30 '200kW P5 LR'; Parkers"),
    ("sr", "standard range", None, "Parkers: Kia EV6 '125kW Air SR 63kWh'; EV Database: Ford 'Mustang Mach-E SR RWD'"),
    ("dm", "dual motor", None, "Carwow: Polestar 2 '310kW 82kWh Long Range DM Prime'; Parkers: Tesla 'DM Performance'"),
    ("sm", "single motor", None, "Carwow: Polestar 2 '200kW 70kWh Standard Range SM Prime', Volvo ES90 '245kW SM'; Parkers"),
    ("tm", "twin motor", None, "Carwow: Volvo EC40 '325kW TM Perf'; Carwow specification: Volvo EX90 'Twin Motor'"),
    ("adv", "advanced", None, "Carwow: Ford Puma Gen-E '[Adv Driver Assist]'; Parkers: Skoda Enyaq '[Adv]' / '[Advanced]'"),
    ("drv", "driver", None, "Carwow: Ford Puma Gen-E '[Comfort/Adv Drv Asst]'; Parkers '[Adv Driver Assist]'"),
    ("asst", "assist", None, "Carwow: Ford Puma Gen-E '[Comfort/Adv Drv Asst]'; Parkers '[Adv Driver Assist]'"),
    ("4m", "4matic", ("mercedes", "mercedesamg"), "Carwow: Mercedes CLA '350 260kW 4M AMG Line' / 'C 400 4MATIC 360kW'; Parkers"),
    ("4m", "4motion", ("volkswagen",), "Parkers: VW ID.4 '210kW 4M Match Pro' / '220kW 4MOTION GTX'"),
)
_SHORT = [(re.compile(rf"(?<![^ ]){short}(?![^ +])"), long, makes) for short, long, makes, _ in
          sorted(SHORT_FORMS, key=lambda e: -len(e[0].split()))]


def expand(ws: list[str], make: str | None = None) -> list[str]:
    """Folded words with CAP's short forms read as the long ones (SHORT_FORMS); `make` admits the forms one make uses."""
    return list(_expand(" ".join(ws), make_key(make) if make else None))


@lru_cache(maxsize=65536)
def _expand(s: str, mk: str | None) -> tuple[str, ...]:
    for rx, long, makes in _SHORT:
        if makes is None or mk in makes:
            s = rx.sub(long, s)
    return tuple(s.split())


def name_words(s: str | None, make: str | None = None) -> list[str]:
    """A derivative's, trim's, engine's or pack's words, read alike whichever source printed them."""
    return expand(words(s), make)


def name_compact(s: str | None, make: str | None = None) -> str:
    """name_words joined, '+' kept: a name compared whole ('Techno+' is not 'Techno')."""
    return "".join(name_words(s, make))


# ---------------------------------------------------------------- makes and models

# Make names some sources print for a catalogue make (the catalogue's make slug), by compact().
# Gathered from the code: the used readers (cinch, Motorpoint: 'Mercedes-Benz', 'SsangYong', 'KGM', 'ORA',
# 'GWM ORA', 'MG MOTOR UK') and EV Database's 'Mercedes-Benz' (services/facts.py).
MAKE_ALIASES = {"mercedesbenz": "mercedes", "ssangyong": "kgm-motors", "kgm": "kgm-motors", "ora": "gwm", "gwmora": "gwm",
                "mgmotoruk": "mg"}
# (catalogue make slug, a retailer's model name by compact()) → the catalogue model slug: the used readers'
# names the catalogue files differently. Only the same car: cinch's 'e-Niro' is the previous generation, not
# the Niro EV, and stays unmatched.
MODEL_ALIASES = {
    ("audi", "a6"): "a6-sportback-e-tron", ("audi", "a6avant"): "a6-avant-e-tron", ("audi", "q6"): "q6-e-tron",
    ("audi", "q4etronsportback"): "q4-e-tron-sportback", ("audi", "q4"): "q4-e-tron", ("audi", "q8"): "q8-e-tron",
    ("bmw", "i4grancoupe"): "i4",
    ("ds", "ds3crossback"): "3-crossback-e-tense",
    ("gwm", "funkycat"): "ora-03", ("gwm", "ora03"): "ora-03",
    ("honda", "hondae"): "e",
    ("ds", "ds3"): "3-e-tense",
    ("kgm-motors", "korandoemotion"): "korando-e-motion", ("kgm-motors", "torres"): "torres-evx",
    ("lexus", "ux"): "ux-300e",
    ("mg", "mgs5"): "s5-ev",
    ("mini", "hatchback"): "electric", ("mini", "cooper"): "electric",   # under the electric filter, the Cooper Electric
    ("omoda", "5"): "omoda-e5",
    ("polestar", "4coupe"): "4",
    ("skoda", "enyaqiv"): "enyaq", ("skoda", "citigo"): "citigo-e-iv",
    ("smart", "forfour"): "eq-forfour", ("smart", "hashtag1"): "1", ("smart", "hashtag3"): "3", ("smart", "hashtag5"): "smart-5",
    ("volkswagen", "golf"): "e-golf",
    ("volvo", "c40"): "c40-recharge",   # the EC40 is the same car renamed, so 'C40' alone is ambiguous without this
}


def make_key(s: str | None) -> str:
    """A make as compared: compact(), its alias resolved to the catalogue's make."""
    k = compact(s)
    return compact(MAKE_ALIASES[k]) if k in MAKE_ALIASES else k


def same_make(name: str | None, model: dict) -> bool:
    """Whether a printed make names a catalogue model's make (its slug or its name)."""
    k = make_key(name)
    return bool(k) and k in (make_key(model.get("make_name")), make_key(model.get("make")))


# ---------------------------------------------------------------- units

KM_PER_MILE = 1.609344
_KW = re.compile(r"(\d+)\s*kw(?!h)", re.I)
_KWH = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
_PS = re.compile(r"(\d+)\s*PS\b", re.I)
_BHP = re.compile(r"(\d+)\s*bhp", re.I)


def kw(s: str | None) -> int | None:
    """The first power in kW a text prints: '150kW GT-Line S 81.4kWh' → 150."""
    m = _KW.search(s or "")
    return int(m.group(1)) if m else None


def kwh(s: str | None) -> float | None:
    """The first energy in kWh a text prints: '150kW GT-Line S 81.4kWh' → 81.4."""
    m = _KWH.search(s or "")
    return float(m.group(1)) if m else None


def kwhs(s: str | None) -> list[float]:
    """Every energy in kWh a text prints, in order."""
    return [float(x) for x in _KWH.findall(s or "")]


def ps(s: str | None) -> int | None:
    """The first power in PS a text prints: '160kW (218PS) RWD' → 218."""
    m = _PS.search(s or "")
    return int(m.group(1)) if m else None


def bhp(s: str | None) -> int | None:
    """The first power in bhp a text prints: 'AWD Dual Motor 320 BHP' → 320."""
    m = _BHP.search(s or "")
    return int(m.group(1)) if m else None


def km_to_miles(km: float) -> float:
    return km / KM_PER_MILE


# ---------------------------------------------------------------- record identities

def key(*parts: str) -> str:
    """A record key from its names: lower-case, 'kwh' glued to its number, single spaces, parts joined by |."""
    out = []
    for p in parts:
        p = re.sub(r"\s*kwh", "kwh", (p or "").lower())
        out.append(re.sub(r"\s+", " ", p).strip())
    return "|".join(out)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
