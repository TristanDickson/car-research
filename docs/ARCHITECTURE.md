# Architecture

The design is the owner's, as in their other project bolthole (`docs/REBUILD.md`): **only
the raw responses are permanent.** Every page fetched is kept, exactly as it came, in a raw
store outside git on the owner's laptop. Parsing, matching ("which records are the same
car") and everything the app reads are derived from those raws by a build that runs from
scratch every time, so a better parser or a better matcher fixes the past as well as the
future. The only other durable things are the owner's own files and decisions, in git.

```
providers (discover → fetch → parse)       pipeline/providers/*      Python, stdlib
   manual_seed     data/seed/*.json          the owner's cars, offers, requirements, decisions (read by every build)
   carwow_paste    data/pastes/carwow/*.txt  Carwow offer pages copied out of a logged-in browser (read by every build)
   carwow_catalog  carwow.co.uk (live)       the catalogue: every electric model, from the sitemaps + <make>/electric pages
   carwow_specs    carwow.co.uk (live)       equipment per trim, numbers per engine, CAP ids + version dates, images
   carwow_model    carwow.co.uk (live)       the derivative registry: every derivative by CAP name, brackets included
   carwow_options  quotes.carwow.co.uk       each derivative's configurator: options and packs with prices
   carwow_deals    carwow.co.uk (live)       best cash price per CAP derivative, Kia PCP-finance price, rep. example
   hyundai_offers  hyundai.com/uk (live)     Hyundai Finance national PCP example per model, with validity dates
   ncd             new-car-discount.com      broker all-in cash price per derivative
   leaseloco       leaseloco.com (live)      best personal lease per derivative/profile (ex-VAT → inc.)
   rrg             rrg-group.com (live)      dealer PCP example for the PV5 7-seat
   kia_specs       kia.com/uk (live)         grade × feature ticks, numbers per powertrain, seat variants
   hyundai_specs   hyundai.com/uk (live)     the Tech & Spec guide PDF per model: ● / - per trim, battery-qualified ticks, packs with prices
   hyundai_configurator  hyundai.com/uk (live)  the build-and-price GraphQL: every orderable configuration, its price, the packages in it
   evdb, evdb_cars ev-database.org (live)    measured numbers per variant; each variant's own page
   carwow_used     quotes.carwow.co.uk        used stock per model: derivative, price, year, mileage (the buy-used route; residual evidence)
   cinch_used      search-api...cinch.co.uk   used stock per make (electric), with registrations; folded with the others per model
   motorpoint_used motorpoint.co.uk           the supermarket's electric stock, nearly new; list price when new per car
        │  scrape (pipeline/runner.py): fetch and keep, nothing else
        ▼
RAW STORE  $CAR_RESEARCH_RAW (D:\car-research-raw)   on the owner's laptop, outside git, never rewritten
        │  bodies/<sha[:2]>/<sha256>.gz   one per distinct body       index/<YYYY-MM>.jsonl  one line per fetch
        │  logs/                          runs, the backfill's finished pages, each night's job log
        │  plus the legacy source: every committed version of the old data/history (pipeline/legacy.py)
        │
        │  build (pipeline/build.py), from scratch every run, into a disposable SQLite database:
        │    1 parse every stored page with its provider's parser (cached by fetch and code version)
        │      and write what each source said (gold.py): models, specs, registry, options,
        │      configurations, used stock; every price becomes a sighting
        │    2 derivatives: one per CAP id any record names; the owner's entry stands for its own
        │    3 match every record at once (services/resolve.py, services/match.py); the owner's
        │      decisions (data/seed/trim_map.json) override
        │    4 fold each offer's sightings into spans of an unchanged price
        ▼  export_snapshot()                 pipeline/services/snapshot.py, services/claims.py
JSON    web/public/data/*.json               COMMITTED on main by the laptop's nightly job
        ▼  push to main → Actions → next build (output: export) → Pages
SPA     web/                                 Next.js 16 App Router, Tailwind 4, react-query, Dexie
        │  first load: download the snapshot into IndexedDB; after that read it from there,
        │  no network, and fetch a newer cut in the background (a service worker keeps the app)
        ▼  pages query IndexedDB (public tables) + the reader's saved searches and settings
```

The database (`data/car-research.sqlite`, gitignored) holds nothing that is not derived: delete
it and `python -m pipeline build` makes it again. Its tables keep the names they had before the
rebuild (`cars`, `trim_map`, `offer_observations`, `specs`, `used_listings`, …), so the snapshot
exporter and the claim store read them as before.

## Offers are observations

An offer is never edited in place. Each page fetched says what it showed: one **sighting** per
**offer key** per fetch, with `present = 0` when a check found the offer gone. The offer key is
stable per real-world offer (a Carwow deal id, a seed id, a dealer URL plus trim). The build
sorts every sighting of a key by date and folds them into spans: consecutive sightings with the
same price-bearing fields are one span, a different price starts a new one, a `gone` sighting is
never merged. The order pages were read in changes nothing, so a Wayback capture from 2025 or
a legacy row folds in wherever it falls. At one instant a page held in the raw store outranks a
legacy copy of what was read from it. The exporter derives, per key:

| Field | Meaning |
| --- | --- |
| `state` | `gone` if the latest sighting was a miss; `expired` if `valid_to` has passed or the source said so; otherwise the status the source implied (`live`, `lead`, `derived`, `illustrative`, `campaign`, `historical`) |
| `last_seen_at`, `age_days` | last positive sighting and its age at export time |
| `stale` | an active offer not seen for more than 14 days (`STALE_DAYS`) |
| `history` | every span with its price-bearing fields, so a price change is a diff, not an overwrite |

Only **current** offers (active state, not stale) feed a car's best per route and source;
freshness is derived in the browser from the spans (`lib/model/offers.ts`), as of today, so
an un-refreshed deployment still greys out old offers. An offer key names one derivative at its
source, so the whole of its history sits on the car its latest sighting is matched to.

## Matching: CAP ids, the rules, and the owner's decisions

Every source names cars differently. A record carries a `car_ref` (`{source, key, …}`): the key
is whatever is stable for that source, the CAP derivative id on Carwow (`carwow-cap`), Hyundai's
CAP code (`hyundai-cap`), or the derivative text normalised by `parse.norm_key` (`ncd`,
`leaseloco`, `rrg`: lower-case, `kwh` glued to its number, parts joined by `|`). The build
matches every record at once (`Build.match`), in this order:

1. **The owner's decision.** A row of `data/seed/trim_map.json` with a `car_id` says "this is
   that car" and wins. A row without one (`ignored`) says the derivative is not one of the owner's
   cars; it does not stop the rules below, and only marks a record they cannot place as ignored
   rather than unmapped.
2. **A CAP id.** A record naming a CAP id is that derivative.
3. **The broker's text** (LeaseLoco, NCD, used listings): the rules in `services/resolve.py`
   against every derivative of that make and model (below). A used listing is matched the same
   way (the owner's decision, then the rules) but never listed as unmapped: stock is not an offer.
4. Otherwise the record is listed on the Data page as `unmapped` (or `conflict`), with its
   evidence, and `python -m pipeline trims` prints it. A spec row is never a mapping task:
   EV Database rows belong to no car (the claim store lays them over cars by model and battery).

The result of every match is written to the build database's `trim_map` table with its method
and evidence, so the Data page can show why a lease sits on a car. That table is derived like
everything else; the owner's decisions live only in the seed file.

## Derivatives (every EV on sale)

`carwow_catalog` writes a `models` row per `<make>/<model>` Carwow lists, from three index
pages: `sitemap/car_models.xml` (every model, and which have a `/specifications` page),
`sitemap/car_model_deals.xml` (which have a `/deals` page) and each make's `/electric` page
(the make's electric models by name, from `sitemap/brand_fuel_types.xml`). Makes without an
`/electric` page because everything they sell is electric (Tesla, Polestar, XPeng …) are
flagged by make; MINI's electric models are listed by slug. The pages merge by slug (a flag set
by any page sticks). `carwow_specs`, `carwow_deals` and the others discover their targets from
`models` in the last build's database (`ctx.extras["db"]`), falling back to their static lists
before the first catalogue run; within one night's scrape each provider's records are written
into that database as it goes, so the catalogue read first tonight is what the model pages are
discovered from tonight. `leaseloco` guesses each model's slug as an *optional* target, which
the scraper skips on a 404 instead of counting a failure.

The build makes one derivative per CAP id that any record names (`Build.derivatives`), in the
form the matcher and the app read (`services/autocars.py`), id `carwow-cap:<cap id>`:

- from its **specification row** (`from_spec`): make, model and trim as Carwow prints them, the
  engine as the variant, numbers, the canonical equipment flags as tri-state fields (`standard` /
  `option`, else `unknown`: an equipment list that omits an item is not proof it is absent), RRP,
  image, the derivative's version date as the model year;
- else from the **registry** (`carwow_model`'s line for it) or, for a derivative only a deals page
  prints (run-out stock, an archived price list), from the **latest deals-page line** that names
  it (`from_stub`): trim, engine, RRP, version date. Of several lines, the one from the newest
  price list wins, then the latest sighting, so the order pages were read in never decides.

A derivative the owner entered in `data/seed/cars.json` (the trim map's `carwow-cap` decision
names it) appears once, as the owner's entry, carrying its CAP id; it inherits everything said
about the derivative, and a match on it, a spec row for it or a used listing of it lands on the
owner's car. `auto: true` marks a derivative the owner has not entered, which is all the app's
"Hand-curated" filter reads. Nothing else makes a car: no record creates one as a side effect.

### Resolving broker rows (services/resolve.py)

A broker row carries CAP's derivative name ('150kW GT-Line S 81.4kWh 5dr Auto [Heat
Pump]'); Carwow carries the CAP id and RRP but prints only trim and engine, so one trim
often has several derivatives on Carwow told apart by RRP alone (packs, a heat pump, a
seat layout). This is linkage to a registry, not clustering (bolthole's resolver clusters
peers because no source carries an id; here the CAP id is the sync key). The rules, in
order, each recorded as `method` + `evidence` on the trim-map row:

| Step | Rule | method |
| --- | --- | --- |
| gates | make + model agree, kW and kWh agree where both print them, every trim word of the candidate appears in the text (`services/match.py`); engine words are a bonus | |
| one match | a single candidate survives | `trim-powertrain` |
| twins | the broker's own RRP equals one twin's (NCD prints price + saving, £135 above the RRP for on-the-road extras) | `rrp` |
| | the same CAP name was pinned to a twin by another source | `name` |
| | a pack in the name goes to the dearer twin when there are exactly two prices; '[No …]' or no bracket to the cheapest | `bracket`, `base` |
| | identical prices: the current price-list version, then the id | `version` |
| conflict | a pack bracket against three or more prices and no RRP | status `conflict`, listed on the Data page, never guessed |

A bracket that picked a twin also says something Carwow never prints: '[Heat Pump]' → heat
pump standard, '[No Heat Pump]' → none, '[7 seat]' → seats, any other name → a pack the
derivative includes. The claim store reads that from the resolved broker names at export
(`claims.from_broker_labels`); nothing is written onto the car record.

The rules see every record at once. The `name` rule ("the same CAP name was pinned to a twin by
another source") reads pins that a first pass made from every sighting whose own RRP settled it,
so it gives the same answer whatever order the pages were read in, and a page that printed its
RRP once keeps its name pinned after it stops printing it. A name pinned to two twins pins
neither.

## Backfill from the Wayback Machine

Each live provider has a second capability, `backfill`, built by
`providers/wayback.py::backfill_capability(base)`: discover asks the CDX index for every 200
capture of the base capability's URLs since a date, thins them to one per week and drops
captures whose body digest matches the last one kept, and yields a target per capture whose
`observed_at` is the archive timestamp; fetch pulls the raw page (`/web/<ts>id_/<url>`); parse is
the base parser, which reads `observed_at` and `original_url` off the target. The scraper keeps
each capture in the raw store (origin `wayback`, its target carrying the archive date), so the
build parses it like any page and its sightings fold into the spans by date.

`python -m pipeline backfill` runs it by hand on the laptop (archive.org refuses connections from
some cloud networks, and the laptop is where the raws live), then `python -m pipeline build`
folds the captures in. A run takes on no new page after `--budget-seconds`; the pages whose
captures it finished go into the raw store's backfill log, which the next run skips. `--shard
i/n` splits one provider's pages across runs. The backfill made on GitHub before the rebuild
(Oct 2026) survives as legacy rows; its raw captures were never kept, so re-running the backfill
would fetch them as raws.

Coverage (probed 6 Oct 2026, with the archive partly offline): Carwow Kona and EV6 deals pages
have 8–9 captures each since mid-2024, Hyundai's Ioniq 5 offer page 30, New Car Discount's Kona
and Ioniq 5 listings 3–4, the newer models (Ioniq 3, EV2, EV3, PV5, Inster) 0–3, LeaseLoco and
RRG none. Old captures of a page that has since been redesigned parse to zero rows, which is
harmless. Spec providers have no backfill: a spec row is current state.

## The legacy history

Before the rebuild the pipeline threw its pages away and committed `data/history/*.jsonl`:
parsed records, each pinned to the car it had been matched to. That history is the only copy of
what was fetched between January 2025 (the Wayback backfill) and 10 Oct 2026. `pipeline
raw-migrate` (and every `nightly`) copies every committed version of every one of those files
into the raw store, byte for byte, as fetches of source `legacy` dated by their commit; it is
idempotent and reads every ref the clone has, so the files' removal from `main` loses nothing.

The build reads them with the matching taken out (`legacy.read`): no row keeps its `car_id`,
`resolutions.jsonl` (the old pipeline's matches) yields nothing, and the owner's own offers are
read from `data/seed` rather than from their copies. A legacy price row is a span, so it becomes
two sightings, at its start and at its end; every version contributes its sightings, and at one
instant the latest commit's wins. Where today's parser derives a field from fields the legacy
row kept, the reader derives it too (`legacy.upgrade`): New Car Discount's RRP, which the old
spans lacked because a span kept its first sighting's payload.

## Specs (features by variant)

A `spec` record is one source variant: a Carwow CAP derivative (trim equipment list +
engine numbers + model facts, keyed `carwow-cap:<cap>`) or a Kia grade × powertrain
(× seat count where the page splits them, keyed `kia-spec:<model>:<grade>:<battery drive>[:<seats>seat]`).
`providers/carwow_specs.py` and `providers/kia_specs.py` are the parsers; both are pinned to
captured pages in `tests/fixtures`. The build matches a spec row by its CAP id or by the owner's
decision and never records a miss: a Kia grade without a car is kept with `car_id NULL` so the
Specs page can show the whole range. A spec row keeps its latest state, and `changed_at` moves
when the fingerprint (features, flags, numbers, RRP) does.

`services/features.py` maps the sources' wording onto canonical flags
(`heat_pump`, `v2l_internal`, `v2l_external`, `heated_front_seats`, `camera_360`, …),
each `standard`, `option` or `null` (not listed; sources say what a car has, not what it
lacks). The exporter attaches each car's mapped specs and a `spec_check` comparing the
hand-entered tri-state fields with the flags, and falls back to a Carwow render for the
car image (exact derivative first, then the same model and trim word).

## Live scraping

`providers/http.py` is the one fetch path: a browser user agent, a per-host delay, two retries
on 429/5xx, and a `FetchError` that keeps the status and body of an HTTP error. The scraper
(`pipeline/runner.py`) keeps every response in the raw store, a failed one too when the site
answered, and records the run in the store's log; one dead page does not sink a provider's run.
A fetch that combines several responses (cinch's and Motorpoint's pages, Hyundai's configurator
page and the API call it names, Hyundai's downloads page and the PDF it links) hands the parser
one body and also returns each response as it came, which the store keeps beside it (role
`part`). Each live provider is a `parse_page(text, …) -> rows` pure function with the real
captured page in `tests/fixtures/`, so a layout change fails `tests/test_providers.py` rather
than writing nonsense; the page is kept either way, so the fixed parser reads it again at the
next build.

What each site gives, and the caveats carried into the offer rows:

- **Carwow deals pages** are server-rendered and public. Per derivative: RRP, Carwow's best
  cash price across its dealers (status `lead`, the named dealer needs the logged-in quotes
  page), and on Kia pages a separate *PCP Finance* price (the price if you take Kia's PCP, usually
  below cash: the row carries `pcp_finance_price` and the delta). One representative PCP example
  per model, matched to its derivative by RRP, status `illustrative`.
- **Hyundai UK offer pages** embed the complete PCP example as JSON (`data-js-options`): cash
  price, grant, OTR, deposit and contribution, APR and flat rate, GFV, interest, mileage, excess
  charge, and the order window in the T&Cs (`valid_from` / `valid_to`). Deposit is Hyundai's
  example (£3,500), not £0; the maths in the app normalises that.
- **New Car Discount** prints one all-in price per derivative, including the grant. The listing
  names the no-heat-pump and pack variants explicitly, which is how the trim map tells them apart.
- **LeaseLoco** ships deals in `__NEXT_DATA__` (`originalBestDealList`, or the first search
  page for models without a curated list). Prices are ex-VAT and are multiplied by 1.2; the key
  includes term, initial-months and mileage because the same car appears on several profiles.
- **RRG** is a plain-text representative example on a dealer page; the regex is pinned to the
  current wording.

Blocked or unavailable, and why they are not providers: Richmond Hyundai and Kia's used-car site
(Imperva, blocks headless Chromium too), cars2buy (Cloudflare), Arnold Clark (client-rendered),
EV Database (rate-limited), and Kia's own quote API (`kiaofferscalculator.co.uk`), which answers
"No quote available for parameters entered" for every parameter set, in the live widget as well.

## Carwow without an API

Carwow has no public API and blocks datacenter scraping, so Carwow offers come in as pasted
pages: copy the dealer-offer page text from the logged-in browser into
`data/pastes/carwow/<date>_<dealid>.txt` with a `# captured_at: <iso>` first line. The file is
the Bronze artifact; `carwow_paste` parses it (price, contribution, APR, GFV, mileage, the
car facts, the dealer) and reconciles the payment count against the page's own totals.
`tests/test_carwow_paste.py` pins the parser to the four real pages captured so far.

## Mapping to the reference repos

| Concern | bolthole | car-research |
| --- | --- | --- |
| Providers | `app/crawlers/*`, `Provider` of `Capability` records with discover/fetch/parse | `pipeline/providers/*`, same records, synchronous |
| Raws | `artifacts`, content-addressed, `fs` backend under `ARTIFACT_ROOT` | `pipeline/raw.py`: gzipped bodies by sha256 and an append-only index, under `CAR_RESEARCH_RAW` |
| Re-deriving | a parser fix re-parses Bronze; `resolve --rebuild` re-clusters from scratch | every build parses every page and matches every record from scratch |
| Durable decisions | `listing_pair_decision` (same / different pairs), manual snaps | the trim map's decisions in `data/seed/trim_map.json`; the owner's cars, offers and picks |
| Identity | clustering peers (no source carries an id) | linkage to a registry: the CAP id is the key, text is matched to it by rules with evidence |
| Export | `app.cli export-snapshot` → `services/snapshot.py`, `manifest.json` with `schema_version` | `python -m pipeline build` → `pipeline/services/snapshot.py`, same manifest shape |
| Where data lives | squashed orphan `data` branch stitched in by the deploy workflow | the snapshot committed on `main` under `web/public/data` |
| Static client | `lib/snapshot.ts` fetch + in-memory cache; Dexie for private data | `lib/snapshot.ts` fetch; `lib/db.ts` seeds **public** data into Dexie too and pages query it |
| CI | `frontend-ci.yml`, `pages-build-check.yml`, `backend-ci.yml` | `web-ci.yml`, `pipeline-ci.yml` (unit tests, a build from the owner's files) |

## Snapshot contract (schema_version 7)

The pipeline exports facts and knows nothing of the reader: no term, no savings rate,
no residual assumption. Every cost is computed in the browser (see "The cost model lives
in the browser").

| File | Shape |
| --- | --- |
| `manifest.json` | `{schema_version, generated_at, counts:{cars,cars_generated,models,offers,observations,used_spans,cash_benchmarks,unmapped_trims,specs,used_listings}, runs:[…]}` |
| `cars.json` | one record per derivative (`auto: true` when the owner has not entered it; `source_kind`, `cap_id`, `model_slug`) and per car the owner entered, with their facts, `model_key`, `flags`, `spec_count`, `image`, `picks`; no costs |
| `details.json` | per car id: spec rows, the hand-versus-source check, the seed's requirement check; fetched on demand |
| `sightings.json` | every offer observation span: `{key, car_id, model, route, source, provider, status, seller, from, to, present, deal}` where `deal` is the full price-bearing payload |
| `used_spans.json` | every used listing's asking-price spans: `{key, source, model, car_id, year, price, mileage, vrm, town, from, to, present}` |
| `used.json` | used stock per model: every listing ever seen (derivative, site, link, present) |
| `models.json` | the catalogue: every electric model, printed names, has_deals / has_specs, and per model how many derivatives, cars, cars with a live sighting and used examples we hold |
| `specs.json` | every scraped variant: features, options, canonical flags, numbers, image, provider, car_id when mapped |
| `requirements.json` | the requirements document as seeded; the reader edits their own copy in the browser |
| `data.json` | providers, `sources` (id → name), recent runs, unmapped trims, offer-state counts, catalogue counts: the SPA's Data page |

`source` on a span is the site, not the provider: `snapshot.SOURCES` folds Carwow's deal,
paste and used providers into one source, so the same derivative and route can be read
site by site.

`generated_at` can be pinned (`--generated-at`) so CI can rebuild the snapshot and diff it
against the committed one deterministically.

Bump `SCHEMA_VERSION` in `pipeline/services/snapshot.py` and `SUPPORTED_SCHEMA_VERSION` in
`web/src/lib/snapshot.ts` together on any incompatible change; the banner warns on skew.

The big arrays are compact JSON; `requirements.json`, `data.json` and `manifest.json` are
pretty-printed. Every commit of `web/public/data` is a dated market snapshot, which is the
price history.

## The true monthly

`web/src/lib/model/dealMath.ts` puts every route on one footing (`true_monthly`): each
cash flow discounted at the savings rate (money not spent on a car earns it), the car's
expected value at the end credited back, the present cost spread as an annuity over the
months. Lease: initial rental and fees now, the rentals, nothing back. PCP: deposit and
payments, then the option to buy at the GFV and sell at the expected value, worth
max(V − GFV, 0). Outright and used: the price now, the car sold at V after the term; the
floor variant uses the highest GFV any lender guarantees for the car. V and the rate come
from the reader's quoting basis (`requirements.quoting_basis`: `term_months`,
`savings_rate_apr`, `residual_pct_of_list` at `residual_at_months` on a smooth curve
`pct ** (t / at)`, `compare_over`), edited in Settings. With V = GFV the PCP
figure is today's hand-back arithmetic, so `true_monthly_floor` is the pessimistic case.

`model/deal_math.py` is the same arithmetic in Python. It is the oracle, not the exporter:
`python3 -m model.cost_fixture > tests/fixtures/cost_cases.json` writes what it says a set
of deals cost, `tests/test_deal_math.py` asserts the file is still what the module
computes, and `web/src/lib/model/dealMath.test.ts` asserts the port reproduces every
number. It also prints the markdown deal table (`python -m pipeline deal-table`).

Where V comes from, in order (`expectedValue`, reported as `residual_source`):

1. **used-market**: the median asking price of the model's used examples registered
   term-years ago (three or more of them), across `carwow_used`, `cinch_used` and
   `motorpoint_used` with the same car listed twice counted once (the same registration,
   or the same mileage where a site prints none). Model-level, not per trim, and read
   *as of a date* from the used spans (`sightings.residualAt`).
2. **gfv-grown**: the highest GFV any lender guarantees for the car that day, grown at
   the savings rate over the term. The lender stood behind the floor; the expectation
   sits above it by about the rate they discounted at. No forecasting beyond that.
3. **assumption**: the flat share of list from the basis.

### Deals of different lengths

A 25-month lease, a 37-month PCP and a 49-month PCP are not the same purchase. Each
deal's true monthly over its own term is an equivalent-annual-cost figure (it assumes you
would repeat a similar deal), which is one honest way to rank them; the default is the
other: cost every deal over the reader's term and say what has to happen at that month
(`web/src/lib/model/horizon.ts`, `at_horizon` on every point):

| Deal | At the reader's horizon H |
| --- | --- |
| PCP longer than H | `settle_early`: the payments still owed and the balloon discounted at the deal's rate (stated APR, else implied) are paid at H; the car is sold at V(H) |
| PCP shorter than H | `balloon_then_keep`: the balloon is paid when due, the car kept to H and sold at V(H) |
| PCP of length H | `as_agreed`: buy at the GFV and sell; the equity, never below zero |
| lease of another length | `lease_ends` / `lease_runs_on`: its own-term figure, flagged (ending a lease early is priced by the lender, not by arithmetic) |
| cash, used | `sold` at H |

Every point carries both figures (`true_monthly` over `horizon_months`, and
`own_true_monthly` over `own_horizon_months`) and the deal as printed (`terms`), so the
cards show the comparable number with the real deal beside it and a one-line note when
the two lengths differ. `compare_over: "own"` in the basis ranks by the own-term figure
instead.

Buying used is the fourth route: the cheapest example of the model listed now, costed the
same way (price now, sold after the term at what examples that much older ask today, else
on the flat curve), competes with the finance routes on the Pick cards; the car page lists
the stock by registration year and names the sites. Each retailer names the model its own
way ('Kona', 'ID.4', 'MG4', '4 Coupe'); `providers/used_match.py` files a listing under
the catalogue model by letters and digits, then without the electric suffix, then a short
alias table of same-car spellings.

## The app: one search, three views, saved searches

`web/src/lib/query.ts` is the one search behind the cards (`/`), the table
(`/cars`) and the specs grid (`/specs`): make, model, text, year; a min/max for every
number a car carries or costs (turning circle included); a tri-state chip for every
canonical equipment flag, for the routes a car can be had by and for hand-curated
(standard → standard, pack or option → hidden), combined with 'all' or 'any'; the sort.
It lives in the URL, so a view is a link and switching view keeps it. `useCarQuery`
applies it once per page over the car records plus the costs they do not carry. A car
no source has a value for is left out by a chip or a bound that asks about it.

A saved search is that query string with a name, kept in the IndexedDB settings
(`lib/db.ts` `getSearches`, `saveSearch`, …). `data/seed/requirements.json` `searches`
seeds the list once (and folds in once for a list begun before the snapshot carried
any); the default one is what a search view opens on when the app loads, and after that
the last search used follows the reader between views until they change it. The bar's
picker loads one, **Save…** names the current one, and Settings renames, deletes and
picks the default. The card's pack line is `searchPacks`: for each equipment chip the
search sets to "standard, pack or option", the pack the car needs for it and its price.
Settings also holds the budget line and the quoting basis. Tables built on
`components/DataTable` take a `prefsKey`: the reader shows, hides and reorders their
columns (`lib/columns.ts`, kept in localStorage per table; moving steps among the shown
columns, and a column turned on joins the end of them), and a `pinned` column (the
car) stays first and in view when the table scrolls sideways.

`lib/fields.ts` is the one list of what a car has: each field's key, label, unit, group
and how to read it off a car (or its costs). The Cars table makes a column of each, plus a
tri-state column per equipment flag the snapshot names (`flagFields`); the search's bounds
are every number and amount in it (`RANGE_FIELDS`, `r.<key>` in the URL); the car page
lists every field by group with the claim that filled it. A field the pipeline learns is
one line there.

## Facts: one claim store, one resolver

`pipeline/services/claims.py` is where every car field comes from at export. No source
writes onto a car; each emits *claims* about a subject at the level it speaks of, and a
derivative inherits what is said about the levels it belongs to:

| Level | Subject | Who speaks of it |
| --- | --- | --- |
| own | a car the owner entered | `data/seed/cars.json` |
| derivative | a CAP derivative id | the registry's CAP name and brackets (`carwow_model`), the configurator page (`carwow_options`), the maker's own configuration matched by trim, battery and price (`hyundai_configurator`), a specification row's numbers, a broker's derivative name |
| trim_battery | make, model, trim, battery | a maker's tick that holds for one battery only (`● 49kWh only`, 'only standard on the 84kWh battery'), and a maker's row for a trim sold with one battery |
| trim | make, model, trim | Carwow's standard-equipment list and trim description, the makers' grade tables (`kia_specs`, `hyundai_specs`), a curated car's reading of its trim |
| engine | make, model, engine | battery, range, power, from any specification row with that engine |
| model | make, model | body numbers; what EV Database says of every variant when they agree, and (as `inferred`, the weakest number) the body numbers every current variant's page agrees on |
| variant | an EV Database variant, matched by battery and, between packs of the same size, by the car's model year and what is on sale | measured numbers from the index card and the variant's own page (`evdb_cars`), availability |
| pack | make, model, pack name | what the pack bundles (the configurator, a curated car) |

Two edges join them: a derivative **includes** a pack (`[Tech Pack]` in its CAP name, a
curated car's packs, a pack fitted by default) and a subject **offers** a pack at a price
(the configurator, a curated car's `packs_required`). A claim is `(field, value, kind,
source, label)`; the kind says what sort of evidence it is, and for equipment the kinds
rank: curated; configured (the maker's own configurator: a package in the price is
fitted, a package offered on the trim but not in the price is not, a package the model
sells elsewhere and neither lists nor offers here is not available); named (a bracket)
and maker (the maker's own table: ● fitted, - not fitted), the same strength; named_twin (a trim with a `[No X]` version has X on its other
derivatives), included (through an included pack), curated_twin, listed (a standard list,
or fitted by default), described, offered (through a pack, with its price), option (on its
own, with its price), available (EV Database), absent (not in a complete standard list,
or not offered as an option or pack). Numbers rank by level, nearest first.

The resolver takes a field's strongest kind across the car's levels and requires it to
agree; a disagreement is unknown and both sides are kept on the car (`disagreements`). So
CAP's `[No Heat Pump]` on the derivative and Hyundai's ● on the trim are weighed together
and shown, rather than one quietly winning. A verdict of none means not fitted as
standard: where a pack or an option offers the item, the answer is that pack or option,
whoever said none. A maker's grade with several columns (Kia's with-heat-pump column, two
powertrains) speaks for the trim where the columns agree; where they differ the plainest
column speaks weakly and the bracket or the battery level decides. A CAP name reprinted by
three brokers is one `named` claim with three sightings, not three claims. What a stronger
source sets aside is kept on the car as `overruled`, so the car page can say that Hyundai's
table ticked the heat pump the configurator does not sell on that trim. Every resolved field names
its claim (`field_sources`, exported in the per-car detail file, not `cars.json`), `flags` carries all 29 equipment flags with a verdict
(standard, pack, option, none), `packs_required` and `pack_prices_gbp` say which pack a
"pack" verdict leans on and what it costs, and the app prices the packs a car needs for
the equipment a search asks for (`lib/query.ts` `searchPacks`). Nothing in the resolver names a feature: the heat
pump, the cabin socket and the powered tailgate are three flags among the 29
`services/features.py` knows, resolved by the same rules.

The configurator page (`providers/carwow_options.py`, Gold `options`) is read for every derivative the registry or a
specification row names: its JSON block lists every option and pack with prices and
contents, so "not offered" is evidence rather than silence.

The makers' tables are the other side of the scale. `providers/kia_specs.py` reads
kia.com's grade × feature grid; `providers/hyundai_specs.py` reads the Tech & Spec guide
PDF Hyundai UK publishes per model (layout text via `pdftotext`, else pypdf): one row per
trim from the latest model year's column, with the items ticked, the items dashed, the
ticks qualified by battery, the batteries the pricing table sells the trim with, and the
packs the OPTIONAL EXTRAS table prices with their contents and the trims they are offered
on. The PDF prints one glyph for standard and for optional, so an item a pack offered on
the trim bundles is read as that pack's; a dash on an accessory row (an exterior V2L
adaptor) is read as sold separately.

`providers/hyundai_configurator.py` (Gold `configurations`)
is the transactional source: the build-and-price page's GraphQL endpoint, one query per
model, returns every orderable configuration (Hyundai's FSC) with trim, powertrain, price,
the packages in that price with a description of what they bundle, and each trim's
standard-equipment list. The claim store matches a configuration to a CAP derivative by
trim, battery and price (then, for what is left, by brackets agreeing with packages where
the pairing is unique) and reads it at the `configured` rank; the trim's equipment list is
read as a list, since it is the union over the trim's powertrains.

## Sightings: every route, every source, over time

`web/src/lib/model/sightings.ts` is the one fact behind every price in the app: a
*sighting* is a price one source showed for one subject over the span of days it stayed
the same. Subjects are derivatives (an offer on a car) or, for used stock, the model and
registration year. Routes are `cash`, `pcp`, `pch` and `used`; sources are a dimension of
their own. The pipeline stores two tables (`offer_observations`, and `used_observations`
as spans of a listing's asking price, closed when it goes) and exports them as
`sightings.json` and `used_spans.json`; the model sees one list of `Sighting` records.

`cost` puts a sighting on the common footing of `dealMath` with the used market read *as
of a date*: `residualAt` answers "what did the model's cars of that year ask on that day"
from the used spans themselves, counting a car once across sites; `floorGfvAt` the GFV a
lender guaranteed that day. History is costed as of each sighting's first day, so a June
PCP is costed on June's evidence (none before 6 October 2026, so `residual_source` says
so); what things cost now is the same function as of today. `series` groups costed
sightings by subject, route and source (an offer as flat spans held to its next sighting
unless seen gone between; a model's used stock as the cheapest example day by day);
`residualSeries` samples the evidence monthly; `current` picks the cheapest per route and
source as of today; `trend` reads the movement of the best cash price; `usedStock` the
model's stock by registration year.

## The cost model lives in the browser

The pipeline exports facts; the browser owns the one cost model and every page reads its
stored results. `web/src/lib/model/recompute.ts` (`computeAll`) is pure: spans, cars, the
basis and today in; per car the current best per route and source (`costs`), every
series, the residual evidence, and every offer's latest state with its freshness and
normalisation (`offers`) out. `lib/db.ts` runs it after seeding and whenever the stored
key (snapshot `generated_at`, the basis, the day) differs from the one the results were
computed under, writes the results to IndexedDB in one transaction, and `saveRequirements`
runs it again before resolving, so a change to the term or the rate in Settings
recomputes everything once and every page re-reads. ~8,000 sightings cost twice
(history and today) in well under a second; the Data page shows the last run.

Nothing is costed at render time: `lib/costs.ts` turns a car's stored row into what a card
or table shows, and `lib/useCarQuery.ts` joins the rows to the cars once per page.

## Trends in the app

`web/src/lib/trends.ts` turns an offer's history into chart series: `offerSeries` joins
spans into a step line (a 'gone' breaks it), `dailyBest` takes the lowest covering span
per day with a current offer extended to today, `movement` reports the current run,
the first value and a windowed delta. `components/charts/LineChart.tsx` is a plain SVG
multi-line chart (2px lines, 8px end markers with a surface ring, hairline grid, legend
for two or more series, direct end-labels for up to four, crosshair tooltip reading
every series at the snapped date, arrow-key focus) and `Sparkline.tsx` the stat-tile
version. Colours are assigned by sorted offer id so a filter never repaints a line; the
palette was validated against the app's dark surface. Every chart has a table twin.

Model matching is forgiving ("Kona" matches "Kona Electric"); the year is a car's model
year or a Carwow derivative version's year. The Pick page shows 48 cards at a time with a
"show more" button, since every EV is ~2,000 derivatives; Specs pages its columns 40 at a
time.

## Browser-side database

`web/src/lib/db.ts` opens `CarResearchDB` (Dexie):

- **facts** `cars`, `sightings`, `used_spans`, `specs`, `models`, `meta` (and `details`,
  `used`, fetched in the background after each download) — downloaded once and then read
  with no network: `ensureSeeded` returns the stored snapshot whenever there is one this
  build can read (`meta.manifest`), and only a first visit or a new data format waits on a
  download. `checkForUpdate` asks the site for the manifest afterwards (the banner calls it
  once per load and when the browser comes back online) and, when the site has a newer
  cut, replaces the facts in one transaction and the pages re-read; offline it reports so
  and the stored copy stays.
- **results** `costs`, `series`, `residuals`, `offers` — what the cost model makes of the
  facts under the reader's basis as of today; rewritten by `ensureComputed` when the
  snapshot, the basis or the day changes (`meta.costed` holds the key they were computed
  under, `meta.compute_stats` the last run).
- **private** `settings` (the saved searches; the budget line and the quoting basis) —
  never leave the browser, survive new snapshots.

Pages use react-query hooks (`lib/hooks.ts`) over Dexie queries; saving the settings
invalidates every results query. The snapshot banner shows the stored generation, runs the
background check, and can be asked to check again.

The app itself is kept by a service worker: `web/scripts/build-sw.mjs` runs after
`next build`, lists every built file except the snapshot's JSON (IndexedDB holds that) and
writes `out/sw.js`, which caches them under a name hashed from their contents, serves them
cache-first (a page by its directory address, an RSC payload whatever its `_rsc` query), and
drops the previous build's cache when a new one installs.

## Deploy

`.github/workflows/pages-deploy.yml` runs on push to `main`: `npm ci`, `next build` with
`NEXT_PUBLIC_BASE_PATH=/car-research`, copy `index.html` → `404.html` (SPA fallback for deep
links like `/cars/view?id=…`), `.nojekyll`, `upload-pages-artifact`, `deploy-pages`.

One-time repo settings: **Settings → Pages → Source = "GitHub Actions"** (until then the
deploy step fails with a 404), and the `github-pages` environment GitHub creates at that point
carries a deployment-branch rule naming the branch that was the default at the time. Changing
the default branch later does not update the rule. The workflow deploys from `main`, so add
`main` under Settings → Environments → github-pages → Deployment branches and tags. A run
rejected by that rule fails in two seconds with no runner and no logs.

The nightly job runs on the owner's laptop, where the raws live (`scripts/nightly.ps1`, registered
with Task Scheduler by `scripts/install-nightly.ps1`, daily at 03:17, waking the laptop and
catching up after a missed start). In a worktree of its own (`%USERPROFILE%\car-research-nightly`)
it checks out `origin/<branch>` and runs `python -m pipeline nightly`: new committed history into
the raw store, scrape every live source into it, build from scratch, snapshot, deal table. With
`-Push` it commits `web/public/data` and `docs/deal-comparison.md` and pushes to `main`, which
deploys the site; if `main` moved meanwhile it builds again on it from the raws (no new fetching)
and retries. Without `-Push` it pushes nothing and logs how its snapshot differs from main's
(`scripts/compare_snapshots.py`): the mode for nights when the GitHub scrape still runs. Each
night's log is `<raw store>\logs\nightly\<date>.log`. Each provider keeps itself inside a few
hours: the configurator pages rotate weekly (250 a night), EV Database car pages stop at 60 or
25 minutes.

CI cannot rebuild from raws it does not have. `pipeline-ci.yml` runs the unit tests (which build
from a raw store of the captured fixture pages) and a build over the owner's own files with an
empty raw store.

If the snapshot ever grows past a few MB (per-listing price history, scraped used-car markets),
move it off `main` onto a squashed orphan `data` branch exactly as `etf-tool/scripts/publish-data.sh`
does, and add the second checkout step to the deploy workflow.

## Local development

```
make nightly         # python -m pipeline nightly: migrate new history, scrape into the raw store, build, snapshot
make build           # python -m pipeline build: from scratch from the raws already held (no network), snapshot, deal table
make test            # python unittest + web lint/typecheck/vitest
make web-dev         # next dev on :3001, reads web/public/data
make web-build       # static export to web/out
python -m pipeline scrape --only <provider>   # one live source into the raw store
python -m pipeline raw-status | raw-migrate | status | trims | models | deal-table | backfill
```

Python ≥ 3.11, stdlib only (on this laptop `uv run --python 3.12`; set `PYTHONUTF8=1` on
Windows). Node 22. `CAR_RESEARCH_RAW` names the raw store; without the owner's laptop, a clone
can still `raw-migrate` the legacy history into an empty store and build from that.

## Adding a provider (scraper)

1. Save a real page into `tests/fixtures/` first and write `parse_page()` against it.
2. `pipeline/providers/<name>.py`: `discover` yields the targets (URL and whatever the parser
   needs in `metadata`, which the raw store keeps with each fetch), `fetch` calls
   `http.fetch_url` (a fetch that combines several responses returns them as `parts`), `parse`
   wraps `parse_page`; declare `Capability(kinds=("offer",))` and `Provider(live=True)`.
3. Register it in `pipeline/providers/__init__.py`, in the order it should be scraped.
4. Emit `ParsedRecord(kind="offer", key=<offer key>, row=…)` with `offer_key`, `observed_at`
   (from `observed_at_for(target)`), `present`, `finance_type`, `status`, `verification:
   "scraped"`, the price fields in the seed schema, and `car_ref` (a CAP id, or `{source, key,
   label, make, model, derivative}` for the rules to match).
5. `python -m pipeline scrape --only <name>`, then `python -m pipeline build` and `python -m
   pipeline trims` to see what the rules could not place (decide it in `data/seed/trim_map.json`
   if it is yours to decide). Add a fixture test, through `tests.helpers.Raws` for the build.

## Decisions

- **Only the raws are permanent** (the owner's design, 10 Oct 2026, `docs/REBUILD.md`). The
  database and the snapshot are derived from scratch on every build; the owner's own files and
  decisions are the only other durable thing.
- **SQLite, not Postgres.** Single user, tiny data, no concurrent writers. Stdlib only.
- **The snapshot committed on `main`.** The orphan-branch machinery is documented above for later.
- **Next.js static export, not Vite.** Mirrors the two most recent reference repos so the layout,
  data client and deploy workflow are familiar. No server mode is built.
- **No Tremor.** Plain Tailwind tables; fewer dependencies, no React 19 / Tailwind 4 friction.
- **The cost model in the browser, the pipeline exporting facts.** The term, the savings
  rate and the residual assumption are the reader's, so the pipeline knows nothing of them;
  one TypeScript implementation costs every sighting under the reader's basis, once per
  change, and stores the results. `model/deal_math.py` stays as the oracle behind the shared
  fixture and the markdown deal table.
- **Public data in IndexedDB as well as private.** Matches the "dump it all into a local DB on load"
  pattern; filtering and sorting stay instant, and with the service worker the app opens and
  works offline after the first load.
