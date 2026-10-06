"""The hand-curated seed data (data/seed/*.json) as a provider.

Everything captured by hand from the ChatGPT research goes through the same
Bronze → Silver → Gold path as a scraper would, so provenance and lineage are
uniform: the seed file bytes are the artifact, each JSON entry is a Silver row.
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
    "deals.json": "deal",
    "requirements.json": "requirements",
}


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
    for row in doc[kind + "s"]:
        yield ParsedRecord(kind=kind, key=row["id"], row=row)


seed = Capability(
    name="seed",
    parser_version="1",
    discover=discover,
    fetch=fetch,
    parse=parse,
    kinds=("car", "deal", "requirements"),
)

provider = Provider(
    name="manual_seed",
    default_capability="seed",
    capabilities={"seed": seed},
)
