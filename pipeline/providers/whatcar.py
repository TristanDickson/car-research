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

The class articles are re-published in place (the electric ones were last modified in April 2026,
still on the 2025 survey), so each row carries the article's own dates and the build keeps the
newest article that names a model. Only entries still running ('present') are applied to the
catalogue's model, so an old generation's rating never lands on its successor.

Emits 'spec' records keyed whatcar:<article>:<model>:<last year, or present>. Three pages a night.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import norm_key, text
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
        key = f"whatcar:{article}:{norm_key(name)}:{end}"
        return rows.setdefault(key, {
            "spec_key": key, "name": name, "years": f"{start}-{end}", "from_year": start, "to_year": None if end == "present" else int(end),
            "current": end == "present", "list": None, "rank": None, "of": len(table) or None, "numbers": {"reliability_pct": pct},
            "faults": None, "article": text(title.group(1)) if title else article, "published": published, "modified": modified,
            "source_url": url, "observed_at": observed_at})

    for t in table:
        row(t["name"], t["from_year"], t["end"], t["score"])["rank"] = t["rank"]
    for i, h in enumerate(heads):
        chunk = body[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        rating = RATING_RE.search(chunk)
        if not rating:
            continue
        r = row(h.group(2).strip(), int(h.group(3)), h.group(4), float(rating.group(1)))
        r["list"] = next((s for pos, s in reversed(lists) if pos < h.start()), None)
        if not table:   # the overall article: its write-ups' own numbering is the rank
            r["rank"] = int(h.group(1))
        if faults := FAULTS_RE.search(chunk):
            r["faults"] = text(faults.group(1))
    return list(rows.values())


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.identifier, target.metadata.get("url") or "", observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


reliability = Capability(name="reliability", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="whatcar", default_capability="reliability", capabilities={"reliability": reliability}, live=True)
