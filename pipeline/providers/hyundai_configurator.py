"""Hyundai UK's car configurator: what the maker will actually build, at what price.

The build-and-price page per model (hyundai.com/uk/en/models/<model>/configurator.html)
is a web app over a GraphQL endpoint that needs no credentials. One query per model
returns every orderable configuration, Hyundai's FSC: its trim, powertrain, price, and
the packages that price includes (name, price, a description of what they bundle), plus
each trim's standard-equipment list. The packages offered on a trim and powertrain are
the union over its configurations.

This is the strongest word on what is fitted: a package in the price is fitted, a
package offered on the trim but not in the price is an extra, and a package the model
sells somewhere but neither lists nor offers here is not available. The claim store
(services/claims.py) matches each configuration to a CAP derivative by trim, battery
and price and reads it at the 'configured' rank.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "hyundai-cfg"
PAPI = "https://org-eu-www.hyundai.com/eu/papi"
# carwow model slug → (hyundai site slug, model name as Carwow prints it)
MODELS = {
    "inster": ("inster", "Inster"), "ioniq-5": ("ioniq5", "Ioniq 5"), "ioniq-6": ("ioniq6", "Ioniq 6"),
    "ioniq-9": ("ioniq9", "Ioniq 9"), "kona-electric": ("kona-electric", "Kona Electric"),
}
MODEL_ID_RE = re.compile(r'"modelId"\s*:\s*"([^"]+)"')
KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
PS_RE = re.compile(r"(\d+)\s*PS\b", re.I)
SEATS_RE = re.compile(r"(\d)\s*Seat", re.I)
QUERY = """query Trims($country: TrimmedString!, $language: TrimmedString!, $modelId: TrimmedString!, $service: TrimmedString!) {
  hppTrimEquipments(country: $country, language: $language, modelId: $modelId, service: $service) {
    trimId equipNm: equipmentDescription highlight equipCategory: category1 sortNo longDescription
  }
  hppFscs2(country: $country, language: $language, modelId: $modelId, service: $service) {
    fsc modelId: modelCd bodyTypeNo: bodytype trimId trimNm powertrainId trimSort modelNm productYear bodytypeNm powertrainNm
    packages { pkgNm pkgPrice pkgNetPrice }
    pkg1Cd pkg1Nm pkg1Price pkg1Description pkg2Cd pkg2Nm pkg2Price pkg2Description pkg3Cd pkg3Nm pkg3Price pkg3Description
    pkg4Cd pkg4Nm pkg4Price pkg4Description pkg5Cd pkg5Nm pkg5Price pkg5Description
    fscPrice fscPrice2 discount1Price discount2Price discount3Price
  }
}"""


def page_url(hy_slug: str) -> str:
    return f"https://www.hyundai.com/uk/en/models/{hy_slug}/configurator.html"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for model, (hy, name) in MODELS.items():
        if target.identifier in ("all", model):
            yield Target(identifier=model, metadata={"model": model, "model_name": name, "url": page_url(hy)})


def fetch(target: Target, ctx: Context) -> Fetched:
    """The configurator page names the model id; the Trims query returns everything else.
    The artifact is both: the page url, the id, and the query's JSON."""
    page = fetch_url(target.metadata["url"], ctx)
    m = MODEL_ID_RE.search(page.body.decode("utf-8", "replace"))
    if not m:
        return Fetched(url=target.metadata["url"], status_code=404, body=b"", content_type="text/html")
    body = json.dumps({"query": QUERY, "variables": {"country": "uk", "language": "en", "modelId": m.group(1), "service": "S03"}}).encode()
    res = fetch_url(PAPI, ctx, data=body, accept="application/json",
                    headers={"Content-Type": "application/json", "Referer": "https://www.hyundai.com/", "Origin": "https://www.hyundai.com"})
    out = {"page": target.metadata["url"], "modelId": m.group(1), "response": json.loads(res.body.decode("utf-8", "replace"))}
    return Fetched(url=target.metadata["url"], status_code=res.status_code, body=json.dumps(out, ensure_ascii=False).encode(), content_type="application/json")


# ---------------------------------------------------------------- rows

def trim_name(t: str) -> str:
    """'CROSS' → 'Cross', 'N LINE S' → 'N Line S'; '01', 'Calligraphy Black Ink' as printed."""
    t = (t or "").strip()
    return t.title() if t.isupper() and not t.isdigit() else t


def pack_items(name: str, description: str | None) -> list[str]:
    """What a package bundles, as short clauses the flag patterns can read: its name, then the
    description split at 'and' / commas, with 'excluding …' brackets dropped so an exclusion is
    not read as an inclusion ('V2L with internal 3-pin plug … (excluding external adaptor)')."""
    items = [name.strip()]
    d = text(description or "").replace("\xa0", " ")
    d = re.sub(r"\((?:excluding|not including|without|available from)[^)]*\)", " ", d, flags=re.I)
    d = re.sub(r"\b(?:excluding|except(?:ing)?|not including)\b[^.;,]*", " ", d, flags=re.I)
    for sentence in re.split(r"(?<=[.;])\s+", d):
        for clause in re.split(r",\s+|\s+and\s+(?=[A-Z])", sentence):
            c = clause.strip(" .")
            if len(c) > 3 and not re.match(r"^(convenience aid|not intended|which can|allows)", c, re.I):
                items.append(c)
    return items


def _packages(f: dict) -> list[dict]:
    """The packages in a configuration's price, with descriptions from the numbered fields."""
    desc = {}
    for i in range(1, 6):
        if f.get(f"pkg{i}Nm"):
            desc[f[f"pkg{i}Nm"]] = {"code": f.get(f"pkg{i}Cd"), "description": f.get(f"pkg{i}Description")}
    out = []
    for p in f.get("packages") or []:
        name = (p.get("pkgNm") or "").strip()
        if not name:
            continue
        d = desc.get(name) or {}
        out.append({"name": name, "code": d.get("code"), "price": float(p["pkgPrice"]) if p.get("pkgPrice") is not None else None,
                    "description": d.get("description"), "items": pack_items(name, d.get("description"))})
    return out


def parse_payload(d: dict, model: str, model_name: str, observed_at: str) -> list[dict]:
    data = (d.get("response") or {}).get("data") or {}
    equipment: dict[str, list[str]] = {}
    for e in data.get("hppTrimEquipments") or []:
        if e.get("equipNm"):
            equipment.setdefault(e["trimId"], []).append(text(e["equipNm"]))
    fscs = data.get("hppFscs2") or []
    rows: list[dict] = []
    for f in fscs:
        pt = f.get("powertrainNm") or ""
        kwh = KWH_RE.search(pt)
        ps = PS_RE.search(pt)
        seats = SEATS_RE.search(f.get("bodytypeNm") or "")
        drive = re.search(r"\b(AWD|RWD|FWD)\b", pt)
        rows.append({
            "fsc": f["fsc"], "make": "Hyundai", "make_slug": "hyundai", "model": model_name, "model_slug": model,
            "trim": trim_name(f.get("trimNm")), "trim_id": f.get("trimId"), "powertrain": pt, "powertrain_id": f.get("powertrainId"),
            "battery_kwh": float(kwh.group(1)) if kwh else None, "power_ps": int(ps.group(1)) if ps else None,
            "drive": drive.group(1) if drive else None, "seats": int(seats.group(1)) if seats else None,
            "body_type": f.get("bodyTypeNo"), "product_year": f.get("productYear"),
            "price": float(f["fscPrice"]) if f.get("fscPrice") is not None else None, "price_ex_vat": f.get("fscPrice2"),
            "packages": _packages(f), "equipment": equipment.get(f.get("trimId"), []),
            "source": "Hyundai UK configurator", "source_url": d.get("page"), "observed_at": observed_at,
        })
    # What each trim and powertrain can be ordered with: every package any of its configurations includes.
    offered: dict[tuple, dict[str, dict]] = {}
    for r in rows:
        group = offered.setdefault((r["trim_id"], r["powertrain_id"]), {})
        for p in r["packages"]:
            group.setdefault(p["name"], {"name": p["name"], "price": p["price"], "items": p["items"]})
    for r in rows:
        r["offered"] = sorted(offered[(r["trim_id"], r["powertrain_id"])].values(), key=lambda p: p["name"])
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    if not body:
        return
    d = json.loads(body.decode("utf-8", "replace"))
    for row in parse_payload(d, target.metadata["model"], target.metadata["model_name"], observed_at_for(target)):
        yield ParsedRecord(kind="configuration", key=f"{SITE}:{row['fsc']}", row=row)


configurations = Capability(name="configurations", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("configuration",))
provider = Provider(name="hyundai_configurator", default_capability="configurations", capabilities={"configurations": configurations}, live=True)
