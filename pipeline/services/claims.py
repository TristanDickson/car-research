"""One fact store for everything a car is, and one resolver.

Every source says things about a *subject* at some level, and a derivative
inherits what is said about the levels it belongs to:

    own         a hand-curated car record (its own id)
    derivative  a CAP derivative id: a registry name and its brackets, a
                configurator page, the maker's own configuration (matched by trim,
                battery and price), a specification row's numbers, a broker's name
    trim_battery  make, model, trim, battery: what the maker's table says is fitted
                only with one battery ('● 49kWh only')
    trim        make, model, trim: a standard-equipment list, a description, a
                manufacturer's grade table, what a curated car says of its trim
    engine      make, model, engine: battery, range, power
    model       make, model: body numbers; what EV Database says of every variant
    variant     an EV Database variant, matched by battery
    pack        make, model, pack name: what the pack bundles

Two edges join them: a derivative *includes* a pack (a CAP name's '[Tech Pack]',
a curated car's packs) and a subject *offers* a pack at a price (the
configurator, a curated car's packs_required). A claim is (field, value, kind,
source, label), and the kind says what sort of evidence it is:

    curated       the household's own reading of the car
    configured    the maker's own configurator: a package in the price is fitted, a
                  package offered on the trim but not in the price is not, a package
                  the model sells elsewhere and neither lists nor offers here is not
                  available. What can be ordered at that price outranks any document.
    named         the CAP name's brackets: '[No Heat Pump]', '[Heat Pump]', '[7 seat]';
                  one claim per name however many brokers reprint it
    maker         the maker's own grade table (Kia UK, Hyundai UK): ● fitted, - not
                  available; ranked with `named`, so the two must agree
    named_twin    a trim with a '[No X]' version has X on its other derivatives
    included      fitted through a pack the derivative includes
    curated_twin  a curated car's reading of its trim, for the trim's other derivatives
    listed        in a standard-equipment list, or fitted by default on the configurator
    described     the trim's description says it is fitted
    offered       available through a pack the trim or derivative is offered
    option        available as an option on its own
    available     EV Database: the model variant can be had with it (or not)
    absent        not in a complete standard list and not offered: not available
    measured      a number a source printed

The resolver walks a car's subjects, ranks the claims for each field by kind
(equipment) or by level (numbers), takes the strongest bucket, and requires the
bucket to agree; a disagreement is unknown, kept with both sides. Equipment
buckets by kind across levels: CAP's '[No Heat Pump]' on the derivative and
the maker's ● on the trim are the same strength, so they are weighed together
and shown as a disagreement when they differ, rather than one quietly winning. Every resolved
field records the claim it came from. Nothing here names a particular feature:
heat pump, cabin socket and powered tailgate are three of the 29 flags
services/features.py knows, resolved by the same rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.services.facts import model_of, pick_variant
from pipeline.services.features import FLAGS, flags_for, wheel_size, wheel_sizes

EQUIPMENT: tuple[str, ...] = tuple(FLAGS)
TRI = ("standard", "pack", "option", "none")
TRI_RANK = {"standard": 3, "pack": 2, "option": 1, "none": 0}

# The car record's own names for some flags (the brief and the UI read these), and booleans.
CAR_TRI = {"heat_pump": "heat_pump", "internal_v2l": "v2l_internal", "external_v2l": "v2l_external"}
CAR_BOOL = {"heated_seats": "heated_front_seats", "camera_360": "camera_360", "glass_roof": "glass_roof",
            "memory_seats": "memory_seats", "ventilated_seats": "ventilated_seats"}

NUMBERS = ("battery_kwh", "battery_usable_kwh", "wltp_range_mi", "real_range_mi", "real_range_cold_mi", "real_range_mild_mi",
           "motorway_range_cold_mi", "motorway_range_mild_mi", "power_hp", "power_kw", "torque_lbft", "zero_to_62_s", "top_speed_mph",
           "efficiency_mi_kwh", "dc_peak_kw", "dc_avg_kw", "dc_10_80_min", "ac_kw", "charge_port", "architecture_v", "battery_chemistry",
           "v2l_kw", "seats", "isofix_seats", "doors", "boot_l", "boot_max_l", "frunk_l", "turning_circle_m", "wheelbase_m", "length_mm",
           "width_mm", "width_mirrors_mm", "height_mm", "weight_kg", "gvwr_kg", "payload_kg", "roof_load_kg", "tow_kg", "tow_unbraked_kg",
           "wheel_in", "wheel_options", "roof_rails", "body", "segment", "platform", "ncap_stars", "ncap_adult_pct", "ncap_child_pct",
           "ncap_vru_pct", "ncap_assist_pct", "ncap_year", "warranty_years", "warranty_miles", "insurance_group",
           "list_price_gbp", "used_from_gbp", "drive")
ENGINE_FIELDS = ("battery_kwh", "wltp_range_mi", "power_hp", "zero_to_62_s", "top_speed_mph", "efficiency_mi_kwh", "ac_kw", "drive", "dc_peak_kw", "dc_10_80_min")
BODY_FIELDS = ("seats", "doors", "boot_l", "boot_max_l", "turning_circle_m", "wheelbase_m", "length_mm", "width_mm", "height_mm")
NUMBER_ALIASES = {"zero_to_60_s": "zero_to_62_s", "power_bhp": "power_hp", "kerb_weight_kg": "weight_kg"}
# What EV Database says of a variant (the index card and the car page, providers/evdb*.py).
EVDB_NUMBERS = tuple(f for f in NUMBERS if f not in ("battery_kwh", "doors", "wheel_in", "wheel_options", "list_price_gbp", "used_from_gbp"))
EVDB_FLAGS = {"heat_pump": "heat_pump", "v2l_external": "v2l_external", "v2l_internal": "v2l_internal", "v2l_any": "v2l_any",
              "three_pin_socket": "three_pin_socket"}
# Body numbers that are one number for a model: said at model level when every current variant agrees.
EVDB_MODEL_FIELDS = ("length_mm", "width_mm", "width_mirrors_mm", "height_mm", "wheelbase_m", "boot_l", "boot_max_l", "frunk_l",
                     "roof_load_kg", "isofix_seats", "turning_circle_m", "seats", "segment", "platform", "body", "roof_rails",
                     "ncap_stars", "ncap_adult_pct", "ncap_child_pct", "ncap_vru_pct", "ncap_assist_pct", "ncap_year",
                     "warranty_years", "warranty_miles", "charge_port", "architecture_v")
CARWOW_RAW = {"Top speed": ("top_speed_mph", "mph"), "Consumption": ("efficiency_mi_kwh", "miles/kWh"), "Battery capacity": ("battery_kwh", "kWh")}

EQUIP_TIERS = (("curated",), ("configured",), ("named", "maker"), ("named_twin",), ("included",), ("curated_twin",), ("listed",), ("described",),
               ("offered",), ("option",), ("available",), ("absent",))
EQUIP_ORDER = tuple(k for tier in EQUIP_TIERS for k in tier)
EQUIP_RANK = {k: i for i, tier in enumerate(EQUIP_TIERS) for k in tier}
OVERRULED_KINDS = ("configured", "named", "maker", "curated_twin")   # worth showing when a stronger source overrides them
LEVEL_ORDER = ("own", "derivative", "trim_battery", "trim", "engine", "model", "variant")
NUMBER_KINDS = ("curated", "named", "measured", "listed", "inferred")   # inferred: every current variant of the model agrees
PRICES = ("list_price_gbp", "used_from_gbp")   # drift with time: the latest sighting wins, never a disagreement
NUMBER_TOLERANCE = 0.05                         # numbers within 5% of each other are the same number (wheels, rounding)
COMPLETE_LIST = 40   # a standard-equipment list this long is read as the whole of it
MAKER_PROVIDERS = ("kia_specs", "hyundai_specs")
# Who reprinted a CAP name: the registry and the brokers, by the name the Data page uses.
SIGHTING_NAMES = {"carwow": "Carwow", "carwow_deals": "Carwow", "carwow_paste": "Carwow", "leaseloco": "LeaseLoco", "ncd": "New Car Discount",
                  "rrg": "RRG", "hyundai_offers": "Hyundai UK", "manual_seed": "hand-entered"}
KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
SEATS_RE = re.compile(r"^\s*(\d)\s*-?\s*(?:seat|seats|seater|st)\b", re.I)


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def trim_head(trim: str | None) -> str:
    """The trim's own words: '02 · 85kW 49kWh Auto' → '02'; 'GT-Line S Heat Pump' → 'GT-Line S';
    'Ultimate 65kWh' → 'Ultimate'; 'Elite 7-seat' → 'Elite'."""
    t = re.sub(r"\[[^\]]*\]", " ", (trim or "").split("·")[0])
    t = re.sub(r"\bheat pump\b", " ", t, flags=re.I)
    words = [w for w in re.split(r"\s+", t.strip())
             if w and not re.search(r"\d+\s*kwh|\d+kw\b|^\d+dr$|^auto$|^\d-?seat", w, re.I)]
    return " ".join(words)


def model_key(make: str | None, model: str | None) -> str:
    return f"{norm(make)}|{norm(model)}"


def trim_subject(make, model, trim) -> str:
    return f"trim:{model_key(make, model)}|{norm(trim_head(trim))}"


def trim_battery_subject(make, model, trim, kwh) -> str:
    return f"trimbattery:{model_key(make, model)}|{norm(trim_head(trim))}|{float(kwh):g}"


def engine_subject(make, model, engine) -> str:
    return f"engine:{model_key(make, model)}|{norm(engine)}"


def model_subject(make, model) -> str:
    return f"model:{model_key(make, model)}"


def pack_subject(make, model, pack) -> str:
    return f"pack:{model_key(make, model)}|{norm(pack)}"


@dataclass(frozen=True)
class Claim:
    field: str
    value: object
    kind: str
    source: str
    label: str
    price: float | None = None
    pack: str | None = None
    # ISO date the source printed it: prices drift, so the latest wins among equals.
    seen: str | None = None


class Store:
    def __init__(self) -> None:
        self.claims: dict[str, list[Claim]] = {}
        self.includes: dict[str, dict[str, str]] = {}       # subject → {pack subject: pack name}
        self.offers: dict[str, dict[str, tuple[str, float | None]]] = {}   # subject → {pack subject: (name, price)}
        self.variants: dict[str, list[dict]] = {}           # model key → EV Database rows
        self.names: dict[str, str] = {}                     # derivative subject → CAP name
        self.trim_batteries: dict[str, set[float]] = {}     # trim subject → the kWh the maker sells it with
        self.named: dict[tuple[str, str, object], dict] = {}   # (subject, field, value) → the CAP name and who printed it
        self.configured: dict[str, str] = {}                # cap_id → the maker's configuration code it matched

    def add(self, subject: str, claim: Claim) -> None:
        self.claims.setdefault(subject, []).append(claim)

    def include(self, subject: str, pack: str, name: str) -> None:
        self.includes.setdefault(subject, {})[pack] = name

    def offer(self, subject: str, pack: str, name: str, price: float | None) -> None:
        self.offers.setdefault(subject, {})[pack] = (name, price)

    def name_claim(self, subject: str, field: str, value: object, name: str, sighting: str) -> None:
        """A CAP name's bracket, seen on one more site. Brokers reprint CAP's name; that is one claim
        with several sightings, not several claims."""
        e = self.named.setdefault((subject, field, value), {"name": name, "seen": set()})
        e["seen"].add(sighting)

    def flush_named(self) -> None:
        for (subject, field, value), e in self.named.items():
            self.add(subject, Claim(field, value, "named", "CAP derivative name", f"CAP derivative name · {e['name']} (seen on {', '.join(sorted(e['seen']))})"))
        self.named.clear()

    def count(self) -> int:
        return sum(len(v) for v in self.claims.values())


# ---------------------------------------------------------------- extraction

def _bracket_claims(store: Store, subject: str, make: str, model: str, brackets: list[str], sighting: str, name: str) -> None:
    """What a CAP name's brackets say: a seat count, 'No X', X, or a pack."""
    for b in brackets:
        b = b.strip()
        m = SEATS_RE.match(b)
        if m:
            store.name_claim(subject, "seats", int(m.group(1)), name, sighting)
            continue
        negative = b.lower().startswith("no ")
        hit = [k for k, v in flags_for([b[3:] if negative else b]).items() if v == "standard"]
        if hit:
            for k in hit:
                store.name_claim(subject, k, "none" if negative else "standard", name, sighting)
        elif not negative:
            store.include(subject, pack_subject(make, model, b), b)


PACK_PRICE_RE = re.compile(r"^(.*?)\s*\(\s*£\s*([\d,]+)\s*\)\s*$")


def split_pack(name: str | None, prices: dict | None = None) -> tuple[str | None, float | None]:
    """'Tech Pack (£500)' → ('Tech Pack', 500.0); a bare name takes its price from `prices`."""
    if not name:
        return None, None
    m = PACK_PRICE_RE.match(name)
    if m:
        return m.group(1).strip(), float(m.group(2).replace(",", ""))
    return name.strip(), (prices or {}).get(name.strip())


def from_curated(store: Store, car: dict) -> None:
    """A hand-curated car: its own reading of itself, and of its trim for the trim's other derivatives."""
    own = f"own:{car['id']}"
    label = f"hand-curated · {car['id']}"
    packs_required = car.get("packs_required") or {}
    prices = car.get("pack_prices_gbp") or {}
    for f, flag in CAR_TRI.items():
        v = car.get(f)
        if v in TRI:
            pack, price = split_pack(packs_required.get(f), prices)
            store.add(own, Claim(flag, v, "curated", "hand-curated", label, price, pack))
            store.add(trim_subject(car.get("make"), car.get("model"), car.get("trim")), Claim(flag, v, "curated_twin", "hand-curated", label, price, pack))
            if v == "pack" and pack:
                ps = pack_subject(car.get("make"), car.get("model"), pack)
                store.add(ps, Claim(flag, "standard", "pack_contents", "hand-curated", f"{label} · {pack}"))
                store.offer(trim_subject(car.get("make"), car.get("model"), car.get("trim")), ps, pack, price)
    for f, flag in CAR_BOOL.items():
        v = car.get(f)
        if isinstance(v, bool):
            store.add(own, Claim(flag, "standard" if v else "none", "curated", "hand-curated", label))
    for f in NUMBERS:
        if car.get(f) not in (None, ""):
            store.add(own, Claim(f, car[f], "curated", "hand-curated", label))
    for p in car.get("packs") or []:
        name, _ = split_pack(p)
        if name:
            store.include(own, pack_subject(car.get("make"), car.get("model"), name), name)


def _described(description: str | None) -> dict[str, bool]:
    """Flags a trim description says are fitted: a sentence that matches the flag
    and does not hedge it (option, no, without, not fitted)."""
    out: dict[str, bool] = {}
    for sent in re.split(r"(?<=[.!?])\s+", description or ""):
        low = sent.lower()
        if re.search(r"\boption|\bno \w+ pump|without|not (fitted|available|included|standard)|lacks|can be specified|available with", low):
            continue
        for k, v in flags_for([sent]).items():
            if v == "standard":
                out[k] = True
    return out


def from_carwow_spec(store: Store, row: dict) -> None:
    """A Carwow specification row: the derivative's numbers, the trim's standard list and description."""
    make, model, trim, engine = row.get("make"), row.get("model"), row.get("trim"), row.get("engine")
    cap = row.get("cap_id")
    src = "Carwow specification"
    nums = {NUMBER_ALIASES.get(k, k): v for k, v in (row.get("numbers") or {}).items()}
    for raw_label, (f, unit) in CARWOW_RAW.items():   # rows parsed before the parser read these keep them as text
        raw = (row.get("raw_numbers") or {}).get(raw_label)
        if nums.get(f) in (None, "") and raw:
            m = re.search(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), raw.replace(",", ""), re.I)
            if m:
                nums[f] = float(m.group(1))
    label = f"{src} · {row.get('variant') or trim}"
    seen = (row.get("last_seen_at") or row.get("observed_at") or "")[:10] or None
    w = wheel_size(row.get("features") or [])
    if w and cap:
        store.add(f"derivative:{cap}", Claim("wheel_in", w, "listed", src, f"{src} · {trim} standard equipment"))
    for f in NUMBERS:
        if nums.get(f) not in (None, ""):
            if cap:
                store.add(f"derivative:{cap}", Claim(f, nums[f], "measured", src, label, seen=seen))
            if f in ENGINE_FIELDS:
                store.add(engine_subject(make, model, engine), Claim(f, nums[f], "measured", src, f"{src} · {trim} {engine} (same engine)", seen=seen))
            if f in BODY_FIELDS:
                store.add(model_subject(make, model), Claim(f, nums[f], "measured", src, f"{src} · {make} {model} (same model)", seen=seen))
    if cap and row.get("rrp"):
        store.add(f"derivative:{cap}", Claim("list_price_gbp", float(row["rrp"]), "listed", src, label, seen=seen))
    tsub = trim_subject(make, model, trim)
    items = row.get("features") or []
    fl = flags_for(items, row.get("options") or [])
    for k, v in fl.items():
        if v == "standard":
            store.add(tsub, Claim(k, "standard", "listed", src, f"{src} · {trim} standard equipment"))
        elif v == "option":
            store.add(tsub, Claim(k, "option", "option", src, f"{src} · {trim} options"))
        elif len(items) >= COMPLETE_LIST:
            store.add(tsub, Claim(k, "none", "absent", src, f"not in {src.split(' ')[0]}'s standard equipment for {trim}"))
    for k in _described(row.get("description")):
        store.add(tsub, Claim(k, "standard", "described", src, f"Carwow trim description · {trim}"))


def _maker_verdicts(row: dict) -> dict[str, str]:
    """Every flag a maker's row speaks to: standard (●), option (○, an extra), none (a printed -),
    or unlisted (a complete list that prints no blanks of its own does not name it: not fitted,
    but weakly, since a wording the flag's pattern misses would otherwise read as a firm no).
    A qualified item ('49kWh only') is none of these: the row says nothing of it at trim level."""
    out = {k: v for k, v in flags_for(row.get("features") or [], row.get("options") or []).items() if v}
    if row.get("absent") is not None:
        for k, v in flags_for(row["absent"]).items():
            if v == "standard" and k not in out:
                out[k] = "none"
    elif len(row.get("features") or []) >= COMPLETE_LIST:
        for k in EQUIPMENT:
            out.setdefault(k, "unlisted")
    return out


def from_maker_specs(store: Store, rows: list[dict]) -> None:
    """The maker's own grade tables (Kia UK, Hyundai UK): one row per grade × powertrain (× seats).

    A grade's rows speak for the trim where they all agree; where they differ (Kia's with-heat-pump
    column, two powertrains with different kit) the plainest column speaks weakly, below a CAP name,
    and the fact is left to the battery level or the bracket. A row with one battery also speaks at trim-and-battery level,
    and a qualified tick ('● 49kWh only', 'only standard on the 84kWh battery') speaks there alone.
    A pack in the maker's extras list is offered on the trims it names, with its price."""
    groups: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
    for row in rows:
        make, model, trim = row.get("make"), row.get("model"), row.get("trim") or ""
        src = row.get("source") or "maker specification"
        verdicts = _maker_verdicts(row)
        tsub = trim_subject(make, model, trim)
        head = trim_head(trim) or trim
        groups.setdefault((tsub, f"{src} · {head}"), []).append((row, verdicts))
        w = wheel_size(row.get("features") or [])
        if w:
            store.add(tsub, Claim("wheel_in", w, "listed", src, f"{src} · {head} standard equipment"))
        kwh = (row.get("numbers") or {}).get("battery_kwh")
        kwhs = [float(kwh)] if kwh else [float(b) for b in row.get("batteries") or []]
        store.trim_batteries.setdefault(tsub, set()).update(kwhs)
        if len(kwhs) == 1:
            groups.setdefault((trim_battery_subject(make, model, trim, kwhs[0]), f"{src} · {head} {kwhs[0]:g} kWh"), []).append((row, verdicts))
        for q in row.get("qualified") or []:
            hit = [k for k, v in flags_for([q["item"]]).items() if v == "standard"]
            for value, key in (("standard", "standard_kwh"), ("none", "none_kwh")):
                for b in q.get(key) or []:
                    for k in hit:
                        store.add(trim_battery_subject(make, model, trim, b), Claim(k, value, "maker", src, f"{src} · {head} {float(b):g} kWh · {q['item']}: {q['note']}"))
        for p in row.get("packs") or []:
            ps = pack_subject(make, model, p["name"])
            for k, v in flags_for(p.get("items") or []).items():
                if v == "standard":
                    store.add(ps, Claim(k, "standard", "pack_contents", src, f"{src} · {p['name']}"))
            store.offer(tsub, ps, p["name"], p.get("price"))
    for (sub, label), members in groups.items():
        src = members[0][0].get("source") or "maker specification"
        for k in EQUIPMENT:
            said = [v.get(k) for _, v in members if v.get(k)]
            vals = {"none" if v == "unlisted" else v for v in said}
            if not vals:
                continue
            if len(vals) == 1:
                v = next(iter(vals))
                if v == "option":
                    store.add(sub, Claim(k, "option", "option", src, f"{label} options"))
                elif v == "none" and "unlisted" in said:
                    store.add(sub, Claim(k, "none", "absent", src, f"not in {label}"))
                else:
                    store.add(sub, Claim(k, v, "maker", src, label))
                continue
            # The grade's columns differ (a with-heat-pump column, a better-equipped powertrain): the
            # plainest column speaks for the trim, weakly, and the CAP name or configurator says the rest.
            v = min(vals, key=lambda t: TRI_RANK[t])
            store.add(sub, Claim(k, v, "option" if v == "option" else "absent", src, f"{label} (its columns differ; the plainest says {v})"))


def _current(variants: list[dict]) -> list[dict]:
    """The variants on sale now (EV Database's car page says), else those from the model's latest year or the one before."""
    on = [v for v in variants if (v.get("numbers") or {}).get("on_sale") is True]
    if on:
        return on
    years = [(v.get("numbers") or {}).get("year_from") or 0 for v in variants]
    top = max(years, default=0)
    return [v for v, y in zip(variants, years) if y >= top - 1]


def _all_agree(values: list) -> bool:
    if not values:
        return False
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        lo, hi = min(values), max(values)
        return hi - lo <= 0.5 or (lo and (hi - lo) / abs(lo) <= 0.02)
    return len({str(v).lower() for v in values}) == 1


def from_evdb(store: Store, rows: list[dict], catalogue: list[dict], pages: list[dict] | None = None) -> None:
    """EV Database variants: what the index card and the variant's own page (when read) measure, and what the
    model can be had with. Where every current variant of a model gives the same body number, the model does."""
    by_id = {str(p.get("evdb_id") or p["spec_key"].split(":", 1)[1]): p for p in pages or []}
    for r in rows:
        m = model_of(r.get("make") or "", r.get("model") or "", catalogue)
        if not m:
            continue
        page = by_id.get(r["spec_key"].split(":", 1)[1])
        if page:   # the car page fills in and corrects the card
            r["numbers"] = {**(r.get("numbers") or {}), **(page.get("numbers") or {})}
            r["flags"] = {**(r.get("flags") or {}), **(page.get("flags") or {})}
        mk = model_key(m.get("make_name") or m["make"], m.get("model_name") or m["model"])
        store.variants.setdefault(mk, []).append(r)
        vs = f"variant:{r['spec_key']}"
        label = f"EV Database · {r.get('model')}"
        nums = r.get("numbers") or {}
        for f in EVDB_NUMBERS:
            if nums.get(f) not in (None, ""):
                store.add(vs, Claim(f, nums[f], "measured", "EV Database", label))
        for ev, flag in EVDB_FLAGS.items():
            v = (r.get("flags") or {}).get(ev)
            if v in TRI:
                store.add(vs, Claim(flag, v, "available", "EV Database", label))
    for mk, vs in store.variants.items():
        name = f"{vs[0].get('make')} {mk.split('|')[1]}"
        # Where every variant of a model says the same, the model says it.
        for ev, flag in EVDB_FLAGS.items():
            vals = {(v.get("flags") or {}).get(ev) for v in vs}
            if len(vals) == 1 and next(iter(vals)) in TRI:
                store.add(f"model:{mk}", Claim(flag, next(iter(vals)), "available", "EV Database", f"EV Database · every {name} variant"))
        current = _current(vs)
        for f in EVDB_MODEL_FIELDS:
            vals = [(v.get("numbers") or {}).get(f) for v in current]
            vals = [x for x in vals if x not in (None, "")]
            if _all_agree(vals):
                store.add(f"model:{mk}", Claim(f, vals[0], "inferred", "EV Database", f"EV Database · every current {name} variant"))


def from_registry(store: Store, derivatives: list[dict]) -> None:
    """The derivative registry: every CAP name with its brackets and RRP; a trim's no-X twin."""
    by_trim: dict[str, list[dict]] = {}
    for d in derivatives:
        sub = f"derivative:{d['cap_id']}"
        store.names[sub] = d.get("name") or ""
        _bracket_claims(store, sub, d.get("make") or d.get("make_slug"), d.get("model") or d.get("model_slug"), d.get("brackets") or [], "Carwow", d.get("name") or "")
        if d.get("rrp"):
            store.add(sub, Claim("list_price_gbp", float(d["rrp"]), "listed", "Carwow model page", f"Carwow model page · {d.get('name')}", seen=(d.get("observed_at") or "")[:10] or None))
        by_trim.setdefault(trim_subject(d.get("make") or d.get("make_slug"), d.get("model") or d.get("model_slug"), d.get("trim")), []).append(d)
    for tsub, ds in by_trim.items():
        negated: dict[str, str] = {}
        for d in ds:
            for b in d.get("brackets") or []:
                if b.lower().startswith("no "):
                    for k, v in flags_for([b[3:]]).items():
                        if v == "standard":
                            negated[k] = d.get("trim") or ""
        for k, trim in negated.items():
            store.add(tsub, Claim(k, "standard", "named_twin", "Carwow derivative names", f"Carwow derivative names · {trim} has a [No …] version; this is not it"))


def from_options(store: Store, row: dict, make: str, model: str) -> None:
    """A derivative's configurator page: options, packs and their contents, and what is in neither."""
    sub = f"derivative:{row['cap_id']}"
    src = "Carwow configurator"
    covered: set[str] = set()
    fitted = {w for o in row.get("options") or [] if o.get("default") for w in wheel_sizes([o["name"]])}
    offered = {w for o in row.get("options") or [] if not o.get("default") for w in wheel_sizes([o["name"]])} - fitted
    if len(fitted) == 1:
        store.add(sub, Claim("wheel_in", next(iter(fitted)), "measured", src, f"{src} · the wheels fitted by default"))
    if fitted and offered:
        store.add(sub, Claim("wheel_options", ", ".join(f'{w}"' for w in sorted(offered)), "measured", src, f"{src} · wheels offered as options"))
    for o in row.get("options") or []:
        hit = [k for k, v in flags_for([o["name"]]).items() if v == "standard"]
        covered.update(hit)
        for k in hit:
            if o.get("default"):
                store.add(sub, Claim(k, "standard", "listed", src, f"{src} · {o['name']} (fitted by default)"))
            else:
                store.add(sub, Claim(k, "option", "option", src, f"{src} · {o['name']}", o.get("price")))
    for p in row.get("packs") or []:
        ps = pack_subject(make, model, p["name"])
        hit = [k for k, v in flags_for(p.get("items") or []).items() if v == "standard"]
        covered.update(hit)
        for k in hit:
            store.add(ps, Claim(k, "standard", "pack_contents", src, f"{src} · {p['name']}"))
        if p.get("default"):
            store.include(sub, ps, p["name"])
        else:
            store.offer(sub, ps, p["name"], p.get("price"))
    for k in EQUIPMENT:
        if k not in covered:
            store.add(sub, Claim(k, "none", "absent", src, f"not offered as an option or pack ({src})"))


def _pack_flags(p: dict) -> set[str]:
    return {k for k, v in flags_for(p.get("items") or [p.get("name") or ""]).items() if v == "standard"}


def _engine_kwh(d: dict) -> float | None:
    m = KWH_RE.search(d.get("engine") or "")
    return float(m.group(1)) if m else None


def _brackets_fit(d: dict, r: dict) -> bool:
    """A CAP name's brackets against a configuration's packages: '[No Heat Pump]' needs no package with
    one, '[Tech Pack]' needs that package in the price; a name without brackets fits any."""
    pflags: set[str] = set()
    for p in r.get("packages") or []:
        pflags |= _pack_flags(p)
    names = {norm(p.get("name")) for p in r.get("packages") or []}
    for b in d.get("brackets") or []:
        b = b.strip()
        if SEATS_RE.match(b):
            continue
        negative = b.lower().startswith("no ")
        hit = {k for k, v in flags_for([b[3:] if negative else b]).items() if v == "standard"}
        if negative and hit & pflags:
            return False
        if not negative and norm(b) not in names and not (hit and hit <= pflags):
            return False
    return True


def from_configurations(store: Store, rows: list[dict], derivatives: list[dict]) -> None:
    """The maker's configurator: every orderable configuration with its price and packages.

    A configuration is a CAP derivative when the trim, battery and price agree; what is left pairs
    off where the brackets agree with the packages and the pairing is unique. On a matched
    derivative the price is its list price, a package in the price is fitted, a package offered
    on the trim and powertrain but not in the price is an extra (not fitted, offered at its
    price), and a package the model sells on some other trim or powertrain is not available
    here. Each trim's standard-equipment list speaks for the trim."""
    by_trim: dict[str, list[dict]] = {}
    for d in derivatives:
        by_trim.setdefault(trim_subject(d.get("make") or d.get("make_slug"), d.get("model") or d.get("model_slug"), d.get("trim")), []).append(d)

    def tsub_of(r: dict) -> str:
        return trim_subject(r["make"], r["model"], r["trim"])

    def fits(d: dict, r: dict) -> bool:
        k = _engine_kwh(d)
        if r.get("battery_kwh") is not None and k is not None and abs(k - float(r["battery_kwh"])) > 1.5:
            return False
        ds = next((int(m.group(1)) for b in d.get("brackets") or [] for m in [SEATS_RE.match(b.strip())] if m), None)
        if ds is None:
            m = re.search(r"\b(\d)\s*(?:st|seats?)\b", d.get("name") or "", re.I)
            ds = int(m.group(1)) if m else None
        return r.get("seats") is None or ds is None or ds == int(r["seats"])

    taken: set[str] = set()
    match: dict[str, str] = {}
    for r in rows:   # 1. the price decides
        cands = [d for d in by_trim.get(tsub_of(r), []) if fits(d, r) and d.get("rrp") and r.get("price")
                 and abs(float(d["rrp"]) - float(r["price"])) <= 1 and d["cap_id"] not in taken]
        if len(cands) == 1:
            match[r["fsc"]] = cands[0]["cap_id"]
            taken.add(cands[0]["cap_id"])
    for r in rows:   # 2. what is left pairs off uniquely where the brackets agree with the packages
        if r["fsc"] in match:
            continue
        cands = [d for d in by_trim.get(tsub_of(r), []) if fits(d, r) and d["cap_id"] not in taken and _brackets_fit(d, r)]
        if len(cands) != 1:
            continue
        d = cands[0]
        rivals = [x for x in rows if x is not r and x["fsc"] not in match and tsub_of(x) == tsub_of(r) and fits(d, x) and _brackets_fit(d, x)]
        if not rivals:
            match[r["fsc"]] = d["cap_id"]
            taken.add(d["cap_id"])

    model_packs: dict[str, dict[str, set[str]]] = {}   # model → flag → the packages that carry it anywhere on the model
    for r in rows:
        mp = model_packs.setdefault(model_key(r["make"], r["model"]), {})
        for p in (r.get("packages") or []) + (r.get("offered") or []):
            for k in _pack_flags(p):
                mp.setdefault(k, set()).add(p["name"])

    for r in rows:
        src = r.get("source") or "maker configurator"
        label = f"{src} · {r['trim']} {r.get('powertrain') or ''} £{float(r['price']):,.0f}".replace("  ", " ") if r.get("price") else f"{src} · {r['trim']} {r.get('powertrain') or ''}"
        for p in (r.get("packages") or []) + (r.get("offered") or []):
            ps = pack_subject(r["make"], r["model"], p["name"])
            for k in _pack_flags(p):
                store.add(ps, Claim(k, "standard", "pack_contents", src, f"{src} · {p['name']}"))
        cap = match.get(r["fsc"])
        if not cap:
            continue
        sub = f"derivative:{cap}"
        store.configured[cap] = r["fsc"]
        if r.get("price"):
            store.add(sub, Claim("list_price_gbp", float(r["price"]), "listed", src, label, seen=(r.get("observed_at") or "")[:10] or None))
        equip = {k for k, v in flags_for(r.get("equipment") or []).items() if v == "standard"}
        included: dict[str, str] = {}
        for p in r.get("packages") or []:
            store.include(sub, pack_subject(r["make"], r["model"], p["name"]), p["name"])
            for k in _pack_flags(p):
                included.setdefault(k, p["name"])
        for k, name in included.items():
            store.add(sub, Claim(k, "standard", "configured", src, f"{label} · {name} in the price", None, name))
        offered: dict[str, dict] = {}
        for p in r.get("offered") or []:
            if any(p["name"] == q["name"] for q in r.get("packages") or []):
                continue
            store.offer(sub, pack_subject(r["make"], r["model"], p["name"]), p["name"], p.get("price"))
            for k in _pack_flags(p):
                offered.setdefault(k, p)
        for k, p in offered.items():
            if k not in included and k not in equip:
                price = f" (£{float(p['price']):,.0f})" if p.get("price") else ""
                store.add(sub, Claim(k, "none", "configured", src, f"{label} · {p['name']}{price} is an extra, not in this price"))
        for k, names in model_packs.get(model_key(r["make"], r["model"]), {}).items():
            if k not in included and k not in offered and k not in equip:
                store.add(sub, Claim(k, "none", "configured", src, f"{label} · the {r['model']} has this only in {' / '.join(sorted(names))}, not offered on this trim and powertrain"))
    done: set[str] = set()
    for r in rows:   # the trim's standard-equipment list, once per trim: a list like Carwow's, not a per-configuration fact
        tsub = tsub_of(r)
        if tsub in done or not r.get("equipment"):
            continue
        done.add(tsub)
        for k, v in flags_for(r["equipment"]).items():
            if v == "standard":
                store.add(tsub, Claim(k, "standard", "listed", r.get("source") or "maker configurator", f"{r.get('source') or 'maker configurator'} · {r['trim']} standard equipment"))
        w = wheel_size(r["equipment"])
        if w:
            store.add(tsub, Claim("wheel_in", w, "listed", r.get("source") or "maker configurator", f"{r.get('source') or 'maker configurator'} · {r['trim']} standard equipment"))


def from_broker_labels(store: Store, rows: list[dict]) -> None:
    """Broker rows resolved to a derivative, whose names carry CAP's brackets."""
    for r in rows:
        if not (r.get("car_id") or "").startswith("carwow-cap:"):
            continue
        br = [b.strip() for b in re.findall(r"\[([^\]]+)\]", r.get("label") or "") if b.strip()]
        if br:
            _bracket_claims(store, f"derivative:{r['car_id'].split(':', 1)[1]}", r.get("make") or "", r.get("model") or "", br, SIGHTING_NAMES.get(r.get("source") or "", r.get("source") or "?"), r.get("label") or "")


def build_store(cars: list[dict], specs: list[dict], catalogue: list[dict], derivatives: list[dict], options: list[dict],
                broker_rows: list[dict], configurations: list[dict] | None = None) -> Store:
    store = Store()
    for c in cars:
        if not c.get("auto"):
            from_curated(store, c)
    for sp in specs:
        if sp.get("provider") == "carwow_specs":
            from_carwow_spec(store, sp)
    from_maker_specs(store, [sp for sp in specs if sp.get("provider") in MAKER_PROVIDERS])
    from_evdb(store, [sp for sp in specs if sp.get("provider") == "evdb"], catalogue, [sp for sp in specs if sp.get("provider") == "evdb_cars"])
    from_registry(store, derivatives)
    names = {d["cap_id"]: (d.get("make") or d.get("make_slug"), d.get("model") or d.get("model_slug")) for d in derivatives}
    by_cap = {str(c.get("cap_id")): c for c in cars if c.get("cap_id")}
    for o in options:
        mk, mo = names.get(o["cap_id"]) or ((by_cap.get(o["cap_id"]) or {}).get("make"), (by_cap.get(o["cap_id"]) or {}).get("model"))
        if mk and mo:
            from_options(store, o, mk, mo)
    for r in broker_rows:
        c = by_cap.get((r.get("car_id") or "").split(":", 1)[-1]) or {}
        from_broker_labels(store, [{**r, "make": c.get("make"), "model": c.get("model")}])
    store.flush_named()
    from_configurations(store, configurations or [], derivatives)
    return store


# ---------------------------------------------------------------- resolution

@dataclass
class Resolved:
    value: object
    claim: Claim | None
    disagreement: list[Claim] | None = None
    overruled: list[Claim] | None = None   # a weaker source that said otherwise, kept so the override is visible


def _subjects(car: dict, variant: dict | None, store: Store | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not car.get("auto"):
        out.append(("own", f"own:{car['id']}"))
    if car.get("cap_id"):
        out.append(("derivative", f"derivative:{car['cap_id']}"))
    make, model = car.get("make"), car.get("model")
    tsub = trim_subject(make, model, car.get("trim"))
    kwh = car.get("battery_kwh")
    known = (store.trim_batteries.get(tsub) if store else None) or set()
    if kwh and known:
        near = min(known, key=lambda b: abs(b - float(kwh)))
        if abs(near - float(kwh)) <= max(3.0, 0.1 * near):   # the maker's nominal kWh against a source's usable or rounded one
            out.append(("trim_battery", trim_battery_subject(make, model, car.get("trim"), near)))
    out.append(("trim", tsub))
    if car.get("variant"):
        out.append(("engine", engine_subject(make, model, car.get("variant"))))
    out.append(("model", model_subject(make, model)))
    if variant:
        out.append(("variant", f"variant:{variant['spec_key']}"))
    return out


def _agree(cands: list[tuple[tuple, Claim]], bucket_of=lambda rank: rank) -> Resolved:
    """The strongest bucket of a sorted candidate list must agree, else it is unknown with both sides."""
    best = bucket_of(cands[0][0])
    bucket = [c for r, c in cands if bucket_of(r) == best]
    vals = {c.value for c in bucket}
    if len(vals) == 1:
        return Resolved(bucket[0].value, bucket[0])
    if bucket[0].field in PRICES:
        latest = max(bucket, key=lambda c: c.seen or "")
        return Resolved(latest.value, latest)
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        lo, hi = min(vals), max(vals)   # type: ignore[type-var]
        if hi - lo <= 0.5 or (lo and (hi - lo) / abs(lo) <= NUMBER_TOLERANCE):
            return Resolved(bucket[0].value, bucket[0])
    return Resolved(None, None, bucket)


def resolve_equipment(field: str, subjects: list[tuple[str, str]], store: Store) -> Resolved:
    """Is it fitted? The strongest kind of claim across the car's levels must agree (standard, none,
    or what a curated car or EV Database says). A verdict of none means not fitted as standard:
    where a pack or an option offers it, the answer is that pack or option, whoever said none."""
    cands: list[tuple[tuple, Claim]] = []
    for level, key in subjects:
        lr = LEVEL_ORDER.index(level)
        for c in store.claims.get(key, []):
            if c.field == field and c.kind in EQUIP_RANK:
                cands.append(((EQUIP_RANK[c.kind], lr), c))
        for ps, name in store.includes.get(key, {}).items():
            for c in store.claims.get(ps, []):
                if c.field == field and c.kind == "pack_contents":
                    cands.append(((EQUIP_RANK["included"], lr), Claim(field, "standard", "included", c.source, f"{c.source} · {name} (included)", None, name)))
        for ps, (name, price) in store.offers.get(key, {}).items():
            for c in store.claims.get(ps, []):
                if c.field == field and c.kind == "pack_contents":
                    cands.append(((EQUIP_RANK["offered"], lr), Claim(field, "pack", "offered", c.source, f"{c.source} · {name}{f' £{price:,.0f}' if price else ''}", price, name)))
    if not cands:
        return Resolved(None, None)
    cands.sort(key=lambda rc: rc[0])
    fitted = [rc for rc in cands if rc[1].kind not in ("offered", "option")]
    offers = [rc for rc in cands if rc[1].kind in ("offered", "option")]
    if fitted:
        r = _agree(fitted, bucket_of=lambda rank: rank[0])   # the same kind at any level is one bucket
        if r.claim is not None:
            best = EQUIP_RANK[r.claim.kind]
            r.overruled = [c for rank, c in fitted if rank[0] != best and c.kind in OVERRULED_KINDS and str(c.value) != str(r.value)] or None
        if r.claim is None or r.value != "none" or not offers:
            return r
        return Resolved(offers[0][1].value, offers[0][1], overruled=r.overruled)
    return Resolved(offers[0][1].value, offers[0][1])


def resolve_number(field: str, subjects: list[tuple[str, str]], store: Store) -> Resolved:
    cands: list[tuple[tuple, Claim]] = []
    for level, key in subjects:
        for c in store.claims.get(key, []):
            if c.field == field and c.kind in NUMBER_KINDS:
                cands.append(((LEVEL_ORDER.index(level), NUMBER_KINDS.index(c.kind)), c))
    if not cands:
        return Resolved(None, None)
    cands.sort(key=lambda rc: rc[0])
    return _agree(cands)


def _sides(claims: list[Claim]) -> list[str]:
    """One side per value, naming everyone who said it: 'none (Carwow …; ncd …)', 'standard (Hyundai UK …)'."""
    by: dict[str, list[str]] = {}
    for c in claims:
        by.setdefault(str(c.value), []).append(c.label)
    return [f"{v} ({'; '.join(labels)})" for v, labels in by.items()]


def resolve_car(car: dict, store: Store) -> dict:
    """Write every resolved field onto the car: the canonical fields, `flags`
    (every equipment flag with a verdict), `packs_required`, `pack_prices_gbp`,
    `field_sources` (the winning claim per field), `disagreements` and `overruled` (a named,
    maker or configured claim a stronger one set aside, so the override is visible)."""
    sources: dict[str, str] = {}
    disagreements: dict[str, list[str]] = {}
    overruled: dict[str, list[str]] = {}
    subjects = _subjects(car, None, store)
    # Numbers first: the battery picks the EV Database variant and the maker's battery column.
    for f in NUMBERS:
        r = resolve_number(f, subjects, store)
        if r.claim:
            car[f] = r.value
            if not (r.claim.kind == "curated" and not car.get("auto")):
                sources[f] = r.claim.label
        elif r.disagreement:
            disagreements[f] = _sides(r.disagreement)
    variants = store.variants.get(model_key(car.get("make"), car.get("model")), [])
    v = pick_variant(car, variants) if variants else None
    if v:
        car["evdb_url"] = v.get("source_url")
    subjects = _subjects(car, v, store)
    if v:
        for f in NUMBERS:
            if car.get(f) in (None, ""):
                r = resolve_number(f, subjects, store)
                if r.claim:
                    car[f] = r.value
                    sources[f] = r.claim.label
    flags: dict[str, str] = {}
    packs_required: dict[str, str] = {}
    prices: dict[str, float] = dict(car.get("pack_prices_gbp") or {})
    for flag in EQUIPMENT:
        r = resolve_equipment(flag, subjects, store)
        if r.claim:
            flags[flag] = str(r.value)
            if not (r.claim.kind == "curated" and not car.get("auto")):
                sources[flag] = r.claim.label
            if r.value == "pack" and r.claim.pack:
                packs_required[flag] = r.claim.pack
                if r.claim.price:
                    prices[r.claim.pack] = r.claim.price
            if r.overruled:
                overruled[flag] = _sides(r.overruled)
        elif r.disagreement:
            disagreements[flag] = _sides(r.disagreement)
    if "v2l_internal" in flags or "v2l_external" in flags:
        flags["v2l_any"] = max((flags.get("v2l_internal", "none"), flags.get("v2l_external", "none")), key=lambda t: TRI_RANK.get(t, -1))
    for f, flag in CAR_TRI.items():
        car[f] = flags.get(flag, "unknown")
        if flag in sources:
            sources[f] = sources[flag]
        if flag in packs_required:
            packs_required[f] = packs_required.pop(flag)
    for f, flag in CAR_BOOL.items():
        if flag in flags:
            car[f] = flags[flag] != "none"
    included: set[str] = set(car.get("packs") or [])
    for level, key in subjects:
        included.update(store.includes.get(key, {}).values())
    car["flags"] = flags
    car["packs_required"] = packs_required or None
    car["pack_prices_gbp"] = prices or None
    if included:
        car["packs"] = sorted(included)
    car["field_sources"] = sources or None
    car["disagreements"] = disagreements or None
    car["overruled"] = overruled or None
    name = store.names.get(f"derivative:{car.get('cap_id')}")
    if name:
        car["cap_name"] = name
    return car


def resolve_all(cars: list[dict], store: Store) -> dict:
    """Every car resolved; a few counts for the Data page."""
    n_fields = 0
    n_dis = 0
    for c in cars:
        resolve_car(c, store)
        n_fields += len(c.get("field_sources") or {})
        n_dis += len(c.get("disagreements") or {})
    return {"claims": store.count(), "subjects": len(store.claims), "fields_from_claims": n_fields, "disagreements": n_dis}
