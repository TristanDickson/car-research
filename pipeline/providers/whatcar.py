"""What Car? Reliability Survey: owners' reports of the faults their cars (up to five years old) had,
rated as a percentage.

What Car? publishes the survey as articles: one per class (electric cars n26158, electric SUVs
n26161), and one for each year's edition overall (n27337, the 2026 survey, published 22 Sep 2026).
Every rating is in the page's HTML; the page repeats the article in a script, which is not read. A
class article writes up its ten most and ten least reliable models, each entry naming the model and
the years it covers ('2. Hyundai Ioniq 5 (2021-present)'), then 'Reliability rating 80.7%' and
'Most common faults: ...', and ends with a table ranking every model in the class (19 electric cars,
27 electric SUVs: 'Rank | Make and model | Score', the years before the name for a model no longer
sold). The overall article has the write-ups only, of its top 20 and bottom 10. Per-car lookups by
registration need a login and are not read; nor are the other classes' articles, which rate few
electric cars.

A write-up also prints 'Average repair cost: 90% £0, 5% £1-£100, ...' and 'Typical time off road:
56% more than a week, ...', read as the share of repairs that cost the owner nothing and the share
of faulty cars off the road for more than a week. The share of cars that had a fault is only in the
prose ('Overall, 42% of Ioniq 5s went wrong, compared with 30% of EV6s'; 'Thirty-six percent of
ID 4 owners had gripes, compared with 30% of people with Enyaqs'): a sentence that says cars went
wrong or had a fault gives its first share of the cars or owners in general, or of the entry's own
model, to the entry, and a share of another model of the article to that model when it has none of
its own. A share of faulty cars ('56% of faulty Ioniq 5s off the road') is not one. The sentence is
kept with the row.

The class articles are re-published in place (the electric ones were last modified in April 2026,
still on the 2025 survey), so each row carries the article's own dates and the build keeps the
newest article that names a model. Only entries still running ('present') are applied to the
catalogue's model, so an old generation's rating never lands on its successor.

Emits 'spec' records keyed whatcar:<article>:<model>:<last year, or present>. Three pages a night.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline import normalise
from pipeline.providers.http import fetch_url
from pipeline.providers.parse import text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "whatcar"
ARTICLES = {
    "electric-cars": "https://www.whatcar.com/news/reliability-survey-most-reliable-electric-cars/n26158",
    "electric-suvs": "https://www.whatcar.com/news/reliability-survey-most-reliable-electric-suvs/n26161",
    "overall": "https://www.whatcar.com/news/most-reliable-cars/n27337",
}
HEAD_RE = re.compile(r"^\s*=?(\d{1,2})\.\s+(.+?)\s+\((\d{4})\s*[-–]\s*(present|\d{4})\)\s*$", re.M)   # '=1.' is a tie
# A list's heading, a short line: 'Most reliable electric cars', 'Least reliable electric SUVs', 'The 10 most unreliable cars'.
LIST_RE = re.compile(r"^(?=[^\n]{0,60}$)[^\n]*\b(most|least) (un)?reliable\b[^\n]*$", re.M | re.I)
RATING_RE = re.compile(r"Reliability rating\s+(\d+(?:\.\d+)?)\s*%")
FAULTS_RE = re.compile(r"Most common faults:\s*([^\n]+)")
LABELS = ("Reliability rating", "Most common faults:", "Average repair cost:", "Typical time off road:", "Time off road:")
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                                     "seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
WORD_PCT_RE = re.compile(r"\b(" + "|".join(TENS) + r")(?:[- ](" + "|".join(list(UNITS)[1:10]) + r"))?\s+per\s?cent\b|\b(" + "|".join(UNITS) + r")\s+per\s?cent\b", re.I)
FAULT_VERB_RE = re.compile(r"went wrong|had (?:at least one |a |an |any |some )?(?:issue|problem|fault|defect|gripe)s?\b|suffer(?:ed|ing)? (?:any|some sort of|at least one|a)\b"
                           r"|reported (?:at least one|a|any) (?:issue|fault|problem)", re.I)
SHARE_RE = re.compile(r"\(?(\d+)%\)? (of|with) (?:the |their |participating )?((?:people with |owners of )?[A-Za-z0-9][\w\-]*(?: (?!\d+%)[A-Za-z0-9][\w\-]*){0,4})")
GENERIC = ("cars", "car", "models", "owners", "people", "vehicles", "respondents", "examples")
OWN_RATE_RE = re.compile(r"(?:\b[Ii]ts|'s) (\d+)% fault rate|\b[Ii]ts fault rate of (?:just |only )?(\d+)%")


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for name, url in ARTICLES.items():
        if target.identifier in ("all", name):
            yield Target(identifier=name, metadata={"url": url})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def page_text(page: str) -> str:
    """The article as lines of text: scripts and styles dropped, every tag a line break."""
    page = re.sub(r"<(script|style)\b.*?</\1>", "", page, flags=re.S | re.I)
    lines = (text(s) for s in re.split(r"<[^>]+>", page))
    return "\n".join(s for s in lines if s)


def _date(page: str, key: str) -> str | None:
    m = re.search(rf'"{key}"\s*:\s*"(\d{{4}}-\d{{2}}-\d{{2}})', page)
    return m.group(1) if m else None


NAME_YEARS_RE = re.compile(r"^(?:(\d{4})\s*[-–]\s*(\d{4})\s+)?(.+?)(?:\s*\((\d{4})\s*[-–]\s*(present|\d{4})\))?$")


def ranking(page: str) -> list[dict]:
    """A class article's closing table, every model of the class: rank, name, years, score."""
    out = []
    for t in re.findall(r"<table\b.*?</table>", re.sub(r"<(script|style)\b.*?</\1>", "", page, flags=re.S | re.I), re.S):
        for tr in re.findall(r"<tr\b.*?</tr>", t, re.S):
            cells = [text(c) for c in re.findall(r"<td\b.*?</td>", tr, re.S)]
            if len(cells) != 3 or not cells[0].isdigit() or not (score := re.match(r"(\d+(?:\.\d+)?)\s*%", cells[2])):
                continue
            m = NAME_YEARS_RE.match(cells[1])
            start, end = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(5))
            if not start:
                continue
            out.append({"rank": int(cells[0]), "name": m.group(3).strip(), "from_year": int(start), "end": end, "score": float(score.group(1))})
    return out


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalise.fold(s))


def _model_words(name: str) -> list[str]:
    """The model part of an entry's name, the make's first word off: 'Hyundai Ioniq 5' → ioniq, 5."""
    return _words(name)[1:] or _words(name)


def _is(phrase: str, name: str) -> bool:
    """Does a phrase ('Ioniq 5s went', 'MG ZS EV owners', 'Niro hybrid and plug-in') start with this model's words?"""
    p, m = _words(phrase), _model_words(name)
    for cand in (m, _words(name)):
        n = 0
        while n < min(len(p), len(cand)) and p[n] in (cand[n], cand[n] + "s"):   # 'Ioniq 5s', 'EQAs', 'Corsa Electrics'
            n += 1
        if n == len(cand) or n >= 2:
            return True
    return False


def _prose(chunk: str) -> str:
    """An entry's write-up after its figures, as sentences, with spelled shares as numbers ('Thirty-six percent' → 36%)."""
    lines = chunk.split("\n")
    last = max((i for i, l in enumerate(lines) if l.startswith(LABELS)), default=-1)
    text = " ".join(lines[last + 2:] if last >= 0 else lines)

    def num(m: re.Match) -> str:
        if m.group(3):
            return f"{UNITS[m.group(3).lower()]}%"
        return f"{TENS[m.group(1).lower()] + (UNITS[m.group(2).lower()] if m.group(2) else 0)}%"
    text = WORD_PCT_RE.sub(num, text)
    return re.sub(r"(\d+) ?per ?cent\b", r"\1%", text)


def _figures(chunk: str, label: str) -> str | None:
    """A figure's value, which the page may split over several lines, up to the next label or the write-up."""
    lines = chunk.split("\n")
    for i, l in enumerate(lines):
        if l.startswith(label):
            out = [l[len(label):].strip()]
            for nxt in lines[i + 1:i + 4]:
                if nxt.startswith(LABELS) or len(nxt) > 60:
                    break
                out.append(nxt)
            return " ".join(x for x in out if x).strip() or None
    return None


def repairs_free(chunk: str) -> float | None:
    """The share of repairs that cost the owner nothing: '90% £0, 5% £1-£100' → 90; '£0' → 100."""
    v = _figures(chunk, "Average repair cost:")
    if not v or v.lower() in ("n/a", "na"):
        return None
    m = re.search(r"(\d+)%\s*(?:cost\s*)?(?:£0\b|fixed for free)", v)
    if m:
        return float(m.group(1))
    return 100.0 if re.fullmatch(r"(?:100%\s*)?(?:cost\s*)?£0", v.strip()) else None


def off_road_week(chunk: str) -> float | None:
    """The share of faulty cars off the road for more than a week; 0 when the shares printed cover every car without it."""
    v = _figures(chunk, "Typical time off road:") or _figures(chunk, "Time off road:")
    if not v or v.lower() in ("n/a", "na"):
        return None
    m = re.search(r"(\d+)% more than a week", v)
    if m:
        return float(m.group(1))
    return 0.0 if sum(int(x) for x in re.findall(r"(\d+)%", v)) >= 99 else None


def fault_shares(prose: str, name: str, others: list[str]) -> tuple[tuple[float, str] | None, dict[str, tuple[float, str]]]:
    """(the entry's own share of cars with a fault and the sentence, {another entry: its share and the sentence})."""
    own: tuple[float, str] | None = None
    theirs: dict[str, tuple[float, str]] = {}
    if re.search(r"\bno (?:participating )?owners? report(?:ed|ing)? (?:a single|any) fault", prose, re.I):
        own = (0.0, "no owner reported a fault")
    for sentence in re.split(r"(?<=[.!?])\s+", prose):
        if not FAULT_VERB_RE.search(sentence) and "fault rate" not in sentence:
            continue
        if own is None and (m := OWN_RATE_RE.search(sentence)):
            own = (float(m.group(1) or m.group(2)), sentence.strip())
        for m in SHARE_RE.finditer(sentence):
            phrase = m.group(3)
            if phrase.lower().startswith("faulty"):
                continue
            target = re.sub(r"^(?:people with|owners of) ", "", phrase, flags=re.I)
            if _words(target)[:1] and _words(target)[0] in GENERIC or _is(target, name):
                if own is None and m.group(2) == "of":
                    own = (float(m.group(1)), sentence.strip())
            else:
                for o in others:
                    if o != name and _is(target, o) and o not in theirs:
                        theirs[o] = (float(m.group(1)), sentence.strip())
    return own, theirs


def parse_page(page: str, article: str, url: str, observed_at: str) -> list[dict]:
    """One row per rated model: from a class article's table (rank among every model of the class) and its
    write-ups (the list it sits in and the common faults), from the overall article's write-ups alone."""
    body = page_text(page)
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    lists = [(m.start(), "least" if m.group(1).lower() == "least" or m.group(2) else "most") for m in LIST_RE.finditer(body)]
    heads = list(HEAD_RE.finditer(body))
    published, modified = _date(page, "datePublished"), _date(page, "dateModified")
    table = ranking(page)
    rows: dict[str, dict] = {}

    def row(name: str, start: int, end: str, pct: float) -> dict:
        # One row per model and generation: a table and a write-up may differ on the first year (Model Y 2021, 2022).
        key = f"whatcar:{article}:{normalise.key(name)}:{end}"
        return rows.setdefault(key, {
            "spec_key": key, "name": name, "years": f"{start}-{end}", "from_year": start, "to_year": None if end == "present" else int(end),
            "current": end == "present", "list": None, "rank": None, "of": len(table) or None, "numbers": {"reliability_pct": pct},
            "faults": None, "article": text(title.group(1)) if title else article, "published": published, "modified": modified,
            "source_url": url, "observed_at": observed_at})

    for t in table:
        row(t["name"], t["from_year"], t["end"], t["score"])["rank"] = t["rank"]
    names = sorted({t["name"] for t in table} | {h.group(2).strip() for h in heads}, key=len, reverse=True)
    mentioned: dict[str, tuple[float, str]] = {}
    for i, h in enumerate(heads):
        chunk = body[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        rating = RATING_RE.search(chunk)
        if not rating:
            continue
        name = h.group(2).strip()
        r = row(name, int(h.group(3)), h.group(4), float(rating.group(1)))
        r["list"] = next((s for pos, s in reversed(lists) if pos < h.start()), None)
        if not table:   # the overall article: its write-ups' own numbering is the rank
            r["rank"] = int(h.group(1))
        if faults := FAULTS_RE.search(chunk):
            r["faults"] = text(faults.group(1))
        for key, value in (("repairs_free_pct", repairs_free(chunk)), ("off_road_week_pct", off_road_week(chunk))):
            if value is not None:
                r["numbers"][key] = value
        own, theirs = fault_shares(_prose(chunk), name, names)
        if own:
            r["numbers"]["faulty_pct"], r["faulty_said"] = own
        for other, said in theirs.items():
            mentioned.setdefault(other, said)
    for r in rows.values():   # a model the write-ups name only in passing ('compared with 30% of people with Enyaqs')
        if "faulty_pct" not in r["numbers"] and r["current"] and r["name"] in mentioned:
            r["numbers"]["faulty_pct"], r["faulty_said"] = mentioned[r["name"]]
    return list(rows.values())


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.identifier, target.metadata.get("url") or "", observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


reliability = Capability(name="reliability", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="whatcar", default_capability="reliability", capabilities={"reliability": reliability}, live=True)
