"""Provider + Capability records (the etf-tool shape, synchronous and smaller).

A Provider is a named bag of Capabilities; a Capability is a named bag of plain
functions: discover (what to fetch), fetch (get bytes), parse (bytes → records).
No classes with methods, no inheritance: compose middleware at construction.

The runner stores every fetched body as a Bronze artifact, every parsed record as
a Silver row, then replaces the provider's Gold rows for the kinds the capability
emits. A capability that emits both cars and deals must emit them in one run so
the FK from deals to cars is satisfied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator


@dataclass(frozen=True)
class Target:
    """A unit of work: 'all' or one specific id / URL / file."""

    identifier: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Context:
    """Per-run knobs handed to discover / fetch / parse."""

    root: Path
    delay_seconds: float = 1.5
    max_targets: int | None = None
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Fetched:
    url: str
    status_code: int
    body: bytes
    content_type: str | None = None
    headers: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedRecord:
    kind: str   # car | deal | requirements
    key: str    # stable id within the source
    row: dict


DiscoverFn = Callable[[Target, Context], Iterator[Target]]
FetchFn = Callable[[Target, Context], Fetched]
ParseFn = Callable[[bytes, Target], Iterator[ParsedRecord]]


@dataclass(frozen=True)
class Capability:
    name: str
    parser_version: str
    discover: DiscoverFn
    fetch: FetchFn
    parse: ParseFn
    kinds: tuple[str, ...]   # record kinds this capability emits (Gold rows replaced per run)


@dataclass(frozen=True)
class Provider:
    name: str
    default_capability: str
    capabilities: dict[str, Capability]
    # live providers fetch the web; CI replays history with --offline and skips them.
    live: bool = False

    def capability_for(self, name: str | None) -> Capability:
        if name is None:
            name = self.default_capability
        try:
            return self.capabilities[name]
        except KeyError:
            raise ValueError(
                f"Provider {self.name!r} has no capability {name!r}. "
                f"Available: {sorted(self.capabilities)}"
            ) from None
