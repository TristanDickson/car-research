"""Small text helpers shared by the page parsers."""
from __future__ import annotations

import html
import re

MONEY = re.compile(r"£\s*([\d,]+(?:\.\d+)?)")


def money(s: str | None) -> float | None:
    m = MONEY.search(s or "")
    return float(m.group(1).replace(",", "")) if m else None


def pct(s: str | None) -> float | None:
    m = re.search(r"([\d.]+)\s*%", s or "")
    return float(m.group(1)) / 100 if m else None


def number(s: str | None) -> float | None:
    m = re.search(r"-?([\d,]+(?:\.\d+)?)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def text(fragment: str) -> str:
    """Tags out, entities decoded, whitespace collapsed."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragment, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def norm_key(*parts: str) -> str:
    """Trim-map key: lower-case, 'kwh' glued to its number, single spaces, parts joined by |."""
    out = []
    for p in parts:
        p = re.sub(r"\s*kwh", "kwh", (p or "").lower())
        out.append(re.sub(r"\s+", " ", p).strip())
    return "|".join(out)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
