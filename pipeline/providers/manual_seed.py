"""The default settings (data/seed/requirements.json): the quoting basis and the starting saved searches.

The file's bytes are the artifact and its one record is the requirements document the
snapshot carries; the reader edits their own copy in the browser.
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

FILE = "requirements.json"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    yield Target(identifier=FILE, metadata={"kind": "requirements"})


def fetch(target: Target, ctx: Context) -> Fetched:
    path = ctx.root / "data" / "seed" / FILE
    return Fetched(
        url=path.resolve().as_uri(),
        status_code=200,
        body=path.read_bytes(),
        content_type="application/json",
    )


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    yield ParsedRecord(kind="requirements", key="requirements", row=json.loads(body.decode("utf-8")))


seed = Capability(
    name="seed",
    parser_version="3",
    discover=discover,
    fetch=fetch,
    parse=parse,
    kinds=("requirements",),
)

provider = Provider(
    name="manual_seed",
    default_capability="seed",
    capabilities={"seed": seed},
)
