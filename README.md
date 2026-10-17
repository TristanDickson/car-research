# car-research

A generic app for exploring UK electric car prices and planning an upgrade from any starting car:
what a car is worth, and what a given deal (PCP, PCH, used, cash) actually costs once the
headline numbers are unpicked.

**Live site:** https://tristandickson.github.io/car-research/

## Why this exists

The household using it has a PCP that ends on 10 December 2026, and rather than walk into a
dealer and react to the monthly figure, wanted every deal on one footing. Nothing in the app is
built around their car or requirements (`docs/DECISIONS.md`, "The app is generic"). The app's
default settings, the quoting basis and the starting saved searches, are
`data/seed/requirements.json`; each reader changes their own copy in Settings.

Three things move independently in a deal, and sellers shuffle value between them: the
**vehicle price** (list, dealer discount, government grant), the **finance support** (APR,
manufacturer contribution) and the **GFV** (the guaranteed future value the lender
underwrites). A low APR is worthless if the car's price under that finance is £3-5k above the
best cash price elsewhere; a high monthly can be cheap money with a pessimistic balloon. So every
deal is costed with nothing down, over the reader's own term, against the best confirmed
like-for-like cash price, with the GFV treated as a floor rather than a forecast
(`docs/ARCHITECTURE.md`, "Costing").

## How it fits together

The design is the owner's (`docs/DECISIONS.md`, after their project bolthole): only the raw
responses are permanent; everything the app reads is re-derived from them by a build that runs
from scratch every time; nothing is typed in by hand but the default settings. Live since 10 Oct 2026;
how it works is `docs/ARCHITECTURE.md`, and the next step `docs/ARCHITECTURE-NEXT.md`.

```
live scrapers ─────────▶ RAW STORE on the owner's laptop (D:\car-research-raw, outside git)
(pipeline/providers)      every response, gzipped by sha256, an append-only index of every fetch,
                          plus every committed version of the old data/history, as the source `history`
                                        │
data/seed/requirements.json ────────────┤  build, from scratch every run (pipeline/build.py):
  (the default settings)                │  parse every page → what each source said → one derivative
                                        │  per CAP id → match every record at once
                                        ▼  → prices folded into spans
                              SQLite (disposable) ─▶ web/public/data/*.json (committed) ─▶ Pages ─▶ SPA
                                                     facts only: cars, every price as a span of days,
                                                     used asking prices, specs; the browser costs them
```

- **Sources.** Carwow (its catalogue of every electric model on sale, specifications, deals,
  configurator and used stock), the brokers and dealers (New Car Discount, LeaseLoco, RRG, Lloyd
  and Halliwell Jones, cinch, Motorpoint), the makers (Kia's specification tables, Hyundai's
  guides, configurator and offers), EV Database, ADAC, What Car?, the UK and US recall registers,
  and Parkers. What each prints, what is read and what is left: `docs/SOURCES.md`.
- **Cars.** Every CAP derivative a page names is a car (CAP HPI's id for one exact version of a
  car); 1,983 in a build of 16 Oct, 1,604 of them on sale.
  Every field a car carries comes from one claim store that weighs what each source says
  (`docs/ARCHITECTURE.md`, "Transform").
- **Costs.** Cash, PCP, lease and used are compared on one footing, the true monthly: every
  payment discounted at the reader's savings rate, the car's expected value at the end credited
  back, and the present cost spread over the reader's term. The term, the rate and the residual
  assumption are the reader's, set in Settings and kept in the browser, which costs every price
  sighting itself (`docs/ARCHITECTURE.md`, "Costing").
- **The app.** One search drives the Pick cards, the Cars table and the Specs grid; it lives in
  the URL and can be saved under a name. The app works offline once loaded.

The flows and the data model are in `docs/ARCHITECTURE.md`.

## Repo layout

```
pipeline/               Python package: raw store, scraper, build, snapshot exporter, CLI
  raw.py                the raw store: every fetched response by sha256, an append-only index, logs
  history.py            the committed data/history as a source: copied into the store, read without its matches
  runner.py             scrape one provider into the raw store (keeps every response, failures and parts too)
  build.py              everything derived, from scratch: parse, derivatives, matching, spans, cars
  gold.py               the database writers, order-tolerant, creating no cars
  stages.py             what each stage did night by night, for the Data page
  providers/            one module per source, registered in providers/__init__.py in scrape order;
                        http.py (polite fetch), politeness.py (resting refusing sites), parse.py (helpers),
                        used_match.py (used listings to catalogue models), wayback.py (the backfill)
  services/claims.py    every car field from one claim store: what each source says at its level, one precedence order, provenance
  services/resolve.py   broker derivative text → the derivative it names (rules, evidence, conflicts)
  services/match.py     the gates: kW / kWh / trim words must agree
  services/facts.py     EV Database variants filed under models and picked per car by battery
  services/autocars.py  a derivative in the form the matcher and the app read, from a spec row or a registry/deals line
  services/snapshot.py  the database → web/public/data: cars, every price as spans, specs, catalogue, data page; no costs
  services/features.py  equipment wording → canonical flags (heat pump, internal V2L, …) shared by every spec source
model/deal_math.py      PCP / PCH / cash / used arithmetic in Python: the oracle behind tests/fixtures/cost_cases.json (model/cost_fixture.py) and the markdown deal table
web/src/lib/model/      the cost model the app runs: dealMath.ts (the port, checked against the fixture), horizon.ts (deals of other lengths over the reader's term), sightings.ts (every route and source over time), breakeven.ts, recompute.ts (one pass, stored in IndexedDB)
data/seed/              requirements.json: the default settings (the quoting basis and the starting saved searches)
scripts/                the nightly job (nightly.sh), its scheduler entry (install-nightly.sh: Task Scheduler or cron), Chrome's download for DVSA (fetch-with-chrome.mjs), a snapshot comparison
web/                    Next.js static SPA: pick, compare, cars, car page, specs, offers, data, settings (saved searches, the car to compare with, budget line, quoting basis)
  src/lib/fields.ts     the one list of car fields: Cars table columns, search bounds, the car page's Spec card
  src/lib/query.ts      the search (URL state), facets, ranges, saved-search descriptions; src/lib/db.ts the IndexedDB store
  public/data/          the committed snapshot the SPA reads
docs/                   the owner's decisions, architecture, the rebuild, sources, requirements, research notes, generated deal table
tests/                  Python unit tests; tests/fixtures holds one real page per scraper; tests/helpers.Raws builds over them
.github/workflows/      pages-deploy, web-ci, pipeline-ci (unit tests and a build from the default settings alone)
```

## Working on it

```
python -m pipeline build        # from scratch: raws + the committed history + the default settings → DB → web/public/data
python -m pipeline nightly      # new committed history into the store, scrape everything, build, snapshot, deal table
python -m pipeline scrape --only carwow_deals,ncd   # some live sources into the raw store
python -m pipeline records <key> [--kind spec] [--show]   # what the sources said about a key, and when
python -m pipeline raw-status   # what the raw store holds, by source
python -m pipeline trims        # records the rules could not place
python -m pipeline models       # the catalogue, with what has been scraped per model (the Data page shows the same)
python -m pipeline status | deal-table | raw-migrate
python -m pipeline backfill --since 2025-01-01   # Wayback captures into the raw store; then build
scripts/nightly.sh --push --build-only --code HEAD   # put a code change on the site now: build it from the raws held, push it with its snapshot
make test                       # python unittest + web lint/typecheck/vitest
make web-dev                    # http://localhost:3001
make web-build                  # static export to web/out
```

Python ≥ 3.11 with no third-party packages; Node 22 (`cd web && npm install`). On the owner's
laptop: `uv run --python 3.12 python -m pipeline …` (the system Python is 3.9) and
`PYTHONUTF8=1` (Windows reads files as cp1252 otherwise). `CAR_RESEARCH_RAW` names the raw store
(`D:\car-research-raw` there); without the owner's laptop, a clone can still `raw-migrate` the
committed history into an empty store and build from that. `hyundai_specs` reads Hyundai's PDF
guides with poppler's `pdftotext` (`CAR_RESEARCH_PDFTOTEXT` names it if it is not on the PATH;
on the laptop it is under `%USERPROFILE%\tools`). xpdf's is skipped, and pypdf, the fallback,
loses lines of the packs' contents; the reader is part of the parse cache's key, and without
either the guides are still kept and parse at the next build that has one. The database
(`data/car-research.sqlite`, `CAR_RESEARCH_DB`) and the parse cache (`data/parse-cache.sqlite`,
`CAR_RESEARCH_PARSE_CACHE`) are disposable.

A night's scrape fetches about 2,000 pages at a polite pace (1,282 on 15 Oct; since then Parkers
adds up to 400, and the configurator read 250 on 16 Oct where it had read 3). Refusals are expected, not failures: a
refusing site is not asked again that night, rests for a growing number of nights, and comes back
with a few pages, doubling each clean night (`pipeline/providers/politeness.py`); the build keeps
what earlier pages said meanwhile.

**Nightly:** the laptop's scheduled job (`scripts/nightly.sh`, 03:17) scrapes, builds, and
commits `web/public/data` to `main`, which redeploys the app. Its
log is `D:\car-research-raw\logs\nightly\<date>.log`. A site that changes its layout shows up as
a provider with 0 records and its offers going stale a fortnight later; fix the parser against a
fresh fixture, and the next build reads every stored page again with it.

Every car and every offer comes from a page the pipeline fetched. A source worth reading is a new
reader in `pipeline/providers/`; nothing is pasted or typed in.

**When a scraper meets a name the rules cannot place:** `python -m pipeline trims` prints it
with the label as the site printed it. Nothing is ever attached to a guessed car; the fix is a
better rule (`BOARD.md`, T3).

## Data conventions

- **`vehicle_price`** is the net price after dealer discount *and* government grant, before any
  manufacturer finance contribution and before the customer deposit: what you would pay in cash
  from that seller.
- **`amount_of_credit`** = vehicle price minus deposit minus contribution.
- Every offer sighting carries `captured_at` and `status` as the source implied it (live /
  expired / lead / illustrative / derived / campaign / historical). The exported
  `freshness.state` adds `gone` and auto-expires on `valid_to`.

## Next steps

The open work, and the decisions still owed, are tickets on `BOARD.md`. What the pages print and
we do not read yet is at the end of `docs/SOURCES.md`.
