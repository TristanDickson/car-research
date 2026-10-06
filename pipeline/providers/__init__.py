"""Provider registry: the source of truth for what `refresh` runs, in order.

manual_seed must run first: it writes the cars and the trim map that the other
providers resolve their offers against.
"""
from pipeline.providers import carwow_paste, manual_seed
from pipeline.providers.types import (
    Capability,
    Context,
    Fetched,
    ParsedRecord,
    Provider,
    Target,
)

PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (
        manual_seed.provider,
        carwow_paste.provider,
    )
}

__all__ = [
    "PROVIDERS",
    "Capability",
    "Context",
    "Fetched",
    "ParsedRecord",
    "Provider",
    "Target",
]
