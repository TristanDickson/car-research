"""Parkers (www.parkers.co.uk), Bauer's used-car valuation site: every generation of a model, its trims and
every derivative, old ones included (docs/SOURCES.md, "Parkers"). It is the list of trims and derivatives the
resolver's car level reads (docs/REBUILD.md, "Next: one resolver over every record").

Two capabilities:

  sitemap   the three spec sitemaps (`sitemap/zip-files/spec-1.xml.gz` ...), a week apart: every spec page's
            address, which names the model, the generation with its body and start year (`kona-electric/
            suv-2018`), each trim (`trim-ultimate`), each engine and each derivative in CAP's wording with its
            packs (`160kw-ultimate-65kwh-5dr-auto-[lux-pack]`). One 'spec' record per address of an electric
            generation, keyed parkers-sitemap:<path>.
  pages     each electric derivative's own page: its on-sale dates, price when new, the specs, the charging
            times and the standard and optional equipment. Discovered from the sitemaps the raw store holds,
            never-read pages first (newest generations first), then pages read more than FRESH_DAYS ago;
            PER_RUN a night. One 'spec' record keyed parkers:<path>.

A derivative is electric when its address names a kWh, or every engine of its generation is electric; and never
when its name burns fuel (parse.combustion).
"""
from __future__ import annotations

import gzip
import html as H
import re
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import combustion, money
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "parkers"
HOST = "www.parkers.co.uk"
BASE = f"https://{HOST}/"
SITEMAPS = ("spec-1", "spec-2", "spec-3")
SITEMAP_FRESH_DAYS = 7
FRESH_DAYS = 30
PER_RUN = 400
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
KWH_RE = re.compile(r"\d\s*-?kwh|kwh-battery", re.I)
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
ON_SALE_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})"
                        r"\s*-\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})|(\w+))$")


# ---------------------------------------------------------------- the sitemap

def site_paths(xml: str) -> list[list[str]]:
    """Every spec page's address in a sitemap, as its path's parts ('hyundai', 'kona-electric', 'suv-2018', ...)."""
    return [u.replace(BASE, "").strip("/").split("/") for u in LOC_RE.findall(xml) if u.startswith(BASE)]


def electric_paths(paths: list[list[str]]) -> list[list[str]]:
    """The addresses of electric generations' derivatives, trims and engines (see the module docstring)."""
    gens: dict[tuple[str, str, str], list[list[str]]] = {}
    for p in paths:
        if len(p) == 5 and p[-1] == "specs":
            gens.setdefault((p[0], p[1], p[2]), []).append(p)
    out: list[list[str]] = []
    for key, ps in gens.items():
        engines = [p[3] for p in ps if p[3].startswith("engine-")]
        all_electric = bool(engines) and all("electric" in e or KWH_RE.search(e) for e in engines)
        derivs = [p for p in ps if not p[3].startswith(("trim-", "engine-"))]
        keep = [p for p in derivs if (KWH_RE.search(p[3]) or all_electric) and not combustion(p[3].replace("-", " "))]
        if keep:
            out += [p for p in ps if p[3].startswith(("trim-", "engine-"))] + keep
    return out


def _start_year(generation: str) -> int | None:
    m = re.search(r"(\d{4})$", generation)
    return int(m.group(1)) if m else None


def _sitemap_row(p: list[str]) -> dict:
    make, model, gen, leaf = p[0], p[1], p[2], p[3]
    kind = "trim" if leaf.startswith("trim-") else "engine" if leaf.startswith("engine-") else "derivative"
    return {"spec_key": f"{SITE}-sitemap:{'/'.join(p[:4])}", "source": "Parkers sitemap", "source_url": BASE + "/".join(p) + "/",
            "make_slug": make, "model_slug": model, "generation": gen, "generation_start": _start_year(gen),
            "body": re.sub(r"-?\d{4}$", "", gen) or None, "entry": kind,
            "slug": leaf[len(kind) + 1:] if kind != "derivative" else leaf}


def discover_sitemaps(target: Target, ctx: Context) -> Iterator[Target]:
    """The spec sitemaps, unless every one was fetched in the last SITEMAP_FRESH_DAYS (a named one always)."""
    names = SITEMAPS if target.identifier == "all" else (target.identifier,)
    held = _latest(ctx, "sitemap") if target.identifier == "all" else {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SITEMAP_FRESH_DAYS)).isoformat()
    for n in names:
        if held.get(n, {}).get("fetched_at", "") < cutoff:
            yield Target(identifier=n, metadata={"url": f"{BASE}sitemap/zip-files/{n}.xml.gz"})


def fetch_sitemap(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx, accept="application/xml")


def _xml(body: bytes) -> str:
    return (gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body).decode("utf-8", "replace")


def parse_sitemap(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    seen = observed_at_for(target)
    for p in electric_paths(site_paths(_xml(body))):
        row = _sitemap_row(p)
        row["observed_at"] = seen
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


# ---------------------------------------------------------------- the derivative pages

def _latest(ctx: Context, capability: str) -> dict[str, dict]:
    """target → its latest successful fetch for this capability, from the raw store (none without one)."""
    store = ctx.extras.get("raw_store")
    out: dict[str, dict] = {}
    if store is None:
        return out
    for e in store.entries():
        if e.get("source") == "parkers" and e.get("capability") == capability and e.get("status") == 200 and e.get("role") != "part":
            if e["fetched_at"] >= out.get(e["target"], {}).get("fetched_at", ""):
                out[e["target"]] = e
    return out


def discover_pages(target: Target, ctx: Context) -> Iterator[Target]:
    """Electric derivatives' pages from the sitemaps the raw store holds: never-read ones first, newest generations
    first; then those read more than FRESH_DAYS ago, stalest first. PER_RUN a run (`parkers_per_run` overrides)."""
    if target.identifier != "all":
        yield Target(identifier=target.identifier, metadata={"url": BASE + target.identifier + "/specs/"})
        return
    store = ctx.extras.get("raw_store")
    maps = _latest(ctx, "sitemap")
    paths: dict[str, list[str]] = {}
    for e in maps.values():
        for p in electric_paths(site_paths(_xml(store.get(e["sha256"])))):
            if not p[3].startswith(("trim-", "engine-")):
                paths["/".join(p[:4])] = p
    read = _latest(ctx, "pages")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)).isoformat()
    never = sorted((p for k, p in paths.items() if k not in read), key=lambda p: (-(_start_year(p[2]) or 0), p))
    stale = sorted((p for k, p in paths.items() if k in read and read[k]["fetched_at"] < cutoff), key=lambda p: read["/".join(p[:4])]["fetched_at"])
    from pipeline.providers.politeness import allowance, note
    usual = int(ctx.extras.get("parkers_per_run", PER_RUN))
    budget = allowance(store, HOST, usual)
    note(ctx, HOST, budget, usual)
    for p in (never + stale)[:budget]:
        yield Target(identifier="/".join(p[:4]), metadata={"url": BASE + "/".join(p[:4]) + "/specs/", "make_slug": p[0], "model_slug": p[1],
                                                         "generation": p[2]})


def fetch_page(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def _lines(page: str) -> list[str]:
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", page, flags=re.S | re.I)
    t = H.unescape(re.sub(r"<[^>]+>", "\n", t)).replace("�", "£")
    return [re.sub(r"\s+", " ", l).strip() for l in t.split("\n") if l.strip()]


def _after(lines: list[str], label: str) -> str | None:
    """The line after the first that is exactly `label`."""
    for i, l in enumerate(lines[:-1]):
        if l == label:
            return lines[i + 1]
    return None


def _num(s: str | None) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def _month(name: str, year: str) -> str:
    return f"{int(year):04d}-{MONTHS[name.lower()]:02d}"


SPEC_LABELS = {   # label on the page -> (field, what to read)
    "Horsepower": "power_bhp", "Acceleration 0-60mph": "zero_to_60_s", "Energy consumption": "efficiency_mi_kwh",
    "Electric range": "wltp_range_mi", "Insurance group": "insurance_group", "Battery capacity": "battery_kwh",
    "Weight": "weight_kg", "Length": "length_mm", "Width": "width_mm", "Wheelbase": "wheelbase_mm",
    "Turning circle": "turning_circle_m", "Doors": "doors",
}


EQUIP_RE = re.compile(r'class="specs-detail__equipment__group__title">(.*?)</a>|<li>(.*?)</li>', re.S)


def _equipment(page: str, head: str) -> list[str]:
    """The items listed under 'Standard Equipment (N)' or 'Optional Equipment (N)', without their group headings.
    Parkers lists what the version had 'at some point during its production lifespan', not one car's kit."""
    i = page.find(f"{head} Equipment (")
    if i < 0:
        return []
    j = page.find("Equipment (", i + len(head) + 12)
    block = page[i: j if j > 0 else i + 200_000]
    end = block.find("specs-detail__section")
    block = block[: end] if end > 0 else block
    return [H.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip() for m in EQUIP_RE.finditer(block) if m.group(2)]


def parse_page(page: str, meta: dict, observed_at: str | None) -> dict | None:
    lines = _lines(page)
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    title = H.unescape(title.group(1)).strip() if title else ""
    name = None
    for i, l in enumerate(lines):
        if l.endswith(" Specs & dimensions") and i:
            name = l[: -len(" Specs & dimensions")].strip()
            break
    if not name:
        return None
    on_sale = next((ON_SALE_RE.match(l) for l in lines if ON_SALE_RE.match(l)), None)
    since = _month(on_sale.group(1), on_sale.group(2)) if on_sale else None
    until = _month(on_sale.group(3), on_sale.group(4)) if on_sale and on_sale.group(3) else None
    numbers: dict[str, float | str] = {}
    for label, field in SPEC_LABELS.items():
        v = _num(_after(lines, label))
        if v is not None:
            numbers[field] = v
    for label, field in (("Transmission", "transmission"), ("Fuel type", "fuel")):
        v = _after(lines, label)
        if v:
            numbers[field] = v
    if "wheelbase_mm" in numbers:
        numbers["wheelbase_m"] = round(float(numbers.pop("wheelbase_mm")) / 1000, 3)
    charging: dict[str, str] = {}
    try:
        i = lines.index("Battery charging times")
        chargers = []
        for l in lines[i + 1:]:
            if l.startswith("Charge from"):
                break
            chargers.append(l)
        times = [lines[j + 1] for j in range(i, min(i + 40, len(lines) - 1)) if lines[j].startswith("Charge from")]
        labels = [lines[j] for j in range(i, min(i + 40, len(lines) - 1)) if lines[j].startswith("Charge from")]
        for c, lab, t in zip(chargers, labels, times):
            charging[f"{c} · {lab.replace('Charge from ', '')}"] = t
    except ValueError:
        pass
    path = meta.get("path") or "/".join(x for x in (meta.get("make_slug"), meta.get("model_slug"), meta.get("generation")) if x)
    return {
        "spec_key": f"{SITE}:{meta.get('target') or path}", "source": "Parkers", "source_url": meta.get("url"), "observed_at": observed_at,
        "make_slug": meta.get("make_slug"), "model_slug": meta.get("model_slug"), "generation": meta.get("generation"),
        "generation_start": _start_year(meta.get("generation") or ""),
        "title": title.replace(" specs & dimensions | Parkers", ""), "name": name,
        "on_sale_since": since, "on_sale_until": until,
        "price_new": money(_after(lines, "Price when new")),
        "numbers": numbers, "charging": charging or None,
        "features": _equipment(page, "Standard"), "options": _equipment(page, "Optional"),
    }


def parse_page_record(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    meta = dict(target.metadata, target=target.identifier)
    row = parse_page(body.decode("utf-8", "replace"), meta, observed_at_for(target))
    if row:
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


sitemap = Capability(name="sitemap", parser_version="1", discover=discover_sitemaps, fetch=fetch_sitemap, parse=parse_sitemap, kinds=("spec",))
pages = Capability(name="pages", parser_version="1", discover=discover_pages, fetch=fetch_page, parse=parse_page_record, kinds=("spec",))
provider = Provider(name="parkers", default_capability="pages", capabilities={"sitemap": sitemap, "pages": pages}, live=True)
