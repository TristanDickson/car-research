"""The hand-curated seed data (data/seed/*.json) as a provider.

Everything captured by hand goes through the same Bronze → Silver → Gold path as
a scraper would, so provenance and lineage are uniform: the seed file bytes are
the artifact, each JSON entry is a Silver row. Deals in the seed are offer
observations (id = offer key, captured_at = observed_at).
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from pipeline.providers.types import (
    Capability,
    Context,
    Fetched,
    ParsedRecord,
    Provider,
    Target,
)

SEED_FILES = {
    "cars.json": "car",
    "deals.json": "offer",
    "requirements.json": "requirements",
    "trim_map.json": "trim_map",
}
LIST_KEY = {"car": "cars", "offer": "deals", "trim_map": "trim_map"}


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    names = SEED_FILES if target.identifier == "all" else [target.identifier]
    for name in names:
        yield Target(identifier=name, metadata={"kind": SEED_FILES[name]})


def fetch(target: Target, ctx: Context) -> Fetched:
    path = ctx.root / "data" / "seed" / target.identifier
    return Fetched(
        url=path.resolve().as_uri(),
        status_code=200,
        body=path.read_bytes(),
        content_type="application/json",
    )


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    doc = json.loads(body.decode("utf-8"))
    kind = target.metadata.get("kind") or SEED_FILES[target.identifier]
    if kind == "requirements":
        yield ParsedRecord(kind="requirements", key="requirements", row=doc)
        return
    for row in doc[LIST_KEY[kind]]:
        if kind == "offer":
            row = dict(row)
            row.setdefault("offer_key", row["id"])
            row.setdefault("observed_at", row["captured_at"])
            row.setdefault("present", 1)
            yield ParsedRecord(kind="offer", key=row["offer_key"], row=row)
        elif kind == "trim_map":
            yield ParsedRecord(kind="trim_map", key=f'{row["source"]}|{row["source_key"]}', row=row)
        else:
            yield ParsedRecord(kind=kind, key=row["id"], row=row)


seed = Capability(
    name="seed",
    parser_version="2",
    discover=discover,
    fetch=fetch,
    parse=parse,
    kinds=("car", "offer", "requirements", "trim_map"),
)

provider = Provider(
    name="manual_seed",
    default_capability="seed",
    capabilities={"seed": seed},
)
