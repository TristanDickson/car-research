"""Provider registry: every source, in the order `scrape` runs the live ones.

manual_seed reads the default settings (data/seed/requirements.json); the build reads
it on every run. carwow_catalog runs first of the live ones: the Carwow and LeaseLoco
scrapers discover their pages from the models it finds. Live providers
(live=True) hit the web and keep every response in the raw store.
"""
from pipeline.providers import (
    carwow_catalog,
    carwow_deals,
    carwow_model,
    carwow_options,
    carwow_specs,
    carwow_used,
    cinch_new,
    cinch_used,
    adac,
    dvsa_recalls,
    evdb,
    evdb_cars,
    hyundai_configurator,
    hyundai_offers,
    hyundai_specs,
    kia_dealers,
    kia_specs,
    leaseloco,
    manual_seed,
    motorpoint_used,
    ncd,
    parkers,
    nhtsa_recalls,
    rrg,
    whatcar,
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
        carwow_catalog.provider,   # the model list the Carwow + LeaseLoco scrapers discover from
        carwow_specs.provider,     # before deals: a derivative's generated car comes from its spec
        carwow_model.provider,     # the derivative registry: every CAP name with its brackets; stubs for what the spec page omits
        carwow_options.provider,   # what each derivative can be ordered with: options and packs, with prices
        carwow_deals.provider,
        hyundai_offers.provider,
        ncd.provider,
        leaseloco.provider,
        rrg.provider,
        cinch_new.provider,
        kia_dealers.provider,      # Kia dealer groups' offer pages: the full worked PCP example each prints, with its own contribution        # cinch's new cars: a real PCP quote and a cash price for every electric car it stocks
        kia_specs.provider,       # the makers' own grade tables: what each trim is fitted with, by the maker's word
        hyundai_specs.provider,
        hyundai_configurator.provider,   # what the maker will actually build at what price: the strongest word on what is fitted
        evdb.provider,            # measured numbers per variant; laid over the cars by model and battery at export
        evdb_cars.provider,       # each variant's own page: dimensions, weights, charging, V2L outlets, NCAP (a batch a night)
        parkers.provider,         # every generation's trims and derivatives with their on-sale dates, old ones included (a batch a night)
        adac.provider,            # ADAC's test of each model (ride, build quality, space) and its breakdown statistics (a batch a night)
        whatcar.provider,         # What Car?'s owner reliability survey, per model
        dvsa_recalls.provider,    # every UK safety recall, laid over the models by the build (Chrome downloads the file)
        nhtsa_recalls.provider,   # every US safety recall (NHTSA), laid over the models sold there by the build
        carwow_used.provider,      # used stock per model: the 'buy used' route and the residual evidence
        cinch_used.provider,       # more used stock, with registrations; the snapshot folds the sources
        motorpoint_used.provider,  # nearly-new stock: what a car is worth after a PCP term
    )
}

__all__ = ["PROVIDERS", "Capability", "Context", "Fetched", "ParsedRecord", "Provider", "Target"]
