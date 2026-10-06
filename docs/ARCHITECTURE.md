# Architecture

The same shape as `etf-tool` and `bolthole`, scaled to a dataset of tens of cars and
hundreds of deals: **scrape → resolve → app**, with only the *app* layer shipped to the
browser. No Postgres, no worker, no server mode. The data is tiny, so it is committed
on `main` and GitHub Pages serves it.

```
providers (discover → fetch → parse)       pipeline/providers/*      Python, stdlib
   manual_seed   data/seed/*.json           cars, requirements, trim map, hand-captured offers
   carwow_paste  data/pastes/carwow/*.txt   Carwow offer pages copied out of a logged-in browser
   <scrapers>    (to come)                  manufacturer / dealer / broker / aggregator pages
        │  Bronze  artifacts            every fetched body, sha256-addressed, supersede chain
        │  Silver  source_rows          one row per parsed record, in the source's vocabulary
        │  Gold    cars                 canonical trims (hand-curated)
        │          trim_map             (site, trim-as-printed) → car_id; misses recorded as 'unmapped'
        │          offer_observations   one row per offer key per sighting (present / gone)
        ▼          requirements
SQLite  data/car-research.sqlite            gitignored: a dev-machine artifact
        │
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
is resolved through `trim_map`; the key is the trim text normalised by the provider. A miss
leaves the record in Silver, records an `unmapped` row, and counts on the run. `python -m
pipeline trims` lists them (and fails CI); add the mapping to `data/seed/trim_map.json` and
re-run. Nothing is ever attached to a guessed car.

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

## Snapshot contract (schema_version 2)

| File | Shape |
| --- | --- |
| `manifest.json` | `{schema_version, generated_at, counts:{cars,offers,observations,cash_benchmarks,unmapped_trims}, runs:[…]}` |
| `cars.json` | car records plus `requirement_check` `{passes, failures[], unknown[]}` and `deal_summary` (best current cash / PCP / PCH with the age of each) |
| `offers.json` | latest observation of each offer plus `metrics` (from `model/deal_math.py`) and `freshness` (state, stale, age, first/last seen, history) |
| `requirements.json` | the requirements document verbatim |
| `data.json` | providers, recent runs, unmapped trims, offer-state counts: the SPA's Data page |

`generated_at` can be pinned (`--generated-at`) so CI can rebuild the snapshot and diff it
against the committed one deterministically.

Bump `SCHEMA_VERSION` in `pipeline/services/snapshot.py` and `SUPPORTED_SCHEMA_VERSION` in
`web/src/lib/snapshot.ts` together on any incompatible change; the banner warns on skew.

Files are written with `sort_keys` and `indent=1` so git diffs of the data are readable. Every
commit of `web/public/data` is a dated market snapshot, which is the price history.

## Finance maths lives in the pipeline

`model/deal_math.py` normalises PCP, PCH and cash deals: solves missing monthlies from APR, credit
and GFV; back-solves the implied APR as a check on the stated one; computes paid-if-handed-back,
paid-if-bought, cost of credit, effective monthly, and, against the lowest cash price captured
for the same car, the acquisition penalty, funding premium and effective annual rate. It runs once
at export time and the results ride in `deals[].metrics`, so the browser has no finance code to
drift. Conventions: payments at months 1..n, balloon at n+1, APR as an effective annual rate.
`tests/test_deal_math.py` pins it to the real Carwow quotes.

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

One-time repo setting: **Settings → Pages → Source = "GitHub Actions"**. Until then the deploy
step fails.

If the snapshot ever grows past a few MB (per-listing price history, scraped used-car markets),
move it off `main` onto a squashed orphan `data` branch exactly as `etf-tool/scripts/publish-data.sh`
does, and add the second checkout step to the deploy workflow.

## Local development

```
make snapshot        # python -m pipeline refresh --out web/public/data
make test            # python unittest + web lint/typecheck/vitest
make web-dev         # next dev on :3001, reads web/public/data
make web-build       # static export to web/out
python -m pipeline status | deal-table | run <provider> [--capability …] [--target …]
```

Python ≥ 3.11, stdlib only so far. Node 22.

## Adding a provider (scraper)

1. `pipeline/providers/<name>.py`: write `discover`, `fetch`, `parse`; wrap fetch with delay /
   retry middleware when it exists; declare `Capability(kinds=…)` and `Provider`.
2. Register it in `pipeline/providers/__init__.py` (after `manual_seed`, which writes the cars
   and trim map everything else resolves against).
3. Emit `ParsedRecord(kind="offer", key=<offer key>, row=…)` with `offer_key`, `observed_at`,
   `present`, `finance_type`, `status`, the price fields in the seed schema, and either `car_id`
   or `car_ref: {source, key, label}` for the trim map to resolve.
4. `python -m pipeline run <name>`, then `python -m pipeline trims` to see what needs mapping,
   then `make snapshot`. The deal maths, freshness and requirement checks apply automatically.
5. `carwow_paste` is the template: a file-backed provider with a pure `parse_page()` that the
   tests exercise against real captured pages.

Candidate first providers, in the order they pay off: Carwow dealer-offer pages (full PCP
representative examples), Cars2buy derivative price lists (cash benchmarks), manufacturer offer
pages (campaign terms), LeaseLoco (PCH).

## Decisions

- **SQLite, not Postgres.** Single user, tiny data, no concurrent writers. Stdlib only.
- **Data committed on `main`.** ~60KB. The orphan-branch machinery is documented above for later.
- **Next.js static export, not Vite.** Mirrors the two most recent reference repos so the layout,
  data client and deploy workflow are familiar. No server mode is built.
- **No Tremor.** Plain Tailwind tables; fewer dependencies, no React 19 / Tailwind 4 friction.
- **Finance maths in Python at export, not in the browser.** One implementation, pinned by tests.
- **Public data in IndexedDB as well as private.** Matches the "dump it all into a local DB on load"
  pattern; filtering and sorting stay instant and the app works offline after first load.
