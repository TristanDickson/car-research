# car-research

A persistent platform for evaluating cars and car deals: which car is right for us, what a car
is intrinsically worth, and what a given deal (PCP, PCH, used, cash) actually costs once the
headline numbers are unpicked.

**Live site:** https://tristandickson.github.io/car-research/ (after the one-time Pages setting,
see *Deploy*).

## Why this exists

Our Ioniq 5 PCP ends on **10 December 2026**. Rather than repeat the "walk into a dealer and
react to the monthly figure" process, this repo:

1. Captures **what we need from a car** as structured, weighted requirements
   (`docs/requirements.md`, `data/seed/requirements.json`).
2. Keeps **every car and every offer** we look at as dated, sourced observations with their
   source page as evidence, and normalises each onto one footing (`model/deal_math.py`).
   An offer not seen for a fortnight goes stale and drops out of the summaries, so "current"
   is a property of the data, not a label.
3. Serves it as a fast **single-page app** on GitHub Pages that loads the whole dataset into the
   browser's IndexedDB and lets us filter, sort and compare (`web/`).
4. Will estimate how **intrinsically good value** a car is: a model of the real base cost to
   build and ship a car from its spec, as a yardstick independent of marketing. Not started.

### The PCP obfuscation problem

Three things move independently and sellers shuffle value between them: the **vehicle price**
(list, dealer discount, government grant), the **finance support** (APR, manufacturer
contribution) and the **GFV** the lender underwrites. A low APR is worthless if the car's price
under that finance is £3-5k above the best cash price elsewhere. A high monthly can be cheap
money with a pessimistic balloon. Examples already in the data:

- Kia EV3 GT-Line S: nominal 3.9% PCP, but **~8.5% effective** against a £37,263 broker cash
  price because the PCP's net vehicle price is £3,692 higher.
- Hyundai Kona Ultimate: Richmond's 2.9% PCP looks like "only £287 more than cash", until a
  £26,966 outright price appears elsewhere and it becomes a **£6,871 premium at ~11%**.
- Hyundai Ioniq 3: cheapest car on the list, worst finance (8.9%, £5,533 interest on £27k).
  Right car, wrong campaign. Buy it cash or wait for a 0-3% campaign.
- Hyundai Ioniq 5: 0% plus £3,000 contribution, yet £652/month because the GFV is now 40% of
  price versus ~55% on our 2022 deal.

So every deal is normalised to **£0 deposit, total cost over the term, and measured against the
best confirmed like-for-like cash price**. The GFV is treated as a floor, not a forecast.
Full rules in `docs/research-notes.md`; the generated comparison is `docs/deal-comparison.md`.

## Where we are (6 Oct 2026)

| Car | Role | Route | Status |
| --- | --- | --- | --- |
| Kia PV5 Elite 7-seat | The car Tristan actually wants: 7 seats, dual powered sliding doors, V2L, Ioniq 5 footprint | PCP 3.9%, ~£699/month £0 down, GFV £18,662 | Over my partner's £400 ceiling. Decide by pricing the delta vs the best ≤£400 car. |
| Hyundai Ioniq 3 Ultimate EV Pack | Rational compact: 300mi, V2L, heat pump, 1,800mm wide | **Cash £27,445.** PCP is 8.9%, don't | Brand new model, no owner corpus. Test drive. |
| Kia EV2 GT-Line S + heat pump | Better-equipped Ioniq 3 rival, 257mi | Cash lead £29,666; lease ~£427 effective | Broker price unconfirmed for December. |
| Hyundai Kona Ultimate | Safe fallback | Richmond PCP £547; **£26,966 outright lead** | Confirm the cash lead is like-for-like. |
| Hyundai Ioniq 5 84kWh Premium | Known quantity, best charging | PCP 0% + £3k, £652/month | Good structure only if we expect equity. |
| Hyundai Inster 02 + Tech Pack | Cheap control | PCP 0% + £3k, £325/month | 4 seats, 223mi. |
| Used 2024 Kia EV6 GT-Line S | Most car per pound | £26,995, 27.8k miles | Still 1,890mm wide. |

Test-drive shortlist: Ioniq 3 Ultimate EV Pack and PV5 Elite 7-seat, Inster as the control.

Those are the hand-curated trims. Behind them sits **every EV on sale in the UK**: the
pipeline reads Carwow's model index each night (~250 electric models from ~50 makes),
scrapes the specification and deals page of each, and generates a car record per
derivative nobody has curated (~1,500), with its equipment, numbers, image, Carwow's cash
price and PCP example, and LeaseLoco's leases where the derivative text can be matched.
In the app every search covers the lot; the curated trims are a filter ("Hand-curated")
and a seeded saved search. See "Every EV on sale" below.

## How it fits together

```
data/seed/*.json ─────────────┐
data/pastes/carwow/*.txt ─────┼─▶ pipeline (Python) ─▶ SQLite ─▶ web/public/data/*.json (committed)
Carwow catalogue ─▶ live      │     bronze/silver/gold           facts only: cars, every price as a span
  scrapers (8 sites) ─────────┘     trim map resolves each       of days, used asking prices, specs
data/history/*.jsonl ─────────┘     source's trim naming, else   push main ─▶ Pages ─▶ SPA
   (committed sighting log, specs   a generated car per         SPA loads the facts into IndexedDB and
    and catalogue, replayed so CI   Carwow derivative           costs every sighting under the reader's
    needs no network)                                            own term and rate (web/src/lib/model)
```

Details, the snapshot contract and the decisions are in `docs/ARCHITECTURE.md`.

## Where the prices come from

| Provider | What it reads | What it yields | Offline? |
| --- | --- | --- | --- |
| `manual_seed` | `data/seed/*.json` | cars, requirements, trim map, 29 hand-captured offers | yes |
| `carwow_paste` | `data/pastes/carwow/*.txt` | dealer PCP quotes from the logged-in Carwow account (4 so far) | yes |
| `carwow_catalog` | carwow.co.uk sitemaps and `<make>/electric` pages | the catalogue: every electric model, which have a deals page and a specifications page | scrapes |
| `carwow_deals` | carwow.co.uk public `<make>/<model>/deals` pages, one per catalogue model | Carwow's best cash price per derivative (CAP id), Kia's separate "PCP finance" price, the model-level representative PCP example | scrapes |
| `hyundai_offers` | hyundai.com/uk per-model offer pages | Hyundai Finance's full national PCP example per model (deposit, contribution, APR, GFV, validity dates) | scrapes |
| `ncd` | new-car-discount.com model listings | broker all-in cash price per derivative | scrapes |
| `leaseloco` | leaseloco.com model pages (the known ones plus a guess per catalogue model; a 404 is skipped) | best personal-lease deal per derivative and profile, VAT added | scrapes |
| `rrg` | rrg-group.com Kia PV5 offers | the dealer's PCP example for the PV5 7-seat | scrapes |
| `carwow_model` | carwow.co.uk `/<make>/<model>`, the public model page | the derivative registry: every derivative by its CAP name with the brackets CAP prints (`[No Heat Pump]`, `[Heat Pump]`, `[7 seat]`), RRP, engine and version date; a stub car for any derivative the specification page omits, and the facts the brackets and their twins carry | scrapes |
| `carwow_options` | quotes.carwow.co.uk's configurator, one page per derivative | every option and pack the derivative can be ordered with, with prices and what each pack bundles; a feature in neither is not available on that derivative | scrapes |
| `carwow_specs` | carwow.co.uk `/specifications` per catalogue model | equipment per trim, numbers per engine, CAP ids with version dates, an image per derivative; a generated car for every derivative nobody curates | scrapes |
| `kia_specs` | kia.com/uk `/specification` per model | grade × feature ticks, numbers per powertrain, seat variants | scrapes |
| `hyundai_specs` | hyundai.com/uk `/models/<model>/downloads.html`, the Tech & Spec guide PDF it links (needs `pdftotext` from poppler-utils, or pypdf) | the maker's own table per trim: ● / - per item, battery-qualified ticks (`● 49kWh only`, a footnote's `N/A on 63kWh`), which batteries each trim is sold with, packs with contents, price and the trims they are offered on | scrapes |
| `hyundai_configurator` | hyundai.com/uk `/models/<model>/configurator.html` and the GraphQL endpoint behind it (no credentials) | what the maker will build at what price: every orderable configuration (Hyundai's FSC) with trim, powertrain, price and the packages in that price; the packages offered on each trim and powertrain; each trim's standard-equipment list. Matched to CAP derivatives by trim, battery and price; the strongest word on what is fitted | scrapes |
| `carwow_used` | quotes.carwow.co.uk used stock per catalogue model | every used example Carwow's partner dealers list: derivative, price, year, mileage, town | scrapes |
| `cinch_used` | cinch's search API, every electric car per make | cinch's own and marketplace stock with the registration, the CAP variant and the fee-inclusive price | scrapes |
| `motorpoint_used` | motorpoint.co.uk's electric listing | the supermarket's nearly-new stock: CAP trim, year, mileage, price, branch, and the list price when new | scrapes |
| `evdb` | ev-database.org/uk, the index page | per variant: real range, efficiency, 0–62, average 10–80% rapid-charge power, useable battery, boot, weight, towing, heat pump and V2L offered; laid over the cars by model and battery at export, each filled field naming its source | scrapes |
| `evdb_cars` | ev-database.org/uk `/car/<id>/<slug>`, each variant's own page, for the variants filed under a catalogue model; 40 a run, paced at 25 s and slowing on a 429 (the site throttles hard), never-read pages first one per model in turn, then any older than 14 days | everything the page prints: length, width (with and without mirrors), height, wheelbase, weights, payload, roof load, towing, boot and frunk, seats and ISOFIX, AC and DC charging (peak, 10–80% average and time), charge port, usable battery, voltage and chemistry, power, torque, top speed, real range by weather and road, Euro NCAP scores, battery warranty, V2L outlets and output. Fills the variant's index card; a body number every current variant of a model agrees on speaks for the model | scrapes |

Every sighting on every route is kept over time, source by source, and exported as
spans. The browser costs them on one footing as of their own day
(`web/src/lib/model/sightings.ts`): each car's history reads those series, and the car's
headline figures are the same model as of today, under the term and savings rate the
reader sets in Settings.

The three used sources are folded per model: the same registration, or the same year and
mileage where a site prints no registration, is one car. The union is the buy-used route
and the residual evidence (what a car of the term's age asks today).

Every scrape is an observation: the body is kept (Bronze), parsed (Silver), resolved to a car
(one of our 19 curated trims through the trim map, else the generated car for that Carwow
derivative) and written as a sighting (Gold). Re-seeing the same price extends the sighting; a
changed price is a new row; a price not seen for 14 days is stale and drops out of the
best-price summaries. Kia's own quote widget currently returns "No quote
available" for every car, so Kia Finance examples are hand-captured for now; Richmond and
cars2buy block automated reads and stay as pastes.

## Every EV on sale

The curated shortlist is 19 trims the household has looked at closely. The alternative
to any of them is the whole UK EV market, so the pipeline covers that too, without a
hand-written model list:

1. `carwow_catalog` reads Carwow's sitemaps (`car_models.xml`, `car_model_deals.xml`,
   `brand_fuel_types.xml`) and each make's `/electric` page, and writes a `models` row per
   `<make>/<model>` with the printed names and whether a deals and a specifications page exist.
   Makes whose whole range is electric (Tesla, Polestar, XPeng …) have no such page and are
   flagged by make; MINI's electric models are listed by slug. ~250 electric models, ~50 makes.
2. `carwow_specs` and `carwow_deals` discover their pages from that table (the old static list
   is the fallback before the first catalogue run); `leaseloco` tries each model's slug and
   skips the ones LeaseLoco does not have.
3. A derivative the trim map does not know gets a **generated car** (`carwow-cap:<cap id>`,
   `auto: true`): from its spec row when the specification page lists it (equipment flags,
   numbers, RRP, image, the derivative's version date as the model year), else a stub from
   what the deals page prints (trim, engine, RRP). A spec-built car replaces a stub; nothing
   replaces a hand-curated car, and a derivative promoted to one later simply maps over it.
   Tri-state fields are `unknown` when the source does not list the item: an equipment list
   without "heat pump" is not proof there is none. A search that asks for an item leaves
   out the cars no source has a value for.
4. Broker rows (LeaseLoco, NCD) name derivatives in their own words; `services/match.py`
   resolves them to the one generated car of that make and model whose kW, kWh and trim
   words agree, and refuses ties (those stay unmapped for a human).

`python -m pipeline models` prints the catalogue with what has been scraped per model. The
Data page shows the same table.

## The true monthly

Cash, PCP, lease and used are compared on one footing. Every payment is discounted at the
savings rate (money not spent on a car earns it), the car's expected value at the end is
credited back (owned outright or used: sold; PCP: the equity above the GFV, never below
zero; lease: nothing), and the present cost is spread as a monthly over the reader's term.
The Pick cards lead with it, the Cars table and every price board rank by it, and the
bracketed figure is the GFV floor (the car worth only what a lender guarantees). The car's
value at the end comes from the used market where the three used sources list enough
examples of that age (the median asking price), else from the best GFV known for the car
grown at the savings rate, else from the flat assumption; each figure says which.

The term, the savings rate, the residual assumption and how deals of other lengths rank
are the reader's, set in Settings and kept in the browser; the pipeline
exports facts and nothing else. Changing them recomputes every figure in the browser
(`web/src/lib/model`, pinned to `model/deal_math.py` by a shared fixture). Deals of other
lengths are costed over the reader's term with the assumption stated beside the real deal:
a longer PCP settled early and the car sold, a shorter one's balloon paid and the car kept,
a lease over its own term; or, by choice, each deal over its own term.

Broker leases and prices land on the right derivative by rules with evidence (see
`docs/ARCHITECTURE.md`, "Resolving broker rows"): the broker's own RRP where it prints
one, the pack named in brackets ('[Heat Pump]', '[Tech Pack]'), the cheapest twin
otherwise; what a rule cannot decide is listed on the Data page as a conflict rather
than guessed, and a bracket that decided also tells the generated car what it has.

## Trends

Every sighting is kept, so prices are a history, not a number: one row per distinct
price with the span of dates it was seen over. The app draws them on three levels:

- **Pick cards**: a 90-day sparkline of the best outright price with "down £x over 30
  days" and how long it has sat at the current price.
- **Car page → Price over time**: outright prices by source and advertised monthly
  payments by offer as step lines through their sightings, with a crosshair that reads
  every line at a date, the list-after-grant line for reference, and the same data as
  a table underneath.
- **Sort by "biggest price fall"** on the Pick and Cars views for the movers.

The nightly scrape adds a point per car per day. Older points come from two places:
the hand-captured offers and Carwow quotes keep their original dates, and `pipeline
backfill` folds dated captures of the scraped pages from the Wayback Machine into the
same history (`.github/workflows/backfill.yml`, dispatched by hand). Coverage there is
sparse and uneven: a probe found roughly one capture every few months for the Carwow
Kona and EV6 pages and Hyundai's Ioniq 5 offer page, next to nothing for the newer
models, and nothing for LeaseLoco or RRG. It gives waypoints (what Carwow's Kona price
was in January, May and August), not a daily line. There is no other public source of
historical UK car prices for these pages; the nightly scrape is the trend.

## Specs: features by make, model, variant and year

Two sources list equipment per variant in machine-readable form, and both are scraped
nightly alongside the prices:

- **Carwow `/specifications`** per model: the standard-equipment list per trim, the
  derivatives available for it as CAP ids with a dated derivative version (the
  model-year marker), RRP and Carwow price, and a render per derivative (the photos on
  the cards come from here until you drop your own into `web/public/images/cars/`).
- **Kia UK `/specification`** per model: grade-by-feature tick tables (✓ standard, OPT
  option) and the numeric tables per powertrain; the PV5 page breaks 5- and 7-seat out.

Every variant lands in `specs` (and `data/history/specs.jsonl`), mapped to one of our
trims where the trim map knows it and kept anyway where it does not. The wording is
normalised into canonical flags (`pipeline/services/features.py`: heat pump, internal
and external V2L, heated seats, 360 camera, powered tailgate, and so on) so the same
question can be asked of both sources. The **Specs** page is a feature-by-variant matrix
with the shared make / model / variant / year filter; the car page's **Equipment** card
shows what the sources list for that exact variant next to the hand-entered fields,
and `spec_check` names any disagreement (today: Carwow lists an interior V2L socket on the
Kona Advance and N Line, which the model-year 27 spec sheet contradicts; ask the dealer).

Hyundai UK has no spec page that can be read without a browser; Carwow covers its models.

## Searches

One search bar drives Pick, Cars, Specs and Offers: make, model, text, year, a min/max on
every number a car carries or costs (the common ones shown, any other added from the
panel's picker: wheel size, cold-weather range, payload, NCAP score …), a chip per
equipment flag, and the sort. It lives in the URL (`?make=Kia&model=EV3&q=gt-line&year=2026`), so a
search is a link and it follows you between pages. A search can be saved under a name and
loaded from the bar; the default one is what those pages open on. Saved searches live in
the browser and are managed in Settings; `data/seed/requirements.json` seeds two ("My
brief": heat pump and cabin socket fitted or available, four or more seats; and
"Hand-curated"). On Cars, every field is a column: **Columns** lists the shown ones in order
(move up, down, or remove) and adds any other from a grouped, searchable list (kept per
browser); the car stays pinned on the left when the table scrolls sideways. One field list
(`web/src/lib/fields.ts`) drives the columns, the bounds and the car page's Spec card, which
shows every field with the source that filled it.

The app works offline once it has loaded: the snapshot is stored in IndexedDB and read
without the network, a newer one is fetched in the background when the site is reachable,
and a service worker (written at build time by `web/scripts/build-sw.mjs`) keeps the app
itself.

## Repo layout

```
pipeline/               Python package: providers, SQLite medallion, snapshot exporter, history, CLI
  providers/            manual_seed, carwow_paste, carwow_catalog (the model index), and the live scrapers (carwow_specs, carwow_deals, hyundai_offers, ncd, leaseloco, rrg, kia_specs, hyundai_specs, hyundai_configurator)
                        http.py (polite fetch: UA, per-host delay, retry) and parse.py (money/pct/text/key helpers)
  services/snapshot.py  Gold → web/public/data: cars, every price as spans (sightings, used spans), specs, catalogue, data page; no costs
  services/autocars.py  a car record from a Carwow spec row (or a deals-page stub) for every derivative nobody curates
  services/match.py     broker derivative text → the one generated car whose kW / kWh / trim words agree
  history.py            offer_observations ⇄ data/history/observations.jsonl, specs ⇄ specs.jsonl, models ⇄ models.jsonl (CI and a fresh clone replay all three)
  services/features.py  equipment wording → canonical flags (heat pump, internal V2L, …) shared by every spec source
model/deal_math.py      PCP / PCH / cash / used normalisation in Python: the oracle behind tests/fixtures/cost_cases.json (model/cost_fixture.py) and the markdown deal table
web/src/lib/model/      the cost model the app runs: dealMath.ts (the port, checked against the fixture), horizon.ts (deals of other lengths over the reader's term), sightings.ts (every route and source over time), recompute.ts (one pass, stored in IndexedDB)
data/seed/              hand-captured cars (19), offers (29), requirements, trim map (50 mapped, the rest ignored on purpose)
data/pastes/            pasted source pages, one file each (carwow: 4, richmond: 2)
data/history/           the committed sighting log, scraped specs and the catalogue, rewritten by every refresh
web/                    Next.js static SPA: pick, compare, cars, car detail (price board, history, equipment), specs, settings (saved searches, budget line, quoting basis), data, offers
  public/data/          the committed snapshot the SPA reads
docs/                   requirements, research notes, architecture, generated deal table,
  transcripts/          raw source conversations (contact details redacted)
tests/                  Python unit tests; tests/fixtures holds one real page per scraper
.github/workflows/      pages-deploy, web-ci, pipeline-ci (offline replay; fails if the snapshot is stale), scrape (nightly), backfill (Wayback, by hand, sharded per provider)
```

## Working on it

```
make snapshot      # run every provider (live scrape) → SQLite → data/history + web/public/data
make snapshot-offline   # same without the network: seed + pastes + replayed history
make test          # python unittest + web lint/typecheck/vitest
make web-dev       # http://localhost:3001
python3 -m pipeline deal-table > docs/deal-comparison.md
python3 -m pipeline trims        # anything scraped that is not yet in the trim map
python3 -m pipeline backfill --since 2025-01-01   # Wayback captures → history (needs a network archive.org will talk to)
```

Python ≥ 3.11 with no third-party packages; Node 22 (`cd web && npm install`).

**Nightly:** `.github/workflows/scrape.yml` runs every provider at 03:17 UTC, commits
`data/history`, `web/public/data` and `docs/deal-comparison.md` when anything changed, and
redeploys the app. A site that changes its layout shows up as a provider with 0 records in the
run and its offers going stale a fortnight later; fix the parser against a fresh fixture.

**To add a Carwow quote:** copy the dealer-offer page text from your logged-in browser into
`data/pastes/carwow/<date>_<dealid>.txt`, first line `# captured_at: 2026-10-07T09:00:00Z`,
then `make snapshot-offline`. If the trim is new, `python3 -m pipeline trims` tells you what to
add to `data/seed/trim_map.json`. Re-pasting the same offer on a later date records a new
sighting (and any price change) rather than overwriting.

**To add any other offer or a car:** edit `data/seed/deals.json` or `cars.json` following the
existing entries (every offer has `captured_at`, `status`, `verification`, a `source`, and prices
net of discount and grant), run `make snapshot-offline`, commit the seed and the regenerated
snapshot together. CI rejects a seed change without its snapshot, and rejects unmapped trims.

**When a scraper meets a new derivative:** `python3 -m pipeline trims` prints it with the label
as the site printed it. Add a row to `data/seed/trim_map.json` with the `car_id` it is, or with
`"status": "ignored"` and a note if it is a derivative we do not track (wrong pack, no heat
pump, 5-seat). Nothing is ever attached to a guessed car.

## Deploy

Push to `main` deploys via `.github/workflows/pages-deploy.yml`. One-time settings in the GitHub
repo: **Settings → Pages → Source = "GitHub Actions"**, and the `github-pages` environment must
allow `main` to deploy. Enabling Pages creates that environment with a branch rule naming whatever
branch was the default at the time, and changing the default branch later does not update it, so
add `main` under Settings → Environments → github-pages → Deployment branches and tags. A deploy
rejected by that rule fails in two seconds with no runner and no logs.

## Data conventions

- **`vehicle_price`** is the net price after dealer discount *and* government grant, before any
  manufacturer finance contribution and before the customer deposit: what you would pay in cash
  from that seller.
- **`amount_of_credit`** = vehicle price minus deposit minus contribution.
- Every offer sighting carries `captured_at`, `status` as the source implied it (live / expired /
  lead / illustrative / derived / campaign / historical) and `verification` (pasted / cited /
  derived / user). The exported `freshness.state` adds `gone` and auto-expires on `valid_to`.
  Anything ChatGPT sourced is *cited* until we re-verify it.
- Cars carry `heat_pump` and `internal_v2l` as standard / pack / option / none / unknown, with
  `packs_required` naming the pack. These two fields drive most trim decisions.

## Context log

- **2026-10-09** Every field a car carries is a column, a bound and a line on the car page,
  from one list (`web/src/lib/fields.ts`): about 70 numbers and texts plus a column per
  equipment flag. Wheel size is new: the configurator's default wheels (one size fitted, the
  others as options) or the size the standard list names. A new source, `evdb_cars`, reads
  EV Database's page for each variant, which prints the dimensions, weights, charging curve,
  NCAP scores and outlets the index card leaves out; Carwow's specification pages never
  print dimensions, so width was known for 17 of ~2,000 cars before. Carwow's top speed and
  consumption, which the old parse left as text, are read. Field provenance moved from
  `cars.json` into the per-car detail file, which halves the cars file.

- **2026-10-08** Saved searches replace the Requirements page, the stars and the
  Shortlist / Every EV switch. A search (the bar's state, in the URL) can be saved under a
  name; the default one is what Pick, Cars and Specs open on, and the search then follows
  you between them. The hard rules, preferences and wants editors are gone (preferences and
  wants never did anything); Settings keeps the budget line and the quoting basis. The card's
  pack line now names the packs behind the equipment the search asks for. Cars gains a
  column chooser (show, hide, reorder; kept per browser) with the car pinned on the left for
  a phone held sideways, and turning circle joins the ranges. The app now works offline: the
  stored snapshot is used without waiting on the network, a newer one is fetched in the
  background, and a service worker keeps the built app.
- **2026-10-08** Hyundai's own configurator settles the Inster. `hyundai_configurator`
  reads the GraphQL endpoint behind hyundai.com/uk's build-and-price pages: every orderable
  configuration with its price and the packages in that price. It says the heat pump is a
  £760 package on the 02 49 kWh and Cross and not sold on the 01 at all, which is exactly
  what CAP's `[No Heat Pump]` names say and the opposite of the PDF table's tick; the four
  disagreements resolve to none or "pack £760", and what a stronger source sets aside stays
  on the car as `overruled`. Configurations match CAP derivatives by trim, battery and price
  (23 of 51 across the five models; the Inster in full), and read at a new `configured`
  rank above the brackets and the makers' tables. Brokers reprinting a CAP name are one
  claim with its sightings, not three.
- **2026-10-08** The makers' own tables rank with CAP's brackets. `hyundai_specs` reads
  Hyundai UK's Tech & Spec guide PDF per model (● / - per trim, `● 49kWh only`, footnotes,
  the batteries each trim is sold with, packs with prices); it and `kia_specs` feed the claim
  store as kind `maker`, the same strength as a `[No Heat Pump]` bracket, so where the two
  differ the car shows both sides instead of one quietly winning (the MY27 Inster: CAP names
  the 01, 02 49 kWh and Cross `[No Heat Pump]`; Hyundai's table ticks them). A tick that
  holds for one battery only speaks at a new trim-and-battery level. A maker's `-` is not
  fitted as standard: a pack or option offered on the trim upgrades it (the Kona Advance's
  heated seats are its £600 Comfort Pack). Ventilated brake discs and tinted windscreens no
  longer read as ventilated seats and privacy glass.
- **2026-10-08** One fact store for every car field (`pipeline/services/claims.py`): every
  source emits claims about a derivative, a trim, an engine, a model, an EV Database
  variant or a pack; a derivative inherits by level and the packs it includes or is
  offered; one precedence order per field class decides, a disagreement stays unknown with
  both sides kept, and every field names the claim it came from. Carwow's configurator
  page per derivative joins as a source (options and packs with prices). The brief names
  the packs a car needs and what they cost. The per-field overlays are gone.
- **2026-10-08** The derivative registry: Carwow's public model page names every
  derivative as CAP does, brackets included, so `[No Heat Pump]` versions and their
  standard twins are told apart, derivatives the specification page omits get a stub
  car, and the trim description stands in where the name says nothing. In the app
  every figure is as of today (a price confirmed last night holds until seen gone or
  stale), a longer lease is costed on the rentals within the reader's term, and a
  progress bar shows the snapshot loading and the figures being recomputed.
- **2026-10-08** The cost model moved into the browser. The pipeline exports facts only
  (every price as a span of days, every used asking price, the cars); the app costs every
  sighting under the reader's own term, savings rate and residual assumption, once per
  change, and stores the results in IndexedDB. Deals of different lengths are costed over
  the reader's term with the assumption stated beside the deal as printed. The Python
  arithmetic stays as the oracle behind a shared fixture.

- **2026-10-06** Specs: Carwow specification pages and Kia UK specification tables scraped
  per variant, normalised to canonical feature flags, shown as a Specs matrix and an
  Equipment card with a hand-versus-source check; images per derivative; one URL-synced
  make / model / variant / year filter across every page.
- **2026-10-06** Trends: sparklines on the Pick cards, price-over-time charts on the car
  page, a Trends page with movers and small multiples. Sighting merge generalised so
  backfilled (older) captures extend, start or split spans correctly. Wayback Machine
  backfill as a capability on every live provider plus a dispatchable workflow.
- **2026-10-06** Live scrapers: Carwow public deals pages, Hyundai UK offer pages, New Car
  Discount, LeaseLoco and RRG, each pinned to a real captured page in `tests/fixtures`. Sightings
  are logged to `data/history/observations.jsonl` and replayed so CI and fresh clones need no
  network. Nightly scrape workflow. 80 offers across 19 trims after the first live run; the trim
  map carries 50 mapped derivatives and ~150 deliberately ignored ones.
- **2026-10-06** Offers became observations: offer keys, sighting history, freshness (stale after
  14 days, gone, auto-expiry), a trim map with an unmapped queue, and a Carwow paste provider
  with the four real pages from the transcript as fixtures. SPA gained Offers and Data pages.

- **2026-10-06** Built the platform: pipeline (SQLite medallion, snapshot export), Next.js SPA
  with IndexedDB, Pages deploy and CI. Imported the 4-6 Oct ChatGPT conversation into
  `docs/transcripts/`, distilled requirements and research notes, captured 19 cars and 33 deals.
- **2026-10-06** Project started. Current car is a Hyundai Ioniq 5 on a 36-month 0% PCP,
  £0 deposit, ~£540/month, ending 10 Dec 2026.

## Next steps

1. Confirm the cash leads are like-for-like and available for December using the enquiry
   script in `docs/research-notes.md`; the scraped NCD and Carwow prices are leads, not quotes.
2. Get the Ioniq 3 Premium EV Pack GFV so a ~£400 PCP alternative can be priced properly.
3. Kia Finance examples: the `kiaofferscalculator.co.uk` quote API answers "No quote available"
   for every parameter set today (the live widget too); revisit, else keep hand-capturing.
4. Richmond paste parser (two pages saved under `data/pastes/richmond/`), and a used-market
   provider once a source that allows automated reads is found.
5. Intrinsic-value model: start with £/kWh, £/mile of range and £/kg against segment, then
   residual-value evidence from used listings.
