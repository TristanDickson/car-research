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
        │  on load: fetch manifest → if generated_at changed, bulk-load JSON into IndexedDB
        ▼  pages query IndexedDB (public tables) + the user's shortlist (private table)
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

Only **current** offers (active state, not stale) feed a car's best-cash / best-PCP / best-PCH
summary. The SPA recomputes age and staleness from `last_seen_at` at view time, so an
un-refreshed deployment still greys out old offers. Re-running a provider over an unchanged
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

A bracket that picked a twin also says something Carwow never prints, so it is written
onto the generated car: the name as a pack, '[Heat Pump]' → heat pump standard,
'[No Heat Pump]' → none, '[7 seat]' → seats. An offer key names one derivative at its
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

## Snapshot contract (schema_version 4)

| File | Shape |
| --- | --- |
| `manifest.json` | `{schema_version, generated_at, counts:{cars,cars_generated,models,offers,observations,cash_benchmarks,unmapped_trims,specs}, runs:[…]}` |
| `cars.json` | car records (hand-curated, and generated ones with `auto: true`, `source_kind`, `cap_id`, `model_slug`) plus `requirement_check` `{passes, failures[], unknown[]}` and `deal_summary` (best current cash / PCP / PCH with the age of each) |
| `models.json` | the catalogue: every electric model, printed names, has_deals / has_specs, and per model how many derivatives, cars and priced cars we hold |
| `offers.json` | latest observation of each offer plus `metrics` (from `model/deal_math.py`) and `freshness` (state, stale, age, first/last seen, history) |
| `specs.json` | every scraped variant: features, options, canonical flags, numbers, image, provider, car_id when mapped |
| `requirements.json` | the requirements document verbatim |
| `data.json` | providers, recent runs, unmapped trims, offer-state counts, catalogue counts: the SPA's Data page |

`generated_at` can be pinned (`--generated-at`) so CI can rebuild the snapshot and diff it
against the committed one deterministically.

Bump `SCHEMA_VERSION` in `pipeline/services/snapshot.py` and `SUPPORTED_SCHEMA_VERSION` in
`web/src/lib/snapshot.ts` together on any incompatible change; the banner warns on skew.

Files are written with `sort_keys` and `indent=1` so git diffs of the data are readable. Every
commit of `web/public/data` is a dated market snapshot, which is the price history.

## The true monthly

`model/deal_math.py` puts every route on one footing (`true_monthly`): each cash flow
discounted at the savings rate (money not spent on a car earns it), the car's expected
value at the end credited back, the present cost spread as an annuity over the
agreement. Lease: initial rental and fees now, the rentals, nothing back. PCP: deposit
and payments, then the option to buy at the GFV and sell at the expected value, worth
max(V − GFV, 0). Outright: the price now, the car sold at V after the standard term; the
floor variant uses the highest GFV any lender guarantees for the car. V comes from
`requirements.json` `quoting_basis.residual_pct_of_list` at `residual_at_months` on a
smooth curve (pct ** (t / at)); `savings_rate_apr` is the discount rate. Both are
assumptions, shown on the Data page, until a used-market source replaces the residual.
With V = GFV the PCP figure is today's hand-back arithmetic, so `true_monthly_floor` is
the pessimistic case. The exporter puts the best current true monthly per route on
each car (`deal_summary.true_monthly_by_route`) and the app ranks offers by it.

Where V comes from, in order (`deal_math.expected_value`, reported as `residual_source`):

1. **used-market**: the median asking price of the model's used examples registered
   term-years ago (three or more of them), across `carwow_used`, `cinch_used` and
   `motorpoint_used` with the same car listed twice counted once
   (`snapshot.dedupe_listings`: the same registration, or the same year and mileage where a
   site prints none). Model-level, not per trim.
2. **gfv-grown**: the highest GFV any lender guarantees for the car, grown at the savings
   rate over the term. The lender stood behind the floor; the expectation sits above it by
   about the rate they discounted at. No forecasting beyond that.
3. **assumption**: the flat share of list from `quoting_basis`.

The used stock is also the fourth route. Per model the cheapest car listed now is costed
like the others (price now, sold after the term at what examples that much older ask
today, else on the flat curve), lands in `deal_summary.true_monthly_by_route.used` and
competes with the finance routes on the Pick cards; the car page lists the stock by
registration year and names the sites. Used stock is current state, not history: a
listing missing from the page it came from (a model's cards on Carwow, a make's stock on
cinch, the whole electric listing on Motorpoint) is marked gone, another source's stock
for the model is untouched, and `data/history/used.jsonl` replays it all.

Each retailer names the model its own way ('Kona', 'ID.4', 'MG4', '4 Coupe');
`providers/used_match.py` files a listing under the catalogue model by letters and digits,
then without the electric suffix, then a short alias table of same-car spellings. What we
do not sell (the previous-generation e-Niro, a Mini hatch not in the catalogue) is skipped
and counted on stderr.

## The app: one query, three views, the reader's own brief

`web/src/lib/query.ts` is the one search behind the cards (`/`), the table
(`/cars`) and the specs grid (`/specs`): scope, make, model, text, year; a min/max
for every number a car carries or costs; a tri-state chip for every canonical
equipment flag and for the routes a car can be had by (standard → standard or option
→ hidden), combined with 'all' or 'any'; the brief filter; the sort. It lives in the
URL, so a view is a link and switching view keeps it. `useCarQuery` applies it once
per page over the car records plus a context the records do not carry (the brief
verdict, the costs, the shortlist).

The brief is the reader's data: `data/seed/requirements.json` seeds an IndexedDB
settings row once, the Requirements page edits it (budget, hard rules on any car
field, preference weights), and `lib/brief.ts` evaluates it in the browser with three
states: meets, fails, not confirmed. The quoting basis stays a pipeline input, since
every cost in the snapshot was computed with it. `cars.json` carries only what every
page shows; `details.json` (stock by year, spec rows, the cross-check) is fetched on
demand for a car page. The app computes no cost: `deal_summary.routes` is the model's
answer as of the snapshot, and the card reads it.

## Facts with their sources

A generated car knows what Carwow's specification page prints: battery, range,
power, 0-60, boot, seats, equipment per trim. It does not print efficiency, charging
power or dimensions. `pipeline/services/facts.py` fills the gaps at export from the
evidence we hold and writes `field_sources` on the car (field → source), which the
car page shows as a mark on the value:

- `providers/evdb.py` reads EV Database's UK index once a night: one card per
  variant with the measured real range, Wh/mi, kerb weight, 0-62, useable battery,
  average rapid-charge power over 10-80%, towing, boot, price, and whether a heat
  pump or vehicle-to-load is offered. Variants are EV Database's own, so a car takes
  the variant of its model (longest catalogue name that starts the variant's) whose
  useable battery fits its gross one; two variants and no battery to choose by is no
  match, never a guess.
- A hand-curated car's tri-state fields describe its trim, so the generated
  derivatives of the same make, model and trim name take them where their own spec
  said nothing (the Inster 02's cabin socket in the Tech Pack reaches every
  `02 · …` derivative).

A field the car already carries is never overwritten.

## Sightings: every route, every source, over time

`model/sightings.py` is the one fact behind the Trends page and the car page's
history: a *sighting* is a price one source showed for one subject over the span
of days it stayed the same. Subjects are derivatives (an offer on a car) or, for
used stock, the model and registration year. Routes are `cash`, `pcp`, `pch` and
`used`; sources are a dimension of their own (`SOURCES` maps a provider to one, so
Carwow's deal, paste and used providers are one source). Storage stays two tables
(`offer_observations`, and `used_observations` as spans of a listing's asking
price, closed when it goes), but the model sees one list of `Sighting` records.

`cost` puts a sighting on the common footing of `deal_math` with the used market
read *as of a date*: `residual_at` answers "what did the model's cars of that year
ask on that day" from the used sightings themselves, counting a car once across
sites; `floor_gfv_at` the GFV a lender guaranteed that day. History is costed as
of each sighting's first day, so a June PCP is costed on June's evidence (none
before 6 October 2026, so `residual_source` says so); what things cost now is the
same function as of today. `series` groups costed sightings by subject, route and
source (an offer as flat spans; a model's used stock as the cheapest example day by
day); `residual_series` samples the evidence monthly; `current` picks the cheapest
per route and source as of today, and `deal_summary.routes` carries it onto every
car as the one cost model the app reads (`costs.ts` no longer computes anything).

`pipeline/services/series.py` only loads rows and hands them to the model; the
exporter writes `series.json` and `residuals.json`. `data/history/used_observations.jsonl`
replays the spans; stock recorded before spans existed gets one span from its
first to last sighting (`gold.backfill_used_spans`).

## Finance maths lives in the pipeline

`model/deal_math.py` normalises PCP, PCH and cash deals: solves missing monthlies from APR, credit
and GFV; back-solves the implied APR as a check on the stated one; computes paid-if-handed-back,
paid-if-bought, cost of credit, effective monthly, and, against the lowest cash price captured
for the same car, the acquisition penalty, funding premium and effective annual rate. It runs once
at export time and the results ride in `deals[].metrics`, so the browser has no finance code to
drift. Conventions: payments at months 1..n, balloon at n+1, APR as an effective annual rate.
`tests/test_deal_math.py` pins it to the real Carwow quotes.

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

## Filters in the app

`web/src/lib/filters.ts` holds one filter set (scope, make, model, variant text, model
year) in the URL query; `FilterBar` renders it and every list page applies `carMatches`,
`offerMatches` or `specMatches`. Scope is `""` (the hand-curated shortlist) or `all`
(every EV: the generated cars too); it is not a narrowing, so `clear` keeps it and an
empty result offers the switch. Model matching is forgiving ("Kona" matches "Kona
Electric"); the year is a car's model year or a Carwow derivative version's year. The
Pick page shows 48 cards at a time and Trends 36 charts, with "show more" buttons, since
every EV is ~1,500 derivatives; Specs shows the first 60 columns until a filter narrows it.

## Browser-side database

`web/src/lib/db.ts` opens `CarResearchDB` (Dexie):

- **public** `cars`, `deals`, `meta` — cleared and bulk-loaded from the snapshot whenever
  `manifest.generated_at` differs from the stored one. Seeding is memoised per session; a reload
  re-checks only the manifest.
- **private** `shortlist` — the user's picks. Never leaves the browser.

Pages use react-query hooks (`lib/hooks.ts`) over Dexie queries. The snapshot banner shows the
loaded generation and can re-check Pages for a newer one.

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

`.github/workflows/scrape.yml` runs nightly (and on dispatch): `pipeline refresh` with the live
providers, commits `data/history`, `web/public/data` and `docs/deal-comparison.md` if anything
changed, then dispatches the Pages deploy (a push made with the workflow token does not trigger
other workflows by itself). `pipeline-ci.yml` runs `refresh --offline`: seed, pastes and the
replayed history, so the freshness diff is deterministic and needs no network.

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
- **Finance maths in Python at export, not in the browser.** One implementation, pinned by tests.
- **Public data in IndexedDB as well as private.** Matches the "dump it all into a local DB on load"
  pattern; filtering and sorting stay instant and the app works offline after first load.
