"""Provider registry: the source of truth for what `refresh` runs."""
from pipeline.providers import manual_seed
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
