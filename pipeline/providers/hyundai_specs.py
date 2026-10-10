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
provider: features (●), absent (-), qualified items, batteries, packs. The
claim store (services/claims.py) reads them as the maker's claims.
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


def parse_pricing(txt: str) -> dict[str, dict]:
    """trim words → {batteries: [kWh], prices: {kWh: on-the-road £}} from the pricing table.

    A row is a trim line ('01 42kWh', 'Advance 63 kWh 170PS') and, within a few lines, the money
    line; pdftotext wraps 'Battery / Electric' and 'RWD' around them, so the head is gathered
    from the lines near the money and cut back to the words before the first kWh / PS token.
    Where the trim is printed once beside several powertrain rows ('Premium' between
    '77.4 KWh 228PS RWD' and '77.4 KWh 325PS AWD') the nearest such line names the row."""
    out: dict[str, dict] = {}
    lines = [l.strip() for l in txt.split("\n")]
    on = False
    pending: list[str] = []
    for i, s in enumerate(lines):
        if re.match(r"^Pricing\b", s):
            on = True
            pending = []
            continue
        if not on:
            continue
        if s.startswith("OPTIONAL EXTRAS") or s.startswith("Features and options may vary"):
            on = False
            continue
        amounts = [money(m) for m in MONEY_RE.findall(s)]
        if len(amounts) >= 3 and max(a for a in amounts if a) >= 5000:
            head = text(" ".join(pending + [re.split(r"\s{2,}", s)[0]]))
            head = re.sub(r"\(MY\d\d\)|\bMY\d\d\b|battery electric|battery|electric|\bBEV\b", " ", head, flags=re.I)
            kwh = KWH_RE.search(head)
            cut = re.search(r"\d+(?:\.\d+)?\s*kwh|\d+\s*ps\b|\d+\s*kw\b", head, re.I)
            trim = head[: cut.start()] if cut else head
            trim = re.sub(r"\brwd\b|\bawd\b|\bfwd\b|\(.*?\)|(?<![\w£.,])0(?![\w.,])|\d\s*seats?", " ", trim, flags=re.I)
            trim = re.sub(r"\s+", " ", trim).strip()
            if not trim:
                near = [(abs(j - i), j) for j in range(max(0, i - 4), min(len(lines), i + 5)) if j != i and _trim_only(lines[j])]
                trim = lines[min(near)[1]] if near else ""
            if trim and not re.search(r"^trim$|fuel type", trim, re.I):
                trim = next((k for k in out if _same(k, trim)), trim)
                row = out.setdefault(trim, {"batteries": [], "prices": {}})
                if kwh:
                    k = float(kwh.group(1))
                    if k not in row["batteries"]:
                        row["batteries"].append(k)
                    row["prices"][str(k)] = max(a for a in amounts if a)
            pending = []
        elif s and PRICING_NOISE_RE.search(s):
            continue
        elif s and not PRICING_HEADER_RE.search(s):
            pending.append(s)
        elif s:
            pending = []
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
    rows: list[dict] = []
    for (_, seats), col in best.items():
        trim = col["trim"].title() if col["trim"].isupper() else col["trim"]
        trim = re.sub(r"^(INSTER|IONIQ \d|KONA(?: ELECTRIC)?)\s+", "", trim, flags=re.I).replace("N line", "N Line")
        batteries = next((v["batteries"] for t, v in pricing.items() if _same(t, trim)), [])
        packs = [e for e in extras if e["items"] and any(_same(t, trim) for t in e["trims"])]
        options = [e["name"] for e in extras if not e["items"] and any(_same(t, trim) for t in e["trims"])]
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
            "features": features, "absent": absent, "qualified": qualified, "options": options,
            "packs": [{"name": p["name"], "price": p["price"], "items": p["items"]} for p in packs],
            "flags": flags_for(features, options), "numbers": {"seats": seats} if seats else {},
        })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    if not body:
        return
    for row in parse_text(pdf_text(body), target.metadata["model"], target.metadata["model_name"], target.metadata["url"], observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


specs = Capability(name="specs", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="hyundai_specs", default_capability="specs", capabilities={"specs": specs}, live=True)
