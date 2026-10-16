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


# A derivative name that names a combustion engine: Carwow's pages for some models list their petrol versions beside
# the electric ones (the Focus's '1.0 EcoBoost Hybrid mHEV', the Astra Sports Tourer Electric page's '1.2 Turbo 130'),
# and a range extender ('160kW Hybrid EV 19kWh') carries one too. An engine size counts only before an engine word,
# so '0.9% APR' or 'Turbo S' (a Taycan) is not one.
COMBUSTION_RE = re.compile(r"\b(?:m?hev|phev|hybrid|petrol|diesel|ecoboost|t-?gdi|gdi|crdi|tdi|tsi|tfsi|tce|puretech|bluehdi|skyactiv|vtec|multiair)\b"
                           r"|\b\d\.\d\s*(?:turbo\b|t\b|l\b|litre)", re.I)


def combustion(name: str | None) -> bool:
    return bool(COMBUSTION_RE.search(name or ""))
