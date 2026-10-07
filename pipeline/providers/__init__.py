"""Provider registry: the source of truth for what `refresh` runs, in order.

manual_seed must run first: it writes the cars and the trim map that the other
providers resolve their offers against. carwow_catalog next: the Carwow and
LeaseLoco scrapers discover their pages from the models it writes. Live
providers (live=True) hit the web; `refresh --offline` skips them and replays
data/history instead.
"""
from pipeline.providers import (
    carwow_catalog,
    carwow_deals,
    carwow_paste,
    carwow_specs,
    carwow_used,
    hyundai_offers,
    kia_specs,
    leaseloco,
    manual_seed,
    ncd,
    rrg,
)
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
        carwow_catalog.provider,   # the model list the Carwow + LeaseLoco scrapers discover from
        carwow_specs.provider,     # before deals: a derivative's generated car comes from its spec
        carwow_deals.provider,
        hyundai_offers.provider,
        ncd.provider,
        leaseloco.provider,
        rrg.provider,
        kia_specs.provider,
        carwow_used.provider,      # used stock per model: the 'buy used' route and the residual evidence
    )
}

__all__ = ["PROVIDERS", "Capability", "Context", "Fetched", "ParsedRecord", "Provider", "Target"]
