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
    carwow_model,
    carwow_options,
    carwow_paste,
    carwow_specs,
    carwow_used,
    cinch_used,
    evdb,
    hyundai_offers,
    hyundai_specs,
    kia_specs,
    leaseloco,
    manual_seed,
    motorpoint_used,
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
        carwow_model.provider,     # the derivative registry: every CAP name with its brackets; stubs for what the spec page omits
        carwow_options.provider,   # what each derivative can be ordered with: options and packs, with prices
        carwow_deals.provider,
        hyundai_offers.provider,
        ncd.provider,
        leaseloco.provider,
        rrg.provider,
        kia_specs.provider,       # the makers' own grade tables: what each trim is fitted with, by the maker's word
        hyundai_specs.provider,
        evdb.provider,            # measured numbers per variant; laid over the cars by model and battery at export
        carwow_used.provider,      # used stock per model: the 'buy used' route and the residual evidence
        cinch_used.provider,       # more used stock, with registrations; the snapshot folds the sources
        motorpoint_used.provider,  # nearly-new stock: what a car is worth after a PCP term
    )
}

__all__ = ["PROVIDERS", "Capability", "Context", "Fetched", "ParsedRecord", "Provider", "Target"]
