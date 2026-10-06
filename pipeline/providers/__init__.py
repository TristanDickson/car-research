"""Provider registry: the source of truth for what `refresh` runs, in order.

manual_seed must run first: it writes the cars and the trim map that the other
providers resolve their offers against. Live providers (live=True) hit the web;
`refresh --offline` skips them and replays data/history instead.
"""
from pipeline.providers import carwow_deals, carwow_paste, hyundai_offers, leaseloco, manual_seed, ncd, rrg
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
        carwow_deals.provider,
        hyundai_offers.provider,
        ncd.provider,
        leaseloco.provider,
        rrg.provider,
    )
}

__all__ = ["PROVIDERS", "Capability", "Context", "Fetched", "ParsedRecord", "Provider", "Target"]
