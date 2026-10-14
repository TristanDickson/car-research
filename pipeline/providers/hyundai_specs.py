"""Hyundai UK's "Technical, Specifications and Pricing" guide, one PDF per model,
linked from https://www.hyundai.com/uk/en/models/<model>/downloads.html

The maker's own word, trim by trim: a Specifications table of ● / - cells per
trim column (a trim can have two columns, one per model year; a cell can carry
a qualifier such as '● 49kWh only' or a footnote mark whose text says 'only
standard on the 84kWh battery'), a pricing table (which batteries each trim
comes with), and an OPTIONAL EXTRAS table (packs with their contents, price and
the trims they are offered on). The PDF's standard and optional glyphs extract
as the same character, so an item a pack offered on the trim bundles is read
as that pack's, not as standard; a '-' is not fitted as standard.

Fetch reads the downloads page, follows the guide link and keeps the PDF as
the artifact; parse turns it into layout text (pdftotext, else pypdf) and
emits one 'spec' row per trim (the latest model year of each), like the Kia
provider: features (●), absent (-), qualified items, batteries, packs, options
with their prices. Each row also carries its powertrains: every pricing-table
row for the trim (on-the-road price and the other cells as printed) with the
Technical pages' numbers and text for that powertrain and trim; the numbers
every powertrain shares, and the battery warranty, are the row's `numbers`.
The claim store (services/claims.py) reads the rows as the maker's claims.
"""
from __future__ import annotations

import html as H
import os
import re
import shutil
import subprocess
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import money, norm_key, slug, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for
from pipeline.services.features import flags_for

SITE = "hyundai-spec"
# carwow model slug → (hyundai site slug, model name as Carwow prints it)
MODELS = {
    "inster": ("inster", "Inster"), "ioniq-5": ("ioniq5", "Ioniq 5"), "ioniq-6": ("ioniq6", "Ioniq 6"),
    "ioniq-9": ("ioniq9", "Ioniq 9"), "kona-electric": ("kona-electric", "Kona Electric"),
}
GUIDE_RE = re.compile(r"https://dmassets\.hyundai\.com/is/content/hyundaiautoever/[A-Za-z0-9_+%-]*Tech[A-Za-z0-9_+%-]*", re.I)
CELL_RE = re.compile(r"●|(?<!\w)[-–](?!\w)")
MY_RE = re.compile(r"MY\s?(\d\d)")
KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
MONEY_RE = re.compile(r"£\s?[\d,]+(?:\.\d+)?")
FOOT_RE = re.compile(r"(?:^|\s)(\*{1,4}|[‡†])\s*([A-Z][^*‡†]+?)\s*$")
MARK_RE = re.compile(r"\*{1,4}|[‡†]")
PAINT_RE = re.compile(r"\b(paint|colour|color|wheels?)\b|^Seat Trim", re.I)
AVAIL_RE = re.compile(r"^(?:All trims?|All|(?:Only\s+)?Available\s+(?:on|for)\b.*|Not available\b.*|Standard on\b.*|[^()]+\s+only|[^:()]+:\s*.+)$", re.I)
PRICING_HEADER_RE = re.compile(r"TRIM|FUEL|CO2|INSURANCE|VED|RETAIL|P11D|BIK|PAYABLE|GROUP|BAND|COST|VALUE|TYPE|G/KM|YEAR|RECOMMENDED|ROAD|\(WLTP\)|^VAT|^\*|PRICE|%", re.I)


def url_for(hy_slug: str) -> str:
    return f"https://www.hyundai.com/uk/en/models/{hy_slug}/downloads.html"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for model, (hy, name) in MODELS.items():
        if target.identifier in ("all", model):
            yield Target(identifier=model, metadata={"model": model, "model_name": name, "url": url_for(hy)})


def fetch(target: Target, ctx: Context) -> Fetched:
    """The downloads page names the guide; the guide (a PDF) is the artifact."""
    page = fetch_url(target.metadata["url"], ctx)
    m = GUIDE_RE.search(page.body.decode("utf-8", "replace"))
    if not m:
        return Fetched(url=target.metadata["url"], status_code=404, body=b"", content_type="text/html", parts=(page,))
    pdf = fetch_url(H.unescape(m.group(0)), ctx, accept="application/pdf")
    return Fetched(url=pdf.url, status_code=pdf.status_code, body=pdf.body, content_type=pdf.content_type, parts=(page,))


_READER: tuple[str, str | None] | None = None


def pdf_reader() -> tuple[str, str | None]:
    """(what reads the guides, poppler's pdftotext path if that). The parser was written against
    poppler's layout; xpdf's pdftotext (Git for Windows ships one) and pypdf wrap the tables
    differently, and pypdf loses lines of a pack's contents (the Ioniq 5 Ultimate's Zen Pack).
    So: $CAR_RESEARCH_PDFTOTEXT, else a poppler pdftotext on PATH, else pypdf. The build's parse
    cache keys on this, so a change of reader reads every stored guide again."""
    global _READER
    if _READER is None:
        candidates = [os.environ.get("CAR_RESEARCH_PDFTOTEXT"), shutil.which("pdftotext")]
        for exe in [c for c in candidates if c]:
            try:
                v = subprocess.run([exe, "-v"], capture_output=True, timeout=30)
            except OSError:
                continue
            banner = (v.stdout + v.stderr).decode("utf-8", "replace")
            if "poppler" in banner.lower():
                version = next((line.split()[-1] for line in banner.splitlines() if "version" in line), "?")
                _READER = (f"poppler {version}", exe)
                break
        else:
            try:
                import pypdf
                _READER = (f"pypdf {pypdf.__version__}", None)
            except ImportError:
                _READER = ("none", None)
    return _READER


def pdf_text(body: bytes) -> str:
    """Layout-preserving text of a guide, by the reader pdf_reader() picks."""
    name, exe = pdf_reader()
    if exe:
        # From a file: a pdftotext on Windows may not read a PDF from standard input.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "guide.pdf")
            with open(src, "wb") as f:
                f.write(body)
            out = subprocess.run([exe, "-layout", "-enc", "UTF-8", src, "-"], capture_output=True, check=True)
        return out.stdout.decode("utf-8", "replace")
    if name == "none":
        raise RuntimeError("reading a PDF needs poppler's pdftotext ($CAR_RESEARCH_PDFTOTEXT, or poppler-utils) or pypdf")
    import io
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(body))
    return "\n\f".join(p.extract_text(extraction_mode="layout") or "" for p in reader.pages)


def _same(a: str, b: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", a.lower()) == re.sub(r"[^a-z0-9]", "", b.lower())


# ---------------------------------------------------------------- the specification table

def _columns(line: str) -> list[dict]:
    """Column names and their centres from a header line ('INSTER 01   INSTER 02 ...')."""
    return [{"name": m.group(0).strip(), "start": m.start(), "end": m.end(), "mid": (m.start() + m.end()) / 2}
            for m in re.finditer(r"\S+(?:[ ]\S+)*", line)]


def _qualifiers(line: str, cols: list[dict]) -> list[str]:
    """The line under the header ('7 SEAT (MY27)   6 SEAT (MY27)   7 SEAT BLACK INK (MY27) 6 SEAT BLACK INK (MY27)'):
    each token goes to the nearest column; two qualifiers printed a single space apart are split at ') 6'."""
    quals = [""] * len(cols)
    hits = [0] * len(cols)
    for m in re.finditer(r"\S+(?:[ ]\S+)*", line):
        at = m.start()
        for part in re.split(r"(?<=\))\s+(?=\d)", m.group(0)):
            mid = at + len(part) / 2
            idx = min(range(len(cols)), key=lambda i: abs(cols[i]["mid"] - mid))
            quals[idx] = f"{quals[idx]} {part}".strip()
            hits[idx] += 1
            cols[idx]["mid"] = (cols[idx]["mid"] + mid) / 2 if hits[idx] == 1 else cols[idx]["mid"]
            at += len(part) + 1
    return quals


def _cells(line: str, cols: list[dict]) -> list[str]:
    """What each column's window holds on a row line."""
    bounds = []
    for i, c in enumerate(cols):
        lo = (cols[i - 1]["mid"] + c["mid"]) / 2 if i else c["start"] - 2
        hi = (c["mid"] + cols[i + 1]["mid"]) / 2 if i + 1 < len(cols) else len(line) + 1
        bounds.append((int(lo), int(hi)))
    return [line[lo:hi].strip() for lo, hi in bounds]


def _cell_value(cell: str) -> tuple[str | None, str]:
    """(standard | none | None, qualifier text)."""
    c = cell.strip()
    if not c:
        return None, ""
    if c.startswith("●"):
        return "standard", c[1:].strip()
    if re.fullmatch(r"[-–]", c):
        return "none", ""
    if re.search(r"standard", c, re.I):
        return "standard", c
    if re.search(r"n/?a|not available", c, re.I):
        return "none", c
    return None, c


def _footnote_line(line: str, fm: re.Match) -> bool:
    """A footnote on its own line, or printed beside the KEY legend ('● Standard   *** Heat pump is ...')."""
    before = line[: fm.start()].strip()
    return before in ("", "KEY") or bool(re.fullmatch(r"[●-]\s*(Standard|Optional|Not Available)", before, re.I))


def _is_heading(s: str) -> bool:
    t = s.strip()
    return bool(t) and t == t.upper() and not CELL_RE.search(t) and len(t) < 60 and not MONEY_RE.search(t)


def parse_specs(txt: str) -> tuple[dict[str, dict], dict[str, str]]:
    """{column key: {trim, qualifier, my, seats, items: [(label, value, qualifier)]}}, and the footnotes.

    A qualifier is the text after a cell's ● ('49kWh only') and any footnote mark on the cell
    ('●***'); a mark on the label alone ('Heat Pump***') applies to every cell of the row."""
    lines = txt.split("\n")
    columns: dict[str, dict] = {}
    footnotes: dict[str, str] = {}
    cols: list[dict] | None = None
    keys: list[str] = []
    pending: list[str] = []
    done = False
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        s = line.strip()
        if s.startswith("Specifications") and not done:
            at = line.index("Specifications") + len("Specifications")
            if line[at:].strip():
                header, j = " " * at + line[at:], i
            else:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines):
                    break
                header = lines[j].rstrip()
            cols = _columns(header)
            quals = [""] * len(cols)
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and cols and (MY_RE.search(lines[k]) or re.search(r"\bSEAT\b", lines[k], re.I)):
                quals = _qualifiers(lines[k].rstrip(), cols)
                j = k
            keys = []
            for idx, (c, q) in enumerate(zip(cols, quals)):
                my = MY_RE.search(q or c["name"])
                seats = re.search(r"(\d)\s*SEAT", q, re.I)
                extra = re.sub(r"\d\s*SEATS?|\(MY\d\d\)|\bMY\d\d\b", " ", q).strip()
                key = f"{c['name']}|{q}"
                if key in keys:
                    key = f"{key}#{idx}"
                columns.setdefault(key, {"trim": re.sub(r"\s+", " ", f"{re.sub(r'\(MY\d\d\)|\bMY\d\d\b', '', c['name'])} {extra}").strip(), "qualifier": q,
                                         "my": int(my.group(1)) if my else None, "seats": int(seats.group(1)) if seats else None, "items": []})
                keys.append(key)
            pending = []
            i = j + 1
            continue
        if re.match(r"^Pricing\b", s):
            cols, done = None, True   # the pricing pages follow; no more footnotes
        if cols and s.startswith("KEY"):
            cols = None
        fm = FOOT_RE.search(line)
        if fm and not done and _footnote_line(line, fm):
            footnotes[fm.group(1)] = text(fm.group(2))
            i += 1
            continue
        if cols is None or not s:
            i += 1
            continue
        if _is_heading(s):
            pending = []
            i += 1
            continue
        first = min((c["start"] for c in cols), default=len(line))
        label_part = line[: max(0, first - 2)].strip()
        cells = _cells(line, cols)
        values = [_cell_value(c) for c in cells]
        if not any(v for v, _ in values):
            pending.append(s)
            i += 1
            continue
        label = text(" ".join(pending + ([label_part] if label_part else [])))
        pending = []
        lm = re.search(r"(\*{1,4}|[‡†])\s*$", label)
        label = label[: lm.start()].strip() if lm else label
        row_marked = any(MARK_RE.search(q) for _, q in values)
        if label:
            for key, (v, q) in zip(keys, values):
                if v is not None:
                    if lm and not row_marked:
                        q = f"{q} {lm.group(1)}".strip()
                    columns[key]["items"].append((label, v, q))
        i += 1
    return columns, footnotes


# ---------------------------------------------------------------- pricing and extras

PRICING_NOISE_RE = re.compile(r"single speed|reduction|battery electric|^bev$|^electric$|^battery$|^\(MY\d\d\)$|^\d\s*seats?$", re.I)


def _trim_only(s: str) -> bool:
    """A pricing line that is just a trim name ('Premium'), printed beside its powertrain rows."""
    return bool(s) and not MONEY_RE.search(s) and not re.search(r"\d", s) and not PRICING_HEADER_RE.search(s) and not PRICING_NOISE_RE.search(s)


INSURANCE_RE = re.compile(r"^(?:\d{1,2}[A-Z]|TBC)$")
PS_RE = re.compile(r"(\d+)\s*PS\b", re.I)
DRIVE_RE = re.compile(r"\b(AWD|RWD|FWD)\b", re.I)
SEATS_RE = re.compile(r"(\d)\s*SEATS?\b", re.I)


def _is_price_line(s: str) -> bool:
    amounts = [a for a in (money(m) for m in MONEY_RE.findall(s)) if a]
    return len(MONEY_RE.findall(s)) >= 3 and bool(amounts) and max(amounts) >= 5000


def _int(x: float | None) -> float | int | None:
    return int(x) if x is not None and float(x).is_integer() else x


def _price_cells(s: str) -> tuple[str, dict]:
    """A price line's own label words, and its cells: CO2 g/km, insurance group, VED band and first-year cost,
    basic retail, VAT, retail, recommended on the road, P11D, BIK band, monthly BIK at 20% and 40%, as printed.
    The guides print five or six £ cells before the BIK band (the VED cost is the sixth) and the monthly BIK with or without £."""
    tokens = s.split()
    first = next((i for i, t in enumerate(tokens) if MONEY_RE.fullmatch(t)), len(tokens))
    pre = tokens[:first]
    cells: dict = {}
    if len(pre) >= 2 and re.fullmatch(r"[A-M]", pre[-1]) and INSURANCE_RE.match(pre[-2]):
        cells["ved_band"] = pre.pop()
    if pre and INSURANCE_RE.match(pre[-1]):
        ins = pre.pop()
        cells["insurance_group"] = None if ins == "TBC" else ins
    if pre and re.fullmatch(r"\d+", pre[-1]):
        cells["co2_g_km"] = int(pre.pop())
    rest = tokens[first:]
    at = next((i for i, t in enumerate(rest) if re.fullmatch(r"\d+(?:\.\d+)?%", t)), len(rest))
    amounts = [money(t) for t in rest[:at] if MONEY_RE.fullmatch(t)]
    if len(amounts) >= 5:
        if len(amounts) >= 6:
            cells["ved_first_year_gbp"] = _int(amounts[-6])
        for k, v in zip(("basic_retail_gbp", "vat_gbp", "retail_price_gbp", "otr_price_gbp", "p11d_gbp"), amounts[-5:]):
            cells[k] = _int(v)
    elif amounts:
        cells["otr_price_gbp"] = _int(max(a for a in amounts if a is not None))
    if at < len(rest):
        cells["bik_pct"] = _int(float(rest[at].rstrip("%")))
        after = [float(t.replace("£", "").replace(",", "")) for t in rest[at + 1:] if re.fullmatch(r"£?[\d,]+(?:\.\d+)?", t)]
        for k, v in zip(("bik_monthly_20pct_gbp", "bik_monthly_40pct_gbp"), after):
            cells[k] = v
    return " ".join(pre), cells


def _price_trim(head: str) -> str:
    t = re.sub(r"\(MY\d\d\)|\bMY\d\d\b|single speed reduction|battery electric|battery|electric|\bBEV\b|\d\s*seats?\b", " ", head, flags=re.I)
    cut = re.search(r"\d+(?:\.\d+)?\s*kwh|\d+\s*ps\b|\d+\s*kw\b", t, re.I)
    t = t[: cut.start()] if cut else t
    t = re.sub(r"\brwd\b|\bawd\b|\bfwd\b|\(.*?\)|(?<![\w£.,])0(?![\w.,])", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def parse_price_rows(txt: str) -> list[dict]:
    """Every row of the pricing table: {trim, label, model_year, battery_kwh, power_ps, drive, seats, cells}.

    A row is its price line and the lines pdftotext wraps around it ('Advance 63 kWh 170PS' above,
    'RWD' below; 'CALLIGRAPHY' above, '7 SEAT BLACK INK (MY27)' below), up to the blank lines that
    part one row from the next. Where rows are printed with no blank between them, a line between two
    price lines goes with the lower one. A table titled 'MY26' gives its rows that model year. Where
    the trim is printed once beside several powertrain rows ('Premium' between '77.4 KWh 228PS RWD'
    and '77.4 KWh 325PS AWD') the nearest such line names the row."""
    out: list[dict] = []
    on, table_my, run = False, None, []
    title = next((l.strip() for l in txt.split("\n") if l.strip()), "")   # 'IONIQ 5', printed atop every page

    def flush() -> None:
        at = [k for k, s in enumerate(run) if _is_price_line(s)]
        for n, k in enumerate(at):
            above = run[(at[n - 1] + 1 if n else 0): k]
            below = run[k + 1:] if n + 1 == len(at) else []
            hdr = [j for j, s in enumerate(above) if PRICING_HEADER_RE.search(s)]
            above = above[hdr[-1] + 1:] if hdr else above
            below = below[: next((j for j, s in enumerate(below) if PRICING_HEADER_RE.search(s)), len(below))]
            own, cells = _price_cells(run[k])
            head = text(" ".join([*above, own, *below]))
            trim = _price_trim(head)
            if not trim:
                near = [(abs(j - k), j) for j in range(len(run)) if j != k and _trim_only(run[j])]
                trim = run[min(near)[1]] if near else ""
            if not trim or re.search(r"^trim$|fuel type", trim, re.I):
                continue
            my, kwh, ps, drive, seats = MY_RE.search(head), KWH_RE.search(head), PS_RE.search(head), DRIVE_RE.search(head), SEATS_RE.search(head)
            label = re.sub(r"\s+", " ", re.sub(r"battery electric|\bbattery\b|\belectric\b|\bBEV\b|single speed reduction", " ", head, flags=re.I)).strip()
            out.append({"trim": trim, "label": label, "model_year": 2000 + int(my.group(1)) if my else table_my,
                        "battery_kwh": float(kwh.group(1)) if kwh else None, "power_ps": int(ps.group(1)) if ps else None,
                        "drive": drive.group(1).upper() if drive else None, "seats": int(seats.group(1)) if seats else None, "cells": cells})
        run.clear()

    for s in (l.strip() for l in txt.split("\n")):
        if re.match(r"^Pricing\b", s):
            flush()
            on = True
            continue
        if not on:
            continue
        if s.startswith("OPTIONAL EXTRAS") or s.startswith("Features and options may vary"):
            flush()
            on = False
            continue
        m = re.fullmatch(r"MY\s?(\d\d)", s)
        if m or not s or s == title:
            flush()
            table_my = 2000 + int(m.group(1)) if m else table_my
            continue
        run.append(s)
    flush()
    return out


def parse_pricing(txt: str) -> dict[str, dict]:
    """trim words → {batteries: [kWh], prices: {'kWh|PS|seats|model year': on-the-road £}, rows: [price rows]}
    from the pricing table (parse_price_rows). A trim printed twice ('CROSS', 'Cross') is one trim."""
    out: dict[str, dict] = {}
    for r in parse_price_rows(txt):
        trim = next((k for k in out if _same(k, r["trim"])), r["trim"])
        row = out.setdefault(trim, {"batteries": [], "prices": {}, "rows": []})
        row["rows"].append(r)
        if r["battery_kwh"] is not None and r["battery_kwh"] not in row["batteries"]:
            row["batteries"].append(r["battery_kwh"])
        if r["cells"].get("otr_price_gbp") is not None:
            row["prices"][_pt_key(r)] = r["cells"]["otr_price_gbp"]
    return out


def _pt_key(r: dict) -> str:
    return "|".join("" if r.get(k) is None else f"{r[k]:g}" for k in ("battery_kwh", "power_ps", "seats", "model_year"))


# ---------------------------------------------------------------- the technical pages

WORD_NUMBERS = {w: i for i, w in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                                            "eleven", "twelve"))}
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _nums(s: str) -> list[float]:
    return [float(n.replace(",", "")) for n in NUM_RE.findall(s or "")]


def _first(s: str) -> float | int | None:
    n = _nums(s)
    return _int(n[0]) if n else None


def _minutes(s: str) -> int | None:
    """'0 hr 18 min', '1hr 43min', '30 min @ 73kW max', '18 mins', '24 minutes @ 233kW max)' → minutes."""
    s = re.sub(r"@.*", "", s or "")
    h = re.search(r"(\d+)\s*h(?:r|rs|ours?)?\b", s, re.I)
    m = re.search(r"(\d+)\s*min", s, re.I)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def _bounds(s: str) -> tuple[float | int | None, float | int | None]:
    """'1880 - 1960' and '425-337' → (low, high); '520' → (520, 520)."""
    n = _nums(s)
    return (_int(min(n[:2])), _int(max(n[:2]))) if n else (None, None)


def _power(label: str, value: str) -> dict:
    """'170 / 125' under '(PS/kW)', '160/218 (kW/PS)', '168 (228)' under 'kW (PS)' → power_kw, power_ps."""
    n = _nums(value)
    if len(n) < 2:
        return {}
    order = re.search(r"\((PS|kW)\s*/\s*(PS|kW)\)", value, re.I) or re.search(r"\((PS|kW)\s*/\s*(PS|kW)\)", label, re.I)
    kw_first = order.group(1).lower() == "kw" if order else bool(re.match(r"^kW\s*\(PS\)", label, re.I))
    kw, ps = (n[0], n[1]) if kw_first else (n[1], n[0])
    return {"power_kw": _int(kw), "power_ps": _int(ps)}


def _technical_numbers(label: str, value: str, section: str, section_pct: str | None) -> dict:
    """One Technical row in the names the other spec providers use (kia_specs, evdb_cars; claims.NUMBERS where it has one)."""
    lb = label
    if re.search(r"Motor Max Power|^kW\s*\(PS\)", lb, re.I):
        return _power(lb, value)
    if re.search(r"Torque", lb, re.I):
        n = _nums(value)
        return {"torque_nm": _int(n[0]), "torque_lbft": _int(n[1]) if len(n) > 1 else None} if n else {}
    if re.match(r"0\s*-\s*62", lb):
        return {"zero_to_62_s": _first(value)}
    if re.match(r"Top Speed", lb, re.I):
        n = _nums(value)
        return {"top_speed_mph": _int(n[1] if "kph" in lb.lower() and len(n) > 1 else n[0])} if n else {}
    if re.match(r"Battery (?:Capacity|Size)", lb, re.I):
        return {"battery_kwh": _first(value)}
    if re.match(r"Charging Port", lb, re.I):
        return {"charge_port": value}
    if re.search(r"Max DC charging", lb, re.I):
        return {"dc_peak_kw": _first(value)}
    if re.search(r"On Board Charger", lb, re.I):
        return {"ac_kw": _first(value)}
    m = re.search(r"Public\s+(\d+)\s*kW\s+CCS\s*\(10\s*-\s*80%\)", lb, re.I)
    if m:
        at = re.search(r"@\s*(\d+)\s*kW", value, re.I)
        return {f"_dc:{m.group(1)}": (_minutes(value), int(at.group(1)) if at else None)}
    m = re.search(r"CHARGING\s*-\s*(\d+)\s*KW", section, re.I)
    if m and re.match(r"Est\w*\s+Time", lb, re.I) and section_pct and re.search(r"10\s*-\s*80", section_pct):
        return {f"_dc:{m.group(1)}": (_minutes(value), None)}
    if re.search(r"Turning Circle", lb, re.I):
        return {"turning_circle_m": _first(value)}
    if re.search(r"Overall Length", lb, re.I):
        return {"length_mm": _first(value)}
    if re.search(r"Width.*(?:Excluding|without)\s+(?:Door\s+|Side\s+)?Mirrors", lb, re.I):
        return {"width_mm": _first(value)}
    if re.search(r"Width.*Including\s+(?:Door|Standard Side)\s+Mirrors|with standard O/S", lb, re.I):
        return {"width_mirrors_mm": _first(value)}
    if re.match(r"Wheelbase", lb, re.I):
        n = _first(value)
        return {"wheelbase_m": n / 1000 if n else None}
    m = re.match(r"(1st|2nd) Row (Head|Leg|Shoulder) Room", lb, re.I)   # the Ioniq 6's '1st Row Head Room (mm)'
    if m:
        kind = {"head": "headroom", "leg": "legroom", "shoulder": "shoulder"}[m.group(2).lower()]
        return {f"{kind}_{'front' if m.group(1) == '1st' else 'rear'}_mm": _first(value)}
    if re.search(r"Overall Height|^Height\s*\(mm\)", lb, re.I):
        return {"height_mm": _first(value)}
    if re.search(r"Kerb Weight", lb, re.I):
        lo, hi = _bounds(value)
        return {"kerb_weight_kg": lo, "kerb_weight_max_kg": hi}
    if re.match(r"Payload", lb, re.I):
        lo, hi = _bounds(value)
        return {"payload_kg": lo, "payload_max_kg": hi}
    if re.search(r"Gross Vehicle Weight", lb, re.I):
        return {"gvwr_kg": _first(value)}
    if re.search(r"Unbraked", lb, re.I):
        return {"tow_unbraked_kg": _first(value)}
    if re.search(r"Tow.*Braked", lb, re.I):
        return {"tow_kg": _first(value)}
    if re.search(r"Gross Train", lb, re.I):
        return {"gross_train_weight_kg": _first(value)}
    if re.search(r"Noseweight", lb, re.I):
        return {"noseweight_kg": _first(value)}
    if re.search(r"Roof Weight", lb, re.I):
        return {"roof_load_kg": _first(value)}
    if re.search(r"Frunk\s*\+\s*Trunk", lb, re.I):
        n = _nums(value)
        return {"frunk_l": _int(n[0]), "boot_l": _int(n[1])} if len(n) >= 2 else {}
    if re.match(r"Frunk", lb, re.I):
        return {"frunk_l": _first(value)}
    if re.search(r"Seats Up\s*\(behind 2nd row", lb, re.I):
        return {"boot_3rd_row_folded_l": _bounds(value)[0]}
    if re.search(r"Seats Up", lb, re.I):
        return {"boot_l": _bounds(value)[0], **({"boot_rear_slid_l": _bounds(value)[1]} if len(_nums(value)) > 1 else {})}
    if re.search(r"Seats Down", lb, re.I):
        return {"boot_max_l": _first(value)}
    if re.search(r"(?:Electric|Maximum Potential EV Driving)\s+Range", lb, re.I):
        n = _nums(value)
        return {"wltp_range_mi": _int(n[0]), "wltp_range_km": _int(n[1]) if len(n) > 1 else None} if n else {}
    if re.search(r"Efficiency.*kWh per 100\s*Km", lb, re.I):
        return {"efficiency_kwh_100km": _first(value)}
    if re.match(r"Front Tyre", lb, re.I):
        w = re.search(r"R\s?(\d\d)\b", value)
        return {"tyre_front": value, **({"wheel_in": int(w.group(1))} if w else {})}
    if re.match(r"Rear Tyre", lb, re.I):
        return {"tyre_rear": value}
    return {}


def _strip_model(s: str, model_name: str) -> str:
    words = [re.escape(w) for w in (model_name or "").split()]
    for n in range(len(words), 0, -1):
        s2 = re.sub(r"^\s*" + r"\s+".join(words[:n]) + r"\b\s*", "", s, flags=re.I)
        if s2 != s:
            return s2
    return s


def _scope(s: str, trims: list[str], model_name: str) -> tuple[str, int | None] | None:
    """A trim heading on a Technical page ('ADVANCE', 'INSTER 01', 'CALLIGRAPHY 6 SEAT BLACK INK') → (trim, seats)."""
    seats = SEATS_RE.search(s)
    body = re.sub(r"\s+", " ", SEATS_RE.sub(" ", _strip_model(s, model_name))).strip()
    t = next((t for t in trims if body and _same(t, body)), None)
    return (t, int(seats.group(1)) if seats else None) if t else None


def _column(name: str, trims: list[str], model_name: str) -> dict:
    """A Technical column's header ('63 kWh 170 PS RWD', 'Advance 65kWh', '160kW (218PS) RWD Long Range', 'Ultimate')."""
    body = _strip_model(name, model_name)
    trim = max((t for t in trims if re.sub(r"[^a-z0-9]", "", body.lower()).startswith(re.sub(r"[^a-z0-9]", "", t.lower()))), key=len, default=None)
    kwh, ps, drive = KWH_RE.search(body), PS_RE.search(body), DRIVE_RE.search(body)
    return {"name": name, "trim": trim, "battery_kwh": float(kwh.group(1)) if kwh else None,
            "power_ps": int(ps.group(1)) if ps else None, "drive": drive.group(1).upper() if drive else None}


def _split(line: str, cols: list[dict]) -> tuple[str, list[tuple[int, str]]]:
    """A Technical line → (its label, [(column index, value)]). A chunk is the label when it starts and ends
    left of the first column; a value chunk goes to the column whose centre is nearest."""
    first = min(c["start"] for c in cols)
    label, values = "", []
    for m in re.finditer(r"\S+(?:[ ]\S+)*", line):
        if not values and not label and m.start() < first - 2 and m.end() <= first + 1:
            label = m.group(0)
            continue
        mid = (m.start() + m.end()) / 2
        values.append((min(range(len(cols)), key=lambda i: abs(cols[i]["mid"] - mid)), m.group(0).strip()))
    return label, values


def parse_technical(txt: str, trims: list[str], model_name: str) -> list[dict]:
    """The Technical pages: [{column: {name, trim, battery_kwh, power_ps, drive}, scope: (trim, seats) | None,
    section, label, value}], one per printed cell.

    A page's first line names its columns: powertrains ('84 kWh 228 PS RWD'), or a trim and battery each
    ('Advance 65kWh'). Rows under a trim heading ('ADVANCE', 'INSTER 01', 'CALLIGRAPHY 6 SEAT') speak for
    that trim only; a '-' there is a powertrain the trim is not sold with. A label pdftotext wraps around
    its values ('Estimated Charging Emergency 3 Pin' / values / 'Connector (ICCB) 2.3kW (10-100%)') is
    joined; a value line with no label of its own takes the label lines above it."""
    lines = txt.split("\n")
    cells: list[dict] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "Technical":
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            break
        cols = _columns(lines[j].rstrip())
        for c in cols:
            c.update(_column(c["name"], trims, model_name))
        j += 1
        rows: list[dict] = []
        pending: list[str] = []
        scope, section, section_pct = None, "", None
        prev_unlabelled = False
        page = []
        while j < len(lines):
            s = lines[j].strip()
            if s == "Technical" or re.match(r"^(Specifications|Pricing)\b", s):
                break
            page.append(lines[j].rstrip())
            j += 1
        parsed = []
        for line in page:
            s = line.strip()
            if not s or re.fullmatch(r"(?:\(?MY\d\d\)?\s*)+", s) or len(s.split("  ")[0]) > 100 or not cols:
                parsed.append(None)
                continue
            parsed.append(_split(line, cols))
        for k, p in enumerate(parsed):
            if p is None:
                continue
            label, values = p
            if not values:
                sc = _scope(label, trims, model_name)
                if sc:
                    scope, section, pending, prev_unlabelled = sc, "", [], False
                    continue
                if re.match(r"^[A-Z][A-Z&]{2,}(?:\s|$)", label):   # 'ELECTRIC MOTOR', 'CHARGING - 350 KW1', 'WEIGHT AND CAPACITY ( Core / N Line)'
                    section, section_pct, scope, pending, prev_unlabelled = text(label), None, None, [], False
                    continue
                nxt = next((q for q in parsed[k + 1:] if q is not None), None)
                if prev_unlabelled and rows and not (nxt and not nxt[0] and nxt[1]):
                    rows[-1]["label"] = text(f"{rows[-1]['label']} {label}")
                else:
                    pending.append(label)
                prev_unlabelled = False
                continue
            if label or pending:
                rows.append({"label": text(" ".join(pending + ([label] if label else []))), "values": values,
                             "scope": scope, "section": section, "section_pct": section_pct})
                prev_unlabelled = not label
                pending = []
                if re.match(r"Percentage", rows[-1]["label"], re.I):
                    section_pct = values[0][1]
            else:
                prev_unlabelled = False
        for r in rows:
            for idx, v in r["values"]:
                cells.append({"column": {k: cols[idx][k] for k in ("name", "trim", "battery_kwh", "power_ps", "drive")}, "scope": r["scope"],
                              "section": r["section"], "section_pct": r["section_pct"], "label": r["label"], "value": v})
        i = j
    return cells


def _fits(col: dict, pt: dict, trim: str) -> bool:
    if col["trim"] and not _same(col["trim"], trim):
        return False
    if col["battery_kwh"] and pt.get("battery_kwh") and abs(col["battery_kwh"] - pt["battery_kwh"]) > 0.5:
        return False
    if col["power_ps"] and pt.get("power_ps"):
        return col["power_ps"] == pt["power_ps"]
    if col["drive"] and pt.get("drive"):
        return col["drive"] == pt["drive"]
    return True


def technical_for(cells: list[dict], pt: dict, trim: str, seats: int | None) -> tuple[str | None, dict, dict]:
    """(the column, numbers, facts as printed) the Technical pages give one trim × powertrain (× seats).

    The column is the one whose header fits the powertrain (battery, then power, then drive); where
    several fit (a pricing row that names no battery or power), the one the trim's own heading fills.
    Then: the rows for every trim, overlaid by the trim's rows, overlaid by its seat count's rows."""
    def in_scope(c: dict, exact: bool) -> bool:
        sc = c["scope"]
        if sc is None or not _same(sc[0], trim):
            return False
        return sc[1] == seats if exact else sc[1] is None or (seats is not None and sc[1] == seats)

    cols = {c["column"]["name"]: c["column"] for c in cells if _fits(c["column"], pt, trim)}
    if len(cols) > 1:
        filled = {c["column"]["name"] for c in cells if c["value"] not in ("-", "–") and in_scope(c, False)}
        cols = {n: c for n, c in cols.items() if n in filled} or cols
    for k in ("trim", "battery_kwh", "power_ps", "drive"):
        if len({c[k] for c in cols.values() if c[k]}) > 1:
            return None, {}, {}   # columns for different powertrains fit and the trim's headings do not pick one
    names = list(cols)
    use = set(names)
    numbers: dict = {}
    facts: dict = {}
    dc: dict[int, tuple] = {}
    for layer in (lambda c: c["scope"] is None, lambda c: in_scope(c, False) and c["scope"][1] is None,
                  lambda c: seats is not None and in_scope(c, True)):
        for c in cells:
            if c["column"]["name"] not in use or not layer(c) or c["value"] in ("-", "–", "TBC", "NA"):
                continue
            facts[f"{c['section'].title()} · {c['label']}" if c["section"] else c["label"]] = c["value"]
            value = c["value"]
            other = re.search(r"\(([\d,.]+)\s+([A-Za-z][A-Za-z ]*)\)", value)   # '3825 (3845 CROSS)': the named trim's own figure
            if other:
                value = other.group(1) if _same(other.group(2), trim) else value[: other.start()]
            for k, v in _technical_numbers(c["label"], value, c["section"], c["section_pct"]).items():
                if k.startswith("_dc:"):
                    dc[int(k[4:])] = v
                elif v is not None:
                    numbers[k] = v
    if dc:
        fast = max(k for k, v in dc.items() if v[0] is not None) if any(v[0] is not None for v in dc.values()) else None
        if fast is not None and fast >= 100:
            numbers["dc_10_80_min"], numbers["dc_10_80_charger_kw"] = dc[fast][0], fast
            if "dc_peak_kw" not in numbers and dc[fast][1]:
                numbers["dc_peak_kw"] = dc[fast][1]
        if dc.get(50) and dc[50][0] is not None:
            numbers["dc_10_80_50kw_min"] = dc[50][0]
    return (names[0] if names else None), numbers, facts


def warranty_numbers(labels: list[str]) -> dict:
    """'Eight Year 100,000 High Voltage Battery Warranty', 'High Voltage Battery Warranty - 8 Years, 100,000 Miles',
    'Five Year Unlimited Mileage Warranty' → warranty_years / warranty_miles (the battery's, as EV Database names
    them) and vehicle_warranty_years / vehicle_warranty_miles."""
    out: dict = {}
    for l in labels:
        y = re.search(r"\b(\d+|" + "|".join(WORD_NUMBERS) + r")\s+Years?\b", l, re.I)
        years = (int(y.group(1)) if y.group(1).isdigit() else WORD_NUMBERS[y.group(1).lower()]) if y else None
        miles = next((int(n) for n in (x.replace(",", "") for x in re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{5,6}\b", l))), None)
        if re.search(r"Battery Warranty", l, re.I) and years:
            out["warranty_years"] = years
            if miles:
                out["warranty_miles"] = miles
        elif re.search(r"Mileage Warranty|Vehicle Warranty|Year.*Warranty", l, re.I) and years and not re.search(r"Perforation|Paint|Health", l, re.I):
            out["vehicle_warranty_years"] = years
            out["vehicle_warranty_miles"] = "unlimited" if re.search(r"Unlimited", l, re.I) else miles
    return out


PACK_RE = re.compile(r"^(.*?\bPack)\s*[:(]\s*(.+?)\)?\s*$", re.I)
PACK_ROW_RE = re.compile(r"^[^:(]*\bPack\b\s*[:(]", re.I)      # a table row that is a pack's own availability, not an item
ACCESSORY_RE = re.compile(r"adapt[eo]r|accessor", re.I)          # sold separately: a - means not supplied, not unavailable


def parse_extras(txt: str, trims: list[str]) -> list[dict]:
    """Packs and options from OPTIONAL EXTRAS: name, items, retail price, the trims offered on.

    A pack lists its contents after its name, in brackets or after a colon ('Tech Pack (Remote
    Smart Park Assist, ...)', 'Comfort Pack: Heated Front Seats, ...'); a bracket on anything else
    is colours or an abbreviation ('Digital Side Mirrors (DSM)'), not equipment. Where a colour is
    offered on its own trims ('Glow Mint: 01 & 02 MY27') that applies to the paint that names it."""
    block: list[str] = []
    on = False
    for line in txt.split("\n"):
        s = line.strip()
        if s.startswith("OPTIONAL EXTRAS"):
            on = True
            continue
        if on and s.startswith("Features and options may vary"):
            break
        if on and s:
            block.append(s)
    entries: list[dict] = []
    avail: list[tuple[int, str]] = []   # (entry index at that point, text)
    for s in block:
        amounts = [money(m) for m in MONEY_RE.findall(s)]
        parts = [p for p in re.split(r"\s{2,}", MONEY_RE.split(s)[0].strip()) if p]
        pm = PACK_RE.match(parts[0]) if parts else None
        if parts and re.match(r"^[A-Z]", parts[0]) and (pm or not AVAIL_RE.match(parts[0])):
            name, items = parts[0], []
            if pm:
                name, items = pm.group(1).strip(), [text(x) for x in re.split(r"\s*,\s*", pm.group(2)) if x.strip()]
            entries.append({"name": name, "items": items, "price": max(amounts) if amounts else None, "trims": []})
            parts = parts[1:]
        elif entries and amounts and entries[-1]["price"] is None:
            entries[-1]["price"] = max(amounts)
        for p in parts:
            avail.append((len(entries) - 1, p))
    for idx, s in avail:
        target = None
        if ":" in s:
            colour = s.split(":", 1)[0].strip()
            target = next((e for e in entries if colour.lower() in e["name"].lower()), None)
        if target is None and idx >= 0:
            target = entries[idx]
        if target is not None:
            _apply_trims(target, s, trims)
    for e in entries:
        if not e["trims"] and not e.get("restricted"):
            e["trims"] = list(trims)   # nothing said: offered on every trim
    return entries


def _apply_trims(cur: dict, s: str, trims: list[str]) -> None:
    """'All trims', 'All', 'Available on Ultimate trim only', 'Advance only', 'Not available on Calligraphy Black Ink',
    'Glow Mint: 01 & 02 MY27' → the trims offered on. 'Standard on X' is not an offer."""
    body = s.split(":", 1)[-1].strip() if ":" in s else s.strip()
    cur["restricted"] = True
    if re.match(r"^Standard on\b", body, re.I):
        # 'Metallic / Pearl Paint £795, Standard on Calligraphy Black Ink': an extra on every other trim
        names = [t.strip() for t in re.split(r"\s*(?:,|&|\band\b|/)\s*", re.sub(r"^Standard on\s+|\btrims?\b|\bonly\b|\.$", " ", body, flags=re.I)) if t.strip()]
        cur["trims"] = [t for t in trims if not any(_same(t, n) for n in names)]
        return
    if re.fullmatch(r"all(\s+trims?)?\.?", body, re.I):
        cur["trims"] = sorted(set(cur["trims"]) | set(trims), key=trims.index) if trims else cur["trims"]
        return
    negative = bool(re.match(r"^Not available (on|for)\b", body, re.I))
    body = re.sub(r"^(?:Not available|(?:Only\s+)?Available)\s+(?:on|for)\s+|\btrims?\b|\bonly\b|\(MY\d\d\)|\bMY\d\d\b|\.$", " ", body, flags=re.I)
    names = [t.strip() for t in re.split(r"\s*(?:,|&|\band\b|/)\s*", body) if t.strip()]
    known = [t for t in trims if any(_same(t, n) for n in names)]
    if negative:
        cur["trims"] = [t for t in trims if t not in known]
        return
    cur["trims"] = sorted(set(cur["trims"]) | set(known or names), key=lambda t: trims.index(t) if t in trims else len(trims))


# ---------------------------------------------------------------- rows

def _qualify(label: str, note: str, batteries: list[float]) -> tuple[str, dict | None]:
    """A ● with a battery condition ('49kWh only', 'only standard on the 84kWh battery (N/A on 63kWh)')
    against the trim's batteries: ('standard' | 'none' | 'qualified', {standard_kwh, none_kwh})."""
    na = [float(k) for k in KWH_RE.findall(note.split("N/A")[-1])] if "N/A" in note.upper() else []
    std = [float(k) for k in KWH_RE.findall(note) if float(k) not in na]
    if batteries:
        std_b = [b for b in batteries if b in std]
        none_b = [b for b in batteries if b not in std]
        if not none_b:
            return "standard", None
        if not std_b:
            return "none", None
        return "qualified", {"item": label, "note": note, "standard_kwh": std_b, "none_kwh": none_b}
    return "qualified", {"item": label, "note": note, "standard_kwh": std, "none_kwh": na}


def _via_pack(label: str, pack_items: list[str], pack_flags: set[str]) -> bool:
    """'Surround View Monitor (SVM)' when the Tech Pack lists 'Surround View Monitor'; 'Front Seats - Memory
    Driver Side' when the Zen Pack lists 'Driver Memory Seats' (the same flag)."""
    nl = re.sub(r"[^a-z0-9]", "", label.lower())
    if any(re.sub(r"[^a-z0-9]", "", it.lower()) in nl for it in pack_items if it.strip()):
        return True
    return bool(pack_flags & {k for k, v in flags_for([label]).items() if v == "standard"})


def _powertrains(pricing: dict[str, dict], cells: list[dict], trim: str, seats: int | None, my: int | None) -> list[dict]:
    """The trim's rows of the pricing table (its model year's, where the table prints several; its seat count's),
    each with the Technical pages' numbers for that powertrain and the price table's cells as printed."""
    rs = [r for t, v in pricing.items() if _same(t, trim) for r in v["rows"]]
    if my and any(r["model_year"] == 2000 + my for r in rs):
        rs = [r for r in rs if r["model_year"] in (2000 + my, None)]
    if seats:
        rs = [r for r in rs if r["seats"] == seats] or [r for r in rs if r["seats"] is None]
    out = []
    for r in rs:
        column, numbers, facts = technical_for(cells, r, trim, seats)
        col = next((c["column"] for c in cells if c["column"]["name"] == column), None) if column else None
        drive = (col or {}).get("drive") or r["drive"]
        cells_ = r["cells"]
        numbers = {**numbers, **({"drive": drive} if drive else {}),
                   **({"list_price_gbp": cells_["otr_price_gbp"]} if cells_.get("otr_price_gbp") is not None else {}),
                   **({"insurance_group": cells_["insurance_group"]} if cells_.get("insurance_group") else {})}
        out.append({"label": r["label"], "battery_kwh": r["battery_kwh"], "power_ps": r["power_ps"] or numbers.get("power_ps"),
                    "drive": drive, "seats": r["seats"], "model_year": r["model_year"], "otr_price_gbp": cells_.get("otr_price_gbp"),
                    "price_table": cells_, "technical_column": column, "numbers": numbers, "facts": facts})
    return out


def _common(powertrains: list[dict]) -> dict:
    """The numbers every powertrain of the trim agrees on. Not the battery: the trim's batteries are the price
    table's (65 kWh), which the claim store keys on; the Technical page's 65.4 kWh stays with the powertrain."""
    if not powertrains:
        return {}
    first = powertrains[0]["numbers"]
    return {k: v for k, v in first.items() if k != "battery_kwh" and all(p["numbers"].get(k) == v for p in powertrains[1:])}


def parse_text(txt: str, model: str, model_name: str, url: str, observed_at: str) -> list[dict]:
    columns, footnotes = parse_specs(txt)
    pricing = parse_pricing(txt)
    extras = parse_extras(txt, list(pricing))
    # One row per trim (and seat count): the latest model year's column.
    best: dict[tuple[str, int | None], dict] = {}
    for col in columns.values():
        k = (col["trim"].lower(), col["seats"])
        if k not in best or (col["my"] or 0) > (best[k]["my"] or 0):
            best[k] = col

    def trim_of(col: dict) -> str:
        trim = col["trim"].title() if col["trim"].isupper() else col["trim"]
        return re.sub(r"^(INSTER|IONIQ \d|KONA(?: ELECTRIC)?)\s+", "", trim, flags=re.I).replace("N line", "N Line")

    cells = parse_technical(txt, list(dict.fromkeys([*pricing, *(trim_of(c) for c in best.values())])), model_name)
    rows: list[dict] = []
    for (_, seats), col in best.items():
        trim = trim_of(col)
        batteries = next((v["batteries"] for t, v in pricing.items() if _same(t, trim)), [])
        powertrains = _powertrains(pricing, cells, trim, seats, col["my"])
        packs = [e for e in extras if e["items"] and any(_same(t, trim) for t in e["trims"])]
        offered = [e for e in extras if not e["items"] and any(_same(t, trim) for t in e["trims"])]
        options = [e["name"] for e in offered]
        option_prices = [{"name": e["name"], "price_gbp": e["price"]} for e in offered]
        features, absent, qualified = [], [], []
        for label, value, qual in col["items"]:
            if PACK_ROW_RE.match(label):
                continue   # 'Comfort Pack: Heated Front Seats, ...' is the pack's row; the extras table prices it
            mark = MARK_RE.search(qual)
            note = text(f"{footnotes.get(mark.group(0), '')} {MARK_RE.sub('', qual)}") if mark else qual
            if value == "standard" and KWH_RE.search(note):
                value, q = _qualify(label, note, batteries)
                if q:
                    qualified.append(q)
                    continue
            if value == "none" and ACCESSORY_RE.search(label):
                options.append(label)   # 'Vehicle to Load (Exterior Adaptor) -': not supplied, had as an accessory
                option_prices.append({"name": label, "price_gbp": None})
                continue
            (features if value == "standard" else absent).append(label)
        # The table prints one glyph for standard and for optional. An item a pack offered on this
        # trim bundles is the optional one: not standard, had through the pack.
        pack_items = [it for e in packs for it in e["items"]]
        pack_flags = {k for k, v in flags_for(pack_items).items() if v == "standard"}
        features = [f for f in features if not _via_pack(f, pack_items, pack_flags)]
        seat_label = f"{seats}-seat" if seats else ""
        variant = " ".join(x for x in (model_name, trim, seat_label) if x)
        rows.append({
            "spec_key": f"{SITE}:{model}:{slug(trim)}" + (f":{seats}seat" if seats else ""), "source": "Hyundai UK specification", "source_url": url,
            "observed_at": observed_at, "make": "Hyundai", "model": model_name, "model_slug": model, "trim": trim, "seats": seats,
            "model_year": 2000 + col["my"] if col["my"] else None, "variant": variant, "batteries": batteries,
            "car_ref": {"source": SITE, "key": norm_key("hyundai", model, trim, seat_label), "label": f"Hyundai {variant}"},
            "features": features, "absent": absent, "qualified": qualified, "options": options, "option_prices": option_prices,
            "packs": [{"name": p["name"], "price": p["price"], "items": p["items"]} for p in packs],
            "flags": flags_for(features, options),
            "numbers": {**_common(powertrains), **warranty_numbers(features), **({"seats": seats} if seats else {})},
            "powertrains": powertrains,
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    if not body:
        return
    for row in parse_text(pdf_text(body), target.metadata["model"], target.metadata["model_name"], target.metadata["url"], observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


specs = Capability(name="specs", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="hyundai_specs", default_capability="specs", capabilities={"specs": specs}, live=True)
