# Architecture

The same shape as `etf-tool` and `bolthole`, scaled to a dataset of tens of cars and
hundreds of deals: **scrape → resolve → app**, with only the *app* layer shipped to the
browser. No Postgres, no worker, no server mode. The data is tiny, so it is committed
on `main` and GitHub Pages serves it.

```
providers (discover → fetch → parse)       pipeline/providers/*      Python, stdlib
   manual_seed     data/seed/*.json          cars, requirements, trim map, hand-captured offers
   carwow_paste    data/pastes/carwow/*.txt  Carwow offer pages copied out of a logged-in browser
   carwow_catalog  carwow.co.uk (live)       the catalogue: every electric model, from the sitemaps + <make>/electric pages
   carwow_specs    carwow.co.uk (live)       equipment per trim, numbers per engine, CAP ids + version dates, images
   carwow_deals    carwow.co.uk (live)       best cash price per CAP derivative, Kia PCP-finance price, rep. example
   hyundai_offers  hyundai.com/uk (live)     Hyundai Finance national PCP example per model, with validity dates
   ncd             new-car-discount.com      broker all-in cash price per derivative
   leaseloco       leaseloco.com (live)      best personal lease per derivative/profile (ex-VAT → inc.)
   rrg             rrg-group.com (live)      dealer PCP example for the PV5 7-seat
   kia_specs       kia.com/uk (live)         grade × feature ticks, numbers per powertrain, seat variants
   hyundai_specs   hyundai.com/uk (live)     the Tech & Spec guide PDF per model: ● / - per trim, battery-qualified ticks, packs with prices
   hyundai_configurator  hyundai.com/uk (live)  the build-and-price GraphQL: every orderable configuration, its price, the packages in it
   carwow_used     quotes.carwow.co.uk        used stock per model: derivative, price, year, mileage (the buy-used route; residual evidence)
   cinch_used      search-api...cinch.co.uk   used stock per make (electric), with registrations; folded with the others per model
   motorpoint_used motorpoint.co.uk           the supermarket's electric stock, nearly new; list price when new per car
        │  Bronze  artifacts            every fetched body, sha256-addressed, supersede chain
        │  Silver  source_rows          one row per parsed record, in the source's vocabulary
        │  Gold    models               the catalogue: <make>/<model>, names, electric / has_deals / has_specs
        │          cars                 canonical trims: hand-curated, plus one generated per Carwow derivative
        │          trim_map             (site, trim-as-printed) → car_id; 'auto' = a generated car; misses 'unmapped'
        │          offer_observations   one row per offer key per sighting (present / gone)
        │          specs                one row per source variant: equipment, flags, numbers, image
        │          used_listings        used stock as current state (present / gone), linked to a derivative where named
        ▼          requirements
SQLite  data/car-research.sqlite            gitignored: a dev-machine artifact
        │  ⇄ data/history/{observations,specs,models,resolutions,used,backfill}.jsonl  COMMITTED: every refresh
        │                                      rewrites them, every run (CI, a fresh clone) replays them first
        ▼  export_snapshot()                 pipeline/services/snapshot.py
JSON    web/public/data/{manifest,cars,offers,requirements,data}.json   COMMITTED on main
        │   offers = latest observation per key + finance maths + freshness (state, age, history)
        ▼  push to main → Actions → next build (output: export) → Pages
SPA     web/                                 Next.js 16 App Router, Tailwind 4, react-query, Dexie
        │  first load: download the snapshot into IndexedDB; after that read it from there,
        │  no network, and fetch a newer cut in the background (a service worker keeps the app)
        ▼  pages query IndexedDB (public tables) + the reader's saved searches and settings
```

## Offers are observations

An offer is never edited in place. Each provider run records what it saw: one
`offer_observations` row per **offer key** per sighting, with `present = 0` when a check
found the offer gone. The offer key is stable per real-world offer (a Carwow deal id, a seed
id, later a dealer URL plus trim). The exporter derives, per key:

| Field | Meaning |
| --- | --- |
| `state` | `gone` if the latest sighting was a miss; `expired` if `valid_to` has passed or the source said so; otherwise the status the source implied (`live`, `lead`, `derived`, `illustrative`, `campaign`, `historical`) |
| `last_seen_at`, `age_days` | last positive sighting and its age at export time |
| `stale` | an active offer not seen for more than 14 days (`STALE_DAYS`) |
| `history` | every sighting with its price-bearing fields, so a price change is a diff, not an overwrite |

Only **current** offers (active state, not stale) feed a car's best per route and source;
freshness is derived in the browser from the spans (`lib/model/offers.ts`), as of today, so
an un-refreshed deployment still greys out old offers. Re-running a provider over an unchanged
page is idempotent (same key, same observed time, same artifact).

## Trim map (the small resolution problem)

Every source names trims differently. A record that arrives with a `car_ref` (`{source, key}`)
is resolved through `trim_map`; the key is whatever is stable for that source: the CAP
derivative id on Carwow (`carwow-cap`), Hyundai's CAP code (`hyundai-cap`), or the derivative
text normalised by `parse.norm_key` (`ncd`, `leaseloco`, `rrg`: lower-case, `kwh` glued to its
number, parts joined by `|`). A miss leaves the record in Silver, records an `unmapped` row, and
counts on the run. `python -m pipeline trims` lists them (and fails CI); add the mapping to
`data/seed/trim_map.json` and re-run. Rows with `"status": "ignored"` are derivatives we have
looked at and chosen not to curate by hand (the 42kWh Ioniq 3, no-heat-pump Insters, 5-seat
PV5s, AWD Ioniq 5s).

Since the catalogue, a miss is rarer: a Carwow CAP id that is not `mapped` resolves to the
generated car `carwow-cap:<id>` (`status: auto`), and a broker's derivative text resolves to
the one generated car of that make + model whose kW, kWh and trim words agree
(`services/match.py`; a tie or a contradiction is a miss, never a guess). Nothing is ever
attached to a guessed car, and a hand-curated car always wins its derivative.

## Generated cars (every EV on sale)

`carwow_catalog` writes a `models` row per `<make>/<model>` Carwow lists, from three index
pages: `sitemap/car_models.xml` (every model, and which have a `/specifications` page),
`sitemap/car_model_deals.xml` (which have a `/deals` page) and each make's `/electric` page
(the make's electric models by name, from `sitemap/brand_fuel_types.xml`). Makes without an
`/electric` page because everything they sell is electric (Tesla, Polestar, XPeng …) are
flagged by make; MINI's electric models are listed by slug. Gold merges the pages by slug
(a flag set by any page sticks). `carwow_specs` and `carwow_deals` discover their targets from
`models` (`ctx.extras["db"]`, which the runner sets), falling back to their static lists before
the first catalogue run; `leaseloco` guesses each model's slug as an *optional* target, which
the runner skips on a 404 instead of counting a failure.

Every Carwow derivative without a hand-curated car gets a generated one
(`services/autocars.py`), id `carwow-cap:<cap id>`, `auto: true`:

- from its **spec row** (`from_spec`): make, model and trim as Carwow prints them, the engine as
  the variant, numbers (seats, battery, range, power, boot, turning circle), the canonical
  equipment flags as tri-state fields (`standard` / `option`, else `unknown`: an equipment list
  that omits an item is not proof it is absent), RRP, image, the derivative's version date as
  the model year;
- from a **deals-page stub** (`from_stub`, carried in the offer's `car_ref`): trim, engine, RRP,
  version date. Seen for derivatives only an (archived) deals page prints: run-out stock, last
  year's list.

`gold.ensure_auto_car` writes one unless a hand-curated car owns the id; a spec-built car
replaces a stub, a stub replaces nothing.

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
derivative includes. The claim store reads that from the broker rows in the trim map at
export (`claims.from_broker_labels`); nothing is written onto the car record, which no
history carries, so a live run and a replay of the history say the same. An offer key names one derivative at its
source, so when a rule moves it to a different twin its whole sighting history moves
too (`gold.write`). `pipeline reparse` re-runs the parsers and the rules over the stored
pages without the network. `gold.prune_auto_cars` drops generated cars nothing
refers to (their derivative was promoted to a hand-curated car). On replay, `import_specs`
regenerates the spec-built cars and `import_history` rebuilds a stub from the observation's
`car_ref` when its car is missing, so the committed history is complete without a cars file:
the order is models → specs → observations (`cli._replay`).

## Backfill from the Wayback Machine

Each live provider has a second capability, `backfill`, built by
`providers/wayback.py::backfill_capability(base)`: discover asks the CDX index for
every 200 capture of the base capability's URLs since a date, thins them to one per
week and drops captures whose body digest matches the last one kept, and yields a
target per capture whose `observed_at` is the archive timestamp; fetch pulls the raw
page (`/web/<ts>id_/<url>`); parse is the base parser, which reads `observed_at` and
`original_url` off the target. The runner stores the archived body as a Bronze
artifact under the base provider, so a backfilled sighting is indistinguishable from a
live one apart from its date.

Gold's `_merge_sighting` makes out-of-order sightings safe: a sighting matching the
span before it extends that span; one matching the span after it moves that span's
start back; one bridging two matching spans merges them; a different price inside a
span splits the span at that point (the span was seen at its start and end, so those
become two rows). `refresh` skips `backfill`; `pipeline backfill` runs it. `.github/workflows/backfill.yml`
runs it on GitHub runners (archive.org refuses connections from some cloud networks) as
one short job per provider, each from the committed history, exporting only that
provider's rows (`export-history --source`); a merge job replays the committed history,
replaces each provider's rows with its chunk (`import-history --replace-source`), and
commits. A chunk's log is readable the moment it finishes, a hung page costs that chunk
one timeout, and a failed chunk leaves the others' results intact.

Coverage (probed 6 Oct 2026, with the archive partly offline): Carwow Kona and EV6
deals pages have 8–9 captures each since mid-2024, Hyundai's Ioniq 5 offer page 30,
New Car Discount's Kona and Ioniq 5 listings 3–4, the newer models (Ioniq 3, EV2, EV3,
PV5, Inster) 0–3, LeaseLoco and RRG none. Old captures of a page that has since been
redesigned parse to zero rows, which is harmless.

Chunks are time-boxed. archive.org can take a minute per index query on a bad night, so
a chunk takes on no new page after `--budget-seconds` (20 minutes in the workflow, inside
a 30-minute job) and exports what it has; the pages whose captures it consumed go into
`backfill_ledger` (committed as `data/history/backfill.jsonl` by the merge job), and the
next run skips them. `--shard i/n` splits one provider's pages across jobs
(`carwow_deals@3/8` in the workflow matrix). Re-run the workflow until the chunks report
nothing left; a capture folded in twice merges, never duplicates. Spec providers have no
backfill: a spec row is current state and an older capture must not overwrite it.

## Specs (features by variant)

A `spec` record is one source variant: a Carwow CAP derivative (trim equipment list +
engine numbers + model facts, keyed `carwow-cap:<cap>`) or a Kia grade × powertrain
(× seat count where the page splits them, keyed `kia-spec:<model>:<grade>:<battery drive>[:<seats>seat]`).
`providers/carwow_specs.py` and `providers/kia_specs.py` are the parsers; both are
pinned to captured pages in `tests/fixtures`. The runner resolves a spec through the trim
map like an offer but never records a miss: a Carwow derivative nobody curates gets a
generated car (above); a Kia grade without a car is kept with `car_id NULL` so the Specs
page can show the whole range. Gold upserts by key and stamps `changed_at` when the
fingerprint (features, flags, numbers, RRP) moves. Spec rows are current state, so the
spec providers have no Wayback backfill (an older capture must not overwrite them).

`services/features.py` maps the sources' wording onto canonical flags
(`heat_pump`, `v2l_internal`, `v2l_external`, `heated_front_seats`, `camera_360`, …),
each `standard`, `option` or `null` (not listed; sources say what a car has, not what it
lacks). The exporter attaches each car's mapped specs and a `spec_check` comparing the
hand-entered tri-state fields with the flags, and falls back to a Carwow render for the
car image (exact derivative first, then the same model and trim word). Specs are
committed as `data/history/specs.jsonl` and replayed offline, so CI reproduces the
snapshot without the network.

## Live scraping

`providers/http.py` is the one fetch path: a browser user agent, a per-host delay, two retries
on 429/5xx, and a `FetchError` the runner turns into a per-target failure (one dead page does
not sink a provider's run; the run records `errors` and the failing targets). Each live
provider is a `parse_page(text, …) -> rows` pure function with the real captured page in
`tests/fixtures/`, so a layout change fails `tests/test_providers.py` rather than writing
nonsense. Providers set `live=True`; `refresh --offline` skips them, which is what CI runs.

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

| Concern | etf-tool / bolthole | car-research |
| --- | --- | --- |
| Providers | `app/crawlers/*`, `Provider` of `Capability` records with discover/fetch/parse | `pipeline/providers/*`, same records, synchronous |
| Bronze | `artifacts` in Postgres, content-addressed, `superseded_by` | `artifacts` in SQLite, same columns |
| Silver | `source_*` tables per source | one generic `source_rows` table (`source`, `kind`, `source_key`, JSON `row`) |
| Gold | `funds`, `assets`, … | `cars`, `trim_map`, `offer_observations`, `requirements` (JSON payload + indexed columns) |
| Identity | bolthole's listing → property resolver | `trim_map`: a lookup table per source, with an unmapped queue |
| Export | `app.cli export-snapshot` → `services/snapshot.py`, `manifest.json` with `schema_version` | `python -m pipeline export-snapshot` → `pipeline/services/snapshot.py`, same manifest shape |
| Where data lives | squashed orphan `data` branch stitched in by the deploy workflow (100MB+) | committed on `main` under `web/public/data` (~60KB) |
| Static client | `lib/snapshot.ts` fetch + in-memory cache; Dexie for private data | `lib/snapshot.ts` fetch; `lib/db.ts` seeds **public** data into Dexie too and pages query it |
| Dual mode | `NEXT_PUBLIC_MODE=static` vs live FastAPI | static only |
| Deploy | `pages-deploy.yml`: Actions artifact, SPA 404 fallback, `.nojekyll` | same workflow, single checkout |
| CI | `frontend-ci.yml`, `pages-build-check.yml`, `backend-ci.yml` | `web-ci.yml`, `pipeline-ci.yml` (adds a snapshot-freshness check) |

## Snapshot contract (schema_version 7)

The pipeline exports facts and knows nothing of the reader: no term, no savings rate,
no residual assumption. Every cost is computed in the browser (see "The cost model lives
in the browser").

| File | Shape |
| --- | --- |
| `manifest.json` | `{schema_version, generated_at, counts:{cars,cars_generated,models,offers,observations,used_spans,cash_benchmarks,unmapped_trims,specs,used_listings}, runs:[…]}` |
| `cars.json` | car records (hand-curated, and generated ones with `auto: true`, `source_kind`, `cap_id`, `model_slug`) with their facts, `model_key`, `flags`, `spec_count`, `image`, `picks`; no costs |
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
| own | a hand-curated car record | `data/seed/cars.json` |
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

The configurator page (`providers/carwow_options.py`, Gold `options`,
`data/history/options.jsonl`) is read for every derivative the registry or a
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

`providers/hyundai_configurator.py` (Gold `configurations`, `data/history/configurations.jsonl`)
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

`.github/workflows/scrape.yml` runs nightly at 03:17 UTC (and on dispatch): `pipeline refresh`
with the live providers writes `data/history`; the committed snapshot is then built from a
fresh replay of that history (`refresh --offline` into a second database, then
`export-snapshot --runs-db` so the Data page still shows the live runs). It commits
`data/history`, `web/public/data` and `docs/deal-comparison.md` if anything changed, then
dispatches the Pages deploy (a push made with the workflow token does not trigger other
workflows by itself). If main moved during the ~90-minute run, the push is rejected and
the job folds main's history into its database, writes it again and rebuilds the snapshot
from it (three tries). Each provider keeps itself inside the 180-minute job limit: the
configurator pages rotate weekly (250 a night), EV Database car pages stop at 60 or 25
minutes. `pipeline-ci.yml` runs `refresh --offline`: seed, pastes and the replayed history,
pinned to the committed `generated_at`, and fails if the committed snapshot differs, so
the snapshot is always what the history reproduces.

If the snapshot ever grows past a few MB (per-listing price history, scraped used-car markets),
move it off `main` onto a squashed orphan `data` branch exactly as `etf-tool/scripts/publish-data.sh`
does, and add the second checkout step to the deploy workflow.

## Local development

```
make snapshot        # python -m pipeline refresh --out web/public/data   (live scrape)
make snapshot-offline  # same with --offline: seed + pastes + replayed history
make test            # python unittest + web lint/typecheck/vitest
make web-dev         # next dev on :3001, reads web/public/data
make web-build       # static export to web/out
python -m pipeline status | deal-table | run <provider> [--capability …] [--target …]
```

Python ≥ 3.11, stdlib only so far. Node 22.

## Adding a provider (scraper)

1. Save a real page into `tests/fixtures/` first and write `parse_page()` against it.
2. `pipeline/providers/<name>.py`: `discover` yields the targets (URL in `metadata`), `fetch`
   calls `http.fetch_url`, `parse` wraps `parse_page`; declare `Capability(kinds=("offer",))` and
   `Provider(live=True)`.
3. Register it in `pipeline/providers/__init__.py` (after `manual_seed`, which writes the cars
   and trim map everything else resolves against).
4. Emit `ParsedRecord(kind="offer", key=<offer key>, row=…)` with `offer_key`, `observed_at`,
   `present`, `finance_type`, `status`, `verification: "scraped"`, the price fields in the seed
   schema, and `car_ref: {source, key, label}` for the trim map to resolve.
5. `python -m pipeline run <name>`, then `python -m pipeline trims` to see what needs mapping or
   ignoring, then `make snapshot`. The deal maths, freshness and requirement checks apply
   automatically. Add a fixture test to `tests/test_providers.py`.

## Decisions

- **SQLite, not Postgres.** Single user, tiny data, no concurrent writers. Stdlib only.
- **Data committed on `main`.** ~60KB. The orphan-branch machinery is documented above for later.
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
